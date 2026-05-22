from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import NETWORK_DEFAULT_COLORS, plot_network_hydrograph
from core.io import load_params, load_timeseries
from core.models import run_network_simulation

st.set_page_config(page_title="Rede Hidrológica", page_icon="🏔️", layout="wide")
st.title("🏔️ Roteamento em Rede Hidrológica")
st.markdown("Simula a propagação de vazões em uma rede de subcatchments usando **SMAP + Muskingum**.")

PARAMS_PATH = Path("data/example_network_params.csv")
PREC_PATH = Path("data/example_network_prec.csv")
ETP_PATH = Path("data/example_network_etp.csv")

_DT_SECONDS = 86400.0  # SmapD is daily


def _load_network_series(source) -> pd.DataFrame:
    """Load prec or etp file; convert column names to int basin IDs when possible."""
    df = load_timeseries(source)
    try:
        df.columns = pd.Index([int(float(c)) for c in df.columns])
    except (ValueError, TypeError):
        pass
    return df


def _map_series_columns(
    df: pd.DataFrame, expected_ids: list, label: str, key_prefix: str
) -> pd.DataFrame:
    """Show mapping UI if df columns don't match expected int basin IDs."""
    expected_set = set(expected_ids)
    current_set = set(df.columns)

    if current_set == expected_set:
        return df

    try:
        converted = {int(float(c)): c for c in df.columns}
        if set(converted.keys()) == expected_set:
            return df.rename(columns={v: k for k, v in converted.items()})
    except (ValueError, TypeError):
        pass

    available = [str(c) for c in df.columns]
    unmatched = [eid for eid in expected_ids if eid not in current_set]
    st.warning(
        f"Colunas de {label} não correspondem aos IDs dos subcatchments. "
        "Selecione a coluna para cada bacia:"
    )
    rename_map: dict = {}
    used: set = set()
    for eid in unmatched:
        opts = [c for c in available if c not in used]
        chosen = st.selectbox(
            f"Bacia **{eid}** — coluna de {label}:", options=opts, key=f"{key_prefix}_map_{eid}"
        )
        rename_map[chosen] = eid
        used.add(chosen)
    return df.rename(columns=rename_map)


# --- Checkbox first; uploaders only shown when example is OFF ---
if "use_network_example" not in st.session_state:
    st.session_state["use_network_example"] = True

use_example = st.checkbox("Usar dados de exemplo", key="use_network_example")

if use_example:
    params_df = load_params(PARAMS_PATH)
    prec_df = _load_network_series(PREC_PATH)
    etp_df = _load_network_series(ETP_PATH)
    st.info("Usando rede de exemplo com 2 subcatchments.")
else:
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    with col_dl1:
        st.download_button(
            "📥 Template — parâmetros",
            data=PARAMS_PATH.read_bytes(),
            file_name="template_rede_params.csv",
            mime="text/csv",
        )
        st.caption("Colunas: `id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x, downstream_id`")
    with col_dl2:
        st.download_button(
            "📥 Template — precipitação",
            data=PREC_PATH.read_bytes(),
            file_name="template_rede_prec.csv",
            mime="text/csv",
        )
        st.caption("Colunas: `date, id1, id2, …` — uma coluna de chuva por subcatchment.")
    with col_dl3:
        st.download_button(
            "📥 Template — ETP",
            data=ETP_PATH.read_bytes(),
            file_name="template_rede_etp.csv",
            mime="text/csv",
        )
        st.caption("Colunas: `date, id1, id2, …` — uma coluna de ETP por subcatchment.")

    col1, col2, col3 = st.columns(3)
    with col1:
        params_file = st.file_uploader("Parâmetros da rede", type=["csv", "xlsx"])
    with col2:
        prec_file = st.file_uploader("Precipitação", type=["csv", "xlsx"], key="prec_upload")
    with col3:
        etp_file = st.file_uploader("ETP", type=["csv", "xlsx"], key="etp_upload")

    if not (params_file and prec_file and etp_file):
        st.warning("Carregue os três arquivos (parâmetros, precipitação e ETP) para continuar.")
        st.stop()

    params_df = load_params(params_file)

    if "downstream_id" not in params_df.columns:
        st.warning("Coluna `downstream_id` não encontrada nos parâmetros.")
        ds_col = st.selectbox(
            "Qual coluna representa o subcatchment de jusante (exutório = vazio)?",
            options=list(params_df.columns),
            key="map_downstream_id",
        )
        params_df = params_df.rename(columns={ds_col: "downstream_id"})

    params_df["downstream_id"] = (
        pd.to_numeric(params_df["downstream_id"], errors="coerce")
        .replace(-999, float("nan"))
    )

    prec_df = _load_network_series(prec_file)
    etp_df = _load_network_series(etp_file)

    expected_ids = params_df["id"].astype(int).tolist()
    prec_df = _map_series_columns(prec_df, expected_ids, "precipitação", "prec")
    etp_df = _map_series_columns(etp_df, expected_ids, "ETP", "etp")

    if set(prec_df.columns) != set(etp_df.columns):
        st.error("Os arquivos de precipitação e ETP devem ter os mesmos IDs de subcatchment após o mapeamento.")
        st.stop()

st.subheader("Parâmetros dos Subcatchments")
st.dataframe(params_df, use_container_width=True)

basin_ids = params_df["id"].astype(int).tolist()
if set(st.session_state.get("basin_names", {}).keys()) != set(basin_ids):
    st.session_state["basin_names"] = {bid: str(bid) for bid in basin_ids}

if st.button("▶ Executar roteamento", type="primary"):
    with st.spinner("Simulando rede hidrológica..."):
        result_df = run_network_simulation(params_df, prec_df, etp_df)
        st.session_state["network_result"] = result_df
        st.session_state["network_params"] = params_df.copy()

if "network_result" in st.session_state:
    result_df = st.session_state["network_result"]
    params_stored: pd.DataFrame = st.session_state.get("network_params", pd.DataFrame())

    name_map: dict = st.session_state.get("basin_names", {})
    display_df = result_df.rename(columns=name_map)

    # Identify outlet basins (downstream_id is NaN)
    if "downstream_id" in params_stored.columns:
        outlet_ids = (
            params_stored.loc[params_stored["downstream_id"].isna(), "id"]
            .astype(int)
            .tolist()
        )
    else:
        outlet_ids = list(result_df.columns)

    outlet_names = [name_map.get(oid, str(oid)) for oid in outlet_ids]
    outlet_cols = [c for c in display_df.columns if c in outlet_names]

    tab_all, tab_out, tab_stats, tab_raw = st.tabs([
        "📈 Todos os Subcatchments",
        "🔵 Exutórios",
        "📊 Estatísticas",
        "📋 Dados Brutos",
    ])

    with tab_all:
        _btn_col1, _btn_col2, _ = st.columns([1, 1, 8])
        with _btn_col1:
            with st.popover("✏️ Nomes"):
                _name_cols = st.columns(min(len(basin_ids), 4))
                for _i, _bid in enumerate(basin_ids):
                    with _name_cols[_i % len(_name_cols)]:
                        _new_name = st.text_input(
                            f"ID {_bid}",
                            value=st.session_state["basin_names"].get(_bid, str(_bid)),
                            key=f"basin_name_{_bid}",
                        )
                        st.session_state["basin_names"][_bid] = _new_name
        colors_all: dict = {}
        with _btn_col2:
            with st.popover("🎨 Cores"):
                picker_cols = st.columns(min(len(display_df.columns), 5))
                for i, col in enumerate(display_df.columns):
                    default = NETWORK_DEFAULT_COLORS[i % len(NETWORK_DEFAULT_COLORS)]
                    with picker_cols[i % len(picker_cols)]:
                        colors_all[col] = st.color_picker(
                            f"Bacia {col}", value=default, key=f"color_all_{col}"
                        )
        st.plotly_chart(
            plot_network_hydrograph(display_df, colors=colors_all),
            use_container_width=True,
        )

    with tab_out:
        if outlet_cols:
            colors_out: dict = {}
            with st.popover("🎨 Cores"):
                picker_cols = st.columns(min(len(outlet_cols), 5))
                for i, col in enumerate(outlet_cols):
                    default = NETWORK_DEFAULT_COLORS[i % len(NETWORK_DEFAULT_COLORS)]
                    with picker_cols[i % len(picker_cols)]:
                        colors_out[col] = st.color_picker(
                            f"Bacia {col}", value=default, key=f"color_out_{col}"
                        )
            st.plotly_chart(
                plot_network_hydrograph(
                    display_df[outlet_cols],
                    title="Hidrogramas dos Exutórios",
                    colors=colors_out,
                ),
                use_container_width=True,
            )
        else:
            st.info("Nenhum exutório identificado (todas as bacias têm jusante definida).")

    with tab_stats:
        stats_rows = []
        for col in display_df.columns:
            s = display_df[col]
            stats_rows.append({
                "Bacia": col,
                "Tipo": "Exutório" if col in outlet_names else "Interno",
                "Média (m³/s)": round(float(s.mean()), 3),
                "Pico (m³/s)": round(float(s.max()), 3),
                "Volume (hm³)": round(float(s.sum() * _DT_SECONDS / 1e6), 3),
            })
        stats_df = pd.DataFrame(stats_rows).set_index("Bacia")
        st.dataframe(stats_df, use_container_width=True)
        st.download_button(
            "📥 Baixar estatísticas (CSV)",
            data=stats_df.to_csv().encode(),
            file_name="estatisticas_rede.csv",
            mime="text/csv",
            key="dl_stats",
        )

    with tab_raw:
        st.dataframe(display_df.round(4), use_container_width=True)
        st.download_button(
            "📥 Exportar resultados (CSV)",
            data=display_df.round(4).to_csv().encode(),
            file_name="resultado_rede.csv",
            mime="text/csv",
        )

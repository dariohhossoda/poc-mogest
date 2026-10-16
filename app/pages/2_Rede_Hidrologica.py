from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import (
    BASEMAPS,
    NETWORK_DEFAULT_COLORS,
    plot_network_hydrograph,
    plot_network_map,
)
from core.geo import (
    basin_links,
    load_polygons,
    missing_param_columns,
    polygons_to_params,
)
from core.io import load_params, load_timeseries
from core.models import CUNGE_COLUMNS, run_network_simulation

st.set_page_config(page_title="Rede Hidrológica", page_icon="🏔️", layout="wide")
st.title("🏔️ Roteamento em Rede Hidrológica")
st.markdown(
    "Simula a propagação de vazões em uma rede de subcatchments usando **SMAP** "
    "e **Muskingum** (linear ou Muskingum-Cunge)."
)

PARAMS_PATH = Path("data/example_network_params.csv")
PREC_PATH = Path("data/example_network_prec.csv")
ETP_PATH = Path("data/example_network_etp.csv")
POLYGONS_PATH = Path("data/example_network_basins.geojson")

_DT_SECONDS = 86400.0  # SmapD is daily

_ROUTING_METHODS = {
    "Muskingum linear (k, x)": "muskingum",
    "Muskingum-Cunge (características do trecho)": "muskingum_cunge",
}


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


_MAP_METRICS = (
    "Pico (m³/s)",
    "Média (m³/s)",
    "Volume (hm³)",
    "Fração de montante (%)",
    "Vazão no instante (m³/s)",
)


def _map_values(metric: str, total: pd.DataFrame, natural: pd.DataFrame, when=None):
    if metric.startswith("Pico"):
        return total.max()
    if metric.startswith("Média"):
        return total.mean()
    if metric.startswith("Volume"):
        return total.sum() * _DT_SECONDS / 1e6
    if metric.startswith("Fração"):
        mean_total = total.mean()
        return (1 - natural.mean() / mean_total.where(mean_total > 0)) * 100
    return total.loc[when]


def _clicked_basin(selection, ids: list):
    """Basin id from a plotly map selection (marker customdata or polygon)."""
    for point in (selection or {}).get("selection", {}).get("points", []):
        value = point.get("customdata", point.get("location"))
        if isinstance(value, list):
            value = value[0] if value else None
        if value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
            if value in ids:
                return value
    return None


def _render_map_tab(gdf, total, natural, params, name_map, outlet_ids):
    if gdf is None:
        st.info(
            "Carregue os polígonos das sub-bacias (GeoJSON, shapefile .zip ou "
            "GeoPackage) junto com os dados e execute de novo para ver o mapa."
        )
        return

    ids = [i for i in total.columns if i in set(gdf["id"])]
    if not ids:
        st.warning("Nenhum `id` dos polígonos corresponde às sub-bacias simuladas.")
        return

    c_metric, c_base, c_when = st.columns([2, 1, 3])
    metric = c_metric.selectbox("Métrica", _MAP_METRICS, key="map_metric")
    basemap = BASEMAPS[c_base.selectbox("Fundo", list(BASEMAPS), key="map_basemap")]
    when = None
    if metric.startswith("Vazão no instante"):
        when = c_when.select_slider(
            "Instante",
            options=list(total.index),
            value=total[ids].sum(axis=1).idxmax(),
            format_func=lambda t: pd.Timestamp(t).strftime("%Y-%m-%d"),
            key="map_when",
        )

    labels = {i: name_map.get(i, str(i)) for i in ids}
    clicked = _clicked_basin(st.session_state.get("network_map"), ids)
    if clicked is not None and clicked != st.session_state.get("map_last_click"):
        st.session_state["map_last_click"] = clicked
        st.session_state["map_basin"] = clicked
    if st.session_state.get("map_basin") not in ids:
        st.session_state["map_basin"] = next((o for o in outlet_ids if o in ids), ids[0])

    downstream = params.set_index("id")["downstream_id"]
    col_map, col_hydro = st.columns([3, 2])
    with col_map:
        st.plotly_chart(
            plot_network_map(
                gdf[gdf["id"].isin(ids)],
                _map_values(metric, total[ids], natural[ids], when),
                metric,
                labels,
                outlet_ids,
                basin_links(gdf, downstream),
                basemap=basemap,
                selected=st.session_state["map_basin"],
            ),
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="network_map",
        )
        st.caption(
            "Exutórios em vermelho; linhas ligam cada sub-bacia à de jusante. "
            "Clique numa sub-bacia para ver o hidrograma."
        )
    with col_hydro:
        basin = st.selectbox(
            "Sub-bacia", ids, format_func=lambda i: labels[i], key="map_basin"
        )
        fig = plot_network_hydrograph(
            pd.DataFrame({"Natural": natural[basin], "Total": total[basin]}),
            title=labels[basin],
        )
        fig.for_each_trace(
            lambda t: t.update(name=t.name.removeprefix("Subcatchment "))
        )
        if when is not None:
            fig.add_vline(x=when, line_dash="dot", line_color="#808080")
        fig.update_layout(height=470, legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")


# --- Checkbox first; uploaders only shown when example is OFF ---
if "use_network_example" not in st.session_state:
    st.session_state["use_network_example"] = True

use_example = st.checkbox("Usar dados de exemplo", key="use_network_example")

if use_example:
    params_df = load_params(PARAMS_PATH)
    prec_df = _load_network_series(PREC_PATH)
    etp_df = _load_network_series(ETP_PATH)
    polygons_gdf = load_polygons(POLYGONS_PATH)
    st.info("Usando rede de exemplo com 2 subcatchments.")
else:
    col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)
    with col_dl1:
        st.download_button(
            "📥 Template — parâmetros",
            data=PARAMS_PATH.read_bytes(),
            file_name="template_rede_params.csv",
            mime="text/csv",
        )
        st.caption(
            "Colunas: `id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x, "
            "downstream_id`; `tuin` em % (0–100). Para Muskingum-Cunge: "
            "`length` (m), `q_ref` (m³/s), `manning`, `width` (m), `slope` (m/m)."
        )
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
    with col_dl4:
        st.download_button(
            "📥 Template — polígonos",
            data=POLYGONS_PATH.read_bytes(),
            file_name="template_rede_poligonos.geojson",
            mime="application/geo+json",
        )
        st.caption(
            "Opcional. GeoJSON, shapefile (.zip) ou GeoPackage com `id` "
            "(e `name`). Com todas as colunas de parâmetros, dispensa a tabela."
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        params_file = st.file_uploader("Parâmetros da rede", type=["csv", "xlsx"])
    with col2:
        prec_file = st.file_uploader("Precipitação", type=["csv", "xlsx"], key="prec_upload")
    with col3:
        etp_file = st.file_uploader("ETP", type=["csv", "xlsx"], key="etp_upload")
    with col4:
        polygons_file = st.file_uploader(
            "Polígonos (opcional)",
            type=["geojson", "json", "zip", "gpkg"],
            key="polygons_upload",
        )

    polygons_gdf = None
    if polygons_file:
        try:
            polygons_gdf = load_polygons(polygons_file)
        except Exception as e:  # malformed geodata raises many error types
            st.error(f"Erro ao ler os polígonos: {e}")
            st.stop()

    if params_file:
        params_df = load_params(params_file)
    elif polygons_gdf is not None and not missing_param_columns(polygons_gdf):
        params_df = polygons_to_params(polygons_gdf)
        st.info(
            "Parâmetros lidos dos atributos dos polígonos; `area` vem da geometria "
            "quando o atributo falta."
        )
    elif polygons_gdf is not None:
        st.warning(
            "Os polígonos não têm todos os parâmetros "
            f"({', '.join(missing_param_columns(polygons_gdf))}): carregue também a "
            "tabela de parâmetros."
        )
        st.stop()
    else:
        st.warning("Carregue os parâmetros (tabela ou polígonos com atributos).")
        st.stop()

    if not (prec_file and etp_file):
        st.warning("Carregue a precipitação e a ETP para continuar.")
        st.stop()

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
st.dataframe(params_df, width="stretch")

_tuin = pd.to_numeric(params_df.get("tuin"), errors="coerce")
if _tuin is not None and (_tuin > 0).any() and (_tuin <= 1).all():
    st.warning(
        "`tuin` é lido em porcentagem (0–100). Valores entre 0 e 1 parecem "
        "fração: multiplique por 100 se for o caso."
    )

method_label = st.radio(
    "Método de propagação",
    list(_ROUTING_METHODS),
    horizontal=True,
    help=(
        "Linear: usa `k` e `x` da sub-bacia que recebe a vazão de montante. "
        "Cunge: calcula k e x a partir do trecho (MGB, Collischonn et al., 2020)."
    ),
)
method = _ROUTING_METHODS[method_label]
if method == "muskingum_cunge":
    _missing = [c for c in CUNGE_COLUMNS if c not in params_df.columns]
    if _missing:
        st.error(
            f"Muskingum-Cunge exige as colunas {', '.join(_missing)} na tabela de "
            "parâmetros (trecho que atravessa a sub-bacia de jusante)."
        )
        st.stop()

basin_ids = params_df["id"].astype(int).tolist()
if polygons_gdf is not None:
    _no_polygon = sorted(set(basin_ids) - set(polygons_gdf["id"]))
    if _no_polygon:
        st.warning(f"Sub-bacias sem polígono (fora do mapa): {_no_polygon}")
if set(st.session_state.get("basin_names", {}).keys()) != set(basin_ids):
    _names_source = (
        polygons_gdf.set_index("id")["name"]
        if polygons_gdf is not None and "name" in polygons_gdf.columns
        else params_df.set_index("id")["name"]
        if "name" in params_df.columns
        else pd.Series(dtype=str)
    )
    st.session_state["basin_names"] = {
        bid: str(_names_source.get(bid, bid)) for bid in basin_ids
    }

if st.button("▶ Executar roteamento", type="primary"):
    with st.spinner("Simulando rede hidrológica..."):
        try:
            result_df, natural_df = run_network_simulation(
                params_df, prec_df, etp_df, method=method
            )
        except ValueError as e:
            st.error(f"Erro na simulação da rede: {e}")
            st.stop()
        st.session_state["network_result"] = result_df
        st.session_state["network_natural"] = natural_df
        st.session_state["network_params"] = params_df.copy()
        st.session_state["network_method"] = method_label
        st.session_state["network_polygons"] = polygons_gdf

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

    natural_display = st.session_state["network_natural"].rename(columns=name_map)
    st.caption(f"Método: {st.session_state.get('network_method', '')}")

    tab_all, tab_out, tab_nat, tab_map, tab_stats, tab_raw = st.tabs([
        "📈 Todos os Subcatchments",
        "🔵 Exutórios",
        "🌱 Natural × Total",
        "🗺️ Mapa",
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
            width="stretch",
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
                width="stretch",
            )
        else:
            st.info("Nenhum exutório identificado (todas as bacias têm jusante definida).")

    with tab_nat:
        st.markdown(
            "**Natural**: vazão gerada pelo SMAP na própria sub-bacia. "
            "**Total**: natural + vazão de montante propagada."
        )
        nat_col = st.selectbox("Sub-bacia", list(display_df.columns), key="nat_basin")
        fig_nat = plot_network_hydrograph(
            pd.DataFrame({
                "Natural": natural_display[nat_col],
                "Total": display_df[nat_col],
            }),
            title=f"Vazão natural e total — {nat_col}",
        )
        fig_nat.for_each_trace(
            lambda t: t.update(name=t.name.removeprefix("Subcatchment "))
        )
        st.plotly_chart(fig_nat, width="stretch")

    with tab_map:
        _render_map_tab(
            st.session_state.get("network_polygons"),
            result_df,
            st.session_state["network_natural"],
            params_stored,
            name_map,
            outlet_ids,
        )

    with tab_stats:
        stats_rows = []
        for col in display_df.columns:
            s = display_df[col]
            stats_rows.append({
                "Bacia": col,
                "Tipo": "Exutório" if col in outlet_names else "Interno",
                "Média (m³/s)": round(float(s.mean()), 3),
                "Média natural (m³/s)": round(float(natural_display[col].mean()), 3),
                "Pico (m³/s)": round(float(s.max()), 3),
                "Volume (hm³)": round(float(s.sum() * _DT_SECONDS / 1e6), 3),
            })
        stats_df = pd.DataFrame(stats_rows).set_index("Bacia")
        st.dataframe(stats_df, width="stretch")
        st.download_button(
            "📥 Baixar estatísticas (CSV)",
            data=stats_df.to_csv().encode(),
            file_name="estatisticas_rede.csv",
            mime="text/csv",
            key="dl_stats",
        )

    with tab_raw:
        raw_df = pd.concat(
            {"total": display_df, "natural": natural_display}, axis=1
        ).round(4)
        raw_df.columns = [f"{name}_{kind}" for kind, name in raw_df.columns]
        st.dataframe(raw_df, width="stretch")
        st.download_button(
            "📥 Exportar resultados (CSV)",
            data=raw_df.to_csv().encode(),
            file_name="resultado_rede.csv",
            mime="text/csv",
        )

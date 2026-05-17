from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import plot_network_hydrograph
from core.io import load_params, load_timeseries
from core.models import run_network_simulation

st.set_page_config(page_title="Rede Hidrológica", page_icon="🏔️", layout="wide")
st.title("🏔️ Roteamento em Rede Hidrológica")
st.markdown("Simula a propagação de vazões em uma rede de subcatchments usando **SMAP + Muskingum**.")

PARAMS_PATH = Path("data/example_network_params.csv")
PREC_PATH = Path("data/example_network_prec.csv")
ETP_PATH = Path("data/example_network_etp.csv")


def _load_network_series(source) -> pd.DataFrame:
    """Load a prec or etp file (date index, columns = int basin IDs)."""
    df = load_timeseries(source)
    try:
        df.columns = pd.Index([int(c) for c in df.columns])
    except (ValueError, TypeError):
        pass
    return df


prec_file = st.file_uploader("Precipitação (CSV/XLSX: date, id1, id2…)", type=["csv", "xlsx"], key="prec_upload")
etp_file = st.file_uploader("ETP (CSV/XLSX: date, id1, id2…)", type=["csv", "xlsx"], key="etp_upload")

if prec_file is not None or etp_file is not None:
    st.session_state["use_network_example"] = False
elif "use_network_example" not in st.session_state:
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

    params_col, _ = st.columns([1, 2])
    with params_col:
        params_file = st.file_uploader("Parâmetros da rede", type=["csv", "xlsx"])

    if not (prec_file and etp_file and params_file):
        st.warning("Carregue os três arquivos (parâmetros, precipitação e ETP) para continuar.")
        st.stop()

    params_df = load_params(params_file)
    try:
        prec_df = _load_network_series(prec_file)
        etp_df = _load_network_series(etp_file)
    except Exception as e:
        st.error(f"Erro ao carregar séries temporais: {e}")
        st.stop()

    if set(prec_df.columns) != set(etp_df.columns):
        st.error("Os arquivos de precipitação e ETP devem ter os mesmos IDs de subcatchment.")
        st.stop()

st.subheader("Parâmetros dos Subcatchments")
st.dataframe(params_df, use_container_width=True)

if st.button("▶ Executar roteamento", type="primary"):
    with st.spinner("Simulando rede hidrológica..."):
        result_df = run_network_simulation(params_df, prec_df, etp_df)
        st.session_state["network_result"] = result_df

if "network_result" in st.session_state:
    result_df = st.session_state["network_result"]
    st.subheader("Hidrogramas da Rede")
    st.plotly_chart(plot_network_hydrograph(result_df), use_container_width=True)
    st.subheader("Dados da Simulação")
    st.dataframe(result_df.round(4), use_container_width=True)
    st.download_button(
        "📥 Exportar resultados (CSV)",
        data=result_df.round(4).to_csv().encode(),
        file_name="resultado_rede.csv",
        mime="text/csv",
    )

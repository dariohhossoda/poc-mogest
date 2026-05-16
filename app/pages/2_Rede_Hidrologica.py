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
TS_PATH = Path("data/example_network_timeseries.csv")


def _parse_timeseries(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits unified timeseries (cols: {id}_prec, {id}_etp) into prec_df and etp_df."""
    basin_ids = sorted({int(c.split("_")[0]) for c in df.columns})
    prec_df = df[[f"{i}_prec" for i in basin_ids]].copy()
    prec_df.columns = pd.Index(basin_ids)
    etp_df = df[[f"{i}_etp" for i in basin_ids]].copy()
    etp_df.columns = pd.Index(basin_ids)
    return prec_df, etp_df


use_example = st.checkbox("Usar dados de exemplo", value=True)

if use_example:
    params_df = load_params(PARAMS_PATH)
    ts_df = load_timeseries(TS_PATH)
    prec_df, etp_df = _parse_timeseries(ts_df)
    st.info("Usando rede de exemplo com 2 subcatchments.")
else:
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "📥 Template — parâmetros da rede",
            data=PARAMS_PATH.read_bytes(),
            file_name="template_rede_params.csv",
            mime="text/csv",
        )
        st.caption(
            "Colunas: `id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x, downstream_id`"
        )
    with col_dl2:
        st.download_button(
            "📥 Template — série temporal",
            data=TS_PATH.read_bytes(),
            file_name="template_rede_timeseries.csv",
            mime="text/csv",
        )
        st.caption("Colunas: `date, {id}_prec, {id}_etp` — uma coluna por subcatchment.")

    col1, col2 = st.columns(2)
    with col1:
        params_file = st.file_uploader("Parâmetros da rede (CSV)", type="csv")
    with col2:
        ts_file = st.file_uploader(
            "Série temporal unificada (CSV: date, {id}_prec, {id}_etp…)", type="csv"
        )

    if params_file and ts_file:
        params_df = pd.read_csv(params_file)
        ts_df = load_timeseries(ts_file)
        try:
            prec_df, etp_df = _parse_timeseries(ts_df)
        except KeyError as e:
            st.error(f"Coluna não encontrada na série temporal: {e}")
            st.stop()
    else:
        st.warning("Carregue os dois arquivos para continuar.")
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

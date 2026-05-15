import pandas as pd
import streamlit as st

from app.components.charts import plot_network_hydrograph
from core.io import load_params, load_timeseries
from core.models import run_network_simulation

st.set_page_config(page_title="Rede Hidrológica", page_icon="🏔️", layout="wide")
st.title("🏔️ Roteamento em Rede Hidrológica")
st.markdown("Simula a propagação de vazões em uma rede de subcatchments usando **SMAP + Muskingum**.")

use_example = st.checkbox("Usar dados de exemplo", value=True)

if use_example:
    params_df = load_params("data/example_network_params.csv")
    prec_df = load_timeseries("data/example_network_prec.csv")
    etp_df = load_timeseries("data/example_network_etp.csv")
    prec_df.columns = prec_df.columns.astype(int)
    etp_df.columns = etp_df.columns.astype(int)
    st.info("Usando rede de exemplo com 2 subcatchments.")
else:
    col1, col2, col3 = st.columns(3)
    with col1:
        params_file = st.file_uploader("Parâmetros da rede (CSV)", type="csv")
    with col2:
        prec_file = st.file_uploader("Precipitação por subcatchment (CSV: date, id1, id2…)", type="csv")
    with col3:
        etp_file = st.file_uploader("ETP por subcatchment (CSV: date, id1, id2…)", type="csv")

    if params_file and prec_file and etp_file:
        params_df = pd.read_csv(params_file)
        prec_df = pd.read_csv(prec_file, parse_dates=["date"], index_col="date")
        etp_df = pd.read_csv(etp_file, parse_dates=["date"], index_col="date")
        prec_df.columns = prec_df.columns.astype(int)
        etp_df.columns = etp_df.columns.astype(int)
    else:
        st.warning("Carregue os três arquivos para continuar.")
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

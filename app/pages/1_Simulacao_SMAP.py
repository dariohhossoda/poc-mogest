from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import plot_hydrograph
from core.io import load_timeseries
from core.models import run_smap_daily, run_smap_monthly
from core.postprocess import kge, nash_sutcliffe, peak_flow, runoff_volume

st.set_page_config(page_title="Simulação SMAP", page_icon="🌧️", layout="wide")
st.title("🌧️ Simulação SMAP")

# --- Sidebar ---
st.sidebar.header("Configuração do Modelo")
model_type = st.sidebar.radio("Escala temporal", ["Diário (SmapD)", "Mensal (SmapM)"])

if model_type == "Diário (SmapD)":
    st.sidebar.subheader("Parâmetros SmapD")
    params = {
        "Str": st.sidebar.slider("Str — Cap. máx. solo (mm)", 50.0, 2000.0, 100.0, 10.0),
        "Crec": st.sidebar.slider("Crec — Recarga aquífero", 0.0, 5.0, 0.0, 0.1),
        "Capc": st.sidebar.slider("Capc — Cap. de campo (mm)", 10.0, 200.0, 40.0, 5.0),
        "kkt": st.sidebar.slider("kkt — Recessão superficial (dias)", 1.0, 100.0, 30.0, 1.0),
        "k2t": st.sidebar.slider("k2t — Recessão subterrânea", 0.01, 1.0, 0.2, 0.01),
        "Ai": st.sidebar.slider("Ai — Abstração inicial (mm)", 0.0, 10.0, 2.5, 0.1),
        "Tuin": st.sidebar.slider("Tuin — Umidade inicial (fração)", 0.0, 1.0, 0.0, 0.01),
        "Ebin": st.sidebar.slider("Ebin — Escoamento base inicial (mm)", 0.0, 100.0, 0.0, 1.0),
        "Ad": st.sidebar.number_input("Ad — Área da bacia (km²)", min_value=0.1, value=1.0, step=1.0),
    }
    run_fn = run_smap_daily
    example_path = Path("data/example_daily.csv")
    template_name = "template_smap_diario.csv"
else:
    st.sidebar.subheader("Parâmetros SmapM")
    params = {
        "Str": st.sidebar.slider("Str — Cap. máx. solo (mm)", 100.0, 5000.0, 1000.0, 50.0),
        "Pes": st.sidebar.slider("Pes — Coef. de perda", 0.1, 3.0, 1.0, 0.1),
        "Crec": st.sidebar.slider("Crec — Recarga aquífero", 0.0, 2.0, 0.5, 0.1),
        "kkt": st.sidebar.slider("kkt — Recessão superficial (meses)", 0.5, 10.0, 1.5, 0.1),
        "Tuin": st.sidebar.slider("Tuin — Umidade inicial (fração)", 0.0, 1.0, 0.5, 0.01),
        "Ebin": st.sidebar.slider("Ebin — Escoamento base inicial (mm)", 0.0, 100.0, 0.1, 1.0),
        "Ad": st.sidebar.number_input("Ad — Área da bacia (km²)", min_value=0.1, value=1.0, step=1.0),
    }
    run_fn = run_smap_monthly
    example_path = Path("data/example_monthly.csv")
    template_name = "template_smap_mensal.csv"

# --- Data input ---
st.subheader("Dados de Entrada")
use_example = st.checkbox("Usar dados de exemplo", value=True)

if use_example:
    df = load_timeseries(example_path)
    st.info(f"Usando `{example_path.name}` — {len(df)} registros.")
else:
    st.download_button(
        "📥 Baixar template CSV",
        data=example_path.read_bytes(),
        file_name=template_name,
        mime="text/csv",
    )
    st.caption("Formato esperado: colunas `date`, `prec` (mm), `etp` (mm). Coluna `obs` opcional.")

    data_file = st.file_uploader("Série temporal (CSV: date, prec, etp)", type="csv")
    if data_file:
        df = pd.read_csv(data_file, parse_dates=["date"], index_col="date")
        if not {"prec", "etp"}.issubset(df.columns):
            st.error("O arquivo deve conter as colunas `prec` e `etp`.")
            st.stop()
    else:
        st.warning("Carregue o arquivo CSV para continuar.")
        st.stop()

obs_file = st.file_uploader(
    "Vazão observada — opcional (CSV: date, obs)", type="csv", key="obs"
)
obs: list | None = None
if obs_file:
    obs_df = pd.read_csv(obs_file, parse_dates=["date"], index_col="date")
    obs = obs_df.iloc[:, 0].tolist()

# --- Run ---
if st.button("▶ Executar simulação", type="primary"):
    with st.spinner("Executando modelo SMAP..."):
        sim = run_fn(params, df["prec"].tolist(), df["etp"].tolist())
        st.session_state["sim"] = sim
        st.session_state["sim_index"] = df.index
        st.session_state["sim_obs"] = obs

if "sim" in st.session_state:
    sim = st.session_state["sim"]
    index = st.session_state["sim_index"]
    obs = st.session_state["sim_obs"]

    st.subheader("Hidrograma")
    st.plotly_chart(plot_hydrograph(sim, index=index, obs=obs), use_container_width=True)

    st.subheader("Métricas")
    metrics: dict[str, str] = {
        "Pico de Vazão (m³/s)": f"{peak_flow(sim):.3f}",
        "Volume Escoado (hm³)": f"{runoff_volume(sim):.3f}",
    }
    if obs is not None and len(obs) == len(sim):
        metrics["NSE"] = f"{nash_sutcliffe(obs, sim):.3f}"
        metrics["KGE"] = f"{kge(obs, sim):.3f}"

    for col, (label, value) in zip(st.columns(len(metrics)), metrics.items()):
        col.metric(label, value)

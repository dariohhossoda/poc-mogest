from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import plot_cumulative_volume, plot_hydrograph, plot_monthly_averages
from core.io import load_timeseries
from core.models import (
    calibrate_smap_daily,
    calibrate_smap_monthly,
    run_smap_daily,
    run_smap_monthly,
)
from core.postprocess import annual_stats, kge, nash_sutcliffe, peak_flow, runoff_volume

st.set_page_config(page_title="Simulação SMAP", page_icon="🌧️", layout="wide")
st.title("🌧️ Simulação SMAP")

# --- Sidebar: model type ---
st.sidebar.header("Configuração do Modelo")
model_type = st.sidebar.radio("Escala temporal", ["Diário (SmapD)", "Mensal (SmapM)"])

# --- Parameters: editable table ---
st.subheader("Parâmetros do Modelo")

if model_type == "Diário (SmapD)":
    param_data = {
        "Str":  (100.0,  "Cap. máx. solo (mm)"),
        "Crec": (0.0,    "Recarga aquífero"),
        "Capc": (40.0,   "Cap. de campo (mm)"),
        "kkt":  (30.0,   "Recessão superficial (dias)"),
        "k2t":  (0.2,    "Recessão subterrânea"),
        "Ai":   (2.5,    "Abstração inicial (mm)"),
        "Tuin": (0.0,    "Umidade inicial (fração)"),
        "Ebin": (0.0,    "Escoamento base inicial (mm)"),
        "Ad":   (1.0,    "Área da bacia (km²)"),
    }
    run_fn = run_smap_daily
    calibrate_fn = calibrate_smap_daily
    calib_options = ["Str", "Crec", "Capc", "kkt", "k2t", "Ai"]
    example_path = Path("data/example_daily.csv")
    template_name = "template_smap_diario.csv"
else:
    param_data = {
        "Str":  (1000.0, "Cap. máx. solo (mm)"),
        "Pes":  (1.0,    "Coef. de perda"),
        "Crec": (0.5,    "Recarga aquífero"),
        "kkt":  (1.5,    "Recessão superficial (meses)"),
        "Tuin": (0.5,    "Umidade inicial (fração)"),
        "Ebin": (0.1,    "Escoamento base inicial (mm)"),
        "Ad":   (1.0,    "Área da bacia (km²)"),
    }
    run_fn = run_smap_monthly
    calibrate_fn = calibrate_smap_monthly
    calib_options = ["Str", "Pes", "Crec", "kkt"]
    example_path = Path("data/example_monthly.csv")
    template_name = "template_smap_mensal.csv"

params_key = "params_daily" if model_type.startswith("D") else "params_monthly"
params_df = pd.DataFrame(
    {
        "Valor": {k: v[0] for k, v in param_data.items()},
        "Descrição": {k: v[1] for k, v in param_data.items()},
    }
)
params_df.index.name = "Parâmetro"

edited_df = st.data_editor(
    params_df,
    column_config={
        "Valor": st.column_config.NumberColumn("Valor"),
        "Descrição": st.column_config.TextColumn("Descrição", disabled=True),
    },
    use_container_width=False,
    key=params_key,
)
params = edited_df["Valor"].to_dict()

# --- Data input ---
st.subheader("Dados de Entrada")

st.download_button(
    "📥 Baixar template",
    data=example_path.read_bytes(),
    file_name=template_name,
    mime="text/csv",
)
st.caption("Colunas: `date`, `prec` (mm), `etp` (mm). Aceita CSV (`,` ou `;`) e XLSX.")

data_file = st.file_uploader("Série temporal", type=["csv", "xlsx"])
if data_file is not None:
    st.session_state["use_example"] = False
elif "use_example" not in st.session_state:
    st.session_state["use_example"] = True

use_example = st.checkbox("Usar dados de exemplo", key="use_example")

if use_example:
    df = load_timeseries(example_path)
    st.info(f"Usando `{example_path.name}` — {len(df)} registros.")
else:
    if data_file is None:
        st.warning("Carregue o arquivo para continuar.")
        st.stop()
    df = load_timeseries(data_file)
    if not {"prec", "etp"}.issubset(df.columns):
        st.error("O arquivo deve conter as colunas `prec` e `etp`.")
        st.stop()

obs_file = st.file_uploader(
    "Vazão observada — opcional (CSV/XLSX: date, obs)", type=["csv", "xlsx"], key="obs"
)
obs: list | None = None
if obs_file:
    obs_df = load_timeseries(obs_file)
    obs = obs_df.iloc[:, 0].tolist()

# --- Run ---
if st.button("▶ Executar simulação", type="primary"):
    with st.spinner("Executando modelo SMAP..."):
        prec = df["prec"].tolist()
        etp = df["etp"].tolist()
        sim = run_fn(params, prec, etp)
        st.session_state.update({
            "sim": sim,
            "sim_index": df.index,
            "sim_obs": obs,
            "sim_prec": prec,
            "sim_etp": etp,
            "sim_params": params,
        })
        st.session_state.pop("calib_result", None)

if "sim" in st.session_state:
    sim = st.session_state["sim"]
    index = st.session_state["sim_index"]
    obs = st.session_state["sim_obs"]

    dt_seconds = 86400.0 if model_type.startswith("D") else 86400.0 * 30.44

    tab_hyd, tab_vol, tab_mon, tab_ann = st.tabs([
        "📈 Hidrograma", "📊 Volume Acumulado", "📅 Médias Mensais", "📋 Estatísticas Anuais"
    ])
    with tab_hyd:
        st.plotly_chart(plot_hydrograph(sim, index=index, obs=obs), use_container_width=True)
    with tab_vol:
        st.plotly_chart(plot_cumulative_volume(sim, index=index, obs=obs, dt_seconds=dt_seconds), use_container_width=True)
    with tab_mon:
        st.plotly_chart(plot_monthly_averages(sim, index=index, obs=obs), use_container_width=True)
    with tab_ann:
        stats = annual_stats(sim, index, obs=obs, dt_seconds=dt_seconds)
        if stats.empty:
            st.info("Série temporal insuficiente para estatísticas anuais (mínimo: 1 ano completo com ≥ 90 % dos registros esperados).")
        else:
            st.dataframe(stats, use_container_width=True)
            st.download_button(
                "📥 Baixar estatísticas anuais (CSV)",
                data=stats.to_csv().encode(),
                file_name="estatisticas_anuais.csv",
                mime="text/csv",
                key="dl_annual",
            )

    # --- Download série simulada ---
    result_df = pd.DataFrame({"sim_m3s": sim}, index=index)
    result_df.index.name = "date"
    if obs is not None and len(obs) == len(sim):
        result_df["obs_m3s"] = obs
    st.download_button(
        "📥 Baixar série simulada (CSV)",
        data=result_df.to_csv().encode(),
        file_name="vazao_simulada.csv",
        mime="text/csv",
    )

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

    # --- Calibration (only when observed data is available) ---
    if obs is not None and len(obs) == len(sim):
        st.divider()
        st.subheader("🎯 Calibração Automática")
        sel_vars = st.multiselect(
            "Parâmetros a calibrar",
            options=calib_options,
            default=calib_options[:4],
        )
        if st.button("Calibrar parâmetros", disabled=not sel_vars):
            with st.spinner("Calibrando... pode levar alguns segundos."):
                calib_params, calib_kge = calibrate_fn(
                    st.session_state["sim_params"],
                    st.session_state["sim_prec"],
                    st.session_state["sim_etp"],
                    obs,
                    sel_vars,
                )
                calib_sim = run_fn(calib_params, st.session_state["sim_prec"], st.session_state["sim_etp"])
                st.session_state["calib_result"] = {
                    "params": calib_params,
                    "sim": calib_sim,
                    "kge": calib_kge,
                }

        if "calib_result" in st.session_state:
            cr = st.session_state["calib_result"]
            st.plotly_chart(
                plot_hydrograph(cr["sim"], index=index, obs=obs, title="Hidrograma Calibrado"),
                use_container_width=True,
            )
            col_kge, *_ = st.columns(4)
            col_kge.metric("KGE calibrado", f"{cr['kge']:.3f}")
            st.write("**Parâmetros calibrados:**")
            calib_df = pd.DataFrame.from_dict(cr["params"], orient="index", columns=["Valor"]).round(4)
            calib_df.index.name = "Parâmetro"
            st.dataframe(calib_df, use_container_width=False)

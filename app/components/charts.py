import numpy as np
import plotly.graph_objects as go
import pandas as pd


def plot_hydrograph(
    sim: list,
    index=None,
    obs: list | None = None,
    title: str = "Hidrograma Simulado",
) -> go.Figure:
    x = index if index is not None else list(range(len(sim)))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=x, y=sim, name="Simulado", line=dict(color="steelblue", width=2))
    )
    if obs is not None:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=obs,
                name="Observado",
                line=dict(color="firebrick", width=1.5, dash="dot"),
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="Tempo",
        yaxis_title="Vazão (m³/s)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def plot_cumulative_volume(
    sim: list,
    index=None,
    obs: list | None = None,
    dt_seconds: float = 86400.0,
    title: str = "Volume Acumulado",
) -> go.Figure:
    x = index if index is not None else list(range(len(sim)))
    cum_sim = np.cumsum(np.array(sim) * dt_seconds) / 1e6  # hm³
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=cum_sim, name="Simulado", line=dict(color="steelblue", width=2), fill="tozeroy", fillcolor="rgba(70,130,180,0.1)"))
    if obs is not None:
        cum_obs = np.cumsum(np.array(obs) * dt_seconds) / 1e6
        fig.add_trace(go.Scatter(x=x, y=cum_obs, name="Observado", line=dict(color="firebrick", width=1.5, dash="dot")))
    fig.update_layout(
        title=title,
        xaxis_title="Tempo",
        yaxis_title="Volume Acumulado (hm³)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


_MONTH_NAMES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def plot_monthly_averages(
    sim: list,
    index,
    obs: list | None = None,
    title: str = "Médias Mensais de Vazão",
) -> go.Figure:
    df_sim = pd.DataFrame({"sim": sim}, index=pd.DatetimeIndex(index))
    monthly = df_sim["sim"].groupby(df_sim.index.month).mean()
    labels = [_MONTH_NAMES[m - 1] for m in monthly.index]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=monthly.values, name="Simulado", marker_color="steelblue"))
    if obs is not None:
        df_obs = pd.DataFrame({"obs": obs}, index=pd.DatetimeIndex(index))
        monthly_obs = df_obs["obs"].groupby(df_obs.index.month).mean()
        fig.add_trace(go.Bar(
            x=[_MONTH_NAMES[m - 1] for m in monthly_obs.index],
            y=monthly_obs.values,
            name="Observado",
            marker_color="firebrick",
            opacity=0.75,
        ))
    fig.update_layout(
        title=title,
        xaxis_title="Mês",
        yaxis_title="Vazão Média (m³/s)",
        barmode="group",
    )
    return fig


def plot_network_hydrograph(df: pd.DataFrame, title: str = "Hidrogramas da Rede") -> go.Figure:
    fig = go.Figure()
    for col in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[col], name=f"Subcatchment {col}"))
    fig.update_layout(
        title=title,
        xaxis_title="Tempo",
        yaxis_title="Vazão (m³/s)",
        hovermode="x unified",
    )
    return fig

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

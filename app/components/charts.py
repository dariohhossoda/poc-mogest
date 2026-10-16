import json

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


NETWORK_DEFAULT_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def plot_network_hydrograph(
    df: pd.DataFrame,
    title: str = "Hidrogramas da Rede",
    colors: dict | None = None,
) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(df.columns):
        color = (colors or {}).get(col) or NETWORK_DEFAULT_COLORS[i % len(NETWORK_DEFAULT_COLORS)]
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col], name=f"Subcatchment {col}",
            line=dict(color=color, width=2),
        ))
    fig.update_layout(
        title=title,
        xaxis_title="Tempo",
        yaxis_title="Vazão (m³/s)",
        hovermode="x unified",
    )
    return fig


BASEMAPS = {
    "Cinza claro": "carto-positron",
    "Escuro": "carto-darkmatter",
    "Sem fundo": "white-bg",
}

_TRANSPARENT = [[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]]


def _map_view(gdf) -> dict:
    """Center and zoom that fit the polygons."""
    minx, miny, maxx, maxy = gdf.total_bounds
    extent = max(maxx - minx, (maxy - miny) * 1.6, 1e-3)
    zoom = float(np.clip(np.log2(360.0 / extent) - 1.2, 1, 14))
    center = {"lon": (minx + maxx) / 2, "lat": (miny + maxy) / 2}
    return {"center": center, "zoom": zoom}


def plot_network_map(
    gdf,
    values: pd.Series,
    value_label: str,
    names: dict,
    outlet_ids: list,
    links: pd.DataFrame,
    basemap: str = "carto-positron",
    selected=None,
) -> go.Figure:
    """
    Choropleth of subcatchments colored by ``values`` (indexed by basin id).

    ``gdf`` is a WGS84 GeoDataFrame with ``id``; ``links`` has lon0/lat0 →
    lon1/lat1 segments from upstream to downstream basins. Basin markers carry
    the id in ``customdata`` so a map selection identifies the basin.
    """
    dark = basemap == "carto-darkmatter"
    edge = "#e0e0e0" if dark else "#404040"
    geojson = json.loads(gdf[["id", "geometry"]].to_json())
    ids = gdf["id"].tolist()
    label = [names.get(i, str(i)) for i in ids]
    z = [values.get(i, np.nan) for i in ids]

    fig = go.Figure()
    fig.add_trace(go.Choroplethmap(
        geojson=geojson,
        featureidkey="properties.id",
        locations=ids,
        z=z,
        text=label,
        colorscale="Blues",
        marker_opacity=0.75,
        marker_line_color=edge,
        marker_line_width=1,
        colorbar=dict(title=value_label),
        hovertemplate="<b>%{text}</b><br>" + value_label + ": %{z:.3f}<extra></extra>",
        name="Sub-bacias",
    ))

    if selected is not None and selected in ids:
        fig.add_trace(go.Choroplethmap(
            geojson=geojson,
            featureidkey="properties.id",
            locations=[selected],
            z=[0],
            colorscale=_TRANSPARENT,
            showscale=False,
            marker_line_color="#d62728",
            marker_line_width=3,
            hoverinfo="skip",
            name="Selecionada",
        ))

    if not links.empty:
        lon, lat = [], []
        for _, seg in links.iterrows():
            lon += [seg["lon0"], seg["lon1"], None]
            lat += [seg["lat0"], seg["lat1"], None]
        fig.add_trace(go.Scattermap(
            lon=lon, lat=lat, mode="lines",
            line=dict(color=edge, width=2),
            hoverinfo="skip",
            name="Ligação montante → jusante",
        ))

    points = gdf.geometry.representative_point()
    is_outlet = [i in outlet_ids for i in ids]
    fig.add_trace(go.Scattermap(
        lon=points.x, lat=points.y,
        mode="markers+text",
        text=label,
        textposition="top center",
        textfont=dict(color=edge),
        customdata=ids,
        marker=dict(
            size=[14 if o else 8 for o in is_outlet],
            color=["#d62728" if o else edge for o in is_outlet],
        ),
        hovertemplate="<b>%{text}</b><extra></extra>",
        name="Exutório (vermelho) / sub-bacia",
    ))

    fig.update_layout(
        map=dict(style=basemap, **_map_view(gdf)),
        margin=dict(l=0, r=0, t=10, b=0),
        height=520,
        showlegend=False,
    )
    return fig

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


_RIVER_COLOR = "#4a90c2"


def _line_coords(geoms) -> tuple[list, list]:
    """lon/lat lists of (multi)line geometries, segments split by None."""
    lon, lat = [], []
    for geom in geoms:
        parts = getattr(geom, "geoms", [geom])
        for part in parts:
            xs, ys = part.xy
            lon += list(xs) + [None]
            lat += list(ys) + [None]
    return lon, lat


def _rivers_trace(rivers) -> go.Scattermap:
    lon, lat = _line_coords(rivers.geometry)
    return go.Scattermap(
        lon=lon, lat=lat, mode="lines",
        line=dict(color=_RIVER_COLOR, width=1.5),
        hoverinfo="skip",
        name="Rios",
    )


def plot_delineation_preview(
    points: pd.DataFrame,
    bbox: tuple | None = None,
    polygons=None,
    rivers=None,
    snapped=None,
    basemap: str = "carto-positron",
    ana: pd.DataFrame | None = None,
) -> go.Figure:
    """
    Map of the delineation inputs and, once it ran, its result.

    ``points`` has id, lat, lon and kind ("Exutório" or "Posto"); ``bbox`` is
    the GLO-30 window (west, south, east, north). ``polygons``, ``rivers`` and
    ``snapped`` (outlets moved to the river) are WGS84 GeoDataFrames. ``ana``
    holds ANA stations (``core.ana`` columns), drawn as clickable markers whose
    customdata starts with ``"ana"`` and the station code.
    """
    dark = basemap == "carto-darkmatter"
    edge = "#e0e0e0" if dark else "#404040"
    fig = go.Figure()

    if polygons is not None and len(polygons):
        lon, lat = _line_coords(polygons.geometry.boundary)
        fig.add_trace(go.Scattermap(
            lon=lon, lat=lat, mode="lines",
            line=dict(color=edge, width=1.5),
            hoverinfo="skip",
            name="Sub-bacias",
        ))
        centers = polygons.geometry.representative_point()
        fig.add_trace(go.Scattermap(
            lon=centers.x, lat=centers.y, mode="text",
            text=polygons["name"], textfont=dict(color=edge),
            hoverinfo="skip", name="Nomes",
        ))
    if rivers is not None and len(rivers):
        fig.add_trace(_rivers_trace(rivers))
    if bbox is not None:
        west, south, east, north = bbox
        fig.add_trace(go.Scattermap(
            lon=[west, east, east, west, west],
            lat=[south, south, north, north, south],
            mode="lines",
            line=dict(color="#808080", width=1),
            hoverinfo="skip",
            name="Janela do DEM",
        ))
    if snapped is not None and len(snapped):
        fig.add_trace(go.Scattermap(
            lon=snapped.geometry.x, lat=snapped.geometry.y,
            mode="markers",
            marker=dict(size=9, color=_RIVER_COLOR),
            text=snapped["name"],
            customdata=snapped["dist_snap_m"],
            hovertemplate="<b>%{text}</b> no rio<br>deslocado %{customdata:.0f} m"
            "<extra></extra>",
            unselected=dict(marker=dict(opacity=1)),
            name="Ponto no rio",
        ))
    if ana is not None and len(ana):
        fig.add_trace(_ana_trace(ana))
    if len(points):
        is_outlet = points["kind"].eq("Exutório").tolist()
        fig.add_trace(go.Scattermap(
            lon=points["lon"], lat=points["lat"],
            mode="markers",
            marker=dict(
                size=[14 if o else 10 for o in is_outlet],
                color=["#d62728" if o else edge for o in is_outlet],
            ),
            text=points["id"],
            customdata=points["kind"],
            hovertemplate="<b>%{text}</b> (%{customdata})<extra></extra>",
            unselected=dict(marker=dict(opacity=1)),
            name="Pontos informados",
        ))

    if polygons is not None and len(polygons):
        view = _map_view(polygons)
    elif bbox is not None:
        view = _map_view_bounds(bbox)
    elif len(points):
        view = _map_view_bounds(
            (points["lon"].min(), points["lat"].min(),
             points["lon"].max(), points["lat"].max())
        )
    else:
        view = {"center": {"lon": -47.0, "lat": -15.0}, "zoom": 3}
    fig.update_layout(
        map=dict(style=basemap, **view),
        margin=dict(l=0, r=0, t=10, b=0),
        height=460,
        showlegend=False,
    )
    return fig


_ANA_OPEN = "#1f77b4"
_ANA_CLOSED = "#9e9e9e"


def _ana_trace(ana: pd.DataFrame) -> go.Scattermap:
    """ANA stations: blue in operation, grey closed; a click selects one."""
    area = ana["area_km2"].map(lambda a: "—" if pd.isna(a) else f"{a:,.0f} km²")
    status = ana["operando"].map({True: "em operação", False: "desativado"})
    coord = ana["casas_coord"].map(
        lambda n: "" if n >= 2 else f"<br>coordenada com {n} casa(s) decimal(is)"
    )
    return go.Scattermap(
        lon=ana["lon"], lat=ana["lat"],
        mode="markers",
        marker=dict(
            size=9,
            color=[_ANA_OPEN if o else _ANA_CLOSED for o in ana["operando"]],
        ),
        selected=dict(marker=dict(size=15)),
        unselected=dict(marker=dict(opacity=1)),
        customdata=list(zip(
            ["ana"] * len(ana), ana["codigo"], ana["nome"], ana["rio"], area,
            ana["responsavel"], status, coord,
        )),
        hovertemplate="<b>%{customdata[1]}</b> %{customdata[2]}<br>"
        "%{customdata[3]} · área %{customdata[4]}<br>"
        "%{customdata[5]} · %{customdata[6]}%{customdata[7]}<extra>ANA</extra>",
        name="Postos ANA",
    )


def _map_view(gdf) -> dict:
    """Center and zoom that fit the polygons."""
    return _map_view_bounds(gdf.total_bounds)


def _map_view_bounds(bounds) -> dict:
    """Center and zoom that fit (west, south, east, north)."""
    minx, miny, maxx, maxy = bounds
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
    rivers=None,
) -> go.Figure:
    """
    Choropleth of subcatchments colored by ``values`` (indexed by basin id).

    ``gdf`` is a WGS84 GeoDataFrame with ``id``; ``links`` has lon0/lat0 →
    lon1/lat1 segments from upstream to downstream basins. Basin markers carry
    the id in ``customdata`` so a map selection identifies the basin.
    ``rivers`` (optional, WGS84 lines) is drawn under the links.
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

    if rivers is not None and len(rivers):
        fig.add_trace(_rivers_trace(rivers))

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

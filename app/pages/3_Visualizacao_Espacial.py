import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.io import load_params


def _load_geojson(file) -> pd.DataFrame:
    data = json.loads(file.read())
    features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
    rows = []
    for feat in features:
        props = dict(feat.get("properties") or {})
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates", [])
        geom_type = geom.get("type", "")
        if geom_type == "Point":
            lon, lat = float(coords[0]), float(coords[1])
        elif geom_type == "Polygon":
            ring = coords[0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
        elif geom_type == "MultiPolygon":
            ring = coords[0][0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
        else:
            continue
        rows.append({**props, "lat": lat, "lon": lon})
    return pd.DataFrame(rows)

st.set_page_config(page_title="Visualização Espacial", page_icon="🗺️", layout="wide")
st.title("🗺️ Visualização Espacial")
st.markdown(
    "Visualize bacias e resultados de simulação em mapa interativo. "
    "Os resultados da última simulação são sobrepostos automaticamente."
)

EXAMPLE_SPATIAL = Path("data/example_spatial.csv")
EXAMPLE_SPATIAL_GEOJSON = Path("data/example_spatial.geojson")

# --- Spatial data ---
st.subheader("Localização das Bacias")

spatial_file = st.file_uploader(
    "Coordenadas das bacias (CSV/XLSX/GeoJSON)", type=["csv", "xlsx", "geojson"]
)

if spatial_file is not None:
    st.session_state["use_spatial_example"] = False
elif "use_spatial_example" not in st.session_state:
    st.session_state["use_spatial_example"] = True

use_example = st.checkbox("Usar localização de exemplo", key="use_spatial_example")

if use_example:
    spatial_df = load_params(EXAMPLE_SPATIAL)
    st.info("Usando coordenadas de exemplo.")
else:
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "📥 Template — CSV",
            data=EXAMPLE_SPATIAL.read_bytes(),
            file_name="template_espacial.csv",
            mime="text/csv",
        )
        st.caption("Colunas obrigatórias: `id`, `lat`, `lon`. Opcionais: `name`, `downstream_id`.")
    with dl2:
        st.download_button(
            "📥 Template — GeoJSON",
            data=EXAMPLE_SPATIAL_GEOJSON.read_bytes(),
            file_name="template_espacial.geojson",
            mime="application/geo+json",
        )
        st.caption("Features com `Point` ou `Polygon`. Propriedades: `id`, `name`, `downstream_id`.")
    if spatial_file is None:
        st.warning("Carregue o arquivo de coordenadas para continuar.")
        st.stop()
    if spatial_file.name.endswith(".geojson"):
        spatial_df = _load_geojson(spatial_file)
    else:
        spatial_df = load_params(spatial_file)

for col in ["id", "lat", "lon"]:
    if col not in spatial_df.columns:
        st.error(f"Coluna obrigatória ausente: `{col}`")
        st.stop()

spatial_df["id"] = spatial_df["id"].astype(str)
if "name" not in spatial_df.columns:
    spatial_df["name"] = spatial_df["id"]
spatial_df = spatial_df.reset_index(drop=True)

# --- Simulation results from session state ---
network_result: pd.DataFrame | None = st.session_state.get("network_result")
smap_sim: list | None = st.session_state.get("sim")

peak_map: dict[str, float] = {}
if network_result is not None:
    for col in network_result.columns:
        peak_map[str(col)] = float(network_result[col].max())
elif smap_sim is not None and len(spatial_df) == 1:
    peak_map[str(spatial_df["id"].iloc[0])] = float(max(smap_sim))

has_results = bool(peak_map)

# --- Build map ---
peaks = [peak_map.get(bid, None) for bid in spatial_df["id"]]
peaks_numeric = [p if p is not None else 0.0 for p in peaks]
max_peak = max(peaks_numeric) if any(p is not None for p in peaks) else 1.0
marker_size = [12 + min((p / (max_peak or 1.0)) * 18, 18) for p in peaks_numeric]

hover_texts = []
for _, row in spatial_df.iterrows():
    bid = str(row["id"])
    label = f"<b>{row['name']}</b> (id={bid})"
    if bid in peak_map:
        label += f"<br>Pico simulado: {peak_map[bid]:.3f} m³/s"
    hover_texts.append(label)

fig = go.Figure()

# Network lines (upstream → downstream)
if "downstream_id" in spatial_df.columns:
    idx_map = {row["id"]: row for _, row in spatial_df.iterrows()}
    for _, row in spatial_df.iterrows():
        ds_id = str(row.get("downstream_id", ""))
        if ds_id and ds_id not in ("nan", "") and ds_id in idx_map:
            ds = idx_map[ds_id]
            fig.add_trace(go.Scattermapbox(
                lat=[float(row["lat"]), float(ds["lat"])],
                lon=[float(row["lon"]), float(ds["lon"])],
                mode="lines",
                line=dict(color="steelblue", width=2),
                hoverinfo="skip",
                showlegend=False,
            ))

# Basin markers
fig.add_trace(go.Scattermapbox(
    lat=spatial_df["lat"].tolist(),
    lon=spatial_df["lon"].tolist(),
    text=hover_texts,
    mode="markers",
    marker=go.scattermapbox.Marker(
        size=marker_size,
        color=peaks_numeric if has_results else ["steelblue"] * len(spatial_df),
        colorscale="YlOrRd" if has_results else None,
        showscale=has_results,
        colorbar=dict(title="Pico (m³/s)") if has_results else None,
        cmin=0 if has_results else None,
        cmax=max_peak if has_results else None,
    ),
    hovertemplate="%{text}<extra></extra>",
    name="Bacias",
))

fig.update_layout(
    mapbox_style="open-street-map",
    mapbox=dict(
        zoom=8,
        center=dict(
            lat=float(spatial_df["lat"].mean()),
            lon=float(spatial_df["lon"].mean()),
        ),
    ),
    margin=dict(l=0, r=0, t=30, b=0),
    height=520,
    showlegend=False,
)

st.plotly_chart(fig, use_container_width=True)

if has_results:
    st.caption("Marcadores coloridos (amarelo → vermelho) por vazão de pico da última simulação.")
    result_spatial = spatial_df[["id", "name", "lat", "lon"]].copy()
    result_spatial["pico_m3s"] = [peak_map.get(bid, float("nan")) for bid in spatial_df["id"]]
    st.download_button(
        "📥 Baixar resultados espaciais (CSV)",
        data=result_spatial.to_csv(index=False).encode(),
        file_name="resultado_espacial.csv",
        mime="text/csv",
    )
else:
    st.info(
        "Execute uma simulação em **Simulação SMAP** (bacia única) ou "
        "**Rede Hidrológica** (múltiplas bacias) para sobrepor vazões de pico no mapa."
    )

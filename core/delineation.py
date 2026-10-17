"""
Subcatchment delineation from an outlet point, entirely in memory.

Wraps the copy of mogest-network in ``core/mogest_network`` and converts its
output to the format of the network page: integer basin ids, the parameter
columns of ``run_network`` and polygons shaped like ``load_polygons``. The DEM
comes from the Copernicus GLO-30 bucket or from uploaded bytes; nothing is
written to disk.
"""

import io
import math
import zipfile
from dataclasses import dataclass
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd

from core.geo import EQUAL_AREA, WGS84
from core.mogest_network import JUSANTE_FINAL
from core.mogest_network.delineacao import PontoExutorio, delinear
from core.mogest_network.dem import (
    bbox_em_torno,
    carregar_dem_bytes,
    mosaico_glo30,
)
from core.mogest_network.muskingum_k import ajustar_estabilidade, k_por_celeridade

DEFAULT_RESOLUTION_DEG = 1 / 1200  # 3" (~90 m)
NATIVE_RESOLUTION_DEG = 1 / 3600  # 1" (~30 m), GLO-30 native
# Largest DEM handed to pyflwdir. Peak memory measured on the Cachoeira basin
# (2026-10-17) was ~64 bytes per cell above the imports, so 12 M cells (about
# 3° x 3° at 3") add ~0.8 GB.
MAX_CELLS = 12_000_000

# mogest-network defaults (config.ParamsSmap); tuin goes from fraction to %
SMAP_DEFAULTS = {
    "str": 900.0,
    "crec": 5.0,
    "capc": 40.0,
    "kkt": 90.0,
    "k2t": 2.0,
    "ai": 2.5,
    "tuin": 50.0,
    "ebin": 0.0,
}
# mogest-network defaults (propagacao.MuskingumCunge); A in km²
CUNGE_DEFAULTS = {
    "manning": 0.035,
    "width_coef": 1.5,
    "width_exp": 0.5,
    "q_ref_coef": 1.0 / 3.0,
    "q_ref_exp": 0.7,
    "slope_min": 1e-4,
}

TOPOLOGY_COLUMNS = ("id", "name", "downstream_id", "area", "length", "slope")


@dataclass
class Station:
    """Point given by the user: the basin outlet or a gauge upstream of it."""

    id: str
    lat: float
    lon: float


@dataclass
class DelineationResult:
    """Delineated network in the format of the network page (WGS84)."""

    polygons: gpd.GeoDataFrame
    params: pd.DataFrame
    outlets: gpd.GeoDataFrame
    rivers: gpd.GeoDataFrame
    bbox: tuple | None
    touches_border: bool


def points_bbox(points: list[Station], buffer_km: float) -> tuple:
    """(west, south, east, north) around all points, as in mogest-network."""
    boxes = np.array([bbox_em_torno(p.lon, p.lat, buffer_km) for p in points])
    return (
        float(boxes[:, 0].min()),
        float(boxes[:, 1].min()),
        float(boxes[:, 2].max()),
        float(boxes[:, 3].max()),
    )


def bbox_cells(bbox: tuple, resolution_deg: float) -> int:
    """Number of DEM cells covering the bbox at the given resolution."""
    west, south, east, north = bbox
    return math.ceil((east - west) / resolution_deg) * math.ceil(
        (north - south) / resolution_deg
    )


def _check_cells(cells: int, max_cells: int) -> None:
    if cells > max_cells:
        raise ValueError(
            f"O DEM teria {cells / 1e6:.1f} milhões de células (limite "
            f"{max_cells / 1e6:.0f} milhões): reduza o buffer ou a resolução."
        )


def _upstream_area(topology: pd.DataFrame) -> dict:
    """Area draining into the reach of each basin (sum over its upstream basins)."""
    downstream = dict(zip(topology["id"], topology["downstream_id"]))
    own = dict(zip(topology["id"], topology["area"]))
    total = dict(own)
    # walk each basin down to the outlet, adding its own area on the way
    for bid, area in own.items():
        ds = downstream[bid]
        while not pd.isna(ds):
            total[ds] += area
            ds = downstream[ds]
    inflow = {bid: 0.0 for bid in own}
    for bid, ds in downstream.items():
        if not pd.isna(ds):
            inflow[ds] += total[bid]
    return inflow


def network_params(
    topology: pd.DataFrame, celerity_ms: float = 1.0, x: float = 0.2
) -> pd.DataFrame:
    """
    Network parameter table from a delineated topology.

    ``topology`` has the columns of ``TOPOLOGY_COLUMNS``. SMAP parameters take
    the mogest-network defaults (``ebin`` is zero). Linear Muskingum gets
    ``k = length / celerity`` in days, adjusted so the coefficients stay
    non-negative; ``k = 0`` means direct pass-through. Muskingum-Cunge gets
    ``q_ref`` and ``width`` from the area draining into the reach, as in
    mogest-network (minimum 1 km²).
    """
    params = topology.loc[:, list(TOPOLOGY_COLUMNS)].copy()
    for name, value in SMAP_DEFAULTS.items():
        params[name] = value
    kx = [
        ajustar_estabilidade(k_por_celeridade(length, celerity_ms), x)
        for length in params["length"]
    ]
    params["k"] = [k for k, _ in kx]
    params["x"] = [xx for _, xx in kx]

    inflow = _upstream_area(params)
    area_in = params["id"].map(inflow).clip(lower=1.0)
    c = CUNGE_DEFAULTS
    params["q_ref"] = c["q_ref_coef"] * area_in ** c["q_ref_exp"]
    params["manning"] = c["manning"]
    params["width"] = c["width_coef"] * area_in ** c["width_exp"]
    params["slope"] = params["slope"].clip(lower=c["slope_min"])
    return params


def _to_app_format(res, celerity_ms: float, x: float):
    """Integer ids (1 = outlet) and app columns; the original id becomes ``name``."""
    topo = res.topologia
    new_id = {sid: n for n, sid in enumerate(topo["id"], start=1)}
    topology = pd.DataFrame(
        {
            "id": topo["id"].map(new_id),
            "name": topo["id"].astype(str),
            "downstream_id": topo["jusante"].map(
                lambda j: np.nan if j == JUSANTE_FINAL else new_id[j]
            ),
            "area": topo["area_km2"].astype(float),
            "length": topo["L_trecho_km"].astype(float) * 1000.0,
            "slope": topo["S_trecho"].astype(float),
        }
    )
    params = network_params(topology, celerity_ms, x)

    polygons = res.subbacias[["id", "geometry"]].copy()
    polygons["name"] = polygons["id"].astype(str)
    polygons["id"] = polygons["id"].map(new_id)
    polygons = polygons.to_crs(WGS84)
    polygons["area_geom"] = polygons.geometry.to_crs(EQUAL_AREA).area / 1e6
    polygons = polygons[["id", "name", "area_geom", "geometry"]]

    outlets = res.outlets.copy()
    outlets["name"] = outlets["id"].astype(str)
    outlets["id"] = outlets["id"].map(new_id)
    outlets = outlets.to_crs(WGS84)

    rivers = res.rios.to_crs(WGS84) if len(res.rios) else res.rios.set_crs(WGS84)
    return polygons, params, outlets, rivers


def delineate(
    outlet: Station,
    stations: list[Station] | None = None,
    *,
    dem_bytes: bytes | None = None,
    buffer_km: float = 30.0,
    buffer_max_km: float = 240.0,
    resolution_deg: float | None = DEFAULT_RESOLUTION_DEG,
    area_min_km2: float | None = None,
    river_threshold_km2: float = 5.0,
    max_snap_m: float = 2000.0,
    celerity_ms: float = 1.0,
    x: float = 0.2,
    max_cells: int = MAX_CELLS,
    on_step: Callable[[str], None] | None = None,
) -> DelineationResult:
    """
    Delineate the basin of ``outlet`` and its subcatchments.

    Without ``dem_bytes`` the GLO-30 is read for a bbox of ``buffer_km`` around
    the points; while the basin touches the DEM border the buffer doubles, up
    to ``buffer_max_km`` or the cell limit. With ``dem_bytes`` (a GeoTIFF) the
    whole raster is used and a border contact is only reported.

    Raises
    ------
    ValueError
        DEM above ``max_cells``, point outside the outlet basin, or two points
        on the same river cell.
    RuntimeError
        No GLO-30 tile for the bbox.
    """
    stations = list(stations or [])
    step = on_step or (lambda _msg: None)
    exu = PontoExutorio(outlet.id, outlet.lon, outlet.lat)
    gauges = [PontoExutorio(s.id, s.lon, s.lat, posto=True) for s in stations]
    kwargs = dict(
        area_min_km2=area_min_km2,
        limiar_rio_km2=river_threshold_km2,
        max_snap_m=max_snap_m,
    )

    bbox = None
    if dem_bytes is not None:
        step("Lendo o DEM enviado")
        dem = carregar_dem_bytes(dem_bytes)
        _check_cells(dem.elevacao.size, max_cells)
        step("Calculando direções de fluxo e sub-bacias")
        res = delinear(dem, exu, gauges, **kwargs)
    else:
        res_deg = resolution_deg or NATIVE_RESOLUTION_DEG
        buffer = buffer_km
        while True:
            bbox = points_bbox([outlet, *stations], buffer)
            _check_cells(bbox_cells(bbox, res_deg), max_cells)
            step(f"Lendo o Copernicus GLO-30 (buffer de {buffer:.0f} km)")
            dem = mosaico_glo30(bbox, resolution_deg)
            step("Calculando direções de fluxo e sub-bacias")
            res = delinear(dem, exu, gauges, **kwargs)
            next_bbox = points_bbox([outlet, *stations], buffer * 2)
            if (
                not res.toca_borda
                or buffer * 2 > buffer_max_km
                or bbox_cells(next_bbox, res_deg) > max_cells
            ):
                break
            buffer *= 2
            del dem, res

    polygons, params, outlets, rivers = _to_app_format(res, celerity_ms, x)
    return DelineationResult(polygons, params, outlets, rivers, bbox, res.toca_borda)


def export_zip(result: DelineationResult, params: pd.DataFrame | None = None) -> bytes:
    """
    Zip, built in memory, with the delineation for download.

    ``subbacias.gpkg`` and ``parametros.csv`` can be uploaded back to the
    network page; ``exutorios.geojson`` and ``rios.geojson`` are for GIS use.
    ``params`` overrides the table of ``result`` (e.g. after user edits).
    """
    table = result.params if params is None else params
    layers = {
        "subbacias.gpkg": (result.polygons.drop(columns="area_geom"), "GPKG"),
        "exutorios.geojson": (result.outlets, "GeoJSON"),
        "rios.geojson": (result.rivers, "GeoJSON"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (gdf, driver) in layers.items():
            if len(gdf) == 0:
                continue
            data = io.BytesIO()
            gdf.to_file(data, driver=driver)
            zf.writestr(name, data.getvalue())
        zf.writestr("parametros.csv", table.to_csv(index=False))
    return buffer.getvalue()


def series_template(params: pd.DataFrame, days: int = 3) -> bytes:
    """CSV template for precipitation or ETP with one column per basin id."""
    index = pd.date_range("2020-01-01", periods=days, freq="D", name="date")
    frame = pd.DataFrame(0.0, index=index, columns=params["id"].tolist())
    return frame.to_csv().encode()

"""Subcatchment polygons: reading, area and conversion to network parameters."""

import io
import warnings
import zipfile
from pathlib import Path, PurePosixPath

import geopandas as gpd
import pandas as pd
from mogestpy.quantity.hydrological.routing import REQUIRED_PARAM_COLUMNS

WGS84 = "EPSG:4326"
EQUAL_AREA = "EPSG:6933"  # WGS 84 / NSIDC EASE-Grid 2.0 Global (equal-area)
POLYGON_SUFFIXES = (".geojson", ".json", ".zip", ".gpkg")
# Shapefile (DBF) truncates field names to 10 characters
COLUMN_ALIASES = {"downstream": "downstream_id", "ds_id": "downstream_id"}


def _normalize_id(value):
    """Basin IDs become int when possible, matching the time-series columns."""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return value
    return int(as_float) if as_float.is_integer() else value


def _flat_shapefile_zip(data: bytes) -> bytes:
    """
    Rebuild the zip with only the first shapefile's files at its root.

    GDAL reads an in-memory zip only from its root, and uploads often keep the
    shapefile inside a folder.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as src:
        shapefiles = sorted(n for n in src.namelist() if n.lower().endswith(".shp"))
        if not shapefiles:
            raise ValueError("O arquivo .zip não contém um shapefile (.shp).")
        stem = shapefiles[0][:-4]
        flat = io.BytesIO()
        with zipfile.ZipFile(flat, "w") as dst:
            for member in src.namelist():
                if member.rsplit(".", 1)[0] == stem:
                    dst.writestr(PurePosixPath(member).name, src.read(member))
    return flat.getvalue()


def _read_file(data: bytes, suffix: str) -> gpd.GeoDataFrame:
    """Read from memory: pyogrio opens bytes through GDAL /vsimem/, not the disk."""
    if suffix == ".zip":
        data = _flat_shapefile_zip(data)
    with warnings.catch_warnings():
        # GDAL names the in-memory file without the .gpkg extension
        warnings.filterwarnings("ignore", message=".*non conformant file extension")
        return gpd.read_file(io.BytesIO(data))


def load_polygons(source) -> gpd.GeoDataFrame:
    """
    Read subcatchment polygons from GeoJSON, zipped shapefile or GeoPackage.

    ``source`` is a path or an uploaded file object with ``name``. Returns a
    GeoDataFrame in WGS84 with lower-case column names, an ``id`` column
    normalized like the time-series columns and ``area_geom`` in km².
    """
    name = str(getattr(source, "name", source)).lower()
    if not name.endswith(POLYGON_SUFFIXES):
        raise ValueError(f"Formato não suportado: use {', '.join(POLYGON_SUFFIXES)}.")

    data = source.read() if hasattr(source, "read") else Path(source).read_bytes()
    gdf = _read_file(data, Path(name).suffix)

    gdf = gdf.rename(columns={c: c.lower() for c in gdf.columns if c != "geometry"})
    if "downstream_id" not in gdf.columns:
        gdf = gdf.rename(columns=COLUMN_ALIASES)
    gdf = gdf.set_geometry("geometry")
    if "id" not in gdf.columns:
        raise ValueError("Os polígonos precisam de um atributo `id`.")
    if not gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Todas as feições devem ser polígonos.")

    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    gdf = gdf.to_crs(WGS84)

    gdf["id"] = gdf["id"].map(_normalize_id)
    if gdf["id"].duplicated().any():
        raise ValueError("O atributo `id` dos polígonos tem valores repetidos.")
    gdf["area_geom"] = gdf.geometry.to_crs(EQUAL_AREA).area / 1e6
    return gdf.reset_index(drop=True)


def missing_param_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    """Network parameter columns absent from the polygon attributes (area aside)."""
    return [c for c in REQUIRED_PARAM_COLUMNS if c != "area" and c not in gdf.columns]


def polygons_to_params(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Network parameter table from polygon attributes.

    ``area`` comes from the geometry when the attribute is missing or empty.
    Extra attributes (e.g. Muskingum-Cunge reach columns, ``name``) are kept.
    """
    missing = missing_param_columns(gdf)
    if missing:
        raise ValueError(f"Faltam atributos de parâmetros nos polígonos: {missing}.")
    params = pd.DataFrame(gdf.drop(columns="geometry"))
    if "area" not in params.columns:
        params["area"] = params["area_geom"]
    else:
        params["area"] = pd.to_numeric(params["area"], errors="coerce").fillna(
            params["area_geom"]
        )
    return params.drop(columns="area_geom")


def basin_links(gdf: gpd.GeoDataFrame, downstream: pd.Series) -> pd.DataFrame:
    """
    Upstream → downstream segments between basin representative points.

    ``downstream`` maps basin id to downstream id (NaN at outlets). Returns
    columns id, downstream_id, lon0, lat0, lon1, lat1 for basins whose
    downstream basin also has a polygon.
    """
    points = gdf.set_index("id").geometry.representative_point()
    rows = []
    for bid, ds in downstream.items():
        if pd.isna(ds):
            continue
        ds = _normalize_id(ds)
        if bid in points.index and ds in points.index:
            p0, p1 = points[bid], points[ds]
            rows.append(
                {
                    "id": bid,
                    "downstream_id": ds,
                    "lon0": p0.x,
                    "lat0": p0.y,
                    "lon1": p1.x,
                    "lat1": p1.y,
                }
            )
    return pd.DataFrame(
        rows, columns=["id", "downstream_id", "lon0", "lat0", "lon1", "lat1"]
    )

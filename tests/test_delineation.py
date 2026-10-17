import io
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.io import MemoryFile

from core.delineation import (
    Station,
    bbox_cells,
    delineate,
    export_zip,
    network_params,
    series_template,
)
from core.geo import load_polygons
from core.io import load_params
from core.models import run_network_simulation
from core.mogest_network.dem import carregar_dem_bytes

# Synthetic DEM of mogest-network (tests/sintetico.py): main valley on row 100
# draining west and a tributary on column 150 (rows 0-99) joining it.
CRS_UTM = CRS.from_epsg(31983)
CELL = 100.0  # m
X0, Y0 = 300000.0, 7500000.0


class Upload(io.BytesIO):
    """Stand-in for a Streamlit UploadedFile."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _synthetic_tif() -> bytes:
    row, col = np.mgrid[0:201, 0:200].astype("float32")
    z = 0.01 * col * CELL + 0.05 * np.abs(row - 100) * CELL
    trib = (
        0.01 * (100 - row) * CELL
        + 0.05 * np.abs(col - 150) * CELL
        + 0.01 * 150 * CELL
    )
    z = np.where(row < 100, np.minimum(z, trib + 1.0), z).astype("float32")
    profile = dict(
        driver="GTiff",
        height=z.shape[0],
        width=z.shape[1],
        count=1,
        dtype="float32",
        crs=CRS_UTM,
        transform=Affine(CELL, 0, X0, 0, -CELL, Y0),
        nodata=-9999.0,
    )
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(z, 1)
        return mem.read()


def _station(sid: str, row: int, col: int) -> Station:
    """Station at the center of a synthetic DEM cell."""
    x = X0 + (col + 0.5) * CELL
    y = Y0 - (row + 0.5) * CELL
    lon, lat = Transformer.from_crs(CRS_UTM, "EPSG:4326", always_xy=True).transform(
        x, y
    )
    return Station(sid, lat, lon)


@pytest.fixture(scope="module")
def tif() -> bytes:
    return _synthetic_tif()


@pytest.fixture(scope="module")
def result(tif):
    return delineate(
        _station("foz", 100, 1),
        [_station("posto_a", 100, 120), _station("posto_afl", 60, 150)],
        dem_bytes=tif,
        river_threshold_km2=0.5,
    )


def test_dem_from_bytes(tif):
    dem = carregar_dem_bytes(tif)
    assert dem.elevacao.shape == (201, 200)
    assert dem.crs.to_epsg() == 31983


def test_topology_in_app_format(result):
    params = result.params.set_index("name")
    # integer ids in topology order, 1 = basin outlet
    assert params.loc["foz", "id"] == 1
    assert pd.isna(params.loc["foz", "downstream_id"])
    assert params.loc["posto_a", "downstream_id"] == params.loc["foz", "id"]
    assert params.loc["posto_afl", "downstream_id"] == params.loc["posto_a", "id"]
    # reach posto_a -> foz: 119 cells of 100 m along the main valley
    assert params.loc["foz", "length"] == pytest.approx(11900, abs=200)
    assert params.loc["posto_afl", "length"] == 0.0
    # polygons in WGS84 with the same ids and areas as the parameters
    poly = result.polygons.set_index("id")
    assert result.polygons.crs.to_epsg() == 4326
    np.testing.assert_allclose(
        poly.loc[result.params["id"], "area_geom"], result.params["area"], rtol=0.01
    )
    # the synthetic valleys start at the raster edge
    assert result.touches_border


def test_network_params_muskingum_and_cunge():
    topo = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["foz", "a", "b"],
            "downstream_id": [np.nan, 1, 1],
            "area": [10.0, 20.0, 30.0],
            "length": [86400.0, 0.0, 0.0],  # 1 day at 1 m/s
            "slope": [0.01, 0.0, 0.0],
        }
    )
    params = network_params(topo, celerity_ms=1.0, x=0.2).set_index("id")
    assert params.loc[1, "k"] == pytest.approx(1.0)
    assert params.loc[1, "x"] == pytest.approx(0.2)
    assert params.loc[2, "k"] == 0.0  # zero length: direct pass-through
    # Cunge: area draining into the reach of 1 is 20 + 30 km²
    assert params.loc[1, "width"] == pytest.approx(1.5 * 50**0.5)
    assert params.loc[1, "q_ref"] == pytest.approx(50**0.7 / 3)
    assert params.loc[2, "slope"] == pytest.approx(1e-4)
    assert params.loc[1, "tuin"] == 50.0  # mogest-network 0.5 as %


def test_dem_cell_limit(tif):
    with pytest.raises(ValueError, match="células"):
        delineate(_station("foz", 100, 1), dem_bytes=tif, max_cells=1000)
    # 1° x 1° at 3" is 1200 x 1200 cells
    assert bbox_cells((-47.0, -24.0, -46.0, -23.0), 1 / 1200) == 1200 * 1200


def test_zip_round_trip_runs_network(result):
    with zipfile.ZipFile(io.BytesIO(export_zip(result))) as zf:
        names = set(zf.namelist())
        polygons = load_polygons(Upload(zf.read("subbacias.gpkg"), "subbacias.gpkg"))
        params = load_params(Upload(zf.read("parametros.csv"), "parametros.csv"))
    assert {"subbacias.gpkg", "parametros.csv", "rios.geojson"} <= names
    assert sorted(polygons["id"]) == sorted(result.params["id"])
    assert polygons.set_index("id")["name"].to_dict() == (
        result.params.set_index("id")["name"].to_dict()
    )

    template = pd.read_csv(io.BytesIO(series_template(params)), index_col=0)
    assert [int(c) for c in template.columns] == params["id"].tolist()
    index = pd.date_range("2020-01-01", periods=60, freq="D")
    ids = params["id"].tolist()
    rng = np.random.default_rng(0)
    prec = pd.DataFrame(rng.gamma(0.5, 10.0, (60, len(ids))), index=index, columns=ids)
    etp = pd.DataFrame(4.0, index=index, columns=ids)
    for method in ("muskingum", "muskingum_cunge"):
        total, natural = run_network_simulation(params, prec, etp, method=method)
        assert np.isfinite(total.to_numpy()).all()
        outlet = params.loc[params["downstream_id"].isna(), "id"].item()
        assert (total[outlet] >= natural[outlet] - 1e-9).all()


def test_nothing_written_to_disk(tif, tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    tmp = tmp_path / "tmp"
    cwd.mkdir()
    tmp.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.setenv("TMPDIR", str(tmp))

    res = delineate(
        _station("foz", 100, 1),
        [_station("posto_a", 100, 120)],
        dem_bytes=tif,
        river_threshold_km2=0.5,
    )
    with zipfile.ZipFile(io.BytesIO(export_zip(res))) as zf:
        load_polygons(Upload(zf.read("subbacias.gpkg"), "subbacias.gpkg"))
    basins = Path(__file__).parent.parent / "data" / "example_network_basins.geojson"
    load_polygons(Upload(basins.read_bytes(), "bacias.geojson"))

    assert list(cwd.iterdir()) == []
    assert list(tmp.iterdir()) == []


@pytest.mark.slow
def test_cachoeira_matches_mogest_network():
    # examples/cachoeira/config.yaml of mogest-network; areas from its
    # `mogest-network delinear` output (saidas/topologia.csv)
    res = delineate(
        Station("barragem_cachoeira", -23.050833, -46.319278),
        [Station("piracaia_montante", -23.0062, -46.2395)],
        buffer_km=25,
        area_min_km2=60,
        river_threshold_km2=2,
        max_snap_m=1500,
    )
    expected = {
        "barragem_cachoeira": 36.87556045625951,
        "piracaia_montante": 69.25500438925077,
        "sb001": 58.66935158818677,
        "sb002": 66.71614809980946,
        "sb003": 96.74273091615869,
        "sb004": 63.22596839613478,
    }
    areas = res.params.set_index("name")["area"]
    pd.testing.assert_series_equal(
        areas.sort_index(),
        pd.Series(expected).sort_index(),
        check_names=False,
        rtol=1e-6,
    )
    assert abs(areas.sum() / 392 - 1) <= 0.05  # SABESP: 392 km²

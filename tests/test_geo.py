import io
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from core.geo import (
    basin_links,
    load_polygons,
    missing_param_columns,
    polygons_to_params,
)
from core.io import load_params, load_timeseries
from core.models import run_network_simulation

DATA = Path("data")
BASINS = DATA / "example_network_basins.geojson"


class Upload(io.BytesIO):
    """Stand-in for a Streamlit UploadedFile."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _series(name: str) -> pd.DataFrame:
    df = load_timeseries(DATA / name)
    df.columns = [int(c) for c in df.columns]
    return df


def _zip_shapefile(gdf: gpd.GeoDataFrame, tmp_path: Path) -> Upload:
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    with pytest.warns(UserWarning, match="truncated"):
        gdf.to_file(shp_dir / "bacias.shp")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f"bacias/{f.name}")
    return Upload(buffer.getvalue(), "bacias.zip")


def test_example_polygons_area():
    gdf = load_polygons(BASINS)
    assert gdf["id"].tolist() == [1, 2]
    np.testing.assert_allclose(gdf["area_geom"], [50, 30], rtol=0.02)


@pytest.mark.filterwarnings("ignore:Normalized/laundered field name")
def test_formats_and_reprojection_agree(tmp_path):
    reference = load_polygons(BASINS)
    utm = gpd.read_file(BASINS).to_crs("EPSG:31983")  # SIRGAS 2000 / UTM 23S

    gpkg = tmp_path / "bacias.gpkg"
    utm.to_file(gpkg, driver="GPKG")
    loaded = [
        load_polygons(Upload(BASINS.read_bytes(), "bacias.geojson")),
        load_polygons(Upload(gpkg.read_bytes(), "bacias.gpkg")),
        load_polygons(_zip_shapefile(utm, tmp_path)),
    ]
    for gdf in loaded:
        assert gdf.crs.to_epsg() == 4326
        assert gdf["id"].tolist() == reference["id"].tolist()
        np.testing.assert_allclose(gdf.total_bounds, reference.total_bounds, atol=1e-6)
        np.testing.assert_allclose(gdf["area_geom"], reference["area_geom"], rtol=1e-6)
        # shapefile truncates downstream_id to "downstream"; read back under the alias
        assert gdf["downstream_id"].tolist()[1] == 1


def test_rejects_unknown_format_and_missing_id():
    with pytest.raises(ValueError, match="Formato"):
        load_polygons(Upload(b"", "bacias.kml"))
    gdf = gpd.read_file(BASINS).drop(columns="id")
    with pytest.raises(ValueError, match="id"):
        load_polygons(Upload(gdf.to_json(drop_id=True).encode(), "x.geojson"))


def test_polygons_with_attributes_replace_params_table():
    params_csv = load_params(DATA / "example_network_params.csv")
    gdf = load_polygons(BASINS)
    assert "str" in missing_param_columns(gdf)

    attrs = params_csv.drop(columns=["area", "downstream_id"])
    full = gdf.merge(attrs, on="id")
    assert missing_param_columns(full) == []
    params = polygons_to_params(full)
    np.testing.assert_allclose(params["area"], gdf["area_geom"])

    prec, etp = _series("example_network_prec.csv"), _series("example_network_etp.csv")
    total, _ = run_network_simulation(params, prec, etp)
    reference, _ = run_network_simulation(
        params_csv.assign(area=params["area"].to_numpy()), prec, etp
    )
    pd.testing.assert_frame_equal(total, reference)


def test_basin_links():
    gdf = load_polygons(BASINS)
    links = basin_links(gdf, gdf.set_index("id")["downstream_id"])
    assert links[["id", "downstream_id"]].values.tolist() == [[2, 1]]

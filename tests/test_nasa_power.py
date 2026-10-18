import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from core import nasa_power
from core.nasa_power import (
    ETO,
    IMERG_GRID,
    METEOROLOGY_GRID,
    PRECIPITATION,
    PROJECT_CITATION,
    PointSeries,
    areal_series,
    blocks,
    cell_weights,
    complete_period,
    eto_fao56,
    fetch_point,
)
from core.origin import file_origin, origins_json

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(nasa_power, "PAUSE_S", 0.0)


def test_meteorology_cell_of_jaguari():
    # dariOS SOP (2026-10-10): Barragem Jaguari falls in the cell (-23.0, -46.25)
    assert METEOROLOGY_GRID.center(-22.92, -46.42) == (-23.0, -46.25)


def test_imerg_cells_follow_tenth_degree_edges():
    # conferred on the API on 2026-10-17: the first two share a series
    assert IMERG_GRID.center(-23.02, -46.32) == (-23.05, -46.35)
    assert IMERG_GRID.center(-23.08, -46.32) == (-23.05, -46.35)
    assert IMERG_GRID.center(-23.02, -46.24) == (-23.05, -46.25)


def test_weights_split_polygon_between_cells():
    # meteorology cell edge at -22.75: half of the box on each side
    polygons = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(-46.3, -22.85, -46.2, -22.65)], crs="EPSG:4326"
    )
    weights = cell_weights(polygons, METEOROLOGY_GRID)
    assert sorted(weights["lat"]) == [-23.0, -22.5]
    assert weights["weight"].sum() == pytest.approx(1.0)
    assert weights["weight"].to_numpy() == pytest.approx([0.5, 0.5], abs=1e-3)


def test_weights_on_imerg_grid():
    polygons = gpd.GeoDataFrame(
        {"id": [7]}, geometry=[box(-46.40, -23.10, -46.20, -22.95)], crs="EPSG:4326"
    )
    weights = cell_weights(polygons, IMERG_GRID)
    assert len(weights) == 4  # 2 x 2 cells of 0.1°
    assert weights["weight"].sum() == pytest.approx(1.0)


def test_blocks_of_ten_years():
    assert blocks(dt.date(2001, 3, 1), dt.date(2020, 6, 30)) == [
        (dt.date(2001, 3, 1), dt.date(2010, 12, 31)),
        (dt.date(2011, 1, 1), dt.date(2020, 6, 30)),
    ]


def _body(start: dt.date, end: dt.date, value: float, fill_last: bool = False) -> dict:
    days = pd.date_range(start, end, freq="D")
    values = {f"{d:%Y%m%d}": value for d in days}
    if fill_last:
        values[f"{days[-1]:%Y%m%d}"] = -999.0
    return {
        "geometry": {"coordinates": [-46.25, -23.0, 919.21]},
        "properties": {"parameter": {"PRECTOTCORR": values}},
        "header": {
            "api": {"name": "POWER Daily API", "version": "v2.10.0"},
            "sources": ["MERRA2", "GEOSIT"],
            "time_standard": "LST",
        },
        "parameters": {"PRECTOTCORR": {"units": "mm/day"}},
    }


def test_fetch_point_joins_blocks_offline():
    calls = []

    def opener(url, timeout):
        calls.append(url)
        if "start=20100101" in url:
            return io.BytesIO(
                json.dumps(
                    _body(dt.date(2010, 1, 1), dt.date(2019, 12, 31), 1.0)
                ).encode()
            )
        return io.BytesIO(
            json.dumps(
                _body(dt.date(2020, 1, 1), dt.date(2020, 1, 5), 2.0, fill_last=True)
            ).encode()
        )

    point = fetch_point(
        -23.0,
        -46.25,
        ("PRECTOTCORR",),
        dt.date(2010, 1, 1),
        dt.date(2020, 1, 5),
        opener=opener,
    )
    assert len(calls) == 2
    assert "community=AG" in calls[0] and "time-standard=lst" in calls[0]
    series = point.data["PRECTOTCORR"]
    assert len(series) == 3652 + 5
    assert series.iloc[0] == 1.0 and series.iloc[-2] == 2.0
    assert np.isnan(series.iloc[-1])  # -999 becomes NaN
    assert point.elevation_m == 919.21
    assert point.api == "POWER Daily API v2.10.0"
    assert point.units == {"PRECTOTCORR": "mm/day"}
    assert point.sources == ["GEOSIT", "MERRA2"]


def test_eto_matches_mogest_network():
    # NASA POWER at the Cachoeira cell and the ETo of mogest-network
    # (pyet.pm_fao56), examples/cachoeira/{dados/met_nasa_power.csv,
    # saidas/etp_penman_pontos.csv}, year 2024
    met = pd.read_csv(DATA / "eto_cachoeira_2024.csv", index_col=0, parse_dates=True)
    eto = eto_fao56(met, -22.97, 919.21)
    np.testing.assert_allclose(eto, met["eto_pyet"], atol=1e-6)


def test_complete_period_cuts_edges_and_reports_gaps():
    index = pd.date_range("2020-01-01", periods=6, freq="D")
    frame = pd.DataFrame(
        {1: [np.nan, 1, 1, np.nan, 1, np.nan], 2: [1, 1, 1, 1, 1, 1]}, index=index
    )
    cut, gaps = complete_period(frame)
    assert cut.index[0] == index[1] and cut.index[-1] == index[4]
    assert gaps == [index[3]]


def _fake_fetch(values: dict, last_day_missing: bool = True):
    """fetch_point stand-in: constant series per cell, last day empty."""

    def fetch(lat, lon, parameters, start, end, time_standard):
        index = pd.date_range(start, end, freq="D", name="date")
        data = pd.DataFrame({p: values[(lat, lon)] for p in parameters}, index=index)
        if last_day_missing:
            data.iloc[-1] = np.nan
        return PointSeries(
            data=data,
            elevation_m=900.0,
            api="POWER Daily API v2.10.0",
            sources=["MERRA2"],
            time_standard=time_standard.upper(),
            units={p: "mm/day" for p in parameters},
            urls=[f"https://example.test/{lat},{lon}"],
        )

    return fetch


def test_areal_series_weighted_mean_and_origin():
    polygons = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[box(-46.3, -22.85, -46.2, -22.65), box(-46.3, -23.1, -46.2, -22.9)],
        crs="EPSG:4326",
    )
    fetch = _fake_fetch({(-23.0, -46.25): 2.0, (-22.5, -46.25): 4.0})
    series, gaps, origin = areal_series(
        polygons,
        PRECIPITATION["PRECTOTCORR"],
        dt.date(2020, 1, 1),
        dt.date(2020, 1, 10),
        entry="Precipitação",
        names={1: "a", 2: "b"},
        fetch=fetch,
        today=dt.date(2026, 10, 17),
    )
    assert list(series.columns) == [1, 2]
    assert len(series) == 9  # last day cut
    assert gaps == []
    assert series[1].iloc[0] == pytest.approx(3.0, abs=1e-2)  # half of each cell
    assert series[2].iloc[0] == pytest.approx(2.0)
    assert origin["origem"] == "NASA POWER"
    assert origin["periodo_com_dado"] == "2020-01-01 a 2020-01-09"
    assert origin["padrao_tempo"] == "LST"
    assert len(origin["celulas"]) == 2 and len(origin["urls"]) == 2
    assert {p["nome"] for p in origin["pesos"]} == {"a", "b"}
    assert origin["citacao"][0] == PROJECT_CITATION
    assert origin["citacao"][1] == (
        "The data was obtained from the POWER Project's Daily 2.10.0 version on "
        "2026/10/17."
    )
    json.loads(origins_json([origin]))  # serializable


def test_areal_series_eto_per_cell():
    met = pd.read_csv(DATA / "eto_cachoeira_2024.csv", index_col=0, parse_dates=True)

    def fetch(lat, lon, parameters, start, end, time_standard):
        assert time_standard == "lst" and set(parameters) <= set(met.columns)
        return PointSeries(
            met[list(parameters)], 919.21, "POWER Daily API v2.10.0", [], "LST", {}
        )

    polygons = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(-46.4, -23.1, -46.2, -22.95)], crs="EPSG:4326"
    )
    series, _, origin = areal_series(
        polygons,
        ETO,
        dt.date(2024, 1, 1),
        dt.date(2024, 12, 31),
        entry="ETP",
        fetch=fetch,
    )
    expected = eto_fao56(met, -23.0, 919.21)  # latitude of the cell centre
    np.testing.assert_allclose(series[1], expected)
    assert "calculo" in origin


def test_areal_series_limits():
    polygons = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(-47.5, -24.5, -44.5, -21.5)], crs="EPSG:4326"
    )
    with pytest.raises(ValueError, match="PRECTOTCORR"):
        areal_series(
            polygons,
            PRECIPITATION["IMERG_PRECTOT"],
            dt.date(2010, 1, 1),
            dt.date(2010, 12, 31),
            entry="Precipitação",
            fetch=_fake_fetch({}),
        )
    with pytest.raises(ValueError, match="1984"):
        areal_series(
            polygons, ETO, dt.date(1981, 1, 1), dt.date(1990, 1, 1), entry="ETP"
        )


def test_file_origin_identifies_upload():
    data = b"date,1\n2020-01-01,0\n"
    series = pd.DataFrame({1: [0.0]}, index=pd.to_datetime(["2020-01-01"]))
    origin = file_origin("Precipitação", "chuva.csv", data, series)
    assert origin["origem"] == "Arquivo enviado"
    assert origin["sha256"] == hashlib.sha256(data).hexdigest()
    assert origin["tamanho_bytes"] == len(data)
    assert origin["periodo"] == "2020-01-01 a 2020-01-01"


@pytest.mark.slow
def test_power_live_cachoeira_cell():
    polygons = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(-46.40, -23.10, -46.20, -22.95)], crs="EPSG:4326"
    )
    series, gaps, origin = areal_series(
        polygons,
        PRECIPITATION["PRECTOTCORR"],
        dt.date(2024, 1, 1),
        dt.date(2024, 12, 31),
        entry="Precipitação",
    )
    assert len(series) == 366 and not gaps
    assert 800 < series[1].sum() < 2500  # annual rain, mm
    assert origin["padrao_tempo"] == "LST"

import datetime as dt
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).parent.parent
PAGE = str(ROOT / "app" / "pages" / "2_Rede_Hidrologica.py")
SKIP = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
_PARAMS_TABLE = "Parâmetros dos Subcatchments"


def _files(root: Path) -> set:
    return {
        p.relative_to(root)
        for p in root.rglob("*")
        if not SKIP.intersection(p.relative_to(root).parts)
    }


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_example_network_runs():
    at = AppTest.from_file(PAGE).run(timeout=60)
    assert not at.exception
    assert _PARAMS_TABLE in [h.value for h in at.subheader]
    _button(at, "▶ Executar roteamento").click().run(timeout=60)
    assert not at.exception
    assert "network_result" in at.session_state


def test_delineation_mode_waits_for_points():
    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    assert not at.exception
    assert any("Delimitar sub-bacias" in i.value for i in at.info)


@pytest.mark.slow
def test_delineation_from_glo30_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = _files(ROOT)

    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=300)

    assert not at.exception
    assert not at.error
    result = at.session_state["delineation"]
    assert len(result.params) == 6  # Cachoeira, as in mogest-network
    assert at.metric[0].value == "6"

    # precipitation and ETo of 2024 from NASA POWER, then the simulation
    at.radio(key="prec_source").set_value("NASA POWER")
    at.radio(key="etp_source").set_value("NASA POWER")
    at.run(timeout=60)
    for kind, product in (("prec", "PRECTOTCORR"), ("etp", "ETO")):
        at.date_input(key=f"{kind}_power_start_{product}").set_value(
            dt.date(2024, 1, 1)
        )
        at.date_input(key=f"{kind}_power_end_{product}").set_value(
            dt.date(2024, 12, 31)
        )
        at.run(timeout=60)
        at.button(key=f"{kind}_power_go").click().run(timeout=300)
        assert not at.error
    _button(at, "▶ Executar roteamento").click().run(timeout=120)
    assert not at.exception
    assert len(at.session_state["network_result"]) == 366
    assert _files(ROOT) == before
    assert list(tmp_path.iterdir()) == []


def _fake_delineation(*_args, **_kwargs):
    """Two subcatchments near the Cachoeira dam, in the delineate() format."""
    import geopandas as gpd
    from shapely.geometry import Point, box

    from core.delineation import DelineationResult, network_params

    topology = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["barragem_cachoeira", "piracaia_montante"],
            "downstream_id": [float("nan"), 1.0],
            "area": [120.0, 270.0],
            "length": [8000.0, 0.0],
            "slope": [0.002, 0.003],
        }
    )
    polygons = gpd.GeoDataFrame(
        {"id": [1, 2], "name": topology["name"], "area_geom": topology["area"]},
        geometry=[
            box(-46.40, -23.10, -46.30, -22.95),
            box(-46.30, -23.10, -46.20, -22.95),
        ],
        crs="EPSG:4326",
    )
    outlets = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "name": topology["name"],
            "posto": [False, True],
            "dist_snap_m": [0.0, 30.0],
        },
        geometry=[Point(-46.319, -23.051), Point(-46.2395, -23.0062)],
        crs="EPSG:4326",
    )
    rivers = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return DelineationResult(
        polygons,
        network_params(topology),
        outlets,
        rivers,
        (-46.6, -23.3, -46.0, -22.8),
        False,
    )


def _fake_power(lat, lon, parameters, start, end, time_standard="lst", opener=None):
    from core.nasa_power import PointSeries

    index = pd.date_range(start, end, freq="D", name="date")
    values = {
        "PRECTOTCORR": 4.0,
        "IMERG_PRECTOT": 4.0,
        "T2M": 20.0,
        "T2M_MAX": 26.0,
        "T2M_MIN": 15.0,
        "RH2M": 75.0,
        "WS2M": 1.5,
        "ALLSKY_SFC_SW_DWN": 18.0,
        "PS": 91.0,
    }
    data = pd.DataFrame({p: values[p] for p in parameters}, index=index)
    data.iloc[-3:] = float("nan")  # POWER leaves the last days empty
    return PointSeries(data, 919.21, "POWER Daily API v2.10.0", ["MERRA2"], "LST", {})


def test_delineation_with_nasa_power_offline(monkeypatch):
    import streamlit as st

    import core.delineation
    import core.nasa_power

    st.cache_data.clear()
    monkeypatch.setattr(core.delineation, "delineate", _fake_delineation)
    monkeypatch.setattr(core.nasa_power, "fetch_point", _fake_power)
    monkeypatch.setattr(core.nasa_power, "PAUSE_S", 0.0)

    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=60)
    assert not at.exception

    at.radio(key="prec_source").set_value("NASA POWER")
    at.radio(key="etp_source").set_value("NASA POWER")
    at.run(timeout=60)
    at.button(key="prec_power_go").click().run(timeout=60)
    at.button(key="etp_power_go").click().run(timeout=60)
    assert not at.exception
    assert not at.error
    assert any("Período com dado" in w.value for w in at.warning)
    # the delineation already shows the parameters
    assert _PARAMS_TABLE not in [h.value for h in at.subheader]

    _button(at, "▶ Executar roteamento").click().run(timeout=60)
    assert not at.exception
    assert "network_result" in at.session_state
    origins = at.session_state["network_origins"]
    assert [o["origem"] for o in origins][1:] == ["NASA POWER", "NASA POWER"]
    assert origins[0]["entrada"] == "Sub-bacias e parâmetros"
    assert origins[2]["produto"].startswith("ETo FAO-56")


def test_new_outlet_clears_upstream_stations(monkeypatch):
    import core.delineation

    calls = []

    def fake(outlet, stations, **kwargs):
        calls.append([s.id for s in stations])
        return _fake_delineation()

    monkeypatch.setattr(core.delineation, "delineate", fake)

    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)

    # renaming the outlet keeps the example station
    at.text_input(key="dl_outlet_id").set_value("cachoeira").run(timeout=60)
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=60)
    assert calls[-1] == ["piracaia_montante"]

    # moving it clears the table
    at.number_input(key="dl_lat").set_value(-22.9).run(timeout=60)
    assert not at.exception
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=60)
    assert calls[-1] == []

    # back at the example outlet (as after leaving the mode in the browser),
    # the example station comes back
    at.number_input(key="dl_lat").set_value(-23.050833).run(timeout=60)
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=60)
    assert calls[-1] == ["piracaia_montante"]


def _fake_inventory(*_args, **_kwargs):
    return pd.DataFrame(
        {
            "codigo": ["62666010", "62664500", "99999999"],
            "nome": ["SB-CA-BRC Barragem Cachoeira", "CACHOEIRA MONTANTE", "LONGE"],
            "rio": ["RIO DA CACHOEIRA"] * 2 + ["OUTRO"],
            "municipio": ["PIRACAIA"] * 3,
            "estado": ["SÃO PAULO"] * 3,
            "responsavel": ["SABESP", "SPÁGUAS-SP", "ANA"],
            "operadora": ["SABESP", "SPÁGUAS-SP", "ANA"],
            "area_km2": [392.0, float("nan"), 10.0],
            "lat": [-23.0508, -23.0064, -10.0],
            "lon": [-46.3192, -46.2397, -50.0],
            "casas_coord": [4, 4, 1],
            "operando": [True, True, False],
        }
    )


def _click_ana(at: AppTest, code: str):
    at.session_state["delineation_map"] = {
        "selection": {"points": [{"customdata": ["ana", code]}]}
    }
    return at.run(timeout=60)


def test_ana_station_as_outlet_and_upstream(monkeypatch):
    import streamlit as st

    import core.ana

    st.cache_data.clear()
    monkeypatch.setattr(core.ana, "fetch_inventory", _fake_inventory)

    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    at.checkbox(key="dl_ana").check().run(timeout=60)
    assert not at.exception
    # only the two stations inside the window
    assert any("2 postos da ANA na janela" in c.value for c in at.caption)

    _click_ana(at, "62666010")
    at.button(key="dl_ana_outlet").click().run(timeout=60)
    assert not at.exception
    assert at.text_input(key="dl_outlet_id").value == "62666010"
    assert at.number_input(key="dl_lat").value == pytest.approx(-23.0508)

    _click_ana(at, "62664500")
    at.button(key="dl_ana_station").click().run(timeout=60)
    assert not at.exception
    stations = at.session_state["dl_stations_last"]
    # the new outlet cleared the example station; the ANA one was added
    assert stations["id"].tolist() == ["62664500"]
    # clicking it again: it is already a point, so both buttons are off
    _click_ana(at, "62664500")
    assert at.button(key="dl_ana_station").disabled

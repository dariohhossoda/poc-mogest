import numpy as np
import pandas as pd
import pytest

from core.calibration import (
    calibrate_network,
    calibration_order,
    downstream_map,
    evaluations_per_gauge,
    gauge_groups,
    match_observed_columns,
    observed_by_basin,
    parameter_bounds,
)
from core.models import run_network_simulation

# 3 -> 2 -> 1 (outlet) <- 4
_TOPOLOGY = {1: None, 2: 1, 3: 2, 4: 1}
_TRUE = {  # str, kkt per group
    "upstream": (900.0, 120.0),
    "downstream": (300.0, 50.0),
}


def _params(values: dict | None = None) -> pd.DataFrame:
    rows = []
    for sid, ds in _TOPOLOGY.items():
        str_, kkt = (values or {}).get(sid, (500.0, 90.0))
        rows.append(
            {
                "id": sid,
                "name": f"posto_{sid}",
                "area": 100.0 + 10 * sid,
                "str": str_,
                "crec": 5.0,
                "capc": 40.0,
                "kkt": kkt,
                "k2t": 2.0,
                "ai": 2.5,
                "tuin": 50.0,
                "ebin": 1.0,
                "k": 1.0,
                "x": 0.2,
                "downstream_id": -999 if ds is None else ds,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def forcing():
    rng = np.random.default_rng(0)
    index = pd.date_range("2020-01-01", periods=3 * 365, freq="D", name="date")
    wet = rng.random((len(index), 4)) < 0.3
    prec = pd.DataFrame(
        np.where(wet, rng.gamma(0.8, 15.0, (len(index), 4)), 0.0),
        index=index,
        columns=list(_TOPOLOGY),
    )
    etp = pd.DataFrame(3.5, index=index, columns=list(_TOPOLOGY))
    return prec, etp


def test_groups_and_order():
    ds = downstream_map(_params())
    assert ds == _TOPOLOGY
    assert gauge_groups(ds, [1, 2]) == {1: 1, 2: 2, 3: 2, 4: 1}
    assert gauge_groups(ds, [2]) == {1: None, 2: 2, 3: 2, 4: None}
    assert calibration_order(ds, [1, 2]) == [2, 1]
    assert calibration_order(ds, [2, 1]) == [2, 1]


def test_bounds_and_evaluations():
    bounds = parameter_bounds()
    assert bounds["str"] == (100, 2000)
    assert set(bounds) == {"str", "crec", "capc", "kkt", "k2t", "ai"}
    assert evaluations_per_gauge(6, "fast") == 8 * 6 * 21


def test_match_observed_columns_by_id_and_name():
    obs = pd.DataFrame(columns=["1", "posto_2", "3.0", "outro", "posto_1"])
    matched, unmatched = match_observed_columns(obs, _params())
    assert matched == {"1": 1, "posto_2": 2, "3.0": 3}
    assert unmatched == ["outro", "posto_1"]  # posto_1 repeats subcatchment 1


def test_observed_negative_is_missing():
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    obs = pd.DataFrame({"a": [1.0, -999.0, 2.0]}, index=index[:3])
    out = observed_by_basin(
        obs, {"a": 7}, index.append(pd.DatetimeIndex(["2020-01-04"]))
    )
    assert list(out.columns) == [7]
    assert out[7].isna().tolist() == [False, True, False, True]


def _truth(prec, etp):
    up, down = _TRUE["upstream"], _TRUE["downstream"]
    params = _params({2: up, 3: up, 1: down, 4: down})
    total, _ = run_network_simulation(params, prec, etp)
    return total


def test_twin_experiment_recovers_both_gauges(forcing):
    prec, etp = forcing
    observed = _truth(prec, etp)[[1, 2]]
    observed.iloc[400:430, 1] = np.nan  # gap in the upstream gauge
    result = calibrate_network(
        _params(),
        prec,
        etp,
        observed,
        ["str", "kkt"],
        calibration=("2020-07-01", "2021-12-31"),
        seed=1,
        optimizer={"popsize": 10, "maxiter": 25},
    )
    assert list(result.metrics.index) == [2, 1]
    assert (result.metrics["KGE calibração"] > 0.97).all()
    assert (result.metrics["KGE validação"] > 0.95).all()
    assert result.metrics.loc[2, "Sub-bacias"] == 2
    assert result.metrics.loc[2, "Dias calibração"] == 549 - 30
    by_id = result.params.set_index("id")
    # Each group shares one parameter set
    assert by_id.loc[2, "str"] == by_id.loc[3, "str"]
    assert by_id.loc[1, "kkt"] == by_id.loc[4, "kkt"]
    assert by_id.loc[2, "str"] != by_id.loc[1, "str"]
    # Non-calibrated columns untouched, same rows and columns as the input
    assert list(result.params.columns) == list(_params().columns)
    assert (result.params["crec"] == 5.0).all()


def test_ungauged_outlet_inherits_upstream_parameters(forcing):
    prec, etp = forcing
    observed = _truth(prec, etp)[[2]]
    result = calibrate_network(
        _params(),
        prec,
        etp,
        observed,
        ["str"],
        calibration=("2020-01-01", "2022-12-31"),
        seed=1,
        optimizer={"popsize": 5, "maxiter": 5},
    )
    by_id = result.params.set_index("id")
    assert result.inherited == {1: 2}
    assert by_id.loc[1, "str"] == by_id.loc[2, "str"]
    assert by_id.loc[4, "str"] == 500.0  # no gauge upstream: kept
    assert np.isnan(result.metrics.loc[2, "KGE validação"])  # no validation days


def test_progress_is_reported(forcing):
    prec, etp = forcing
    observed = _truth(prec, etp)[[1, 2]]
    calls = []
    calibrate_network(
        _params(),
        prec,
        etp,
        observed,
        ["kkt"],
        calibration=("2020-07-01", "2021-12-31"),
        seed=1,
        optimizer={"popsize": 4, "maxiter": 3, "tol": 0},
        on_progress=lambda *a: calls.append(a),
    )
    assert [(c[0], c[2], c[3]) for c in calls] == [
        (0, 2, 1), (0, 2, 2), (0, 2, 3), (1, 1, 1), (1, 1, 2), (1, 1, 3),
    ]  # fmt: skip


def test_short_calibration_period_is_refused(forcing):
    prec, etp = forcing
    observed = _truth(prec, etp)[[1]]
    with pytest.raises(ValueError, match="só 10 dias"):
        calibrate_network(
            _params(), prec, etp, observed, ["str"],
            calibration=("2021-01-01", "2021-01-10"),
        )  # fmt: skip

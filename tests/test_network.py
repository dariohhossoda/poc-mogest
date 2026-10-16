from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.io import load_params, load_timeseries
from core.models import run_network_simulation

DATA = Path("data")
EXPECTED = Path("tests/data/expected_network_example.csv")


def _series(name: str) -> pd.DataFrame:
    df = load_timeseries(DATA / name)
    df.columns = [int(c) for c in df.columns]
    return df


@pytest.fixture
def example():
    return (
        load_params(DATA / "example_network_params.csv"),
        _series("example_network_prec.csv"),
        _series("example_network_etp.csv"),
    )


def test_matches_previous_implementation(example):
    # Output of the in-app SMAP + Muskingum loop replaced by mogestpy.run_network
    expected = pd.read_csv(EXPECTED, index_col=0, parse_dates=True)
    expected.columns = [int(c) for c in expected.columns]
    total, _ = run_network_simulation(*example)
    pd.testing.assert_frame_equal(
        total[expected.columns], expected, check_freq=False, check_names=False
    )


def test_natural_flow_of_headwater_equals_total(example):
    total, natural = run_network_simulation(*example)
    np.testing.assert_allclose(total[2], natural[2])
    assert (total[1] >= natural[1] - 1e-9).all()


def test_minus_999_is_outlet(example):
    params, prec, etp = example
    params = params.copy()
    params["downstream_id"] = params["downstream_id"].fillna(-999)
    total, _ = run_network_simulation(params, prec, etp)
    assert set(total.columns) == {1, 2}


def test_muskingum_cunge_runs(example):
    total, natural = run_network_simulation(*example, method="muskingum_cunge")
    assert total.shape == natural.shape
    assert np.isfinite(total.to_numpy()).all()
    assert total[1].sum() >= natural[1].sum()


def test_muskingum_cunge_requires_reach_columns(example):
    params, prec, etp = example
    params = params.drop(columns=["length"])
    with pytest.raises(ValueError, match="length"):
        run_network_simulation(params, prec, etp, method="muskingum_cunge")

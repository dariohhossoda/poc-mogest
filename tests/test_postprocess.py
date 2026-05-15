import numpy as np
import pytest

from core.postprocess import kge, nash_sutcliffe, peak_flow, runoff_volume


def test_nse_perfect():
    obs = [1.0, 2.0, 3.0, 4.0]
    assert nash_sutcliffe(obs, obs) == pytest.approx(1.0)


def test_nse_mean_predictor_is_zero():
    obs = [1.0, 2.0, 3.0, 4.0]
    sim = [np.mean(obs)] * 4
    assert nash_sutcliffe(obs, sim) == pytest.approx(0.0)


def test_kge_perfect():
    obs = [1.0, 2.0, 3.0, 4.0]
    assert kge(obs, obs) == pytest.approx(1.0)


def test_peak_flow():
    assert peak_flow([1.0, 5.0, 3.0, 2.0]) == pytest.approx(5.0)


def test_runoff_volume_units():
    # 1 m³/s over 1 day = 86 400 m³ = 0.0864 hm³
    assert runoff_volume([1.0], dt_seconds=86400) == pytest.approx(0.0864, rel=1e-3)

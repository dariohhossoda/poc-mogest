from core.models import run_smap_daily, run_smap_monthly

PREC_D = [0.0, 10.0, 5.0, 0.0, 20.0, 0.0, 0.0, 8.0, 0.0, 3.0] * 6  # 60 days
ETP_D = [3.5] * 60

PREC_M = [180.0, 165.0, 140.0, 55.0, 20.0, 5.0, 3.0, 8.0, 35.0, 98.0, 145.0, 190.0] * 2
ETP_M = [85.0, 78.0, 82.0, 90.0, 95.0, 99.0, 102.0, 100.0, 94.0, 88.0, 84.0, 83.0] * 2


def test_smap_daily_output_length():
    result = run_smap_daily({}, PREC_D, ETP_D)
    assert len(result) == len(PREC_D)


def test_smap_daily_non_negative():
    result = run_smap_daily({}, PREC_D, ETP_D)
    assert all(v >= 0 for v in result)


def test_smap_monthly_output_length():
    result = run_smap_monthly({}, PREC_M, ETP_M)
    assert len(result) == len(PREC_M)


def test_smap_monthly_non_negative():
    result = run_smap_monthly({}, PREC_M, ETP_M)
    assert all(v >= 0 for v in result)


def test_fast_calibration_recovers_kge():
    from core.models import calibrate_smap_daily

    true_params = {"Str": 400.0, "kkt": 60.0}
    obs = run_smap_daily(true_params, PREC_D, ETP_D)
    calibrated, kge_value = calibrate_smap_daily(
        {}, PREC_D, ETP_D, obs, ["Str", "kkt"], fast=True
    )
    assert set(calibrated) == {"Str", "kkt"}
    assert kge_value > 0.9

import pandas as pd
from mogestpy.quantity.hydrological.muskingum import MuskingumCunge
from mogestpy.quantity.hydrological.routing import run_network
from mogestpy.quantity.hydrological.smap import SmapD, SmapM


def run_smap_daily(params: dict, prec: list, etp: list) -> list[float]:
    return SmapD(**params).run_to_list(prec, etp)


def run_smap_monthly(params: dict, prec: list, etp: list) -> list[float]:
    return SmapM(**params).run_to_list(prec, etp)


def calibrate_smap_daily(
    params: dict,
    prec: list,
    etp: list,
    obs: list,
    variables: list[str],
    fast: bool = False,
) -> tuple[dict, float]:
    """Returns (calibrated_params, KGE). ``fast`` uses integer DE (4 decimals)."""
    model = SmapD(**params)
    calibrate = model.fast_calibrate if fast else model.calibrate
    result = calibrate(prec, etp, obs, variables)
    calibrated = {**params, **dict(zip(variables, result.x))}
    return calibrated, float(-result.fun)


def calibrate_smap_monthly(
    params: dict,
    prec: list,
    etp: list,
    obs: list,
    variables: list[str],
    fast: bool = False,
) -> tuple[dict, float]:
    """Returns (calibrated_params, KGE). ``fast`` uses integer DE (4 decimals)."""
    model = SmapM(**params)
    calibrate = model.fast_calibrate if fast else model.calibrate
    result = calibrate(prec, etp, obs, variables)
    calibrated = {**params, **dict(zip(variables, result.x))}
    return calibrated, float(-result.fun)


CUNGE_COLUMNS = ("length", "q_ref", "manning", "width", "slope")


def run_network_simulation(
    params_df: pd.DataFrame,
    prec_df: pd.DataFrame,
    etp_df: pd.DataFrame,
    method: str = "muskingum",
    verbose: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    SMAP + routing over a network of subcatchments (mogestpy ``run_network``).

    params_df columns: id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x,
    downstream_id; ``tuin`` in percent (0-100). ``downstream_id`` empty or -999
    marks an outlet. Muskingum-Cunge also needs CUNGE_COLUMNS: reach length (m),
    reference discharge (m³/s), Manning n, channel width (m) and slope (m/m) of
    the reach crossing the subcatchment that receives the upstream flow.
    prec_df / etp_df: indexed by time, columns = subcatchment id
    method: "muskingum" (linear, k and x) or "muskingum_cunge"
    Returns (total, natural): discharge (m³/s) per subcatchment, with and
    without upstream contribution.
    """
    params_df = params_df.copy()
    params_df["downstream_id"] = pd.to_numeric(
        params_df["downstream_id"], errors="coerce"
    ).replace(-999, float("nan"))

    if method == "muskingum_cunge":
        missing = [c for c in CUNGE_COLUMNS if c not in params_df.columns]
        if missing:
            raise ValueError(f"Muskingum-Cunge requires parameter columns: {missing}.")
        router = MuskingumCunge.router()
    elif method == "muskingum":
        router = None
    else:
        raise ValueError(f"Unknown routing method: {method}.")

    return run_network(
        params_df,
        prec_df,
        etp_df,
        verbose=verbose,
        router=router,
        return_natural_flow=True,
    )

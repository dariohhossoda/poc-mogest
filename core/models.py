import pandas as pd
from mogestpy.quantity.hydrological.smap import SmapD, SmapM
from mogestpy.quantity.hydrological.routing import run_network


def run_smap_daily(params: dict, prec: list, etp: list) -> list[float]:
    return SmapD(**params).run_to_list(prec, etp)


def run_smap_monthly(params: dict, prec: list, etp: list) -> list[float]:
    return SmapM(**params).run_to_list(prec, etp)


def run_network_simulation(
    params_df: pd.DataFrame,
    prec_df: pd.DataFrame,
    etp_df: pd.DataFrame,
    verbose: bool = False,
) -> pd.DataFrame:
    return run_network(params_df, prec_df, etp_df, verbose=verbose)

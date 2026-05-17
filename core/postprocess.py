import numpy as np
import pandas as pd


def nash_sutcliffe(obs: list, sim: list) -> float:
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    return float(1 - np.sum((obs - sim) ** 2) / np.sum((obs - obs.mean()) ** 2))


def kge(obs: list, sim: list) -> float:
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    r = float(np.corrcoef(obs, sim)[0, 1])
    alpha = float(sim.std() / obs.std())
    beta = float(sim.mean() / obs.mean())
    return float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def peak_flow(series: list) -> float:
    return float(np.max(series))


def runoff_volume(series: list, dt_seconds: float = 86400.0) -> float:
    """Cumulative volume in hm³."""
    return float(np.sum(series) * dt_seconds / 1e6)


def annual_stats(
    sim: list,
    index,
    obs: list | None = None,
    dt_seconds: float = 86400.0,
) -> pd.DataFrame:
    """
    Annual summary statistics grouped by year.
    Only includes years with >= 90 % of expected records
    (365 steps for daily, 12 for monthly).
    Returns empty DataFrame when the series is too short.
    """
    idx = pd.DatetimeIndex(index)
    df_sim = pd.DataFrame({"sim": sim}, index=idx)
    obs_series = pd.Series(obs, index=idx) if obs is not None else None
    expected = 365 if dt_seconds <= 86400 else 12

    rows = []
    for year, grp in df_sim.groupby(df_sim.index.year):
        if len(grp) < expected * 0.9:
            continue
        row: dict = {
            "Ano": int(year),
            "Média (m³/s)": round(float(grp["sim"].mean()), 3),
            "Pico (m³/s)": round(float(grp["sim"].max()), 3),
            "Volume (hm³)": round(float(grp["sim"].sum() * dt_seconds / 1e6), 3),
        }
        if obs_series is not None:
            obs_yr = obs_series[obs_series.index.year == year]
            sim_yr = grp["sim"]
            if len(obs_yr) == len(sim_yr):
                row["NSE"] = round(nash_sutcliffe(obs_yr.tolist(), sim_yr.tolist()), 3)
                row["KGE"] = round(kge(obs_yr.tolist(), sim_yr.tolist()), 3)
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Ano")

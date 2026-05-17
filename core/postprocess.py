import numpy as np


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

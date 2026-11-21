"""
Calibration of the SMAP parameters of a network against observed discharge.

Group strategy of mogest-network (``src/mogest_network/calibracao.py``),
rewritten on top of the app's simulation (``run_network`` from mogestpy):

- Group of a gauge: the subcatchments whose first gauge downstream, counting
  the subcatchment itself, is that gauge. They share the SMAP parameters.
- Groups are calibrated from upstream to downstream. Each group simulates only
  its own subcatchments; the total flow of the upstream groups, already
  calibrated, enters as a fixed external inflow (``external_inflows``).
- Subcatchments below every gauge take the parameters of the upstream gauge
  with the largest drainage area (or keep theirs, when no gauge is upstream).
- Optimizer: ``scipy.optimize.differential_evolution``, objective KGE over the
  calibration period. The rest of the observed period is validation.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from mogestpy.quantity.hydrological.smap import SmapD
from scipy.optimize import differential_evolution

from core.models import network_router, prepare_network_params, run_network_simulation
from core.postprocess import kge, nash_sutcliffe

# Parameter column -> name in SmapD.bounds()
CALIBRATABLE = {
    "str": "Str",
    "crec": "Crec",
    "capc": "Capc",
    "kkt": "kkt",
    "k2t": "k2t",
    "ai": "Ai",
}

# Differential evolution settings per mode; evaluations per gauge are at most
# popsize * n_parameters * (maxiter + 1).
MODES = {
    "fast": {"popsize": 8, "maxiter": 20},
    "full": {"popsize": 15, "maxiter": 60},
}

MIN_CALIBRATION_DAYS = 30
_PENALTY = 10.0


def parameter_bounds() -> dict[str, tuple[float, float]]:
    """Bounds of the calibrated columns, from ``SmapD.bounds()``."""
    base = SmapD().bounds()
    return {col: tuple(base[name]) for col, name in CALIBRATABLE.items()}


# region: topology


def downstream_map(params: pd.DataFrame) -> dict:
    """Subcatchment id -> downstream id, or None at an outlet."""
    ds = prepare_network_params(params).set_index("id")["downstream_id"]
    return {sid: (None if pd.isna(d) else type(sid)(d)) for sid, d in ds.items()}


def upstream_sets(downstream: dict) -> dict:
    """Subcatchment id -> set of every subcatchment upstream of it (itself included)."""
    ups = {sid: {sid} for sid in downstream}
    for sid in downstream:
        current = downstream[sid]
        while current is not None:
            ups[current].add(sid)
            current = downstream[current]
    return ups


def gauge_groups(downstream: dict, gauges) -> dict:
    """Subcatchment id -> first gauge downstream (itself included), or None."""
    gauges = set(gauges)
    groups = {}
    for sid in downstream:
        current = sid
        while current is not None and current not in gauges:
            current = downstream[current]
        groups[sid] = current
    return groups


def calibration_order(downstream: dict, gauges) -> list:
    """Gauges from upstream to downstream (a gauge upstream of another comes first)."""
    ups = upstream_sets(downstream)
    return sorted(gauges, key=lambda g: (len(ups[g]), str(g)))


def drainage_area(params: pd.DataFrame, downstream: dict) -> dict:
    """Subcatchment id -> area (km²) upstream of it, itself included."""
    area = params.set_index("id")["area"].astype(float)
    return {
        sid: float(area[list(s)].sum()) for sid, s in upstream_sets(downstream).items()
    }


# endregion

# region: observed data


def match_observed_columns(
    obs: pd.DataFrame, params: pd.DataFrame
) -> tuple[dict, list]:
    """
    Observed column -> subcatchment id, by id or by ``name``.

    Returns (matched, unmatched): matched columns and the names of the others.
    """
    ids = params["id"].tolist()
    by_text = {str(i): i for i in ids}
    if "name" in params.columns:
        for sid, name in zip(ids, params["name"]):
            by_text.setdefault(str(name).strip(), sid)
    matched, unmatched = {}, []
    for col in obs.columns:
        text = str(col).strip()
        sid = by_text.get(text)
        if sid is None:
            try:
                sid = by_text.get(str(int(float(text))))
            except ValueError:
                sid = None
        if sid is None or sid in matched.values():
            unmatched.append(col)
        else:
            matched[col] = sid
    return matched, unmatched


def observed_by_basin(
    obs: pd.DataFrame, mapping: dict, index: pd.Index
) -> pd.DataFrame:
    """Observed discharge (m³/s) on the simulation index, one column per gauge."""
    frame = obs[list(mapping)].rename(columns=mapping)
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.where(frame >= 0)  # negative values are missing-data flags
    return frame.reindex(index)


# endregion

# region: calibration


@dataclass
class CalibrationResult:
    params: pd.DataFrame
    """Calibrated parameters, same columns and order as the input."""
    metrics: pd.DataFrame
    """One row per gauge: group size, KGE and NSE in calibration and validation."""
    simulated: pd.DataFrame
    """Total discharge at each gauge with the calibrated parameters."""
    observed: pd.DataFrame
    """Observed discharge at each gauge on the simulation index."""
    groups: dict
    """Subcatchment id -> gauge of its group (None: inherited or kept)."""
    inherited: dict = field(default_factory=dict)
    """Ungauged subcatchment id -> gauge whose parameters it took."""


class _GroupObjective:
    """-KGE at the gauge, one parameter vector for every subcatchment of a group."""

    def __init__(
        self, sub_params, columns, prec, etp, external, router, gauge, obs, mask
    ):
        self.sub_params = sub_params
        self.columns = columns
        self.prec = prec
        self.etp = etp
        self.external = external
        self.router = router
        self.gauge = gauge
        self.obs = obs[mask]
        self.mask = mask

    def params_for(self, vector) -> pd.DataFrame:
        params = self.sub_params.copy()
        params.loc[:, self.columns] = np.broadcast_to(
            np.asarray(vector, float), (len(params), len(self.columns))
        )
        return params

    def simulate(self, vector) -> np.ndarray:
        from mogestpy.quantity.hydrological.routing import run_network

        total = run_network(
            self.params_for(vector),
            self.prec,
            self.etp,
            external_inflows=self.external,
            router=self.router,
        )
        return total[self.gauge].to_numpy()

    def __call__(self, vector) -> float:
        sim = self.simulate(vector)[self.mask]
        with np.errstate(all="ignore"):
            value = kge(self.obs, sim)
        return -value if np.isfinite(value) else _PENALTY


def _progress_callback(on_progress, i: int, n: int, gauge, settings: dict):
    """DE callback: scipy passes the result only to a sole ``intermediate_result``."""
    generation = 0

    def callback(intermediate_result):
        nonlocal generation
        generation += 1
        if on_progress is not None:
            best = -float(intermediate_result.fun)
            on_progress(i, n, gauge, generation, settings["maxiter"], best)

    return callback


def _metrics(obs: np.ndarray, sim: np.ndarray, mask: np.ndarray) -> tuple:
    mask = mask & np.isfinite(obs)
    if mask.sum() < 2:
        return np.nan, np.nan, int(mask.sum())
    with np.errstate(all="ignore"):
        return (
            kge(obs[mask], sim[mask]),
            nash_sutcliffe(obs[mask], sim[mask]),
            int(mask.sum()),
        )


def calibrate_network(
    params: pd.DataFrame,
    prec: pd.DataFrame,
    etp: pd.DataFrame,
    observed: pd.DataFrame,
    columns: list[str],
    calibration: tuple,
    method: str = "muskingum",
    mode: str = "fast",
    seed: int | None = None,
    on_progress: Callable[[int, int, object, int, int, float], None] | None = None,
    optimizer: dict | None = None,
) -> CalibrationResult:
    """
    Calibrate the SMAP parameters of a network, group by group.

    Parameters
    ----------
    params : pd.DataFrame
        Network parameters, as in ``run_network_simulation``.
    prec, etp : pd.DataFrame
        Forcing, one column per subcatchment id, on the same index.
    observed : pd.DataFrame
        Observed discharge (m³/s) on the forcing index, one column per gauged
        subcatchment id (see ``observed_by_basin``). NaN marks a missing day.
    columns : list of str
        Parameter columns to calibrate (keys of ``CALIBRATABLE``).
    calibration : tuple
        (first, last) day of the calibration period, both included. Observed
        days outside it are the validation period; the simulation always
        starts at the first forcing day, which works as warm-up.
    method : str
        Routing method ("muskingum" or "muskingum_cunge").
    mode : str
        Key of ``MODES``.
    seed : int, optional
        Seed of the differential evolution.
    on_progress : callable, optional
        Called after each generation as ``on_progress(i, n, gauge, generation,
        maxiter, best_kge)``, with ``i`` the 0-based position of the gauge.
    optimizer : dict, optional
        Overrides the ``MODES`` settings of ``differential_evolution``.

    Returns
    -------
    CalibrationResult
    """
    unknown = [c for c in columns if c not in CALIBRATABLE]
    if unknown or not columns:
        raise ValueError(
            f"Parâmetros não calibráveis: {unknown or 'nenhum escolhido'}."
        )
    params = params.copy()
    base = prepare_network_params(params)
    router = network_router(base, method)
    downstream = downstream_map(base)
    gauges = [g for g in observed.columns if g in downstream]
    if not gauges:
        raise ValueError("Nenhuma coluna observada corresponde a uma sub-bacia.")
    observed = observed[gauges].reindex(prec.index)

    first, last = pd.Timestamp(calibration[0]), pd.Timestamp(calibration[1])
    cal_mask = np.asarray((prec.index >= first) & (prec.index <= last))
    for g in gauges:
        n = int((cal_mask & observed[g].notna().to_numpy()).sum())
        if n < MIN_CALIBRATION_DAYS:
            raise ValueError(
                f"Sub-bacia {g}: só {n} dias observados no período de calibração "
                f"(mínimo {MIN_CALIBRATION_DAYS})."
            )

    bounds = parameter_bounds()
    settings = {**MODES[mode], **(optimizer or {})}
    groups = gauge_groups(downstream, gauges)
    order = calibration_order(downstream, gauges)
    ups = upstream_sets(downstream)
    base = base.set_index("id", drop=False)

    for i, gauge in enumerate(order):
        ids = [s for s, g in groups.items() if g == gauge]
        sub = base.loc[ids].copy()
        sub.loc[gauge, "downstream_id"] = np.nan  # the gauge is the outlet of the run
        entering = {
            u: downstream[u] for u in ups[gauge] - set(ids) if downstream[u] in ids
        }
        external = None
        if entering:
            upstream_ids = sorted(ups[gauge] - set(ids), key=str)
            upstream = base.loc[upstream_ids].copy()
            for u in upstream_ids:
                if downstream[u] in ids:
                    upstream.loc[u, "downstream_id"] = np.nan
            total = run_network_simulation(
                upstream.reset_index(drop=True),
                prec[upstream_ids],
                etp[upstream_ids],
                method=method,
            )[0]
            external = pd.DataFrame(
                0.0, index=prec.index, columns=sorted(set(entering.values()), key=str)
            )
            for u, receiver in entering.items():
                external[receiver] += total[u]
        obs = observed[gauge].to_numpy(dtype=float)
        objective = _GroupObjective(
            sub.reset_index(drop=True), columns, prec[ids], etp[ids], external, router,
            gauge, obs, cal_mask & np.isfinite(obs),
        )  # fmt: skip

        result = differential_evolution(
            objective,
            [bounds[c] for c in columns],
            seed=seed,
            polish=False,
            callback=_progress_callback(on_progress, i, len(order), gauge, settings),
            **settings,
        )
        base.loc[ids, columns] = np.asarray(result.x, float)

    # Ungauged subcatchments below every gauge
    area = drainage_area(base.reset_index(drop=True), downstream)
    inherited = {}
    for sid, g in groups.items():
        if g is not None:
            continue
        candidates = [p for p in gauges if p in ups[sid]]
        if candidates:
            source = max(candidates, key=lambda p: area[p])
            base.loc[sid, columns] = base.loc[source, columns].to_numpy()
            inherited[sid] = source

    calibrated = params.copy()
    by_id = base.set_index("id")
    for col in columns:
        calibrated[col] = calibrated["id"].map(by_id[col]).astype(float)

    total, _ = run_network_simulation(calibrated, prec, etp, method=method)
    obs_mask = observed.notna().to_numpy()
    rows = []
    for j, g in enumerate(gauges):
        sim = total[g].to_numpy()
        obs = observed[g].to_numpy(dtype=float)
        kge_c, nse_c, n_c = _metrics(obs, sim, cal_mask)
        kge_v, nse_v, n_v = _metrics(obs, sim, ~cal_mask & obs_mask[:, j])
        rows.append(
            {
                "id": g,
                "Sub-bacias": sum(1 for v in groups.values() if v == g),
                "KGE calibração": kge_c,
                "NSE calibração": nse_c,
                "Dias calibração": n_c,
                "KGE validação": kge_v,
                "NSE validação": nse_v,
                "Dias validação": n_v,
            }
        )
    metrics = pd.DataFrame(rows).set_index("id").loc[[g for g in order]]
    return CalibrationResult(
        params=calibrated,
        metrics=metrics,
        simulated=total[gauges],
        observed=observed,
        groups=groups,
        inherited=inherited,
    )


def evaluations_per_gauge(n_columns: int, mode: str) -> int:
    """Upper bound of model runs per gauge for a mode."""
    s = MODES[mode]
    return s["popsize"] * n_columns * (s["maxiter"] + 1)


def group_sizes(params: pd.DataFrame, gauges) -> dict:
    """Gauge -> number of subcatchments in its group."""
    groups = gauge_groups(downstream_map(params), gauges)
    return {g: sum(1 for v in groups.values() if v == g) for g in gauges}


# endregion

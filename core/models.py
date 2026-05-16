import pandas as pd
from mogestpy.quantity.hydrological.smap import SmapD, SmapM
from mogestpy.quantity.hydrological.muskingum import Muskingum


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
    """
    SMAP + linear Muskingum routing over a network of subcatchments.

    params_df columns: id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x, downstream_id
    prec_df / etp_df: indexed by time, columns = subcatchment id (int)
    Returns DataFrame indexed by time with total discharge (m³/s) per subcatchment.
    """

    def _upstream_ids(basin_id):
        return params_df.loc[params_df["downstream_id"] == basin_id, "id"].tolist()

    def _topological_order():
        all_ids = set(params_df["id"].tolist())
        has_downstream = set(params_df["downstream_id"].dropna().astype(int).tolist())
        headwaters = [i for i in all_ids if i not in has_downstream]
        order, seen, queue = [], set(), list(headwaters)
        while queue:
            nid = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            order.append(nid)
            row = params_df[params_df["id"] == nid].iloc[0]
            if pd.notna(row["downstream_id"]):
                queue.append(int(row["downstream_id"]))
        return order

    total_flows: dict[int, list[float]] = {}

    for basin_id in _topological_order():
        row = params_df[params_df["id"] == basin_id].iloc[0]
        smap_params = {
            "Str": float(row["str"]),
            "Crec": float(row["crec"]),
            "Capc": float(row["capc"]),
            "kkt": float(row["kkt"]),
            "k2t": float(row["k2t"]),
            "Ai": float(row["ai"]),
            "Tuin": float(row["tuin"]),
            "Ebin": float(row["ebin"]),
            "Ad": float(row["area"]),
        }
        local: list[float] = SmapD(**smap_params).run_to_list(
            prec_df[basin_id].tolist(), etp_df[basin_id].tolist()
        )
        total = list(local)
        for up_id in _upstream_ids(basin_id):
            up_row = params_df[params_df["id"] == up_id].iloc[0]
            routed = Muskingum.downstream_routing(
                total_flows[up_id], k=float(up_row["k"]), x=float(up_row["x"]), dt=1.0
            )
            total = [a + b for a, b in zip(total, routed)]
        total_flows[basin_id] = total
        if verbose:
            print(f"Subcatchment {basin_id} concluído.")

    return pd.DataFrame(total_flows, index=prec_df.index)

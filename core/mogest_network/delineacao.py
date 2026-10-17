"""
Delimitação das sub-bacias com pyflwdir.

Os exutórios das sub-bacias são o exutório da bacia, os postos
fluviométricos e, opcionalmente, outlets automáticos por área mínima
(`FlwdirRaster.subbasins_area`). A topologia sai do próprio mapa de
direções: a sub-bacia de jusante é a que contém a célula logo abaixo do
exutório de cada sub-bacia.

Cópia de mogest-network (ver `core/mogest_network/__init__.py`). Única
alteração: `JUSANTE_FINAL` vem do pacote, e não de `rede.py`.
"""

import logging
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import pyflwdir
import rasterio.features
from pyproj import Transformer
from shapely.geometry import Point, shape

from .dem import Dem, toca_borda
from . import JUSANTE_FINAL

log = logging.getLogger(__name__)

FRACAO_AREA_MIN_AUTO = 0.2


@dataclass
class PontoExutorio:
    """Ponto informado pelo usuário que vira exutório de sub-bacia."""

    id: str
    lon: float
    lat: float
    posto: bool = False


@dataclass
class Delimitacao:
    """Resultado da delimitação."""

    subbacias: gpd.GeoDataFrame
    outlets: gpd.GeoDataFrame
    rios: gpd.GeoDataFrame
    topologia: pd.DataFrame
    rotulos: np.ndarray
    toca_borda: bool


def _indices_pontos(flw, dem: Dem, pontos: list[PontoExutorio]) -> np.ndarray:
    lons = np.array([p.lon for p in pontos])
    lats = np.array([p.lat for p in pontos])
    if dem.latlon:
        xs, ys = lons, lats
    else:
        tr = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
        xs, ys = tr.transform(lons, lats)
    return np.asarray(flw.index(xs, ys), dtype=np.int64)


def _area_incremental(uparea_flat, outlets: dict, jusante: dict) -> dict:
    """Área de cada sub-bacia = área a montante do exutório − áreas dos montantes."""
    area = {sid: float(uparea_flat[idx]) for sid, idx in outlets.items()}
    inc = dict(area)
    for sid, jus in jusante.items():
        if jus != JUSANTE_FINAL:
            inc[jus] -= area[sid]
    return inc


def _jusantes(flw, rotulos_flat, outlets: dict, num_para_id: dict) -> dict:
    jus = {}
    n = rotulos_flat.size
    for sid, idx in outlets.items():
        ds = int(flw.idxs_ds[idx])
        if ds == idx or ds < 0 or ds >= n or rotulos_flat[ds] == 0:
            jus[sid] = JUSANTE_FINAL
        else:
            jus[sid] = num_para_id[int(rotulos_flat[ds])]
    return jus


def delinear(
    dem: Dem,
    exutorio: PontoExutorio,
    pontos: list[PontoExutorio] | None = None,
    area_min_km2: float | None = None,
    limiar_rio_km2: float = 5.0,
    max_snap_m: float = 2000.0,
) -> Delimitacao:
    """
    Delimita a bacia do exutório e suas sub-bacias.

    Parâmetros
    ----------
    dem : Dem
        Elevação (latlon ou projetado).
    exutorio : PontoExutorio
        Exutório da bacia (lon/lat em graus).
    pontos : list[PontoExutorio], opcional
        Postos fluviométricos e outros pontos de interesse dentro da bacia.
    area_min_km2 : float, opcional
        Área mínima para outlets automáticos; None desliga a subdivisão
        automática (só os pontos do usuário).
    limiar_rio_km2 : float
        Área de contribuição mínima de uma célula de rio (snap e camada de rios).
    max_snap_m : float
        Distância máxima, ao longo do fluxo, para levar um ponto até o rio.

    Retorna
    -------
    Delimitacao

    Erros
    -----
    ValueError
        Ponto fora da bacia do exutório, ou dois pontos no mesmo pixel de rio.
    """
    pontos = list(pontos or [])
    todos = [exutorio] + pontos
    ids = [p.id for p in todos]
    if len(set(ids)) != len(ids):
        raise ValueError(f"IDs de pontos repetidos: {ids}")

    flw = pyflwdir.from_dem(
        dem.elevacao,
        nodata=dem.nodata,
        transform=tuple(dem.transform)[:6],
        latlon=dem.latlon,
    )
    uparea = flw.upstream_area(unit="km2")
    rio = uparea >= limiar_rio_km2

    idx_brutos = _indices_pontos(flw, dem, todos)
    idx_snap, dist_snap = flw.snap(idxs=idx_brutos, mask=rio, max_length=max_snap_m, unit="m")
    idx_snap = np.asarray(idx_snap, dtype=np.int64)
    for p, d, i in zip(todos, dist_snap, idx_snap):
        if not rio.flat[i]:
            log.warning(
                "Ponto %s não alcançou um rio (> %.0f m) e ficou fora da rede.",
                p.id,
                max_snap_m,
            )
        elif d > 0:
            log.info("Ponto %s deslocado %.0f m até o rio.", p.id, d)
    if len(set(idx_snap.tolist())) != len(idx_snap):
        raise ValueError("Dois pontos caíram no mesmo pixel de rio após o snap.")

    mascara_bacia = flw.basins(idxs=idx_snap[:1]) > 0
    for p, i in zip(pontos, idx_snap[1:]):
        if not mascara_bacia.flat[i]:
            raise ValueError(f"Ponto {p.id} está fora da bacia do exutório.")

    outlets = {p.id: int(i) for p, i in zip(todos, idx_snap)}
    posto = {p.id: p.posto for p in todos}

    auto = []
    if area_min_km2:
        _, idxs_auto = flw.subbasins_area(area_min_km2, uparea=uparea)
        usados = set(outlets.values())
        auto = [
            int(i) for i in np.asarray(idxs_auto) if mascara_bacia.flat[i] and int(i) not in usados
        ]
    auto_ids = set()
    for n, idx in enumerate(sorted(auto, key=lambda i: -uparea.flat[i]), start=1):
        outlets[f"_auto{n}"] = idx
        posto[f"_auto{n}"] = False
        auto_ids.add(f"_auto{n}")

    # Remove outlets automáticos que geram sub-bacias pequenas demais: a
    # própria sub-bacia automática pequena, ou a automática logo a montante
    # de um ponto do usuário cuja sub-bacia ficou pequena.
    while True:
        id_para_num = {sid: n for n, sid in enumerate(outlets, start=1)}
        num_para_id = {n: sid for sid, n in id_para_num.items()}
        rotulos = flw.basins(
            idxs=np.array(list(outlets.values())),
            ids=np.array(list(id_para_num.values()), dtype=np.uint32),
        )
        jusante = _jusantes(flw, rotulos.ravel(), outlets, num_para_id)
        area = _area_incremental(uparea.ravel(), outlets, jusante)
        if not area_min_km2:
            break
        limite = FRACAO_AREA_MIN_AUTO * area_min_km2
        remover = set()
        for sid in outlets:
            if area[sid] >= limite:
                continue
            if sid in auto_ids:
                remover.add(sid)
            else:
                mont_auto = [m for m, j in jusante.items() if j == sid and m in auto_ids]
                if mont_auto:
                    remover.add(max(mont_auto, key=lambda m: uparea.flat[outlets[m]]))
        if not remover:
            break
        for sid in remover:
            del outlets[sid]

    # Renumera as automáticas (sb001 = maior área a montante)
    restantes = sorted(
        (s for s in outlets if s in auto_ids), key=lambda s: -uparea.flat[outlets[s]]
    )
    novo = {s: f"sb{n:03d}" for n, s in enumerate(restantes, start=1)}
    renomear = lambda s: novo.get(s, s)  # noqa: E731
    outlets = {renomear(s): i for s, i in outlets.items()}
    jusante = {renomear(s): (renomear(j) if j != JUSANTE_FINAL else j) for s, j in jusante.items()}
    area = {renomear(s): a for s, a in area.items()}
    posto = {renomear(s): v for s, v in posto.items()}
    num_para_id = {n: renomear(s) for n, s in num_para_id.items()}

    # Comprimento e desnível do trecho: do exutório de cada montante até o
    # exutório da sub-bacia, média ponderada pela área a montante. A
    # declividade (desnível / comprimento, cotas do DEM bruto) alimenta a
    # onda cinemática; em reservatório fica ~0 e o propagador aplica um mínimo.
    mascara_outlets = np.zeros(flw.shape, dtype=bool)
    mascara_outlets.flat[list(outlets.values())] = True
    l_trecho = {sid: 0.0 for sid in outlets}
    desnivel = {sid: 0.0 for sid in outlets}
    pesos = {sid: 0.0 for sid in outlets}
    cota = dem.elevacao.ravel()
    for sid, jus in jusante.items():
        if jus == JUSANTE_FINAL:
            continue
        idx = outlets[sid]
        mascara_outlets.flat[idx] = False
        caminhos, dist = flw.path(idxs=[idx], mask=mascara_outlets, unit="m")
        mascara_outlets.flat[idx] = True
        w = float(uparea.flat[idx])
        l_trecho[jus] += w * float(dist[0])
        desnivel[jus] += w * float(cota[caminhos[0][0]] - cota[caminhos[0][-1]])
        pesos[jus] += w
    for sid in l_trecho:
        if pesos[sid] > 0:
            l_trecho[sid] /= pesos[sid]
            desnivel[sid] /= pesos[sid]
    s_trecho = {
        sid: (max(desnivel[sid], 0.0) / l_trecho[sid] if l_trecho[sid] > 0 else 0.0)
        for sid in outlets
    }

    topologia = pd.DataFrame(
        {
            "id": list(outlets),
            "jusante": [jusante[s] for s in outlets],
            "area_km2": [area[s] for s in outlets],
            "L_trecho_km": [l_trecho[s] / 1000.0 for s in outlets],
            "S_trecho": [s_trecho[s] for s in outlets],
            "posto": [posto[s] for s in outlets],
        }
    )

    crs = dem.crs
    geoms = {}
    for geom, valor in rasterio.features.shapes(
        rotulos.astype(np.int32), mask=rotulos > 0, transform=dem.transform
    ):
        geoms.setdefault(num_para_id[int(valor)], []).append(shape(geom))
    subbacias = gpd.GeoDataFrame(
        topologia.copy(),
        geometry=[gpd.GeoSeries(geoms[s], crs=crs).union_all() for s in topologia["id"]],
        crs=crs,
    )

    xs, ys = flw.xy(np.array(list(outlets.values())))
    snap_m = dict(zip(ids, np.asarray(dist_snap, dtype=float)))
    outlets_gdf = gpd.GeoDataFrame(
        {
            "id": list(outlets),
            "posto": [posto[s] for s in outlets],
            "dist_snap_m": [snap_m.get(s, 0.0) for s in outlets],
        },
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
        crs=crs,
    )

    mascara_rio = rio & (rotulos > 0)
    feats = flw.streams(mask=mascara_rio, uparea=uparea)
    rios = gpd.GeoDataFrame(geometry=[], crs=crs)
    if feats:
        # streams() segue o último segmento até o pit; recorta na bacia
        rios = gpd.clip(gpd.GeoDataFrame.from_features(feats, crs=crs), subbacias)
        rios = rios[~rios.is_empty].reset_index(drop=True)

    return Delimitacao(
        subbacias=subbacias,
        outlets=outlets_gdf,
        rios=rios,
        topologia=topologia,
        rotulos=rotulos,
        toca_borda=toca_borda(rotulos > 0),
    )

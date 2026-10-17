"""
Estimativa dos parâmetros de Muskingum (k, x) de cada trecho a partir
do comprimento de rio derivado do DEM.

O passo de tempo do SMAP diário é 1 dia, então a maioria dos trechos entre
sub-bacias tem tempo de viagem menor que o passo. O ajuste abaixo mantém os
coeficientes c0, c1 e c2 não negativos (condição 2kx <= dt <= 2k(1-x)).

Cópia de mogest-network (ver `core/mogest_network/__init__.py`), sem alteração.
"""

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

SEGUNDOS_POR_DIA = 86400.0


def k_por_celeridade(comprimento_m: float, celeridade_ms: float) -> float:
    """
    Tempo de viagem do trecho, em dias.

    Parâmetros
    ----------
    comprimento_m : float
        Comprimento do trecho de rio, em metros.
    celeridade_ms : float
        Celeridade da onda de cheia, em m/s.

    Retorna
    -------
    float
        k = L / c, em dias.
    """
    if celeridade_ms <= 0:
        raise ValueError("celeridade_ms deve ser positiva.")
    return float(comprimento_m) / (celeridade_ms * SEGUNDOS_POR_DIA)


def ajustar_estabilidade(k: float, x: float, dt: float = 1.0) -> tuple[float, float]:
    """
    Ajusta (k, x) para que os coeficientes de Muskingum sejam não negativos.

    Parâmetros
    ----------
    k : float
        Tempo de viagem do trecho, na mesma unidade de `dt`.
    x : float
        Fator de ponderação desejado (0 a 0,5).
    dt : float
        Passo de tempo.

    Retorna
    -------
    tuple[float, float]
        (k, x) ajustados. Quando k < dt/2 nenhum x satisfaz a condição e o
        trecho é tratado como translação desprezível: retorna (0, 0), que a
        rede interpreta como passagem direta (Q_saida = Q_entrada).
    """
    if k <= 0 or k < dt / 2:
        return 0.0, 0.0
    x_max = min(0.5, dt / (2 * k), 1 - dt / (2 * k))
    x_aj = float(np.clip(x, 0.0, x_max))
    return float(k), x_aj


def parametros_trechos(
    topologia: pd.DataFrame,
    celeridade_ms: float = 1.0,
    x: float = 0.2,
    dt: float = 1.0,
) -> pd.DataFrame:
    """
    Calcula k e x de cada sub-bacia a partir do comprimento do trecho.

    O trecho de uma sub-bacia é o rio que liga os exutórios das sub-bacias
    de montante ao exutório dela, por onde passa a vazão afluente.

    Parâmetros
    ----------
    topologia : pd.DataFrame
        Deve ter as colunas `id` e `L_trecho_km`.
    celeridade_ms : float
        Celeridade da onda, em m/s.
    x : float
        Fator de ponderação desejado.
    dt : float
        Passo de tempo, em dias.

    Retorna
    -------
    pd.DataFrame
        Cópia de `topologia` com as colunas `k` (dias) e `x`.
    """
    topo = topologia.copy()
    ks, xs = [], []
    for _, row in topo.iterrows():
        k_bruto = k_por_celeridade(row["L_trecho_km"] * 1000.0, celeridade_ms)
        k_aj, x_aj = ajustar_estabilidade(k_bruto, x, dt)
        if k_aj == 0.0 and k_bruto > 0:
            log.info(
                "Sub-bacia %s: k=%.3f d < dt/2, trecho tratado como passagem direta.",
                row["id"],
                k_bruto,
            )
        ks.append(k_aj)
        xs.append(x_aj)
    topo["k"] = ks
    topo["x"] = xs
    return topo

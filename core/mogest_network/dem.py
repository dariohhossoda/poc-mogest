"""
Leitura do DEM: GeoTIFF local ou mosaico do Copernicus GLO-30.

O GLO-30 é lido direto do bucket público na AWS (Cloud Optimized GeoTIFF),
só na janela do bbox pedido.

Cópia de mogest-network (ver `core/mogest_network/__init__.py`). Alterações:
`baixar_glo30`, que grava o mosaico num cache em disco, foi trocada por
`mosaico_glo30`, que devolve o `Dem` em memória; `carregar_dem_bytes` lê um
GeoTIFF enviado sem passar pelo disco; `GDAL_SEM_DISCO` configura o GDAL.
"""

import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.merge import merge

log = logging.getLogger(__name__)

URL_GLO30 = "https://copernicus-dem-30m.s3.amazonaws.com"
KM_POR_GRAU = 111.32


@dataclass
class Dem:
    """Raster de elevação em memória."""

    elevacao: np.ndarray
    transform: Affine
    crs: CRS
    nodata: float

    @property
    def latlon(self) -> bool:
        return bool(self.crs.is_geographic)


def carregar_dem(arquivo: str | Path, bbox: tuple | None = None) -> Dem:
    """
    Lê um GeoTIFF de elevação, opcionalmente recortado por bbox.

    Parâmetros
    ----------
    arquivo : str | Path
        Caminho do GeoTIFF (ou URL GDAL, ex.: /vsicurl/...).
    bbox : tuple, opcional
        (oeste, sul, leste, norte) no CRS do raster.

    Retorna
    -------
    Dem
    """
    with rasterio.open(arquivo) as src:
        if bbox is None:
            elev = src.read(1, masked=False).astype("float32")
            transform = src.transform
        else:
            janela = rasterio.windows.from_bounds(*bbox, transform=src.transform)
            janela = janela.round_offsets().round_lengths()
            elev = src.read(1, window=janela, boundless=True).astype("float32")
            transform = src.window_transform(janela)
        nodata = src.nodata if src.nodata is not None else -9999.0
        crs = src.crs
    elev[~np.isfinite(elev)] = nodata
    return Dem(elev, transform, crs, float(nodata))


def nomes_tiles_glo30(bbox: tuple) -> list[str]:
    """
    Nomes dos tiles de 1°x1° do GLO-30 que cobrem o bbox.

    O nome usa o canto sudoeste do tile, ex.: S23_00_W047_00 cobre
    lat -23 a -22 e lon -47 a -46.
    """
    oeste, sul, leste, norte = bbox
    nomes = []
    for lat in range(math.floor(sul), math.ceil(norte)):
        for lon in range(math.floor(oeste), math.ceil(leste)):
            ns = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
            ew = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            nomes.append(f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM")
    return nomes


# Abre os COG por HTTP sem listar o bucket e sem tentar arquivos auxiliares.
# O cache do /vsicurl/ é o padrão do GDAL, em memória.
GDAL_SEM_DISCO = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
}


def carregar_dem_bytes(dados: bytes, bbox: tuple | None = None) -> Dem:
    """
    Lê um GeoTIFF de elevação a partir dos bytes, sem gravar em disco.

    O rasterio abre objetos de arquivo por `MemoryFile` (`/vsimem/`).
    """
    return carregar_dem(io.BytesIO(dados), bbox)


def mosaico_glo30(bbox: tuple, resolucao_graus: float | None = None) -> Dem:
    """
    Monta o mosaico do Copernicus GLO-30 para o bbox, em memória.

    Parâmetros
    ----------
    bbox : tuple
        (oeste, sul, leste, norte) em graus (EPSG:4326).
    resolucao_graus : float, opcional
        Reamostra o mosaico (ex.: 1/1200 = 3"); None mantém 1" (~30 m).

    Retorna
    -------
    Dem

    Erros
    -----
    RuntimeError
        Se nenhum tile existir para o bbox (ex.: só oceano).
    """
    with rasterio.Env(**GDAL_SEM_DISCO):
        fontes = []
        for nome in nomes_tiles_glo30(bbox):
            url = f"/vsicurl/{URL_GLO30}/{nome}/{nome}.tif"
            try:
                fontes.append(rasterio.open(url))
            except rasterio.errors.RasterioIOError:
                log.info("Tile ausente (oceano?): %s", nome)
        if not fontes:
            raise RuntimeError(f"Nenhum tile GLO-30 encontrado para o bbox {bbox}.")

        log.info("Lendo %d tile(s) GLO-30", len(fontes))
        try:
            res = (resolucao_graus, resolucao_graus) if resolucao_graus else None
            mosaico, transform = merge(fontes, bounds=bbox, res=res, nodata=-9999.0)
        finally:
            for f in fontes:
                f.close()
    elev = mosaico[0].astype("float32")
    elev[~np.isfinite(elev)] = -9999.0
    return Dem(elev, transform, CRS.from_epsg(4326), -9999.0)


def bbox_em_torno(lon: float, lat: float, buffer_km: float) -> tuple:
    """bbox (oeste, sul, leste, norte) em graus, com `buffer_km` em volta do ponto."""
    dlat = buffer_km / KM_POR_GRAU
    dlon = buffer_km / (KM_POR_GRAU * max(math.cos(math.radians(lat)), 0.1))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def toca_borda(mascara: np.ndarray) -> bool:
    """True se a máscara da bacia tem célula na borda do raster."""
    return bool(
        mascara[0, :].any() or mascara[-1, :].any() or mascara[:, 0].any() or mascara[:, -1].any()
    )

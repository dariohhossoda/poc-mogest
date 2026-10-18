"""
Where each input of a simulation came from.

Origins are plain dicts (Portuguese keys, as shown to the user) so the page
can display them and the user can download them as JSON. NASA POWER origins
are built in ``core.nasa_power``.
"""

import datetime as dt
import hashlib
import json

import pandas as pd

GLO30_CITATION = (
    "Copernicus DEM GLO-30, https://doi.org/10.5270/ESA-c5d3d65. © DLR e.V. "
    "2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under "
    "COPERNICUS by the European Union and ESA; all rights reserved."
)
GLO30_BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com (AWS Open Data)"


def _period(series: pd.DataFrame | None) -> dict:
    if series is None or len(series) == 0:
        return {}
    return {
        "periodo": f"{series.index[0]:%Y-%m-%d} a {series.index[-1]:%Y-%m-%d}",
        "dias": len(series),
        "colunas": [str(c) for c in series.columns],
    }


def file_origin(entry: str, name: str, data: bytes, series=None) -> dict:
    """File sent by the user, identified by name, size and SHA-256."""
    return {
        "entrada": entry,
        "origem": "Arquivo enviado",
        "arquivo": name,
        "tamanho_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **_period(series),
    }


def example_origin(entry: str, path, series=None) -> dict:
    """Example data shipped with the app."""
    return {
        "entrada": entry,
        "origem": "Dados de exemplo do app",
        "arquivo": str(path),
        **_period(series),
    }


def delineation_origin(
    *,
    points: pd.DataFrame,
    glo30: bool,
    resolution_deg: float | None,
    bbox: tuple | None,
    dem_name: str | None,
    dem_bytes: bytes | None,
    settings: dict,
    today: dt.date | None = None,
) -> dict:
    """Subcatchments delineated in the app from the outlet and the gauges."""
    if glo30:
        arcsec = round((resolution_deg or 1 / 3600) * 3600)
        dem = {
            "dem": "Copernicus DEM GLO-30 (DGED), lido em memória",
            "resolucao": f'{arcsec}"',
            "bbox_oeste_sul_leste_norte": [round(v, 6) for v in bbox] if bbox else None,
            "repositorio": GLO30_BUCKET,
            "acesso": f"{today or dt.date.today():%Y-%m-%d}",
            "citacao": [GLO30_CITATION],
        }
    else:
        dem = {
            "dem": "GeoTIFF enviado",
            "arquivo": dem_name,
            "tamanho_bytes": len(dem_bytes or b""),
            "sha256": hashlib.sha256(dem_bytes or b"").hexdigest(),
        }
    return {
        "entrada": "Sub-bacias e parâmetros",
        "origem": "Delimitação no app (pyflwdir, cópia do mogest-network)",
        "pontos": points.to_dict("records"),
        **dem,
        "discretizacao": settings,
    }


def origins_json(origins: list[dict]) -> bytes:
    """Origins as a JSON document for download."""
    doc = {
        "gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "entradas": origins,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2, default=str).encode()

"""
ANA fluviometric station inventory (Hidroweb), read in memory.

The request follows dariOS ``Processos/2026-10-11_Fonte-ANA-Hidroweb_v1.md``:
the public SOAP web service answers GET with every parameter in the URL, even
empty ones, and needs no login. ``HidroInventario`` with ``tpEst=1`` returns
every fluviometric station in Brazil (about 18 thousand, 60 MB of XML, a few
seconds). Only stations that measure or measured stage or discharge are kept:
water-quality-only sites are dropped. Nothing is written to disk.
"""

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd

INVENTORY_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/HidroInventario"
_PARAMS = (
    "codEstDE",
    "codEstATE",
    "tpEst",
    "nmEst",
    "nmRio",
    "codSubBacia",
    "codBacia",
    "nmMunicipio",
    "nmEstado",
    "sgResp",
    "sgOper",
    "telemetrica",
)
TIMEOUT_S = 120
NO_DATE = "1800-01-01"  # the inventory's "no date" marker
# Stage, discharge, water level recorder and telemetry
_HYDRO = ("Escala", "DescLiquida", "RegistradorNivel", "Telemetrica")

COLUMNS = (
    "codigo",
    "nome",
    "rio",
    "municipio",
    "estado",
    "responsavel",
    "operadora",
    "area_km2",
    "lat",
    "lon",
    "casas_coord",
    "operando",
)
CITATION = (
    "Agência Nacional de Águas e Saneamento Básico (ANA), Hidroweb, inventário "
    "de estações fluviométricas (HidroInventario)."
)


def inventory_url() -> str:
    params = dict.fromkeys(_PARAMS, "")
    params["tpEst"] = "1"
    return f"{INVENTORY_URL}?{urllib.parse.urlencode(params)}"


def fetch_inventory(opener=urllib.request.urlopen) -> pd.DataFrame:
    """Every stage or discharge station of the ANA inventory (see module doc)."""
    try:
        with opener(inventory_url(), timeout=TIMEOUT_S) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"A ANA respondeu {e.code} ao inventário.") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Falha de rede ao consultar a ANA: {e}") from e
    return parse_inventory(body)


def _measured(text: str) -> bool:
    return bool(text) and not text.startswith(NO_DATE)


def _decimals(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


def parse_inventory(xml: bytes) -> pd.DataFrame:
    """Stations of a ``HidroInventario`` response; one row per ``Table``."""
    rows = []
    for table in ET.fromstring(xml).iter():
        if table.tag.rsplit("}", 1)[-1] != "Table":
            continue

        def get(name: str) -> str:
            return (table.findtext(name) or "").strip()

        hydro = any(get(f"TipoEstacao{k}") == "1" for k in _HYDRO) or any(
            _measured(get(f"Periodo{k}Inicio")) for k in _HYDRO
        )
        if not hydro:
            continue
        try:
            lat, lon = float(get("Latitude")), float(get("Longitude"))
        except ValueError:
            continue
        area = pd.to_numeric(get("AreaDrenagem") or None, errors="coerce")
        rows.append(
            {
                "codigo": get("Codigo").zfill(8),
                "nome": get("Nome"),
                "rio": get("RioNome"),
                "municipio": get("nmMunicipio"),
                "estado": get("nmEstado"),
                "responsavel": get("ResponsavelSigla"),
                "operadora": get("OperadoraSigla"),
                "area_km2": area,
                "lat": lat,
                "lon": lon,
                "casas_coord": min(
                    _decimals(get("Latitude")), _decimals(get("Longitude"))
                ),
                "operando": get("Operando") == "1",
            }
        )
    return pd.DataFrame(rows, columns=list(COLUMNS))


def stations_in_bbox(stations: pd.DataFrame, bbox: tuple) -> pd.DataFrame:
    """Stations inside (west, south, east, north)."""
    west, south, east, north = bbox
    inside = stations["lon"].between(west, east) & stations["lat"].between(south, north)
    return stations[inside].reset_index(drop=True)

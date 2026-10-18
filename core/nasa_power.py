"""
Daily NASA POWER series averaged over subcatchments, read in memory.

The requests follow dariOS ``Processos/scripts/baixar_nasa_power.py``: daily
point requests in JSON (community AG), split in 10-year blocks, sent one at a
time with a pause and retried on 429/5xx; -999 becomes NaN. Each request goes
to the centre of a grid cell, and each subcatchment series is the mean of the
cells it crosses weighted by the intersection area. Precipitation is
PRECTOTCORR (MERRA-2/GEOS-IT) or IMERG_PRECTOT (GPM IMERG); ETP is the FAO-56
Penman-Monteith reference evapotranspiration computed in each cell before the
average. Nothing is written to disk.
"""

import datetime as dt
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from core.geo import EQUAL_AREA, WGS84

POINT_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
COMMUNITY = "AG"  # radiation in MJ/m²/day, as FAO-56 uses
FILL = -999.0
BLOCK_YEARS = 10  # 20 variables x 10 years pass; the whole period gives 502
# NASA asks for serial requests; repeating a point without pause gets blocked
PAUSE_S = 1.0
RETRIES = 4
TIMEOUT_S = 300
# Requests per download (cells x 10-year blocks): about 1 s each plus the pause
MAX_REQUESTS = 60

PROJECT_CITATION = (
    "The data was obtained from National Aeronautics and Space Administration "
    "(NASA) Langley Research Center's Prediction Of Worldwide Energy Resources "
    "(POWER) project funded through the NASA Earth Science Division."
)
NOTIFY = (
    "A NASA pede que publicações que usem o dado sejam informadas a "
    "larc-power-project@mail.nasa.gov, e que o repasse do dado a outros "
    "pesquisadores também seja avisado."
)
MERRA2 = (
    "Gelaro, R. et al. (2017). The Modern-Era Retrospective Analysis for "
    "Research and Applications, Version 2 (MERRA-2). J. Climate, 30, 5419-5454. "
    "https://doi.org/10.1175/JCLI-D-16-0758.1"
)
IMERG = (
    "Huffman, G. J. et al. GPM IMERG Final Precipitation L3 1 day 0.1 degree x "
    "0.1 degree V07. NASA GES DISC."
)
RADIATION = (
    "Radiação: NASA/GEWEX SRB 4.0 (1984-2000) e CERES SYN1deg/FLASHFlux "
    "(desde 2001), grade de 1°."
)
FAO56 = (
    "Allen, R. G., Pereira, L. S., Raes, D. & Smith, M. (1998). Crop "
    "evapotranspiration: guidelines for computing crop water requirements. "
    "FAO Irrigation and Drainage Paper 56. Roma: FAO."
)


@dataclass(frozen=True)
class Grid:
    """Regular lat/lon grid given by the centre of its first cell and the steps."""

    name: str
    dlat: float
    dlon: float
    lat0: float
    lon0: float

    def center(self, lat: float, lon: float) -> tuple[float, float]:
        """Centre of the cell holding the point."""
        i = round((lat - self.lat0) / self.dlat)
        j = round((lon - self.lon0) / self.dlon)
        return round(self.lat0 + i * self.dlat, 4), round(self.lon0 + j * self.dlon, 4)

    def cell(self, lat: float, lon: float):
        """Cell box (shapely, WGS84) around a centre."""
        return box(
            lon - self.dlon / 2,
            lat - self.dlat / 2,
            lon + self.dlon / 2,
            lat + self.dlat / 2,
        )

    def centers(self, bounds: tuple) -> list[tuple[float, float]]:
        """Centres of the cells crossing (west, south, east, north)."""
        west, south, east, north = bounds
        i0 = math.floor((south - self.lat0) / self.dlat + 0.5)
        i1 = math.ceil((north - self.lat0) / self.dlat - 0.5)
        j0 = math.floor((west - self.lon0) / self.dlon + 0.5)
        j1 = math.ceil((east - self.lon0) / self.dlon - 0.5)
        return [
            (round(self.lat0 + i * self.dlat, 4), round(self.lon0 + j * self.dlon, 4))
            for i in range(i0, i1 + 1)
            for j in range(j0, j1 + 1)
        ]


# MERRA-2/GEOS-IT: centres from -90/-180 (conferred against the regional endpoint)
METEOROLOGY_GRID = Grid("MERRA-2/GEOS-IT, 0,5° × 0,625°", 0.5, 0.625, -90.0, -180.0)
# IMERG: 0.1° cells with edges on multiples of 0.1° (conferred on 2026-10-17)
IMERG_GRID = Grid("GPM IMERG, 0,1°", 0.1, 0.1, -89.95, -179.95)


@dataclass(frozen=True)
class Product:
    """What is requested from POWER for one model input."""

    key: str
    label: str
    parameters: tuple[str, ...]
    grid: Grid
    time_standard: str
    first_day: dt.date
    sources: tuple[str, ...]


PRECIPITATION = {
    "PRECTOTCORR": Product(
        "PRECTOTCORR",
        "PRECTOTCORR — MERRA-2/GEOS-IT corrigida (desde 1981)",
        ("PRECTOTCORR",),
        METEOROLOGY_GRID,
        "lst",
        dt.date(1981, 1, 1),
        (MERRA2,),
    ),
    "IMERG_PRECTOT": Product(
        "IMERG_PRECTOT",
        "IMERG_PRECTOT — GPM IMERG, 0,1° (desde 2000, dia em UTC)",
        ("IMERG_PRECTOT",),
        IMERG_GRID,
        "utc",  # the API has IMERG only in UTC
        dt.date(2000, 6, 1),
        (IMERG,),
    ),
}
# Variables of FAO-56 Penman-Monteith; radiation starts in 1984
ETO = Product(
    "ETO",
    "ETo FAO-56 Penman-Monteith (T2M, T2M_MAX, T2M_MIN, RH2M, WS2M, "
    "ALLSKY_SFC_SW_DWN, PS)",
    ("T2M", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "PS"),
    METEOROLOGY_GRID,
    "lst",
    dt.date(1984, 1, 1),
    (MERRA2, RADIATION, FAO56),
)


@dataclass
class PointSeries:
    """Daily series of one point request, with the response metadata."""

    data: pd.DataFrame
    elevation_m: float
    api: str
    sources: list[str]
    time_standard: str
    units: dict
    urls: list[str] = field(default_factory=list)


_last_request = 0.0


def _wait() -> None:
    global _last_request
    pause = PAUSE_S - (time.monotonic() - _last_request)
    if pause > 0:
        time.sleep(pause)
    _last_request = time.monotonic()


def _get_json(url: str, opener=urllib.request.urlopen) -> dict:
    for attempt in range(1, RETRIES + 1):
        _wait()
        try:
            with opener(url, timeout=TIMEOUT_S) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read()[:1000].decode(errors="replace")
            try:
                reason = "; ".join(json.loads(body).get("messages") or []) or body
            except (json.JSONDecodeError, AttributeError):
                reason = body
            if e.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                time.sleep(30 * attempt if e.code == 429 else 5 * attempt)
                continue
            raise RuntimeError(f"NASA POWER respondeu {e.code}: {reason}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == RETRIES:
                raise RuntimeError(
                    f"Falha de rede ao consultar a NASA POWER: {e}"
                ) from e
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def blocks(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Request periods of at most ``BLOCK_YEARS`` calendar years."""
    out = []
    while start <= end:
        cut = min(end, dt.date(start.year + BLOCK_YEARS, 1, 1) - dt.timedelta(days=1))
        out.append((start, cut))
        start = cut + dt.timedelta(days=1)
    return out


def point_url(
    lat: float, lon: float, parameters, start: dt.date, end: dt.date, time_standard: str
) -> str:
    query = {
        "parameters": ",".join(parameters),
        "community": COMMUNITY,
        "format": "JSON",
        "time-standard": time_standard,
        "latitude": lat,
        "longitude": lon,
        "start": f"{start:%Y%m%d}",
        "end": f"{end:%Y%m%d}",
    }
    return f"{POINT_URL}?{urllib.parse.urlencode(query)}"


def parse_response(body: dict) -> tuple[pd.DataFrame, float, dict]:
    """(daily data with NaN for -999, cell elevation, header) of one response."""
    values = body["properties"]["parameter"]
    data = pd.DataFrame(values).replace(FILL, np.nan)
    data.index = pd.to_datetime(data.index, format="%Y%m%d")
    data.index.name = "date"
    return data.astype(float), float(body["geometry"]["coordinates"][2]), body


def fetch_point(
    lat: float,
    lon: float,
    parameters: tuple[str, ...],
    start: dt.date,
    end: dt.date,
    time_standard: str = "lst",
    opener=urllib.request.urlopen,
) -> PointSeries:
    """Daily series of ``parameters`` at a point, joining 10-year blocks."""
    frames, urls, sources = [], [], set()
    body = {}
    elevation = float("nan")
    for b_start, b_end in blocks(start, end):
        url = point_url(lat, lon, parameters, b_start, b_end, time_standard)
        urls.append(url)
        data, elevation, body = parse_response(_get_json(url, opener))
        frames.append(data)
        sources.update(body.get("header", {}).get("sources", []))
    header = body.get("header", {})
    api = header.get("api", {})
    return PointSeries(
        data=pd.concat(frames).sort_index(),
        elevation_m=elevation,
        api=f"{api.get('name', 'POWER Daily API')} {api.get('version', '')}".strip(),
        sources=sorted(sources),
        time_standard=str(header.get("time_standard", time_standard)).upper(),
        units={k: v.get("units") for k, v in body.get("parameters", {}).items()},
        urls=urls,
    )


def cell_weights(polygons: gpd.GeoDataFrame, grid: Grid) -> pd.DataFrame:
    """
    Area weight of each grid cell in each polygon (id, lat, lon, weight).

    ``lat``/``lon`` are cell centres. Areas are taken in an equal-area
    projection; the weights of a polygon sum to 1.
    """
    rows = []
    polygons = polygons.to_crs(WGS84)
    for bid, geom in zip(polygons["id"], polygons.geometry):
        centers = grid.centers(geom.bounds)
        cells = gpd.GeoSeries([grid.cell(*c) for c in centers], crs=WGS84)
        projected = gpd.GeoSeries([geom], crs=WGS84).to_crs(EQUAL_AREA).iloc[0]
        areas = cells.to_crs(EQUAL_AREA).intersection(projected).area.to_numpy()
        total = areas.sum()
        for (lat, lon), area in zip(centers, areas):
            if area > 0:
                rows.append({"id": bid, "lat": lat, "lon": lon, "weight": area / total})
    return pd.DataFrame(rows, columns=["id", "lat", "lon", "weight"])


def _e0(t):
    """Saturation vapour pressure (kPa) at temperature t (°C), FAO-56 eq. 11."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def eto_fao56(met: pd.DataFrame, lat_deg: float, elevation_m: float) -> pd.Series:
    """
    Daily FAO-56 Penman-Monteith reference evapotranspiration (mm/day).

    ``met`` has the POWER columns of ``ETO.parameters``: T2M, T2M_MAX, T2M_MIN
    (°C), RH2M (%), WS2M (m/s at 2 m), ALLSKY_SFC_SW_DWN (MJ/m²/day) and PS
    (kPa). Rs/Rso is kept within 0.3-1.0, as in ``pyet.pm_fao56``, which the
    mogest-network uses; without ``g`` (soil heat flux is zero for days).
    """
    t, tmax, tmin = met["T2M"], met["T2M_MAX"], met["T2M_MIN"]
    rh, u2, rs, p = met["RH2M"], met["WS2M"], met["ALLSKY_SFC_SW_DWN"], met["PS"]
    gamma = 0.000665 * p
    delta = 4098 * _e0(t) / (t + 237.3) ** 2
    es = (_e0(tmax) + _e0(tmin)) / 2
    ea = rh / 100 * es  # eq. 19, mean relative humidity

    day = met.index.dayofyear.to_numpy()
    phi = np.deg2rad(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi / 365 * day)
    dec = 0.409 * np.sin(2 * np.pi / 365 * day - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    ra = (24 * 60 / np.pi * 0.0820 * dr) * (
        ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws)
    )
    rso = (0.75 + 2e-5 * elevation_m) * ra
    ratio = (rs / rso).clip(0.3, 1.0)
    rnl = (
        4.903e-9
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4)
        / 2
        * (0.34 - 0.14 * np.sqrt(ea))
        * (1.35 * ratio - 0.35)
    )
    rn = 0.77 * rs - rnl
    eto = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (
        delta + gamma * (1 + 0.34 * u2)
    )
    return eto.rename("eto")


def complete_period(series: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """
    Cut leading and trailing days with a gap in any column.

    POWER leaves the last days at -999 while the products catch up. Returns
    the cut frame and the days still missing inside it.
    """
    full = series.notna().all(axis=1)
    if not full.any():
        return series.iloc[0:0], []
    cut = series.loc[full.idxmax() : full[::-1].idxmax()]
    gaps = list(cut.index[cut.isna().any(axis=1)])
    return cut, gaps


def _fmt_period(index) -> str:
    if len(index) == 0:
        return "sem dado"
    return f"{index[0]:%Y-%m-%d} a {index[-1]:%Y-%m-%d}"


def areal_series(
    polygons: gpd.GeoDataFrame,
    product: Product,
    start: dt.date,
    end: dt.date,
    *,
    entry: str,
    names: dict | None = None,
    fetch: Callable[..., PointSeries] = fetch_point,
    on_step: Callable[[str], None] | None = None,
    max_requests: int = MAX_REQUESTS,
    today: dt.date | None = None,
) -> tuple[pd.DataFrame, list, dict]:
    """
    Daily series of ``product`` per polygon id, area-weighted over the grid.

    Returns the series cut to the days with data everywhere, the days still
    missing inside that period, and the origin record of the data. ``fetch``
    has the signature of ``fetch_point`` (the page passes a cached version).

    Raises
    ------
    ValueError
        Start before the product's first day, end before start, or more
        requests than ``max_requests``.
    RuntimeError
        Request refused by POWER or network failure.
    """
    step = on_step or (lambda _msg: None)
    if start < product.first_day:
        raise ValueError(
            f"{product.key} começa em {product.first_day:%Y-%m-%d}: ajuste o início."
        )
    if end < start:
        raise ValueError("O fim do período vem antes do início.")

    weights = cell_weights(polygons, product.grid)
    cells = sorted(set(zip(weights["lat"], weights["lon"])))
    n_requests = len(cells) * len(blocks(start, end))
    if n_requests > max_requests:
        hint = (
            " Use PRECTOTCORR, de grade mais grossa."
            if product.grid is IMERG_GRID
            else " Reduza o período."
        )
        raise ValueError(
            f"Seriam {n_requests} pedidos à NASA POWER ({len(cells)} células × "
            f"{len(blocks(start, end))} blocos de até {BLOCK_YEARS} anos; limite "
            f"{max_requests}).{hint}"
        )

    step(f"{len(cells)} célula(s) da grade {product.grid.name} cruzam as sub-bacias")
    per_cell, meta = {}, {}
    for n, (lat, lon) in enumerate(cells, start=1):
        step(f"Célula {n} de {len(cells)}: pedindo à NASA POWER")
        point = fetch(lat, lon, product.parameters, start, end, product.time_standard)
        if product is ETO:
            per_cell[(lat, lon)] = eto_fao56(point.data, lat, point.elevation_m)
        else:
            per_cell[(lat, lon)] = point.data[product.parameters[0]]
        meta[(lat, lon)] = point

    step("Calculando a média ponderada por sub-bacia")
    series = {}
    for bid, group in weights.groupby("id", sort=False):
        parts = pd.concat(
            [per_cell[(r.lat, r.lon)] * r.weight for r in group.itertuples()], axis=1
        )
        # a gap in any cell leaves the day empty, instead of a partial mean
        series[bid] = parts.sum(axis=1).where(parts.notna().all(axis=1))
    frame = pd.DataFrame(series)
    frame.index.name = "date"
    frame = frame[[i for i in polygons["id"] if i in frame.columns]]
    cut, gaps = complete_period(frame)

    first = next(iter(meta.values()))
    version = first.api.rsplit(" ", 1)[-1].lstrip("v")
    accessed = today or dt.date.today()
    names = names or {}
    origin = {
        "entrada": entry,
        "origem": "NASA POWER",
        "produto": product.label,
        "variaveis": list(product.parameters),
        "unidades": first.units,
        "api": first.api,
        "fontes": sorted({s for p in meta.values() for s in p.sources}),
        "comunidade": COMMUNITY,
        "padrao_tempo": first.time_standard,
        "grade": product.grid.name,
        "espacializacao": "média ponderada pela área de cada célula na sub-bacia",
        "periodo_pedido": f"{start:%Y-%m-%d} a {end:%Y-%m-%d}",
        "periodo_com_dado": _fmt_period(cut.index),
        "dias_faltando": [f"{d:%Y-%m-%d}" for d in gaps],
        "acesso": f"{accessed:%Y-%m-%d}",
        "celulas": [
            {"lat": lat, "lon": lon, "elevacao_m": meta[(lat, lon)].elevation_m}
            for lat, lon in cells
        ],
        "pesos": [
            {
                "id": _plain(r.id),
                "nome": str(names.get(r.id, r.id)),
                "lat": r.lat,
                "lon": r.lon,
                "peso": round(float(r.weight), 6),
            }
            for r in weights.itertuples()
        ],
        "urls": [u for p in meta.values() for u in p.urls],
        "citacao": [
            PROJECT_CITATION,
            f"The data was obtained from the POWER Project's Daily {version} "
            f"version on {accessed:%Y/%m/%d}.",
            *product.sources,
        ],
        "aviso": NOTIFY,
    }
    if product is ETO:
        origin["calculo"] = (
            "ETo FAO-56 Penman-Monteith diária em cada célula (latitude do centro e "
            "elevação da célula devolvida pela API), Rs/Rso entre 0,3 e 1,0; média "
            "ponderada depois do cálculo."
        )
    return cut, gaps, origin


def _plain(value):
    """numpy scalars become Python ones, for JSON."""
    return value.item() if hasattr(value, "item") else value

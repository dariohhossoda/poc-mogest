import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.charts import (
    BASEMAPS,
    NETWORK_DEFAULT_COLORS,
    plot_delineation_preview,
    plot_network_hydrograph,
    plot_network_map,
)
from core.ana import fetch_inventory, stations_in_bbox
from core.delineation import (
    DEFAULT_RESOLUTION_DEG,
    TOPOLOGY_COLUMNS,
    Station,
    delineate,
    export_zip,
    points_bbox,
    series_template,
)
from core.geo import (
    basin_links,
    load_polygons,
    missing_param_columns,
    polygons_to_params,
)
from core.io import load_params, load_timeseries
from core.models import CUNGE_COLUMNS, run_network_simulation
from core.nasa_power import ETO, PRECIPITATION, areal_series, fetch_point
from core.origin import (
    delineation_origin,
    example_origin,
    file_origin,
    origins_json,
)

st.set_page_config(page_title="Rede Hidrológica", page_icon="🏔️", layout="wide")
st.title("🏔️ Roteamento em Rede Hidrológica")
st.markdown(
    "Simula a propagação de vazões em uma rede de subcatchments usando **SMAP** "
    "e **Muskingum** (linear ou Muskingum-Cunge)."
)

PARAMS_PATH = Path("data/example_network_params.csv")
PREC_PATH = Path("data/example_network_prec.csv")
ETP_PATH = Path("data/example_network_etp.csv")
POLYGONS_PATH = Path("data/example_network_basins.geojson")

_DT_SECONDS = 86400.0  # SmapD is daily

_SOURCES = ("Enviar arquivos", "Delimitar a partir de um ponto")
_GLO30 = "Copernicus GLO-30"
_RESOLUTIONS = {'3" (~90 m)': DEFAULT_RESOLUTION_DEG, '1" (~30 m, nativa)': None}
# Cachoeira dam (Cantareira system), the mogest-network example
_EXAMPLE_OUTLET = ("barragem_cachoeira", -23.050833, -46.319278)
_EXAMPLE_STATIONS = pd.DataFrame(
    {"id": ["piracaia_montante"], "lat": [-23.0062], "lon": [-46.2395]}
)
_NO_STATIONS = _EXAMPLE_STATIONS.iloc[0:0]

_SERIES_SOURCES = ("Enviar arquivo", "NASA POWER")
_POWER_START = dt.date(2016, 1, 1)
# POWER leaves the last days empty while its products catch up
_POWER_END = dt.date(2025, 12, 31)

_ROUTING_METHODS = {
    "Muskingum linear (k, x)": "muskingum",
    "Muskingum-Cunge (características do trecho)": "muskingum_cunge",
}


def _load_network_series(source) -> pd.DataFrame:
    """Load prec or etp file; convert column names to int basin IDs when possible."""
    df = load_timeseries(source)
    try:
        df.columns = pd.Index([int(float(c)) for c in df.columns])
    except (ValueError, TypeError):
        pass
    return df


def _map_series_columns(
    df: pd.DataFrame, expected_ids: list, label: str, key_prefix: str
) -> pd.DataFrame:
    """Show mapping UI if df columns don't match expected int basin IDs."""
    expected_set = set(expected_ids)
    current_set = set(df.columns)

    if current_set == expected_set:
        return df

    try:
        converted = {int(float(c)): c for c in df.columns}
        if set(converted.keys()) == expected_set:
            return df.rename(columns={v: k for k, v in converted.items()})
    except (ValueError, TypeError):
        pass

    available = [str(c) for c in df.columns]
    unmatched = [eid for eid in expected_ids if eid not in current_set]
    st.warning(
        f"Colunas de {label} não correspondem aos IDs dos subcatchments. "
        "Selecione a coluna para cada bacia:"
    )
    rename_map: dict = {}
    used: set = set()
    for eid in unmatched:
        opts = [c for c in available if c not in used]
        chosen = st.selectbox(
            f"Bacia **{eid}** — coluna de {label}:", options=opts, key=f"{key_prefix}_map_{eid}"
        )
        rename_map[chosen] = eid
        used.add(chosen)
    return df.rename(columns=rename_map)


def _delineation_points(outlet: Station, stations_df: pd.DataFrame) -> list[Station]:
    """Outlet plus the filled rows of the stations table."""
    rows = stations_df.dropna(subset=["id", "lat", "lon"])
    stations = [
        Station(str(r["id"]).strip(), float(r["lat"]), float(r["lon"]))
        for _, r in rows.iterrows()
        if str(r["id"]).strip()
    ]
    return [outlet, *stations]


@st.cache_data(ttl=86400, max_entries=256, show_spinner=False)
def _fetch_power(lat, lon, parameters, start, end, time_standard):
    """Public data keyed by the cell centre: shared between sessions, in memory."""
    return fetch_point(lat, lon, parameters, start, end, time_standard)


@st.cache_data(ttl=86400, max_entries=1, show_spinner=False)
def _ana_inventory():
    """Public ANA inventory, shared between sessions, in memory (~6 MB)."""
    return fetch_inventory()


def _clicked_ana(selection, stations: pd.DataFrame):
    """Row of the ANA station clicked on the delineation map, or None."""
    for point in (selection or {}).get("selection", {}).get("points", []):
        data = point.get("customdata")
        if isinstance(data, list) and len(data) > 1 and data[0] == "ana":
            match = stations[stations["codigo"] == data[1]]
            if len(match):
                return match.iloc[0]
    return None


def _use_as_outlet(code: str, lat: float, lon: float):
    st.session_state["dl_outlet_id"] = code
    st.session_state["dl_lat"] = lat
    st.session_state["dl_lon"] = lon


def _add_station(code: str, lat: float, lon: float):
    """Append a row to the stations table, keeping the edits made so far."""
    coords, version, _ = st.session_state["dl_stations_base"]
    current = st.session_state.get("dl_stations_last", _NO_STATIONS)
    row = pd.DataFrame({"id": [code], "lat": [lat], "lon": [lon]})
    st.session_state["dl_stations_base"] = (
        coords,
        version + 1,
        pd.concat([current, row], ignore_index=True),
    )


def _render_ana_choice(ana: pd.DataFrame, points_df: pd.DataFrame):
    """Caption of the ANA layer and, once a station is clicked, what to do with it."""
    station = _clicked_ana(st.session_state.get("delineation_map"), ana)
    if station is None:
        st.caption(
            f"{len(ana)} postos da ANA na janela (azul: em operação; cinza: "
            "desativado). Clique em um para usá-lo como exutório ou posto a "
            "montante. Escolha o exutório primeiro: mudá-lo limpa os postos."
        )
        return
    area = (
        "sem área" if pd.isna(station["area_km2"])
        else f"área {station['area_km2']:,.0f} km²"
    )
    status = "em operação" if station["operando"] else "desativado"
    st.markdown(
        f"**{station['codigo']}** {station['nome']} · {station['rio']} · "
        f"{area} · {station['responsavel']} · {status} · "
        f"{station['lat']:.4f}, {station['lon']:.4f}"
    )
    if station["casas_coord"] < 2:
        st.warning(
            f"A coordenada deste posto tem só {station['casas_coord']} casa(s) "
            "decimal(is) no inventário: confira antes de usar."
        )
    code, lat, lon = station["codigo"], float(station["lat"]), float(station["lon"])
    taken = code in set(points_df["id"].astype(str))
    b_outlet, b_station = st.columns(2)
    b_outlet.button(
        "📍 Usar como exutório",
        on_click=_use_as_outlet,
        args=(code, lat, lon),
        disabled=taken,
        key="dl_ana_outlet",
    )
    b_station.button(
        "➕ Adicionar aos postos a montante",
        on_click=_add_station,
        args=(code, lat, lon),
        disabled=taken,
        key="dl_ana_station",
    )
    if taken:
        st.caption("Este posto já está entre os pontos informados.")


def _power_series(kind: str, label: str, polygons, names: dict):
    """
    NASA POWER inputs and download for one series.

    Returns (series, origin) of the current download, or (None, None) while
    there is none for the current period, product and delineation.
    """
    if kind == "prec":
        product = PRECIPITATION[
            st.selectbox(
                "Produto",
                list(PRECIPITATION),
                format_func=lambda k: PRECIPITATION[k].label,
                key="prec_power_product",
            )
        ]
    else:
        product = ETO
        st.caption(product.label)
    c_start, c_end = st.columns(2)
    start = c_start.date_input(
        "Início",
        value=max(_POWER_START, product.first_day),
        min_value=product.first_day,
        max_value=dt.date.today(),
        key=f"{kind}_power_start_{product.key}",
    )
    end = c_end.date_input(
        "Fim",
        value=_POWER_END,
        min_value=product.first_day,
        max_value=dt.date.today(),
        key=f"{kind}_power_end_{product.key}",
    )
    signature = (st.session_state.get("delineation_run"), product.key, start, end)

    if st.button("🛰️ Baixar da NASA POWER", key=f"{kind}_power_go"):
        with st.status(f"{label}: NASA POWER", expanded=True) as status:
            try:
                series, gaps, origin = areal_series(
                    polygons,
                    product,
                    start,
                    end,
                    entry=label,
                    names=names,
                    fetch=_fetch_power,
                    on_step=status.write,
                )
            except (ValueError, RuntimeError) as e:
                status.update(label="Download falhou", state="error")
                st.error(str(e))
                st.stop()
            status.update(label=f"{label}: NASA POWER pronta", state="complete")
        st.session_state[f"power_{kind}"] = {
            "key": signature,
            "series": series,
            "gaps": gaps,
            "origin": origin,
        }

    stored = st.session_state.get(f"power_{kind}")
    if stored is None:
        st.info("Escolha o período e clique em **Baixar da NASA POWER**.")
        return None, None
    if stored["key"] != signature:
        st.info("O período, o produto ou as sub-bacias mudaram: baixe de novo.")
        return None, None
    series, origin = stored["series"], stored["origin"]
    if series.empty:
        st.error("A NASA POWER não tem dado nesse período.")
        return None, None
    if origin["periodo_com_dado"] != f"{start:%Y-%m-%d} a {end:%Y-%m-%d}":
        st.warning(
            f"Período com dado em todas as sub-bacias: {origin['periodo_com_dado']}. "
            "A POWER deixa os últimos dias vazios enquanto atualiza os produtos."
        )
    if stored["gaps"]:
        days = ", ".join(origin["dias_faltando"][:10])
        st.error(f"Dias sem dado no meio da série: {days}. Ajuste o período.")
        return None, None
    st.caption(
        f"{len(origin['celulas'])} célula(s) da grade {origin['grade']}; pesos e "
        "citações em **Origem dos dados**."
    )
    st.download_button(
        f"📥 {label} da NASA POWER (CSV)",
        data=series.to_csv().encode(),
        file_name=f"nasa_power_{kind}.csv",
        mime="text/csv",
        key=f"{kind}_power_dl",
        help="No formato do template: pode ser enviado de volta.",
    )
    return series, origin


def _series_input(kind: str, label: str, polygons, names: dict):
    """Uploaded file or NASA POWER; returns (series, origin) or (None, None)."""
    source = st.radio(
        f"Origem — {label.lower()}",
        _SERIES_SOURCES,
        horizontal=True,
        key=f"{kind}_source",
    )
    if source == _SERIES_SOURCES[1]:
        return _power_series(kind, label, polygons, names)
    file = st.file_uploader(label, type=["csv", "xlsx"], key=f"{kind}_upload")
    if file is None:
        return None, None
    series = _load_network_series(file)
    return series, file_origin(label, file.name, file.getvalue(), series)


def _render_origins(origins: list[dict], key: str):
    """One block per input, with its citations, and the JSON download."""
    for origin in origins:
        st.markdown(f"**{origin['entrada']}** — {origin['origem']}")
        details = {
            k: v
            for k, v in origin.items()
            if k not in ("entrada", "origem", "citacao", "aviso")
        }
        st.json(details, expanded=False)
        for line in origin.get("citacao", []):
            st.caption(line)
        if origin.get("aviso"):
            st.caption(origin["aviso"])
    st.download_button(
        "📥 Origem dos dados (JSON)",
        data=origins_json(origins),
        file_name="origem_dados.json",
        mime="application/json",
        key=f"origins_dl_{key}",
    )


def _render_delineation():
    """
    Delineation inputs and result.

    Returns (params, polygons, rivers, origin) of the current delineation, or stops the
    page while there is none. Everything stays in ``st.session_state``.
    """
    st.markdown(
        "Informe o exutório e, se quiser, postos fluviométricos a montante. As "
        "sub-bacias saem do DEM com o pyflwdir, como no `mogest-network "
        "delinear`. O DEM é lido em memória e nada fica gravado no servidor: "
        "baixe o resultado para guardá-lo. Os valores iniciais são da bacia da "
        "represa Cachoeira (Sistema Cantareira)."
    )
    c_id, c_lat, c_lon = st.columns(3)
    outlet = Station(
        c_id.text_input("ID do exutório", value=_EXAMPLE_OUTLET[0], key="dl_outlet_id"),
        c_lat.number_input(
            "Latitude", -90.0, 90.0, _EXAMPLE_OUTLET[1], format="%.6f", key="dl_lat"
        ),
        c_lon.number_input(
            "Longitude", -180.0, 180.0, _EXAMPLE_OUTLET[2], format="%.6f", key="dl_lon"
        ),
    )
    st.caption(
        "Postos a montante (opcional): cada um vira o exutório de uma sub-bacia. "
        "Mudar as coordenadas do exutório limpa a tabela."
    )
    # The table belongs to the outlet location: moving the outlet gives a new key
    # and an empty table, since the old stations belong to another basin.
    # Renaming the outlet keeps them; the example outlet comes with its station.
    # A station added from the ANA map bumps the version: new key, same rows plus
    # the new one.
    coords = (outlet.lat, outlet.lon)
    base = st.session_state.get("dl_stations_base")
    if base is None or base[0] != coords:
        base = (
            coords,
            0,
            _EXAMPLE_STATIONS if coords == _EXAMPLE_OUTLET[1:] else _NO_STATIONS,
        )
        st.session_state["dl_stations_base"] = base
    _, version, initial = base
    stations_df = st.data_editor(
        initial,
        num_rows="dynamic",
        column_config={
            "id": st.column_config.TextColumn("ID"),
            "lat": st.column_config.NumberColumn("Latitude", format="%.6f"),
            "lon": st.column_config.NumberColumn("Longitude", format="%.6f"),
        },
        hide_index=True,
        key=f"dl_stations_{coords[0]}_{coords[1]}_{version}",
    )
    st.session_state["dl_stations_last"] = stations_df

    c_dem, c_res, c_buf = st.columns(3)
    dem_source = c_dem.radio("DEM", [_GLO30, "GeoTIFF próprio"], key="dl_dem_source")
    glo30 = dem_source == _GLO30
    dem_file = None
    if not glo30:
        dem_file = c_dem.file_uploader(
            "GeoTIFF de elevação", type=["tif", "tiff"], key="dl_dem_file"
        )
    res_label = c_res.selectbox(
        "Resolução do GLO-30", list(_RESOLUTIONS), key="dl_res", disabled=not glo30
    )
    buffer_km = c_buf.number_input(
        "Buffer em volta dos pontos (km)",
        1.0,
        240.0,
        25.0,
        key="dl_buffer",
        disabled=not glo30,
        help="Se a bacia encostar na borda, o buffer dobra até 240 km.",
    )
    with st.expander("Discretização e propagação"):
        a1, a2, a3, a4, a5 = st.columns(5)
        area_min = a1.number_input(
            "Área mínima automática (km²)",
            0.0,
            value=60.0,
            key="dl_area_min",
            help="Divide a bacia em sub-bacias de pelo menos essa área; 0 desliga.",
        )
        river = a2.number_input("Limiar de rio (km²)", 0.1, value=2.0, key="dl_river")
        snap = a3.number_input(
            "Snap máximo (m)", 0.0, value=1500.0, key="dl_snap",
            help="Distância máxima, ao longo do fluxo, para levar um ponto ao rio.",
        )
        celerity = a4.number_input(
            "Celeridade (m/s)", 0.1, value=1.0, key="dl_celerity",
            help="k = comprimento do trecho / celeridade (Muskingum linear).",
        )
        x_musk = a5.number_input("x do Muskingum", 0.0, 0.5, 0.2, key="dl_x")

    points = _delineation_points(outlet, stations_df)
    points_df = pd.DataFrame(
        {
            "id": [p.id for p in points],
            "lat": [p.lat for p in points],
            "lon": [p.lon for p in points],
            "kind": ["Exutório"] + ["Posto"] * (len(points) - 1),
        }
    )
    dem_key = (dem_file.file_id if dem_file else None) if not glo30 else None
    inputs = (
        tuple(points_df.itertuples(index=False)),
        dem_source,
        dem_key,
        _RESOLUTIONS[res_label] if glo30 else None,
        buffer_km if glo30 else None,
        area_min,
        river,
        snap,
        celerity,
        x_musk,
    )

    if st.button("🗺️ Delimitar sub-bacias", type="primary"):
        if len(set(points_df["id"])) != len(points_df):
            st.error("Os IDs do exutório e dos postos devem ser diferentes.")
            st.stop()
        if not glo30 and dem_file is None:
            st.error("Envie o GeoTIFF de elevação ou use o Copernicus GLO-30.")
            st.stop()
        with st.status("Delimitando as sub-bacias…", expanded=True) as status:
            status.write(
                "A primeira delimitação da sessão compila o pyflwdir (numba) e "
                "demora mais."
            )
            try:
                result = delineate(
                    points[0],
                    points[1:],
                    dem_bytes=dem_file.getvalue() if dem_file else None,
                    buffer_km=buffer_km,
                    resolution_deg=_RESOLUTIONS[res_label],
                    area_min_km2=area_min or None,
                    river_threshold_km2=river,
                    max_snap_m=snap,
                    celerity_ms=celerity,
                    x=x_musk,
                    on_step=status.write,
                )
            except (ValueError, RuntimeError) as e:
                status.update(label="Delimitação falhou", state="error")
                st.error(str(e))
                st.stop()
            status.update(label="Sub-bacias delimitadas", state="complete")
        st.session_state["delineation"] = result
        st.session_state["delineation_inputs"] = inputs
        st.session_state["delineation_origin"] = delineation_origin(
            points=points_df,
            glo30=glo30,
            resolution_deg=_RESOLUTIONS[res_label],
            bbox=result.bbox,
            dem_name=dem_file.name if dem_file else None,
            dem_bytes=dem_file.getvalue() if dem_file else None,
            settings={
                "area_min_km2": area_min or None,
                "limiar_rio_km2": river,
                "snap_max_m": snap,
                "celeridade_ms": celerity,
                "x_muskingum": x_musk,
            },
        )
        st.session_state["delineation_run"] = (
            st.session_state.get("delineation_run", 0) + 1
        )
        st.session_state.pop("network_result", None)

    result = st.session_state.get("delineation")
    current = (
        result is not None and st.session_state.get("delineation_inputs") == inputs
    )
    c_base, c_ana = st.columns([2, 3], vertical_alignment="bottom")
    basemap = BASEMAPS[c_base.selectbox("Fundo", list(BASEMAPS), key="dl_basemap")]
    show_ana = c_ana.checkbox(
        "Mostrar postos fluviométricos da ANA",
        key="dl_ana",
        help="Postos de cota ou vazão do inventário Hidroweb na janela do mapa; "
        "clique em um para usá-lo. A primeira consulta do dia baixa o "
        "inventário do Brasil (cerca de 60 MB, alguns segundos).",
    )
    window = points_bbox(points, buffer_km) if glo30 else None
    view = result.bbox if current else window
    ana = None
    if show_ana:
        try:
            with st.spinner("Baixando o inventário de postos da ANA…"):
                inventory = _ana_inventory()
        except RuntimeError as e:
            st.error(str(e))
        else:
            ana = stations_in_bbox(
                inventory, view or points_bbox(points, buffer_km)
            )
    st.plotly_chart(
        plot_delineation_preview(
            points_df,
            bbox=view,
            polygons=result.polygons if current else None,
            rivers=result.rivers if current else None,
            snapped=result.outlets[result.outlets["posto"]] if current else None,
            basemap=basemap,
            ana=ana,
        ),
        width="stretch",
        key="delineation_map",
        on_select="rerun",
        selection_mode="points",
    )
    if ana is not None:
        _render_ana_choice(ana, points_df)
    if result is None:
        st.info("Ajuste os pontos e clique em **Delimitar sub-bacias**.")
        st.stop()
    if not current:
        st.info("Os dados de entrada mudaram: delimite de novo para continuar.")
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("Sub-bacias", len(result.params))
    m2.metric("Área total (km²)", f"{result.params['area'].sum():,.1f}")
    moved = result.outlets[result.outlets["posto"]]
    m3.metric("Maior deslocamento até o rio (m)", f"{moved['dist_snap_m'].max():,.0f}")
    if result.touches_border:
        st.warning(
            "A bacia encosta na borda do DEM: a área pode estar truncada. Aumente "
            "o buffer ou envie um DEM maior."
        )

    st.caption(
        "Parâmetros iniciais: a topologia vem do DEM (só leitura); os parâmetros "
        "SMAP e de propagação podem ser editados."
    )
    params = st.data_editor(
        result.params,
        disabled=list(TOPOLOGY_COLUMNS),
        hide_index=True,
        key=f"dl_params_{st.session_state['delineation_run']}",
    )
    d1, d2 = st.columns(2)
    d1.download_button(
        "📥 Baixar delimitação (.zip)",
        data=export_zip(result, params),
        file_name="delimitacao.zip",
        mime="application/zip",
        help="subbacias.gpkg e parametros.csv podem ser enviados de volta.",
    )
    d2.download_button(
        "📥 Template — precipitação e ETP",
        data=series_template(params),
        file_name="template_rede_series.csv",
        mime="text/csv",
        help="Uma coluna por sub-bacia, com os IDs da delimitação.",
    )
    origin = {
        **st.session_state["delineation_origin"],
        "parametros_editados_na_tela": not params.equals(result.params),
    }
    return params, result.polygons, result.rivers, origin


_MAP_METRICS = (
    "Pico (m³/s)",
    "Média (m³/s)",
    "Volume (hm³)",
    "Fração de montante (%)",
    "Vazão no instante (m³/s)",
)


def _map_values(metric: str, total: pd.DataFrame, natural: pd.DataFrame, when=None):
    if metric.startswith("Pico"):
        return total.max()
    if metric.startswith("Média"):
        return total.mean()
    if metric.startswith("Volume"):
        return total.sum() * _DT_SECONDS / 1e6
    if metric.startswith("Fração"):
        mean_total = total.mean()
        return (1 - natural.mean() / mean_total.where(mean_total > 0)) * 100
    return total.loc[when]


def _clicked_basin(selection, ids: list):
    """Basin id from a plotly map selection (marker customdata or polygon)."""
    for point in (selection or {}).get("selection", {}).get("points", []):
        value = point.get("customdata", point.get("location"))
        if isinstance(value, list):
            value = value[0] if value else None
        if value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
            if value in ids:
                return value
    return None


def _render_map_tab(gdf, total, natural, params, name_map, outlet_ids, rivers=None):
    if gdf is None:
        st.info(
            "Carregue os polígonos das sub-bacias (GeoJSON, shapefile .zip ou "
            "GeoPackage) junto com os dados e execute de novo para ver o mapa."
        )
        return

    ids = [i for i in total.columns if i in set(gdf["id"])]
    if not ids:
        st.warning("Nenhum `id` dos polígonos corresponde às sub-bacias simuladas.")
        return

    c_metric, c_base, c_when = st.columns([2, 1, 3])
    metric = c_metric.selectbox("Métrica", _MAP_METRICS, key="map_metric")
    basemap = BASEMAPS[c_base.selectbox("Fundo", list(BASEMAPS), key="map_basemap")]
    when = None
    if metric.startswith("Vazão no instante"):
        when = c_when.select_slider(
            "Instante",
            options=list(total.index),
            value=total[ids].sum(axis=1).idxmax(),
            format_func=lambda t: pd.Timestamp(t).strftime("%Y-%m-%d"),
            key="map_when",
        )

    labels = {i: name_map.get(i, str(i)) for i in ids}
    clicked = _clicked_basin(st.session_state.get("network_map"), ids)
    if clicked is not None and clicked != st.session_state.get("map_last_click"):
        st.session_state["map_last_click"] = clicked
        st.session_state["map_basin"] = clicked
    if st.session_state.get("map_basin") not in ids:
        st.session_state["map_basin"] = next((o for o in outlet_ids if o in ids), ids[0])

    downstream = params.set_index("id")["downstream_id"]
    col_map, col_hydro = st.columns([3, 2])
    with col_map:
        st.plotly_chart(
            plot_network_map(
                gdf[gdf["id"].isin(ids)],
                _map_values(metric, total[ids], natural[ids], when),
                metric,
                labels,
                outlet_ids,
                basin_links(gdf, downstream),
                basemap=basemap,
                selected=st.session_state["map_basin"],
                rivers=rivers,
            ),
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="network_map",
        )
        st.caption(
            "Exutórios em vermelho; linhas ligam cada sub-bacia à de jusante. "
            "Clique numa sub-bacia para ver o hidrograma."
        )
    with col_hydro:
        basin = st.selectbox(
            "Sub-bacia", ids, format_func=lambda i: labels[i], key="map_basin"
        )
        fig = plot_network_hydrograph(
            pd.DataFrame({"Natural": natural[basin], "Total": total[basin]}),
            title=labels[basin],
        )
        fig.for_each_trace(
            lambda t: t.update(name=t.name.removeprefix("Subcatchment "))
        )
        if when is not None:
            fig.add_vline(x=when, line_dash="dot", line_color="#808080")
        fig.update_layout(height=470, legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")


# --- Checkbox first; uploaders only shown when example is OFF ---
if "use_network_example" not in st.session_state:
    st.session_state["use_network_example"] = True

use_example = st.checkbox("Usar dados de exemplo", key="use_network_example")

if use_example:
    params_df = load_params(PARAMS_PATH)
    prec_df = _load_network_series(PREC_PATH)
    etp_df = _load_network_series(ETP_PATH)
    polygons_gdf = load_polygons(POLYGONS_PATH)
    rivers_gdf = None
    origins = [
        example_origin("Parâmetros da rede", PARAMS_PATH),
        example_origin("Polígonos", POLYGONS_PATH),
        example_origin("Precipitação", PREC_PATH, prec_df),
        example_origin("ETP", ETP_PATH, etp_df),
    ]
    st.info("Usando rede de exemplo com 2 subcatchments.")
    from_delineation = False
else:
    rivers_gdf = None
    origins = []
    source = st.radio(
        "Origem das sub-bacias", _SOURCES, horizontal=True, key="network_source"
    )
    from_delineation = source == _SOURCES[1]
    if from_delineation:
        params_df, polygons_gdf, rivers_gdf, network_origin = _render_delineation()
        st.subheader("Precipitação e ETP")
        st.caption(
            "Cada série vem de um arquivo (uma coluna por sub-bacia, como no "
            "template) ou da NASA POWER, com a média das células da grade "
            "ponderada pela área de cada uma na sub-bacia."
        )
        names = polygons_gdf.set_index("id")["name"].to_dict()
        col_p, col_e = st.columns(2)
        with col_p:
            prec_df, prec_origin = _series_input(
                "prec", "Precipitação", polygons_gdf, names
            )
        with col_e:
            etp_df, etp_origin = _series_input("etp", "ETP", polygons_gdf, names)
        if prec_df is None or etp_df is None:
            st.warning("Defina a precipitação e a ETP para continuar.")
            st.stop()
        origins = [network_origin, prec_origin, etp_origin]
    else:
        col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)
        with col_dl1:
            st.download_button(
                "📥 Template — parâmetros",
                data=PARAMS_PATH.read_bytes(),
                file_name="template_rede_params.csv",
                mime="text/csv",
            )
            st.caption(
                "Colunas: `id, area, str, crec, capc, kkt, k2t, ai, tuin, ebin, k, x, "
                "downstream_id`; `tuin` em % (0–100). Para Muskingum-Cunge: "
                "`length` (m), `q_ref` (m³/s), `manning`, `width` (m), `slope` (m/m)."
            )
        with col_dl2:
            st.download_button(
                "📥 Template — precipitação",
                data=PREC_PATH.read_bytes(),
                file_name="template_rede_prec.csv",
                mime="text/csv",
            )
            st.caption("Colunas: `date, id1, id2, …` — uma coluna de chuva por subcatchment.")
        with col_dl3:
            st.download_button(
                "📥 Template — ETP",
                data=ETP_PATH.read_bytes(),
                file_name="template_rede_etp.csv",
                mime="text/csv",
            )
            st.caption("Colunas: `date, id1, id2, …` — uma coluna de ETP por subcatchment.")
        with col_dl4:
            st.download_button(
                "📥 Template — polígonos",
                data=POLYGONS_PATH.read_bytes(),
                file_name="template_rede_poligonos.geojson",
                mime="application/geo+json",
            )
            st.caption(
                "Opcional. GeoJSON, shapefile (.zip) ou GeoPackage com `id` "
                "(e `name`). Com todas as colunas de parâmetros, dispensa a tabela."
            )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            params_file = st.file_uploader("Parâmetros da rede", type=["csv", "xlsx"])
        with col2:
            prec_file = st.file_uploader(
                "Precipitação", type=["csv", "xlsx"], key="prec_upload"
            )
        with col3:
            etp_file = st.file_uploader("ETP", type=["csv", "xlsx"], key="etp_upload")
        with col4:
            polygons_file = st.file_uploader(
                "Polígonos (opcional)",
                type=["geojson", "json", "zip", "gpkg"],
                key="polygons_upload",
            )

        polygons_gdf = None
        if polygons_file:
            try:
                polygons_gdf = load_polygons(polygons_file)
            except Exception as e:  # malformed geodata raises many error types
                st.error(f"Erro ao ler os polígonos: {e}")
                st.stop()

        if polygons_file:
            origins.append(
                file_origin("Polígonos", polygons_file.name, polygons_file.getvalue())
            )
        if params_file:
            params_df = load_params(params_file)
            origins.insert(
                0,
                file_origin(
                    "Parâmetros da rede", params_file.name, params_file.getvalue()
                ),
            )
        elif polygons_gdf is not None and not missing_param_columns(polygons_gdf):
            params_df = polygons_to_params(polygons_gdf)
            origins[0]["entrada"] = "Polígonos e parâmetros (atributos)"
            st.info(
                "Parâmetros lidos dos atributos dos polígonos; `area` vem da geometria "
                "quando o atributo falta."
            )
        elif polygons_gdf is not None:
            st.warning(
                "Os polígonos não têm todos os parâmetros "
                f"({', '.join(missing_param_columns(polygons_gdf))}): carregue "
                "também a tabela de parâmetros."
            )
            st.stop()
        else:
            st.warning("Carregue os parâmetros (tabela ou polígonos com atributos).")
            st.stop()

        if not (prec_file and etp_file):
            st.warning("Carregue a precipitação e a ETP para continuar.")
            st.stop()
        prec_df = _load_network_series(prec_file)
        etp_df = _load_network_series(etp_file)
        origins += [
            file_origin("Precipitação", prec_file.name, prec_file.getvalue(), prec_df),
            file_origin("ETP", etp_file.name, etp_file.getvalue(), etp_df),
        ]

    if "downstream_id" not in params_df.columns:
        st.warning("Coluna `downstream_id` não encontrada nos parâmetros.")
        ds_col = st.selectbox(
            "Qual coluna representa o subcatchment de jusante (exutório = vazio)?",
            options=list(params_df.columns),
            key="map_downstream_id",
        )
        params_df = params_df.rename(columns={ds_col: "downstream_id"})

    params_df["downstream_id"] = (
        pd.to_numeric(params_df["downstream_id"], errors="coerce")
        .replace(-999, float("nan"))
    )

    expected_ids = params_df["id"].astype(int).tolist()
    prec_df = _map_series_columns(prec_df, expected_ids, "precipitação", "prec")
    etp_df = _map_series_columns(etp_df, expected_ids, "ETP", "etp")

    if set(prec_df.columns) != set(etp_df.columns):
        st.error("Os arquivos de precipitação e ETP devem ter os mesmos IDs de subcatchment após o mapeamento.")
        st.stop()

    common = prec_df.index.intersection(etp_df.index)
    if common.empty:
        st.error("A precipitação e a ETP não têm nenhum dia em comum.")
        st.stop()
    if len(common) < max(len(prec_df), len(etp_df)):
        st.warning(
            "A precipitação e a ETP cobrem períodos diferentes: a simulação usa o "
            f"trecho comum, de {common[0]:%Y-%m-%d} a {common[-1]:%Y-%m-%d}."
        )
        prec_df, etp_df = prec_df.loc[common], etp_df.loc[common]

with st.expander("🔎 Origem dos dados"):
    _render_origins(origins, "inputs")

# The delineation already shows the parameters, in its editable table
if not from_delineation:
    st.subheader("Parâmetros dos Subcatchments")
    st.dataframe(params_df, width="stretch")

_tuin = pd.to_numeric(params_df.get("tuin"), errors="coerce")
if _tuin is not None and (_tuin > 0).any() and (_tuin <= 1).all():
    st.warning(
        "`tuin` é lido em porcentagem (0–100). Valores entre 0 e 1 parecem "
        "fração: multiplique por 100 se for o caso."
    )

method_label = st.radio(
    "Método de propagação",
    list(_ROUTING_METHODS),
    horizontal=True,
    help=(
        "Linear: usa `k` e `x` da sub-bacia que recebe a vazão de montante. "
        "Cunge: calcula k e x a partir do trecho (MGB, Collischonn et al., 2020)."
    ),
)
method = _ROUTING_METHODS[method_label]
if method == "muskingum_cunge":
    _missing = [c for c in CUNGE_COLUMNS if c not in params_df.columns]
    if _missing:
        st.error(
            f"Muskingum-Cunge exige as colunas {', '.join(_missing)} na tabela de "
            "parâmetros (trecho que atravessa a sub-bacia de jusante)."
        )
        st.stop()

basin_ids = params_df["id"].astype(int).tolist()
if polygons_gdf is not None:
    _no_polygon = sorted(set(basin_ids) - set(polygons_gdf["id"]))
    if _no_polygon:
        st.warning(f"Sub-bacias sem polígono (fora do mapa): {_no_polygon}")
if set(st.session_state.get("basin_names", {}).keys()) != set(basin_ids):
    _names_source = (
        polygons_gdf.set_index("id")["name"]
        if polygons_gdf is not None and "name" in polygons_gdf.columns
        else params_df.set_index("id")["name"]
        if "name" in params_df.columns
        else pd.Series(dtype=str)
    )
    st.session_state["basin_names"] = {
        bid: str(_names_source.get(bid, bid)) for bid in basin_ids
    }

if st.button("▶ Executar roteamento", type="primary"):
    with st.spinner("Simulando rede hidrológica..."):
        try:
            result_df, natural_df = run_network_simulation(
                params_df, prec_df, etp_df, method=method
            )
        except ValueError as e:
            st.error(f"Erro na simulação da rede: {e}")
            st.stop()
        st.session_state["network_result"] = result_df
        st.session_state["network_natural"] = natural_df
        st.session_state["network_params"] = params_df.copy()
        st.session_state["network_method"] = method_label
        st.session_state["network_origins"] = origins
        st.session_state["network_polygons"] = polygons_gdf
        st.session_state["network_rivers"] = rivers_gdf

if "network_result" in st.session_state:
    result_df = st.session_state["network_result"]
    params_stored: pd.DataFrame = st.session_state.get("network_params", pd.DataFrame())

    name_map: dict = st.session_state.get("basin_names", {})
    display_df = result_df.rename(columns=name_map)

    # Identify outlet basins (downstream_id is NaN)
    if "downstream_id" in params_stored.columns:
        outlet_ids = (
            params_stored.loc[params_stored["downstream_id"].isna(), "id"]
            .astype(int)
            .tolist()
        )
    else:
        outlet_ids = list(result_df.columns)

    outlet_names = [name_map.get(oid, str(oid)) for oid in outlet_ids]
    outlet_cols = [c for c in display_df.columns if c in outlet_names]

    natural_display = st.session_state["network_natural"].rename(columns=name_map)
    st.caption(f"Método: {st.session_state.get('network_method', '')}")

    tab_all, tab_out, tab_nat, tab_map, tab_stats, tab_raw, tab_origin = st.tabs([
        "📈 Todos os Subcatchments",
        "🔵 Exutórios",
        "🌱 Natural × Total",
        "🗺️ Mapa",
        "📊 Estatísticas",
        "📋 Dados Brutos",
        "🔎 Origem dos dados",
    ])

    with tab_all:
        _btn_col1, _btn_col2, _ = st.columns([1, 1, 8])
        with _btn_col1:
            with st.popover("✏️ Nomes"):
                _name_cols = st.columns(min(len(basin_ids), 4))
                for _i, _bid in enumerate(basin_ids):
                    with _name_cols[_i % len(_name_cols)]:
                        _new_name = st.text_input(
                            f"ID {_bid}",
                            value=st.session_state["basin_names"].get(_bid, str(_bid)),
                            key=f"basin_name_{_bid}",
                        )
                        st.session_state["basin_names"][_bid] = _new_name
        colors_all: dict = {}
        with _btn_col2:
            with st.popover("🎨 Cores"):
                picker_cols = st.columns(min(len(display_df.columns), 5))
                for i, col in enumerate(display_df.columns):
                    default = NETWORK_DEFAULT_COLORS[i % len(NETWORK_DEFAULT_COLORS)]
                    with picker_cols[i % len(picker_cols)]:
                        colors_all[col] = st.color_picker(
                            f"Bacia {col}", value=default, key=f"color_all_{col}"
                        )
        st.plotly_chart(
            plot_network_hydrograph(display_df, colors=colors_all),
            width="stretch",
        )

    with tab_out:
        if outlet_cols:
            colors_out: dict = {}
            with st.popover("🎨 Cores"):
                picker_cols = st.columns(min(len(outlet_cols), 5))
                for i, col in enumerate(outlet_cols):
                    default = NETWORK_DEFAULT_COLORS[i % len(NETWORK_DEFAULT_COLORS)]
                    with picker_cols[i % len(picker_cols)]:
                        colors_out[col] = st.color_picker(
                            f"Bacia {col}", value=default, key=f"color_out_{col}"
                        )
            st.plotly_chart(
                plot_network_hydrograph(
                    display_df[outlet_cols],
                    title="Hidrogramas dos Exutórios",
                    colors=colors_out,
                ),
                width="stretch",
            )
        else:
            st.info("Nenhum exutório identificado (todas as bacias têm jusante definida).")

    with tab_nat:
        st.markdown(
            "**Natural**: vazão gerada pelo SMAP na própria sub-bacia. "
            "**Total**: natural + vazão de montante propagada."
        )
        nat_col = st.selectbox("Sub-bacia", list(display_df.columns), key="nat_basin")
        fig_nat = plot_network_hydrograph(
            pd.DataFrame({
                "Natural": natural_display[nat_col],
                "Total": display_df[nat_col],
            }),
            title=f"Vazão natural e total — {nat_col}",
        )
        fig_nat.for_each_trace(
            lambda t: t.update(name=t.name.removeprefix("Subcatchment "))
        )
        st.plotly_chart(fig_nat, width="stretch")

    with tab_map:
        _render_map_tab(
            st.session_state.get("network_polygons"),
            result_df,
            st.session_state["network_natural"],
            params_stored,
            name_map,
            outlet_ids,
            rivers=st.session_state.get("network_rivers"),
        )

    with tab_stats:
        stats_rows = []
        for col in display_df.columns:
            s = display_df[col]
            stats_rows.append({
                "Bacia": col,
                "Tipo": "Exutório" if col in outlet_names else "Interno",
                "Média (m³/s)": round(float(s.mean()), 3),
                "Média natural (m³/s)": round(float(natural_display[col].mean()), 3),
                "Pico (m³/s)": round(float(s.max()), 3),
                "Volume (hm³)": round(float(s.sum() * _DT_SECONDS / 1e6), 3),
            })
        stats_df = pd.DataFrame(stats_rows).set_index("Bacia")
        st.dataframe(stats_df, width="stretch")
        st.download_button(
            "📥 Baixar estatísticas (CSV)",
            data=stats_df.to_csv().encode(),
            file_name="estatisticas_rede.csv",
            mime="text/csv",
            key="dl_stats",
        )

    with tab_raw:
        raw_df = pd.concat(
            {"total": display_df, "natural": natural_display}, axis=1
        ).round(4)
        raw_df.columns = [f"{name}_{kind}" for kind, name in raw_df.columns]
        st.dataframe(raw_df, width="stretch")
        st.download_button(
            "📥 Exportar resultados (CSV)",
            data=raw_df.to_csv().encode(),
            file_name="resultado_rede.csv",
            mime="text/csv",
        )

    with tab_origin:
        st.caption("Entradas usadas nesta simulação.")
        _render_origins(st.session_state.get("network_origins", []), "result")

import io

import pytest

from core.ana import inventory_url, parse_inventory, stations_in_bbox

# Shape of a HidroInventario response: the schema, then one Table per station
_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="http://MRCS/">
  <xs:schema id="NewDataSet" xmlns:xs="http://www.w3.org/2001/XMLSchema">
    <xs:element name="Table" />
  </xs:schema>
  <diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">
    <NewDataSet xmlns="">
      <Table>
        <RioNome>RIO DA CACHOEIRA</RioNome><nmEstado>S\xc3\x83O PAULO</nmEstado>
        <nmMunicipio>PIRACAIA</nmMunicipio><ResponsavelSigla>SABESP</ResponsavelSigla>
        <OperadoraSigla>SABESP</OperadoraSigla><Codigo>62666010</Codigo>
        <Nome>SB-CA-BRC Barragem Cachoeira</Nome>
        <Latitude>-23.0508</Latitude><Longitude>-46.3192</Longitude>
        <AreaDrenagem>392</AreaDrenagem><TipoEstacaoEscala>1</TipoEstacaoEscala>
        <TipoEstacaoQualAgua>0</TipoEstacaoQualAgua><Operando>1</Operando>
      </Table>
      <Table>
        <Codigo>62666000</Codigo><Nome>PIRACAIA</Nome>
        <Latitude>-23.05</Latitude><Longitude>-46.3333</Longitude>
        <TipoEstacaoEscala>0</TipoEstacaoEscala>
        <PeriodoEscalaInicio>1970-04-01 00:00:00</PeriodoEscalaInicio>
        <Operando>0</Operando>
      </Table>
      <Table>
        <Codigo>62665800</Codigo><Nome>CORPO CENTRAL</Nome>
        <Latitude>-23.0336</Latitude><Longitude>-46.29</Longitude>
        <TipoEstacaoEscala>0</TipoEstacaoEscala>
        <TipoEstacaoQualAgua>1</TipoEstacaoQualAgua>
        <PeriodoEscalaInicio>1800-01-01 00:00:00</PeriodoEscalaInicio>
        <Operando>1</Operando>
      </Table>
      <Table>
        <Codigo>1234567</Codigo><Nome>SEM COORDENADA</Nome>
        <TipoEstacaoEscala>1</TipoEstacaoEscala><Operando>1</Operando>
      </Table>
    </NewDataSet>
  </diffgr:diffgram>
</DataSet>"""


def test_parse_keeps_stage_and_discharge_stations():
    df = parse_inventory(_XML)
    # quality-only site and station without coordinates are dropped
    assert df["codigo"].tolist() == ["62666010", "62666000"]
    first, closed = df.iloc[0], df.iloc[1]
    assert first["area_km2"] == 392
    assert first["estado"] == "SÃO PAULO"
    assert bool(first["operando"]) and not bool(closed["operando"])
    assert closed["casas_coord"] == 2  # -23.05


def test_bbox_and_url():
    df = parse_inventory(_XML)
    assert len(stations_in_bbox(df, (-46.32, -23.1, -46.3, -23.0))) == 1
    url = inventory_url()
    assert "tpEst=1" in url and "nmEstado=&" in url  # every parameter present


def test_fetch_inventory_reports_network_errors():
    import urllib.error

    from core.ana import fetch_inventory

    def offline(url, timeout):
        raise urllib.error.URLError("sem rede")

    with pytest.raises(RuntimeError, match="Falha de rede"):
        fetch_inventory(opener=offline)

    def ok(url, timeout):
        return io.BytesIO(_XML)

    assert len(fetch_inventory(opener=ok)) == 2

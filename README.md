# MOGESTpy App

Interface web em [Streamlit](https://streamlit.io) para os modelos hidrológicos do
[MOGESTpy](https://pypi.org/project/mogestpy/).

**App publicado:** https://mogestpy.streamlit.app

## Páginas

| Página | O que faz |
|---|---|
| Simulação SMAP | SMAP diário (`SmapD`) ou mensal (`SmapM`) em uma bacia: parâmetros editáveis ou importados, métricas (NSE, KGE), volume acumulado, médias mensais, estatísticas anuais e calibração automática (evolução diferencial padrão ou rápida) quando há série observada |
| Rede Hidrológica | SMAP em cada sub-bacia com propagação por Muskingum linear ou Muskingum-Cunge (`mogestpy.quantity.hydrological.routing.run_network`); hidrogramas por sub-bacia e nos exutórios, vazão natural × total, mapa das sub-bacias (pico, média, volume, fração de montante ou vazão num instante; clique abre o hidrograma), estatísticas e exportação. As sub-bacias vêm de arquivos ou são delimitadas a partir de um ponto (ver abaixo) |

## Requisitos

- Python 3.11+
- `mogestpy>=2.1.0` (as demais dependências estão em `pyproject.toml` e `requirements.txt`)

## Como rodar

Local:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/streamlit run app/main.py
```

Docker (http://localhost:8501):

```bash
docker compose up --build
```

Testes e lint:

```bash
pytest
pytest -m slow   # lê o Copernicus GLO-30 pela rede (caso Cachoeira)
ruff check .
```

## Arquivos de entrada

CSV (separador `,` ou `;`) ou XLSX. Cada página oferece um template para download, e os
exemplos estão em `data/`.

| Página | Arquivo | Colunas |
|---|---|---|
| Simulação SMAP | série | `date`, `prec` (mm), `etp` (mm) |
| Simulação SMAP | observada (opcional) | `date`, `obs` (m³/s) |
| Rede Hidrológica | parâmetros | `id`, `area` (km²), `str`, `crec`, `capc`, `kkt`, `k2t`, `ai`, `tuin` (% de 0 a 100), `ebin`, `k`, `x`, `downstream_id` (vazio ou `-999` no exutório) |
| Rede Hidrológica | parâmetros, só para Muskingum-Cunge | `length` (m), `q_ref` (m³/s), `manning`, `width` (m), `slope` (m/m) do trecho que atravessa a sub-bacia que recebe a vazão de montante; `length = 0` passa a vazão sem propagar |
| Rede Hidrológica | precipitação e ETP | `date` e uma coluna por sub-bacia, com o `id` como nome (no modo delimitação, podem vir da NASA POWER) |
| Rede Hidrológica | polígonos (opcional) | GeoJSON, shapefile em `.zip` ou GeoPackage, em qualquer sistema de coordenadas (reprojetado para WGS84), com atributo `id` e, opcionalmente, `name` (no shapefile, `downstream_id` truncado para `downstream` é reconhecido). Se os atributos trouxerem todas as colunas de parâmetros, a tabela de parâmetros é dispensada; `area` em km² é calculada pela geometria quando falta |

## Delimitação a partir de um ponto

Na página Rede, a opção "Delimitar a partir de um ponto" recebe o exutório e, se houver,
postos a montante, e delimita a bacia e as sub-bacias com o
[pyflwdir](https://deltares.github.io/pyflwdir/), com o mesmo código do `mogest-network`
(cópia em `core/mogest_network/`, com a origem registrada no `__init__.py`). O DEM é o
Copernicus GLO-30, lido direto do bucket público só na janela em volta dos pontos, ou um
GeoTIFF enviado. Cada ponto vira o exutório de uma sub-bacia, e uma área mínima opcional
subdivide o restante. Os parâmetros SMAP saem com os padrões do `mogest-network`, e
`k`, `length`, `slope`, `q_ref` e `width` vêm do DEM; tudo pode ser editado antes de
simular. O DEM é limitado a 12 milhões de células (cerca de 3° × 3° a 3").

**Nenhum dado fica no servidor.** DEM, arquivos enviados e resultados vivem só na memória
da sessão. O resultado sai por download: um `.zip` com `subbacias.gpkg` e
`parametros.csv`, que podem ser enviados de volta pela opção "Enviar arquivos", mais
`exutorios.geojson` e `rios.geojson`.

Na rede, o Muskingum linear usa `k` (em passos de tempo, dias) e `x` da sub-bacia que
recebe a vazão de montante, como no `run_network` do MOGESTpy.

### Precipitação e ETP da NASA POWER

Com as sub-bacias delimitadas, a precipitação e a ETP podem vir, cada uma, de um arquivo
ou da [NASA POWER](https://power.larc.nasa.gov/) (diária, sem chave). A série de cada
sub-bacia é a média das células da grade que a cruzam, ponderada pela área de interseção,
com um pedido por célula:

| Série | Produto | Grade | Dia | Desde |
|---|---|---|---|---|
| Precipitação | `PRECTOTCORR` (MERRA-2/GEOS-IT, padrão) | 0,5° × 0,625° | hora solar local | 1981 |
| Precipitação | `IMERG_PRECTOT` (GPM IMERG) | 0,1° | UTC (a API só tem IMERG em UTC) | 2000-06 |
| ETP | ETo FAO-56 Penman-Monteith, calculada em cada célula com `T2M`, `T2M_MAX`, `T2M_MIN`, `RH2M`, `WS2M`, `ALLSKY_SFC_SW_DWN` e `PS` | 0,5° × 0,625° (radiação 1°) | hora solar local | 1984 |

A POWER deixa os últimos dias vazios enquanto atualiza os produtos: o app corta a série
no último dia com dado e avisa. Cada download fica limitado a 60 pedidos (células × blocos
de 10 anos). As séries baixadas saem em CSV no formato do template.

### Origem dos dados

O painel "Origem dos dados" e a aba de mesmo nome nos resultados dizem de onde veio cada
entrada: o nome e o SHA-256 do arquivo enviado, o arquivo de exemplo, o DEM e os
parâmetros da delimitação, ou, para a POWER, o produto, a versão da API, as fontes, as
células e os pesos por sub-bacia, o período e as URLs. O registro vai também para
`origem_dados.json`, com as frases de citação da POWER e a do Copernicus DEM. A NASA pede
que publicações com o dado sejam informadas a `larc-power-project@mail.nasa.gov`.

## Desenvolvimento

Gitflow: `master` é a versão publicada no Streamlit Cloud; `claude` é a branch de
desenvolvimento. Mudanças entram na `claude` e chegam à `master` por merge. Regras do
projeto em `specs.md`; arquitetura em `CLAUDE.md` (todas as chamadas ao mogestpy ficam em
`core/`).

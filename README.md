# MOGESTpy App

Interface web em [Streamlit](https://streamlit.io) para os modelos hidrológicos do
[MOGESTpy](https://pypi.org/project/mogestpy/).

**App publicado:** https://mogestpy.streamlit.app

## Páginas

| Página | O que faz |
|---|---|
| Simulação SMAP | SMAP diário (`SmapD`) ou mensal (`SmapM`) em uma bacia: parâmetros editáveis ou importados, métricas (NSE, KGE), volume acumulado, médias mensais, estatísticas anuais e calibração automática (evolução diferencial padrão ou rápida) quando há série observada |
| Rede Hidrológica | SMAP em cada sub-bacia com propagação por Muskingum linear ou Muskingum-Cunge (`mogestpy.quantity.hydrological.routing.run_network`); hidrogramas por sub-bacia e nos exutórios, vazão natural × total, estatísticas e exportação |
| Visualização Espacial | Mapa das sub-bacias a partir de CSV com coordenadas ou GeoJSON |

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
| Rede Hidrológica | precipitação e ETP | `date` e uma coluna por sub-bacia, com o `id` como nome |
| Visualização Espacial | pontos | `id`, `name`, `lat`, `lon`, `downstream_id` (ou GeoJSON) |

Na rede, o Muskingum linear usa `k` (em passos de tempo, dias) e `x` da sub-bacia que
recebe a vazão de montante, como no `run_network` do MOGESTpy.

## Desenvolvimento

Gitflow: `master` é a versão publicada no Streamlit Cloud; `claude` é a branch de
desenvolvimento. Mudanças entram na `claude` e chegam à `master` por merge. Regras do
projeto em `specs.md`; arquitetura em `CLAUDE.md` (todas as chamadas ao mogestpy ficam em
`core/`).

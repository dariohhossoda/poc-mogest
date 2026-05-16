# Tasks

## Criar mínimo projeto executável

- [x] Configurar repositório e documentação (`CLAUDE.md`, `specs.md`)
- [x] `pyproject.toml` com dependências e configuração pytest/ruff
- [x] `.gitignore`
- [x] `Dockerfile` (multi-stage) + `docker-compose.yml`
- [x] `core/models.py` — wrappers `SmapD`, `SmapM`, `run_network`
- [x] `core/io.py` — leitura de CSVs de séries temporais e parâmetros
- [x] `core/postprocess.py` — métricas NSE, KGE, pico de vazão, volume
- [x] `app/main.py` — página inicial Streamlit
- [x] `app/components/charts.py` — hidrograma interativo (plotly)
- [x] `app/pages/1_Simulacao_SMAP.py` — simulação diária/mensal com parâmetros e upload de dados
- [x] `app/pages/2_Rede_Hidrologica.py` — roteamento SMAP + Muskingum em rede
- [x] `data/` — arquivos de exemplo (diário, mensal, rede)
- [x] `tests/test_postprocess.py` + `tests/test_models.py`
- [x] Executar `pytest` e garantir que todos os testes passam (9/9)
- [x] Commitar e dar push na branch `claude`
- [x] `docker compose up --build -d` — container rodando em http://localhost:8501
- [x] verificar o conteúdo da versão em uso do mogestpy
- [x] corrigir páginas quebradas

## Melhorar projeto

- [x] unificar dados de entrada em arquivo CSV único
- [x] fornecer template para preenchimento dos dados pelo usuário

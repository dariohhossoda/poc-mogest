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
- [x] adicionar identificação de separador do CSV (, e ;)
- [x] adicionar alternativa de entrada por xlsx
- [x] adicionar botão de calibração quando dados observados estão disponíveis
- [x] adicionar botão de download da série de vazões geradas
- [x] adicionar visualização por vazões acumuladas (volume)
- [x] adicionar gráficos de médias mensais
- [x] adicionar tabela com estatísticas gerais resumidas anualmente quando a série de dados é suficiente
- [x] substituir sliders da página `Simulação SMAP` por tabela editável, adicionar `Ad` também nessa tabela
- [x] quando o arquivo upado não possuir as colunas com mesmo nome, perguntar ao usuário qual é a coluna correspondente esperada
- [x] permitir que o usuário suba arquivo com parâmetros ao invés de usar a tabela de parâmetros em `Simulação SMAP`
- [x] criar página para simulação com visualização de mapas

### main

### Simulação SMAP

### Rede Hidrológica
- [x] Alterar upload de série temporal para dois uploads, um arquivo de precipitação e outro de evapotranspiração com as mesmas colunas date, id1, id2...

### Visualização Espacial


## Correções

- [x] corrigir erro com import de csv ValueError: Missing column provided to parse_dates: date
- [x] remover `Tuin` e `Ebin` dos parâmetros selecionáveis na página `Simulação SMAP`
- [x] a tabela de `Parâmetros Calibrados` deve conter no cabeçalho `Parâmetro` e `Valor` ao invés de ` `, `Valor`
- [x] desmarcar `Usar dados de exemplo` ao fazer upload de arquivo na página `Simulação SMAP`
- [x] lidar com a exceção gerada quando uma série observada de tamanho diferente é subida (cortar série e exibir)
- [x] corrigir erro gerado quando a coluna de ids é um número ('int' object has no attribute 'lower')

# specs.md

## Regras do Projeto

- Nunca commitar informações sensíveis, segredos ou variáveis de ambiente (tokens, senhas, chaves de API, arquivos `.env`).
- Sempre seguir estritamente o escopo da task definida. Nunca refatorar código que não esteja explicitamente especificado na task.
- Sempre perguntar quando for necessário instalar um pacote npm ou pypi

## Fluxo de Trabalho

Todo ciclo de desenvolvimento deve seguir esta sequência obrigatória:

1. Garantir que está na branch `claude` — criá-la se não existir (`git checkout -b claude`).
2. Executar `git pull` para sincronizar com o remoto antes de qualquer alteração.
3. Implementar as mudanças conforme a task.
4. Executar os testes (`pytest`) e garantir que todos passam antes de prosseguir.
5. Commitar as mudanças com mensagem descritiva (`git commit`).
6. Executar `git push` para enviar ao remoto.
7. Atualizar o container (`docker compose up --build -d`) e verificar que a aplicação sobe sem erros.

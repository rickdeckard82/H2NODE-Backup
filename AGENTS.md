# AGENTS.md

Guia para agentes de IA (Claude Code, Codex etc.) neste repositório.

## Convenções

**Idioma:** responda sempre em português. Textos da interface, mensagens de erro da API e comentários em pt-BR.

**Mensagens de commit:** em português, conventional commits (`feat:`, `fix(escopo):`), **sem** linha de coautoria (`Co-Authored-By: …`).

**Versionamento e changelog:** a cada mudança perceptível para quem usa o painel, suba `APP_VERSION` em
`frontend/src/lib/changelog.ts` e a `version` em `frontend/package.json`/`backend/pyproject.toml` (os três iguais) e
adicione a entrada em `CHANGELOG` (é o que o rodapé "v…" mostra). Mudança no agente: suba `AGENT_VERSION` em
`agent/pulse-backup-agent.sh`.

**Padrão visual:** o mesmo do Pulse RADIUS (`../pulse-radius/frontend`) — classes `card`/`btn-*`/`input`/`th`/`td`
de `src/index.css`, componentes de `components/ui.tsx`, gráficos SVG próprios em `components/charts.tsx` (sem libs).

## Regras críticas

- **Nunca grave dado de backup em claro no servidor.** O worker decifra só em pipe (memória) para testar.
- **A chave privada GPG só vai para o worker** (`secrets/private/`, montada só nele). O backend nunca a recebe.
- O manifesto do agente é **entrada não confiável**: todo nome de arquivo passa por `storage.safe_child`.
- O `authorized_keys` é **gerado** (`services/sshkeys.py`); toda chave fica presa a `rrsync -wo -no-del` na
  pasta do cliente. Não afrouxe isso.
- **`proxy`, `sshd`, `ftp` e `tftp` ficam em `network_mode: host`** para o ufw do servidor filtrar 80/443/2222/21/69 (portas com
  `ports:` passam por cima do ufw). Nenhum outro serviço publica porta fora do `127.0.0.1`.
- Mudou o formato do manifesto? Mantenha compatibilidade com `format: "pulse-backup/1"` ou crie `/2` aceitando os dois.
- O agente roda como root em servidores de terceiros: bash compatível com 4.2 (sem `set -u`, sem `mapfile -d`),
  só dependências comuns (gpg, rsync, ssh, tar, gzip, coreutils, util-linux).

## Comandos

```bash
make init / make up / make dev        # ver README
make test-backend                     # pytest (SQLite + gpg real) + ruff — rode sempre
make test-e2e                         # ponta a ponta com PostgreSQL, sshd e agente reais (~3 min)
make lint-agent                       # shellcheck
cd frontend && npm ci && npx tsc --noEmit && npx eslint . --max-warnings 0
```

O SQLite dos testes ignora `FOR UPDATE` e outras particularidades do PostgreSQL — mudanças em consultas do
worker precisam passar pelo `make test-e2e`.

### Migrations (Alembic)

```bash
docker compose exec backend alembic revision --autogenerate -m "descricao"   # em dev (make dev)
docker compose exec backend alembic upgrade head
```
Renomeie o arquivo gerado para `AAAAMMDD_NNNN_descricao.py` com `revision = "NNNN"` sequencial.

## Mapa

- `agent/` — agente bash + instalador + exemplo de `agent.conf`.
- `sshd/` — receptor rsync/SSH (Debian + rrsync).
- `backend/app/services/` — `ingest.py` (recepção), `verify.py` (análise), `retention.py`, `gpg.py`, `sshkeys.py`.
- `backend/app/receivers/` — receptores FTP (pyftpdlib) e TFTP (próprio, só WRQ); `services/receivers.py`
  (receivers.json + fila netin/), `services/netingest.py` (cifra na chegada), `services/netconfig.py` (validação).
- `backend/app/worker.py` — loop do worker. `backend/app/api/routes/` — API.
- `frontend/src/features/` — páginas. `docs/` — segurança, restauração, deploy.

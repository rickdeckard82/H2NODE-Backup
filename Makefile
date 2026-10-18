SHELL := /bin/bash
COMPOSE := docker compose
DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help init keys build up dev down clean ps logs migrate seed test-backend test-e2e lint-agent windows-client windows-installer test-windows-client

help: ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

init: ## Cria .env com segredos aleatórios e gera a chave GPG dos backups
	@if [ -f .env ]; then echo ">> .env já existe, mantido."; else \
	  cp .env.example .env; \
	  sed -i \
	    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$(openssl rand -hex 16)|" \
	    -e "s|^JWT_SECRET=.*|JWT_SECRET=$$(openssl rand -hex 32)|" \
	    -e "s|^FERNET_KEY=.*|FERNET_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')|" \
	    -e "s|^BOOTSTRAP_ADMIN_PASSWORD=.*|BOOTSTRAP_ADMIN_PASSWORD=$$(openssl rand -base64 15 | tr -d '/+=')|" \
	    .env; \
	  chmod 600 .env; \
	  echo ">> .env criado. Ajuste BACKUP_STORAGE_PATH, SSH_PUBLIC_HOST e FRONTEND_ORIGIN."; \
	  echo ">> Senha do admin do painel: $$(grep ^BOOTSTRAP_ADMIN_PASSWORD= .env | cut -d= -f2-)"; \
	fi
	@if [ -f secrets/backup-key.pub.asc ]; then echo ">> chave GPG já existe, mantida."; else ./scripts/gen-backup-key.sh; fi

keys: ## Gera a chave GPG dos backups (secrets/)
	./scripts/gen-backup-key.sh

build: ## Builda as imagens
	$(COMPOSE) build

up: ## Sobe a stack (atrás de reverse proxy com TLS)
	$(COMPOSE) up -d

dev: ## Teste local HTTP (COOKIE_SECURE=false) — http://localhost:8080
	$(DEV) up -d --build

down: ## Derruba a stack (mantém volumes e backups)
	$(COMPOSE) down

clean: ## Derruba e APAGA os volumes (banco, chaves de host SSH). Não toca nos backups.
	$(COMPOSE) down -v

ps: ## Status dos containers
	$(COMPOSE) ps

logs: ## Segue os logs
	$(COMPOSE) logs -f --tail=100

migrate: ## Aplica as migrações Alembic
	$(COMPOSE) exec backend alembic upgrade head

seed: ## Cria o primeiro admin (se não houver usuários)
	$(COMPOSE) exec backend python -m app.seed

test-backend: ## Suíte pytest + ruff do backend (imagem própria, sem tocar na stack)
	docker build --build-arg INSTALL_DEV=true -t pulse-backup-backend-test ./backend
	docker run --rm pulse-backup-backend-test sh -c 'ruff check app tests && pytest -q'

test-e2e: ## Teste ponta a ponta: stack isolada + agente real (MariaDB e PostgreSQL)
	./scripts/e2e-test.sh

windows-client: ## Gera windows-client/build/bin/PulseBackup.exe (requer Go, Node e o CLI do Wails v2)
	cd windows-client && wails build -clean -trimpath -platform windows/amd64

windows-installer: windows-client ## Gera windows-client/build/bin/PulseBackup-Setup-<versão>.exe (requer também o NSIS: makensis)
	test -f windows-client/build/MicrosoftEdgeWebview2Setup.exe || curl -fsSL -o windows-client/build/MicrosoftEdgeWebview2Setup.exe "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
	cd windows-client && makensis -V2 -DVERSION=$$(grep -oP 'Version = "\K[0-9.]+' main.go) -DWEBVIEW2_BOOTSTRAPPER=$(CURDIR)/windows-client/build/MicrosoftEdgeWebview2Setup.exe installer/pulse-backup.nsi

test-windows-client: ## Testes do cliente Windows (Go) + tsc/eslint da interface
	cd windows-client && go vet ./internal/... . && go test ./...
	cd windows-client/frontend && npm ci && npx tsc --noEmit && npx eslint . --max-warnings 0

lint-agent: ## shellcheck do agente
	docker run --rm -v $$PWD/agent:/mnt koalaman/shellcheck:stable -S warning /mnt/pulse-backup-agent.sh /mnt/install.sh

#!/usr/bin/env bash
# Migra um servidor que roda o Pulse Backup (projeto compose "pulse-backup") para o
# H2NODE Backup sem perder nada: banco, chaves de host SSH (os agentes continuam
# confiando no servidor), certificados do Caddy e backups ficam onde estão.
#
#   ./scripts/migrar-h2node.sh          mostra o que vai fazer e pede confirmação
#   ./scripts/migrar-h2node.sh -y       sem perguntar
#
# Rode como root, na pasta do repositório (onde está o .env), DEPOIS do git pull.
# Idempotente: rodar de novo não muda nada.
set -euo pipefail

YES=0
[ "${1:-}" = "-y" ] && YES=1
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "não achei o .env nesta pasta ($(pwd))" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker não instalado" >&2; exit 1; }

LEGACY=pulse-backup
envval() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
has_volume() { docker volume inspect "$1" >/dev/null 2>&1; }
old_containers() { docker ps -aq --filter "label=com.docker.compose.project=$LEGACY"; }

plan=()
add_env=()

# 1. Volumes: continuar usando os do projeto antigo
if [ -z "$(envval VOLUME_PREFIX)" ]; then
    if has_volume "${LEGACY}_db_data"; then
        add_env+=("VOLUME_PREFIX=$LEGACY")
        plan+=("usar os volumes existentes ${LEGACY}_* (banco, chaves de host SSH, certificados)")
    else
        add_env+=("VOLUME_PREFIX=h2node-backup")
    fi
fi

# 2. Banco: os padrões mudaram de pulse/pulse_backup para h2node/h2node_backup.
#    O .env gerado pelo `make init` já traz os valores; se faltarem, fixa os antigos.
if [ -z "$(envval POSTGRES_USER)" ]; then
    add_env+=("POSTGRES_USER=pulse"); plan+=("fixar POSTGRES_USER=pulse (usuário atual do banco)")
fi
if [ -z "$(envval POSTGRES_DB)" ]; then
    add_env+=("POSTGRES_DB=pulse_backup"); plan+=("fixar POSTGRES_DB=pulse_backup (banco atual)")
fi

# 3. Containers do projeto antigo saem (os volumes ficam)
if [ -n "$(old_containers)" ]; then
    plan+=("parar e remover os containers do projeto \"$LEGACY\" (docker compose -p $LEGACY down — sem -v)")
fi
plan+=("subir a stack como projeto \"h2node-backup\" (docker compose up -d --build)")

echo "Migração Pulse Backup → H2NODE Backup em $(pwd):"
for p in "${plan[@]}"; do echo "  • $p"; done
for e in "${add_env[@]}"; do echo "  • acrescentar ao .env: $e"; done
echo
if [ "$YES" -ne 1 ]; then
    read -r -p "Continuar? [s/N] " r
    case "$r" in s|S|sim|SIM) ;; *) echo "nada feito."; exit 0 ;; esac
fi

if [ "${#add_env[@]}" -gt 0 ]; then
    cp -p .env ".env.antes-h2node.$(date +%Y%m%d%H%M%S)"
    { echo; echo "# acrescentado por scripts/migrar-h2node.sh"; printf '%s\n' "${add_env[@]}"; } >> .env
fi

if [ -n "$(old_containers)" ]; then
    docker compose -p "$LEGACY" down
fi
docker compose up -d --build

echo
echo "Pronto. Confira: docker compose ps   e   o painel no navegador."
echo "Depois atualize os clientes (agente Linux 1.5.0, cliente Windows) e o template do Zabbix:"
echo "veja docs/migracao-h2node.md."

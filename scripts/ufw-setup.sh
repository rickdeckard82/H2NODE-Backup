#!/usr/bin/env bash
# Regras do ufw para o Pulse Backup (rodar como root no servidor).
#
#   ./scripts/ufw-setup.sh web                 libera 443 (e 80) para todos — painel HTTPS
#   ./scripts/ufw-setup.sh client 203.0.113.10 libera o SSH de backup só para este IP
#   ./scripts/ufw-setup.sh remove 203.0.113.10 remove a liberação do IP
#   ./scripts/ufw-setup.sh status
#
# Não habilita/reseta o ufw nem mexe na porta SSH de administração (22) — isso
# continua com você, para não correr o risco de se trancar fora do servidor.
#
# Funciona porque sshd e proxy rodam com network_mode: host. Portas publicadas
# com `ports:` no Docker passariam POR CIMA do ufw.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(id -u)" -eq 0 ] || { echo "execute como root" >&2; exit 1; }
command -v ufw >/dev/null || { echo "ufw não instalado" >&2; exit 1; }

PORT="$(grep -E '^SSH_PUBLIC_PORT=' .env 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-2222}"

valid_ip() { [[ "$1" =~ ^[0-9a-fA-F:.]+(/[0-9]{1,3})?$ ]]; }

case "${1:-}" in
    web)
        ufw allow 443/tcp comment 'pulse-backup https'
        # 80: redirecionamento para HTTPS e desafio HTTP-01 do Let's Encrypt.
        # Opcional — sem ela o certificado sai pelo desafio TLS-ALPN na 443.
        ufw allow 80/tcp comment 'pulse-backup http->https'
        ;;
    client)
        ip="${2:?informe o IP do cliente de backup}"
        valid_ip "$ip" || { echo "IP inválido: $ip" >&2; exit 1; }
        ufw allow from "$ip" to any port "$PORT" proto tcp comment 'pulse-backup cliente'
        ;;
    remove)
        ip="${2:?informe o IP}"
        ufw delete allow from "$ip" to any port "$PORT" proto tcp
        ;;
    status)
        ufw status numbered | grep -E "pulse-backup|$PORT|443|80/" || echo "nenhuma regra do pulse-backup"
        ;;
    *)
        sed -n '2,13p' "$0"; exit 2 ;;
esac

#!/usr/bin/env bash
# Instala o agente do H2NODE Backup num servidor Linux (rodar como root).
#
#   ./install.sh                    instala e agenda às 02:30 todos os dias
#   ./install.sh --cron "15 1 * * *"   agenda em outro horário
#   ./install.sh --no-cron          só instala (agende você mesmo no crontab do root)
set -euo pipefail

CRON_SPEC="30 2 * * *"
ADD_CRON=1
while [ $# -gt 0 ]; do
    case "$1" in
        --cron) CRON_SPEC="$2"; shift 2 ;;
        --no-cron) ADD_CRON=0; shift ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "execute como root" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=/usr/local/sbin/h2node-backup-agent

missing=()
for b in bash gpg rsync ssh ssh-keygen tar gzip sha256sum flock mkfifo; do
    command -v "$b" >/dev/null 2>&1 || missing+=("$b")
done
if [ "${#missing[@]}" -gt 0 ]; then
    echo "Faltam dependências: ${missing[*]}"
    echo "  Debian/Ubuntu: apt install gnupg rsync openssh-client tar gzip coreutils util-linux"
    echo "  RHEL/Alma/Rocky: dnf install gnupg2 rsync openssh-clients tar gzip coreutils util-linux"
    exit 1
fi

# ── Migração do Pulse Backup (nome anterior) ──────────────────────────────────
# Mantém a chave SSH, o known_hosts e o agent.conf: a pasta antiga vira a nova e
# fica um link no lugar antigo. Tem que vir antes do mkdir abaixo.
LEGACY_BIN=/usr/local/sbin/pulse-backup-agent
if [ -d /etc/pulse-backup ] && [ ! -L /etc/pulse-backup ] && [ ! -e /etc/h2node-backup ]; then
    mv /etc/pulse-backup /etc/h2node-backup
    ln -s /etc/h2node-backup /etc/pulse-backup
    if [ -f /etc/h2node-backup/agent.conf ]; then
        sed -i -e 's#/etc/pulse-backup/#/etc/h2node-backup/#g' \
               -e 's#/var/log/pulse-backup\.log#/var/log/h2node-backup.log#g' \
               -e 's#/var/tmp/pulse-backup\b#/var/tmp/h2node-backup#g' /etc/h2node-backup/agent.conf
    fi
    echo "Configuração do Pulse Backup migrada: /etc/pulse-backup → /etc/h2node-backup"
fi
if [ -f /var/log/pulse-backup.log ] && [ ! -e /var/log/h2node-backup.log ]; then
    mv /var/log/pulse-backup.log /var/log/h2node-backup.log
fi
rm -f /etc/logrotate.d/pulse-backup

install -m 700 -o root -g root "$HERE/h2node-backup-agent.sh" "$BIN"
# nomes antigos apontam para o agente novo (cron ou scripts que ainda os chamem)
if [ -e "$LEGACY_BIN" ] || [ -L "$LEGACY_BIN" ]; then
    ln -sf "$BIN" "$LEGACY_BIN"
    ln -sf "$BIN" /usr/bin/pulse-backup-agent 2>/dev/null || true
fi
# /usr/local/sbin não está no PATH do root/sudo em vários CentOS/Alma/cPanel: atalho em /usr/bin.
ln -sf "$BIN" /usr/bin/h2node-backup-agent 2>/dev/null || echo "aviso: use o caminho completo: $BIN"
mkdir -p /etc/h2node-backup && chmod 700 /etc/h2node-backup
if [ ! -f /etc/h2node-backup/agent.conf ]; then
    install -m 600 -o root -g root "$HERE/agent.conf.example" /etc/h2node-backup/agent.conf
fi
touch /var/log/h2node-backup.log && chmod 600 /var/log/h2node-backup.log

if [ -d /etc/logrotate.d ]; then
    cat > /etc/logrotate.d/h2node-backup <<'EOF'
/var/log/h2node-backup.log {
    monthly
    rotate 12
    compress
    missingok
    notifempty
    create 600 root root
}
EOF
fi

if [ "$ADD_CRON" -eq 1 ]; then
    line="$CRON_SPEC $BIN run >/dev/null 2>&1"
    current="$(crontab -l 2>/dev/null || true)"
    if printf '%s\n' "$current" | grep -q "$LEGACY_BIN run"; then
        # agendamento do Pulse Backup: mantém o horário, troca só o caminho
        printf '%s\n' "$current" | sed "s#$LEGACY_BIN run#$BIN run#" | crontab -
        echo "crontab do root: agendamento do Pulse Backup passou a chamar $BIN (horário mantido)."
    elif printf '%s\n' "$current" | grep -q "$BIN run"; then
        echo "crontab do root já tem o agente — mantido como está."
    else
        printf '%s\n%s\n' "$current" "$line" | sed '/^$/d' | crontab -
        echo "Agendado no crontab do root: $line"
    fi
fi

"$BIN" init

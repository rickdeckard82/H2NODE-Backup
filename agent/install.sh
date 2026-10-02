#!/usr/bin/env bash
# Instala o agente do Pulse Backup num servidor Linux (rodar como root).
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
BIN=/usr/local/sbin/pulse-backup-agent

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

install -m 700 -o root -g root "$HERE/pulse-backup-agent.sh" "$BIN"
mkdir -p /etc/pulse-backup && chmod 700 /etc/pulse-backup
if [ ! -f /etc/pulse-backup/agent.conf ]; then
    install -m 600 -o root -g root "$HERE/agent.conf.example" /etc/pulse-backup/agent.conf
fi
touch /var/log/pulse-backup.log && chmod 600 /var/log/pulse-backup.log

if [ -d /etc/logrotate.d ]; then
    cat > /etc/logrotate.d/pulse-backup <<'EOF'
/var/log/pulse-backup.log {
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
    if printf '%s\n' "$current" | grep -q "$BIN run"; then
        echo "crontab do root já tem o agente — mantido como está."
    else
        printf '%s\n%s\n' "$current" "$line" | sed '/^$/d' | crontab -
        echo "Agendado no crontab do root: $line"
    fi
fi

"$BIN" init

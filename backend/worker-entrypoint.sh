#!/bin/sh
# Entrypoint do worker. Começa como root só para copiar a chave privada GPG (e
# a senha dela) do bind mount para o tmpfs com dono appuser — o arquivo no host
# pode ser 600 de outro usuário. Depois larga os privilégios de vez.
set -eu
mkdir -p /tmp/keys && chmod 700 /tmp/keys
for f in backup-key.sec.asc backup-key.pass; do
    if [ -f "/run/backup-keys/$f" ]; then
        cp "/run/backup-keys/$f" "/tmp/keys/$f"
        chmod 600 "/tmp/keys/$f"
    fi
done
chown -R 10001:10001 /tmp/keys
# volume compartilhado com os receptores FTP/TFTP (painel e worker gravam nele)
[ -d /netcfg ] && chown 10001:10001 /netcfg && chmod 700 /netcfg
[ -f /tmp/keys/backup-key.pass ] && export BACKUP_KEY_PASSPHRASE_FILE=/tmp/keys/backup-key.pass
[ -f /tmp/keys/backup-key.sec.asc ] && export BACKUP_PRIVATE_KEY_PATH=/tmp/keys/backup-key.sec.asc
exec setpriv --reuid=10001 --regid=10001 --init-groups --no-new-privs python -m app.worker

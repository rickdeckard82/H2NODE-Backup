#!/bin/sh
set -eu

# Chaves de host persistentes (volume): o cliente fixa a fingerprint no known_hosts.
[ -f /etc/ssh/keys/ssh_host_ed25519_key ] || ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/keys/ssh_host_ed25519_key
[ -f /etc/ssh/keys/ssh_host_rsa_key ] || ssh-keygen -q -t rsa -b 4096 -N '' -f /etc/ssh/keys/ssh_host_rsa_key
chmod 600 /etc/ssh/keys/*_key

# Volume compartilhado com o backend: authorized_keys (escrito pelo painel) e a
# chave pública de host (exibida no painel para o known_hosts dos clientes).
chown 10001:10001 /ssh && chmod 755 /ssh
[ -f /ssh/authorized_keys ] || install -o 10001 -g 10001 -m 644 /dev/null /ssh/authorized_keys
cp /etc/ssh/keys/ssh_host_ed25519_key.pub /ssh/ssh_host_ed25519_key.pub
chmod 644 /ssh/ssh_host_ed25519_key.pub

# Pasta de backups (montada do host): dono uid 10001, sem acesso para outros.
mkdir -p /data/incoming /data/store /data/quarantine
chown 10001:10001 /data /data/incoming /data/store /data/quarantine
chmod 750 /data
chmod 700 /data/incoming /data/store /data/quarantine

# Porta/interface vêm do compose (o container roda na rede do host).
sed -i -e "s/^Port .*/Port ${SSH_PORT:-2222}/" /etc/ssh/sshd_config
sed -i -e '/^ListenAddress /d' /etc/ssh/sshd_config
if [ -n "${SSH_BIND:-}" ] && [ "${SSH_BIND}" != "0.0.0.0" ]; then
    echo "ListenAddress ${SSH_BIND}" >> /etc/ssh/sshd_config
fi

echo "[sshd] porta ${SSH_PORT:-2222}, fingerprint da chave de host: $(ssh-keygen -lf /etc/ssh/keys/ssh_host_ed25519_key.pub)"
/usr/sbin/sshd -t
exec /usr/sbin/sshd -D -e

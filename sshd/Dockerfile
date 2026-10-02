FROM debian:bookworm-slim

# rsync traz o /usr/bin/rrsync (script python3) usado no command= do authorized_keys.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server rsync python3 \
 && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
 && mkdir -p /run/sshd /etc/ssh/keys /ssh /data

# uid 10001 = o mesmo do appuser do backend/worker (dono dos arquivos recebidos).
# Senha bloqueada com "*" (e não "!"): sem login por senha, mas a conta não
# fica "travada" para o sshd aceitar chave pública.
# O Debian já traz um usuário de sistema "backup" (uid 34): substituído pelo nosso.
RUN userdel backup \
 && useradd -u 10001 -M -d /nonexistent -s /bin/sh backup \
 && usermod -p '*' backup

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh && chmod 644 /etc/ssh/sshd_config

EXPOSE 2222
HEALTHCHECK --interval=30s --timeout=5s CMD pidof sshd >/dev/null || exit 1
ENTRYPOINT ["/entrypoint.sh"]

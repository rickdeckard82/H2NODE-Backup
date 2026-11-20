#!/usr/bin/env bash
# Ajusta o ufw ao Docker (rodar como root no servidor).
#
#   ./scripts/ufw-docker.sh install   insere no ufw o bloco que faz o Docker obedecê-lo
#   ./scripts/ufw-docker.sh remove    remove o bloco (restaura o comportamento padrão do Docker)
#   ./scripts/ufw-docker.sh status    mostra se o bloco está aplicado e a chain DOCKER-USER
#
# Problema: porta publicada com `ports:` é aberta pelo Docker na chain FORWARD
# (via DOCKER), antes de qualquer regra do ufw — o ufw não a bloquearia. O bloco
# abaixo faz a chain DOCKER-USER (avaliada antes das regras do Docker) consultar
# a ufw-user-forward e barrar a entrada de fora para os containers; o tráfego
# entre containers e a saída deles para a internet continuam livres.
#
# Para expor de propósito uma porta de container, libere-a com o ufw:
#   ufw route allow proto tcp from <IP> to any port <porta-do-container>
#
# Este projeto já usa network_mode: host em proxy/sshd/ftp/tftp (essas portas
# passam pelo INPUT e obedecem ao ufw sem este ajuste); o script é a segunda
# camada, para o caso de alguém publicar uma porta com `ports:` por engano.
#
# Não habilita/reseta o ufw nem mexe na porta SSH de administração.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "execute como root" >&2; exit 1; }

# AFTER_RULES só existe para teste; em produção use o padrão do ufw.
RULES="${AFTER_RULES:-/etc/ufw/after.rules}"
BEGIN="# BEGIN H2NODE-BACKUP UFW AND DOCKER"
END="# END H2NODE-BACKUP UFW AND DOCKER"

if [ -z "${AFTER_RULES:-}" ]; then
    command -v ufw >/dev/null || { echo "ufw não instalado" >&2; exit 1; }
fi
[ -f "$RULES" ] || { echo "arquivo não encontrado: $RULES" >&2; exit 1; }

# marcadores gravados antes do rebranding (Pulse Backup): o bloco é o mesmo
LEGACY_BEGIN="# BEGIN PULSE-BACKUP UFW AND DOCKER"
LEGACY_END="# END PULSE-BACKUP UFW AND DOCKER"

applied() { grep -qF "$BEGIN" "$RULES" || grep -qF "$LEGACY_BEGIN" "$RULES"; }

block() {
    cat <<EOF
$BEGIN
*filter
:ufw-user-forward - [0:0]
:ufw-docker-logging-deny - [0:0]
:DOCKER-USER - [0:0]
-A DOCKER-USER -j ufw-user-forward

# tráfego entre containers/redes privadas e respostas de DNS seguem para o Docker
-A DOCKER-USER -j RETURN -s 10.0.0.0/8
-A DOCKER-USER -j RETURN -s 172.16.0.0/12
-A DOCKER-USER -j RETURN -s 192.168.0.0/16
-A DOCKER-USER -p udp -m udp --sport 53 --dport 1024:65535 -j RETURN

# conexão nova vinda de fora (origem não privada) para os containers: negada,
# a menos que exista um \`ufw route allow\`
-A DOCKER-USER -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 10.0.0.0/8 -j ufw-docker-logging-deny
-A DOCKER-USER -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 172.16.0.0/12 -j ufw-docker-logging-deny
-A DOCKER-USER -p tcp -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -d 192.168.0.0/16 -j ufw-docker-logging-deny
-A DOCKER-USER -p udp -m udp --dport 0:32767 -d 10.0.0.0/8 -j ufw-docker-logging-deny
-A DOCKER-USER -p udp -m udp --dport 0:32767 -d 172.16.0.0/12 -j ufw-docker-logging-deny
-A DOCKER-USER -p udp -m udp --dport 0:32767 -d 192.168.0.0/16 -j ufw-docker-logging-deny

-A DOCKER-USER -j RETURN

-A ufw-docker-logging-deny -m limit --limit 3/min --limit-burst 10 -j LOG --log-prefix "[UFW DOCKER BLOCK] "
-A ufw-docker-logging-deny -j DROP
COMMIT
$END
EOF
}

reload() {
    [ -n "${AFTER_RULES:-}" ] && return 0
    ufw reload >/dev/null
    echo "ufw recarregado"
}

case "${1:-}" in
    install)
        if applied; then
            echo "bloco já aplicado em $RULES"; exit 0
        fi
        cp -p "$RULES" "$RULES.h2node-backup.bak"
        { echo; block; } >>"$RULES"
        echo "bloco inserido em $RULES (cópia em $RULES.h2node-backup.bak)"
        reload
        echo "reinicie o Docker para recriar a DOCKER-USER se ela sumiu: systemctl restart docker"
        ;;
    remove)
        applied || { echo "bloco não está aplicado"; exit 0; }
        cp -p "$RULES" "$RULES.h2node-backup.bak"
        sed -i "/^$BEGIN\$/,/^$END\$/d" "$RULES"
        sed -i "/^$LEGACY_BEGIN\$/,/^$LEGACY_END\$/d" "$RULES"
        echo "bloco removido de $RULES (cópia em $RULES.h2node-backup.bak)"
        reload
        ;;
    status)
        if applied; then echo "bloco aplicado em $RULES"; else echo "bloco NÃO aplicado"; fi
        if [ -z "${AFTER_RULES:-}" ] && command -v iptables >/dev/null; then
            iptables -S DOCKER-USER 2>/dev/null || echo "chain DOCKER-USER inexistente (Docker parado?)"
        fi
        ;;
    *)
        sed -n '2,6p' "$0"; exit 2 ;;
esac

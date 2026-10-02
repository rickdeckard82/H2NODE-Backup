#!/usr/bin/env bash
# Teste ponta a ponta, isolado da stack de produção (projeto compose próprio,
# portas próprias, pasta e chaves temporárias):
#
#   1. sobe db + sshd + backend + worker + frontend;
#   2. cria um "servidor cliente" Debian com MariaDB e PostgreSQL de verdade;
#   3. instala o agente, cadastra o cliente pela API e roda `pulse-backup-agent run`;
#   4. espera o worker receber e VERIFICAR (decifrar e testar) o backup;
#   5. confere que nada ficou no WORK_DIR do cliente e que o rrsync barra leitura.
#
# Uso: ./scripts/e2e-test.sh [--keep]   (--keep deixa a stack de pé para inspeção)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

P=pulse-backup-e2e
WORK="$(mktemp -d /tmp/pulse-backup-e2e.XXXXXX)"
WEB_PORT=18080
SSH_PORT=12222
API="http://127.0.0.1:$WEB_PORT/api"
JAR="$WORK/cookies"
CLIENT_CT="$P-client"

export COMPOSE_PROJECT_NAME=$P
export SECRETS_DIR="$WORK/secrets"
export BACKUP_STORAGE_PATH="$WORK/data"
export POSTGRES_PASSWORD=e2e-postgres
export JWT_SECRET="$(openssl rand -hex 32)"
export FERNET_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"
export BOOTSTRAP_ADMIN_PASSWORD="e2e-admin-password"
export SSH_PUBLIC_HOST=host.docker.internal
export SSH_PUBLIC_PORT=$SSH_PORT
export WEB_PORT PUBLIC_DOMAIN=localhost ACME_EMAIL=e2e@localhost
export COOKIE_SECURE=false FRONTEND_ORIGIN="http://127.0.0.1:$WEB_PORT"
export WORKER_POLL_SECONDS=3
# receptores de rede em portas altas (rede do host) para não colidir com nada
export FTP_PORT=12121 TFTP_PORT=16969 FTP_PASSIVE_PORTS=31000-31009 NET_PUBLIC_HOST=host.docker.internal
COMPOSE=(docker compose -f docker-compose.yml)

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mFALHOU: %s\033[0m\n' "$*"; "${COMPOSE[@]}" logs --tail=60 worker backend sshd || true; exit 1; }

teardown() {
    [ "$KEEP" -eq 1 ] && { echo "stack mantida (projeto $P, pasta $WORK)"; return; }
    docker rm -f "$CLIENT_CT" "$P-juniper" "$P-huawei" "$P-datacom" >/dev/null 2>&1 || true
    docker rmi -f "$P-netdev" >/dev/null 2>&1 || true
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
    # os arquivos recebidos são do uid 10001: apaga com um container
    docker run --rm -v "$WORK:/w" debian:bookworm-slim rm -rf /w/data >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap teardown EXIT

api() { # api METHOD PATH [JSON]
    local csrf
    csrf="$(awk '$6=="pb_csrf"{print $7}' "$JAR" 2>/dev/null | tail -1)"
    curl -sS -f -b "$JAR" -c "$JAR" -X "$1" -H "Content-Type: application/json" \
        -H "X-CSRF-Token: $csrf" ${3:+--data "$3"} "$API$2"
}

step "Gerando chave GPG temporária"
mkdir -p "$BACKUP_STORAGE_PATH"
"$ROOT/scripts/gen-backup-key.sh" "Pulse Backup E2E <e2e@test>" >/dev/null
FPR="$(gpg --with-colons --show-keys "$SECRETS_DIR/backup-key.pub.asc" | awk -F: '$1=="fpr"{print $10; exit}')"
echo "fingerprint: $FPR"

step "Subindo a stack ($P)"
"${COMPOSE[@]}" up -d --build --wait db sshd backend worker frontend ftp tftp >/dev/null

step "Login na API"
for _ in $(seq 1 30); do curl -sf "$API/health" >/dev/null && break; sleep 2; done
curl -sS -f -c "$JAR" -H "Content-Type: application/json" \
    --data "{\"username\":\"admin\",\"password\":\"$BOOTSTRAP_ADMIN_PASSWORD\"}" "$API/auth/login" >/dev/null \
    || fail "login"

step "Preparando o servidor cliente (Debian + MariaDB + PostgreSQL)"
docker rm -f "$CLIENT_CT" >/dev/null 2>&1 || true
docker run -d --name "$CLIENT_CT" --add-host=host.docker.internal:host-gateway \
    -v "$ROOT/agent:/agent:ro" debian:bookworm-slim sleep infinity >/dev/null
docker exec "$CLIENT_CT" bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq --no-install-recommends gnupg rsync openssh-client mariadb-server mariadb-client \
      postgresql postgresql-client procps cron >/dev/null 2>&1
  service mariadb start >/dev/null
  mariadb -e "CREATE DATABASE loja; CREATE TABLE loja.pedidos (id INT PRIMARY KEY, total DECIMAL(10,2));
              INSERT INTO loja.pedidos VALUES (1, 10.50), (2, 99.90);"
  service postgresql start >/dev/null
  su postgres -c "psql -q -c \"CREATE DATABASE erp\""
  su postgres -c "psql -q -d erp -c \"CREATE TABLE clientes (id int, nome text); INSERT INTO clientes VALUES (1, '"'"'Ana'"'"');\""
  mkdir -p /srv/site/cache && echo "<h1>ok</h1>" > /srv/site/index.html && echo lixo > /srv/site/cache/tmp.bin
' || fail "preparar cliente"

step "Instalando o agente"
docker exec "$CLIENT_CT" bash -c 'cd /agent && ./install.sh --no-cron' >/dev/null || fail "install.sh"
SSH_PUB="$(docker exec "$CLIENT_CT" cat /etc/pulse-backup/id_ed25519.pub)"

step "Cadastrando o cliente pela API"
CLIENT_JSON="$(api POST /clients "$(printf '{"slug":"web01","name":"Servidor Web 01","ssh_public_key":"%s","expected_interval_hours":24}' "$SSH_PUB")")" \
    || fail "criar cliente"
CID="$(echo "$CLIENT_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
CFG="$(api GET "/clients/$CID/agent-config")"
echo "$CFG" | python3 -c 'import json,sys; print(json.load(sys.stdin)["content"])' > "$WORK/agent.conf"
echo "$CFG" | python3 -c 'import json,sys; print(json.load(sys.stdin)["known_hosts"])' > "$WORK/known_hosts"
grep -q 'host.docker.internal' "$WORK/known_hosts" || fail "known_hosts sem a chave de host"
# liga pastas e bancos
python3 - "$WORK/agent.conf" <<'PY'
import sys, re
p = sys.argv[1]; s = open(p).read()
s = s.replace('BACKUP_PATHS=(\n  "/etc"', 'BACKUP_PATHS=(\n  "/etc"\n  "/srv/site"')
s = s.replace('EXCLUDES=(\n', 'EXCLUDES=(\n  "/srv/site/cache"\n')
s = s.replace('MYSQL_ENABLED="no"', 'MYSQL_ENABLED="yes"').replace('POSTGRES_ENABLED="no"', 'POSTGRES_ENABLED="yes"')
open(p, "w").write(s)
PY
docker cp "$WORK/agent.conf" "$CLIENT_CT:/etc/pulse-backup/agent.conf"
docker cp "$WORK/known_hosts" "$CLIENT_CT:/etc/pulse-backup/known_hosts"
docker cp "$SECRETS_DIR/backup-key.pub.asc" "$CLIENT_CT:/etc/pulse-backup/backup-key.pub.asc"
docker exec "$CLIENT_CT" bash -c 'chown root: /etc/pulse-backup/* && chmod 600 /etc/pulse-backup/agent.conf'

step "pulse-backup-agent test"
docker exec "$CLIENT_CT" pulse-backup-agent test || fail "agent test"

step "pulse-backup-agent run"
docker exec "$CLIENT_CT" pulse-backup-agent run || fail "agent run (veja /var/log/pulse-backup.log)"
docker exec "$CLIENT_CT" tail -n 20 /var/log/pulse-backup.log
LEFT="$(docker exec "$CLIENT_CT" bash -c 'find /var/tmp/pulse-backup -mindepth 1 | wc -l')"
[ "$LEFT" = "0" ] || fail "sobrou $LEFT arquivo(s) no WORK_DIR do cliente"
echo "WORK_DIR do cliente vazio: ok"

step "Esperando o worker receber e verificar"
STATUS=""
for _ in $(seq 1 60); do
    LIST="$(api GET "/backups?client_id=$CID")"
    STATUS="$(echo "$LIST" | python3 -c 'import json,sys; d=json.load(sys.stdin)["items"]; print("/".join(str(d[0][k]) for k in ("status","verify_status","verify_mode")) if d else "")')"
    case "$STATUS" in */ok/*|*/failed/*) break ;; esac
    sleep 2
done
echo "status/verificação/modo: $STATUS"
[ "$STATUS" = "ok/ok/full" ] || fail "esperado ok/ok/full, veio '$STATUS'"

BID="$(echo "$LIST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["id"])')"
api GET "/backups/$BID" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for c in d["components"]:
    print("  %-11s %-32s %-8s verif=%-6s %s" % (c["kind"], c["name"], c["status"], c["verify_status"], c["verify_message"]))
kinds = {c["kind"] for c in d["components"]}
assert {"files", "mysql", "postgresql"} <= kinds, kinds
assert all(c["verify_status"] == "ok" for c in d["components"]), "componente reprovado"
names = [c["name"] for c in d["components"]]
assert "loja" in names and "erp" in names, names
'

step "Conferindo o conteúdo decifrado (fora do sistema, só com gpg + chave privada)"
STORE="$(docker run --rm -v "$BACKUP_STORAGE_PATH:/d" debian:bookworm-slim sh -c 'ls -d /d/store/web01/*/' | head -1)"
docker run --rm -v "$BACKUP_STORAGE_PATH:/d:ro" -v "$SECRETS_DIR/private:/k:ro" debian:bookworm-slim bash -c "
  set -e
  apt-get update -qq >/dev/null && apt-get install -y -qq gnupg >/dev/null 2>&1
  export GNUPGHOME=\$(mktemp -d)
  gpg --batch --quiet --pinentry-mode loopback --passphrase-file /k/backup-key.pass --import /k/backup-key.sec.asc
  dec() { gpg --batch --quiet --pinentry-mode loopback --passphrase-file /k/backup-key.pass -d \"\$1\"; }
  dec $STORE/*-files-srv_site.tar.gz.gpg | tar -tz | sort | tee /tmp/l
  grep -q 'srv/site/index.html' /tmp/l
  ! grep -q 'cache/tmp.bin' /tmp/l
  dec $STORE/*-mysql-loja.sql.gz.gpg | zcat | grep -q '99.90'
  dec $STORE/*-postgresql-erp.sql.gz.gpg | zcat | grep -q 'Ana'
" || fail "restauração manual"
echo "tar restaurável, exclusão respeitada, dumps MariaDB/PostgreSQL com os dados: ok"

step "Segurança do canal: a chave do cliente não lê nem lista nada no servidor"
if docker exec "$CLIENT_CT" bash -c "rsync -e 'ssh -i /etc/pulse-backup/id_ed25519 -p $SSH_PORT -o UserKnownHostsFile=/etc/pulse-backup/known_hosts -o BatchMode=yes' backup@host.docker.internal:./ /tmp/x/" >/dev/null 2>&1; then
    fail "rsync de LEITURA deveria ser negado"
fi
if docker exec "$CLIENT_CT" bash -c "ssh -i /etc/pulse-backup/id_ed25519 -p $SSH_PORT -o UserKnownHostsFile=/etc/pulse-backup/known_hosts -o BatchMode=yes backup@host.docker.internal id" 2>/dev/null | grep -q uid; then
    fail "shell deveria ser negado"
fi
echo "leitura e shell negados: ok"

step "Equipamentos de rede: Juniper (FTP passivo), Huawei (FTP ativo + pasta), Datacom (TFTP)"
docker run --name "$P-netdev-build" debian:bookworm-slim sh -c \
    'apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends curl tftp-hpa >/dev/null 2>&1' \
    || fail "imagem dos equipamentos simulados"
docker commit "$P-netdev-build" "$P-netdev" >/dev/null && docker rm "$P-netdev-build" >/dev/null
for d in juniper huawei datacom; do
    docker run -d --name "$P-$d" --add-host=host.docker.internal:host-gateway "$P-netdev" sleep infinity >/dev/null
done
ipof() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$P-$1"; }
JIP="$(ipof juniper)"; HIP="$(ipof huawei)"; DIP="$(ipof datacom)"
echo "IPs: juniper=$JIP huawei=$HIP datacom=$DIP"

api POST /ftp-accounts '{"username":"juniper","password":"Senha-teste-01"}' >/dev/null || fail "conta ftp juniper"
api POST /ftp-accounts '{"username":"huawei","password":"Hw-backup-01"}' >/dev/null || fail "conta ftp huawei"
newdev() { api POST /clients "$(printf '{"slug":"%s","name":"%s","kind":"network","vendor":"%s","protocol":"%s","mgmt_ip":"%s","expected_interval_hours":0}' "$1" "$2" "$3" "$4" "$5")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }
J_ID="$(newdev mx-core 'MX core' juniper ftp "$JIP")" || fail "cadastro juniper"
H_ID="$(newdev sw-huawei 'SW Huawei' huawei ftp "$HIP")" || fail "cadastro huawei"
D_ID="$(newdev dm4380 'DM4380MP' datacom tftp "$DIP")" || fail "cadastro datacom"
api GET "/clients/$H_ID/device-config?ftp_user=huawei" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commands"])'
sleep 2  # receptores recarregam o receivers.json

docker exec "$P-juniper" sh -c 'printf "## Last commit: 2026-10-01\nversion 23.4R1;\nsystem {\n    host-name mx-core;\n    root-authentication { encrypted-password \"x\"; }\n}\ninterfaces {\n}\n" | gzip > /tmp/c.gz &&
  curl -sS -T /tmp/c.gz "ftp://juniper:Senha-teste-01@host.docker.internal:12121/mx-core_juniper.conf.gz_20261001_120000"' \
    || fail "upload FTP juniper"
docker exec "$P-huawei" sh -c 'printf "#\n sysname SW-HUAWEI-SEGREDO\n#\ninterface Vlanif10\n ip address 192.0.2.15 255.255.255.0\n#\nreturn\n" > /tmp/vrpcfg.cfg &&
  curl -sS -P - --ftp-create-dirs -T /tmp/vrpcfg.cfg "ftp://huawei:Hw-backup-01@host.docker.internal:12121/192.0.2.15/vrpcfg.cfg"' \
    || fail "upload FTP huawei (modo ativo)"
docker exec "$P-datacom" sh -c 'printf "hostname DM4380MP\naaa user admin\ndot1q\n vlan 10\n!\ninterface l3 mgmt\n" > /tmp/config.txt &&
  tftp -m binary host.docker.internal 16969 -c put /tmp/config.txt DM4380MP/config.txt' \
    || fail "upload TFTP datacom"

# IP não cadastrado (o container do servidor Linux) não consegue enviar por TFTP nem FTP
docker exec "$CLIENT_CT" bash -c 'apt-get install -y -qq curl >/dev/null 2>&1; echo x > /tmp/x &&
  ! curl -sS -m 10 -T /tmp/x "ftp://juniper:Senha-teste-01@host.docker.internal:12121/x" 2>/dev/null' \
    || fail "FTP deveria recusar IP não cadastrado"
echo "IP não cadastrado recusado: ok"

for id in "$J_ID" "$H_ID" "$D_ID"; do
    ST=""
    for _ in $(seq 1 40); do
        ST="$(api GET "/backups?client_id=$id" | python3 -c 'import json,sys; d=json.load(sys.stdin)["items"]; print("/".join(str(d[0][k]) for k in ("status","verify_status","verify_mode")) if d else "")')"
        case "$ST" in */ok/*|*/failed/*) break ;; esac
        sleep 2
    done
    api GET "/backups?client_id=$id" | python3 -c '
import json, sys
b = json.load(sys.stdin)["items"][0]
print("  %-10s %-14s %s/%s" % (b["client_slug"], b["run_name"], b["status"], b["verify_status"]))'
    [ "$ST" = "ok/ok/full" ] || fail "equipamento $id: esperado ok/ok/full, veio $ST"
done
if docker run --rm -v "$BACKUP_STORAGE_PATH:/d:ro" debian:bookworm-slim grep -rl "SW-HUAWEI-SEGREDO" /d; then
    fail "configuração em claro encontrada no armazenamento"
fi
echo "nenhuma configuração em claro no disco: ok"

step "Dashboard"
api GET "/dashboard?days=7" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("  origens:", d["clients_total"], "| ok 24h:", d["last24h"]["ok"], "| backups:", d["backups_bytes"], "bytes | worker online:", d["worker"]["online"], "| verificação profunda:", d["worker"]["deep_verify"])
assert d["last24h"]["ok"] == 4 and d["worker"]["online"] and d["worker"]["deep_verify"]
assert d["devices_active"] == 3 and d["servers_active"] == 1
'

printf '\n\033[1;32mE2E OK\033[0m\n'

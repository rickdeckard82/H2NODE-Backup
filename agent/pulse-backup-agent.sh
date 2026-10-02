#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Pulse Backup — agente para servidores Linux
#
# Faz backup das pastas e bancos configurados em /etc/pulse-backup/agent.conf,
# cifra cada parte com a chave pública GPG do servidor, envia por rsync/SSH e
# apaga tudo localmente. Feito para rodar pelo crontab do root.
#
#   pulse-backup-agent init     cria /etc/pulse-backup, gera a chave SSH do agente
#   pulse-backup-agent test     confere config, chave GPG, conexão e bancos
#   pulse-backup-agent run      executa o backup (padrão, usado no crontab)
#   pulse-backup-agent version
#
# Segurança:
#  - Nenhum dado em claro é gravado em disco: cada pasta/dump sai do tar/dump
#    direto para o gpg por pipe. Só arquivos JÁ cifrados ficam no WORK_DIR, e são
#    apagados ao final (com ou sem sucesso). Exceção: SQL Server, que só sabe
#    gravar o .bak em disco — ele é cifrado e apagado logo em seguida.
#  - Cifra assimétrica: o cliente só tem a chave PÚBLICA; um servidor cliente
#    invadido não consegue decifrar backups (nem os próprios).
#  - A chave SSH do agente só consegue ESCREVER na própria pasta do servidor
#    (rrsync -wo -no-del): não lê, não lista e não apaga nada lá.
# ─────────────────────────────────────────────────────────────────────────────
# Sem `set -u`/pipefail: arrays vazios quebram o `-u` no bash 4.2 (CentOS 7) e os
# códigos de saída de cada etapa dos pipelines são lidos via PIPESTATUS.
umask 077
# A última etapa de um pipeline roda no shell atual (encrypt_stream precisa
# devolver variáveis). Funciona porque o script não tem controle de jobs.
shopt -s lastpipe

AGENT_VERSION="1.0.0"
CONF_DIR="/etc/pulse-backup"
CONF_FILE="${PULSE_BACKUP_CONF:-$CONF_DIR/agent.conf}"
LOCK_FILE="/run/pulse-backup-agent.lock"
export LC_ALL=C
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/mssql-tools18/bin:/opt/mssql-tools/bin"

# ---------------------------------------------------------------- utilidades --

LOG_FILE="/var/log/pulse-backup.log"

log() {
    local level="$1"; shift
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) [$level] $*"
    printf '%s\n' "$line" >> "$LOG_FILE" 2>/dev/null || true
    [ -t 2 ] && printf '%s\n' "$line" >&2
    if command -v logger >/dev/null 2>&1; then
        logger -t pulse-backup -p "user.$( [ "$level" = ERROR ] && echo err || echo info )" -- "$*" 2>/dev/null || true
    fi
    return 0
}

die() { log ERROR "$*"; echo "ERRO: $*" >&2; exit 1; }

json_str() {
    # Escapa uma string para JSON (aspas, barra invertida e controles).
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    s="$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')"
    # bytes que não são UTF-8 (nomes de arquivo antigos) invalidariam o JSON
    if command -v iconv >/dev/null 2>&1; then
        s="$(printf '%s' "$s" | iconv -f UTF-8 -t UTF-8 -c 2>/dev/null)"
    fi
    printf '"%s"' "$s"
}

json_num() { printf '%s' "${1:-0}" | tr -cd '0-9' | sed 's/^$/0/'; }

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

safe_name() {
    # "/var/www" -> "var_www" (nome de arquivo seguro, sem barras)
    local n="${1#/}"
    n="$(printf '%s' "$n" | tr -c 'A-Za-z0-9._-' '_' | sed 's/^[._-]*//; s/_\{2,\}/_/g')"
    n="${n:0:80}"
    printf '%s' "${n:-root}"
}

require_root() { [ "$(id -u)" -eq 0 ] || die "execute como root"; }

load_config() {
    [ -f "$CONF_FILE" ] || die "config não encontrada: $CONF_FILE (rode: $0 init)"
    # O arquivo é "sourced" como root: só aceita se for do root e não gravável por outros.
    local owner mode
    owner="$(stat -c %u "$CONF_FILE")"
    mode="$(stat -c %a "$CONF_FILE")"
    [ "$owner" = "0" ] || die "$CONF_FILE precisa ser do root"
    case "$mode" in
        600|400) ;;
        *) die "$CONF_FILE precisa ter modo 600 (atual: $mode)" ;;
    esac

    # Padrões
    CLIENT_ID=""; SERVER_HOST=""; SERVER_PORT="2222"; SERVER_USER="backup"
    SSH_KEY="$CONF_DIR/id_ed25519"; KNOWN_HOSTS="$CONF_DIR/known_hosts"
    GPG_PUBLIC_KEY="$CONF_DIR/backup-key.pub.asc"; GPG_FINGERPRINT=""
    WORK_DIR="/var/tmp/pulse-backup"
    BACKUP_PATHS=(); EXCLUDES=(); ONE_FILE_SYSTEM="no"
    MYSQL_ENABLED="no"; MYSQL_DATABASES=("all"); MYSQL_DEFAULTS_FILE=""; MYSQL_DUMP_OPTS=""
    POSTGRES_ENABLED="no"; POSTGRES_DATABASES=("all"); POSTGRES_OS_USER="postgres"; POSTGRES_GLOBALS="yes"
    MSSQL_ENABLED="no"; MSSQL_DATABASES=("all"); MSSQL_SERVER="localhost"; MSSQL_USER="sa"
    MSSQL_PASSWORD_FILE="$CONF_DIR/mssql.pass"; MSSQL_BACKUP_DIR="/var/opt/mssql/data/pulse-backup"
    BWLIMIT=""; UPLOAD_RETRIES="3"

    # shellcheck source=/dev/null
    . "$CONF_FILE"

    [[ "$CLIENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$ ]] || die "CLIENT_ID inválido: '$CLIENT_ID'"
    [ -n "$SERVER_HOST" ] || die "SERVER_HOST não definido"
    [[ "$SERVER_PORT" =~ ^[0-9]+$ ]] || die "SERVER_PORT inválido"
    [[ "$UPLOAD_RETRIES" =~ ^[0-9]+$ ]] || UPLOAD_RETRIES=3
}

# ----------------------------------------------------------------------- GPG --

GPG_HOME=""

gpg_prepare() {
    command -v gpg >/dev/null 2>&1 || die "gpg não instalado (apt install gnupg / dnf install gnupg2)"
    [ -s "$GPG_PUBLIC_KEY" ] || die "chave pública GPG não encontrada: $GPG_PUBLIC_KEY"
    GPG_HOME="$(mktemp -d /tmp/pulse-backup-gnupg.XXXXXX)" || die "mktemp falhou"
    chmod 700 "$GPG_HOME"
    gpg --homedir "$GPG_HOME" --batch --quiet --import "$GPG_PUBLIC_KEY" 2>/dev/null \
        || die "falha ao importar $GPG_PUBLIC_KEY"
    local fpr
    fpr="$(gpg --homedir "$GPG_HOME" --batch --with-colons --list-keys 2>/dev/null \
        | awk -F: '$1=="fpr" {print $10; exit}')"
    [ -n "$fpr" ] || die "nenhuma chave em $GPG_PUBLIC_KEY"
    if [ -n "$GPG_FINGERPRINT" ]; then
        local want="${GPG_FINGERPRINT// /}"
        [ "${want^^}" = "${fpr^^}" ] \
            || die "impressão digital da chave GPG ($fpr) não confere com GPG_FINGERPRINT ($want)"
    fi
    GPG_RECIPIENT="$fpr"
}

gpg_encrypt_cmd() {
    # Sem compressão no gpg: o conteúdo já chega comprimido (gzip).
    gpg --homedir "$GPG_HOME" --batch --yes --quiet --no-tty \
        --trust-model always --compress-algo none --cipher-algo AES256 \
        --recipient "$GPG_RECIPIENT" --encrypt "$@"
}

GZIP_CMD="gzip -c"
detect_gzip() {
    if command -v pigz >/dev/null 2>&1; then GZIP_CMD="pigz -c"; fi
}

# ----------------------------------------------------- componentes do backup --

RUN_DIR=""
COMPONENTS_JSON=()
ERRORS=()
COMP_INDEX=0
ANY_FAILED=0
ANY_OK=0

# encrypt_stream <arquivo-saida.gpg>  — lê stdin, calcula SHA-256/tamanho do que
# entra (conteúdo comprimido, antes da cifra) e grava o .gpg.
# Saída: variáveis PLAIN_SHA, PLAIN_SIZE, GPG_RC.
encrypt_stream() {
    local out="$1"
    local fifo_sha="$RUN_DIR/.fifo.sha.$$" fifo_len="$RUN_DIR/.fifo.len.$$"
    local sha_file="$RUN_DIR/.sha.$$" len_file="$RUN_DIR/.len.$$"
    mkfifo "$fifo_sha" "$fifo_len" || return 1
    sha256sum < "$fifo_sha" > "$sha_file" & local p1=$!
    wc -c < "$fifo_len" > "$len_file" & local p2=$!
    tee "$fifo_sha" "$fifo_len" | gpg_encrypt_cmd --output "$out"
    GPG_RC=${PIPESTATUS[1]}
    wait "$p1" "$p2"
    PLAIN_SHA="$(cut -d' ' -f1 < "$sha_file")"
    PLAIN_SIZE="$(tr -cd '0-9' < "$len_file")"
    rm -f "$fifo_sha" "$fifo_len" "$sha_file" "$len_file"
    return 0
}

# add_component kind name file status message duration
add_component() {
    local kind="$1" name="$2" file="$3" status="$4" message="$5" dur="$6"
    local size=0 sha=""
    if [ -n "$file" ] && [ -f "$RUN_DIR/$file" ]; then
        size="$(stat -c %s "$RUN_DIR/$file")"
        sha="$(sha256sum "$RUN_DIR/$file" | cut -d' ' -f1)"
    else
        file=""
    fi
    local j
    j="{\"kind\":$(json_str "$kind"),\"name\":$(json_str "$name")"
    if [ -n "$file" ]; then
        j+=",\"file\":$(json_str "$file"),\"size\":$(json_num "$size"),\"sha256\":$(json_str "$sha")"
        j+=",\"plain_size\":$(json_num "${PLAIN_SIZE:-0}")"
        [ -n "${PLAIN_SHA:-}" ] && j+=",\"plain_sha256\":$(json_str "$PLAIN_SHA")"
    fi
    j+=",\"status\":$(json_str "$status")"
    [ -n "$message" ] && j+=",\"message\":$(json_str "${message:0:3900}")"
    j+=",\"duration_s\":$(json_num "$dur")}"
    COMPONENTS_JSON+=("$j")
    case "$status" in
        failed) ANY_FAILED=1; ERRORS+=("$kind $name: $message"); log ERROR "$kind $name: FALHOU — $message" ;;
        warning) ANY_OK=1; log WARN "$kind $name: aviso — $message" ;;
        *) ANY_OK=1; log INFO "$kind $name: ok ($(json_num "$size") bytes cifrados)" ;;
    esac
}

next_prefix() { COMP_INDEX=$((COMP_INDEX + 1)); printf '%02d' "$COMP_INDEX"; }

errtail() { [ -s "$1" ] && tail -c 1500 "$1" | tr '\n' ' '; }

backup_paths() {
    local p
    for p in "${BACKUP_PATHS[@]}"; do
        [ -n "$p" ] || continue
        local name prefix file t0 err
        name="$(safe_name "$p")"
        prefix="$(next_prefix)"
        file="$prefix-files-$name.tar.gz.gpg"
        t0=$SECONDS
        if [ ! -e "$p" ]; then
            add_component files "$p" "" failed "caminho não existe" 0
            continue
        fi
        local args=(--create --file=- --numeric-owner --warning=no-file-changed --warning=no-file-removed)
        tar --xattrs --help >/dev/null 2>&1 && args+=(--xattrs --acls)
        [ "$ONE_FILE_SYSTEM" = "yes" ] && args+=(--one-file-system)
        local ex
        # Os membros do tar são relativos ("var/www/..."), então as exclusões
        # absolutas da config perdem a barra inicial para casar.
        for ex in "${EXCLUDES[@]}"; do [ -n "$ex" ] && args+=("--exclude=${ex#/}"); done
        # Excluir o próprio WORK_DIR (se estiver dentro de uma pasta salva).
        args+=("--exclude=${WORK_DIR#/}")
        err="$RUN_DIR/.err"
        local rel="${p#/}"
        # -C / + caminho relativo: o tar guarda "var/www/..." (restaura em qualquer raiz).
        tar "${args[@]}" -C / "${rel:-.}" 2>"$err" | $GZIP_CMD | encrypt_stream "$RUN_DIR/$file"
        local rcs=("${PIPESTATUS[@]}")
        local tar_rc=${rcs[0]} gz_rc=${rcs[1]}
        local dur=$((SECONDS - t0))
        if [ "$GPG_RC" -ne 0 ] || [ "$gz_rc" -ne 0 ]; then
            rm -f "$RUN_DIR/$file"
            add_component files "$p" "" failed "falha na compressão/cifra (gzip=$gz_rc gpg=$GPG_RC) $(errtail "$err")" "$dur"
        elif [ "$tar_rc" -ge 2 ]; then
            rm -f "$RUN_DIR/$file"
            add_component files "$p" "" failed "tar falhou (rc=$tar_rc): $(errtail "$err")" "$dur"
        elif [ "$tar_rc" -eq 1 ] || [ -s "$err" ]; then
            add_component files "$p" "$file" warning "tar concluiu com avisos (arquivos alterados durante a leitura?): $(errtail "$err")" "$dur"
        else
            add_component files "$p" "$file" ok "" "$dur"
        fi
        rm -f "$err"
    done
}

# ---- MySQL / MariaDB

mysql_bins() {
    MYSQL_BIN="$(command -v mariadb || command -v mysql || true)"
    MYSQLDUMP_BIN="$(command -v mariadb-dump || command -v mysqldump || true)"
}

mysql_auth_args() {
    MYSQL_AUTH=()
    [ -n "$MYSQL_DEFAULTS_FILE" ] && MYSQL_AUTH=("--defaults-extra-file=$MYSQL_DEFAULTS_FILE")
}

mysql_list_dbs() {
    local out
    out="$("$MYSQL_BIN" "${MYSQL_AUTH[@]}" -N -B -e 'SHOW DATABASES')" || return 1
    printf '%s\n' "$out" | grep -Ev '^(information_schema|performance_schema|sys)$' || true
}

backup_mysql() {
    [ "$MYSQL_ENABLED" = "yes" ] || return 0
    mysql_bins; mysql_auth_args
    if [ -z "$MYSQL_BIN" ] || [ -z "$MYSQLDUMP_BIN" ]; then
        add_component mysql "(todos)" "" failed "cliente mysql/mariadb-dump não encontrado" 0
        return
    fi
    local dbs=()
    if [ "${MYSQL_DATABASES[*]}" = "all" ]; then
        local list err="$RUN_DIR/.err"
        if ! list="$(mysql_list_dbs 2>"$err")"; then
            add_component mysql "(todos)" "" failed "não foi possível listar os bancos: $(errtail "$err")" 0
            rm -f "$err"; return
        fi
        mapfile -t dbs <<< "$list"
        rm -f "$err"
    else
        dbs=("${MYSQL_DATABASES[@]}")
    fi
    local db
    for db in "${dbs[@]}"; do
        [ -n "$db" ] || continue
        local prefix file t0 err opts
        prefix="$(next_prefix)"
        file="$prefix-mysql-$(safe_name "$db").sql.gz.gpg"
        err="$RUN_DIR/.err"; t0=$SECONDS
        # shellcheck disable=SC2206
        opts=(--single-transaction --quick --routines --triggers --events --hex-blob
              --default-character-set=utf8mb4 $MYSQL_DUMP_OPTS)
        "$MYSQLDUMP_BIN" "${MYSQL_AUTH[@]}" "${opts[@]}" --databases "$db" 2>"$err" \
            | $GZIP_CMD | encrypt_stream "$RUN_DIR/$file"
        local rcs=("${PIPESTATUS[@]}") dur=$((SECONDS - t0))
        if [ "${rcs[0]}" -ne 0 ] || [ "${rcs[1]}" -ne 0 ] || [ "$GPG_RC" -ne 0 ]; then
            rm -f "$RUN_DIR/$file"
            add_component mysql "$db" "" failed "dump falhou (rc=${rcs[0]} gpg=$GPG_RC): $(errtail "$err")" "$dur"
        elif [ -s "$err" ]; then
            add_component mysql "$db" "$file" warning "$(errtail "$err")" "$dur"
        else
            add_component mysql "$db" "$file" ok "" "$dur"
        fi
        rm -f "$err"
    done
}

# ---- PostgreSQL

pg_run() {
    # Executa como o usuário do SO dono do cluster (autenticação peer).
    if [ "$(id -un)" = "$POSTGRES_OS_USER" ]; then
        "$@"
    elif command -v runuser >/dev/null 2>&1; then
        runuser -u "$POSTGRES_OS_USER" -- "$@"
    else
        su -s /bin/sh "$POSTGRES_OS_USER" -c "$(printf '%q ' "$@")"
    fi
}

backup_postgres() {
    [ "$POSTGRES_ENABLED" = "yes" ] || return 0
    if ! command -v pg_dump >/dev/null 2>&1; then
        add_component postgresql "(todos)" "" failed "pg_dump não encontrado" 0
        return
    fi
    if ! id "$POSTGRES_OS_USER" >/dev/null 2>&1; then
        add_component postgresql "(todos)" "" failed "usuário do SO '$POSTGRES_OS_USER' não existe" 0
        return
    fi
    cd / || true  # pg_dump reclama se o cwd não for legível pelo usuário postgres
    local err="$RUN_DIR/.err"
    if [ "$POSTGRES_GLOBALS" = "yes" ] && command -v pg_dumpall >/dev/null 2>&1; then
        local prefix file t0
        prefix="$(next_prefix)"; file="$prefix-postgresql-globals.sql.gz.gpg"; t0=$SECONDS
        pg_run pg_dumpall --globals-only 2>"$err" | $GZIP_CMD | encrypt_stream "$RUN_DIR/$file"
        local rcs=("${PIPESTATUS[@]}") dur=$((SECONDS - t0))
        if [ "${rcs[0]}" -ne 0 ] || [ "$GPG_RC" -ne 0 ]; then
            rm -f "$RUN_DIR/$file"
            add_component postgresql "(globais: roles/tablespaces)" "" failed "pg_dumpall falhou (rc=${rcs[0]}): $(errtail "$err")" "$dur"
        else
            add_component postgresql "(globais: roles/tablespaces)" "$file" ok "" "$dur"
        fi
    fi
    local dbs=()
    if [ "${POSTGRES_DATABASES[*]}" = "all" ]; then
        local list
        if ! list="$(pg_run psql -X -At -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY 1" 2>"$err")"; then
            add_component postgresql "(todos)" "" failed "não foi possível listar os bancos: $(errtail "$err")" 0
            rm -f "$err"; return
        fi
        mapfile -t dbs <<< "$list"
    else
        dbs=("${POSTGRES_DATABASES[@]}")
    fi
    local db
    for db in "${dbs[@]}"; do
        [ -n "$db" ] || continue
        local prefix file t0
        prefix="$(next_prefix)"
        file="$prefix-postgresql-$(safe_name "$db").sql.gz.gpg"; t0=$SECONDS
        # --create: o dump recria o banco na restauração (psql -f arquivo.sql postgres).
        pg_run pg_dump --create --format=plain --dbname="$db" 2>"$err" \
            | $GZIP_CMD | encrypt_stream "$RUN_DIR/$file"
        local rcs=("${PIPESTATUS[@]}") dur=$((SECONDS - t0))
        if [ "${rcs[0]}" -ne 0 ] || [ "${rcs[1]}" -ne 0 ] || [ "$GPG_RC" -ne 0 ]; then
            rm -f "$RUN_DIR/$file"
            add_component postgresql "$db" "" failed "pg_dump falhou (rc=${rcs[0]} gpg=$GPG_RC): $(errtail "$err")" "$dur"
        elif [ -s "$err" ]; then
            add_component postgresql "$db" "$file" warning "$(errtail "$err")" "$dur"
        else
            add_component postgresql "$db" "$file" ok "" "$dur"
        fi
    done
    rm -f "$err"
}

# ---- SQL Server (mssql-server para Linux)

mssql_query() {
    # Senha via variável de ambiente (não aparece no ps).
    SQLCMDPASSWORD="$(cat "$MSSQL_PASSWORD_FILE")" "$SQLCMD_BIN" -S "$MSSQL_SERVER" -U "$MSSQL_USER" \
        -C -b -h -1 -W -s '|' -Q "SET NOCOUNT ON; $1"
}

backup_mssql() {
    [ "$MSSQL_ENABLED" = "yes" ] || return 0
    SQLCMD_BIN="$(command -v sqlcmd || true)"
    if [ -z "$SQLCMD_BIN" ]; then
        add_component mssql "(todos)" "" failed "sqlcmd não encontrado (mssql-tools18)" 0
        return
    fi
    if [ ! -r "$MSSQL_PASSWORD_FILE" ]; then
        add_component mssql "(todos)" "" failed "arquivo de senha não encontrado: $MSSQL_PASSWORD_FILE" 0
        return
    fi
    mkdir -p "$MSSQL_BACKUP_DIR" && chmod 700 "$MSSQL_BACKUP_DIR"
    id mssql >/dev/null 2>&1 && chown mssql: "$MSSQL_BACKUP_DIR"
    local err="$RUN_DIR/.err" dbs=()
    if [ "${MSSQL_DATABASES[*]}" = "all" ]; then
        local list
        if ! list="$(mssql_query "SELECT name FROM sys.databases WHERE name <> 'tempdb' AND state_desc = 'ONLINE' ORDER BY name" 2>"$err")"; then
            add_component mssql "(todos)" "" failed "não foi possível listar os bancos: $(errtail "$err")" 0
            rm -f "$err"; return
        fi
        mapfile -t dbs <<< "$list"
    else
        dbs=("${MSSQL_DATABASES[@]}")
    fi
    local db
    for db in "${dbs[@]}"; do
        db="${db%%[[:space:]]}"
        [ -n "$db" ] || continue
        if [[ ! "$db" =~ ^[A-Za-z0-9_.\ -]+$ ]]; then
            add_component mssql "$db" "" failed "nome de banco com caracteres não suportados" 0
            continue
        fi
        local prefix file t0 bak
        prefix="$(next_prefix)"
        file="$prefix-mssql-$(safe_name "$db").bak.gz.gpg"
        bak="$MSSQL_BACKUP_DIR/pulse-$(safe_name "$db").bak"; t0=$SECONDS
        rm -f "$bak"
        if ! mssql_query "BACKUP DATABASE [$db] TO DISK = N'$bak' WITH COPY_ONLY, CHECKSUM, INIT, FORMAT" >"$err" 2>&1 \
           || ! mssql_query "RESTORE VERIFYONLY FROM DISK = N'$bak' WITH CHECKSUM" >>"$err" 2>&1; then
            rm -f "$bak"
            add_component mssql "$db" "" failed "BACKUP/VERIFYONLY falhou: $(errtail "$err")" $((SECONDS - t0))
            continue
        fi
        $GZIP_CMD < "$bak" | encrypt_stream "$RUN_DIR/$file"
        local rcs=("${PIPESTATUS[@]}") dur=$((SECONDS - t0))
        rm -f "$bak"
        if [ "${rcs[0]}" -ne 0 ] || [ "$GPG_RC" -ne 0 ]; then
            rm -f "$RUN_DIR/$file"
            add_component mssql "$db" "" failed "falha ao comprimir/cifrar (gzip=${rcs[0]} gpg=$GPG_RC)" "$dur"
        else
            add_component mssql "$db" "$file" ok "RESTORE VERIFYONLY ok" "$dur"
        fi
    done
    rm -f "$err"
}

# --------------------------------------------------------------------- envio --

ssh_cmd() {
    printf 'ssh -i %q -p %q -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=%q -o ConnectTimeout=20 -o ServerAliveInterval=30' \
        "$SSH_KEY" "$SERVER_PORT" "$KNOWN_HOSTS"
}

rsync_send() {
    # rsync_send <origem...> <destino-relativo>
    # shellcheck disable=SC2054  # a vírgula faz parte do valor de --chmod
    local args=(-rt --partial-dir=.rsync-partial --timeout=600 --chmod=F600,D700 -e "$(ssh_cmd)")
    [ -n "$BWLIMIT" ] && args+=("--bwlimit=$BWLIMIT")
    local attempt=1 delay=30 rc=1
    while [ "$attempt" -le "$UPLOAD_RETRIES" ]; do
        rsync "${args[@]}" "$@" 2>"$RUN_DIR/.rsync.err" && return 0
        rc=$?
        log WARN "rsync falhou (tentativa $attempt/$UPLOAD_RETRIES, rc=$rc): $(errtail "$RUN_DIR/.rsync.err")"
        attempt=$((attempt + 1))
        [ "$attempt" -le "$UPLOAD_RETRIES" ] && sleep "$delay" && delay=$((delay * 2))
    done
    return "$rc"
}

write_manifest() {
    local status="$1" started="$2" finished="$3"
    local os_name="" host
    host="$(hostname -f 2>/dev/null || hostname)"
    [ -r /etc/os-release ] && os_name="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-$NAME}")"
    {
        printf '{"format":"pulse-backup/1"'
        printf ',"client_id":%s' "$(json_str "$CLIENT_ID")"
        printf ',"run_name":%s' "$(json_str "$RUN_NAME")"
        printf ',"agent_version":%s' "$(json_str "$AGENT_VERSION")"
        printf ',"hostname":%s' "$(json_str "$host")"
        printf ',"os":%s' "$(json_str "$os_name $(uname -r)")"
        printf ',"started_at":%s,"finished_at":%s' "$(json_str "$started")" "$(json_str "$finished")"
        printf ',"status":%s' "$(json_str "$status")"
        printf ',"encryption_fingerprint":%s' "$(json_str "${GPG_RECIPIENT:-}")"
        printf ',"components":['
        local i
        for i in "${!COMPONENTS_JSON[@]}"; do
            [ "$i" -gt 0 ] && printf ','
            printf '%s' "${COMPONENTS_JSON[$i]}"
        done
        printf '],"errors":['
        for i in "${!ERRORS[@]}"; do
            [ "$i" -gt 0 ] && printf ','
            json_str "${ERRORS[$i]:0:1900}"
        done
        printf ']}\n'
    } > "$RUN_DIR/manifest.json"
}

cleanup() {
    [ -n "$RUN_DIR" ] && [ -d "$RUN_DIR" ] && rm -rf -- "$RUN_DIR"
    [ -n "$GPG_HOME" ] && [ -d "$GPG_HOME" ] && rm -rf -- "$GPG_HOME"
    return 0
}

# ---------------------------------------------------------------- comandos --

cmd_run() {
    require_root
    load_config
    command -v rsync >/dev/null 2>&1 || die "rsync não instalado"
    [ -r "$SSH_KEY" ] || die "chave SSH não encontrada: $SSH_KEY (rode: $0 init)"
    [ -s "$KNOWN_HOSTS" ] || die "known_hosts vazio: $KNOWN_HOSTS (copie a linha do painel)"

    exec 9>"$LOCK_FILE"
    flock -n 9 || die "outra execução do agente ainda está em andamento"

    trap cleanup EXIT
    trap 'log ERROR "interrompido por sinal"; exit 130' INT TERM

    local started
    started="$(now_iso)"
    RUN_NAME="$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
    mkdir -p "$WORK_DIR" && chmod 700 "$WORK_DIR" || die "não foi possível criar $WORK_DIR"
    RUN_DIR="$WORK_DIR/$RUN_NAME"
    mkdir -m 700 "$RUN_DIR" || die "não foi possível criar $RUN_DIR"
    log INFO "início do backup $RUN_NAME (cliente $CLIENT_ID, agente $AGENT_VERSION)"

    gpg_prepare
    detect_gzip
    backup_paths
    backup_mysql
    backup_postgres
    backup_mssql

    local status="success"
    if [ "${#COMPONENTS_JSON[@]}" -eq 0 ]; then
        status="failed"; ERRORS+=("nada configurado para backup (BACKUP_PATHS / *_ENABLED)")
    elif [ "$ANY_FAILED" -eq 1 ] && [ "$ANY_OK" -eq 1 ]; then
        status="partial"
    elif [ "$ANY_FAILED" -eq 1 ]; then
        status="failed"
    fi
    write_manifest "$status" "$started" "$(now_iso)"

    # 1) arquivos cifrados; 2) manifest.json por último — é ele que sinaliza ao
    # servidor que o upload terminou.
    local dest="$SERVER_USER@$SERVER_HOST:$RUN_NAME/"
    local files=()
    mapfile -t files < <(find "$RUN_DIR" -maxdepth 1 -type f -name '*.gpg' -printf '%f\n' | sort)
    local up_ok=0
    (
        cd "$RUN_DIR" || exit 1
        if [ "${#files[@]}" -gt 0 ]; then
            rsync_send "${files[@]}" "$dest" || exit 1
        fi
        rsync_send manifest.json "$dest" || exit 1
    ) && up_ok=1

    if [ "$up_ok" -eq 1 ]; then
        local total
        total="$(du -sb "$RUN_DIR" | cut -f1)"
        log INFO "backup $RUN_NAME enviado (status=$status, $total bytes) — cópia local apagada"
    else
        log ERROR "falha no envio do backup $RUN_NAME — cópia local apagada; o painel acusará o atraso"
    fi
    # cleanup (trap EXIT) apaga o WORK_DIR desta execução
    [ "$up_ok" -eq 1 ] && [ "$status" != "failed" ] && exit 0
    exit 1
}

cmd_init() {
    require_root
    mkdir -p "$CONF_DIR" && chmod 700 "$CONF_DIR"
    if [ ! -f "$CONF_DIR/id_ed25519" ]; then
        ssh-keygen -q -t ed25519 -N '' -C "pulse-backup@$(hostname)" -f "$CONF_DIR/id_ed25519" \
            || die "ssh-keygen falhou"
    fi
    touch "$CONF_DIR/known_hosts" && chmod 600 "$CONF_DIR/known_hosts"
    if [ ! -f "$CONF_FILE" ]; then
        if [ -f "$(dirname "$0")/agent.conf.example" ]; then
            install -m 600 "$(dirname "$0")/agent.conf.example" "$CONF_FILE"
        else
            : > "$CONF_FILE"; chmod 600 "$CONF_FILE"
        fi
    fi
    echo
    echo "Chave pública SSH deste servidor (cole no cadastro do cliente no painel):"
    echo
    cat "$CONF_DIR/id_ed25519.pub"
    echo
    echo "Próximos passos:"
    echo "  1. No painel: Clientes → Novo cliente, cole a chave acima."
    echo "  2. Em \"Configuração do agente\", copie o agent.conf para $CONF_FILE (modo 600)"
    echo "     e a linha do known_hosts para $CONF_DIR/known_hosts."
    echo "  3. Baixe a chave pública GPG para $CONF_DIR/backup-key.pub.asc"
    echo "  4. Teste:  $0 test"
}

cmd_test() {
    require_root
    load_config
    local ok=1
    echo "• Configuração: $CONF_FILE ok (cliente $CLIENT_ID → $SERVER_HOST:$SERVER_PORT)"
    for bin in gpg rsync ssh tar gzip sha256sum flock; do
        command -v "$bin" >/dev/null 2>&1 || { echo "✗ $bin não instalado"; ok=0; }
    done
    gpg_prepare && echo "• Chave GPG: $GPG_RECIPIENT"
    trap cleanup EXIT
    RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pulse-backup-test.XXXXXX")"
    if echo "teste" | gpg_encrypt_cmd --output "$RUN_DIR/t.gpg" && [ -s "$RUN_DIR/t.gpg" ]; then
        echo "• Cifra: ok"
    else
        echo "✗ Cifra falhou"; ok=0
    fi
    local p
    for p in "${BACKUP_PATHS[@]}"; do
        [ -e "$p" ] && echo "• Pasta $p: ok" || { echo "✗ Pasta $p não existe"; ok=0; }
    done
    if [ "$MYSQL_ENABLED" = "yes" ]; then
        mysql_bins; mysql_auth_args
        if [ -n "$MYSQL_BIN" ] && "$MYSQL_BIN" "${MYSQL_AUTH[@]}" -N -B -e 'SELECT 1' >/dev/null 2>&1; then
            echo "• MySQL/MariaDB: conexão ok ($(mysql_list_dbs 2>/dev/null | wc -l) bancos)"
        else
            echo "✗ MySQL/MariaDB: sem conexão"; ok=0
        fi
    fi
    if [ "$POSTGRES_ENABLED" = "yes" ]; then
        cd / || true
        if pg_run psql -X -At -c 'SELECT 1' >/dev/null 2>&1; then
            echo "• PostgreSQL: conexão ok"
        else
            echo "✗ PostgreSQL: sem conexão como $POSTGRES_OS_USER"; ok=0
        fi
    fi
    if [ "$MSSQL_ENABLED" = "yes" ]; then
        SQLCMD_BIN="$(command -v sqlcmd || true)"
        if [ -n "$SQLCMD_BIN" ] && [ -r "$MSSQL_PASSWORD_FILE" ] && mssql_query "SELECT 1" >/dev/null 2>&1; then
            echo "• SQL Server: conexão ok"
        else
            echo "✗ SQL Server: sem conexão"; ok=0
        fi
    fi
    # rrsync -wo não permite listar; um envio vazio testa autenticação + host key.
    mkdir -p "$RUN_DIR/empty"
    if rsync -r -e "$(ssh_cmd)" "$RUN_DIR/empty/" "$SERVER_USER@$SERVER_HOST:.pulse-test/" 2>"$RUN_DIR/err"; then
        echo "• Conexão SSH/rsync com o servidor: ok"
    else
        echo "✗ Conexão SSH/rsync falhou: $(cat "$RUN_DIR/err")"; ok=0
    fi
    [ "$ok" -eq 1 ] && { echo "Tudo certo."; exit 0; }
    exit 1
}

case "${1:-run}" in
    run) cmd_run ;;
    init) cmd_init ;;
    test) cmd_test ;;
    version|--version|-v) echo "pulse-backup-agent $AGENT_VERSION" ;;
    *) echo "uso: $0 {init|test|run|version}" >&2; exit 2 ;;
esac

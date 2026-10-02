#!/usr/bin/env bash
# Gera o par de chaves GPG dos backups:
#   secrets/backup-key.pub.asc          pública  — vai para os clientes e para o backend
#   secrets/private/backup-key.sec.asc  privada  — só o worker (verificação) e o cofre
#   secrets/private/backup-key.pass     senha da chave privada
#
# GUARDE UMA CÓPIA DA PRIVADA + SENHA FORA DESTE SERVIDOR (cofre/pendrive offline).
# Sem ela, NENHUM backup pode ser restaurado. Ver docs/security.md.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${SECRETS_DIR:-secrets}"
if [ -e "$OUT/backup-key.pub.asc" ] || [ -e "$OUT/private/backup-key.sec.asc" ]; then
    echo "Já existe uma chave em $OUT/ — não sobrescrevo (os backups antigos dependem dela)." >&2
    exit 1
fi
UID_NAME="${1:-Pulse Backup <backup@$(hostname -f 2>/dev/null || hostname)>}"
mkdir -p "$OUT/private" && chmod 700 "$OUT/private"
umask 077

gen() {
    # Roda dentro de um GNUPGHOME descartável. --rfc4880: sem AEAD/v5 — qualquer
    # gpg (1.4, 2.2, 2.4) consegue decifrar numa restauração de emergência.
    local home pass
    home="$(mktemp -d)"
    pass="$(openssl rand -base64 33 | tr -d '\n')"
    printf '%s' "$pass" > "$OUT/private/backup-key.pass"
    gpg --homedir "$home" --batch --quiet --rfc4880 --pinentry-mode loopback --passphrase "$pass" \
        --quick-gen-key "$UID_NAME" rsa4096 cert never
    local fpr
    fpr="$(gpg --homedir "$home" --batch --with-colons --list-keys | awk -F: '$1=="fpr"{print $10; exit}')"
    gpg --homedir "$home" --batch --quiet --rfc4880 --pinentry-mode loopback --passphrase "$pass" \
        --quick-add-key "$fpr" rsa4096 encr never
    gpg --homedir "$home" --batch --armor --export "$fpr" > "$OUT/backup-key.pub.asc"
    gpg --homedir "$home" --batch --armor --pinentry-mode loopback --passphrase "$pass" \
        --export-secret-keys "$fpr" > "$OUT/private/backup-key.sec.asc"
    rm -rf "$home"
    echo "$fpr"
}

for b in gpg openssl; do
    command -v "$b" >/dev/null 2>&1 || { echo "instale '$b' no host (apt install gnupg openssl)" >&2; exit 1; }
done
FPR="$(gen)"
chmod 644 "$OUT/backup-key.pub.asc"
chmod 600 "$OUT/private/backup-key.sec.asc" "$OUT/private/backup-key.pass"
echo
echo "Chave dos backups criada. Impressão digital:"
echo "  $FPR"
echo
echo "AGORA: copie secrets/private/backup-key.sec.asc e secrets/private/backup-key.pass"
echo "para um cofre FORA deste servidor. Sem eles não há restauração."

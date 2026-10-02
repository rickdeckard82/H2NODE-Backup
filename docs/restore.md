# Restauração

Os backups ficam em `BACKUP_STORAGE_PATH/store/<cliente>/<execução>/`, um arquivo `.gpg`
por pasta/banco, mais o `manifest.json` (lista as partes, tamanhos e SHA-256). Também dá
para baixar cada parte pelo painel (**Backups → detalhe → Baixar .gpg**, só admin).

## 1. Importar a chave privada (numa máquina segura)

```bash
export GNUPGHOME=$(mktemp -d)
gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass --import backup-key.sec.asc
alias dec='gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass -d'
```

Opcional — conferir a integridade antes:
```bash
sha256sum *.gpg   # compare com "sha256" de cada componente no manifest.json
```

## 2. Restaurar

**Pastas** (os caminhos são relativos à raiz, ex. `etc/nginx/...`):
```bash
mkdir -p /restore && dec 01-files-etc.tar.gz.gpg | tar -xzp --numeric-owner -C /restore
# um arquivo só:
dec 01-files-etc.tar.gz.gpg | tar -xz -C /restore etc/nginx/nginx.conf
```

**MySQL / MariaDB** (o dump tem `CREATE DATABASE`/`USE`):
```bash
dec 03-mysql-loja.sql.gz.gpg | gunzip | mysql
```

**PostgreSQL** (globais primeiro; o dump do banco tem `--create`):
```bash
dec 05-postgresql-globals.sql.gz.gpg | gunzip | sudo -u postgres psql
dec 06-postgresql-erp.sql.gz.gpg     | gunzip | sudo -u postgres psql -d postgres
```

**SQL Server**:
```bash
dec 07-mssql-ERP.bak.gz.gpg | gunzip > /var/opt/mssql/data/ERP.bak
chown mssql: /var/opt/mssql/data/ERP.bak
sqlcmd -S localhost -U sa -C -Q "RESTORE DATABASE [ERP] FROM DISK = N'/var/opt/mssql/data/ERP.bak' WITH REPLACE"
```

## 3. Ensaio

Faça um ensaio de restauração periódico com a cópia **offline** da chave — é a única
forma de garantir que ela (e a senha) estão corretas.

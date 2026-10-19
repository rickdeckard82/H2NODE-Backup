# Pulse Backup

Sistema para **fazer, receber, validar e acompanhar backups de servidores Linux
(inclusive cPanel/WHM) e de configurações de switches, roteadores e OLTs** (FTP/TFTP),
com painel web protegido por login. Stack: **FastAPI + PostgreSQL** no backend,
**React + Vite + Tailwind** no frontend, **rsync sobre SSH** no transporte e
**GPG** na criptografia, tudo em **Docker**. Mesmos padrões visuais e de código do
Pulse RADIUS e do Projeto.io.

| Parte | O que faz |
|---|---|
| **Agente** (`agent/`) | Script bash no crontab do root de cada cliente. Faz tar das pastas e dump dos bancos (MySQL/MariaDB, PostgreSQL, SQL Server), ou cifra **arquivos que já existem** (ex.: backups de conta do cPanel), **cifra cada parte com a chave pública GPG** do servidor, envia por rsync/SSH e **apaga tudo localmente**. |
| **Cliente Windows** (`windows-client/`) | Aplicativo com interface e ícone na bandeja (Go + Wails): escolhe pastas e arquivos, agenda, **cifra no computador** com a chave pública e envia por **HTTPS** (pedaços com retomada) para `/api/agent/v1`. Ver [windows-client/README.md](windows-client/README.md). |
| **ftp / tftp** | Recebem a configuração de switches, roteadores e OLTs (Datacom TFTP; Huawei, Juniper e Fiberhome/UNM2000 FTP). Só gravação, só IPs cadastrados; o worker cifra na chegada. Ver [docs/network-devices.md](docs/network-devices.md). |
| **sshd** | Recebe os uploads. Só chave pública; cada cliente fica preso (`rrsync -wo -no-del`) à própria pasta, **só escrita** — não lê, não lista, não apaga. |
| **worker** | Recebe os uploads completos, confere tamanho/SHA-256, **decifra em streaming e testa o conteúdo** (tar íntegro, dump completo), aplica retenção, reverifica periodicamente e mede o disco. |
| **puller** | Coletor: entra por SSH nos **MikroTik**, roda `/export`, cifra em memória com a chave pública e grava o `.gpg`. Único serviço com saída para a rede além do proxy; não tem a chave privada. |
| **backend** | API de envio HTTPS do cliente Windows (só grava: cria execução, acrescenta bytes, fecha com o manifesto) e API do painel: login com senha (Argon2id) + 2FA opcional, papéis, auditoria, clientes, backups, dashboard. |
| **frontend** | SPA servida por nginx (só em 127.0.0.1), encaminha `/api` ao backend. |
| **proxy** | Caddy: HTTPS público com certificado **Let's Encrypt automático** para `PUBLIC_DOMAIN`. |
| **db** | PostgreSQL 16 (só na rede interna). |

## Arquitetura

```
 servidor cliente (root/cron)                         servidor de backup (docker compose)
 ┌──────────────────────────┐                  ┌──────────────────────────────────────────┐
 │ pulse-backup-agent run   │  rsync/SSH :2222 │ sshd ──▶ /data/incoming/<cliente>/<exec>/ │
 │  tar | gzip | gpg ──┐    │ ───────────────▶ │            │ (pasta montada do host)     │
 │  dump | gzip | gpg ─┤    │  só .gpg +       │ worker ◀───┘ confere, decifra, testa      │
 │  manifest.json ─────┘    │  manifest.json   │   │    └──▶ /data/store/<cliente>/<exec>/ │
 │  (apaga tudo ao final)   │                  │   ▼                                       │
 └──────────────────────────┘                  │ PostgreSQL ◀── backend ◀── frontend ◀── proxy (Caddy) ◀──── navegador
                                               └──────────────────────────────────────────┘   HTTPS :443
```

Detalhes do modelo de segurança em [docs/security.md](docs/security.md).

## Subir o servidor

Pré-requisitos: Docker + Docker Compose, `openssl` e `gnupg` no host.

```bash
make init        # cria .env com segredos aleatórios + gera a chave GPG em secrets/
                 # (mostra a senha do admin do painel)
vim .env         # PUBLIC_DOMAIN, ACME_EMAIL, BACKUP_STORAGE_PATH
sudo ./scripts/ufw-setup.sh web                  # 443/80 para todos
sudo ./scripts/ufw-setup.sh client <IP-cliente>  # porta de backup só para os clientes
sudo ./scripts/ufw-docker.sh install            # opcional: o ufw também vale para portas publicadas pelo Docker
make build && make up
```

- **Guarde agora** `secrets/private/backup-key.sec.asc` e `secrets/private/backup-key.pass`
  num cofre fora deste servidor. Sem eles nenhum backup pode ser restaurado.
- Painel: `https://PUBLIC_DOMAIN` — o certificado Let's Encrypt é emitido e renovado
  sozinho pelo Caddy.
- Clientes enviam para `PUBLIC_DOMAIN:2222`. Proxy e sshd rodam na rede do host
  para que o **ufw** realmente filtre essas portas (o Docker passaria por cima dele).
  Passo a passo em [docs/deploy.md](docs/deploy.md).

Teste local em HTTP: `make dev` → http://localhost:8080 (login `admin` + senha do `.env`).

## Adicionar um cliente Linux

1. Copie a pasta `agent/` para o servidor cliente e, como root:
   ```bash
   cd agent && ./install.sh --cron "30 2 * * *"
   ```
   O instalador coloca o agente em `/usr/local/sbin/pulse-backup-agent` (com atalho em
   `/usr/bin`, porque o `PATH` do root/sudo nem sempre inclui `/usr/local/sbin`), agenda no
   crontab do root e imprime a **chave pública SSH** do agente. Só a pasta `agent/`
   precisa ir para o cliente — não é preciso clonar o repositório.
2. No painel: **Clientes → Novo cliente**, cole a chave SSH.
3. Em **Agente** (no cliente cadastrado) o painel mostra, prontos para copiar:
   o `agent.conf`, a linha do `known_hosts` e o download da chave pública GPG.
   Ajuste `BACKUP_PATHS` e ligue `MYSQL_ENABLED` / `POSTGRES_ENABLED` / `MSSQL_ENABLED`
   conforme o servidor.
4. `pulse-backup-agent test` e depois `pulse-backup-agent run`.

Bancos suportados:

| Banco | Como | Autenticação |
|---|---|---|
| MySQL / MariaDB | `mysqldump`/`mariadb-dump --single-transaction`, um arquivo por banco | unix_socket do root ou `MYSQL_DEFAULTS_FILE` |
| PostgreSQL | `pg_dump --create` por banco + `pg_dumpall --globals-only` | peer, como o usuário `postgres` |
| SQL Server (Linux) | `BACKUP DATABASE … WITH COPY_ONLY, CHECKSUM` + `RESTORE VERIFYONLY` | `sqlcmd`, senha em arquivo 600 |

### MySQL / MariaDB

No `agent.conf`:

```bash
MYSQL_ENABLED="yes"
MYSQL_DATABASES=( "all" )       # todos, menos information_schema/performance_schema/sys; ou ( "radius" "erp" )
MYSQL_DEFAULTS_FILE=""          # vazio = unix_socket do root
MYSQL_DUMP_OPTS=""              # ex.: "--no-tablespaces" no MySQL 8 sem o privilégio PROCESS
```

Se `mysql -e 'SELECT 1'` funciona como root sem pedir senha (padrão do MariaDB no Debian/Ubuntu),
deixe `MYSQL_DEFAULTS_FILE` vazio. Senão, crie `/etc/pulse-backup/mysql.cnf` (root:root, modo 600)
e aponte `MYSQL_DEFAULTS_FILE="/etc/pulse-backup/mysql.cnf"` — o agente o passa como
`--defaults-extra-file` ao `mysql` e ao `mysqldump`/`mariadb-dump`:

```ini
[client]
user=pulsebackup
password="SuaSenhaForteAqui"    # entre aspas se tiver # ; ou espaço
host=localhost
# socket=/var/run/mysqld/mysqld.sock
```

Prefira um usuário só de leitura a usar o root (o dump usa `--single-transaction --routines --triggers --events`):

```sql
CREATE USER 'pulsebackup'@'localhost' IDENTIFIED BY 'SuaSenhaForteAqui';
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES, PROCESS, RELOAD ON *.* TO 'pulsebackup'@'localhost';
-- MySQL 8.0.20+: GRANT SHOW_ROUTINE ON *.* TO 'pulsebackup'@'localhost';
```

`pulse-backup-agent test` deve mostrar `MySQL/MariaDB: conexão ok (N bancos)`. Se mostrar
`sem conexão`, veja o erro com `mysql --defaults-extra-file=/etc/pulse-backup/mysql.cnf -e 'SHOW DATABASES'`.
Cada banco vira um arquivo `NN-mysql-<banco>.sql.gz.gpg`.

## cPanel/WHM e arquivos grandes

Backups que já existem em disco (ex.: um `.tar.gz` por conta do cPanel, dezenas de GB) não
vão por FTP: o agente (1.1+) cifra cada arquivo **como está** e o envia **um de cada vez**
(cifra, envia, apaga só a cópia cifrada — os originais nunca são alterados), então o disco
do cliente só precisa caber o maior arquivo. No `agent.conf`:

```bash
WORK_DIR="/backup/pulse-work"                      # partição grande, fora de /backup/cpanel
BACKUP_FILES=( "/backup/cpanel/@today/accounts/*.tar.gz" )   # só a pasta da data de hoje
BACKUP_PATHS=( "/etc" "/backup/cpanel/@today/system" )       # a pasta system, pequena, vai inteira
```

`@today` vira a data do servidor (`2026-10-16`) e **falha se a pasta de hoje não existir**
(não reenvia a de ontem); `@latest` pega a pasta datada mais recente. Arquivo alterado há menos
de `FILES_MIN_AGE_MINUTES` (10) ainda está sendo gravado e não é enviado — agende o agente
depois que o backup do cPanel termina (à noite, ex. 22:00: a duração do backup do WHM varia
muito). O agente confere se todas as contas de `/var/cpanel/users` têm backup na pasta do dia
e acusa cada uma que faltar (`CPANEL_CHECK_ACCOUNTS`). A verificação confere o gzip até o fim e o SHA-256 do
conteúdo. Em **Contas cPanel** (menu) há uma linha por conta, com busca, versões e download.
Planeje o espaço: o `.tar.gz` não comprime nem deduplica (um dia completo pode passar de 400 GB).

## Downloads

A página **Downloads** do painel entrega o agente Linux (um `.tar.gz` montado na hora a
partir de `agent/`, montado só-leitura no backend), o instalador do cliente Windows
(compilado pelo serviço `client-builder` — Go + Wails + NSIS no Docker, sem Windows — a cada
`docker compose build` em que `windows-client/` mudou) e a chave pública GPG, com SHA-256.
Atualizou o servidor (`git pull && docker compose build && docker compose up -d`), os
downloads já são as versões novas. Outros pacotes podem ser enviados em **Enviar arquivo**
(ficam em `BACKUP_STORAGE_PATH/downloads`). **Link para o servidor (1 h)** gera um link sem login,
assinado e só para aquele arquivo, com os comandos para baixar e instalar direto no cliente.

## Computadores Windows

Em **Servidores**, cadastre o computador (sem chave SSH) e clique em **Windows → Gerar
token**. Baixe o `PulseBackup-Setup-<versão>.exe` em **Downloads** e instale como
administrador (Windows 10/11 ou Windows Server de 64 bits; no Server o instalador oferece
instalar o WebView2 junto). Na janela de configuração, cole o endereço do painel e o token, confira a impressão digital da chave GPG e escolha pastas,
arquivos e horário. O aplicativo fica na bandeja, abre com o Windows, cifra cada item no
próprio computador e envia por HTTPS — o worker verifica como qualquer outro backup.
Passo a passo em **Ajuda → Windows**.

## Switches, roteadores e OLTs

Cadastre em **Equipamentos de rede** (fabricante, protocolo, IP de origem) e, para
FTP, as contas em **Configuração → Contas FTP**. O painel mostra os comandos de cada
fabricante (Datacom DmOS via TFTP; Huawei VRP, Juniper Junos e Fiberhome via FTP). Cada
configuração recebida é validada, cifrada com a chave GPG e guardada como uma versão.
Nas **OLTs Fiberhome** cada OLT envia direto, do IP dela, e é um equipamento; o campo
**IP da UNM2000** libera a UNM2000, que depois apaga/renomeia o arquivo (esses comandos
respondem sucesso sem alterar nada — o resto continua só de gravação).
Detalhes em [docs/network-devices.md](docs/network-devices.md).

## MikroTik (coleta por SSH)

O MikroTik não envia: o serviço **puller** busca. Em **MikroTik → Usuário de acesso**
crie a credencial (usuário/senha/porta; a senha fica cifrada com a `FERNET_KEY`) e
cole os comandos mostrados em cada MikroTik — um usuário do grupo `ssh,read,sensitive`,
preso ao IP do servidor. Em **MikroTik → Hosts** cadastre um a um ou importe uma lista
(`IP[:porta] [nome]` por linha). A cada intervalo o puller roda `/export show-sensitive`
(`/export` no RouterOS 6), valida, cifra e guarda; a chave SSH do equipamento é fixada
na primeira coleta. Passo a passo e restauração em **Ajuda → MikroTik** e em
[docs/network-devices.md](docs/network-devices.md#mikrotik-coleta-por-ssh).

## Validação dos backups

Cada parte do backup é conferida pelo worker:

1. **Na chegada**: tamanho e SHA-256 do arquivo cifrado iguais aos calculados no
   cliente (detecta transferência corrompida); manifesto validado (sem path traversal,
   cliente certo, sem duplicata).
2. **Destinatário GPG**: o arquivo foi cifrado para a chave do servidor (detecta
   cliente com chave errada — backup que ninguém conseguiria restaurar).
3. **Verificação profunda** (com a chave privada no worker): decifra em streaming,
   sem gravar nada em disco, e testa:
   pastas → gzip íntegro e tar legível até o fim (conta entradas);
   MySQL/PostgreSQL → marcador de fim de dump presente (dump truncado é reprovado);
   SQL Server → cabeçalho MTF do `.bak`; arquivos enviados como estão → gzip íntegro até o fim;
   e o SHA-256 do conteúdo decifrado bate com o do cliente.
4. **Reverificação periódica** (`REVERIFY_INTERVAL_DAYS`, padrão 30): detecta
   corrupção silenciosa no disco do servidor.

Sem a chave privada no worker, os passos 1, 2 e 4 continuam (modo "integridade").

## Painel

Execuções por dia (sucesso / aviso / falha), volume recebido, disco usado × livre,
crescimento do armazenamento, clientes que mais ocupam espaço, status de verificação,
clientes atrasados (sem backup dentro do intervalo esperado) e problemas recentes.
**Contas cPanel** lista cada conta com a cópia mais recente e o histórico de versões, e a
lista de **Backups** tem busca por conta, pasta ou banco.

O menu **Ajuda** traz o passo a passo, já com os dados do seu servidor, de: baixar e decifrar,
servidor Linux, cPanel/WHM, Juniper (Junos), Datacom (DmOS) e UNM2000 (Fiberhome).

Papéis: **admin** (tudo, inclusive usuários, auditoria, baixar e excluir backups),
**operador** (clientes, reverificação), **auditor** (leitura).

## Restauração

No painel (admin), **Backups → detalhe → Baixar** pede a chave privada e a senha e **decifra no
navegador** (a chave não é enviada ao servidor) — serve para arquivos pequenos/médios, como a
configuração de um equipamento. `.gpg` baixa o arquivo ainda cifrado. Para pastas e dumps
grandes use o `gpg` no terminal. Ver [docs/restore.md](docs/restore.md) — resumo:

```bash
gpg --import backup-key.sec.asc
gpg -d 01-files-etc.tar.gz.gpg | tar -xz -C /restore
gpg -d 03-mysql-loja.sql.gz.gpg | gunzip | mysql
gpg -d 05-postgresql-erp.sql.gz.gpg | gunzip | sudo -u postgres psql
```

## Testes

```bash
make test-backend   # pytest + ruff (inclui ingestão e verificação com gpg real)
make test-e2e       # stack isolada + cliente Debian com MariaDB/PostgreSQL de verdade
make lint-agent     # shellcheck do agente
```

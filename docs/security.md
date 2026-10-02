# Modelo de segurança

## Ameaças consideradas

| Cenário | Proteção |
|---|---|
| Servidor cliente invadido | O cliente só tem a chave **pública** GPG: não decifra backups (nem os próprios). A chave SSH dele só **escreve** na própria pasta (`rrsync -wo -no-del`): não lê, não lista, não apaga backups já enviados, não abre shell nem túnel. |
| Servidor de backup invadido | Os arquivos guardados estão cifrados. A chave privada fica só no container `worker` (tmpfs, uid sem privilégio). Para um servidor "cego", não monte a chave privada: o sistema roda em modo integridade. |
| Disco do servidor de backup roubado | Só arquivos `.gpg`. A senha da chave privada fica em `secrets/private/` — guarde o original fora do servidor. |
| Interceptação na rede | SSH (KEX/cifras modernas), host key fixada no `known_hosts` do cliente (`StrictHostKeyChecking=yes`), e o conteúdo já vai cifrado. |
| Corrupção (transferência ou disco) | SHA-256 por arquivo conferido na chegada e na reverificação periódica; MDC do GPG; teste do conteúdo decifrado. |
| Backup "verde" que não restaura | Verificação profunda: tar lido até o fim, dump com marcador final, destinatário GPG correto. |
| Acesso indevido ao painel | Login com Argon2id, bloqueio progressivo após 5 erros, rate-limit, 2FA TOTP com códigos de recuperação, cookies `HttpOnly`/`SameSite=Strict`/`Secure`, CSRF double-submit, refresh token com rotação e detecção de reuso, papéis, trilha de auditoria (inclusive downloads). |

## Dados em claro no cliente

Pastas e dumps saem do `tar`/`mysqldump`/`pg_dump` direto para o `gpg` por pipe —
nada em claro é gravado no disco do cliente. A exceção é o **SQL Server**, que só sabe
gravar o `.bak` em disco: ele é verificado (`RESTORE VERIFYONLY`), cifrado e apagado em
seguida, em `MSSQL_BACKUP_DIR` (modo 700).

## A chave privada é o ponto único de recuperação

- `make keys` gera `secrets/backup-key.pub.asc` (pública) e
  `secrets/private/backup-key.sec.asc` + `backup-key.pass` (privada e senha).
- **Copie a privada e a senha para dois lugares fora do servidor** (cofre de senhas +
  mídia offline). Teste a restauração de um backup com essa cópia.
- A chave é RSA 4096 gerada em modo `--rfc4880` (sem AEAD): qualquer gpg (1.4, 2.2, 2.4)
  decifra, inclusive numa máquina de emergência antiga.
- Não existe "trocar a chave" sem planejamento: backups antigos continuam exigindo a
  chave antiga. Para trocar, gere uma nova em outro diretório, atualize os clientes
  (`GPG_FINGERPRINT` + `.asc`) e mantenha a antiga guardada até a retenção expirar.

## Exposição de rede

| Porta | Quem escuta | Exposição |
|---|---|---|
| 443 / 80 | proxy Caddy (rede do host) | pública — HTTPS com Let's Encrypt; 80 só redireciona |
| 2222 | sshd (rede do host) | **só os IPs dos clientes** (ufw) |
| 8080 | frontend | `127.0.0.1` apenas |
| 8000 / 5432 | backend / PostgreSQL | sem porta no host (redes internas do Compose) |

Proxy e sshd usam `network_mode: host` de propósito: portas publicadas com `ports:`
entram por regras de iptables do Docker avaliadas antes do ufw. Não troque isso por
`ports:` sem também filtrar a chain `DOCKER-USER`.

O Caddy descarta o `X-Forwarded-For` que vem da internet e grava o IP real do
cliente, que é o que aparece na auditoria e no rate-limit do login. `/api/docs` e
`/api/openapi.json` respondem 404 na borda.

## Endurecimento recomendado do host

- `scripts/ufw-setup.sh` para as regras; verifique de fora com `nmap`.
- `BACKUP_STORAGE_PATH` num disco dedicado; monitore o espaço (o painel alerta < 10% livre).
- Atualize as imagens periodicamente (`docker compose build --pull`).
- Para uma cópia fora do site, replique `BACKUP_STORAGE_PATH` (já cifrado) para outro
  local — os arquivos podem ir para storage não confiável.

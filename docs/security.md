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
| Acesso indevido ao painel | Login com Argon2id, bloqueio progressivo após 5 erros (senha **ou código 2FA**: os dois contam), rate-limit, 2FA TOTP com códigos de recuperação **obrigatório para administrador e operador** (`MFA_REQUIRED_ROLES`; sem 2FA a conta só consegue ativá-lo), opção "lembrar este dispositivo" que dispensa **só o código** por `TRUSTED_DEVICE_DAYS` (30; 0 desliga) — token aleatório em cookie `HttpOnly` restrito a `/api/auth`, só o SHA-256 no banco, preso à conta, revogado ao trocar/redefinir a senha, desativar/redefinir o 2FA, desativar a conta ou em "Esquecer todos" —, toda falha de login auditada, cookies `HttpOnly`/`SameSite=Strict`/`Secure`, CSRF double-submit, refresh token com rotação e detecção de reuso, papéis, trilha de auditoria (inclusive downloads). |

## Envio por HTTPS (cliente Windows)

- `/api/agent/v1` fica no mesmo endereço público do painel (443). Autenticação por token
  próprio do computador (`Authorization: Bearer pbu_…`, 256 bits); no banco só fica o
  SHA-256. O token aparece uma vez no painel, pode ser trocado ou revogado na hora e não
  vale para o painel (nem o cookie do painel vale para a API de envio).
- **Só grava**, como o `rrsync -wo`: cria execução, acrescenta bytes a arquivos `*.gpg`
  numa execução aberta e a fecha com o manifesto. Não lista, não lê conteúdo, não apaga,
  não renomeia; execução fechada não aceita mais nada. Nomes passam por `safe_child`.
- Limites: pedaços de até 32 MiB, no máximo 5 execuções abertas por cliente, recusa com
  menos de 2 GiB livres no disco; execução sem manifesto vai para a quarentena após
  `INCOMING_STALE_HOURS` (como no rsync).
- O conteúdo chega **já cifrado** no Windows com a chave pública fixada pelo usuário na
  conexão (conferindo a impressão digital). Se o servidor passar a anunciar outra chave, o
  cliente para em vez de cifrar para ela. No Windows, o token fica protegido por DPAPI.

## Downloads

A página Downloads exige login. O "link para o servidor" é um HMAC (JWT_SECRET) do nome
do arquivo + validade de 1 hora: baixa só aquele arquivo, sem login, até expirar (gerar e
usar ficam na auditoria). Só administradores enviam arquivos, com nome e extensão restritos
(`.exe/.msi/.zip/.tar.gz`, nada servido como página) e até 512 MB; o agente Linux é gerado
da pasta `agent/` do servidor (só-leitura), nunca de um envio.

## Equipamentos de rede (FTP/TFTP)

FTP e TFTP não têm criptografia: a configuração e a senha FTP trafegam em claro. O
sistema compensa no que controla — só IPs cadastrados, receptores só de gravação,
sessões isoladas, cifragem GPG imediata na chegada e remoção do original —, mas o
trecho de rede entre equipamento e servidor deve ser a rede de gerência ou uma VPN.

O servidor de firmwares (página FTP Firmwares) é a única leitura dos receptores: serve só
`STORAGE_PATH/firmware/files` (imagens enviadas pelo administrador, nunca backups), só para
as redes liberadas na página, e o FTP só com o login de firmware, sem gravar nem apagar.

## MikroTik (coleta por SSH)

- A coleta roda no serviço **puller**, separado do worker: ele precisa de saída para a
  rede (rede `egress`) e o worker, que tem a chave privada, continua sem saída. O puller
  só tem a chave **pública** — cifra o `/export` na memória (stdin do gpg) e grava só o
  `.gpg`; não consegue decifrar nada.
- A senha das credenciais precisa ser usada, então é guardada **cifrada** (Fernet,
  `FERNET_KEY`), não como hash. Ela nunca volta pela API. Trocar a `FERNET_KEY` invalida
  essas senhas (o painel avisa; salve-as de novo).
- O usuário criado no RouterOS é do grupo `ssh,read,sensitive` e preso ao IP do
  servidor (`address=`): não consegue alterar o equipamento.
- A chave de host SSH é fixada na primeira coleta bem-sucedida (TOFU). Se mudar, a
  conexão é encerrada **antes** de enviar a senha, e só um operador aceita a nova chave
  (fica na auditoria).

## Decifrar pelo painel

O botão **Baixar** do detalhe do backup decifra **no navegador** (OpenPGP.js): o servidor só entrega
o `.gpg`; a chave privada e a senha são digitadas na hora, ficam só na memória da página e somem ao
fechar a janela. O backend continua sem nunca receber a chave privada. Cada download aparece na
auditoria. Só administradores baixam.

## Dados em claro no cliente

Pastas e dumps saem do `tar`/`mysqldump`/`pg_dump` direto para o `gpg` por pipe —
nada em claro é gravado no disco do cliente. Arquivos enviados como estão (`BACKUP_FILES`, ex.
cPanel) são lidos e cifrados na hora; o agente só apaga a cópia **cifrada** que criou no `WORK_DIR`
e nunca altera os originais. A exceção é o **SQL Server**, que só sabe
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
| 443 / 80 | proxy Caddy (rede do host) | pública — HTTPS com Let's Encrypt; 80 só redireciona. Inclui o envio do cliente Windows (`/api/agent/v1`, token por computador) |
| 2222 | sshd (rede do host) | **só os IPs dos clientes** (ufw) |
| 21 + 30000-30049 | receptor FTP (rede do host) | **só os IPs dos equipamentos FTP** (ufw) |
| 69/udp | receptor TFTP (rede do host) | **só os IPs dos equipamentos TFTP** (ufw) |
| 8080 | frontend | `127.0.0.1` apenas |
| 8000 / 5432 | backend / PostgreSQL | sem porta no host (redes internas do Compose) |
| — | puller | nenhuma porta: só conexões de saída (SSH até os MikroTik) |

Proxy, sshd e os receptores FTP/TFTP usam `network_mode: host` de propósito: portas publicadas com `ports:`
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

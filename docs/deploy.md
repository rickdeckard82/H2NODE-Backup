# Deploy em produção (servidor com IP público)

```
 internet ──443/80──▶ proxy (Caddy, rede do host) ──▶ 127.0.0.1:8080 frontend ──▶ backend ──▶ db
 clientes ──2222────▶ sshd (rede do host)  ──▶ /data/incoming/<cliente>
                       ▲ ufw filtra as duas portas (só os IPs dos clientes na 2222)
```

## 1. Pré-requisitos

- DNS: registro **A** (e AAAA, se houver IPv6) de `PUBLIC_DOMAIN` apontando para o IP público.
- Docker + Docker Compose, `openssl`, `gnupg`.
- Disco dedicado para os backups (ex. `/srv/pulse-backup`).

## 2. Configuração

```bash
git clone … pulse-backup && cd pulse-backup
make init                      # .env com segredos + chave GPG em secrets/
vim .env
```

No `.env`:

| Variável | Valor |
|---|---|
| `PUBLIC_DOMAIN` | `backup.suaempresa.com.br` |
| `ACME_EMAIL` | e-mail para avisos do Let's Encrypt |
| `BACKUP_STORAGE_PATH` | `/srv/pulse-backup/data` |
| `SSH_PUBLIC_PORT` | `2222` (porta que os clientes usam) |
| `COOKIE_SECURE` | `true` |

`FRONTEND_ORIGIN` e `SSH_PUBLIC_HOST` podem ficar vazios — viram `https://PUBLIC_DOMAIN` e `PUBLIC_DOMAIN`.

**Copie `secrets/private/*` para um cofre fora do servidor agora.**

## 3. Firewall (ufw)

O ufw libera só o necessário: **443** (e 80) para todos, e a porta de backup
**só para os IPs dos clientes**:

```bash
sudo ./scripts/ufw-setup.sh web                    # 443 + 80
sudo ./scripts/ufw-setup.sh client 203.0.113.10    # um por servidor cliente
sudo ./scripts/ufw-setup.sh client 198.51.100.0/28 # aceita faixa também
sudo ./scripts/ufw-setup.sh status
```

O script não habilita o ufw nem mexe na porta 22 de administração (garanta a sua
regra de acesso antes de `ufw enable`).

> **Por que `network_mode: host` no proxy e no sshd?** Porta publicada com
> `ports:` no Docker é aberta por regras próprias de iptables (chain `DOCKER`),
> avaliadas **antes** do ufw — o ufw não a bloquearia. Na rede do host, as portas
> 80/443/2222 passam pelo INPUT normal e obedecem ao ufw. Os demais serviços
> (painel, API, banco) não publicam nada público: o frontend escuta só em
> `127.0.0.1:8080` e o banco fica na rede interna do Compose.
>
> Confira de fora do servidor: `nmap -Pn -p 22,80,443,2222,5432,8000,8080 <IP>` deve
> mostrar só 443/80 (e 2222 apenas a partir dos IPs liberados).

## 4. Subir

```bash
make build && make up
docker compose logs -f proxy     # acompanhe a emissão do certificado
```

O Caddy emite o certificado na primeira subida e renova sozinho. A emissão usa o
desafio **TLS-ALPN-01** pela 443 (basta ela liberada) ou **HTTP-01** pela 80. Os
certificados ficam no volume `caddy_data` — não apague (o Let's Encrypt limita
emissões repetidas).

Painel: `https://PUBLIC_DOMAIN` (usuário `admin`, senha mostrada pelo `make init`).

## 5. Atualização

```bash
git pull && docker compose build --pull && docker compose up -d
```
As migrações rodam na subida do backend. O agente nos clientes é atualizado
reexecutando `agent/install.sh` (mantém o `agent.conf`).

## Backup do próprio painel

O PostgreSQL guarda só metadados (cadastro, histórico); os backups em si estão no
disco. Ainda assim, faça dump periódico:
```bash
docker compose exec -T db pg_dump -U pulse pulse_backup | gzip > painel-$(date +%F).sql.gz
```

## Usando outro proxy (Nginx Proxy Manager etc.)

Desligue o Caddy (`docker compose up -d --scale proxy=0` ou remova o serviço) e
aponte o seu proxy para `http://127.0.0.1:8080`, repassando `X-Forwarded-For` com o
IP real (`proxy_set_header X-Forwarded-For $remote_addr;`) e
`X-Forwarded-Proto https`, com `proxy_buffering off` e timeout longo para downloads.

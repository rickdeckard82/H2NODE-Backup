# Backup de switches e roteadores (FTP / TFTP)

Os equipamentos **enviam** a configuração para o servidor; o Pulse Backup recebe,
valida, **cifra com a chave GPG** e guarda como uma versão do equipamento (com
retenção, verificação e alertas iguais aos dos servidores Linux).

```
 switch/roteador ──FTP 21 (+ passivo 30000-30049)──▶ receptor ftp ─┐
                 ──TFTP 69/udp─────────────────────▶ receptor tftp ─┤ netin/<equipamento>/
                                                                     ▼
                                     worker: valida → cifra (GPG) → apaga o original → store/
```

## Cadastro

1. **Configuração → Contas FTP** (só para FTP): crie as contas que os equipamentos
   usam, ex. `huawei` e `juniper`. Uma conta pode servir a vários equipamentos.
   Senha de 8 a 64 caracteres, sem espaço, `@`, `:` ou `/`.
2. **Equipamentos de rede → Novo equipamento**: nome, fabricante, protocolo e o
   **IP de origem** — o IP com que o equipamento chega ao servidor. É ele que
   identifica de quem é o arquivo (cada IP pertence a um único equipamento).
3. **Comandos**: o painel mostra o que colar no equipamento.
4. Libere o IP no firewall: `sudo ./scripts/ufw-setup.sh device <IP> ftp|tftp`.

Intervalo esperado **0 = sob demanda**: Huawei (`save-configuration`) e Juniper
(`transfer-on-commit`) só enviam quando a configuração muda, então não há alerta
de atraso. Para equipamentos agendados, informe o intervalo em horas.

## Comandos por fabricante

`<servidor>` é o `NET_PUBLIC_HOST` do `.env` (use o **IP**, Huawei e Datacom não
aceitam nome).

**Datacom DmOS — TFTP** (envia sob comando; agende na sua automação):
```
show running-config | save overwrite config.txt
copy file config.txt tftp://<servidor>/<identificador>/ source <IP-de-origem>
```

**Huawei VRP — FTP** (envia a cada salvamento):
```
system-view
set save-configuration delay 1
set save-configuration backup-to-server server <servidor> transport-type ftp user huawei password <senha> path ./<IP-de-origem>
```

**Juniper Junos — FTP** (envia um `.conf.gz` a cada commit):
```
set system archival configuration transfer-on-commit
set system archival configuration archive-sites "ftp://juniper:<senha>@<servidor>"
commit
```

## Validação

| Fabricante | Na recepção e na verificação profunda |
|---|---|
| Huawei | texto (ou `.zip` com o `.cfg`) terminando em `return` |
| Juniper | `.gz` íntegro, bloco `system`, chaves `{ }` balanceadas |
| Datacom | texto com comandos de primeiro nível do DmOS (`hostname`, `dot1q`, `interface`…) |
| Genérico | texto não vazio com 3+ linhas |

Arquivo vazio, truncado ou binário vira backup **com falha** (aparece no painel).
Configuração idêntica à anterior é marcada como "idêntica ao backup anterior".

## Segurança

- **FTP e TFTP trafegam em claro**, inclusive a senha FTP. Use a rede de gerência
  ou VPN entre equipamentos e servidor, e libere as portas no ufw **só** para os
  IPs dos equipamentos.
- Os receptores só aceitam **gravação**: TFTP recusa leitura (RRQ); a conta FTP não
  tem RETR, DELE nem APPE, e cada sessão grava numa pasta própria, vazia.
- Conexões de IPs não cadastrados são recusadas antes do login.
- O arquivo em claro fica no disco só até o worker cifrá-lo (segundos) e é apagado.
- Os receptores não acessam o banco: leem `receivers.json` (IPs + hash Argon2id
  das contas), gerado pelo painel, e rodam como uid sem privilégio depois de abrir
  as portas.

## Portas (`.env`)

| Variável | Padrão | |
|---|---|---|
| `FTP_PORT` | 21 | controle FTP |
| `FTP_PASSIVE_PORTS` | 30000-30049 | dados no modo passivo (Junos/curl usam) |
| `FTP_MASQUERADE_ADDRESS` | — | IP anunciado no PASV se houver NAT |
| `TFTP_PORT` | 69/udp | |
| `NET_PUBLIC_HOST` | `SSH_PUBLIC_HOST` | endereço nos comandos de exemplo |
| `NET_MAX_FILE_MB` | 64 | tamanho máximo de um arquivo recebido |

## Problemas comuns

- **"IP não autorizado" / conexão fechada**: o IP de origem não bate com o
  cadastrado (NAT no caminho? `source` diferente no DmOS?). Veja
  `docker compose logs ftp tftp`.
- **Junos não envia**: confira `show log messages | match archiv` no roteador e a
  faixa passiva liberada no ufw.
- **TFTP para no meio**: firewall no caminho bloqueando as portas efêmeras de
  resposta (o ufw do servidor já trata via conntrack).

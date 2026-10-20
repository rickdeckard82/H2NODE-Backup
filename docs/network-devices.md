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

> MikroTik é o contrário: o servidor **busca** a configuração por SSH. Veja
> [MikroTik (coleta por SSH)](#mikrotik-coleta-por-ssh) no fim desta página.

## Cadastro

1. **Configuração → Contas FTP** (só para FTP): crie as contas que os equipamentos
   usam, ex. `huawei` e `juniper`. Uma conta pode servir a vários equipamentos.
   Senha de 8 a 64 caracteres, sem espaço, `@`, `:` ou `/`.
2. **FTP/TFTP → Novo cadastro**: nome, tipo (fabricante), protocolo e o
   **IP de origem** — o IP com que o equipamento chega ao servidor. É ele que
   identifica de quem é o arquivo. O mesmo IP pode ter mais de um cadastro:
   - **FTP**: cada cadastro do IP precisa da sua **Conta FTP** (campo do cadastro) — o
     login diz de quem é o arquivo; com um cadastro só, "Qualquer conta" basta;
   - **TFTP** (sem login): um cadastro TFTP por IP;
   - **SSH** (MikroTik): o coletor é quem conecta, não disputa o IP.
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

**Fiberhome (OLTs e UNM2000) — FTP.** A UNM2000 comanda a exportação, mas **cada OLT envia
direto ao servidor, do IP dela**, um arquivo `<ID>_<MMDD>` por dia (texto, `!WOS system config file`):

1. Contas FTP: a mesma conta que a UNM2000 usa (ex. `fiberhome`).
2. **Um equipamento por OLT**: fabricante *Fiberhome (OLT / UNM2000)*, FTP, IP de origem = IP da OLT.
3. Em cada OLT, o campo **IP da UNM2000 (gerenciador)**: depois que a OLT envia, a UNM2000 entra
   no FTP para apagar o arquivo antigo e **renomear** o novo. O servidor responde sucesso a
   `DELE`/`RNFR`/`RNTO` desse IP **sem alterar nada** (o arquivo já foi guardado e cifrado); sem isso
   a UNM2000 acusa "XFTP server connection failed" e repete a tarefa. O IP da UNM2000 **não** é
   cadastrado como equipamento. Se outro servidor sai pelo mesmo IP (ex.: NAT), ele pode ter um
   cadastro FTP nesse IP **com Conta FTP presa** (diferente da usada pela UNM2000): o login com
   essa conta vai para o cadastro; qualquer outra conta é tratada como a UNM2000.
4. Libere os IPs no ufw (`ufw-setup.sh device <IP> ftp`; pode ser a faixa das OLTs) e aponte o
   cadastro de FTP de backup da UNM2000 para este servidor (porta 21, modo passivo).
5. Intervalo esperado: o da tarefa de exportação (ex. 24 h).

O cadastro de FTP **de firmware** da UNM2000 (as OLTs *baixam* o arquivo) não deve apontar para
cá: o receptor é só de gravação.

## Validação

| Fabricante | Na recepção e na verificação profunda |
|---|---|
| Huawei | texto (ou `.zip` com o `.cfg`) terminando em `return` |
| Juniper | `.gz` íntegro, bloco `system`, chaves `{ }` balanceadas |
| Datacom | texto com comandos de primeiro nível do DmOS (`hostname`, `dot1q`, `interface`…) |
| Fiberhome (OLT / UNM2000) | texto da OLT com `!WOS system config file` ou `hostname`; cada OLT envia o próprio arquivo (`<ID>_<MMDD>`) e é um equipamento (IP de origem = IP da OLT); o **IP da UNM2000** é informado em cada OLT (campo "IP da UNM2000") |
| Genérico | texto não vazio com 3+ linhas |

Arquivo vazio, truncado ou binário vira backup **com falha** (aparece no painel).
Configuração idêntica à anterior é marcada como "idêntica ao backup anterior".

## Arquivos e bancos (FTP)

Tipo **Arquivos e bancos (FTP)**: um servidor ou serviço que não usa o agente envia
dumps e arquivos por FTP (ex.: `curl --netrc -T erp.sql ftp://<servidor>/` no cron).
Cada **conexão FTP** vira uma execução, com uma parte por arquivo: os arquivos ficam na
pasta da sessão até a desconexão e vão juntos para a fila (se o cliente envia como `.part` e
renomeia, vale o nome final). Cada parte é testada **pela extensão** e cifrada direto do
disco, em streaming (`services/filecheck.py`); a execução fica com o pior resultado:

| Arquivo | Teste na recepção |
|---|---|
| `.sql`, `.sql.gz` | dump do mysqldump/mariadb-dump ou pg_dump com o marcador de fim (componente MySQL/PostgreSQL; a verificação profunda confere o marcador de novo). SQL sem o cabeçalho dessas ferramentas: **aviso** |
| `.zip` | CRC de todos os arquivos de dentro (zip com senha: aviso) |
| `.tar.gz`, `.tgz`, `.gz` | gzip íntegro até o fim; tar legível |
| `.pdf` | `%PDF` no início e `%%EOF` no fim |
| `.conf`, `.txt`, `.csv`, `.cfg`, `.ini`, `.json`… | texto, sem bytes binários |
| outros | só guardados |

A verificação profunda confere o SHA-256 do conteúdo decifrado contra o da recepção.
Limite por arquivo: `NET_FILES_MAX_MB` (o arquivo fica em claro no disco só até o worker
cifrá-lo). Passo a passo com script de exemplo em **Ajuda → Arquivos e bancos (FTP)**.

## Segurança

- **FTP e TFTP trafegam em claro**, inclusive a senha FTP. Use a rede de gerência
  ou VPN entre equipamentos e servidor, e libere as portas no ufw **só** para os
  IPs dos equipamentos.
- Exceção controlada: para o **IP da UNM2000** informado nas OLTs Fiberhome, os comandos FTP `DELE`, `RNFR` e `RNTO`
  respondem sucesso **sem fazer nada** (a UNM2000 apaga/renomeia o arquivo que a OLT enviou e o servidor já o guardou).
  Para qualquer outro equipamento continuam recusados, e nenhum backup guardado pode ser lido, alterado ou apagado.
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
| `NET_MAX_FILE_MB` | 64 | tamanho máximo de um arquivo de configuração recebido |
| `NET_FILES_MAX_MB` | 4096 | tamanho máximo de um arquivo do tipo "Arquivos e bancos" |

## Problemas comuns

- **"IP não autorizado" / conexão fechada**: o IP de origem não bate com o
  cadastrado (NAT no caminho? `source` diferente no DmOS?). Veja
  `docker compose logs ftp tftp`.
- **UNM2000 acusa "XFTP server connection failed" / repete a tarefa**: o IP dela não está no campo
  "IP da UNM2000" das OLTs (`ftp_unknown_ip` no log). Procure `ftp_manager_noop` para confirmar.
- **Junos não envia**: confira `show log messages | match archiv` no roteador e a
  faixa passiva liberada no ufw.
- **TFTP para no meio**: firewall no caminho bloqueando as portas efêmeras de
  resposta (o ufw do servidor já trata via conntrack).

## MikroTik (coleta por SSH)

```
 puller ──SSH (porta da credencial)──▶ MikroTik: /export show-sensitive
   │  valida → cifra na memória (chave pública) → store/<equipamento>/<execução>/
   ▼
 worker: decifra em streaming e revalida (verificação profunda)
```

1. **MikroTik → Usuário de acesso** (admin): crie a credencial — nome, usuário, senha
   (8–64, sem espaço, aspas, `\`, `$` ou `?`) e porta SSH padrão.
2. Em cada MikroTik, crie o usuário (o painel mostra os comandos com a senha logo após salvar):

   ```
   /user group add name=pulse-backup policy=ssh,read,sensitive comment="Pulse Backup: somente leitura"
   /user add name=pulse-backup group=pulse-backup password="<SENHA>" address=<IP-DO-SERVIDOR>/32 comment="Pulse Backup"
   ```

   Libere o SSH para o servidor em `/ip service` (campo `address`) e no firewall `input`.
   No servidor não há porta para abrir.
3. **MikroTik → Hosts**: cadastre (IP, porta opcional, credencial, intervalo de coleta)
   ou use **Importar lista** — uma linha por host, `IP[:porta] [nome]`.

Detalhes:

- O intervalo de coleta (mín. 1 h) é também o prazo do alerta de atraso. **Coletar
  agora** agenda para o próximo ciclo do puller (`WORKER_POLL_SECONDS`).
- RouterOS 6 não conhece `show-sensitive`: o puller repete com `/export`, que no 6 já
  inclui os dados sensíveis.
- "Idêntica ao backup anterior" ignora a linha de data do cabeçalho do `/export`.
- Falha de conexão/autenticação vira uma execução **falhou** (sem arquivo) e a mensagem
  aparece na lista de hosts. A próxima tentativa é no intervalo seguinte.
- A chave de host é fixada na 1ª coleta; trocou o IP/porta, ela é fixada de novo. Se
  mudar sem motivo, investigue antes de clicar em **Aceitar nova chave**.
- `.env`: `PULL_CONCURRENCY` (coletas simultâneas, padrão 4) e `PULL_TIMEOUT_SECONDS`
  (segundos sem resposta, padrão 60). Logs: `docker compose logs -f puller`.

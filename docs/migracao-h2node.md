# Migração: Pulse Backup → H2NODE Backup

O projeto mudou de nome na versão **0.9.26** do painel (agente Linux **1.5.0**, cliente
Windows **0.3.0**). Nada para de funcionar no dia da atualização: o servidor continua
aceitando os agentes e clientes Windows antigos, e cada parte pode ser atualizada no seu
tempo. A ordem abaixo é a recomendada.

## 1. Servidor

Na pasta do repositório (ex.: `/app/pulse-backup` — a pasta pode manter o nome antigo):

```bash
git pull
sudo ./scripts/migrar-h2node.sh      # mostra o plano e pede confirmação
```

O script:

- acrescenta `VOLUME_PREFIX=pulse-backup` ao `.env` (os volumes passaram a ter nome fixo,
  `${VOLUME_PREFIX}_db_data` etc.), mantendo **o mesmo banco, as mesmas chaves de host SSH**
  (os agentes continuam confiando no servidor) e **os mesmos certificados** do Caddy;
- fixa `POSTGRES_USER=pulse` e `POSTGRES_DB=pulse_backup` no `.env` se não estiverem lá
  (os padrões mudaram para `h2node`/`h2node_backup`);
- derruba os containers do projeto compose antigo (`docker compose -p pulse-backup down`,
  **sem** `-v`) e sobe o projeto `h2node-backup`.

O `.env` original fica copiado em `.env.antes-h2node.<data>`. O `docker compose` pode
avisar que os volumes foram criados por outro projeto: é esperado.

> Quem monta o volume `pulse-backup_caddy_data` em outro serviço (ex.: um serviço do
> example.com) não precisa mudar nada: com `VOLUME_PREFIX=pulse-backup` o nome continua o mesmo.

As regras do ufw criadas com o comentário `pulse-backup` continuam valendo; o
`scripts/ufw-docker.sh` reconhece o bloco antigo (`PULSE-BACKUP`) no `after.rules`.

## 2. Zabbix

O template passou a ser **H2NODE Backup by HTTP** (macros `{$H2NODE.*}`, chaves
`h2node.backup.*`). Os UUIDs são os mesmos, então importar o arquivo novo **atualiza** o
template existente e mantém o histórico dos itens.

1. Baixe `h2node_backup_zabbix7.yaml` em Configuração → Zabbix e importe
   (Coleta de dados → Templates → Importar, marcando "Atualizar existentes").
2. No host, renomeie as macros: `{$PULSE.URL}` → `{$H2NODE.URL}`,
   `{$PULSE.TOKEN}` → `{$H2NODE.TOKEN}` (e qualquer outra `{$PULSE.*}` que você tenha
   sobrescrito, como `{$PULSE.CLIENT.ALERT:"…"}`).

Sem o passo 2 os itens ficam sem dados e o alerta de "sem dados" dispara.

## 3. Servidores Linux (agente)

Os agentes antigos continuam enviando normalmente. Para atualizar, baixe o agente novo em
Downloads e rode o `install.sh` como antes:

```bash
tar xzf h2node-backup-agent-1.5.0.tar.gz && cd h2node-backup-agent-1.5.0
./install.sh                     # o horário do crontab atual é mantido
h2node-backup-agent test
```

O `install.sh` 1.5.0:

- move `/etc/pulse-backup` para `/etc/h2node-backup` (chave SSH, known_hosts, agent.conf,
  senhas de banco) e deixa um link no lugar antigo;
- ajusta no `agent.conf` os caminhos de `/etc`, do log e do `WORK_DIR` padrão;
- move `/var/log/pulse-backup.log` para `/var/log/h2node-backup.log`;
- troca o caminho no crontab do root **mantendo o horário**;
- deixa `/usr/local/sbin/pulse-backup-agent` e `/usr/bin/pulse-backup-agent` como atalhos
  para o agente novo.

Se o agente 1.5.0 for copiado sem o `install.sh`, ele mesmo faz a migração da pasta
`/etc/pulse-backup` na primeira execução.

Não é preciso recadastrar a chave SSH no painel. Usuários de banco criados com outro nome
(ex.: `pulsebackup` no MySQL) continuam valendo: o nome está só no `mysql.cnf`.

## 4. Computadores Windows

Baixe `H2nodeBackup-Setup-0.3.0.exe` em Downloads e instale por cima. O instalador para e
remove o serviço `PulseBackup`, apaga os arquivos antigos de `Program Files\PulseBackup` e
renomeia `C:\ProgramData\PulseBackup` para `C:\ProgramData\H2nodeBackup`: o servidor, o
token, as pastas escolhidas, o agendamento e o histórico são aproveitados.

## O que continua com o nome antigo (de propósito)

- O formato `pulse-backup/1` do manifesto continua aceito pelo servidor (agentes e clientes
  Windows antigos). Os novos mandam `h2node-backup/1`.
- A identidade da chave GPG já gerada (`Pulse Backup <backup@…>`) não muda: trocar a chave
  obrigaria a reconfigurar todos os clientes. Chaves novas (`make keys`) já saem com o nome
  H2NODE.
- Registros antigos no banco (manifestos de equipamentos `pulse-backup/net-1`, auditoria)
  ficam como foram gravados.

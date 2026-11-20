# Integração com Zabbix

O Zabbix **consulta** o H2NODE Backup (pull) e alerta quando um backup falha, atrasa ou não passa
na verificação, quando o worker para, quando o disco enche, e quando o próprio painel deixa de responder.

## Por que pull

- **Detecta o painel fora do ar.** Se o H2NODE Backup cair, um alerta enviado *por ele* nunca sai;
  aqui o Zabbix percebe a falta de resposta (`nodata`).
- **Uma fonte de verdade.** A saúde vem da mesma função do painel (`services/health.py`): o que
  aparece vermelho no painel é o que alerta no Zabbix.
- **Descoberta automática (LLD).** Servidor ou equipamento cadastrado aparece sozinho no Zabbix;
  desativado ou excluído, some.
- **Sem segredo do Zabbix no H2NODE Backup** e sem porta nova: é HTTPS no mesmo endereço do painel.

## Endpoint

`GET /api/monitoring/status` com `Authorization: Bearer <token>`:

- só leitura; sem token configurado responde **404** (desligado);
- token gerado em **Configuração → Zabbix**, mostrado uma vez (o banco guarda o SHA-256);
  trocar invalida o anterior;
- opcional: redes liberadas (CIDR) — recomendado restringir ao IP do servidor/proxy Zabbix;
- 60 consultas/min por IP; cada consulta grava a hora e o IP (aparecem na página).

Resposta (resumo):

```json
{
  "version": "0.9.20",
  "generated_at": 1792750000,
  "worker": {"last_seen_age": 12, "deep_verify": 1,
             "busy_with": "verificando whm-cpanel/20261023T010002Z-beefbe", "busy_age": 5400},
  "disk": {"total": 4000000000000, "used": 1200000000000, "free": 2800000000000, "pused": 30.0},
  "summary": {"ok": 40, "warning": 1, "failed": 1, "overdue": 0, "never": 2},
  "clients": [
    {"slug": "sw-core", "name": "SW Core", "kind": "network", "vendor": "huawei",
     "health": "failed", "health_code": 2, "last_backup_at": "2026-10-23T03:00:00Z",
     "last_backup_age": 3600, "last_status": "failed", "verify_status": "failed", "verify_code": 2,
     "last_size": 10240, "expected_interval_hours": 24, "error": "conteúdo não parece configuração"}
  ]
}
```

| Campo | Códigos |
|---|---|
| `health_code` | 0 ok · 1 com avisos · 2 falhou (ou corrompido) · 3 atrasado · 4 nunca recebeu |
| `verify_code` | 0 ok · 1 pendente · 2 falhou · 3 sem verificação |
| `last_backup_age`, `worker.last_seen_age` | segundos; `-1` = nunca |
| `worker.busy_with`, `worker.busy_age` | tarefa atual e há quantos segundos; `""` e `-1` = ocioso |

O sinal do worker (`last_seen_age`) vem de uma thread a cada 30 s, também no meio de tarefas longas
(verificar um backup de centenas de GB leva horas). Sem sinal = processo morto ou travado; sinal em
dia com a mesma tarefa há muito tempo = worker preso (`busy_age`).

Os códigos são o contrato com os gatilhos do template: valores novos entram no fim, nunca reordene.
Clientes inativos não aparecem.

## Template

`frontend/public/zabbix/h2node_backup_zabbix7.yaml` (baixável na página **Configuração → Zabbix**),
Zabbix **7.0+**, nome **H2NODE Backup by HTTP**:

- 1 item HTTP agent (`h2node.backup.get`, a cada `{$H2NODE.INTERVAL}`) e todo o resto como itens
  dependentes — uma única requisição por ciclo, qualquer que seja o número de clientes;
- descoberta `h2node.backup.clients.discovery` com saúde, idade do último backup, verificação,
  tamanho e erro por cliente;
- gatilhos:

| Gatilho | Severidade |
|---|---|
| `{#NAME}: último backup falhou` (mostra o erro) | Alta |
| `{#NAME}: backup atrasado` (mostra há quanto tempo) | Alta |
| `{#NAME}: verificação do último backup falhou` | Alta |
| `{#NAME}: nenhum backup recebido ainda` | Atenção |
| `{#NAME}: último backup com avisos` | Atenção |
| Worker parado (sem sinal há `{$H2NODE.WORKER.MAX.AGE}` s) | Alta |
| Worker na mesma tarefa há mais de `{$H2NODE.WORKER.BUSY.MAX}` | Atenção |
| Disco acima de `{$H2NODE.DISK.PUSED.WARN}` / `{$H2NODE.DISK.PUSED.HIGH}` % | Atenção / Alta |
| Verificação profunda desativada | Atenção |
| Sem resposta da API há `{$H2NODE.NODATA}` | Alta |

Os alertas de cliente se resolvem sozinhos quando o próximo backup chega bem.

### Macros

| Macro | Padrão | |
|---|---|---|
| `{$H2NODE.URL}` | `https://backup.example.com` | endereço do painel, sem barra no fim |
| `{$H2NODE.TOKEN}` | — | token do painel (tipo **texto secreto**) |
| `{$H2NODE.INTERVAL}` | `2m` | intervalo da consulta |
| `{$H2NODE.NODATA}` | `15m` | sem resposta por este tempo = alerta |
| `{$H2NODE.WORKER.MAX.AGE}` | `300` | segundos sem sinal do worker (o sinal vem a cada 30 s) |
| `{$H2NODE.WORKER.BUSY.MAX}` | `12h` | tempo máximo na mesma tarefa |
| `{$H2NODE.DISK.PUSED.WARN}` / `.HIGH` | `85` / `95` | uso do disco dos backups (%) |
| `{$H2NODE.WARNING.ALERT}` | `1` | `0` = não alerta backups com avisos |
| `{$H2NODE.CLIENT.ALERT:"<slug>"}` | `1` | `0` silencia um cliente (macro de contexto) |

## Passo a passo

1. Painel → **Configuração → Zabbix** → **Gerar token** (copie; não aparece de novo). Em
   *Redes liberadas*, informe o IP do servidor ou proxy Zabbix.
2. Zabbix → **Coleta de dados → Templates → Importar** → `h2node_backup_zabbix7.yaml`.
3. **Coleta de dados → Hosts → Criar host**: `H2NODE Backup`, sem interface, template
   **H2NODE Backup by HTTP**; em *Macros*, `{$H2NODE.URL}` e `{$H2NODE.TOKEN}`.
4. Em até 2 min os clientes aparecem em **Monitoramento → Dados recentes**, e a página do painel
   mostra "consultou há …". Teste manual:

   ```bash
   curl -fsS -H "Authorization: Bearer <token>" https://backup.example.com/api/monitoring/status
   ```

## Problemas comuns

- **404**: nenhum token gerado (ou revogado).
- **401**: token errado — confira a macro (sem espaço) ou gere outro.
- **403 "IP não autorizado"**: o IP de saída do Zabbix não está nas redes liberadas (o painel
  mostra o IP da última tentativa bem-sucedida; atrás de NAT, use o IP público).
- **Itens "não suportado" com erro de JSONPath**: cliente recém-excluído — some na próxima descoberta.

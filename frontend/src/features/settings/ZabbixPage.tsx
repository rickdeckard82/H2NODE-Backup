import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useFmtDate } from "../../lib/datetime";
import { fmtAgo } from "../../lib/format";
import { CopyBlock } from "../clients/ClientsPage";

interface MonitoringSettings {
  configured: boolean;
  token_hint: string | null;
  allowed_networks: string[];
  last_used_at: string | null;
  last_used_ip: string | null;
  status_url: string;
}

const TEMPLATE_URL = "/zabbix/h2node_backup_zabbix7.yaml";

const ALERTS: [string, string, string][] = [
  ["Último backup falhou", "Alta", "execução com falha ou corrompida (mostra o erro)"],
  ["Backup atrasado", "Alta", "nada dentro do intervalo esperado + tolerância"],
  ["Verificação do último backup falhou", "Alta", "hash, decifragem ou teste do dump não conferiu"],
  ["Nenhum backup recebido ainda", "Atenção", "cliente ativo que nunca enviou"],
  ["Último backup com avisos", "Atenção", "desligável com {$H2NODE.WARNING.ALERT}=0"],
  ["Worker parado", "Alta", "sem sinal do worker há mais de {$H2NODE.WORKER.MAX.AGE} s (o sinal vem a cada 30 s)"],
  ["Worker na mesma tarefa há muito tempo", "Atenção", "vivo, mas preso numa tarefa há mais de {$H2NODE.WORKER.BUSY.MAX}"],
  ["Disco dos backups acima de 85% / 95%", "Atenção / Alta", "{$H2NODE.DISK.PUSED.WARN} e {$H2NODE.DISK.PUSED.HIGH}"],
  ["Verificação profunda desativada", "Atenção", "worker sem a chave privada GPG"],
  ["Sem resposta da API", "Alta", "painel fora do ar, token trocado ou IP do Zabbix bloqueado"],
];

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
        {n}
      </div>
      <div className="min-w-0 flex-1 space-y-2 text-sm">
        <div className="font-semibold">{title}</div>
        {children}
      </div>
    </div>
  );
}

export default function ZabbixPage() {
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [networks, setNetworks] = useState<string | null>(null);

  const q = useQuery({ queryKey: ["monitoring"], queryFn: () => api.get<MonitoringSettings>("/monitoring/settings") });
  const s = q.data;
  const origin = s ? s.status_url.replace(/\/api\/monitoring\/status$/, "") : "";
  const set = (data: MonitoringSettings) => qc.setQueryData(["monitoring"], data);
  const err = (e: unknown, fallback: string) => toast("err", e instanceof ApiError ? e.detail : fallback);

  const gen = useMutation({
    mutationFn: () => api.post<{ token: string; settings: MonitoringSettings }>("/monitoring/token"),
    onSuccess: (r) => {
      set(r.settings);
      setToken(r.token);
    },
    onError: (e) => err(e, "Erro ao gerar o token"),
  });

  const revoke = useMutation({
    mutationFn: () => api.del<MonitoringSettings>("/monitoring/token"),
    onSuccess: (r) => {
      set(r);
      toast("ok", "Token revogado: o Zabbix deixa de consultar");
    },
    onError: (e) => err(e, "Erro ao revogar"),
  });

  const saveNets = useMutation({
    mutationFn: (text: string) =>
      api.put<MonitoringSettings>("/monitoring/settings", { allowed_networks: text.split(/[\s,;]+/).filter(Boolean) }),
    onSuccess: (r) => {
      set(r);
      setNetworks(null);
      toast("ok", "Redes salvas");
    },
    onError: (e) => err(e, "Erro ao salvar"),
  });

  return (
    <div>
      <PageHeader
        title="Zabbix"
        subtitle="O Zabbix consulta o H2NODE Backup e alerta quando um backup falha, atrasa ou não passa na verificação"
      />

      {q.isLoading && <Spinner className="h-5 w-5 text-brand-600" />}
      {q.isError && (
        <Card className="mb-3 text-sm text-rose-600 dark:text-rose-400">
          {q.error instanceof ApiError ? q.error.detail : String(q.error)}
        </Card>
      )}

      {s && (
        <div className="grid gap-3 xl:grid-cols-2">
          <Card className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Acesso do Zabbix</span>
              {s.configured ? <Badge tone="green">token ativo</Badge> : <Badge tone="amber">sem token</Badge>}
              {s.configured &&
                (s.last_used_at ? (
                  <Badge tone="blue">consultou {fmtAgo(s.last_used_at)}</Badge>
                ) : (
                  <Badge>ainda não consultou</Badge>
                ))}
            </div>
            {s.configured ? (
              <p className="text-slate-500 dark:text-slate-400">
                Token terminado em <span className="font-mono">…{s.token_hint}</span>.
                {s.last_used_at && (
                  <>
                    {" "}
                    Última consulta em {fmtDate(s.last_used_at)} de <span className="font-mono">{s.last_used_ip ?? "?"}</span>.
                  </>
                )}
              </p>
            ) : (
              <p className="text-slate-500 dark:text-slate-400">
                Sem token, o endpoint de monitoramento fica desligado (responde 404). Gere um para o Zabbix.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                loading={gen.isPending}
                onClick={() => {
                  if (!s.configured || confirm("Gerar um token novo? O atual deixa de valer até você trocar a macro no Zabbix."))
                    gen.mutate();
                }}
              >
                {s.configured ? "Trocar token" : "Gerar token"}
              </Button>
              {s.configured && (
                <Button
                  variant="ghost"
                  className="text-rose-600 dark:text-rose-400"
                  loading={revoke.isPending}
                  onClick={() => {
                    if (confirm("Revogar o token? O Zabbix vai alertar \"sem resposta da API\".")) revoke.mutate();
                  }}
                >
                  Revogar
                </Button>
              )}
            </div>

            <div className="border-t border-slate-200 pt-3 dark:border-slate-800">
              <div className="mb-1 font-semibold">Redes liberadas</div>
              {networks === null ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-mono text-xs">
                    {s.allowed_networks.length ? s.allowed_networks.join(", ") : "qualquer IP (só o token protege)"}
                  </span>
                  <button
                    className="text-xs text-brand-600 hover:underline dark:text-brand-400"
                    onClick={() => setNetworks(s.allowed_networks.join("\n"))}
                  >
                    editar
                  </button>
                </div>
              ) : (
                <form
                  className="space-y-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    saveNets.mutate(networks);
                  }}
                >
                  <Field label="IP ou CIDR, um por linha" hint="Recomendado: só o IP do servidor (ou proxy) Zabbix. Vazio = qualquer IP.">
                    <textarea
                      className="input min-h-20 font-mono"
                      value={networks}
                      placeholder="198.51.100.10"
                      onChange={(e) => setNetworks(e.target.value)}
                      autoFocus
                    />
                  </Field>
                  <div className="flex justify-end gap-2">
                    <Button type="button" variant="ghost" onClick={() => setNetworks(null)}>
                      Cancelar
                    </Button>
                    <Button type="submit" loading={saveNets.isPending}>
                      Salvar
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </Card>

          <Card className="space-y-4">
            <div className="text-sm font-semibold">Configurar no Zabbix (7.0 ou mais novo)</div>
            <Step n={1} title="Importe o template">
              <p className="text-slate-500 dark:text-slate-400">
                Baixe{" "}
                <a className="text-brand-600 hover:underline dark:text-brand-400" href={TEMPLATE_URL} download>
                  h2node_backup_zabbix7.yaml
                </a>{" "}
                e importe em <b>Coleta de dados → Templates → Importar</b>.
              </p>
            </Step>
            <Step n={2} title="Crie o host">
              <p className="text-slate-500 dark:text-slate-400">
                Em <b>Coleta de dados → Hosts → Criar host</b>: nome <span className="font-mono">H2NODE Backup</span>, sem interface,
                template <b>H2NODE Backup by HTTP</b>.
              </p>
            </Step>
            <Step n={3} title="Preencha as macros do host">
              <CopyBlock label="Macros" text={`{$H2NODE.URL}   = ${origin}\n{$H2NODE.TOKEN} = <token gerado aqui> (tipo: texto secreto)`} />
              <p className="text-xs text-slate-400 dark:text-slate-500">
                Para silenciar um cliente: <span className="font-mono">{'{$H2NODE.CLIENT.ALERT:"slug-do-cliente"}'} = 0</span>.
              </p>
            </Step>
            <Step n={4} title="Confira">
              <p className="text-slate-500 dark:text-slate-400">
                Em até 2 min os clientes aparecem em <b>Dados recentes</b> e o selo acima muda para "consultou". Teste à mão:
              </p>
              <CopyBlock label="Comando" text={`curl -fsS -H "Authorization: Bearer <token>" ${s.status_url}`} />
            </Step>
          </Card>

          <Card className="overflow-x-auto p-0 xl:col-span-2">
            <div className="px-4 pt-4 text-sm font-semibold">Alertas do template</div>
            <table className="mt-2 min-w-full divide-y divide-slate-200 dark:divide-slate-800">
              <thead className="bg-slate-50 dark:bg-slate-800/50">
                <tr>
                  <th className="th">Alerta</th>
                  <th className="th">Severidade</th>
                  <th className="th">Quando</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {ALERTS.map(([a, sev, when]) => (
                  <tr key={a}>
                    <td className="td font-medium">{a}</td>
                    <td className="td whitespace-nowrap">{sev}</td>
                    <td className="td text-slate-500 dark:text-slate-400">{when}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-4 pb-4 pt-2 text-xs text-slate-400 dark:text-slate-500">
              Os alertas de cliente se resolvem sozinhos quando o próximo backup chega bem. Cliente desativado ou excluído some do
              Zabbix na descoberta seguinte.
            </p>
          </Card>
        </div>
      )}

      <Modal open={!!token} onClose={() => setToken(null)} title="Token do Zabbix">
        {token && (
          <div className="space-y-3 text-sm">
            <p className="text-amber-700 dark:text-amber-300">
              Copie agora: o token não é mostrado de novo (o servidor guarda só o hash).
            </p>
            <CopyBlock label="Token" text={token} />
            <p className="text-slate-500 dark:text-slate-400">
              No Zabbix, cole na macro <span className="font-mono">{"{$H2NODE.TOKEN}"}</span> do host, com o tipo{" "}
              <b>Texto secreto</b>.
            </p>
            <div className="flex justify-end">
              <Button onClick={() => setToken(null)}>Copiei</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

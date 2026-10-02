import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { RefreshButton } from "../../components/RefreshButton";
import { HealthBadge } from "../../components/status";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtAgo, fmtBytes } from "../../lib/format";
import type { Client } from "../../lib/types";

interface FormState {
  id?: number;
  slug: string;
  name: string;
  description: string;
  is_active: boolean;
  ssh_public_key: string;
  expected_interval_hours: number;
  retention_days: number;
  retention_min_keep: number;
}

const empty: FormState = {
  slug: "",
  name: "",
  description: "",
  is_active: true,
  ssh_public_key: "",
  expected_interval_hours: 24,
  retention_days: 30,
  retention_min_keep: 7,
};

interface AgentConfig {
  filename: string;
  content: string;
  known_hosts: string | null;
  public_key_available: boolean;
}

export function CopyBlock({ text, label }: { text: string; label?: string }) {
  const toast = useToast();
  return (
    <div className="relative">
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-slate-200 bg-slate-50 p-3 pr-20 font-mono text-xs leading-relaxed text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
        {text}
      </pre>
      <button
        type="button"
        className="btn-ghost absolute right-2 top-2 px-2 py-1 text-xs"
        onClick={() =>
          navigator.clipboard
            .writeText(text)
            .then(() => toast("ok", `${label ?? "Texto"} copiado`))
            .catch(() => toast("err", "Não foi possível copiar"))
        }
      >
        Copiar
      </button>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white dark:bg-brand-500">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="font-semibold">{title}</div>
        {children}
      </div>
    </div>
  );
}

function downloadText(name: string, text: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function AgentConfigModal({ client, onClose }: { client: Client | null; onClose: () => void }) {
  const toast = useToast();
  const q = useQuery({
    queryKey: ["agent-config", client?.id],
    queryFn: () => api.get<AgentConfig>(`/clients/${client!.id}/agent-config`),
    enabled: !!client,
  });
  const cfg = q.data;

  async function downloadKey() {
    try {
      const blob = await api.blob("/server/public-key");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "backup-key.pub.asc";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast("err", e instanceof ApiError ? e.detail : "Chave pública indisponível");
    }
  }

  return (
    <Modal open={!!client} onClose={onClose} title={`Configuração do agente — ${client?.name ?? ""}`} wide>
      {!cfg ? (
        <Spinner className="h-5 w-5 text-brand-600" />
      ) : (
        <div className="space-y-5 text-sm">
          <Step n={1} title="Instale o agente no servidor (como root)">
            <p className="text-slate-500 dark:text-slate-400">
              Copie a pasta <code className="font-mono">agent/</code> do repositório para o servidor e rode o
              instalador. Ele agenda a execução diária no crontab do root e gera a chave SSH do agente.
            </p>
            <CopyBlock
              label="Comando"
              text={`cd agent && sudo ./install.sh --cron "30 2 * * *"\n# a chave pública SSH impressa no final vai no cadastro deste cliente`}
            />
          </Step>
          <Step n={2} title="Cadastre a chave SSH do agente">
            <p className="text-slate-500 dark:text-slate-400">
              {client?.ssh_key_fingerprint ? (
                <>
                  Chave cadastrada: <span className="font-mono">{client.ssh_key_fingerprint}</span>
                </>
              ) : (
                <>
                  <b className="text-amber-600 dark:text-amber-400">Sem chave ainda.</b> Edite o cliente e cole o
                  conteúdo de <code className="font-mono">/etc/pulse-backup/id_ed25519.pub</code>.
                </>
              )}
            </p>
          </Step>
          <Step n={3} title="Grave a configuração em /etc/pulse-backup/agent.conf (modo 600)">
            <p className="text-slate-500 dark:text-slate-400">
              Ajuste <code className="font-mono">BACKUP_PATHS</code> e ligue os bancos que existirem no servidor.
            </p>
            <CopyBlock label="agent.conf" text={cfg.content} />
            <Button variant="ghost" onClick={() => downloadText("agent.conf", cfg.content)}>
              Baixar agent.conf
            </Button>
          </Step>
          <Step n={4} title="Fixe a chave do servidor em /etc/pulse-backup/known_hosts">
            {cfg.known_hosts ? (
              <CopyBlock label="Linha do known_hosts" text={cfg.known_hosts} />
            ) : (
              <p className="text-amber-600 dark:text-amber-400">
                O container sshd ainda não publicou a chave de host — confira se ele está rodando.
              </p>
            )}
          </Step>
          <Step n={5} title="Salve a chave pública GPG em /etc/pulse-backup/backup-key.pub.asc">
            {cfg.public_key_available ? (
              <Button variant="ghost" onClick={downloadKey}>
                Baixar backup-key.pub.asc
              </Button>
            ) : (
              <p className="text-rose-600 dark:text-rose-400">
                Chave GPG não configurada no servidor — rode <code className="font-mono">make keys</code>.
              </p>
            )}
          </Step>
          <Step n={6} title="Teste e rode o primeiro backup">
            <CopyBlock label="Comandos" text={"sudo pulse-backup-agent test\nsudo pulse-backup-agent run"} />
          </Step>
        </div>
      )}
    </Modal>
  );
}

export default function ClientsPage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [form, setForm] = useState<FormState | null>(null);
  const [agentFor, setAgentFor] = useState<Client | null>(null);

  const list = useQuery({
    queryKey: ["clients", "server", q],
    queryFn: () => api.get<Client[]>("/clients", { q, kind: "server" }),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["clients"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body = {
        name: f.name,
        description: f.description || null,
        is_active: f.is_active,
        ssh_public_key: f.ssh_public_key,
        expected_interval_hours: f.expected_interval_hours,
        retention_days: f.retention_days,
        retention_min_keep: f.retention_min_keep,
      };
      return f.id
        ? api.patch<Client>(`/clients/${f.id}`, body)
        : api.post<Client>("/clients", { ...body, slug: f.slug, ssh_public_key: f.ssh_public_key || null });
    },
    onSuccess: (c, f) => {
      toast("ok", f.id ? "Cliente salvo" : "Cliente criado");
      setForm(null);
      invalidate();
      if (!f.id) setAgentFor(c);
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  const remove = useMutation({
    mutationFn: (c: Client) => api.del(`/clients/${c.id}`),
    onSuccess: () => {
      toast("ok", "Cliente removido");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  const canEdit = can("operator");

  return (
    <div>
      <PageHeader
        title="Servidores"
        subtitle="Servidores Linux que enviam backups (agente no crontab do root)"
        actions={
          <>
            <RefreshButton keys={["clients"]} />
            {canEdit && <Button onClick={() => setForm({ ...empty })}>Novo servidor</Button>}
          </>
        }
      />

      <Card className="mb-3">
        <input
          className="input max-w-xs"
          placeholder="Buscar por nome, identificador ou hostname…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Servidor</th>
              <th className="th">Situação</th>
              <th className="th">Último backup</th>
              <th className="th">Guardado</th>
              <th className="th">Retenção</th>
              <th className="th">Agente</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={7}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={7}>
                  Nenhum servidor cadastrado.
                </td>
              </tr>
            )}
            {list.data?.map((c) => (
              <tr key={c.id}>
                <td className="td">
                  <div className="font-medium">{c.name}</div>
                  <div className="font-mono text-xs text-slate-400 dark:text-slate-500">
                    {c.slug}
                    {c.hostname && c.hostname !== c.slug ? ` · ${c.hostname}` : ""}
                  </div>
                </td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">
                    <HealthBadge health={c.health} />
                    {!c.ssh_key_fingerprint && <Badge tone="amber">sem chave SSH</Badge>}
                  </div>
                </td>
                <td className="td" title={fmtDate(c.last_backup_at)}>
                  {fmtAgo(c.last_backup_at)}
                  <div className="text-xs text-slate-400 dark:text-slate-500">a cada {c.expected_interval_hours}h</div>
                </td>
                <td className="td tabular-nums">
                  {fmtBytes(c.stored_bytes)}
                  <div className="text-xs text-slate-400 dark:text-slate-500">{c.backup_count} backup(s)</div>
                </td>
                <td className="td text-xs">
                  {c.retention_days} dias
                  <div className="text-slate-400 dark:text-slate-500">mín. {c.retention_min_keep}</div>
                </td>
                <td className="td text-xs">
                  {c.agent_version ? `v${c.agent_version}` : "—"}
                  <div className="max-w-[11rem] truncate text-slate-400 dark:text-slate-500" title={c.os_info ?? ""}>
                    {c.os_info ?? ""}
                  </div>
                </td>
                <td className="td text-right">
                  <div className="flex justify-end gap-3">
                    <Link
                      to={`/backups?client=${c.id}`}
                      className="text-brand-600 hover:underline dark:text-brand-400"
                    >
                      Backups
                    </Link>
                    {canEdit && (
                      <>
                        <button className="text-brand-600 hover:underline dark:text-brand-400" onClick={() => setAgentFor(c)}>
                          Agente
                        </button>
                        <button
                          className="text-brand-600 hover:underline dark:text-brand-400"
                          onClick={() =>
                            setForm({
                              id: c.id,
                              slug: c.slug,
                              name: c.name,
                              description: c.description ?? "",
                              is_active: c.is_active,
                              ssh_public_key: c.ssh_public_key ?? "",
                              expected_interval_hours: c.expected_interval_hours,
                              retention_days: c.retention_days,
                              retention_min_keep: c.retention_min_keep,
                            })
                          }
                        >
                          Editar
                        </button>
                      </>
                    )}
                    {can("admin") && (
                      <button
                        className="text-rose-600 hover:underline dark:text-rose-400"
                        onClick={() => {
                          if (confirm(`Remover o cliente ${c.name}? O acesso SSH dele é revogado na hora.`))
                            remove.mutate(c);
                        }}
                      >
                        Excluir
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar servidor" : "Novo servidor"} wide>
        {form && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Nome">
                <input
                  className="input"
                  value={form.name}
                  onChange={(e) => {
                    const name = e.target.value;
                    // Sugere o identificador a partir do nome enquanto o usuário não o editou à mão.
                    const follows = !form.id && form.slug === slugOf(form.name);
                    setForm({ ...form, name, slug: follows ? slugOf(name) : form.slug });
                  }}
                  required
                  autoFocus
                />
              </Field>
              <Field label="Identificador (CLIENT_ID)" hint="Minúsculas, números e hífen. Não muda depois.">
                <input
                  className="input font-mono"
                  value={form.slug}
                  disabled={!!form.id}
                  pattern="[a-z0-9][a-z0-9\-]{1,46}[a-z0-9]"
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  required
                />
              </Field>
            </div>
            <Field label="Descrição">
              <input
                className="input"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </Field>
            <Field
              label="Chave pública SSH do agente"
              hint="Conteúdo de /etc/pulse-backup/id_ed25519.pub (gerado pelo install.sh). Vazio = cliente não consegue enviar."
            >
              <textarea
                className="input min-h-[80px] font-mono text-xs"
                value={form.ssh_public_key}
                placeholder="ssh-ed25519 AAAAC3Nza… root@servidor"
                onChange={(e) => setForm({ ...form, ssh_public_key: e.target.value })}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Intervalo esperado (h)" hint="Alerta de atraso">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={744}
                  value={form.expected_interval_hours}
                  onChange={(e) => setForm({ ...form, expected_interval_hours: Number(e.target.value) })}
                />
              </Field>
              <Field label="Retenção (dias)">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={3650}
                  value={form.retention_days}
                  onChange={(e) => setForm({ ...form, retention_days: Number(e.target.value) })}
                />
              </Field>
              <Field label="Manter no mínimo" hint="Backups válidos, mesmo vencidos">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={1000}
                  value={form.retention_min_keep}
                  onChange={(e) => setForm({ ...form, retention_min_keep: Number(e.target.value) })}
                />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              Ativo (inativo = acesso SSH revogado, sem alertas de atraso)
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={() => setForm(null)}>
                Cancelar
              </Button>
              <Button type="submit" loading={save.isPending}>
                Salvar
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <AgentConfigModal client={agentFor} onClose={() => setAgentFor(null)} />
    </div>
  );
}

function slugOf(name: string) {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

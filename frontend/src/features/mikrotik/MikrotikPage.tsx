import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DeleteClientModal } from "../../components/DeleteClientModal";
import { RefreshButton } from "../../components/RefreshButton";
import { HealthBadge } from "../../components/status";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtAgo, fmtBytes } from "../../lib/format";
import type { Client, DeviceCredential } from "../../lib/types";

interface FormState {
  id?: number;
  slug: string;
  name: string;
  description: string;
  is_active: boolean;
  mgmt_ip: string;
  pull_port: string;
  pull_credential_id: number;
  expected_interval_hours: number;
  retention_days: number;
  retention_min_keep: number;
}

const DEFAULTS = { expected_interval_hours: 24, retention_days: 90, retention_min_keep: 10 };

function slugOf(name: string) {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function errMsg(e: unknown) {
  return e instanceof ApiError ? e.detail : "erro inesperado";
}

/** "IP[:porta] [nome]" por linha — o mesmo espírito das listas de hosts do MBackupTool. */
function parseLines(text: string) {
  const rows: { ip: string; port: number | null; name: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, "").trim();
    if (!line) continue;
    const [addr, ...rest] = line.split(/[\s;,]+/);
    const m = addr.match(/^([^:]+)(?::(\d+))?$/);
    if (!m) continue;
    rows.push({ ip: m[1], port: m[2] ? Number(m[2]) : null, name: rest.join(" ") || m[1] });
  }
  return rows;
}

function ImportModal({
  open,
  creds,
  onClose,
  onDone,
}: {
  open: boolean;
  creds: DeviceCredential[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [text, setText] = useState("");
  const [credId, setCredId] = useState<number>(0);
  const [hours, setHours] = useState(DEFAULTS.expected_interval_hours);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<{ line: string; ok: boolean }[]>([]);
  const rows = parseLines(text);
  const cred = credId || creds[0]?.id || 0;

  async function run() {
    setBusy(true);
    const out: { line: string; ok: boolean }[] = [];
    for (const r of rows) {
      const slug = slugOf(r.name === r.ip ? `mk-${r.ip}` : r.name);
      try {
        await api.post<Client>("/clients", {
          slug,
          name: r.name,
          kind: "network",
          vendor: "mikrotik",
          protocol: "ssh",
          mgmt_ip: r.ip,
          pull_port: r.port,
          pull_credential_id: cred,
          expected_interval_hours: hours,
          retention_days: DEFAULTS.retention_days,
          retention_min_keep: DEFAULTS.retention_min_keep,
        });
        out.push({ line: `${r.ip} → ${r.name}: cadastrado`, ok: true });
      } catch (e) {
        out.push({ line: `${r.ip} → ${r.name}: ${errMsg(e)}`, ok: false });
      }
      setLog([...out]);
    }
    setBusy(false);
    onDone();
  }

  const close = () => {
    if (busy) return;
    setText("");
    setLog([]);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Importar MikroTik em lote"
      wide
    >
      <div className="space-y-3 text-sm">
        <Field label="Hosts" hint="Um por linha: IP[:porta] [nome]. Linhas com # são ignoradas. Sem nome, usa o IP.">
          <textarea
            className="input h-48 font-mono text-xs"
            value={text}
            placeholder={"10.0.0.1 RB-Core\n10.0.0.2:2202 RB-POP-Centro\n10.0.0.3"}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Credencial de acesso">
            <select className="input" value={cred} onChange={(e) => setCredId(Number(e.target.value))} disabled={busy}>
              {creds.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.username}, porta {c.port})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Coletar a cada (h)">
            <input
              className="input"
              type="number"
              min={1}
              max={744}
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              disabled={busy}
            />
          </Field>
        </div>
        {log.length > 0 && (
          <ul className="max-h-48 space-y-0.5 overflow-auto rounded-lg border border-slate-200 p-2 font-mono text-xs dark:border-slate-800">
            {log.map((l, i) => (
              <li key={i} className={l.ok ? "text-emerald-700 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                {l.line}
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center justify-between gap-2 pt-2">
          <span className="text-slate-500 dark:text-slate-400">{rows.length} host(s) na lista</span>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={close} disabled={busy}>
              Fechar
            </Button>
            <Button type="button" loading={busy} disabled={!rows.length || !cred} onClick={run}>
              Cadastrar {rows.length || ""}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

export default function MikrotikPage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const [delFor, setDelFor] = useState<Client | null>(null);
  const toast = useToast();
  const [q, setQ] = useState("");
  const [form, setForm] = useState<FormState | null>(null);
  const [importing, setImporting] = useState(false);
  const canEdit = can("operator");

  const list = useQuery({
    queryKey: ["clients", "mikrotik", q],
    queryFn: () => api.get<Client[]>("/clients", { q, kind: "network", vendor: "mikrotik" }),
    // acompanha a coleta pedida com "Coletar agora"
    refetchInterval: 15000,
  });
  const creds = useQuery({
    queryKey: ["device-credentials"],
    queryFn: () => api.get<DeviceCredential[]>("/device-credentials"),
    enabled: canEdit,
  });
  const credName = (id: number | null) => creds.data?.find((c) => c.id === id);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["clients"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body = {
        name: f.name,
        description: f.description || null,
        is_active: f.is_active,
        vendor: "mikrotik",
        protocol: "ssh",
        mgmt_ip: f.mgmt_ip.trim(),
        pull_port: f.pull_port ? Number(f.pull_port) : null,
        pull_credential_id: f.pull_credential_id,
        expected_interval_hours: f.expected_interval_hours,
        retention_days: f.retention_days,
        retention_min_keep: f.retention_min_keep,
      };
      return f.id
        ? api.patch<Client>(`/clients/${f.id}`, body)
        : api.post<Client>("/clients", { ...body, slug: f.slug, kind: "network" });
    },
    onSuccess: (_c, f) => {
      toast("ok", f.id ? "MikroTik salvo" : "MikroTik cadastrado — a primeira coleta sai em instantes");
      setForm(null);
      invalidate();
    },
    onError: (e) => toast("err", errMsg(e)),
  });

  const action = useMutation({
    mutationFn: ({ c, what }: { c: Client; what: "pull-now" | "accept-host-key" }) =>
      api.post<Client>(`/clients/${c.id}/${what}`),
    onSuccess: (_c, { what }) => {
      toast("ok", what === "pull-now" ? "Coleta agendada (sai em até 30 s)" : "Nova chave será aceita na próxima coleta");
      invalidate();
    },
    onError: (e) => toast("err", errMsg(e)),
  });

  const noCreds = canEdit && creds.data?.length === 0;
  const newForm = (): FormState => ({
    slug: "",
    name: "",
    description: "",
    is_active: true,
    mgmt_ip: "",
    pull_port: "",
    pull_credential_id: creds.data?.[0]?.id ?? 0,
    ...DEFAULTS,
  });

  return (
    <div>
      <PageHeader
        title="MikroTik"
        subtitle="O H2NODE Backup entra por SSH em cada MikroTik, exporta a configuração (/export), cifra e guarda"
        actions={
          <>
            <RefreshButton keys={["clients"]} />
            {canEdit && (
              <>
                <Button variant="ghost" onClick={() => setImporting(true)} disabled={!creds.data?.length}>
                  Importar lista
                </Button>
                <Button onClick={() => setForm(newForm())} disabled={!creds.data?.length}>
                  Novo MikroTik
                </Button>
              </>
            )}
          </>
        }
      />

      {noCreds && (
        <Card className="mb-3 border-amber-200 bg-amber-50 text-sm text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
          Primeiro crie o usuário de acesso em{" "}
          <Link className="font-semibold underline underline-offset-2" to="/mikrotik/credentials">
            MikroTik → Usuário de acesso
          </Link>{" "}
          e crie esse usuário nos MikroTik. Passo a passo em{" "}
          <Link className="font-semibold underline underline-offset-2" to="/help/mikrotik">
            Ajuda → MikroTik
          </Link>
          .
        </Card>
      )}

      <Card className="mb-3">
        <input
          className="input max-w-xs"
          placeholder="Buscar por nome, identificador ou IP…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">MikroTik</th>
              <th className="th">Acesso</th>
              <th className="th">Situação</th>
              <th className="th">Última coleta</th>
              <th className="th">Guardado</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={6}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={6}>
                  Nenhum MikroTik cadastrado.
                </td>
              </tr>
            )}
            {list.data?.map((c) => {
              const cred = credName(c.pull_credential_id);
              const hostKeyChanged = !!c.pull_error?.includes("chave de host");
              return (
                <tr key={c.id}>
                  <td className="td">
                    <div className="font-medium">{c.name}</div>
                    <div className="font-mono text-xs text-slate-400 dark:text-slate-500">{c.slug}</div>
                  </td>
                  <td className="td">
                    <div className="font-mono">
                      {c.mgmt_ip}:{c.pull_port ?? cred?.port ?? 22}
                    </div>
                    <div className="text-xs text-slate-400 dark:text-slate-500">
                      {cred ? `${cred.name} (${cred.username})` : "—"}
                    </div>
                    {c.pull_host_key_fingerprint && (
                      <div
                        className="max-w-[14rem] truncate font-mono text-[11px] text-slate-400 dark:text-slate-500"
                        title={`Chave de host fixada: ${c.pull_host_key_fingerprint}`}
                      >
                        {c.pull_host_key_fingerprint}
                      </div>
                    )}
                  </td>
                  <td className="td">
                    <HealthBadge health={c.health} />
                    {c.pull_error && (
                      <div className="mt-1 max-w-xs text-xs text-rose-600 dark:text-rose-400">{c.pull_error}</div>
                    )}
                  </td>
                  <td className="td" title={fmtDate(c.pull_last_at)}>
                    {fmtAgo(c.pull_last_at)}
                    <div className="text-xs text-slate-400 dark:text-slate-500">
                      a cada {c.expected_interval_hours}h
                      {c.is_active && (
                        <>
                          {" · próxima "}
                          {!c.pull_next_at || new Date(c.pull_next_at) <= new Date() ? (
                            <Badge tone="blue">agora</Badge>
                          ) : (
                            fmtDate(c.pull_next_at)
                          )}
                        </>
                      )}
                    </div>
                  </td>
                  <td className="td tabular-nums">
                    {fmtBytes(c.stored_bytes)}
                    <div className="text-xs text-slate-400 dark:text-slate-500">{c.backup_count} versão(ões)</div>
                  </td>
                  <td className="td text-right">
                    <div className="flex flex-wrap justify-end gap-x-3 gap-y-1">
                      <Link to={`/backups?client=${c.id}`} className="text-brand-600 hover:underline dark:text-brand-400">
                        Backups
                      </Link>
                      {canEdit && (
                        <>
                          {c.is_active && (
                            <button
                              className="text-brand-600 hover:underline dark:text-brand-400"
                              onClick={() => action.mutate({ c, what: "pull-now" })}
                            >
                              Coletar agora
                            </button>
                          )}
                          {hostKeyChanged && (
                            <button
                              className="text-amber-600 hover:underline dark:text-amber-400"
                              onClick={() => {
                                if (
                                  confirm(
                                    `Aceitar a nova chave SSH de ${c.name}? Faça isso só se o equipamento foi trocado, reinstalado ou teve a chave regenerada.`,
                                  )
                                )
                                  action.mutate({ c, what: "accept-host-key" });
                              }}
                            >
                              Aceitar nova chave
                            </button>
                          )}
                          <button
                            className="text-brand-600 hover:underline dark:text-brand-400"
                            onClick={() =>
                              setForm({
                                id: c.id,
                                slug: c.slug,
                                name: c.name,
                                description: c.description ?? "",
                                is_active: c.is_active,
                                mgmt_ip: c.mgmt_ip ?? "",
                                pull_port: c.pull_port ? String(c.pull_port) : "",
                                pull_credential_id: c.pull_credential_id ?? creds.data?.[0]?.id ?? 0,
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
                            setDelFor(c);
                          }}
                        >
                          Excluir
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar MikroTik" : "Novo MikroTik"} wide>
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
                    const follows = !form.id && form.slug === slugOf(form.name);
                    setForm({ ...form, name, slug: follows ? slugOf(name) : form.slug });
                  }}
                  required
                  autoFocus
                />
              </Field>
              <Field label="Identificador" hint="Minúsculas, números e hífen. Não muda depois.">
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
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="IP" hint="Onde o servidor conecta por SSH">
                <input
                  className="input font-mono"
                  value={form.mgmt_ip}
                  placeholder="10.0.0.1"
                  onChange={(e) => setForm({ ...form, mgmt_ip: e.target.value })}
                  required
                />
              </Field>
              <Field label="Porta SSH" hint="Vazio = a da credencial">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={65535}
                  value={form.pull_port}
                  placeholder={String(credName(form.pull_credential_id)?.port ?? 22)}
                  onChange={(e) => setForm({ ...form, pull_port: e.target.value })}
                />
              </Field>
              <Field label="Credencial de acesso">
                <select
                  className="input"
                  value={form.pull_credential_id}
                  onChange={(e) => setForm({ ...form, pull_credential_id: Number(e.target.value) })}
                  required
                >
                  {creds.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.username})
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Descrição">
              <input
                className="input"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Coletar a cada (h)" hint="Também é o prazo do alerta de atraso">
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
              <Field label="Manter no mínimo" hint="Versões válidas, mesmo vencidas">
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
              Ativo (inativo = não coleta)
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

      <ImportModal open={importing} creds={creds.data ?? []} onClose={() => setImporting(false)} onDone={invalidate} />
      <DeleteClientModal client={delFor} onClose={() => setDelFor(null)} onDone={invalidate} />
    </div>
  );
}

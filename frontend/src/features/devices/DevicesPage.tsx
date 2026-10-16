import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { RefreshButton } from "../../components/RefreshButton";
import { HealthBadge } from "../../components/status";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtAgo, fmtBytes } from "../../lib/format";
import { VENDOR_LABEL, VENDOR_PROTOCOL, type Client, type Vendor } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";

type Protocol = "ftp" | "tftp";

interface FormState {
  id?: number;
  slug: string;
  name: string;
  description: string;
  is_active: boolean;
  vendor: Vendor;
  mgmt_ip: string;
  manager_ip: string;
  protocol: Protocol;
  expected_interval_hours: number;
  retention_days: number;
  retention_min_keep: number;
}

const empty: FormState = {
  slug: "",
  name: "",
  description: "",
  is_active: true,
  vendor: "huawei",
  mgmt_ip: "",
  manager_ip: "",
  protocol: "ftp",
  // Huawei/Juniper/UNM2000 enviam a cada alteração: sob demanda (sem alerta de atraso)
  expected_interval_hours: 0,
  retention_days: 90,
  retention_min_keep: 10,
};

interface DeviceConfig {
  vendor: string;
  protocol: string;
  server_host: string;
  ftp_user: string | null;
  ftp_accounts: string[];
  commands: string;
  notes: string[];
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

function DeviceConfigModal({ device, onClose }: { device: Client | null; onClose: () => void }) {
  const [ftpUser, setFtpUser] = useState<string>("");
  const q = useQuery({
    queryKey: ["device-config", device?.id, ftpUser],
    queryFn: () => api.get<DeviceConfig>(`/clients/${device!.id}/device-config`, { ftp_user: ftpUser }),
    enabled: !!device,
  });
  const cfg = q.data;
  return (
    <Modal
      open={!!device}
      onClose={() => {
        setFtpUser("");
        onClose();
      }}
      title={`Configurar envio — ${device?.name ?? ""}`}
      wide
    >
      {!cfg ? (
        <Spinner className="h-5 w-5 text-brand-600" />
      ) : (
        <div className="space-y-4 text-sm">
          <p className="text-slate-500 dark:text-slate-400">
            Comandos para o {VENDOR_LABEL[cfg.vendor as Vendor] ?? cfg.vendor} enviar a configuração para{" "}
            <span className="font-mono">{cfg.server_host}</span> via{" "}
            <b className="uppercase">{cfg.protocol}</b>.
          </p>
          {cfg.protocol === "ftp" && cfg.ftp_accounts.length > 1 && (
            <Field label="Conta FTP">
              <select className="input max-w-xs" value={cfg.ftp_user ?? ""} onChange={(e) => setFtpUser(e.target.value)}>
                {cfg.ftp_accounts.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <CopyBlock label="Comandos" text={cfg.commands} />
          <ul className="list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
            {cfg.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
            FTP e TFTP trafegam em claro (inclusive a senha FTP). Use a rede de gerência ou uma VPN entre o
            equipamento e o servidor. Ao chegar, a configuração é cifrada com a chave GPG e o original é apagado.
          </div>
        </div>
      )}
    </Modal>
  );
}

export default function DevicesPage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [form, setForm] = useState<FormState | null>(null);
  const [cfgFor, setCfgFor] = useState<Client | null>(null);

  const list = useQuery({
    queryKey: ["clients", "network", q],
    queryFn: () => api.get<Client[]>("/clients", { q, kind: "network" }),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["clients"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body = {
        name: f.name,
        description: f.description || null,
        is_active: f.is_active,
        vendor: f.vendor,
        mgmt_ip: f.mgmt_ip.trim(),
        // só OLT Fiberhome por FTP tem UNM2000; "" remove (o servidor também limpa nos outros casos)
        manager_ip: f.vendor === "fiberhome" && f.protocol === "ftp" ? f.manager_ip.trim() : "",
        protocol: f.protocol,
        expected_interval_hours: f.expected_interval_hours,
        retention_days: f.retention_days,
        retention_min_keep: f.retention_min_keep,
      };
      return f.id
        ? api.patch<Client>(`/clients/${f.id}`, body)
        : api.post<Client>("/clients", { ...body, slug: f.slug, kind: "network" });
    },
    onSuccess: (c, f) => {
      toast("ok", f.id ? "Equipamento salvo" : "Equipamento cadastrado");
      setForm(null);
      invalidate();
      if (!f.id) setCfgFor(c);
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  const remove = useMutation({
    mutationFn: (c: Client) => api.del(`/clients/${c.id}`),
    onSuccess: () => {
      toast("ok", "Equipamento removido");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  const canEdit = can("operator");

  return (
    <div>
      <PageHeader
        title="Equipamentos de rede"
        subtitle="Switches e roteadores que enviam a configuração por FTP ou TFTP"
        actions={
          <>
            <RefreshButton keys={["clients"]} />
            {canEdit && <Button onClick={() => setForm({ ...empty })}>Novo equipamento</Button>}
          </>
        }
      />

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
              <th className="th">Equipamento</th>
              <th className="th">Fabricante</th>
              <th className="th">Envio</th>
              <th className="th">Situação</th>
              <th className="th">Última configuração</th>
              <th className="th">Guardado</th>
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
                  Nenhum equipamento cadastrado.
                </td>
              </tr>
            )}
            {list.data?.map((c) => (
              <tr key={c.id}>
                <td className="td">
                  <div className="font-medium">{c.name}</div>
                  <div className="font-mono text-xs text-slate-400 dark:text-slate-500">{c.slug}</div>
                </td>
                <td className="td">{c.vendor ? VENDOR_LABEL[c.vendor] : "—"}</td>
                <td className="td">
                  <Badge tone="blue">{c.protocol?.toUpperCase()}</Badge>
                  <div className="mt-0.5 font-mono text-xs text-slate-400 dark:text-slate-500">de {c.mgmt_ip}</div>
                  {c.manager_ip && (
                    <div className="font-mono text-xs text-slate-400 dark:text-slate-500">UNM2000 {c.manager_ip}</div>
                  )}
                </td>
                <td className="td">
                  <HealthBadge health={c.health} />
                </td>
                <td className="td" title={fmtDate(c.last_backup_at)}>
                  {fmtAgo(c.last_backup_at)}
                  <div className="text-xs text-slate-400 dark:text-slate-500">
                    {c.expected_interval_hours ? `a cada ${c.expected_interval_hours}h` : "sob demanda"}
                  </div>
                </td>
                <td className="td tabular-nums">
                  {fmtBytes(c.stored_bytes)}
                  <div className="text-xs text-slate-400 dark:text-slate-500">{c.backup_count} versão(ões)</div>
                </td>
                <td className="td text-right">
                  <div className="flex justify-end gap-3">
                    <Link to={`/backups?client=${c.id}`} className="text-brand-600 hover:underline dark:text-brand-400">
                      Backups
                    </Link>
                    {canEdit && (
                      <>
                        <button className="text-brand-600 hover:underline dark:text-brand-400" onClick={() => setCfgFor(c)}>
                          Comandos
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
                              vendor: c.vendor ?? "generic",
                              mgmt_ip: c.mgmt_ip ?? "",
                              manager_ip: c.manager_ip ?? "",
                              protocol: c.protocol ?? "ftp",
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
                          if (confirm(`Remover o equipamento ${c.name}? O IP dele deixa de poder enviar na hora.`))
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

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar equipamento" : "Novo equipamento"} wide>
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
              <Field label="Fabricante" hint="Define os comandos e a validação">
                <select
                  className="input"
                  value={form.vendor}
                  onChange={(e) => {
                    const vendor = e.target.value as Vendor;
                    setForm({ ...form, vendor, protocol: form.id ? form.protocol : VENDOR_PROTOCOL[vendor] });
                  }}
                >
                  {(Object.keys(VENDOR_LABEL) as Vendor[]).map((v) => (
                    <option key={v} value={v}>
                      {VENDOR_LABEL[v]}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Protocolo">
                <select
                  className="input"
                  value={form.protocol}
                  onChange={(e) => setForm({ ...form, protocol: e.target.value as Protocol })}
                >
                  <option value="ftp">FTP</option>
                  <option value="tftp">TFTP</option>
                </select>
              </Field>
              <Field label="IP de origem" hint="IP com que o equipamento chega aqui">
                <input
                  className="input font-mono"
                  value={form.mgmt_ip}
                  placeholder="192.0.2.15"
                  onChange={(e) => setForm({ ...form, mgmt_ip: e.target.value })}
                  required
                />
              </Field>
            </div>
            {form.vendor === "fiberhome" && form.protocol === "ftp" && (
              <Field
                label="IP da UNM2000 (gerenciador)"
                hint="Depois que a OLT envia, a UNM2000 entra no FTP para apagar/renomear o arquivo. Este IP passa a poder usar o FTP (sem cadastro próprio) — libere-o também no ufw."
              >
                <input
                  className="input font-mono"
                  value={form.manager_ip}
                  placeholder="203.0.113.26"
                  onChange={(e) => setForm({ ...form, manager_ip: e.target.value })}
                />
              </Field>
            )}
            <Field label="Descrição">
              <input
                className="input"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Intervalo esperado (h)" hint="0 = sob demanda (envia a cada alteração)">
                <input
                  className="input"
                  type="number"
                  min={0}
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
              Ativo (inativo = o IP deixa de poder enviar)
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

      <DeviceConfigModal device={cfgFor} onClose={() => setCfgFor(null)} />
    </div>
  );
}

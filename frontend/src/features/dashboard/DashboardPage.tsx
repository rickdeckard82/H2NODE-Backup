import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  DiskDonut,
  HBarList,
  RunsChart,
  StackBar,
  StorageTrendChart,
  VolumeChart,
  type DailyPoint,
  type StoragePoint,
} from "../../components/charts";
import { RefreshButton } from "../../components/RefreshButton";
import { BackupStatusBadge, HealthBadge, VerifyBadge } from "../../components/status";
import { Card, PageHeader, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { useFmtDate } from "../../lib/datetime";
import { fmtAgo, fmtBytes } from "../../lib/format";
import type { BackupStatus, Health, VerifyStatus } from "../../lib/types";

interface Dashboard {
  days: number;
  clients_total: number;
  clients_active: number;
  servers_active: number;
  devices_active: number;
  clients_health: Partial<Record<Health, number>>;
  last24h: { ok: number; warning: number; failed: number };
  window: { ok: number; warning: number; failed: number };
  success_rate: number | null;
  bytes_window: number;
  daily: DailyPoint[];
  verification: Record<VerifyStatus, number>;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
  backups_bytes: number;
  storage_history: StoragePoint[];
  top_clients: { id: number; name: string; slug: string; stored_bytes: number }[];
  recent_problems: {
    id: number;
    client_name: string;
    received_at: string;
    status: BackupStatus;
    verify_status: VerifyStatus;
    message: string | null;
  }[];
  overdue_clients: {
    id: number;
    name: string;
    slug: string;
    health: Health;
    last_backup_at: string | null;
    expected_interval_hours: number;
  }[];
  worker: {
    online: boolean;
    last_seen_at: string | null;
    deep_verify: boolean;
    message: string | null;
    busy_with?: string | null;
    busy_since?: string | null;
  };
}

function Stat({
  label,
  value,
  accent = "bg-slate-300 dark:bg-slate-600",
  tone,
  hint,
}: {
  label: string;
  value: string | number;
  accent?: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <Card className="relative overflow-hidden">
      <span className={`absolute inset-x-0 top-0 h-1 ${accent}`} />
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </span>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span className={`text-2xl font-bold tabular-nums xl:text-3xl ${tone ?? "text-slate-900 dark:text-slate-100"}`}>
          {typeof value === "number" ? value.toLocaleString("pt-BR") : value}
        </span>
        {hint && <span className="text-xs text-slate-400 dark:text-slate-500">{hint}</span>}
      </div>
    </Card>
  );
}

const PERIODS = [7, 30, 90];

export default function DashboardPage() {
  const fmtDate = useFmtDate();
  const [days, setDays] = useState(30);
  const q = useQuery({
    queryKey: ["dashboard", days],
    queryFn: () => api.get<Dashboard>("/dashboard", { days }),
    refetchInterval: 60_000,
  });
  const d = q.data;

  const overdue = (d?.clients_health.overdue ?? 0) + (d?.clients_health.never ?? 0);
  const failing = d?.clients_health.failed ?? 0;

  return (
    <div>
      <PageHeader
        title="Painel"
        subtitle={`Visão geral dos backups — últimos ${days} dias`}
        actions={
          <>
            <div className="flex overflow-hidden rounded-lg border border-slate-300 dark:border-slate-700">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setDays(p)}
                  className={`px-3 py-2 text-sm font-medium ${
                    days === p
                      ? "bg-brand-600 text-white dark:bg-brand-500"
                      : "bg-white text-slate-600 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                  }`}
                >
                  {p}d
                </button>
              ))}
            </div>
            <RefreshButton keys={["dashboard"]} />
          </>
        }
      />

      {q.isLoading || !d ? (
        <Spinner className="h-6 w-6 text-brand-600" />
      ) : (
        <div className="space-y-4">
          {!d.worker.online && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300">
              <b>Worker parado</b> — os uploads não estão sendo recebidos nem verificados
              {d.worker.last_seen_at ? ` (último sinal ${fmtDate(d.worker.last_seen_at)})` : ""}
              {d.worker.busy_with ? `, na tarefa "${d.worker.busy_with}"` : ""}. Veja{" "}
              <code className="font-mono">docker compose logs worker</code>.
            </div>
          )}
          {d.worker.online && d.worker.busy_with && d.worker.busy_since && (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              Worker: {d.worker.busy_with} desde {fmtDate(d.worker.busy_since)}
            </div>
          )}
          {d.worker.online && !d.worker.deep_verify && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
              Verificação profunda desligada — o worker confere hash e chave de destino, mas não decifra
              para testar o conteúdo. {d.worker.message}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat
              label="Origens ativas"
              value={d.clients_active}
              accent="bg-brand-500"
              hint={`${d.servers_active} servidor(es) · ${d.devices_active} equipamento(s)`}
            />
            <Stat
              label="Atrasados / falhando"
              value={overdue + failing}
              tone={overdue + failing ? "text-rose-600 dark:text-rose-400" : undefined}
              accent={overdue + failing ? "bg-rose-500" : "bg-emerald-500"}
              hint={overdue + failing ? `${overdue} atrasado(s) · ${failing} falhando` : "tudo em dia"}
            />
            <Stat
              label="Sucesso (24h)"
              value={d.last24h.ok + d.last24h.warning}
              tone="text-emerald-600 dark:text-emerald-400"
              accent="bg-emerald-500"
              hint={d.last24h.warning ? `${d.last24h.warning} c/ aviso` : undefined}
            />
            <Stat
              label="Falhas (24h)"
              value={d.last24h.failed}
              tone={d.last24h.failed ? "text-rose-600 dark:text-rose-400" : undefined}
              accent="bg-rose-500"
              hint={`${d.window.failed} em ${days}d`}
            />
            <Stat
              label="Espaço em backups"
              value={fmtBytes(d.backups_bytes)}
              accent="bg-brand-500"
              hint={`+${fmtBytes(d.bytes_window)} em ${days}d`}
            />
            <Stat
              label="Disco disponível"
              value={fmtBytes(d.disk_free_bytes)}
              accent={
                d.disk_total_bytes && d.disk_free_bytes / d.disk_total_bytes < 0.1 ? "bg-rose-500" : "bg-slate-400"
              }
              tone={
                d.disk_total_bytes && d.disk_free_bytes / d.disk_total_bytes < 0.1
                  ? "text-rose-600 dark:text-rose-400"
                  : undefined
              }
              hint={`de ${fmtBytes(d.disk_total_bytes)}`}
            />
          </div>

          <Card>
            <RunsChart data={d.daily} />
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <VolumeChart data={d.daily} />
            </Card>
            <Card>
              <h3 className="mb-4 font-semibold">Disco dos backups</h3>
              <DiskDonut
                total={d.disk_total_bytes}
                used={d.disk_used_bytes}
                free={d.disk_free_bytes}
                backups={d.backups_bytes}
              />
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <StorageTrendChart data={d.storage_history} />
            </Card>
            <Card>
              <h3 className="mb-4 font-semibold">Origens que mais ocupam espaço</h3>
              <HBarList
                items={d.top_clients.map((c) => ({ label: c.name, sub: c.slug, value: c.stored_bytes }))}
                empty="Nenhum backup guardado ainda"
              />
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="space-y-5">
              <StackBar
                title="Verificação dos backups guardados"
                parts={[
                  { label: "Verificados", value: d.verification.ok, color: "bg-emerald-500" },
                  { label: "Reprovados", value: d.verification.failed, color: "bg-rose-500" },
                  {
                    label: "Na fila",
                    value: d.verification.pending + d.verification.running,
                    color: "bg-brand-500",
                  },
                  { label: "Sem verificação", value: d.verification.skipped, color: "bg-slate-400" },
                ]}
              />
              <div className="border-t border-slate-100 pt-4 dark:border-slate-800">
                <h3 className="mb-3 font-semibold">Origens atrasadas ou sem backup</h3>
                <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
                  {d.overdue_clients.length ? (
                    d.overdue_clients.map((c) => (
                      <li key={c.id} className="flex items-center justify-between gap-3 py-2">
                        <span className="flex min-w-0 items-center gap-2">
                          <HealthBadge health={c.health} />
                          <span className="truncate font-medium text-slate-700 dark:text-slate-200">{c.name}</span>
                        </span>
                        <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
                          último: {fmtAgo(c.last_backup_at)}
                          {c.expected_interval_hours ? ` · esperado a cada ${c.expected_interval_hours}h` : ""}
                        </span>
                      </li>
                    ))
                  ) : (
                    <li className="py-2 text-slate-400 dark:text-slate-500">Tudo em dia</li>
                  )}
                </ul>
              </div>
            </Card>

            <Card>
              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="font-semibold">Problemas recentes</h3>
                <Link to="/backups?problems=1" className="text-sm text-brand-600 hover:underline dark:text-brand-400">
                  ver todos
                </Link>
              </div>
              <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
                {d.recent_problems.length ? (
                  d.recent_problems.map((p) => (
                    <li key={p.id} className="py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
                          <Link
                            to={`/backups?open=${p.id}`}
                            className="truncate font-medium text-slate-700 hover:underline dark:text-slate-200"
                          >
                            {p.client_name}
                          </Link>
                          {p.status === "ok" || p.status === "warning" ? (
                            <VerifyBadge status={p.verify_status} />
                          ) : (
                            <BackupStatusBadge status={p.status} />
                          )}
                        </span>
                        <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
                          {fmtDate(p.received_at)}
                        </span>
                      </div>
                      {p.message && (
                        <p className="mt-0.5 line-clamp-2 pl-3.5 text-xs text-slate-500 dark:text-slate-400">
                          {p.message}
                        </p>
                      )}
                    </li>
                  ))
                ) : (
                  <li className="py-2 text-slate-400 dark:text-slate-500">Nenhuma falha recente</li>
                )}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RefreshButton } from "../../components/RefreshButton";
import { Badge, Card, Modal, PageHeader, Pagination, Spinner } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { useFmtDate } from "../../lib/datetime";
import type { AuditEntry } from "../../lib/types";

type Tone = "green" | "amber" | "red" | "blue" | "slate";

const ACTION_TONE: Record<string, Tone> = {
  create: "green",
  update: "amber",
  delete: "red",
  login: "blue",
  lockout: "red",
  download: "amber",
  verify: "blue",
  reset_mfa: "amber",
  pull_now: "blue",
  accept_host_key: "amber",
};

const ENTITY_LABEL: Record<string, string> = {
  client: "Cliente",
  backup: "Backup",
  system_user: "Usuário do painel",
  device_credential: "Credencial MikroTik",
};

function pretty(json: string | null) {
  if (!json) return "—";
  try {
    return JSON.stringify(JSON.parse(json), null, 2);
  } catch {
    return json;
  }
}

export default function AuditPage() {
  const fmtDate = useFmtDate();
  const [entityType, setEntityType] = useState("");
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<AuditEntry | null>(null);

  const list = useQuery({
    queryKey: ["audit", entityType, action, actor, page],
    queryFn: () =>
      api.get<Page<AuditEntry>>("/audit", { entity_type: entityType, action, actor, page, page_size: 30 }),
  });

  return (
    <div>
      <PageHeader
        title="Auditoria"
        subtitle="Logins e ações administrativas realizadas no painel"
        actions={<RefreshButton keys={["audit"]} />}
      />

      <Card className="mb-3 flex flex-wrap gap-2">
        <input
          className="input max-w-[12rem]"
          placeholder="Usuário…"
          value={actor}
          onChange={(e) => {
            setActor(e.target.value);
            setPage(1);
          }}
        />
        <select
          className="input max-w-[12rem]"
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Qualquer objeto</option>
          {Object.entries(ENTITY_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <select
          className="input max-w-[12rem]"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Qualquer ação</option>
          {Object.keys(ACTION_TONE).map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Quando</th>
              <th className="th">Usuário</th>
              <th className="th">Ação</th>
              <th className="th">Objeto</th>
              <th className="th">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={5}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.items.map((e) => (
              <tr
                key={e.id}
                className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                onClick={() => setDetail(e)}
              >
                <td className="td">{fmtDate(e.created_at)}</td>
                <td className="td font-medium">{e.actor_username ?? "—"}</td>
                <td className="td">
                  <Badge tone={ACTION_TONE[e.action] ?? "slate"}>{e.action}</Badge>
                </td>
                <td className="td">
                  {ENTITY_LABEL[e.entity_type] ?? e.entity_type}
                  {e.entity_id && <span className="text-slate-400 dark:text-slate-500"> #{e.entity_id}</span>}
                </td>
                <td className="td font-mono text-xs">{e.ip_address ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && (
          <Pagination page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />
        )}
      </Card>

      <Modal open={!!detail} onClose={() => setDetail(null)} title="Detalhe da auditoria" wide>
        {detail && (
          <div className="space-y-3 text-sm">
            <div className="text-slate-500 dark:text-slate-400">
              {fmtDate(detail.created_at)} · {detail.actor_username ?? "—"} · {detail.ip_address ?? "—"}
            </div>
            {detail.user_agent && <div className="break-all text-xs text-slate-400">{detail.user_agent}</div>}
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <div className="label">Antes</div>
                <pre className="overflow-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-950">{pretty(detail.before_json)}</pre>
              </div>
              <div>
                <div className="label">Depois</div>
                <pre className="overflow-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-950">{pretty(detail.after_json)}</pre>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

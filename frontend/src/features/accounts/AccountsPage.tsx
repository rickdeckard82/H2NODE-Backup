import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshButton } from "../../components/RefreshButton";
import { ComponentStatusBadge } from "../../components/status";
import { Badge, Button, Card, Modal, PageHeader, Pagination, Spinner } from "../../components/ui";
import { api, type Page } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { DEFAULT_TZ, useFmtDate } from "../../lib/datetime";
import { fmtAgo, fmtBytes } from "../../lib/format";
import type { Account, AccountVersion, Client } from "../../lib/types";
import { DecryptDownloadModal } from "../backups/DecryptDownloadModal";

const PAGE_SIZE = 50;

type SortKey = "name" | "client" | "received" | "size" | "versions" | "verify";
type Order = "asc" | "desc";

/** Texto começa do A; números e datas começam do maior/mais recente. */
const FIRST_ORDER: Record<SortKey, Order> = {
  name: "asc",
  client: "asc",
  received: "desc",
  size: "desc",
  versions: "desc",
  verify: "asc",
};

function SortTh({
  label,
  k,
  sort,
  order,
  onSort,
}: {
  label: string;
  k: SortKey;
  sort: SortKey;
  order: Order;
  onSort: (k: SortKey) => void;
}) {
  const active = sort === k;
  return (
    <th className="th" aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        className={`inline-flex items-center gap-1 uppercase hover:text-slate-900 dark:hover:text-white ${
          active ? "text-brand-700 dark:text-brand-300" : ""
        }`}
        onClick={() => onSort(k)}
        title="Ordenar"
      >
        {label}
        <span className={`text-[10px] ${active ? "" : "opacity-30"}`}>{active && order === "asc" ? "▲" : "▼"}</span>
      </button>
    </th>
  );
}

/** Hoje (AAAA-MM-DD) no fuso do operador — limite do seletor de data. */
function todayIn(tz: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(),
  );
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function HistoryModal({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const [decrypting, setDecrypting] = useState<AccountVersion | null>(null);
  const q = useQuery({
    queryKey: ["account-history", account?.client_id, account?.name],
    queryFn: () =>
      api.get<AccountVersion[]>("/backups/accounts/history", { client_id: account?.client_id, name: account?.name }),
    enabled: !!account,
  });

  async function downloadGpg(v: AccountVersion) {
    // Garante um access token válido (o download é um GET direto do navegador).
    await api.get("/auth/me").catch(() => undefined);
    const a = document.createElement("a");
    a.href = `/api/backups/${v.backup_id}/components/${v.component_id}/download`;
    a.rel = "noopener";
    a.click();
  }

  return (
    <Modal open={!!account} onClose={onClose} title={account ? `${account.name} — ${account.client_name}` : "Conta"} wide>
      {q.isLoading ? (
        <Spinner className="h-5 w-5 text-brand-600" />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead>
              <tr>
                <th className="th">Data</th>
                <th className="th">Tamanho</th>
                <th className="th">Resultado</th>
                <th className="th">Verificação</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {q.data?.map((v) => (
                <tr key={v.component_id}>
                  <td className="td">
                    {fmtDate(v.received_at)}
                    <div className="font-mono text-xs text-slate-400 dark:text-slate-500">{v.run_name}</div>
                  </td>
                  <td className="td tabular-nums">{fmtBytes(v.size_bytes)}</td>
                  <td className="td">
                    <ComponentStatusBadge status={v.status} />
                  </td>
                  <td className="td">
                    <ComponentStatusBadge status={v.verify_status} />
                    {v.verify_message && (
                      <div className="mt-1 max-w-xs break-words text-xs text-slate-500 dark:text-slate-400">
                        {v.verify_message}
                      </div>
                    )}
                  </td>
                  <td className="td whitespace-nowrap text-right">
                    <Link
                      className="mr-3 text-xs text-slate-500 hover:underline dark:text-slate-400"
                      to={`/backups?open=${v.backup_id}`}
                    >
                      Execução
                    </Link>
                    {can("admin") && v.file_name && (
                      <span className="space-x-3">
                        <button
                          className="text-brand-600 hover:underline dark:text-brand-400"
                          onClick={() => setDecrypting(v)}
                        >
                          Baixar
                        </button>
                        <button
                          className="text-xs text-slate-500 hover:underline dark:text-slate-400"
                          onClick={() => downloadGpg(v)}
                        >
                          .gpg
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4 flex justify-end">
        <Button onClick={onClose}>Fechar</Button>
      </div>
      {decrypting?.file_name && (
        <DecryptDownloadModal
          open
          onClose={() => setDecrypting(null)}
          backupId={decrypting.backup_id}
          componentId={decrypting.component_id}
          fileName={decrypting.file_name}
          sizeBytes={decrypting.size_bytes}
        />
      )}
    </Modal>
  );
}

export default function AccountsPage() {
  const fmtDate = useFmtDate();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const [clientId, setClientId] = useState("");
  const [day, setDay] = useState("");
  const [sort, setSort] = useState<SortKey>("name");
  const [order, setOrder] = useState<Order>("asc");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<Account | null>(null);

  function onSort(k: SortKey) {
    if (k === sort) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(k);
      setOrder(FIRST_ORDER[k]);
    }
    setPage(1);
  }
  const th = { sort, order, onSort };

  const clients = useQuery({
    queryKey: ["clients", "server"],
    queryFn: () => api.get<Client[]>("/clients", { kind: "server" }),
  });
  const list = useQuery({
    queryKey: ["accounts", q, clientId, day, sort, order, page],
    queryFn: () =>
      api.get<Page<Account>>("/backups/accounts", {
        q,
        client_id: clientId,
        day,
        sort,
        order,
        page,
        page_size: PAGE_SIZE,
      }),
    refetchInterval: 60_000,
  });

  return (
    <div>
      <PageHeader
        title="Contas e arquivos"
        subtitle="Cada conta do cPanel (ou arquivo enviado como está pelo agente) com a última cópia guardada e o histórico de versões"
        actions={<RefreshButton keys={["accounts", "account-history"]} />}
      />

      <Card className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input max-w-xs"
          placeholder="Buscar conta ou domínio…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          autoFocus
        />
        <select
          className="input max-w-[14rem]"
          value={clientId}
          onChange={(e) => {
            setClientId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Todos os servidores</option>
          {clients.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          type="date"
          className="input max-w-[11rem]"
          value={day}
          max={todayIn(user?.timezone || DEFAULT_TZ)}
          title="Mostra só as contas com cópia nesse dia, e a cópia desse dia"
          onChange={(e) => {
            setDay(e.target.value);
            setPage(1);
          }}
        />
        {day && (
          <Button
            variant="ghost"
            onClick={() => {
              setDay("");
              setPage(1);
            }}
          >
            Todas as datas
          </Button>
        )}
        {list.data && (
          <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">
            {list.data.total.toLocaleString("pt-BR")} {list.data.total === 1 ? "conta" : "contas"}
          </span>
        )}
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <SortTh label="Conta" k="name" {...th} />
              <SortTh label="Servidor" k="client" {...th} />
              <SortTh label={day ? "Cópia do dia" : "Última cópia"} k="received" {...th} />
              <SortTh label="Tamanho" k="size" {...th} />
              <SortTh label="Versões" k="versions" {...th} />
              <SortTh label="Verificação" k="verify" {...th} />
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
            {list.data?.items.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={6}>
                  {day
                    ? "Nenhuma conta com cópia nesse dia."
                    : "Nenhuma conta encontrada. Aqui aparecem os arquivos enviados como estão (BACKUP_FILES do agente, como os backups de conta do cPanel)."}
                </td>
              </tr>
            )}
            {list.data?.items.map((a) => (
              <tr
                key={`${a.client_id}-${a.name}`}
                className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                onClick={() => setOpen(a)}
              >
                <td className="td font-medium">{a.name.replace(/\.(tar\.gz|tgz|zip)$/i, "")}</td>
                <td className="td text-slate-500 dark:text-slate-400">{a.client_name}</td>
                <td className="td" title={fmtDate(a.last_received_at)}>
                  {day ? fmtDate(a.last_received_at) : fmtAgo(a.last_received_at)}
                </td>
                <td className="td tabular-nums">{fmtBytes(a.size_bytes)}</td>
                <td className="td">
                  <Badge tone="blue">{a.versions}</Badge>
                </td>
                <td className="td">
                  <ComponentStatusBadge status={a.verify_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
        )}
      </Card>

      <HistoryModal account={open} onClose={() => setOpen(null)} />
    </div>
  );
}

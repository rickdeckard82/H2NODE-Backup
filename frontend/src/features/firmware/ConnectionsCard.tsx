import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { Badge, Card, Spinner } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { fmtBytes, fmtDuration } from "../../lib/format";

interface Connection {
  id: string;
  protocol: "ftp" | "tftp";
  ip: string;
  user: string | null;
  since: string;
  file: string | null;
  sent: number;
  size: number | null;
}

interface ConnectionsOut {
  receivers: Record<"ftp" | "tftp", { online: boolean; updated_at: string | null }>;
  connections: Connection[];
}

const POLL_MS = 3000;

/** Sessões de firmware abertas agora: FTP logado (com a transferência em curso) e TFTP baixando. */
export function ConnectionsCard() {
  // velocidade: diferença de bytes entre duas leituras da mesma sessão
  const prev = useRef<Record<string, { sent: number; at: number }>>({});
  const q = useQuery({
    queryKey: ["firmware-connections"],
    queryFn: async () => {
      const data = await api.get<ConnectionsOut>("/firmware/connections");
      const at = Date.now();
      const rates: Record<string, number | null> = {};
      for (const c of data.connections) {
        const p = prev.current[c.id];
        rates[c.id] = p && c.sent >= p.sent && at > p.at ? ((c.sent - p.sent) * 1000) / (at - p.at) : null;
      }
      prev.current = Object.fromEntries(data.connections.map((c) => [c.id, { sent: c.sent, at }]));
      return { ...data, rates, at };
    },
    refetchInterval: POLL_MS,
  });

  const conns = q.data?.connections ?? [];
  const recv = q.data?.receivers;
  const rates = q.data?.rates ?? {};
  const now = q.data?.at ?? 0;

  return (
    <Card className="mb-3 space-y-3 p-0">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 text-sm">
        <span className="font-semibold">Conexões ativas</span>
        <Badge tone={conns.length ? "blue" : "slate"}>{conns.length}</Badge>
        <span className="ml-auto flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          {recv &&
            (["ftp", "tftp"] as const).map((p) => (
              <Badge key={p} tone={recv[p].online ? "green" : "red"}>
                {p.toUpperCase()} {recv[p].online ? "no ar" : "sem sinal"}
              </Badge>
            ))}
          <span>atualiza a cada {POLL_MS / 1000} s</span>
        </span>
      </div>

      {q.isLoading && <Spinner className="mx-4 h-5 w-5 text-brand-600" />}
      {q.isError && (
        <div className="px-4 pb-4 text-sm text-rose-600 dark:text-rose-400">
          {q.error instanceof ApiError ? q.error.detail : String(q.error)}
        </div>
      )}

      {q.isSuccess && (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-50 dark:bg-slate-800/50">
              <tr>
                <th className="th">Protocolo</th>
                <th className="th">IP</th>
                <th className="th">Usuário</th>
                <th className="th">Conectado há</th>
                <th className="th">Transferência</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {conns.length === 0 && (
                <tr>
                  <td className="td text-slate-400 dark:text-slate-500" colSpan={5}>
                    Nenhum equipamento conectado agora.
                  </td>
                </tr>
              )}
              {conns.map((c) => {
                const pct = c.size ? Math.min(100, Math.round((c.sent / c.size) * 100)) : null;
                const rate = rates[c.id];
                return (
                  <tr key={c.id}>
                    <td className="td">
                      <Badge tone="blue">{c.protocol.toUpperCase()}</Badge>
                    </td>
                    <td className="td font-mono">{c.ip}</td>
                    <td className="td font-mono">{c.user ?? "—"}</td>
                    <td className="td whitespace-nowrap">
                      {fmtDuration(Math.max(0, Math.floor((now - new Date(c.since).getTime()) / 1000)))}
                    </td>
                    <td className="td min-w-64">
                      {c.file ? (
                        <div className="space-y-1">
                          <div className="flex justify-between gap-3 text-xs">
                            <span className="truncate font-mono">{c.file}</span>
                            <span className="whitespace-nowrap text-slate-500 dark:text-slate-400">
                              {fmtBytes(c.sent)}
                              {c.size != null && ` de ${fmtBytes(c.size)}`}
                              {rate != null && rate > 0 && ` · ${fmtBytes(rate)}/s`}
                            </span>
                          </div>
                          {pct != null && (
                            <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                              <div className="h-full bg-brand-600 transition-[width]" style={{ width: `${pct}%` }} />
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400 dark:text-slate-500">ocioso (logado, sem transferência)</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

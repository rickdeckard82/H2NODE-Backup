import { useState } from "react";
import { backend } from "../backend";
import { fmtBytes, fmtDate } from "../format";
import type { UIState } from "../types";
import { Badge, Button, Card, RunBadge } from "../ui";

const COMP_TONE = { ok: "green", warning: "amber", failed: "red" } as const;
const COMP_LABEL = { ok: "ok", warning: "aviso", failed: "falhou" } as const;

export default function HistoryPage({ state }: { state: UIState }) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => backend.openConfigDir()}>
          Pasta de configuração
        </Button>
        <Button variant="ghost" onClick={() => backend.openLog()}>
          Abrir log
        </Button>
      </div>
      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Quando</th>
              <th className="th">Resultado</th>
              <th className="th">Enviado</th>
              <th className="th">Itens</th>
              <th className="th">Execução</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {state.history.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={5}>
                  Nenhum backup ainda.
                </td>
              </tr>
            )}
            {state.history.map((r) => {
              const key = r.run_name || r.started_at;
              const comps = r.components ?? [];
              const failed = comps.filter((c) => c.status === "failed").length;
              return [
                <tr
                  key={key}
                  className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  onClick={() => setOpen(open === key ? null : key)}
                >
                  <td className="td">{fmtDate(r.finished_at)}</td>
                  <td className="td">
                    <RunBadge status={r.status} />
                  </td>
                  <td className="td tabular-nums">{fmtBytes(r.bytes)}</td>
                  <td className="td">
                    {comps.length - failed} ok{failed ? `, ${failed} com falha` : ""}
                  </td>
                  <td className="td font-mono text-xs text-slate-400 dark:text-slate-500">{r.run_name || "—"}</td>
                </tr>,
                open === key && (
                  <tr key={key + "-d"}>
                    <td colSpan={5} className="bg-slate-50 px-4 py-3 dark:bg-slate-900/60">
                      <ul className="selectable space-y-1.5 text-sm">
                        {comps.map((c) => (
                          <li key={c.name} className="flex flex-wrap items-start gap-2">
                            <Badge tone={COMP_TONE[c.status]}>{COMP_LABEL[c.status]}</Badge>
                            <span className="font-mono text-xs">{c.name}</span>
                            {c.size > 0 && <span className="text-xs text-slate-400">{fmtBytes(c.size)}</span>}
                            {c.message && <span className="w-full pl-1 text-xs text-slate-500 dark:text-slate-400">{c.message}</span>}
                          </li>
                        ))}
                        {(r.errors ?? []).length > 0 && comps.length === 0 &&
                          r.errors!.map((e) => (
                            <li key={e} className="text-xs text-rose-600 dark:text-rose-400">
                              {e}
                            </li>
                          ))}
                      </ul>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </Card>
      <p className="text-xs text-slate-400 dark:text-slate-500">
        O painel do Pulse Backup mostra também a verificação feita no servidor (o arquivo é decifrado lá e conferido).
      </p>
    </div>
  );
}

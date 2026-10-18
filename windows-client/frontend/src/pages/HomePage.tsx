import { useState } from "react";
import { backend } from "../backend";
import { errText, fmtAgo, fmtBytes, fmtDate } from "../format";
import type { Progress, UIState } from "../types";
import { Button, Card, Note, RunBadge, useToast } from "../ui";

const PHASE: Record<Progress["phase"], string> = {
  preparing: "Preparando",
  snapshot: "Criando cópia de sombra (VSS)",
  packing: "Compactando e cifrando",
  uploading: "Enviando",
  closing: "Finalizando",
  done: "Concluído",
};

function scheduleText(s: UIState["schedule"]): string {
  if (s.mode === "manual") return "só manual";
  if (s.mode === "interval") return `a cada ${s.interval_hours} h`;
  const names = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
  const days = s.days?.length ? s.days.map((d) => names[d]).join(", ") : "todos os dias";
  return `${days} às ${s.time}`;
}

export default function HomePage({ state, go }: { state: UIState; go: (t: "items" | "server" | "history") => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const last = state.history[0];
  const p = state.progress;

  async function runNow() {
    setBusy(true);
    try {
      await backend.runNow();
    } catch (e) {
      toast("err", errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      {state.service_ok && !state.connected && (
        <Note tone="warn">
          Este computador ainda não está conectado ao servidor de backup.{" "}
          <button type="button" className="font-semibold underline" onClick={() => go("server")}>
            Conectar
          </button>
        </Note>
      )}
      {state.connected && state.items.length === 0 && (
        <Note>
          Escolha as pastas e arquivos que entram no backup.{" "}
          <button type="button" className="font-semibold underline" onClick={() => go("items")}>
            Escolher
          </button>
        </Note>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <div className="label">Último backup</div>
          {last ? (
            <>
              <div className="flex items-center gap-2">
                <RunBadge status={last.status} />
                <span className="text-sm text-slate-500 dark:text-slate-400" title={fmtDate(last.finished_at)}>
                  {fmtAgo(last.finished_at)}
                </span>
              </div>
              <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">{fmtBytes(last.bytes)} cifrados enviados</div>
            </>
          ) : (
            <div className="text-sm text-slate-500 dark:text-slate-400">nenhum ainda</div>
          )}
        </Card>
        <Card>
          <div className="label">Próximo backup</div>
          <div className="text-sm font-medium">{state.next_run ? fmtDate(state.next_run) : "—"}</div>
          <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">{scheduleText(state.schedule)}</div>
        </Card>
        <Card>
          <div className="label">Itens</div>
          <div className="text-sm font-medium">
            {state.items.filter((i) => i.is_dir).length} pasta(s), {state.items.filter((i) => !i.is_dir).length} arquivo(s)
          </div>
          <div className="mt-1 text-xs text-slate-400 dark:text-slate-500">
            último sucesso: {state.last_success ? fmtAgo(state.last_success) : "nunca"}
          </div>
        </Card>
      </div>

      <Card className="space-y-4 p-5">
        {state.running ? (
          <>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-semibold">{p ? PHASE[p.phase] : "Preparando"}</div>
                {p && p.count > 0 && (
                  <div className="text-sm text-slate-500 dark:text-slate-400">
                    item {Math.max(p.index, 1)} de {p.count}
                  </div>
                )}
              </div>
              <Button variant="danger" onClick={() => backend.cancel()}>
                Cancelar
              </Button>
            </div>
            {p?.item && <div className="selectable truncate font-mono text-xs text-slate-500 dark:text-slate-400">{p.item}</div>}
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div
                className={`h-full rounded-full bg-brand-600 transition-all dark:bg-brand-500 ${
                  p?.phase === "uploading" && p.item_total > 0 ? "" : "w-1/3 animate-pulse"
                }`}
                style={p?.phase === "uploading" && p.item_total > 0 ? { width: `${(100 * p.item_bytes) / p.item_total}%` } : undefined}
              />
            </div>
            <div className="text-xs text-slate-400 dark:text-slate-500">
              {p?.phase === "uploading"
                ? `${fmtBytes(p.item_bytes)} de ${fmtBytes(p.item_total)} enviados`
                : p?.phase === "packing"
                  ? `${fmtBytes(p.item_bytes)} lidos`
                  : ""}
            </div>
          </>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-slate-600 dark:text-slate-300">
              Pode fechar esta janela: os backups são feitos pelo <b>serviço do Windows</b> no horário agendado, mesmo sem
              ninguém logado{state.use_vss ? ", lendo de uma cópia de sombra (VSS) — arquivos abertos também entram" : ""}.
            </div>
            <Button onClick={runNow} loading={busy} disabled={!state.service_ok || !state.connected || state.items.length === 0}>
              Fazer backup agora
            </Button>
          </div>
        )}
      </Card>

      {last && (last.errors?.length ?? 0) > 0 && !state.running && (
        <Note tone={last.status === "failed" ? "error" : "warn"}>
          <div className="font-semibold">Problemas no último backup</div>
          <ul className="selectable mt-1 list-disc space-y-0.5 pl-5">
            {last.errors!.slice(0, 5).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          {last.errors!.length > 5 && (
            <button type="button" className="mt-1 font-semibold underline" onClick={() => go("history")}>
              ver todos no histórico
            </button>
          )}
        </Note>
      )}
    </div>
  );
}

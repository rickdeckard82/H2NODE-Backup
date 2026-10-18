import clsx from "clsx";
import { useEffect, useState } from "react";
import { backend, onProgress, onState } from "./backend";
import logoDark from "./logo-dark.svg";
import logoLight from "./logo-light.svg";
import HistoryPage from "./pages/HistoryPage";
import HomePage from "./pages/HomePage";
import ItemsPage from "./pages/ItemsPage";
import SchedulePage from "./pages/SchedulePage";
import ServerPage from "./pages/ServerPage";
import type { UIState } from "./types";
import { Badge, Spinner } from "./ui";

const TABS = [
  { id: "home", label: "Início" },
  { id: "items", label: "Pastas e arquivos" },
  { id: "schedule", label: "Agendamento" },
  { id: "server", label: "Servidor" },
  { id: "history", label: "Histórico" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function App() {
  const [state, setState] = useState<UIState | null>(null);
  const [tab, setTab] = useState<TabId>("home");

  useEffect(() => {
    backend.getState().then((s) => {
      setState(s);
      if (!s.connected) setTab("server");
    });
    const offState = onState(setState);
    const offProgress = onProgress((p) => setState((s) => (s ? { ...s, progress: p } : s)));
    return () => {
      offState();
      offProgress();
    };
  }, []);

  if (!state) {
    return (
      <div className="flex h-screen items-center justify-center text-brand-600">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900">
        <img src={logoLight} alt="" className="h-9 w-9 dark:hidden" />
        <img src={logoDark} alt="" className="hidden h-9 w-9 dark:block" />
        <div>
          <div className="text-lg font-bold leading-tight">Pulse Backup</div>
          <div className="text-xs text-slate-500 dark:text-slate-400">Cliente Windows · v{state.version}</div>
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm">
          {state.running && <Badge tone="amber">backup em andamento</Badge>}
          {state.connected ? (
            <Badge tone="green">conectado: {state.client_name}</Badge>
          ) : (
            <Badge tone="red">não conectado</Badge>
          )}
        </div>
      </header>

      <nav className="flex gap-1 border-b border-slate-200 bg-white px-4 dark:border-slate-800 dark:bg-slate-900">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={clsx(
              "-mb-px border-b-2 px-3 py-2.5 text-sm font-medium",
              tab === t.id
                ? "border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-300"
                : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-y-auto p-5">
        {tab === "home" && <HomePage state={state} go={setTab} />}
        {tab === "items" && <ItemsPage state={state} />}
        {tab === "schedule" && <SchedulePage state={state} />}
        {tab === "server" && <ServerPage state={state} />}
        {tab === "history" && <HistoryPage state={state} />}
      </main>
    </div>
  );
}

// Só no `npm run dev` fora do Wails (navegador comum): simula o Go para revisar a
// interface. Não entra no executável (import.meta.env.DEV é falso no build).
import type { UIState } from "./types";

type Listener = (...args: unknown[]) => void;

export function installDevMock() {
  const w = window as unknown as Record<string, unknown>;
  if (w.go) return;
  const listeners: Record<string, Listener[]> = {};
  const now = Date.now();
  const iso = (msAgo: number) => new Date(now - msAgo).toISOString();
  const params = new URLSearchParams(window.location.search);
  const state: UIState = {
    version: "0.1.0",
    connected: params.get("connected") !== "0",
    server_url: "https://backup.exemplo.com.br",
    client_id: "pc-financeiro",
    client_name: "PC Financeiro",
    fingerprint: "A59035F8C3016453280E7C103C28F5FB071A210B",
    items: [
      { path: "C:\\Users\\maria\\Documents", is_dir: true },
      { path: "D:\\Contabilidade\\2026", is_dir: true },
      { path: "C:\\Users\\maria\\Desktop\\senhas-banco.xlsx", is_dir: false },
    ],
    excludes: ["~$*", "*.tmp", "Thumbs.db", "desktop.ini"],
    schedule: { mode: "daily", time: "12:30", days: [1, 2, 3, 4, 5], interval_hours: 24, catch_up: true },
    work_dir: "C:\\Users\\maria\\AppData\\Local\\PulseBackup\\work",
    start_with_windows: true,
    running: params.get("running") === "1",
    progress:
      params.get("running") === "1"
        ? { phase: "uploading", item: "D:\\Contabilidade\\2026", index: 2, count: 3, item_bytes: 734003200, item_total: 1288490188 }
        : null,
    next_run: new Date(now + 3 * 3600_000).toISOString(),
    last_success: iso(20 * 3600_000),
    history: [
      {
        run_name: "20261017T153012Z-a1b2c3", started_at: iso(20.2 * 3600_000), finished_at: iso(20 * 3600_000),
        status: "partial", bytes: 2147483648,
        components: [
          { kind: "files", name: "C:\\Users\\maria\\Documents", size: 1073741824, plain_size: 1073741000, status: "warning", duration_s: 300,
            message: "1520 arquivos, 88 pastas — 1 não puderam ser lidos (em uso ou sem permissão): C:\\Users\\maria\\Documents\\Outlook\\maria.pst: o arquivo já está sendo usado por outro processo" },
          { kind: "files", name: "D:\\Contabilidade\\2026", size: 1073741824, plain_size: 1073741000, status: "ok", duration_s: 280, message: "320 arquivos, 12 pastas" },
          { kind: "file", name: "C:\\Users\\maria\\Desktop\\senhas-banco.xlsx", size: 0, plain_size: 0, status: "failed", duration_s: 0, message: "não encontrado" },
        ],
        errors: ["file C:\\Users\\maria\\Desktop\\senhas-banco.xlsx: não encontrado"],
      },
      { run_name: "20261016T153001Z-d4e5f6", started_at: iso(44.2 * 3600_000), finished_at: iso(44 * 3600_000), status: "success", bytes: 2100000000, components: [], errors: [] },
    ],
    log_path: "C:\\Users\\maria\\AppData\\Local\\PulseBackup\\logs\\pulse-backup.log",
  };
  const ok = () => Promise.resolve();
  w.go = {
    main: {
      App: {
        GetState: () => Promise.resolve(state),
        TestConnection: () => Promise.resolve({ client_id: "pc-financeiro", client_name: "PC Financeiro", fingerprint: state.fingerprint }),
        ConfirmConnection: ok, Disconnect: ok, ChooseFolder: ok, ChooseFiles: ok, RemoveItem: ok,
        SaveExcludes: ok, ChooseWorkDir: ok, SaveSchedule: ok, SetStartWithWindows: ok, OpenLog: ok,
        OpenConfigDir: ok, RunNow: () => Promise.reject("já existe um backup em andamento"), Cancel: ok, Quit: ok,
      },
    },
  };
  w.runtime = {
    EventsOnMultiple: (name: string, cb: Listener) => {
      (listeners[name] ??= []).push(cb);
      return () => (listeners[name] = listeners[name].filter((x) => x !== cb));
    },
  };
}

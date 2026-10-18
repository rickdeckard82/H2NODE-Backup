// Espelho dos tipos do Go (app.go / internal/engine / internal/config).

export interface Item {
  path: string;
  is_dir: boolean;
}

export interface Schedule {
  mode: "daily" | "interval" | "manual";
  time: string;
  days: number[] | null;
  interval_hours: number;
  catch_up: boolean;
}

export interface Progress {
  phase: "preparing" | "packing" | "uploading" | "closing" | "done";
  item: string;
  index: number;
  count: number;
  item_bytes: number;
  item_total: number;
}

export interface Component {
  kind: "files" | "file";
  name: string;
  file?: string;
  size: number;
  plain_size: number;
  status: "ok" | "warning" | "failed";
  message?: string;
  duration_s: number;
}

export interface RunResult {
  run_name: string;
  started_at: string;
  finished_at: string;
  status: "success" | "partial" | "failed" | "canceled";
  bytes: number;
  components: Component[] | null;
  errors: string[] | null;
}

export interface UIState {
  version: string;
  connected: boolean;
  server_url: string;
  client_id: string;
  client_name: string;
  fingerprint: string;
  items: Item[];
  excludes: string[];
  schedule: Schedule;
  work_dir: string;
  start_with_windows: boolean;
  running: boolean;
  progress: Progress | null;
  next_run: string;
  last_success: string;
  history: RunResult[];
  log_path: string;
}

export interface ConnectInfo {
  client_id: string;
  client_name: string;
  fingerprint: string;
}

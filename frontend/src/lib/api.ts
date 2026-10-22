const BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)pb_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Options = {
  method?: string;
  body?: unknown;
  raw?: boolean;
  form?: boolean;
  query?: Record<string, unknown>;
};

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

function buildUrl(path: string, query?: Record<string, unknown>): string {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function request<T>(path: string, opts: Options = {}, retry = true): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  // FormData: deixa o navegador definir o Content-Type (com boundary).
  if (opts.body !== undefined && !opts.form) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = csrfToken();

  const res = await fetch(buildUrl(path, opts.query), {
    method,
    credentials: "include",
    headers,
    body: opts.form
      ? (opts.body as BodyInit)
      : opts.body !== undefined
        ? JSON.stringify(opts.body)
        : undefined,
  });

  if (res.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await tryRefresh()) return request<T>(path, opts, false);
  }

  if (res.status === 204) return undefined as T;
  if (opts.raw) return (await res.blob()) as T;

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { detail?: string }).detail ?? `Erro ${res.status}`);
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string, query?: Record<string, unknown>) => request<T>(path, { query }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  put: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
  blob: (path: string, query?: Record<string, unknown>) =>
    request<Blob>(path, { query, raw: true }),
  upload: <T,>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form, form: true }),
  /** PUT com o arquivo como corpo (sem multipart). */
  putFile: <T,>(path: string, file: Blob) => request<T>(path, { method: "PUT", body: file, form: true }),
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

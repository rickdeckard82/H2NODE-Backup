export function fmtDate(v: string | null | undefined, tz?: string): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    ...(tz ? { timeZone: tz } : {}),
  });
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: i === 0 ? 0 : v < 10 ? 1 : 0 })} ${units[i]}`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}min${String(s).padStart(2, "0")}`;
}

/** "há 3 h", "há 2 dias" — para "último backup". */
export function fmtAgo(v: string | null | undefined): string {
  if (!v) return "nunca";
  const diff = (Date.now() - new Date(v).getTime()) / 1000;
  if (diff < 60) return "agora";
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`;
  const d = Math.floor(diff / 86400);
  return `há ${d} dia${d > 1 ? "s" : ""}`;
}

export function pct(part: number, total: number): string {
  if (!total) return "0%";
  return `${((part / total) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

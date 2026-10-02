/* Gráficos leves em SVG/flex puro — sem dependências (mesmo estilo do Pulse RADIUS).
 * Cores de status (ok/aviso/falha) sempre acompanhadas de legenda com rótulo e
 * valor — a cor nunca é a única pista. Texto sempre em tons neutros. */
import { useState, type ReactNode } from "react";
import { fmtBytes } from "../lib/format";

export const CHART_COLORS = [
  "#2b6cf6", // brand
  "#16a34a", // green
  "#f59e0b", // amber
  "#e11d48", // rose
  "#8b5cf6", // violet
  "#06b6d4", // cyan
];

export interface DailyPoint {
  date: string; // YYYY-MM-DD (fuso do usuário)
  ok: number;
  warning: number;
  failed: number;
  bytes: number;
}

export interface StoragePoint {
  date: string;
  used_bytes: number;
  free_bytes: number;
  backups_bytes: number;
}

function dayLabel(iso: string, opts: Intl.DateTimeFormatOptions = { day: "2-digit", month: "2-digit" }) {
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("pt-BR", { ...opts, timeZone: "UTC" });
}

function weekday(iso: string) {
  return dayLabel(iso, { weekday: "short", day: "2-digit", month: "2-digit" }).replace(".", "");
}

/** Mostra só alguns rótulos do eixo X quando há muitos dias. */
function tickEvery(n: number) {
  if (n <= 10) return 1;
  if (n <= 31) return 5;
  if (n <= 90) return 15;
  return 30;
}

function LegendItem({ color, label, value }: { color: string; label: string; value: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      {label} <b className="tabular-nums text-slate-800 dark:text-slate-100">{value}</b>
    </span>
  );
}

function Tooltip({ children, leftPct }: { children: ReactNode; leftPct: number }) {
  // Mantém o balão dentro do gráfico nas pontas.
  const clamped = Math.min(Math.max(leftPct, 12), 88);
  return (
    <div
      className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800"
      style={{ left: `${clamped}%` }}
    >
      {children}
    </div>
  );
}

/* ---------------- Execuções por dia (barras empilhadas) ---------------- */

export function RunsChart({ data }: { data: DailyPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.ok + d.warning + d.failed));
  const tot = data.reduce(
    (a, d) => ({ ok: a.ok + d.ok, warning: a.warning + d.warning, failed: a.failed + d.failed }),
    { ok: 0, warning: 0, failed: 0 },
  );
  const total = tot.ok + tot.warning + tot.failed;
  const every = tickEvery(data.length);
  const h = hover !== null ? data[hover] : null;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="font-semibold">Execuções por dia</h3>
        <span className="text-sm text-slate-500 dark:text-slate-400">
          {total
            ? `${(((tot.ok + tot.warning) / total) * 100).toFixed(0)}% concluídas · ${total} no período`
            : "nenhuma execução no período"}
        </span>
      </div>

      <div className="relative" onMouseLeave={() => setHover(null)}>
        {h && hover !== null && (
          <Tooltip leftPct={((hover + 0.5) / data.length) * 100}>
            <div className="mb-1 font-semibold capitalize text-slate-700 dark:text-slate-200">
              {weekday(h.date)}
            </div>
            <div className="space-y-0.5 text-slate-600 dark:text-slate-300">
              <LegendItem color="bg-emerald-500" label="Sucesso" value={h.ok} />
              <LegendItem color="bg-amber-500" label="Com aviso" value={h.warning} />
              <LegendItem color="bg-rose-500" label="Falha" value={h.failed} />
              <div className="pt-1 text-slate-400 dark:text-slate-500">{fmtBytes(h.bytes)} recebidos</div>
            </div>
          </Tooltip>
        )}
        <div className="flex h-44 items-end gap-[3px] border-b border-slate-200 dark:border-slate-800">
          {data.map((d, i) => {
            const n = d.ok + d.warning + d.failed;
            return (
              <div
                key={d.date}
                className="flex h-full flex-1 cursor-default flex-col items-center justify-end"
                onMouseEnter={() => setHover(i)}
              >
                <div
                  className={`flex w-full max-w-[36px] flex-col-reverse gap-[2px] overflow-hidden rounded-t transition-opacity ${
                    hover !== null && hover !== i ? "opacity-60" : ""
                  }`}
                  style={{ height: n ? `${Math.max((n / max) * 100, 3)}%` : "0%" }}
                >
                  {d.ok > 0 && <div className="w-full bg-emerald-500" style={{ flexGrow: d.ok }} />}
                  {d.warning > 0 && <div className="w-full bg-amber-500" style={{ flexGrow: d.warning }} />}
                  {d.failed > 0 && <div className="w-full bg-rose-500" style={{ flexGrow: d.failed }} />}
                </div>
                {n === 0 && <div className="h-[2px] w-full max-w-[36px] rounded bg-slate-100 dark:bg-slate-800" />}
              </div>
            );
          })}
        </div>
        <div className="mt-1.5 flex gap-[3px] text-[11px] text-slate-400 dark:text-slate-500">
          {data.map((d, i) => (
            <span key={d.date} className="flex-1 text-center">
              {(data.length - 1 - i) % every === 0 ? dayLabel(d.date) : ""}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
        <LegendItem color="bg-emerald-500" label="Sucesso" value={tot.ok} />
        <LegendItem color="bg-amber-500" label="Com aviso" value={tot.warning} />
        <LegendItem color="bg-rose-500" label="Falha" value={tot.failed} />
      </div>
    </div>
  );
}

/* ---------------- Área suave genérica (bytes ao longo do tempo) ---------------- */

function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return pts.length ? `M ${pts[0][0]} ${pts[0][1]}` : "";
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    const mx = (x0 + x1) / 2;
    d += ` C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`;
  }
  return d;
}

interface Series {
  label: string;
  color: string;     // hex (traço / área)
  dot: string;       // classe Tailwind da bolinha da legenda
  values: number[];
  area?: boolean;
}

function LineAreaChart({
  title,
  subtitle,
  dates,
  series,
  height = 120,
  id,
}: {
  title: string;
  subtitle: string;
  dates: string[];
  series: Series[];
  height?: number;
  id: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600;
  const H = height;
  const pad = 6;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const n = dates.length;
  const x = (i: number) => (n > 1 ? (i / (n - 1)) * W : W / 2);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  const every = tickEvery(n);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="font-semibold">{title}</h3>
        <span className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</span>
      </div>
      {n === 0 ? (
        <p className="py-8 text-center text-sm text-slate-400 dark:text-slate-500">Sem dados ainda</p>
      ) : (
        <div
          className="relative"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
            setHover(Math.min(Math.max(i, 0), n - 1));
          }}
        >
          {hover !== null && (
            <Tooltip leftPct={n > 1 ? (hover / (n - 1)) * 100 : 50}>
              <div className="mb-1 font-semibold capitalize text-slate-700 dark:text-slate-200">
                {weekday(dates[hover])}
              </div>
              <div className="space-y-0.5 text-slate-600 dark:text-slate-300">
                {series.map((s) => (
                  <LegendItem key={s.label} color={s.dot} label={s.label} value={fmtBytes(s.values[hover])} />
                ))}
              </div>
            </Tooltip>
          )}
          <svg
            viewBox={`0 0 ${W} ${H}`}
            width="100%"
            height={H}
            preserveAspectRatio="none"
            role="img"
            aria-label={title}
            className="overflow-visible"
          >
            <defs>
              {series.map((s, si) => (
                <linearGradient key={si} id={`${id}-g${si}`} x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity="0.30" />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                </linearGradient>
              ))}
            </defs>
            <line x1={0} x2={W} y1={H - 0.5} y2={H - 0.5} className="stroke-slate-200 dark:stroke-slate-800" />
            {series.map((s, si) => {
              const pts = s.values.map((v, i) => [x(i), y(v)] as [number, number]);
              const line = smoothPath(pts);
              return (
                <g key={si}>
                  {s.area && n > 1 && <path d={`${line} L ${W} ${H} L 0 ${H} Z`} fill={`url(#${id}-g${si})`} />}
                  <path
                    d={line}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={2}
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              );
            })}
            {hover !== null && (
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={0}
                y2={H}
                className="stroke-slate-300 dark:stroke-slate-600"
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
            )}
          </svg>
          {hover !== null &&
            series.map((s) => (
              <span
                key={s.label}
                className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white dark:border-slate-900"
                style={{
                  left: `${n > 1 ? (hover / (n - 1)) * 100 : 50}%`,
                  top: `${(y(s.values[hover]) / H) * 100}%`,
                  backgroundColor: s.color,
                }}
              />
            ))}
          <div className="mt-1.5 flex justify-between text-[11px] text-slate-400 dark:text-slate-500">
            {dates.map((d, i) =>
              (n - 1 - i) % every === 0 || i === 0 ? (
                <span key={d} className={i === n - 1 ? "font-semibold" : ""}>
                  {dayLabel(d)}
                </span>
              ) : null,
            )}
          </div>
        </div>
      )}
      {series.length > 1 && (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
          {series.map((s) => (
            <LegendItem key={s.label} color={s.dot} label={s.label} value={fmtBytes(s.values[s.values.length - 1] ?? 0)} />
          ))}
        </div>
      )}
    </div>
  );
}

export function VolumeChart({ data }: { data: DailyPoint[] }) {
  const total = data.reduce((s, d) => s + d.bytes, 0);
  const peak = Math.max(0, ...data.map((d) => d.bytes));
  return (
    <LineAreaChart
      id="vol"
      title="Volume recebido por dia"
      subtitle={total ? `${fmtBytes(total)} no período · pico ${fmtBytes(peak)}` : "nada recebido"}
      dates={data.map((d) => d.date)}
      series={[{ label: "Recebido", color: CHART_COLORS[0], dot: "bg-brand-500", values: data.map((d) => d.bytes), area: true }]}
    />
  );
}

export function StorageTrendChart({ data }: { data: StoragePoint[] }) {
  const last = data[data.length - 1];
  const first = data[0];
  const growth = last && first ? last.backups_bytes - first.backups_bytes : 0;
  return (
    <LineAreaChart
      id="stor"
      title="Crescimento do armazenamento"
      subtitle={
        last
          ? `backups ${growth >= 0 ? "+" : "−"}${fmtBytes(Math.abs(growth))} no período`
          : "aguardando a primeira medição do worker"
      }
      dates={data.map((d) => d.date)}
      series={[
        { label: "Disco usado (total)", color: "#94a3b8", dot: "bg-slate-400", values: data.map((d) => d.used_bytes) },
        { label: "Backups", color: CHART_COLORS[0], dot: "bg-brand-500", values: data.map((d) => d.backups_bytes), area: true },
      ]}
    />
  );
}

/* ---------------- Disco: rosca usado (backups/outros) x livre ---------------- */

export function DiskDonut({
  total,
  used,
  free,
  backups,
  size = 168,
  thickness = 22,
}: {
  total: number;
  used: number;
  free: number;
  backups: number;
  size?: number;
  thickness?: number;
}) {
  const other = Math.max(used - backups, 0);
  const segs = [
    { label: "Backups", value: Math.min(backups, used || backups), color: CHART_COLORS[0], dot: "bg-brand-500" },
    { label: "Outros arquivos", value: other, color: "#94a3b8", dot: "bg-slate-400" },
    { label: "Livre", value: free, color: "transparent", dot: "bg-slate-200 dark:bg-slate-700" },
  ];
  const sum = segs.reduce((s, x) => s + x.value, 0) || 1;
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const usedPct = total ? (used / total) * 100 : 0;
  let acc = 0;

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0" role="img" aria-label="Uso do disco de backups">
        <circle cx={c} cy={c} r={r} fill="none" strokeWidth={thickness} className="stroke-slate-100 dark:stroke-slate-800" />
        <g transform={`rotate(-90 ${c} ${c})`}>
          {segs.slice(0, 2).map((s, i) => {
            const len = (s.value / sum) * circ;
            const el =
              len > 0 ? (
                <circle
                  key={i}
                  cx={c}
                  cy={c}
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={thickness}
                  strokeDasharray={`${Math.max(len - 1.5, 0.001)} ${circ}`}
                  strokeDashoffset={-acc}
                >
                  <title>{`${s.label}: ${fmtBytes(s.value)}`}</title>
                </circle>
              ) : null;
            acc += len;
            return el;
          })}
        </g>
        <text x="50%" y="48%" textAnchor="middle" className="fill-slate-900 dark:fill-slate-100" style={{ fontSize: size * 0.15, fontWeight: 700 }}>
          {usedPct.toFixed(0)}%
        </text>
        <text x="50%" y="62%" textAnchor="middle" className="fill-slate-400 dark:fill-slate-500" style={{ fontSize: size * 0.065, letterSpacing: 1.2 }}>
          EM USO
        </text>
      </svg>
      <ul className="w-full min-w-0 space-y-2 text-sm">
        {segs.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span className={`h-3 w-3 shrink-0 rounded-full ${s.dot}`} />
            <span className="truncate font-medium text-slate-700 dark:text-slate-200">{s.label}</span>
            <span className="ml-auto shrink-0 tabular-nums text-slate-500 dark:text-slate-400">
              {fmtBytes(s.value)} · {total ? ((s.value / total) * 100).toFixed(0) : 0}%
            </span>
          </li>
        ))}
        <li className="flex items-center gap-2 border-t border-slate-100 pt-2 text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <span className="h-3 w-3 shrink-0" />
          Capacidade total
          <span className="ml-auto tabular-nums">{fmtBytes(total)}</span>
        </li>
      </ul>
    </div>
  );
}

/* ---------------- Barras horizontais (ranking) ---------------- */

export function HBarList({
  items,
  format = fmtBytes,
  empty = "Sem dados",
}: {
  items: { label: string; sub?: string; value: number }[];
  format?: (n: number) => string;
  empty?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <p className="text-sm text-slate-400 dark:text-slate-500">{empty}</p>;
  return (
    <ul className="space-y-3">
      {items.map((it) => (
        <li key={it.label} title={`${it.label}: ${format(it.value)}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate font-medium text-slate-700 dark:text-slate-200">
              {it.label}
              {it.sub && <span className="ml-1.5 font-mono text-xs text-slate-400 dark:text-slate-500">{it.sub}</span>}
            </span>
            <span className="shrink-0 tabular-nums text-slate-500 dark:text-slate-400">{format(it.value)}</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max((it.value / max) * 100, 1.5)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ---------------- Barra empilhada única (proporções) ---------------- */

export function StackBar({
  title,
  parts,
}: {
  title: string;
  parts: { label: string; value: number; color: string }[];
}) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="font-semibold">{title}</h3>
        <span className="text-sm text-slate-500 dark:text-slate-400">{total} backup(s) guardado(s)</span>
      </div>
      <div className="flex h-8 w-full gap-[2px] overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
        {total > 0 &&
          parts
            .filter((p) => p.value > 0)
            .map((p) => (
              <div
                key={p.label}
                className={`flex items-center justify-center text-xs font-semibold text-white transition-[width] duration-500 ${p.color}`}
                style={{ width: `${(p.value / total) * 100}%` }}
                title={`${p.label}: ${p.value}`}
              >
                {(p.value / total) * 100 >= 10 && <span className="tabular-nums">{p.value}</span>}
              </div>
            ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
        {parts.map((p) => (
          <LegendItem key={p.label} color={p.color} label={p.label} value={p.value} />
        ))}
      </div>
    </div>
  );
}

import clsx from "clsx";
import { createContext, useCallback, useContext, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

// Mesmos componentes do painel (frontend/src/components/ui.tsx), reduzidos.

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("card p-4", className)}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-400 dark:text-slate-500">{hint}</span>}
    </label>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={clsx("animate-spin", className)} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function Button({
  variant = "primary",
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger"; loading?: boolean }) {
  const cls = { primary: "btn-primary", ghost: "btn-ghost", danger: "btn-danger" }[variant];
  return (
    <button type="button" className={clsx(cls, className)} disabled={loading || props.disabled} {...props}>
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export type Tone = "slate" | "green" | "red" | "amber" | "blue";

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: Tone }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
    red: "bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
    blue: "bg-brand-100 text-brand-800 dark:bg-brand-500/15 dark:text-brand-300",
  };
  return <span className={clsx("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export const RUN_STATUS: Record<string, [string, Tone]> = {
  success: ["sucesso", "green"],
  partial: ["parcial", "amber"],
  failed: ["falhou", "red"],
  canceled: ["cancelado", "slate"],
};

export function RunBadge({ status }: { status: string }) {
  const [label, tone] = RUN_STATUS[status] ?? [status, "slate"];
  return <Badge tone={tone}>{label}</Badge>;
}

export function Note({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  const cls = {
    info: "border-brand-200 bg-brand-50 text-slate-700 dark:border-brand-500/20 dark:bg-brand-500/10 dark:text-slate-300",
    warn: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300",
    error: "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300",
  }[tone];
  return <div className={clsx("rounded-lg border px-3 py-2 text-sm", cls)}>{children}</div>;
}

/* ---------------- Toasts ---------------- */

type Toast = { id: number; kind: "ok" | "err"; msg: string };
const ToastCtx = createContext<(kind: Toast["kind"], msg: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], msg: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex max-w-md flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "rounded-lg px-4 py-2.5 text-sm text-white shadow-lg",
              t.kind === "ok" ? "bg-emerald-600" : "bg-rose-600",
            )}
          >
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

import type { ReactNode } from "react";

export function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white dark:bg-brand-500">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-2 text-sm">
        <div className="font-semibold">{title}</div>
        {children}
      </div>
    </div>
  );
}

export function Note({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  const cls =
    tone === "warn"
      ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
      : "bg-brand-500/10 text-slate-700 dark:text-slate-300";
  return <p className={`rounded-lg p-2.5 text-xs leading-relaxed ${cls}`}>{children}</p>;
}

export function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs dark:bg-slate-800">{children}</code>;
}

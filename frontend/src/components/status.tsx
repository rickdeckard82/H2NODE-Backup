import { Badge } from "./ui";
import type { BackupStatus, Health, VerifyStatus } from "../lib/types";

type Tone = "slate" | "green" | "red" | "amber" | "blue";

const BACKUP: Record<BackupStatus, [string, Tone]> = {
  ok: ["sucesso", "green"],
  warning: ["com aviso", "amber"],
  failed: ["falhou", "red"],
  corrupted: ["corrompido", "red"],
};

const VERIFY: Record<VerifyStatus, [string, Tone]> = {
  pending: ["na fila", "slate"],
  running: ["verificando…", "blue"],
  ok: ["verificado", "green"],
  failed: ["reprovado", "red"],
  skipped: ["não verificado", "slate"],
};

const HEALTH: Record<Health, [string, Tone]> = {
  ok: ["em dia", "green"],
  warning: ["com aviso", "amber"],
  failed: ["falhando", "red"],
  overdue: ["atrasado", "red"],
  never: ["sem backup", "amber"],
  inactive: ["inativo", "slate"],
};

export function BackupStatusBadge({ status }: { status: BackupStatus }) {
  const [label, tone] = BACKUP[status] ?? [status, "slate"];
  return <Badge tone={tone}>{label}</Badge>;
}

export function VerifyBadge({ status, mode }: { status: VerifyStatus; mode?: string | null }) {
  const [label, tone] = VERIFY[status] ?? [status, "slate"];
  const suffix = status === "ok" && mode === "integrity" ? " (integridade)" : "";
  return <Badge tone={tone}>{label + suffix}</Badge>;
}

export function HealthBadge({ health }: { health: Health }) {
  const [label, tone] = HEALTH[health] ?? [health, "slate"];
  return <Badge tone={tone}>{label}</Badge>;
}

export function ComponentStatusBadge({ status }: { status: string | null }) {
  if (status === "ok") return <Badge tone="green">ok</Badge>;
  if (status === "warning") return <Badge tone="amber">aviso</Badge>;
  if (status === "failed") return <Badge tone="red">falhou</Badge>;
  if (status === "skipped") return <Badge>—</Badge>;
  return <Badge>pendente</Badge>;
}

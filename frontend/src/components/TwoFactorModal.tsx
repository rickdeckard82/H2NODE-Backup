import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button, Field, Modal, useToast } from "./ui";

interface SetupOut {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

interface RecoveryOut {
  recovery_codes: string[];
}

type Step = "status" | "setup" | "recovery" | "regenerate" | "disable";

function RecoveryCodes({ codes }: { codes: string[] }) {
  const toast = useToast();
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Guarde estes códigos de recuperação num lugar seguro. Cada um funciona uma única vez e serve para entrar ou desativar o 2FA se você perder o aplicativo autenticador.
      </p>
      <div className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-center font-mono text-sm dark:border-slate-800 dark:bg-slate-800/50">
        {codes.map((c) => (
          <span key={c} className="tracking-wider">
            {c}
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            navigator.clipboard
              .writeText(codes.join("\n"))
              .then(() => toast("ok", "Códigos copiados"))
              .catch(() => toast("err", "Não foi possível copiar"));
          }}
        >
          Copiar
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            const blob = new Blob([codes.join("\n") + "\n"], { type: "text/plain" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "h2node-backup-codigos-recuperacao.txt";
            a.click();
            URL.revokeObjectURL(a.href);
          }}
        >
          Baixar .txt
        </Button>
      </div>
    </div>
  );
}

export function TwoFactorModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [step, setStep] = useState<Step>("status");
  const [setup, setSetup] = useState<SetupOut | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setStep("status");
    setSetup(null);
    setRecoveryCodes(null);
    setCode("");
    setPassword("");
    setError(null);
  }

  function close() {
    reset();
    onClose();
  }

  const startSetup = useMutation({
    mutationFn: () => api.post<SetupOut>("/auth/mfa/setup"),
    onSuccess: (res) => {
      setSetup(res);
      setStep("setup");
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao iniciar o 2FA"),
  });

  const confirmEnable = useMutation({
    mutationFn: () => api.post<{ detail: string } & RecoveryOut>("/auth/mfa/enable", { code }),
    onSuccess: async (res) => {
      toast("ok", "2FA ativado");
      await refresh();
      setRecoveryCodes(res.recovery_codes);
      setCode("");
      setPassword("");
      setError(null);
      setStep("recovery");
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Código inválido"),
  });

  const regenerate = useMutation({
    mutationFn: () =>
      api.post<RecoveryOut>("/auth/mfa/recovery-codes/regenerate", { password, code }),
    onSuccess: (res) => {
      toast("ok", "Novos códigos gerados");
      setRecoveryCodes(res.recovery_codes);
      setCode("");
      setPassword("");
      setError(null);
      setStep("recovery");
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Senha ou código inválido"),
  });

  const forgetDevices = useMutation({
    mutationFn: () => api.post<{ detail: string }>("/auth/mfa/trusted-devices/forget"),
    onSuccess: (r) => toast("ok", r.detail),
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao esquecer os dispositivos"),
  });

  const confirmDisable = useMutation({
    mutationFn: () => api.post("/auth/mfa/disable", { password, code }),
    onSuccess: async () => {
      toast("ok", "2FA desativado");
      await refresh();
      close();
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Senha ou código inválido"),
  });

  function submit(fn: () => void) {
    return (e: FormEvent) => {
      e.preventDefault();
      setError(null);
      fn();
    };
  }

  const remaining = user?.mfa_recovery_codes_remaining ?? 0;

  return (
    <Modal open={open} onClose={close} title="Autenticação em duas etapas (2FA)">
      {step === "status" && (
        <div className="space-y-4">
          {user?.mfa_enabled ? (
            <>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                O 2FA está ativo na sua conta.
              </p>
              <div className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-600 dark:text-slate-300">
                    Códigos de recuperação restantes:{" "}
                    <strong className={remaining <= 2 ? "text-red-600 dark:text-red-400" : ""}>
                      {remaining}
                    </strong>
                  </span>
                  <Button variant="ghost" onClick={() => setStep("regenerate")}>
                    Gerar novos
                  </Button>
                </div>
                {remaining <= 2 && (
                  <p className="mt-2 text-xs text-red-600 dark:text-red-400">
                    Você está quase sem códigos — gere um lote novo e guarde-o.
                  </p>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-600 dark:text-slate-300">
                    Dispositivos lembrados no login (sem pedir o código)
                  </span>
                  <Button
                    variant="ghost"
                    loading={forgetDevices.isPending}
                    onClick={() => {
                      if (confirm("Esquecer todos os dispositivos lembrados? O próximo login em cada um pedirá o código."))
                        forgetDevices.mutate();
                    }}
                  >
                    Esquecer todos
                  </Button>
                </div>
                <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
                  Trocar a senha ou desativar o 2FA também os esquece.
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={close}>
                  Fechar
                </Button>
                <Button variant="danger" onClick={() => setStep("disable")}>
                  Desativar 2FA
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                O 2FA está desativado. Ative para exigir um código do seu aplicativo autenticador (Google Authenticator, Authy, 1Password…) a cada login.
              </p>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={close}>
                  Fechar
                </Button>
                <Button loading={startSetup.isPending} onClick={() => startSetup.mutate()}>
                  Ativar 2FA
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {step === "setup" && setup && (
        <form className="space-y-4" onSubmit={submit(() => confirmEnable.mutate())}>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            No seu aplicativo autenticador, escaneie o QR code abaixo — ou adicione a conta manualmente com esta chave ("chave baseada em tempo"):
          </p>
          <div className="flex justify-center">
            <img
              src={setup.qr_svg}
              alt="QR code para configurar o 2FA no aplicativo autenticador"
              className="h-48 w-48 rounded-lg border border-slate-200 bg-white p-2 dark:border-slate-700"
            />
          </div>
          <div className="break-all rounded-lg border border-slate-200 bg-slate-50 p-3 text-center font-mono text-sm tracking-wider dark:border-slate-800 dark:bg-slate-800/50">
            {setup.secret}
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            Alguns apps aceitam colar o link diretamente:{" "}
            <span className="break-all font-mono">{setup.otpauth_uri}</span>
          </p>
          <Field label="Código gerado pelo app" error={error ?? undefined}>
            <input
              className="input text-center font-mono text-lg tracking-widest"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              required
              autoFocus
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={close}>
              Cancelar
            </Button>
            <Button type="submit" loading={confirmEnable.isPending} disabled={code.length !== 6}>
              Confirmar e ativar
            </Button>
          </div>
        </form>
      )}

      {step === "recovery" && recoveryCodes && (
        <div className="space-y-4">
          <RecoveryCodes codes={recoveryCodes} />
          <div className="flex justify-end">
            <Button onClick={close}>Já guardei os códigos</Button>
          </div>
        </div>
      )}

      {step === "regenerate" && (
        <form className="space-y-3" onSubmit={submit(() => regenerate.mutate())}>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Confirme sua senha e um código atual (do autenticador ou um código de recuperação ainda válido). Os códigos anteriores deixam de funcionar.
          </p>
          <Field label="Senha atual">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
            />
          </Field>
          <Field label="Código do autenticador ou de recuperação" error={error ?? undefined}>
            <input
              className="input text-center font-mono text-lg tracking-widest"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={() => setStep("status")}>
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={regenerate.isPending}
              disabled={code.trim().length < 6 || !password}
            >
              Gerar novos códigos
            </Button>
          </div>
        </form>
      )}

      {step === "disable" && (
        <form className="space-y-3" onSubmit={submit(() => confirmDisable.mutate())}>
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Confirme sua senha e um código para desativar o 2FA — pode ser o código atual do autenticador ou um dos seus códigos de recuperação.
          </p>
          <Field label="Senha atual">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
            />
          </Field>
          <Field label="Código do autenticador ou de recuperação" error={error ?? undefined}>
            <input
              className="input text-center font-mono text-lg tracking-widest"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={close}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="danger"
              loading={confirmDisable.isPending}
              disabled={code.trim().length < 6 || !password}
            >
              Desativar 2FA
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

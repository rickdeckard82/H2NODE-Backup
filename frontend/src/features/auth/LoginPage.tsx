import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { AppFooter } from "../../components/AppFooter";
import { Logo } from "../../components/Logo";
import { Waves } from "../../components/Waves";
import { Button, Field } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function LoginPage() {
  const { user, loading, login, verifyMfa } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [rememberDays, setRememberDays] = useState(0);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  async function onSubmitPassword(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await login(username.trim(), password);
      if (res.mfaRequired && res.mfaToken) {
        setMfaToken(res.mfaToken);
        setRememberDays(res.rememberDays ?? 0);
      } else {
        navigate("/", { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Falha ao entrar");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitCode(e: FormEvent) {
    e.preventDefault();
    if (!mfaToken) return;
    setBusy(true);
    setError(null);
    try {
      await verifyMfa(mfaToken, code, remember);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Código inválido");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-slate-100 dark:bg-slate-950">
      <Waves variant="screen" />

      <div className="relative z-10 flex flex-1 items-center justify-center p-4">
        {mfaToken ? (
          <form onSubmit={onSubmitCode} className="card w-full max-w-sm p-6">
            <div className="mb-6 flex flex-col items-center gap-3">
              <Logo className="h-20 w-20" />
              <div className="text-xl font-bold">Pulse Backup</div>
            </div>
            <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
              {useRecovery
                ? "Digite um dos seus códigos de recuperação (uso único)."
                : "Digite o código de 6 dígitos do seu aplicativo autenticador."}
            </p>
            <Field
              label={useRecovery ? "Código de recuperação" : "Código de verificação"}
              error={error ?? undefined}
            >
              <input
                className="input text-center font-mono text-lg tracking-widest"
                inputMode={useRecovery ? "text" : "numeric"}
                autoComplete="one-time-code"
                maxLength={useRecovery ? 13 : 6}
                value={code}
                onChange={(e) =>
                  setCode(useRecovery ? e.target.value.toUpperCase() : e.target.value.replace(/\D/g, ""))
                }
                required
                autoFocus
              />
            </Field>
            {rememberDays > 0 && (
              <label className="mt-3 flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                <span>
                  Lembrar este dispositivo por {rememberDays} dias
                  <span className="block text-xs text-slate-400 dark:text-slate-500">
                    Neste navegador a senha continua sendo pedida, mas o código não. Não marque em computador compartilhado.
                  </span>
                </span>
              </label>
            )}
            <Button
              type="submit"
              className="mt-4 w-full"
              loading={busy}
              disabled={useRecovery ? code.trim().length < 6 : code.length !== 6}
            >
              Verificar
            </Button>
            <button
              type="button"
              className="mt-3 w-full text-center text-sm text-slate-500 hover:underline dark:text-slate-400"
              onClick={() => {
                setUseRecovery((v) => !v);
                setCode("");
                setError(null);
              }}
            >
              {useRecovery ? "Usar o código do autenticador" : "Usar um código de recuperação"}
            </button>
            <button
              type="button"
              className="mt-2 w-full text-center text-sm text-slate-500 hover:underline dark:text-slate-400"
              onClick={() => {
                setMfaToken(null);
                setCode("");
                setError(null);
                setUseRecovery(false);
              }}
            >
              Voltar
            </button>
          </form>
        ) : (
          <form onSubmit={onSubmitPassword} className="card w-full max-w-sm p-6">
            <div className="mb-6 flex flex-col items-center gap-3">
              <Logo className="h-20 w-20" />
              <div className="text-xl font-bold">Pulse Backup</div>
              <p className="text-center text-sm text-slate-500 dark:text-slate-400">Gestão de backups cifrados</p>
            </div>

            <div className="space-y-3">
              <Field label="Usuário">
                <input
                  className="input"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                />
              </Field>
              <Field label="Senha" error={error ?? undefined}>
                <input
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
            </div>

            <Button type="submit" className="mt-5 w-full" loading={busy}>
              Entrar
            </Button>
          </form>
        )}
      </div>

      <AppFooter className="relative z-10 px-4 py-4 text-center" />
    </div>
  );
}

import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ROLE_LABEL, useAuth } from "../lib/auth";
import { Logo } from "./Logo";
import { TwoFactorModal } from "./TwoFactorModal";
import { Button, Card } from "./ui";

/** Papel que exige 2FA (MFA_REQUIRED_ROLES) e a conta ainda não ativou: o servidor recusa
 * o resto do painel, então aqui só dá para ativar o 2FA ou sair. */
export function MfaGate({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  if (!user?.mfa_setup_required) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4 p-6 text-sm">
        <div className="flex items-center gap-3">
          <Logo className="h-10 w-10" />
          <div className="text-lg font-bold">Ative a autenticação em duas etapas</div>
        </div>
        <p className="text-slate-600 dark:text-slate-300">
          Contas com papel <b>{ROLE_LABEL[user.role].toLowerCase()}</b> só usam o painel com 2FA ativo. Use um aplicativo
          autenticador (Google Authenticator, Microsoft Authenticator, Aegis, 1Password…) para ler o QR code e guarde os códigos
          de recuperação em lugar seguro.
        </p>
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
          >
            Sair
          </Button>
          <Button onClick={() => setOpen(true)}>Ativar 2FA agora</Button>
        </div>
      </Card>
      <TwoFactorModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

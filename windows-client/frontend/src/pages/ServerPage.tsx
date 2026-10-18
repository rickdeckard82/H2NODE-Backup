import { useState } from "react";
import { AdminBanner } from "../AdminBanner";
import { backend } from "../backend";
import { errText } from "../format";
import type { ConnectInfo, UIState } from "../types";
import { Button, Card, Field, Note, useToast } from "../ui";

function fmtFpr(fp: string) {
  return fp.replace(/(.{4})/g, "$1 ").trim();
}

export default function ServerPage({ state }: { state: UIState }) {
  const toast = useToast();
  const [url, setUrl] = useState(state.server_url || "https://");
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<ConnectInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = !state.admin;

  async function test() {
    setBusy(true);
    setInfo(null);
    try {
      setInfo(await backend.testConnection(url.trim(), token.trim()));
    } catch (e) {
      toast("err", errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      await backend.confirmConnection();
      toast("ok", "Conectado ao servidor");
      setToken("");
      setInfo(null);
    } catch (e) {
      toast("err", errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (state.connected) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <AdminBanner state={state} />
        <Card className="space-y-3 p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="label">Servidor</div>
              <div className="selectable font-mono text-sm">{state.server_url}</div>
            </div>
            <div>
              <div className="label">Cadastro no painel</div>
              <div className="text-sm">
                {state.client_name} <span className="font-mono text-xs text-slate-400">({state.client_id})</span>
              </div>
            </div>
          </div>
          <div>
            <div className="label">Chave GPG do servidor (fixada)</div>
            <div className="selectable break-all font-mono text-sm">{fmtFpr(state.fingerprint)}</div>
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              Os backups são cifrados para esta chave antes de sair do computador. Se o servidor trocar de chave, o backup
              para até você reconectar.
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              variant="danger"
              disabled={state.running || locked}
              onClick={async () => {
                if (!window.confirm("Desconectar? O token deste computador é apagado e os backups param.")) return;
                try {
                  await backend.disconnect();
                } catch (e) {
                  toast("err", errText(e));
                }
              }}
            >
              Desconectar
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <AdminBanner state={state} />
      <Card className="space-y-4 p-5">
        <div>
          <div className="font-semibold">Conectar ao Pulse Backup</div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No painel, em <b>Servidores</b>, cadastre este computador e clique em <b>Windows</b> → <b>Gerar token</b>. Cole
            aqui o endereço e o token mostrados.
          </p>
        </div>
        <Field label="Endereço do servidor">
          <input className="input font-mono" value={url} disabled={locked} onChange={(e) => setUrl(e.target.value)} placeholder="https://backup.suaempresa.com.br" />
        </Field>
        <Field label="Token" hint="Começa com pbu_. Fica guardado no serviço, protegido pelo Windows (DPAPI da conta do sistema).">
          <input
            className="input font-mono"
            disabled={locked}
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="pbu_…"
            autoComplete="off"
          />
        </Field>
        <div className="flex justify-end">
          <Button variant="ghost" onClick={test} loading={busy && !info} disabled={locked || !url.trim() || !token.trim()}>
            Testar conexão
          </Button>
        </div>

        {info && (
          <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
            <Note>
              Conectou como <b>{info.client_name}</b> <span className="font-mono">({info.client_id})</span>.
            </Note>
            <div>
              <div className="label">Impressão digital da chave GPG do servidor</div>
              <div className="selectable break-all font-mono text-base font-semibold">{fmtFpr(info.fingerprint)}</div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Confira com a mostrada no painel (Configuração → Chaves e servidor). Se for diferente, <b>não confirme</b>: os
                backups seriam cifrados para outra chave.
              </p>
            </div>
            <div className="flex justify-end">
              <Button onClick={confirm} loading={busy}>
                A chave confere — conectar
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

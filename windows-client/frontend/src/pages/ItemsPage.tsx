import { useEffect, useState } from "react";
import { backend } from "../backend";
import { errText } from "../format";
import type { UIState } from "../types";
import { Button, Card, Field, Note, useToast } from "../ui";

function FolderIcon() {
  return (
    <svg className="h-4 w-4 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg className="h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export default function ItemsPage({ state }: { state: UIState }) {
  const toast = useToast();
  const [excludes, setExcludes] = useState(state.excludes.join("\n"));
  const [savingEx, setSavingEx] = useState(false);
  const dirty = excludes.trim() !== state.excludes.join("\n").trim();

  useEffect(() => {
    if (!dirty) setExcludes(state.excludes.join("\n"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.excludes]);

  async function call(fn: () => Promise<void>) {
    try {
      await fn();
    } catch (e) {
      toast("err", errText(e));
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Card className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 p-4 dark:border-slate-800">
          <div>
            <div className="font-semibold">O que entra no backup</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">
              Pastas vão inteiras (com subpastas) num .tar.gz; arquivos vão como estão. Tudo é cifrado antes de sair do
              computador.
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => call(backend.chooseFiles)}>
              Adicionar arquivos
            </Button>
            <Button onClick={() => call(backend.chooseFolder)}>Adicionar pasta</Button>
          </div>
        </div>
        {state.items.length === 0 ? (
          <div className="p-4 text-sm text-slate-400 dark:text-slate-500">Nenhuma pasta ou arquivo escolhido.</div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {state.items.map((it) => (
              <li key={it.path} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                {it.is_dir ? <FolderIcon /> : <FileIcon />}
                <span className="selectable min-w-0 flex-1 truncate font-mono text-xs" title={it.path}>
                  {it.path}
                </span>
                <button
                  type="button"
                  className="text-rose-600 hover:underline disabled:opacity-40 dark:text-rose-400"
                  disabled={state.running}
                  onClick={() => call(() => backend.removeItem(it.path))}
                >
                  Remover
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="space-y-3">
        <Field
          label="Não incluir (um padrão por linha)"
          hint="Vale para nomes de arquivos e pastas dentro das pastas escolhidas. * = qualquer texto. Ex.: *.tmp, ~$* (temporários do Office), node_modules."
        >
          <textarea
            className="input h-32 font-mono text-xs"
            value={excludes}
            onChange={(e) => setExcludes(e.target.value)}
            spellCheck={false}
          />
        </Field>
        <div className="flex justify-end">
          <Button
            disabled={!dirty}
            loading={savingEx}
            onClick={async () => {
              setSavingEx(true);
              await call(async () => {
                await backend.saveExcludes(excludes.split(/\r?\n/));
                toast("ok", "Exclusões salvas");
              });
              setSavingEx(false);
            }}
          >
            Salvar exclusões
          </Button>
        </div>
      </Card>

      <Card className="space-y-2 text-sm">
        <div className="label">Pasta de trabalho</div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="selectable min-w-0 flex-1 truncate font-mono text-xs" title={state.work_dir}>
            {state.work_dir}
          </span>
          <Button variant="ghost" onClick={() => call(backend.chooseWorkDir)} disabled={state.running}>
            Trocar
          </Button>
        </div>
        <Note>
          Cada item é cifrado aqui, enviado e apagado antes do próximo: a pasta só precisa ter espaço para o <b>maior</b>{" "}
          item já compactado. Nada fica em claro nela.
        </Note>
        <p className="text-xs text-slate-400 dark:text-slate-500">
          Arquivos abertos e travados por outro programa (ex.: .pst do Outlook aberto) são pulados e aparecem como aviso no
          histórico. Feche o programa no horário do backup.
        </p>
      </Card>
    </div>
  );
}

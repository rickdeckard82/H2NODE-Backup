import { useEffect, useState } from "react";
import { Button, Field, Modal } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtBytes } from "../../lib/format";
import { decryptBackup, gunzip, PgpError, saveBlob } from "../../lib/pgp";

// Acima disso o navegador sofre (o arquivo inteiro fica na memória).
const WARN_BYTES = 512 * 1024 * 1024;

function readText(file: File): Promise<string> {
  return file.text();
}

export function DecryptDownloadModal({
  open,
  onClose,
  backupId,
  componentId,
  fileName,
  sizeBytes,
}: {
  open: boolean;
  onClose: () => void;
  backupId: number;
  componentId: number;
  fileName: string;
  sizeBytes: number;
}) {
  const plainName = fileName.replace(/\.gpg$/i, "");
  const isGz = /\.gz$/i.test(plainName);

  const [key, setKey] = useState("");
  const [pass, setPass] = useState("");
  const [unzip, setUnzip] = useState(/\.conf\.gz$/i.test(plainName));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nada da chave/senha sobrevive ao fechar a janela.
  useEffect(() => {
    if (!open) {
      setKey("");
      setPass("");
      setError(null);
      setBusy(false);
    }
  }, [open]);

  async function run() {
    setError(null);
    setBusy(true);
    try {
      // Garante um access token válido (o fetch abaixo não renova a sessão).
      await api.get("/auth/me").catch(() => undefined);
      const res = await fetch(`/api/backups/${backupId}/components/${componentId}/download`, {
        credentials: "include",
      });
      if (!res.ok) {
        const d = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new PgpError(d.detail ?? `Erro ${res.status} ao baixar o arquivo`);
      }
      const encrypted = new Uint8Array(await res.arrayBuffer());
      let data = await decryptBackup(encrypted, key, pass);
      let name = plainName;
      if (isGz && unzip) {
        try {
          data = await gunzip(data);
          name = plainName.replace(/\.gz$/i, "");
        } catch {
          throw new PgpError("Decifrado, mas o conteúdo não é um gzip válido. Desmarque “Descompactar”.");
        }
      }
      saveBlob(name, data);
      onClose();
    } catch (e) {
      setError(e instanceof PgpError ? e.message : "Erro inesperado ao decifrar");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={busy ? () => undefined : onClose} title="Baixar decifrado">
      <form
        className="space-y-4 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <p className="text-slate-500 dark:text-slate-400">
          Arquivo: <span className="font-mono text-xs break-all">{plainName}</span> ({fmtBytes(sizeBytes)} cifrado).
          A decifragem acontece <b>no seu navegador</b>: a chave privada e a senha não são enviadas ao
          servidor nem guardadas.
        </p>

        {sizeBytes > WARN_BYTES && (
          <p className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300">
            Arquivo grande: o navegador mantém tudo na memória. Para este tamanho prefira o gpg no terminal
            (docs/restore.md).
          </p>
        )}

        <Field label="Chave privada (.asc)">
          <textarea
            className="input h-28 font-mono text-xs"
            placeholder="-----BEGIN PGP PRIVATE KEY BLOCK-----"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            spellCheck={false}
            autoComplete="off"
          />
          <input
            type="file"
            accept=".asc,.key,.gpg,.txt"
            className="mt-1 block text-xs"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setKey(await readText(f));
            }}
          />
        </Field>

        <Field label="Senha da chave">
          <input
            type="password"
            className="input"
            value={pass}
            onChange={(e) => setPass(e.target.value)}
            autoComplete="off"
          />
          <input
            type="file"
            className="mt-1 block text-xs"
            title="Arquivo com a senha (ex.: backup-key.pass)"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setPass((await readText(f)).replace(/\r?\n$/, ""));
            }}
          />
        </Field>

        {isGz && (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={unzip} onChange={(e) => setUnzip(e.target.checked)} />
            Descompactar o .gz depois de decifrar
          </label>
        )}

        {error && <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button type="submit" loading={busy} disabled={!key.trim()}>
            Decifrar e baixar
          </Button>
        </div>
      </form>
    </Modal>
  );
}

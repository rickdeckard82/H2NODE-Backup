import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Modal, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import type { Client } from "../../lib/types";
import { CopyBlock } from "./ClientsPage";

interface UploadToken {
  token: string;
  hint: string;
  server_url: string;
  public_key_fingerprint: string | null;
}

/** Token do envio por HTTPS (cliente Windows): gerar, trocar e revogar. O token só aparece uma vez. */
export function WindowsTokenModal({ client, onClose }: { client: Client | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [issued, setIssued] = useState<UploadToken | null>(null);

  const close = () => {
    setIssued(null);
    onClose();
  };

  const generate = useMutation({
    mutationFn: (c: Client) => api.post<UploadToken>(`/clients/${c.id}/upload-token`),
    onSuccess: (t) => {
      setIssued(t);
      qc.invalidateQueries({ queryKey: ["clients"] });
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao gerar o token"),
  });

  const revoke = useMutation({
    mutationFn: (c: Client) => api.del(`/clients/${c.id}/upload-token`),
    onSuccess: () => {
      toast("ok", "Token revogado — o cliente Windows parou de enviar");
      qc.invalidateQueries({ queryKey: ["clients"] });
      close();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao revogar"),
  });

  const hasToken = !!client?.upload_token_hint;

  return (
    <Modal open={!!client} onClose={close} title={`Cliente Windows — ${client?.name ?? ""}`} wide>
      {client && (
        <div className="space-y-4 text-sm">
          <p className="text-slate-500 dark:text-slate-400">
            O cliente Windows envia por <b>HTTPS</b>, pelo endereço do painel, com um token próprio deste servidor. Os arquivos
            saem do Windows já cifrados com a chave pública; o token só consegue <b>enviar</b> (não lista, não baixa, não apaga).
            Passo a passo em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/windows" onClick={close}>
              Ajuda → Windows
            </Link>
            .
          </p>

          {issued ? (
            <>
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
                Copie o token agora: ele <b>não aparece de novo</b>. Se perder, gere outro (o anterior para de funcionar).
              </div>
              <CopyBlock label="Endereço do servidor" text={issued.server_url} />
              <CopyBlock label="Token" text={issued.token} />
              {issued.public_key_fingerprint ? (
                <p className="text-slate-500 dark:text-slate-400">
                  Ao conectar, o cliente mostra a impressão digital da chave GPG. Confira se é{" "}
                  <span className="break-all font-mono">{issued.public_key_fingerprint}</span>.
                </p>
              ) : (
                <p className="text-rose-600 dark:text-rose-400">
                  A chave pública GPG não está configurada no servidor: o cliente não conseguirá cifrar.
                </p>
              )}
            </>
          ) : (
            <p>
              {hasToken ? (
                <>
                  Token ativo terminando em <span className="font-mono">…{client.upload_token_hint}</span>.
                </>
              ) : (
                "Nenhum token: este servidor ainda não pode enviar por HTTPS."
              )}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2 pt-2">
            {hasToken && !issued && (
              <Button
                variant="danger"
                loading={revoke.isPending}
                onClick={() => {
                  if (confirm("Revogar o token? O cliente Windows para de enviar na hora.")) revoke.mutate(client);
                }}
              >
                Revogar
              </Button>
            )}
            {!issued && (
              <Button
                loading={generate.isPending}
                onClick={() => {
                  if (!hasToken || confirm("Gerar um token novo? O atual para de funcionar na hora.")) generate.mutate(client);
                }}
              >
                {hasToken ? "Gerar token novo" : "Gerar token"}
              </Button>
            )}
            <Button variant="ghost" onClick={close}>
              Fechar
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { fmtBytes } from "../lib/format";
import type { Client } from "../lib/types";
import { Button, Modal, useToast } from "./ui";

/** Exclusão de servidor/equipamento: com backups guardados, escolhe entre mantê-los
 *  (o cadastro é desativado: acesso revogado, backups seguem na tela de backups)
 *  ou apagar tudo do disco junto com o cadastro. */
export function DeleteClientModal({
  client,
  onClose,
  onDone,
}: {
  client: Client | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [confirmText, setConfirmText] = useState("");
  const close = () => {
    setConfirmText("");
    onClose();
  };
  const run = useMutation({
    mutationFn: ({ c, mode }: { c: Client; mode: "keep" | "purge" }) =>
      mode === "keep" && c.backup_count > 0
        ? api.patch(`/clients/${c.id}`, { is_active: false })
        : api.del(`/clients/${c.id}${mode === "purge" ? "?purge_backups=true" : ""}`),
    onSuccess: (_r, { c, mode }) => {
      toast(
        "ok",
        mode === "keep" && c.backup_count > 0
          ? `${c.name} desativado; backups mantidos`
          : mode === "purge" && c.backup_count > 0
            ? `${c.name} e ${c.backup_count} backup(s) apagados`
            : `${c.name} removido`,
      );
      close();
      onDone();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  if (!client) return null;
  const c = client;
  const has = c.backup_count > 0;

  return (
    <Modal open onClose={close} title={`Excluir ${c.name}`}>
      {!has ? (
        <>
          <p className="text-sm">
            Remove o cadastro e revoga o acesso na hora (chave SSH / IP liberado). Não há backups guardados.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={close}>Cancelar</Button>
            <Button variant="danger" loading={run.isPending} onClick={() => run.mutate({ c, mode: "purge" })}>
              Excluir
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm">
            Há <b>{c.backup_count} backup(s)</b> guardado(s) ({fmtBytes(c.stored_bytes)}). O que fazer com eles?
          </p>
          <div className="mt-4 space-y-3">
            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="font-medium">Manter os backups</div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                O cadastro fica desativado: o acesso é revogado e não chegam novos envios. Os backups continuam
                disponíveis para baixar e seguem a retenção.
              </p>
              <Button
                variant="ghost"
                className="mt-2"
                loading={run.isPending && run.variables?.mode === "keep"}
                disabled={run.isPending}
                onClick={() => run.mutate({ c, mode: "keep" })}
              >
                Desativar e manter backups
              </Button>
            </div>
            <div className="rounded-lg border border-rose-300 p-3 dark:border-rose-500/40">
              <div className="font-medium text-rose-700 dark:text-rose-300">Excluir tudo</div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Apaga do disco os {c.backup_count} backup(s), as pastas do cliente e o cadastro. Não tem volta.
                Digite <b>{c.slug}</b> para confirmar.
              </p>
              <input
                className="input mt-2"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={c.slug}
                aria-label="Confirmação"
              />
              <Button
                variant="danger"
                className="mt-2"
                loading={run.isPending && run.variables?.mode === "purge"}
                disabled={run.isPending || confirmText !== c.slug}
                onClick={() => run.mutate({ c, mode: "purge" })}
              >
                Excluir cadastro e backups
              </Button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DecryptDownloadModal } from "./DecryptDownloadModal";
import { RefreshButton } from "../../components/RefreshButton";
import { BackupStatusBadge, ComponentStatusBadge, VerifyBadge } from "../../components/status";
import { Badge, Button, Card, Modal, PageHeader, Pagination, Spinner, useToast } from "../../components/ui";
import { api, ApiError, type Page } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtBytes, fmtDuration } from "../../lib/format";
import { KIND_LABEL, type Backup, type BackupDetail, type Client } from "../../lib/types";

function durationOf(b: Backup) {
  if (!b.started_at || !b.finished_at) return null;
  return Math.max(0, Math.round((new Date(b.finished_at).getTime() - new Date(b.started_at).getTime()) / 1000));
}

function BackupDetailModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["backup", id],
    queryFn: () => api.get<BackupDetail>(`/backups/${id}`),
    enabled: id !== null,
    refetchInterval: (query) =>
      query.state.data && ["pending", "running"].includes(query.state.data.verify_status) ? 3000 : false,
  });
  const b = q.data;

  const reverify = useMutation({
    mutationFn: () => api.post<{ detail: string }>(`/backups/${id}/verify`),
    onSuccess: (r) => {
      toast("ok", r.detail);
      qc.invalidateQueries({ queryKey: ["backup", id] });
      qc.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao agendar"),
  });

  const remove = useMutation({
    mutationFn: () => api.del(`/backups/${id}`),
    onSuccess: () => {
      toast("ok", "Backup excluído do armazenamento");
      qc.invalidateQueries({ queryKey: ["backups"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onClose();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao excluir"),
  });

  const [decrypting, setDecrypting] = useState<BackupDetail["components"][number] | null>(null);

  async function download(componentId: number) {
    // Garante um access token válido (o download é um GET direto do navegador,
    // fora do fetch que sabe renovar a sessão).
    await api.get("/auth/me").catch(() => undefined);
    const a = document.createElement("a");
    a.href = `/api/backups/${id}/components/${componentId}/download`;
    a.rel = "noopener";
    a.click();
  }

  const stored = b && !b.deleted_at;
  // Com um único arquivo (equipamentos de rede), Baixar/.gpg ficam no rodapé,
  // ao lado de Excluir; com vários, cada linha da tabela tem os seus links.
  const files = b?.components.filter((c) => c.file_name) ?? [];
  const single = files.length === 1 ? files[0] : null;

  return (
    <Modal open={id !== null} onClose={onClose} title={b ? `${b.client_name} — ${b.run_name}` : "Backup"} wide>
      {!b ? (
        <Spinner className="h-5 w-5 text-brand-600" />
      ) : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap gap-2">
            <BackupStatusBadge status={b.status} />
            <VerifyBadge status={b.verify_status} mode={b.verify_mode} />
            {b.deleted_at && <Badge>removido em {fmtDate(b.deleted_at)}</Badge>}
          </div>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            <div>
              <dt className="label">Início</dt>
              <dd>{fmtDate(b.started_at)}</dd>
            </div>
            <div>
              <dt className="label">Duração</dt>
              <dd>{fmtDuration(durationOf(b))}</dd>
            </div>
            <div>
              <dt className="label">Recebido</dt>
              <dd>{fmtDate(b.received_at)}</dd>
            </div>
            <div>
              <dt className="label">Verificado</dt>
              <dd>{fmtDate(b.verified_at)}</dd>
            </div>
            <div>
              <dt className="label">Tamanho cifrado</dt>
              <dd className="tabular-nums">{fmtBytes(b.size_bytes)}</dd>
            </div>
            <div>
              <dt className="label">Conteúdo (comprimido)</dt>
              <dd className="tabular-nums">{fmtBytes(b.plain_size_bytes)}</dd>
            </div>
            <div>
              <dt className="label">Host</dt>
              <dd className="truncate">{b.hostname ?? "—"}</dd>
            </div>
            <div>
              <dt className="label">Agente</dt>
              <dd>{b.agent_version ? `v${b.agent_version}` : "—"}</dd>
            </div>
          </dl>

          {b.verify_message && (
            <div
              className={`rounded-lg border px-3 py-2 ${
                b.verify_status === "failed"
                  ? "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300"
                  : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-300"
              }`}
            >
              <b>Verificação:</b> {b.verify_message}
            </div>
          )}
          {(b.errors.length > 0 || b.error_message) && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
              <b>Erros reportados:</b>
              <ul className="mt-1 list-disc pl-5">
                {(b.errors.length ? b.errors : [b.error_message!]).map((e, i) => (
                  <li key={i} className="break-words">
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
              <thead className="bg-slate-50 dark:bg-slate-800/50">
                <tr>
                  <th className="th">Componente</th>
                  <th className="th">No cliente</th>
                  <th className="th">Verificação</th>
                  <th className="th">Tamanho</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {b.components.map((c) => (
                  <tr key={c.id} className="align-top">
                    <td className="td whitespace-normal">
                      <div className="font-medium">{c.name}</div>
                      <div className="text-xs text-slate-400 dark:text-slate-500">
                        {KIND_LABEL[c.kind]} · {fmtDuration(c.duration_seconds)}
                      </div>
                      {c.message && (
                        <div className="mt-1 max-w-md break-words text-xs text-slate-500 dark:text-slate-400">
                          {c.message}
                        </div>
                      )}
                    </td>
                    <td className="td">
                      <ComponentStatusBadge status={c.status} />
                    </td>
                    <td className="td whitespace-normal">
                      <ComponentStatusBadge status={c.verify_status} />
                      {c.verify_message && (
                        <div className="mt-1 max-w-xs break-words text-xs text-slate-500 dark:text-slate-400">
                          {c.verify_message}
                        </div>
                      )}
                    </td>
                    <td className="td tabular-nums">
                      {c.file_name ? fmtBytes(c.size_bytes) : "—"}
                      {c.item_count != null && (
                        <div className="text-xs text-slate-400 dark:text-slate-500">
                          {c.item_count.toLocaleString("pt-BR")} itens
                        </div>
                      )}
                    </td>
                    <td className="td text-right">
                      {stored && !single && c.file_name && can("admin") && (
                        <span className="space-x-3 whitespace-nowrap">
                          <button
                            className="text-brand-600 hover:underline dark:text-brand-400"
                            title="Pede a chave privada e baixa o arquivo já decifrado"
                            onClick={() => setDecrypting(c)}
                          >
                            Baixar
                          </button>
                          <button
                            className="text-xs text-slate-500 hover:underline dark:text-slate-400"
                            title="Baixa o arquivo ainda cifrado (.gpg)"
                            onClick={() => download(c.id)}
                          >
                            .gpg
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap justify-end gap-2 pt-1">
            {stored && single && can("admin") && (
              <>
                <Button title="Pede a chave privada e baixa o arquivo já decifrado" onClick={() => setDecrypting(single)}>
                  Baixar
                </Button>
                <Button variant="ghost" title="Baixa o arquivo ainda cifrado (.gpg)" onClick={() => download(single.id)}>
                  .gpg
                </Button>
              </>
            )}
            {stored && can("admin") && (
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() => {
                  if (confirm("Excluir os arquivos deste backup do armazenamento? Não há como desfazer."))
                    remove.mutate();
                }}
              >
                Excluir backup
              </Button>
            )}
            {stored && can("operator") && (
              <Button
                variant="ghost"
                loading={reverify.isPending}
                disabled={b.verify_status === "running" || b.verify_status === "pending"}
                onClick={() => reverify.mutate()}
              >
                Verificar novamente
              </Button>
            )}
            <Button onClick={onClose}>Fechar</Button>
          </div>
        </div>
      )}
      {decrypting && id !== null && decrypting.file_name && (
        <DecryptDownloadModal
          open
          onClose={() => setDecrypting(null)}
          backupId={id}
          componentId={decrypting.id}
          fileName={decrypting.file_name}
          sizeBytes={decrypting.size_bytes}
        />
      )}
    </Modal>
  );
}

export default function BackupsPage() {
  const fmtDate = useFmtDate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const clientId = params.get("client") ?? "";
  const status = params.get("status") ?? "";
  const verify = params.get("verify") ?? "";
  const problems = params.get("problems") === "1";
  const qParam = params.get("q") ?? "";
  const open = params.get("open");

  function setParam(k: string, v: string) {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
    if (k !== "open") setPage(1);
  }

  const clients = useQuery({ queryKey: ["clients", ""], queryFn: () => api.get<Client[]>("/clients") });
  const list = useQuery({
    queryKey: ["backups", clientId, status, verify, problems, qParam, page],
    queryFn: () =>
      api.get<Page<Backup>>("/backups", {
        client_id: clientId,
        status,
        verify_status: verify,
        problems: problems || undefined,
        q: qParam,
        page,
        page_size: 25,
      }),
    refetchInterval: 30_000,
  });

  return (
    <div>
      <PageHeader
        title="Backups"
        subtitle="Execuções recebidas dos clientes e o resultado da verificação"
        actions={<RefreshButton keys={["backups", "backup"]} />}
      />

      <Card className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input max-w-[14rem]"
          placeholder="Buscar conta, pasta ou banco…"
          value={qParam}
          onChange={(e) => setParam("q", e.target.value)}
          title="Mostra só as execuções que contêm uma parte com esse nome (ex.: a conta do cPanel)"
        />
        <select className="input max-w-[14rem]" value={clientId} onChange={(e) => setParam("client", e.target.value)}>
          <option value="">Todas as origens</option>
          {(["server", "network"] as const).map((k) => {
            const items = clients.data?.filter((c) => c.kind === k) ?? [];
            return items.length ? (
              <optgroup key={k} label={k === "server" ? "Servidores" : "Equipamentos de rede"}>
                {items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </optgroup>
            ) : null;
          })}
        </select>
        <select className="input max-w-[12rem]" value={status} onChange={(e) => setParam("status", e.target.value)}>
          <option value="">Qualquer resultado</option>
          <option value="ok">Sucesso</option>
          <option value="warning">Com aviso</option>
          <option value="failed">Falhou</option>
          <option value="corrupted">Corrompido</option>
        </select>
        <select className="input max-w-[12rem]" value={verify} onChange={(e) => setParam("verify", e.target.value)}>
          <option value="">Qualquer verificação</option>
          <option value="ok">Verificado</option>
          <option value="failed">Reprovado</option>
          <option value="pending">Na fila</option>
          <option value="skipped">Não verificado</option>
        </select>
        <label className="ml-1 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={problems} onChange={(e) => setParam("problems", e.target.checked ? "1" : "")} />
          Só problemas
        </label>
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Origem</th>
              <th className="th">Data</th>
              <th className="th">Resultado</th>
              <th className="th">Verificação</th>
              <th className="th">Partes</th>
              <th className="th">Tamanho</th>
              <th className="th">Duração</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={7}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.items.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={7}>
                  Nenhum backup encontrado.
                </td>
              </tr>
            )}
            {list.data?.items.map((b) => (
              <tr
                key={b.id}
                className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                onClick={() => setParam("open", String(b.id))}
              >
                <td className="td">
                  <div className="font-medium">{b.client_name}</div>
                  <div className="font-mono text-xs text-slate-400 dark:text-slate-500">{b.run_name}</div>
                </td>
                <td className="td">{fmtDate(b.started_at ?? b.received_at)}</td>
                <td className="td">
                  <BackupStatusBadge status={b.status} />
                </td>
                <td className="td">
                  <VerifyBadge status={b.verify_status} mode={b.verify_mode} />
                </td>
                <td className="td tabular-nums">{b.component_count}</td>
                <td className="td tabular-nums">{fmtBytes(b.size_bytes)}</td>
                <td className="td tabular-nums">{fmtDuration(durationOf(b))}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && (
          <Pagination page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />
        )}
      </Card>

      <BackupDetailModal id={open ? Number(open) : null} onClose={() => setParam("open", "")} />
    </div>
  );
}

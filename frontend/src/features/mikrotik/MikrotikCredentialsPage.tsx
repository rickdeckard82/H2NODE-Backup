import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import type { DeviceCredential, ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { routerosUserCommands, serverAddress } from "./routeros";

interface FormState {
  id?: number;
  name: string;
  username: string;
  password: string;
  port: number;
  description: string;
}

const empty: FormState = { name: "", username: "h2node-backup", password: "", port: 22, description: "" };

/** Comandos para criar o usuário no RouterOS (com a senha só logo depois de salvá-la). */
function CommandsModal({
  cred,
  password,
  onClose,
}: {
  cred: DeviceCredential | null;
  password: string | null;
  onClose: () => void;
}) {
  const info = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const address = serverAddress(info.data?.net_host);
  return (
    <Modal open={!!cred} onClose={onClose} title={`Criar o usuário no MikroTik — ${cred?.name ?? ""}`} wide>
      {cred && (
        <div className="space-y-4 text-sm">
          <p className="text-slate-500 dark:text-slate-400">
            Cole no terminal de <b>cada</b> MikroTik que vai usar esta credencial (Winbox → New Terminal ou SSH como
            admin). O grupo <span className="font-mono">h2node-backup</span> só tem login SSH, leitura e acesso aos dados
            sensíveis — o usuário não consegue alterar nada.
          </p>
          <CopyBlock label="Comandos" text={routerosUserCommands(cred.username, password, address)} />
          <ul className="list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
            {!password && <li>Troque &lt;SENHA&gt; pela senha desta credencial (o painel não a mostra depois de salva).</li>}
            {address.startsWith("<") && (
              <li>
                Troque &lt;IP-DO-SERVIDOR&gt; pelo IP com que o servidor do H2NODE Backup chega ao MikroTik — o usuário só
                consegue entrar a partir dele.
              </li>
            )}
            <li>
              O serviço SSH do MikroTik precisa aceitar o servidor: <span className="font-mono">/ip service print</span>{" "}
              (porta {cred.port}, campo <i>address</i>) e o firewall de <i>input</i>.
            </li>
            <li>
              Depois cadastre os equipamentos em{" "}
              <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/mikrotik">
                MikroTik → Hosts
              </Link>
              .
            </li>
          </ul>
        </div>
      )}
    </Modal>
  );
}

export default function MikrotikCredentialsPage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<FormState | null>(null);
  const [cmds, setCmds] = useState<{ cred: DeviceCredential; password: string | null } | null>(null);
  const isAdmin = can("admin");

  const list = useQuery({
    queryKey: ["device-credentials"],
    queryFn: () => api.get<DeviceCredential[]>("/device-credentials"),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["device-credentials"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body: Record<string, unknown> = {
        name: f.name.trim(),
        username: f.username.trim(),
        port: f.port,
        description: f.description,
      };
      if (f.password) body.password = f.password;
      return f.id
        ? api.patch<DeviceCredential>(`/device-credentials/${f.id}`, body)
        : api.post<DeviceCredential>("/device-credentials", body);
    },
    onSuccess: (cred, f) => {
      toast("ok", "Credencial salva");
      setForm(null);
      invalidate();
      // senha nova ou usuário novo: mostra os comandos já com a senha (única vez)
      if (!f.id || f.password) setCmds({ cred, password: f.password || null });
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  const remove = useMutation({
    mutationFn: (c: DeviceCredential) => api.del(`/device-credentials/${c.id}`),
    onSuccess: () => {
      toast("ok", "Credencial removida");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  return (
    <div>
      <PageHeader
        title="MikroTik — usuário de acesso"
        subtitle="Usuário e senha com que o H2NODE Backup entra por SSH nos MikroTik para exportar a configuração"
        actions={isAdmin && <Button onClick={() => setForm({ ...empty })}>Nova credencial</Button>}
      />

      <Card className="mb-3 text-sm text-slate-600 dark:text-slate-300">
        Crie o mesmo usuário em todos os MikroTik que vão usar a credencial (botão <b>Comandos</b>): ele só tem login SSH,
        leitura e dados sensíveis. A senha fica cifrada no servidor e não volta para a tela. Precisa de usuários diferentes
        para grupos de equipamentos? Crie mais de uma credencial.
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Nome</th>
              <th className="th">Usuário</th>
              <th className="th">Porta SSH</th>
              <th className="th">Equipamentos</th>
              <th className="th">Alterada</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={6}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={6}>
                  Nenhuma credencial. {isAdmin ? "Crie a primeira para cadastrar os MikroTik." : "Peça a um administrador para criar."}
                </td>
              </tr>
            )}
            {list.data?.map((c) => (
              <tr key={c.id}>
                <td className="td">
                  <div className="font-medium">{c.name}</div>
                  {c.description && <div className="text-xs text-slate-400 dark:text-slate-500">{c.description}</div>}
                </td>
                <td className="td font-mono">{c.username}</td>
                <td className="td tabular-nums">{c.port}</td>
                <td className="td tabular-nums">{c.device_count}</td>
                <td className="td">{fmtDate(c.updated_at)}</td>
                <td className="td text-right">
                  <div className="flex justify-end gap-3">
                    <button
                      className="text-brand-600 hover:underline dark:text-brand-400"
                      onClick={() => setCmds({ cred: c, password: null })}
                    >
                      Comandos
                    </button>
                    {isAdmin && (
                      <>
                        <button
                          className="text-brand-600 hover:underline dark:text-brand-400"
                          onClick={() =>
                            setForm({
                              id: c.id,
                              name: c.name,
                              username: c.username,
                              password: "",
                              port: c.port,
                              description: c.description ?? "",
                            })
                          }
                        >
                          Editar
                        </button>
                        <button
                          className="text-rose-600 hover:underline dark:text-rose-400"
                          onClick={() => {
                            if (confirm(`Remover a credencial ${c.name}?`)) remove.mutate(c);
                          }}
                        >
                          Excluir
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar credencial" : "Nova credencial"}>
        {form && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <Field label="Nome" hint="Só para você identificar (ex.: padrão, clientes, POPs)">
              <input
                className="input"
                value={form.name}
                maxLength={80}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                autoFocus
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="sm:col-span-2">
                <Field label="Usuário no MikroTik">
                  <input
                    className="input font-mono"
                    value={form.username}
                    pattern="[A-Za-z0-9._\-]+"
                    minLength={2}
                    maxLength={64}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    required
                  />
                </Field>
              </div>
              <Field label="Porta SSH" hint="Padrão dos hosts">
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={65535}
                  value={form.port}
                  onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
                  required
                />
              </Field>
            </div>
            <Field
              label={form.id ? "Nova senha (opcional)" : "Senha"}
              hint={
                form.id
                  ? "Ao trocar, troque também em todos os MikroTik desta credencial."
                  : "8 a 64 caracteres, sem espaço, aspas, \\, $ ou ? (atrapalham no terminal do RouterOS)."
              }
            >
              <input
                className="input font-mono"
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={64}
                pattern={'[^\\s"\\\\$?]+'}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!form.id}
              />
            </Field>
            <Field label="Descrição">
              <input
                className="input"
                value={form.description}
                maxLength={255}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={() => setForm(null)}>
                Cancelar
              </Button>
              <Button type="submit" loading={save.isPending}>
                Salvar
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <CommandsModal cred={cmds?.cred ?? null} password={cmds?.password ?? null} onClose={() => setCmds(null)} />
    </div>
  );
}

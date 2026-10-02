import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useFmtDate } from "../../lib/datetime";
import type { FtpAccount } from "../../lib/types";

interface FormState {
  id?: number;
  username: string;
  password: string;
  description: string;
  is_active: boolean;
}

const empty: FormState = { username: "", password: "", description: "", is_active: true };

export default function FtpAccountsPage() {
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<FormState | null>(null);

  const list = useQuery({ queryKey: ["ftp-accounts"], queryFn: () => api.get<FtpAccount[]>("/ftp-accounts") });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["ftp-accounts"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body: Record<string, unknown> = { description: f.description || null, is_active: f.is_active };
      if (f.password) body.password = f.password;
      return f.id ? api.patch(`/ftp-accounts/${f.id}`, body) : api.post("/ftp-accounts", { ...body, username: f.username });
    },
    onSuccess: () => {
      toast("ok", "Conta salva");
      setForm(null);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  const remove = useMutation({
    mutationFn: (a: FtpAccount) => api.del(`/ftp-accounts/${a.id}`),
    onSuccess: () => {
      toast("ok", "Conta removida");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  return (
    <div>
      <PageHeader
        title="Contas FTP"
        subtitle="Usuários que os equipamentos usam para enviar a configuração (ex.: huawei, juniper)"
        actions={<Button onClick={() => setForm({ ...empty })}>Nova conta</Button>}
      />

      <Card className="mb-3 text-sm text-slate-600 dark:text-slate-300">
        A conta só funciona a partir do IP de um equipamento cadastrado com protocolo FTP, e só consegue{" "}
        <b>gravar</b> — não lê nem apaga nada. O arquivo é atribuído ao equipamento pelo IP de origem, então uma
        mesma conta pode servir a todos os equipamentos de um fabricante.
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Usuário</th>
              <th className="th">Descrição</th>
              <th className="th">Estado</th>
              <th className="th">Criada</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.isLoading && (
              <tr>
                <td className="td" colSpan={5}>
                  <Spinner className="h-5 w-5 text-brand-600" />
                </td>
              </tr>
            )}
            {list.data?.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={5}>
                  Nenhuma conta FTP.
                </td>
              </tr>
            )}
            {list.data?.map((a) => (
              <tr key={a.id}>
                <td className="td font-mono font-medium">{a.username}</td>
                <td className="td">{a.description ?? "—"}</td>
                <td className="td">{a.is_active ? <Badge tone="green">ativa</Badge> : <Badge tone="red">inativa</Badge>}</td>
                <td className="td">{fmtDate(a.created_at)}</td>
                <td className="td text-right">
                  <div className="flex justify-end gap-3">
                    <button
                      className="text-brand-600 hover:underline dark:text-brand-400"
                      onClick={() =>
                        setForm({
                          id: a.id,
                          username: a.username,
                          password: "",
                          description: a.description ?? "",
                          is_active: a.is_active,
                        })
                      }
                    >
                      Editar
                    </button>
                    <button
                      className="text-rose-600 hover:underline dark:text-rose-400"
                      onClick={() => {
                        if (confirm(`Remover a conta ${a.username}? Os equipamentos que a usam param de enviar.`))
                          remove.mutate(a);
                      }}
                    >
                      Excluir
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar conta FTP" : "Nova conta FTP"}>
        {form && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <Field label="Usuário">
              <input
                className="input font-mono"
                value={form.username}
                disabled={!!form.id}
                pattern="[A-Za-z0-9._\-]+"
                minLength={2}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                required
                autoFocus
              />
            </Field>
            <Field
              label={form.id ? "Nova senha (opcional)" : "Senha"}
              hint="8 a 64 caracteres, sem espaço, @, : ou / (quebram a URL ftp:// do Junos)."
            >
              <input
                className="input font-mono"
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={64}
                pattern="[^\s@:/]+"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!form.id}
              />
            </Field>
            <Field label="Descrição">
              <input
                className="input"
                value={form.description}
                placeholder="ex.: switches Huawei"
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              Conta ativa
            </label>
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
    </div>
  );
}

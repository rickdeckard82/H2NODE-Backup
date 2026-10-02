import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Field, Modal, PageHeader, Pagination, Spinner, useToast } from "../../components/ui";
import { api, ApiError, type Page } from "../../lib/api";
import { ROLE_LABEL, useAuth } from "../../lib/auth";
import { DEFAULT_TZ, TIMEZONES, useFmtDate } from "../../lib/datetime";
import type { SystemUser } from "../../lib/types";

type Role = SystemUser["role"];
const ROLES: Role[] = ["admin", "operator", "auditor"];
const ROLE_HINT: Record<Role, string> = {
  admin: "tudo, inclusive usuários, auditoria, baixar e excluir backups",
  operator: "cadastra e edita clientes, pede reverificação",
  auditor: "somente leitura",
};

interface FormState {
  id?: number;
  username: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  timezone: string;
  password: string;
}

const empty: FormState = {
  username: "",
  email: "",
  full_name: "",
  role: "operator",
  is_active: true,
  timezone: DEFAULT_TZ,
  password: "",
};

export default function SystemUsersPage() {
  const { user } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [form, setForm] = useState<FormState | null>(null);

  const list = useQuery({
    queryKey: ["system-users", q, page],
    queryFn: () => api.get<Page<SystemUser>>("/system-users", { q, page, page_size: 20 }),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["system-users"] });

  const save = useMutation({
    mutationFn: (f: FormState) => {
      const body: Record<string, unknown> = {
        email: f.email,
        full_name: f.full_name,
        role: f.role,
        is_active: f.is_active,
        timezone: f.timezone,
      };
      if (f.password) body.password = f.password;
      return f.id ? api.patch(`/system-users/${f.id}`, body) : api.post("/system-users", { ...body, username: f.username });
    },
    onSuccess: () => {
      toast("ok", "Usuário salvo");
      setForm(null);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  const remove = useMutation({
    mutationFn: (u: SystemUser) => api.del(`/system-users/${u.id}`),
    onSuccess: () => {
      toast("ok", "Usuário removido");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  const resetMfa = useMutation({
    mutationFn: (u: SystemUser) => api.post<{ detail: string }>(`/system-users/${u.id}/reset-mfa`),
    onSuccess: (r) => {
      toast("ok", r.detail);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao resetar 2FA"),
  });

  return (
    <div>
      <PageHeader
        title="Usuários do painel"
        subtitle="Quem pode acessar este painel"
        actions={<Button onClick={() => setForm({ ...empty })}>Novo usuário</Button>}
      />

      <Card className="mb-3">
        <input
          className="input max-w-xs"
          placeholder="Buscar…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Usuário</th>
              <th className="th">Nome</th>
              <th className="th">E-mail</th>
              <th className="th">Papel</th>
              <th className="th">Estado</th>
              <th className="th">Último login</th>
              <th className="th" />
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
            {list.data?.items.map((u) => (
              <tr key={u.id}>
                <td className="td font-medium">
                  {u.username}
                  {u.id === user?.id && <span className="ml-1 text-xs text-slate-400 dark:text-slate-500">(você)</span>}
                </td>
                <td className="td">{u.full_name}</td>
                <td className="td">{u.email}</td>
                <td className="td">
                  <Badge tone="blue">{ROLE_LABEL[u.role]}</Badge>
                </td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">
                    {u.is_active ? <Badge tone="green">ativo</Badge> : <Badge tone="red">inativo</Badge>}
                    {u.mfa_enabled && <Badge tone="blue">2FA</Badge>}
                  </div>
                </td>
                <td className="td">{fmtDate(u.last_login_at)}</td>
                <td className="td text-right">
                  <div className="flex justify-end gap-2">
                    <button
                      className="text-brand-600 hover:underline dark:text-brand-400"
                      onClick={() =>
                        setForm({
                          id: u.id,
                          username: u.username,
                          email: u.email,
                          full_name: u.full_name,
                          role: u.role,
                          is_active: u.is_active,
                          timezone: u.timezone ?? DEFAULT_TZ,
                          password: "",
                        })
                      }
                    >
                      Editar
                    </button>
                    {u.mfa_enabled && u.id !== user?.id && (
                      <button
                        className="text-amber-600 hover:underline dark:text-amber-400"
                        onClick={() => {
                          if (confirm(`Resetar o 2FA de ${u.username}? A pessoa terá que configurar de novo.`))
                            resetMfa.mutate(u);
                        }}
                      >
                        Resetar 2FA
                      </button>
                    )}
                    {u.id !== user?.id && (
                      <button
                        className="text-rose-600 hover:underline dark:text-rose-400"
                        onClick={() => {
                          if (confirm(`Remover ${u.username}?`)) remove.mutate(u);
                        }}
                      >
                        Excluir
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && (
          <Pagination page={page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />
        )}
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? "Editar usuário" : "Novo usuário do painel"}>
        {form && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <div className="grid grid-cols-2 gap-3">
              <Field label="Usuário">
                <input
                  className="input"
                  value={form.username}
                  disabled={!!form.id}
                  pattern="[a-zA-Z0-9._\-]+"
                  minLength={3}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  required
                />
              </Field>
              <Field label="Papel" hint={ROLE_HINT[form.role]}>
                <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Nome completo">
              <input
                className="input"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                required
              />
            </Field>
            <Field label="E-mail">
              <input
                className="input"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </Field>
            <Field label="Fuso horário" hint="Usado nas datas e no agrupamento por dia dos gráficos.">
              <select className="input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
                {(TIMEZONES.includes(form.timezone) ? TIMEZONES : [form.timezone, ...TIMEZONES]).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={form.id ? "Nova senha (opcional)" : "Senha"}
              hint="Mínimo 10 caracteres. Hash Argon2id. Trocar a senha encerra as sessões do usuário."
            >
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                minLength={10}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!form.id}
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

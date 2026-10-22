import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { RefreshButton } from "../../components/RefreshButton";
import { Badge, Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError, csrfToken } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtBytes } from "../../lib/format";
import type { FirmwareFile, FirmwareInfo, FirmwareSettings } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$/;

interface SettingsForm {
  enabled: boolean;
  ftp_username: string;
  ftp_password: string;
  networks: string;
  include_devices: boolean;
}

/** PUT com o arquivo como corpo, com progresso (firmwares passam de centenas de MB). */
function uploadWithProgress(file: File, onProgress: (pct: number) => void): Promise<FirmwareFile> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/firmware/files/${encodeURIComponent(file.name)}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRF-Token", csrfToken());
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data: unknown = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* resposta sem JSON (ex.: 413 do proxy) */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as FirmwareFile);
      else if (xhr.status === 413) reject(new ApiError(413, (data as { detail?: string }).detail ?? "arquivo grande demais"));
      else reject(new ApiError(xhr.status, (data as { detail?: string }).detail ?? `Erro ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(0, "falha de rede durante o envio"));
    xhr.send(file);
  });
}

function commands(f: FirmwareFile, info: FirmwareInfo): string {
  const host = info.host;
  const user = info.settings.ftp_username ?? "<usuario>";
  const tftpHost = info.tftp_port === 69 ? host : `${host}:${info.tftp_port}`;
  const ftpHost = info.ftp_port === 21 ? host : `${host}:${info.ftp_port}`;
  return [
    `# URLs`,
    `tftp://${tftpHost}/${f.name}`,
    `ftp://${user}@${ftpHost}/${f.name}`,
    ``,
    `# Huawei (VRP), no modo usuário`,
    `tftp ${host} get ${f.name}`,
    ``,
    `# Cisco e compatíveis`,
    `copy tftp://${tftpHost}/${f.name} flash:`,
    `copy ftp://${user}:<senha>@${ftpHost}/${f.name} flash:`,
    ``,
    `# Teste a partir de um Linux da rede liberada`,
    `tftp ${host} -m binary -c get ${f.name}`,
    `curl -fO "ftp://${user}:<senha>@${ftpHost}/${f.name}"`,
    `echo "${f.sha256}  ${f.name}" | sha256sum -c -`,
  ].join("\n");
}

function toForm(s: FirmwareSettings): SettingsForm {
  return {
    enabled: s.enabled,
    ftp_username: s.ftp_username ?? "",
    ftp_password: "",
    networks: s.allowed_networks.join("\n"),
    include_devices: s.include_devices,
  };
}

export default function FirmwarePage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<{ name: string; pct: number } | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [cmdFor, setCmdFor] = useState<FirmwareFile | null>(null);

  const q = useQuery({ queryKey: ["firmware"], queryFn: () => api.get<FirmwareInfo>("/firmware") });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["firmware"] });
  const info = q.data;
  const s = info?.settings;

  const upload = useMutation({
    mutationFn: async (f: File) => {
      // garante um access token válido antes de um envio que pode demorar
      await api.get("/auth/me").catch(() => undefined);
      setProgress({ name: f.name, pct: 0 });
      return uploadWithProgress(f, (pct) => setProgress({ name: f.name, pct }));
    },
    onSuccess: (f) => {
      toast("ok", `${f.name} enviado`);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao enviar"),
    onSettled: () => setProgress(null),
  });

  const remove = useMutation({
    mutationFn: (f: FirmwareFile) => api.del(`/firmware/files/${encodeURIComponent(f.name)}`),
    onSuccess: () => {
      toast("ok", "Firmware removido");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  const save = useMutation({
    mutationFn: (f: SettingsForm) =>
      api.put<FirmwareSettings>("/firmware/settings", {
        enabled: f.enabled,
        ftp_username: f.ftp_username.trim() || null,
        ftp_password: f.ftp_password || null,
        allowed_networks: f.networks.split(/[\s,;]+/).filter(Boolean),
        include_devices: f.include_devices,
      }),
    onSuccess: () => {
      toast("ok", "Acesso salvo");
      setForm(null);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao salvar"),
  });

  function pick(f: File) {
    if (!NAME_RE.test(f.name)) {
      toast("err", "Renomeie o arquivo: só letras, números, ponto, hífen e sublinhado, sem espaços");
      return;
    }
    if (info && f.size > info.max_mb * 1024 * 1024) {
      toast("err", `Arquivo maior que ${info.max_mb} MB (FIRMWARE_MAX_MB)`);
      return;
    }
    if (info?.files.some((x) => x.name === f.name) && !confirm(`Substituir ${f.name}?`)) return;
    upload.mutate(f);
  }

  const sameUser = form && s && form.ftp_username.trim() === (s.ftp_username ?? "");
  const needsPassword = !!form && !!form.ftp_username.trim() && !(sameUser && s?.has_password);

  return (
    <div>
      <PageHeader
        title="FTP Firmwares"
        subtitle="Arquivos que switches, OLTs e roteadores baixam por FTP ou TFTP para atualizar o firmware"
        actions={
          <>
            <RefreshButton keys={["firmware"]} />
            {can("admin") && s && (
              <Button variant="ghost" onClick={() => setForm(toForm(s))}>
                Configurar acesso
              </Button>
            )}
            {can("admin") && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) pick(f);
                    e.target.value = "";
                  }}
                />
                <Button loading={upload.isPending} onClick={() => fileRef.current?.click()}>
                  Enviar firmware
                </Button>
              </>
            )}
          </>
        }
      />

      {q.isLoading && <Spinner className="h-5 w-5 text-brand-600" />}
      {q.isError && (
        <Card className="mb-3 text-sm text-rose-600 dark:text-rose-400">
          Não foi possível carregar: {q.error instanceof ApiError ? q.error.detail : String(q.error)}
        </Card>
      )}

      {info && s && (
        <Card className="mb-3 space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">Servidor de firmwares</span>
            {s.enabled ? <Badge tone="green">ativo</Badge> : <Badge tone="amber">desativado</Badge>}
          </div>
          {!s.enabled && (
            <p className="text-slate-500 dark:text-slate-400">
              Ninguém baixa nada enquanto estiver desativado.{" "}
              {can("admin") ? "Use Configurar acesso para liberar as redes dos equipamentos." : ""}
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">TFTP (sem login)</div>
              <div className="font-mono">
                {info.host}:{info.tftp_port}/udp
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">FTP</div>
              <div className="font-mono">
                {info.host}:{info.ftp_port}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {s.ftp_username ? (
                  <>
                    usuário <span className="font-mono">{s.ftp_username}</span> · somente leitura
                  </>
                ) : (
                  "sem usuário definido: FTP de firmware desligado"
                )}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500">Quem pode baixar</div>
              <div className="font-mono text-xs">
                {s.allowed_networks.length ? s.allowed_networks.join(", ") : "nenhuma rede liberada"}
              </div>
              {s.include_devices && (
                <div className="text-xs text-slate-500 dark:text-slate-400">+ IPs dos equipamentos cadastrados</div>
              )}
            </div>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            Só esta pasta é servida para leitura — os backups recebidos por FTP/TFTP continuam inacessíveis. No firewall do
            servidor, libere para as mesmas redes as portas {info.ftp_port}/tcp, {info.ftp_passive_ports}/tcp (FTP passivo) e{" "}
            {info.tftp_port}/udp.
          </p>
        </Card>
      )}

      {progress && (
        <Card className="mb-3 space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <span className="truncate font-mono">{progress.name}</span>
            <span>{progress.pct}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-full bg-brand-600 transition-[width]" style={{ width: `${progress.pct}%` }} />
          </div>
          {progress.pct === 100 && <div className="text-xs text-slate-500">gravando no servidor…</div>}
        </Card>
      )}

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className="th">Arquivo</th>
              <th className="th">Tamanho</th>
              <th className="th">SHA-256</th>
              <th className="th">Enviado</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {info?.files.length === 0 && (
              <tr>
                <td className="td text-slate-400 dark:text-slate-500" colSpan={5}>
                  Nenhum firmware enviado.
                </td>
              </tr>
            )}
            {info?.files.map((f) => (
              <tr key={f.name}>
                <td className="td font-mono font-medium">{f.name}</td>
                <td className="td whitespace-nowrap">{fmtBytes(f.size)}</td>
                <td className="td font-mono text-xs text-slate-500 dark:text-slate-400" title={f.sha256}>
                  {f.sha256.slice(0, 16)}…
                </td>
                <td className="td whitespace-nowrap">{fmtDate(f.updated_at)}</td>
                <td className="td text-right">
                  <div className="flex justify-end gap-3">
                    <button className="text-brand-600 hover:underline dark:text-brand-400" onClick={() => setCmdFor(f)}>
                      Como baixar
                    </button>
                    {can("admin") && (
                      <button
                        className="text-rose-600 hover:underline dark:text-rose-400"
                        onClick={() => {
                          if (confirm(`Excluir ${f.name}? Equipamentos que forem buscá-lo vão receber "não encontrado".`))
                            remove.mutate(f);
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
      </Card>

      <Modal open={!!cmdFor} onClose={() => setCmdFor(null)} title={`Baixar no equipamento — ${cmdFor?.name ?? ""}`} wide>
        {cmdFor && info && (
          <div className="space-y-3 text-sm">
            <p className="text-slate-500 dark:text-slate-400">
              O equipamento precisa estar numa rede liberada. O nome é exato (o TFTP aceita maiúsculas diferentes e ignora
              pastas no caminho). Confira o SHA-256 no equipamento quando ele permitir.
            </p>
            <CopyBlock label="Comandos" text={commands(cmdFor, info)} />
            <div className="break-all rounded-lg bg-slate-50 px-2 py-1.5 font-mono text-[11px] text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              SHA-256 {cmdFor.sha256}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!form} onClose={() => setForm(null)} title="Acesso aos firmwares">
        {form && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(form);
            }}
          >
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              Servidor de firmwares ativo
            </label>
            <Field label="Redes liberadas" hint="Uma por linha, IP ou CIDR (ex.: 192.0.2.0/24). Valem para FTP e TFTP.">
              <textarea
                className="input min-h-24 font-mono"
                value={form.networks}
                placeholder={"192.0.2.0/24\n198.51.100.10"}
                onChange={(e) => setForm({ ...form, networks: e.target.value })}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.include_devices}
                onChange={(e) => setForm({ ...form, include_devices: e.target.checked })}
              />
              Liberar também os IPs dos equipamentos cadastrados (FTP/TFTP e MikroTik)
            </label>
            <Field label="Usuário FTP" hint="Só para firmwares (somente leitura). Vazio desliga o FTP; o TFTP continua.">
              <input
                className="input font-mono"
                value={form.ftp_username}
                pattern="[A-Za-z0-9._\-]{2,64}"
                placeholder="firmware"
                onChange={(e) => setForm({ ...form, ftp_username: e.target.value })}
              />
            </Field>
            {form.ftp_username.trim() && (
              <Field
                label={needsPassword ? "Senha" : "Nova senha (opcional)"}
                hint="8 a 64 caracteres, sem espaço, @, : ou /."
              >
                <input
                  className="input font-mono"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={64}
                  pattern="[^\s@:/]+"
                  value={form.ftp_password}
                  onChange={(e) => setForm({ ...form, ftp_password: e.target.value })}
                  required={needsPassword}
                />
              </Field>
            )}
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

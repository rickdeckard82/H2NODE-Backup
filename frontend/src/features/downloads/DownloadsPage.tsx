import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshButton } from "../../components/RefreshButton";
import { Badge, Button, Card, Modal, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useFmtDate } from "../../lib/datetime";
import { fmtBytes } from "../../lib/format";
import { CopyBlock } from "../clients/ClientsPage";

interface DownloadItem {
  name: string;
  title: string;
  platform: "linux" | "windows" | "key" | "other";
  source: "agent" | "build" | "uploaded" | "key";
  size: number;
  sha256: string;
  updated_at: string;
  version: string | null;
}

interface DownloadsOut {
  items: DownloadItem[];
  problems: string[];
}

interface LinkOut {
  url: string;
  expires_at: string;
}

const link = "text-brand-600 hover:underline dark:text-brand-400";

const PLATFORM: Record<DownloadItem["platform"], { label: string; help?: string }> = {
  linux: { label: "Linux", help: "/help/linux" },
  windows: { label: "Windows", help: "/help/windows" },
  key: { label: "Chave" },
  other: { label: "Outro" },
};

/** Comandos para baixar direto no servidor do cliente com o link temporário. */
function commands(it: DownloadItem, url: string): string {
  if (it.platform === "linux") {
    const dir = it.name.replace(/\.tar\.gz$/, "");
    return [
      `curl -fsSL "${url}" -o ${it.name}`,
      `echo "${it.sha256}  ${it.name}" | sha256sum -c -`,
      `tar xzf ${it.name} && cd ${dir}`,
      `sudo ./install.sh --cron "30 2 * * *"`,
    ].join("\n");
  }
  if (it.platform === "windows") {
    return [
      `# PowerShell (como administrador)`,
      `Invoke-WebRequest -Uri "${url}" -OutFile "$env:TEMP\\${it.name}"`,
      `(Get-FileHash "$env:TEMP\\${it.name}" -Algorithm SHA256).Hash -eq "${it.sha256.toUpperCase()}"`,
      `Start-Process "$env:TEMP\\${it.name}"`,
    ].join("\n");
  }
  if (it.platform === "key") {
    return `sudo curl -fsSL "${url}" -o /etc/pulse-backup/${it.name}`;
  }
  return `curl -fsSL "${url}" -o ${it.name}`;
}

async function downloadNow(name: string) {
  // garante um access token válido: o download é um GET direto do navegador (cookie)
  await api.get("/auth/me").catch(() => undefined);
  const a = document.createElement("a");
  a.href = `/api/downloads/file/${encodeURIComponent(name)}`;
  a.rel = "noopener";
  a.click();
}

export default function DownloadsPage() {
  const { can } = useAuth();
  const fmtDate = useFmtDate();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [linkFor, setLinkFor] = useState<{ item: DownloadItem; link: LinkOut } | null>(null);

  const list = useQuery({ queryKey: ["downloads"], queryFn: () => api.get<DownloadsOut>("/downloads/list") });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["downloads"] });

  const makeLink = useMutation({
    mutationFn: (it: DownloadItem) => api.post<LinkOut>(`/downloads/${encodeURIComponent(it.name)}/link`),
    onSuccess: (l, item) => setLinkFor({ item, link: l }),
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao gerar o link"),
  });

  const upload = useMutation({
    mutationFn: (f: File) => api.putFile<DownloadItem>(`/downloads/${encodeURIComponent(f.name)}`, f),
    onSuccess: (it) => {
      toast("ok", `${it.name} enviado`);
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao enviar"),
  });

  const remove = useMutation({
    mutationFn: (it: DownloadItem) => api.del(`/downloads/${encodeURIComponent(it.name)}`),
    onSuccess: () => {
      toast("ok", "Arquivo removido");
      invalidate();
    },
    onError: (e) => toast("err", e instanceof ApiError ? e.detail : "Erro ao remover"),
  });

  const items = list.data?.items ?? [];
  const problems = list.data?.problems ?? [];
  const hasWindows = items.some((i) => i.platform === "windows");

  return (
    <div>
      <PageHeader
        title="Downloads"
        subtitle="Agentes de backup e a chave pública — baixe aqui ou gere um link temporário para baixar direto no servidor"
        actions={
          <>
            <RefreshButton keys={["downloads"]} />
            {can("admin") && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".exe,.msi,.zip,.tar.gz,.tgz"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) upload.mutate(f);
                    e.target.value = "";
                  }}
                />
                <Button loading={upload.isPending} onClick={() => fileRef.current?.click()}>
                  Enviar arquivo
                </Button>
              </>
            )}
          </>
        }
      />

      {list.isLoading && <Spinner className="h-5 w-5 text-brand-600" />}

      {list.isError && (
        <Card className="mb-3 text-sm text-rose-600 dark:text-rose-400">
          Não foi possível listar os downloads: {list.error instanceof ApiError ? list.error.detail : String(list.error)}
        </Card>
      )}

      {problems.length > 0 && (
        <Card className="mb-3 space-y-1 text-sm text-amber-700 dark:text-amber-300">
          <div className="font-semibold">O servidor não conseguiu ler alguns arquivos:</div>
          <ul className="list-disc pl-5 font-mono text-xs">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            O painel roda como uid 10001: os arquivos precisam ser legíveis por todos (ex.:{" "}
            <span className="font-mono">chmod -R a+rX agent</span> na pasta do projeto).
          </div>
        </Card>
      )}

      {list.isSuccess && !hasWindows && (
        <Card className="mb-3 text-sm text-slate-600 dark:text-slate-300">
          Nenhum instalador do <b>cliente Windows</b> disponível ainda. Ele é compilado pelo próprio servidor (serviço{" "}
          <span className="font-mono">client-builder</span>) ao atualizar com{" "}
          <span className="font-mono">docker compose build &amp;&amp; docker compose up -d</span>. Compilado fora,{" "}
          {can("admin") ? "envie aqui com" : "um administrador envia em"} <b>Enviar arquivo</b> o{" "}
          <span className="font-mono">PulseBackup-Setup-&lt;versão&gt;.exe</span>.
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {items.map((it) => (
          <Card key={it.name} className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{it.title}</span>
                  <Badge tone="blue">{PLATFORM[it.platform].label}</Badge>
                  {it.version && <Badge>v{it.version}</Badge>}
                </div>
                <div className="mt-0.5 truncate font-mono text-xs text-slate-500 dark:text-slate-400">{it.name}</div>
                <div className="text-xs text-slate-400 dark:text-slate-500">
                  {fmtBytes(it.size)} ·{" "}
                  {it.source === "agent"
                    ? "gerado do agente deste servidor"
                    : it.source === "build"
                      ? `compilado por este servidor em ${fmtDate(it.updated_at)}`
                      : `enviado em ${fmtDate(it.updated_at)}`}
                </div>
              </div>
              {PLATFORM[it.platform].help && (
                <Link className={`shrink-0 text-xs ${link}`} to={PLATFORM[it.platform].help!}>
                  Como instalar
                </Link>
              )}
            </div>
            <div className="break-all rounded-lg bg-slate-50 px-2 py-1.5 font-mono text-[11px] text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              SHA-256 {it.sha256}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => downloadNow(it.name)}>Baixar</Button>
              {can("operator") && (
                <Button variant="ghost" loading={makeLink.isPending && makeLink.variables?.name === it.name} onClick={() => makeLink.mutate(it)}>
                  Link para o servidor (1 h)
                </Button>
              )}
              {can("admin") && it.source === "uploaded" && (
                <Button
                  variant="ghost"
                  className="ml-auto text-rose-600 dark:text-rose-400"
                  onClick={() => {
                    if (confirm(`Excluir ${it.name}?`)) remove.mutate(it);
                  }}
                >
                  Excluir
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Modal open={!!linkFor} onClose={() => setLinkFor(null)} title={`Baixar no servidor — ${linkFor?.item.name ?? ""}`} wide>
        {linkFor && (
          <div className="space-y-3 text-sm">
            <p className="text-slate-500 dark:text-slate-400">
              Link sem login, válido até <b>{fmtDate(linkFor.link.expires_at)}</b> e só para este arquivo. Use no servidor ou
              computador que vai receber o agente; o comando confere o SHA-256 antes de instalar.
            </p>
            <CopyBlock label="Comandos" text={commands(linkFor.item, linkFor.link.url)} />
            <CopyBlock label="Link" text={linkFor.link.url} />
            <p className="text-xs text-slate-400 dark:text-slate-500">
              Não publique o link: quem tiver o link baixa o arquivo até ele expirar (o arquivo não é segredo, mas o endereço do
              painel é).
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}

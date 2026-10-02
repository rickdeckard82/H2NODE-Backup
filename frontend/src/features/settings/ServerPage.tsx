import { useQuery } from "@tanstack/react-query";
import { CopyBlock } from "../clients/ClientsPage";
import { Badge, Button, Card, PageHeader, Spinner, useToast } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { fmtBytes } from "../../lib/format";
import type { ServerInfo } from "../../lib/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[14rem_1fr] sm:gap-4">
      <dt className="text-sm text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="min-w-0 break-words text-sm">{children}</dd>
    </div>
  );
}

export default function ServerPage() {
  const toast = useToast();
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const s = q.data;

  async function downloadKey() {
    try {
      const blob = await api.blob("/server/public-key");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "backup-key.pub.asc";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast("err", e instanceof ApiError ? e.detail : "Chave pública indisponível");
    }
  }

  return (
    <div>
      <PageHeader title="Chaves e servidor" subtitle="O que os clientes precisam para enviar backups com segurança" />
      {!s ? (
        <Spinner className="h-6 w-6 text-brand-600" />
      ) : (
        <div className="space-y-4">
          <Card>
            <h3 className="mb-1 font-semibold">Chave de criptografia (GPG)</h3>
            <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
              Os clientes cifram cada parte do backup com a chave <b>pública</b>. Só quem tem a chave{" "}
              <b>privada</b> consegue decifrar — ela fica fora do painel (no worker, para a verificação, e no seu
              cofre offline).
            </p>
            <dl className="divide-y divide-slate-100 dark:divide-slate-800">
              <Row label="Chave pública">
                {s.public_key_available ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-xs">{s.public_key_fingerprint}</span>
                    <Button variant="ghost" onClick={downloadKey}>
                      Baixar .asc
                    </Button>
                  </div>
                ) : (
                  <span className="text-rose-600 dark:text-rose-400">
                    não configurada — rode <code className="font-mono">make keys</code> no servidor
                  </span>
                )}
              </Row>
              {s.public_key_uid && <Row label="Identificação">{s.public_key_uid}</Row>}
              <Row label="Verificação profunda">
                {s.deep_verify_enabled ? (
                  <Badge tone="green">ativa — o worker decifra e testa cada backup</Badge>
                ) : (
                  <Badge tone="amber">desligada — só integridade (hash + destinatário)</Badge>
                )}
              </Row>
            </dl>
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
              Sem uma cópia da chave privada <b>e</b> da senha dela fora deste servidor, um desastre aqui torna
              todos os backups irrecuperáveis. Veja <code className="font-mono">docs/security.md</code>.
            </div>
          </Card>

          <Card>
            <h3 className="mb-1 font-semibold">Recepção (rsync sobre SSH)</h3>
            <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
              Cada cliente entra com a própria chave SSH e só consegue <b>gravar</b> na própria pasta — não lê, não
              lista e não apaga nada.
            </p>
            <dl className="divide-y divide-slate-100 dark:divide-slate-800">
              <Row label="Endereço">
                <span className="font-mono">
                  backup@{s.ssh_host}:{s.ssh_port}
                </span>
              </Row>
              <Row label="Fingerprint do host">
                <span className="font-mono text-xs">{s.ssh_host_key_fingerprint ?? "sshd ainda não publicou a chave"}</span>
              </Row>
            </dl>
            {s.ssh_host_key && (
              <div className="mt-2">
                <div className="label">Linha do known_hosts dos clientes</div>
                <CopyBlock label="Linha do known_hosts" text={s.ssh_host_key} />
              </div>
            )}
          </Card>

          <Card>
            <h3 className="mb-1 font-semibold">Recepção de switches e roteadores (FTP/TFTP)</h3>
            <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
              Só gravação e só a partir dos IPs dos equipamentos cadastrados. A configuração chega em claro (limite
              dos protocolos), é cifrada com a chave GPG na hora e o original é apagado.
            </p>
            <dl className="divide-y divide-slate-100 dark:divide-slate-800">
              <Row label="Endereço para os equipamentos">
                <span className="font-mono">{s.net_host}</span>
              </Row>
              <Row label="FTP">
                <span className="font-mono">
                  porta {s.ftp_port} · passivo {s.ftp_passive_ports}
                </span>
              </Row>
              <Row label="TFTP">
                <span className="font-mono">porta {s.tftp_port}/udp</span>
              </Row>
            </dl>
          </Card>

          <Card>
            <h3 className="mb-3 font-semibold">Armazenamento</h3>
            <dl className="divide-y divide-slate-100 dark:divide-slate-800">
              <Row label="Pasta no container">
                <span className="font-mono">{s.storage_path}</span>
                <span className="text-slate-400 dark:text-slate-500"> (BACKUP_STORAGE_PATH no host)</span>
              </Row>
              <Row label="Capacidade">{fmtBytes(s.disk_total_bytes)}</Row>
              <Row label="Em uso">{fmtBytes(s.disk_used_bytes)}</Row>
              <Row label="Livre">{fmtBytes(s.disk_free_bytes)}</Row>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}

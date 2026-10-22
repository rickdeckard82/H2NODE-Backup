import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

const link = "text-brand-600 hover:underline dark:text-brand-400";

export default function A10HelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const ftpPort = q.data?.ftp_port ?? 21;
  const pasv = q.data?.ftp_passive_ports ?? "30000-30049";

  return (
    <div className="space-y-4">
      <PageHeader
        title="A10 Thunder (ACOS): backup e restauração"
        subtitle="O ACOS envia o backup de sistema (startup-config, aFleX e certificados) por FTP; o Pulse Backup valida o tar.gz, cifra e guarda cada versão."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em <Link className={link} to="/settings/ftp-accounts">Configuração → Contas FTP</Link>, crie por exemplo{" "}
            <Code>a10</Code>. A senha tem de 8 a 64 caracteres, <b>sem espaço, @, : ou /</b>.
          </p>
        </Step>

        <Step n={2} title="Cadastre o equipamento">
          <p>
            Em <Link className={link} to="/devices">Equipamentos de rede</Link>: nome, fabricante <b>A10 (ACOS)</b>,
            protocolo <b>FTP</b> e o <b>IP de origem</b>, o IP com que o equipamento chega ao servidor. Ele identifica
            de quem é o arquivo e cada IP pertence a um único equipamento.
          </p>
          <Note tone="warn">
            Se o envio sai pela interface de gerência, o IP de origem é o do <b>management</b> (e é preciso marcar{" "}
            <Code>use-mgmt-port</Code>). Sem isso, o ACOS usa a rede de dados.
          </Note>
        </Step>

        <Step n={3} title="Libere o IP no firewall do servidor">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-de-origem> ftp" />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code> só para esse IP.
          </p>
        </Step>

        <Step n={4} title="Pela interface web (GUI)">
          <p>
            Em <b>System → Maintenance → Backup → System</b>: <b>Local or Remote</b> = Remote, <b>Encrypt</b> = Disable
            (o Pulse Backup já cifra ao receber), <b>Use Management Port</b> conforme o item acima, e preencha:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><b>Protocol</b>: FTP</li>
            <li><b>Host</b>: <Code>{host}</Code> (use o IP)</li>
            <li><b>Port</b>: {ftpPort === 21 ? "deixe em branco (21)" : <Code>{ftpPort}</Code>}</li>
            <li><b>Location</b>: nome do arquivo, por exemplo <Code>a10-core.tar.gz</Code></li>
            <li><b>User</b> / <b>Password</b>: a conta FTP do passo 1</li>
          </ul>
          <p>Clique em <b>Backup</b>. Para agendar, use a aba <b>Periodic Backup</b> com os mesmos dados.</p>
        </Step>

        <Step n={5} title="Ou pela CLI">
          <CopyBlock
            label="Envio imediato"
            text={`backup system ftp://a10@${host}${ftpPort !== 21 ? `:${ftpPort}` : ""}/a10-core.tar.gz
(o ACOS pede a senha)`}
          />
          <CopyBlock
            label="Periódico (a cada 1 dia)"
            text={`configure
backup-periodic system day 1 ftp://a10@${host}${ftpPort !== 21 ? `:${ftpPort}` : ""}/a10-core.tar.gz
write memory`}
          />
          <p>
            Acrescente <Code>use-mgmt-port</Code> depois de <Code>system</Code>/<Code>day 1</Code> se o envio sair pela
            gerência. Salve com <Code>write memory</Code>: sem isso o agendamento se perde no reinício. Cadastre o
            equipamento com o intervalo esperado igual ao do agendamento (ex.: 24 h); envio manual = <b>0 (sob demanda)</b>.
          </p>
        </Step>

        <Step n={6} title="Confira">
          <p>
            O resultado aparece em <Link className={link} to="/backups">Backups</Link> com <b>sucesso</b> e{" "}
            <b>verificado</b> (o tar.gz é aberto por inteiro). Se não chegar, veja{" "}
            <Code>docker compose logs -f ftp</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP de origem cadastrado não é o que chega (passo 2).</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, firewall (passo 3) ou saída pela porta errada.</li>
            <li>Conecta e não grava — conexão passiva bloqueada ({pasv}) ou senha com caractere proibido.</li>
            <li>Verificação com falha, &quot;tar corrompido ou truncado&quot; — envie de novo.</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão desejada e clique em <b>Baixar</b>: informe a chave privada e a senha e receba o{" "}
            <Code>.tar.gz</Code> já decifrado. Passo a passo em <Link className={link} to="/help/decrypt">Baixar e decifrar</Link>.
          </p>
        </Step>

        <Step n={2} title="Disponibilize e restaure">
          <p>Coloque o arquivo num servidor SCP/SFTP/FTP/TFTP que o A10 alcance e rode:</p>
          <CopyBlock label="No ACOS" text="restore use-mgmt-port scp://usuario@<servidor>/caminho/a10-core.tar.gz" />
          <p>
            O ACOS mostra as diferenças e pede confirmação; ao final, <b>reinicie sem rodar <Code>write memory</Code></b>.
          </p>
          <Note tone="warn">
            Não restaure entre plataformas de hardware diferentes. O restore <b>não recupera as VLANs</b> e pode pedir
            o mapeamento de portas (porta atual ← porta do backup; <Code>0</Code> pula, <Code>-1</Code> recomeça).
          </Note>
        </Step>

        <Step n={3} title="Apague o arquivo em claro">
          <p>
            O backup contém certificados e chaves SSL. Remova de onde copiou: <Code>shred -u a10-core.tar.gz</Code> no
            seu computador e apague-o do servidor de transferência.
          </p>
        </Step>
      </Card>
    </div>
  );
}

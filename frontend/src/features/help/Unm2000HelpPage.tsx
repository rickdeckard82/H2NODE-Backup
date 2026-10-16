import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function Unm2000HelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const ftpPort = q.data?.ftp_port ?? 21;
  const pasv = q.data?.ftp_passive_ports ?? "30000-30049";

  return (
    <div className="space-y-4">
      <PageHeader
        title="UNM2000 (Fiberhome): backup das OLTs"
        subtitle="A UNM2000 exporta a configuração de cada OLT por FTP; o Pulse Backup valida, cifra e guarda cada versão."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            A tarefa de exportação de configuração da UNM2000 grava, por OLT e por dia, um arquivo{" "}
            <Code>config_&lt;IP-da-OLT&gt;_&lt;AAAAMMDD&gt;</Code> (texto, começa com <Code>!WOS system config file</Code>).
          </li>
          <li>
            A <b>UNM2000 inteira</b> é um único equipamento no painel (o IP de origem é o dela). Cada arquivo recebido vira uma
            versão e é comparado só com o anterior <b>da mesma OLT</b>: configuração igual à do dia anterior aparece como
            &quot;idêntica ao backup anterior&quot;.
          </li>
        </ul>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Configurar</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/settings/ftp-accounts">Configuração → Contas FTP</Link>,
            por exemplo <Code>unm2000</Code>. Senha de 8 a 64 caracteres, sem espaço, <Code>@</Code>, <Code>:</Code> ou <Code>/</Code>.
          </p>
        </Step>

        <Step n={2} title="Cadastre a UNM2000 como equipamento">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/devices">Equipamentos de rede</Link>: nome
            (ex.: <Code>unm2000</Code>), fabricante <b>Fiberhome (UNM2000)</b>, protocolo <b>FTP</b> e o <b>IP de origem</b>, o IP com
            que a UNM2000 chega ao servidor.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <b>Retenção:</b> cada arquivo de OLT é uma versão. Com 9 OLTs, o padrão de &quot;mínimo de versões&quot; (10) guarda
              pouco mais de um dia; aumente-o (ex.: 9 OLTs × 30 dias = 270) e ajuste os dias.
            </li>
            <li>
              <b>Intervalo esperado:</b> <b>0</b> (sob demanda) ou o intervalo da tarefa agendada da UNM2000, para receber alerta de
              atraso.
            </li>
          </ul>
        </Step>

        <Step n={3} title="Libere o IP no firewall do servidor">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-da-UNM2000> ftp" />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code> só para esse IP.
          </p>
        </Step>

        <Step n={4} title="Aponte a exportação da UNM2000 para o servidor">
          <p>Na tarefa de exportação de configuração (a que gera a pasta <Code>Config_Export</Code>), use FTP como destino:</p>
          <CopyBlock
            label="Dados do destino"
            text={`servidor : ${host}
porta    : ${ftpPort}
usuário  : unm2000
senha    : <senha da conta FTP>
modo     : passivo`}
          />
          <Note>
            Os nomes dos menus variam conforme a versão da UNM2000. O servidor aceita subpastas (por exemplo{" "}
            <Code>Policy_Task/Config_Export/</Code>): elas são criadas na hora, e só aceita <b>gravação</b>.
          </Note>
        </Step>

        <Step n={5} title="Confira">
          <p>
            Rode a tarefa e veja em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>{" "}
            um item por OLT com <b>sucesso</b> e <b>verificado</b>. Se não chegar, no servidor de backup:{" "}
            <Code>docker compose logs -f ftp</Code>.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP de origem cadastrado não é o que chega (passo 2).</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, NAT ou firewall (passo 3).</li>
            <li>Conecta e não grava — a faixa passiva {pasv} está bloqueada.</li>
            <li>Arquivo recusado — não parece configuração Fiberhome (sem <Code>!WOS</Code> nem <Code>hostname</Code>).</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar a configuração de uma OLT</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão da OLT desejada (o nome do arquivo traz o IP e a data) e clique em <b>Baixar</b>: informe a chave
            privada e a senha. O arquivo tem cerca de 700 KB. Passo a passo em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>.
          </p>
        </Step>

        <Step n={2} title="Aplique na OLT">
          <p>
            O arquivo é o <b>export de configuração da própria OLT</b> (texto com <Code>hostname</Code>, interfaces e perfis).
            Importe-o pela UNM2000 (importação/restauração de configuração da OLT) ou carregue-o pela CLI da OLT, conforme o
            procedimento do manual da sua versão, e confira as diferenças com a configuração atual antes de aplicar.
          </p>
          <Note tone="warn">
            Faça sempre uma cópia da configuração atual antes de restaurar, e valide o IP de gerência e as rotas do arquivo: um
            backup antigo pode trazer endereços diferentes dos atuais.
          </Note>
        </Step>
      </Card>
    </div>
  );
}

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
        subtitle="A UNM2000 manda as OLTs enviarem a configuração por FTP; o H2NODE Backup valida, cifra e guarda cada versão."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            A tarefa de exportação da UNM2000 faz <b>cada OLT enviar a própria configuração</b> por FTP, a partir do{" "}
            <b>IP dela</b>, num arquivo chamado <Code>&lt;ID&gt;_&lt;MMDD&gt;</Code> (ex.: <Code>10000001_1016</Code>). É texto e
            começa com <Code>!WOS system config file</Code>.
          </li>
          <li>
            O servidor identifica quem enviou pelo IP de origem, então <b>cada OLT é um equipamento</b> (fabricante{" "}
            <b>Fiberhome (OLT / UNM2000)</b>). Cada arquivo vira uma versão; configuração igual à do dia anterior aparece como
            &quot;idêntica ao backup anterior&quot;.
          </li>
          <li>
            Depois de cada envio, a <b>própria UNM2000</b> entra no mesmo FTP (do IP dela) para apagar o arquivo antigo e
            renomear o novo para <Code>Policy_Task/Config_Export/config_&lt;IP&gt;_&lt;data&gt;</Code>. Este servidor só aceita
            gravação, então, no cadastro de cada OLT, você informa o <b>IP da UNM2000</b>: esse IP passa a poder usar o FTP e,
            para ele, apagar e renomear respondem sucesso <b>sem alterar nada</b> (o arquivo já foi guardado e cifrado). Sem isso
            a UNM2000 aponta &quot;XFTP server connection failed&quot; e repete a tarefa.
          </li>
          <li>
            Conexão de um IP não cadastrado é recusada antes do login (<Code>ftp_unknown_ip</Code> no log do <Code>ftp</Code>): é
            assim que você descobre os IPs que faltam.
          </li>
        </ul>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Configurar</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/settings/ftp-accounts">Configuração → Contas FTP</Link>,
            por exemplo <Code>fiberhome</Code>: a mesma conta que a UNM2000 e as OLTs usam. Senha de 8 a 64 caracteres, sem espaço,{" "}
            <Code>@</Code>, <Code>:</Code> ou <Code>/</Code>.
          </p>
        </Step>

        <Step n={2} title="Cadastre cada OLT (com o IP da UNM2000)">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/devices">FTP/TFTP</Link>, um
            cadastro por OLT: nome (ex.: o <Code>hostname</Code>, como <Code>OLT-01</Code>), fabricante{" "}
            <b>Fiberhome (OLT / UNM2000)</b>, protocolo <b>FTP</b> e o <b>IP de origem</b> igual ao <b>IP da OLT</b> (o mesmo do nome{" "}
            <Code>config_&lt;IP&gt;_…</Code>). Ao escolher Fiberhome aparece o campo <b>IP da UNM2000 (gerenciador)</b>: preencha com o
            IP com que a UNM2000 chega ao servidor (o mesmo em todas as OLTs; no log do <Code>ftp</Code> aparece como{" "}
            <Code>ftp_unknown_ip</Code> enquanto não estiver cadastrado).
          </p>
          <p>
            Intervalo esperado: o da tarefa (ex.: <b>24</b> h), para ser alertado se uma OLT parar de enviar.
          </p>
          <Note>
            O IP da UNM2000 <b>não</b> é cadastrado como equipamento: se já existir um equipamento com esse IP (por exemplo{" "}
            <Code>unm2000</Code>), exclua-o antes. Se outro servidor sai pelo mesmo IP (ex.: atrás do mesmo NAT), ele pode ter
            um cadastro FTP nesse IP desde que escolha uma <b>Conta FTP</b> própria, diferente da que a UNM2000 usa: o login
            com essa conta vai para o cadastro e qualquer outra conta é tratada como a UNM2000.
          </Note>
        </Step>

        <Step n={3} title="Libere os IPs no firewall do servidor">
          <CopyBlock
            label="Comando (um por equipamento, ou a faixa)"
            text={`sudo ./scripts/ufw-setup.sh device <IP-da-OLT> ftp
sudo ./scripts/ufw-setup.sh device <faixa-das-OLTs, ex.: 10.0.0.0/24> ftp   # ou a faixa inteira
sudo ./scripts/ufw-setup.sh device <IP-da-UNM2000> ftp`}
          />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code>. Liberar uma faixa no ufw é só o filtro de rede: quem decide
            se o envio é aceito continua sendo o cadastro (IP exato + conta FTP).
          </p>
        </Step>

        <Step n={4} title="Aponte a UNM2000 para este servidor">
          <p>No cadastro do servidor FTP da UNM2000 (o de backup das OLTs):</p>
          <CopyBlock
            label="Dados do destino"
            text={`servidor : ${host}
porta    : ${ftpPort}
usuário  : fiberhome
senha    : <senha da conta FTP>
caminho  : ./`}
          />
          <Note>
            Os nomes dos menus variam conforme a versão da UNM2000. O cadastro de FTP de <b>firmware</b> (as OLTs{" "}
            <b>baixam</b> o arquivo) não usa a conta acima, que só grava: para ele, use o usuário e as redes da página{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/firmware">
              FTP Firmwares
            </Link>
            .
          </Note>
        </Step>

        <Step n={5} title="Confira">
          <p>
            Rode a tarefa e veja em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>{" "}
            um item por OLT com <b>sucesso</b> e <b>verificado</b>, e a UNM2000 sem erro de conexão. No servidor:{" "}
            <Code>docker compose logs -f ftp</Code>.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP ainda não está cadastrado (ou o cadastrado não é o que chega) — passo 2.</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, NAT ou firewall (passo 3).</li>
            <li>Conecta e não grava — a faixa passiva {pasv} está bloqueada.</li>
            <li><Code>ftp_manager_noop</Code> — normal: a UNM2000 apagou ou renomeou e o servidor respondeu sem alterar nada.</li>
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

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function DatacomHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const tftpPort = q.data?.tftp_port ?? 69;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Datacom (DmOS): backup e restauração"
        subtitle="O DmOS envia a configuração por TFTP quando o script roda; o H2NODE Backup valida, cifra e guarda cada versão."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Cadastre o equipamento">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/devices">FTP/TFTP</Link>: nome,
            fabricante <b>Datacom (DmOS)</b>, protocolo <b>TFTP</b> e o <b>IP de origem</b>, o IP com que o equipamento chega ao
            servidor. O TFTP não tem usuário nem senha: o que autoriza o envio é esse IP, e cada IP tem um único cadastro
            TFTP.
          </p>
          <p>
            O botão <b>Comandos</b> da linha do equipamento mostra o <b>identificador</b> (slug) usado na pasta do destino, como{" "}
            <Code>core-mpls-con</Code>.
          </p>
          <Note tone="warn">
            Se o equipamento sai por NAT ou por outra interface, o IP que o servidor enxerga é outro. Use{" "}
            <Code>source &lt;IP&gt;</Code> no comando <Code>copy</Code> para fixar a origem e cadastre esse mesmo IP.
          </Note>
        </Step>

        <Step n={2} title="Libere o IP no firewall do servidor">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-de-origem> tftp" />
          <p>
            Abre a porta {tftpPort}/udp só para esse IP; as respostas passam pelo conntrack do ufw.
          </p>
        </Step>

        <Step n={3} title="Crie o script no equipamento">
          <p>
            O script salva a configuração em arquivo e envia para o servidor, para a pasta do equipamento (o{" "}
            <b>identificador</b> entre barras):
          </p>
          <CopyBlock label="No DmOS" text="file edit config-backup.cli" />
          <p>Dentro do arquivo (Ctrl+S salva, Ctrl+X sai):</p>
          <CopyBlock
            label="Conteúdo do config-backup.cli"
            text={`show running-config | save overwrite config.txt
copy file config.txt tftp://${host}/<identificador>/ source <IP-de-origem>`}
          />
          <p>
            Acrescente <Code>time-stamped</Code> ao final do <Code>copy</Code> se quiser que o arquivo chegue com data e hora no
            nome; sem isso, o nome é sempre <Code>config.txt</Code> (o painel guarda cada envio como uma versão separada, e
            configuração idêntica à anterior é marcada como &quot;idêntica&quot;).
          </p>
        </Step>

        <Step n={4} title="Rode ou agende">
          <p>Para rodar na hora, crie a tarefa e execute uma vez; para agendar, defina a recorrência:</p>
          <CopyBlock
            label="No DmOS"
            text={`config
  assistant-task config-backup
    action cli-file config-backup.cli
    schedule recursive hour 3 minute 0
commit

assistant-task config-backup run-now`}
          />
          <p>
            A recorrência aceita listas e faixas, por exemplo <Code>minute 0,10,20,30,40,50</Code>; use <Code>schedule once</Code>{" "}
            para uma única vez. Defina o <b>intervalo esperado</b> do equipamento no painel (em horas) para ser alertado se o
            backup atrasar.
          </p>
        </Step>

        <Step n={5} title="Confira">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link> a execução deve
            aparecer com <b>sucesso</b> e <b>verificado</b>. Se não chegar, veja no servidor{" "}
            <Code>docker compose logs -f tftp</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Conexão de IP não cadastrado — o IP de origem cadastrado não é o que chega (passo 1).</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, NAT ou firewall (passo 2). No equipamento, <Code>show assistant-task config-backup last-failure output</Code> mostra o erro.</li>
            <li>Arquivo recusado — não parece uma configuração DmOS (vazio, binário ou sem comandos como <Code>hostname</Code>, <Code>dot1q</Code>, <Code>interface</Code>).</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar uma configuração</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão desejada e clique em <b>Baixar</b>: informe a chave privada e a senha e receba o arquivo
            de configuração em texto. Passo a passo e a opção pelo terminal em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>.
          </p>
        </Step>

        <Step n={2} title="Leve o arquivo ao equipamento">
          <p>
            O receptor TFTP do H2NODE Backup só aceita <b>gravação</b>: o equipamento não consegue buscar o arquivo nele. Coloque o
            arquivo decifrado num servidor TFTP temporário da sua rede (por exemplo, no seu computador) e importe:
          </p>
          <CopyBlock label="No DmOS" text="copy file tftp://<IP-do-seu-TFTP>/config.txt config-restore.txt" />
        </Step>

        <Step n={3} title="Confira e aplique com proteção">
          <CopyBlock
            label="No DmOS"
            text={`file show config-restore.txt
config exclusive
load override config-restore.txt
show configuration diff
commit check
commit confirmed 5`}
          />
          <p>
            <Code>load override</Code> substitui toda a candidate-config pelo conteúdo do arquivo (para aplicar só um trecho use{" "}
            <Code>load merge</Code>). Nada muda até o commit, e o <Code>commit confirmed 5</Code> reverte sozinho em 5 minutos se
            a configuração cortar o seu acesso; estando tudo certo, confirme com <Code>commit</Code>.
          </p>
          <Note tone="warn">
            Confira antes o IP de gerência, as rotas e as ACLs de proteção de CPU do arquivo: um backup antigo pode trazer
            endereços diferentes dos atuais. Para descartar a candidate sem aplicar, use <Code>clear</Code>.
          </Note>
        </Step>

        <Step n={4} title="Apague os arquivos em claro">
          <p>
            A configuração tem hashes de senha e chaves. No equipamento: <Code>file delete config-restore.txt</Code>; no seu
            computador, apague o arquivo e desligue o servidor TFTP temporário.
          </p>
        </Step>
      </Card>
    </div>
  );
}

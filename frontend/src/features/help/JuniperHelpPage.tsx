import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function JuniperHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const ftpPort = q.data?.ftp_port ?? 21;
  const pasv = q.data?.ftp_passive_ports ?? "30000-30049";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Juniper (Junos): backup e restauração"
        subtitle="O Junos envia um .conf.gz por FTP a cada commit; o H2NODE Backup valida, cifra e guarda cada versão."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/settings/ftp-accounts">Configuração → Contas FTP</Link>,
            crie por exemplo <Code>juniper</Code>. A senha tem de 8 a 64 caracteres, <b>sem espaço, @, : ou /</b> — ela vai
            dentro da URL do Junos.
          </p>
        </Step>

        <Step n={2} title="Cadastre o equipamento">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/devices">FTP/TFTP</Link>: nome,
            fabricante <b>Juniper (Junos)</b>, protocolo <b>FTP</b> e o <b>IP de origem</b>, o IP com que o roteador chega ao
            servidor. Ele identifica de quem é o arquivo (se outro cadastro FTP usar o mesmo IP, escolha uma <b>Conta FTP</b>
            diferente em cada um).
          </p>
          <Note tone="warn">
            Se o roteador sai por NAT ou por outra interface, o IP que o servidor enxerga não é o da interface de gerência.
            Em caso de dúvida, tente a transferência e veja o IP no log do servidor (<Code>ftp_unknown_ip</Code>).
          </Note>
        </Step>

        <Step n={3} title="Libere o IP no firewall do servidor">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-de-origem> ftp" />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code> só para esse IP.
          </p>
        </Step>

        <Step n={4} title="Configure o Junos">
          <CopyBlock
            label="Configuração"
            text={`configure
set system archival configuration transfer-on-commit
set system archival configuration archive-sites "ftp://juniper:<senha>@${host}"
commit`}
          />
          <p>
            <Code>transfer-on-commit</Code> envia a cada commit (por isso o intervalo esperado do equipamento é{" "}
            <b>0 = sob demanda</b>). Para um envio periódico, use também{" "}
            <Code>set system archival configuration transfer-interval &lt;minutos&gt;</Code>.
          </p>
        </Step>

        <Step n={5} title="Teste">
          <CopyBlock
            label="Comando"
            text={`file copy /config/juniper.conf.gz ftp://juniper:<senha>@${host}/`}
          />
          <p>
            O resultado aparece em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>{" "}
            com <b>sucesso</b> e <b>verificado</b>. Se não chegar, veja no servidor{" "}
            <Code>docker compose logs -f ftp</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP de origem cadastrado não é o que chega (passo 2).</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, NAT ou firewall (passo 3).</li>
            <li>Conecta e não grava — conexão passiva bloqueada ({pasv}) ou senha com caractere proibido.</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar uma configuração</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão desejada e clique em <b>Baixar</b>: informe a chave privada e a senha e receba o{" "}
            <Code>.conf</Code> já descompactado. Passo a passo e a opção pelo terminal em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>.
          </p>
          <p>Confira o arquivo: deve começar com <Code>## Last commit</Code>, ter o bloco <Code>system &#123;</Code> e terminar em <Code>&#125;</Code>.</p>
        </Step>

        <Step n={2} title="Envie para o roteador">
          <CopyBlock label="Comando" text="scp juniper.conf usuario@<ip-do-roteador>:/var/tmp/juniper.conf" />
        </Step>

        <Step n={3} title="Compare e aplique com proteção">
          <CopyBlock
            label="No Junos"
            text={`configure
load override /var/tmp/juniper.conf
show | compare
commit check
commit confirmed 5`}
          />
          <p>
            <Code>load override</Code> substitui a configuração inteira (para aplicar só um trecho use{" "}
            <Code>load merge</Code> ou <Code>load replace</Code>). O <Code>commit confirmed 5</Code> volta sozinho em 5 minutos
            se a nova configuração cortar o seu acesso; estando tudo certo, confirme:
          </p>
          <CopyBlock label="Comando" text="commit" />
          <Note tone="warn">
            Nada muda no roteador até o commit. Se algo parecer errado antes dele, use <Code>rollback 0</Code>.
          </Note>
        </Step>

        <Step n={4} title="Apague o arquivo em claro">
          <p>
            A configuração tem hashes de senha e chaves. Remova de onde copiou:{" "}
            <Code>shred -u juniper.conf</Code> no seu computador e <Code>file delete /var/tmp/juniper.conf</Code> no roteador.
          </p>
          <Note>O commit da restauração dispara um novo backup (transfer-on-commit): é esperado.</Note>
        </Step>
      </Card>
    </div>
  );
}

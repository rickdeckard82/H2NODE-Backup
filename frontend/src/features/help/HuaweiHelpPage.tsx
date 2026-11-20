import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

const link = "text-brand-600 hover:underline dark:text-brand-400";

export default function HuaweiHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const ftpPort = q.data?.ftp_port ?? 21;
  const pasv = q.data?.ftp_passive_ports ?? "30000-30049";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Huawei (VRP): backup e restauração"
        subtitle="O VRP envia a configuração salva por FTP (backup-to-server); o H2NODE Backup valida, cifra e guarda cada versão."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em <Link className={link} to="/settings/ftp-accounts">Configuração → Contas FTP</Link>, crie por exemplo{" "}
            <Code>huawei</Code>. A senha tem de 8 a 64 caracteres, <b>sem espaço, @, : ou /</b>.
          </p>
        </Step>

        <Step n={2} title="Cadastre o equipamento">
          <p>
            Em <Link className={link} to="/devices">Equipamentos de rede</Link>: nome, fabricante <b>Huawei (VRP)</b>,
            protocolo <b>FTP</b> e o <b>IP de origem</b>, o IP com que o equipamento chega ao servidor. Ele identifica de
            quem é o arquivo e cada IP pertence a um único equipamento. O servidor guarda cada envio na pasta desse IP
            (o VRP manda <Code>./&lt;ip&gt;/arquivo</Code>; a pasta é criada sozinha).
          </p>
          <Note tone="warn">
            Se o equipamento sai por NAT, por uma VPN instance ou por outra interface, o IP que o servidor enxerga não é o
            da interface de gerência; fixe a origem com <Code>ftp client-source</Code> (passo 4). Em caso de dúvida, tente a transferência e veja o IP no log do servidor (<Code>ftp_unknown_ip</Code>).
          </Note>
        </Step>

        <Step n={3} title="Libere o IP no firewall do servidor">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-de-origem> ftp" />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code> só para esse IP.
          </p>
        </Step>

        <Step n={4} title="Configure o VRP">
          <CopyBlock
            label="Configuração (modo usuário)"
            text={`system-view
ftp client-source -a <IP-de-origem>
set save-configuration backup-to-server server ${host} transport-type ftp user huawei password <senha>
set save-configuration interval 1440
quit`}
          />
          <p>
            O <Code>ftp client-source -a</Code> define o endereço de origem das conexões FTP do switch: use o IP da
            loopback (ex.: <Code>192.0.2.25</Code>), o mesmo cadastrado como <b>IP de origem</b> no passo 2. Sem ele o
            switch sai pela interface mais próxima e o servidor não reconhece o equipamento (ou nem é alcançado).
          </p>
          <p>
            Com isso, cada <Code>save</Code> envia a configuração ao servidor e o <Code>interval</Code> (em minutos)
            repete o envio periodicamente. Como o envio depende de alguém salvar, cadastre o equipamento com intervalo
            esperado <b>0 = sob demanda</b> (sem alerta de atraso). Para conferir:
          </p>
          <CopyBlock label="Comando" text="display current-configuration | include backup-to-server" />
          <Note>
            O comando varia conforme o modelo e a versão (S/CE/AR/NE, V200R010 em diante). Se o seu não aceitar{" "}
            <Code>backup-to-server</Code>, use o teste manual do passo 5 por agendamento (<Code>schedule</Code>) ou outro
            sistema de automação.
          </Note>
        </Step>

        <Step n={5} title="Teste">
          <CopyBlock
            label="No equipamento"
            text={`save
ftp ${host}${ftpPort !== 21 ? ` ${ftpPort}` : ""}
  (usuário huawei e a senha)
[ftp] put vrpcfg.zip
[ftp] quit`}
          />
          <p>
            O resultado aparece em <Link className={link} to="/backups">Backups</Link> com <b>sucesso</b> e{" "}
            <b>verificado</b>. A configuração pode chegar como texto (<Code>.cfg</Code>) ou como <Code>vrpcfg.zip</Code>;
            ela é conferida pelo <Code>return</Code> final. Se não chegar, veja no servidor{" "}
            <Code>docker compose logs -f ftp</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP de origem cadastrado não é o que chega (passo 2).</li>
            <li>Sem nenhuma linha — a conexão não chega: rota, NAT, VPN instance ou firewall (passo 3).</li>
            <li>Conecta e não grava — conexão passiva bloqueada ({pasv}) ou senha com caractere proibido.</li>
            <li>Verificação com falha, &quot;sem o return final&quot; — o arquivo veio truncado; envie de novo.</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar uma configuração</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão desejada e clique em <b>Baixar</b>: informe a chave privada e a senha e receba o
            arquivo já decifrado. Passo a passo e a opção pelo terminal em{" "}
            <Link className={link} to="/help/decrypt">Baixar e decifrar</Link>.
          </p>
          <p>Se vier <Code>vrpcfg.zip</Code>, descompacte: o <Code>vrpcfg.cfg</Code> deve terminar em <Code>return</Code>.</p>
        </Step>

        <Step n={2} title="Envie para o equipamento">
          <p>Use SFTP/SCP (preferível) ou o FTP do seu laboratório; o destino é o flash:</p>
          <CopyBlock label="Comando" text="sftp usuario@<ip-do-equipamento>   # put vrpcfg.cfg flash:/restaurar.cfg" />
        </Step>

        <Step n={3} title="Aplique">
          <CopyBlock
            label="No VRP"
            text={`startup saved-configuration restaurar.cfg
display startup
reboot`}
          />
          <p>
            Confira em <Code>display startup</Code> que o próximo arquivo de configuração é o <Code>restaurar.cfg</Code>{" "}
            antes de reiniciar. Se o seu modelo suportar, dá para aplicar sem reiniciar com{" "}
            <Code>configuration replace file flash:/restaurar.cfg</Code> (compare antes com{" "}
            <Code>display configuration replace</Code>, quando disponível).
          </p>
          <Note tone="warn">
            O <Code>reboot</Code> derruba o equipamento por alguns minutos. Faça com acesso de console ou fora de banda
            e responda <Code>N</Code> à pergunta de salvar a configuração atual, para não sobrescrever o que você acabou de enviar.
          </Note>
        </Step>

        <Step n={4} title="Apague o arquivo em claro">
          <p>
            A configuração tem hashes de senha e chaves. Remova de onde copiou: <Code>shred -u vrpcfg.cfg</Code> no seu
            computador e <Code>delete /unreserved flash:/restaurar.cfg</Code> no equipamento (depois que ele subir).
          </p>
        </Step>
      </Card>
    </div>
  );
}

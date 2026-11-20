import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { routerosUserCommands, serverAddress } from "../mikrotik/routeros";
import { Code, Note, Step } from "./parts";

const link = "text-brand-600 hover:underline dark:text-brand-400";

export default function MikrotikHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const address = serverAddress(q.data?.net_host);

  return (
    <div className="space-y-4">
      <PageHeader
        title="MikroTik (RouterOS): backup e restauração"
        subtitle="O H2NODE Backup entra por SSH em cada MikroTik, roda /export, valida, cifra e guarda cada versão."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Como funciona</h2>
        <p className="text-sm">
          Ao contrário dos outros equipamentos, o MikroTik não envia nada: o serviço <Code>puller</Code> do servidor
          conecta por SSH no intervalo configurado, roda <Code>/export show-sensitive</Code> (no RouterOS 6, <Code>/export</Code>,
          que já traz tudo) e cifra a saída na memória com a chave pública. Nada fica em claro no disco do servidor. Versões em
          que só a linha de data mudou são marcadas como <b>idênticas ao backup anterior</b>.
        </p>
        <Note>
          A chave SSH de cada MikroTik é fixada na primeira coleta bem-sucedida. Se ela mudar depois (equipamento trocado,
          netinstall, chave regenerada), a coleta para antes de mandar a senha e o painel pede para você aceitar a nova chave.
        </Note>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Crie o usuário de acesso no painel">
          <p>
            Em <Link className={link} to="/mikrotik/credentials">MikroTik → Usuário de acesso</Link>, crie uma credencial
            (ex.: usuário <Code>h2node-backup</Code>, porta 22). A senha tem de 8 a 64 caracteres, <b>sem espaço, aspas, \, $ ou ?</b>.
            Ela fica cifrada no servidor e não volta para a tela. Ao salvar, o painel mostra os comandos do passo 2 já com a senha.
          </p>
        </Step>

        <Step n={2} title="Crie o mesmo usuário em cada MikroTik">
          <CopyBlock label="Comandos" text={routerosUserCommands("h2node-backup", null, address)} />
          <p>
            O grupo só tem <Code>ssh</Code>, <Code>read</Code> e <Code>sensitive</Code>: o usuário entra, lê e exporta, mas não
            altera nada. O <Code>sensitive</Code> faz a exportação trazer senhas de PPPoE/Wi-Fi, chaves IPsec etc.; sem ele o
            backup sai incompleto. O <Code>address=</Code> só deixa o usuário entrar a partir do IP do servidor.
          </p>
          <Note tone="warn">
            Se o servidor chega ao MikroTik por NAT, o IP que o MikroTik vê é o do NAT. Use esse IP no <Code>address=</Code>,
            senão a coleta acusa <i>usuário ou senha recusados</i>.
          </Note>
        </Step>

        <Step n={3} title="Libere o SSH para o servidor">
          <p>
            Confira em <Code>/ip service print</Code> se o serviço <Code>ssh</Code> está ativo, em qual porta e se o campo{" "}
            <Code>address</Code> inclui o servidor. Se houver filtro na chain <Code>input</Code>, aceite o servidor antes do drop:
          </p>
          <CopyBlock
            label="Firewall"
            text={`/ip firewall filter add chain=input protocol=tcp dst-port=22 src-address=${address} action=accept comment="H2NODE Backup"`}
          />
          <p>
            A regra entra no fim da lista: arraste-a para cima do drop no Winbox (ou <Code>/ip firewall filter move</Code>). Troque
            o 22 se o SSH usar outra porta. No servidor não há porta para abrir: a conexão sai dele para o MikroTik.
          </p>
        </Step>

        <Step n={4} title="Cadastre os MikroTik">
          <p>
            Em <Link className={link} to="/mikrotik">MikroTik → Hosts</Link>, use <b>Novo MikroTik</b> (nome, IP, porta se for
            diferente da credencial, intervalo de coleta) ou <b>Importar lista</b>, com um host por linha:
          </p>
          <CopyBlock label="Lista" text={"10.0.0.1 RB-Core\n10.0.0.2:2202 RB-POP-Centro\n# linhas com # são ignoradas\n10.0.0.3"} />
          <p>A primeira coleta sai em até 30 segundos. Depois, uma a cada intervalo (padrão 24 h).</p>
        </Step>

        <Step n={5} title="Confira">
          <p>
            A versão aparece em <Link className={link} to="/backups">Backups</Link> com <b>sucesso</b> e <b>verificado</b>. Use{" "}
            <b>Coletar agora</b> para repetir na hora. Se falhar, a mensagem aparece na lista de hosts e em{" "}
            <Code>docker compose logs -f puller</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li><i>sem conexão / tempo esgotado</i>: rota, firewall ou <Code>/ip service</Code> (passo 3).</li>
            <li><i>usuário ou senha recusados</i>: usuário não criado, senha diferente ou <Code>address=</Code> errado (passo 2).</li>
            <li><i>o RouterOS respondeu com erro</i>: o grupo não tem as políticas <Code>read</Code>/<Code>sensitive</Code>.</li>
            <li><i>a chave de host SSH mudou</i>: veja a nota acima. Aceite só se souber por que mudou.</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar uma configuração</h2>

        <Step n={1} title="Baixe e decifre">
          <p>
            Em Backups, abra a versão e clique em <b>Baixar</b>: o arquivo <Code>&lt;equipamento&gt;.rsc</Code> sai decifrado
            (ver <Link className={link} to="/help/decrypt">Baixar e decifrar</Link>). É texto: dá para conferir e copiar só um
            trecho (ex.: <Code>/ip firewall filter</Code>) e colar no terminal.
          </p>
        </Step>

        <Step n={2} title="Envie o arquivo para o MikroTik">
          <p>Arraste o arquivo para <b>Files</b> no Winbox, ou:</p>
          <CopyBlock label="Comando" text="scp RB-Core.rsc admin@<ip-do-mikrotik>:/" />
        </Step>

        <Step n={3} title="Restauração completa: aplique sobre a configuração zerada">
          <CopyBlock
            label="No RouterOS"
            text="/system reset-configuration no-defaults=yes skip-backup=yes run-after-reset=RB-Core.rsc"
          />
          <p>
            O equipamento reinicia vazio e executa o script. Importar por cima da configuração atual, com{" "}
            <Code>/import file-name=RB-Core.rsc</Code>, costuma parar no primeiro item repetido: use isso só para arquivos com
            trechos.
          </p>
          <Note tone="warn">
            Faça com acesso de console, MAC-Winbox ou fora de horário: um erro no script deixa o equipamento sem IP. A exportação
            não leva as senhas dos usuários do RouterOS: recrie-as depois. Em hardware diferente, confira os nomes das interfaces
            (<Code>default-name</Code>) antes.
          </Note>
        </Step>

        <Step n={4} title="Apague o arquivo em claro">
          <p>
            O .rsc tem senhas e chaves. Remova-o do seu computador e do MikroTik (<Code>/file remove RB-Core.rsc</Code>).
          </p>
        </Step>
      </Card>
    </div>
  );
}

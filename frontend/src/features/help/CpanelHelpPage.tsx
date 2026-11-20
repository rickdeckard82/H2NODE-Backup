import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function CpanelHelpPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="cPanel/WHM: backup e restauração"
        subtitle="O agente cifra cada backup de conta (.tar.gz) como está e o envia por rsync/SSH, um arquivo de cada vez."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            O próprio cPanel continua gerando os backups por conta em <Code>/backup/cpanel/AAAA-MM-DD/accounts/*.tar.gz</Code> (e a
            pasta <Code>system</Code>). O agente do H2NODE Backup roda <b>depois</b> dele, no crontab do root, e envia <b>só a pasta
            da data de hoje</b> (<Code>@today</Code>). Se a pasta de hoje não existir (o backup do cPanel falhou ou atrasou), o
            agente acusa falha em vez de reenviar a de ontem.
          </li>
          <li>
            Agente 1.3.0 ou mais novo: confere se <b>todas as contas</b> do servidor (<Code>/var/cpanel/users</Code>) têm backup na
            pasta do dia. Cada conta que faltar aparece como <b>falhou</b> na execução (resultado <i>parcial</i>), em vez de a
            execução parecer completa. Contas com backup desligado no WHM, suspensas (se o WHM não copia suspensas) e criadas há
            menos de 24 h não contam.
          </li>
          <li>
            Cada conta é <b>cifrada como está</b> (sem refazer tar nem compressão), enviado e só então a <b>cópia cifrada</b> é
            apagada, antes de passar ao próximo. A pasta de trabalho só precisa caber o <b>maior</b> arquivo.
            <b>Os backups do cPanel em <Code>/backup/cpanel</Code> nunca são alterados nem apagados</b>: o agente só os lê, e
            a retenção de lá continua sendo a do próprio cPanel.
          </li>
          <li>
            Não usa FTP: o rsync/SSH cifra o transporte, retoma envio interrompido e nada fica em claro no servidor de
            backup. (Backups de contas têm e-mails, bancos e senhas dos clientes.)
          </li>
          <li>
            No servidor de backup, o worker confere o SHA-256, decifra, valida o gzip até o fim e compara o hash do conteúdo
            com o calculado no cPanel.
          </li>
        </ul>
        <Note tone="warn">
          Planeje o espaço: um dia completo do cPanel pode passar de 400 GB e o <Code>.tar.gz</Code> não comprime nem
          deduplica. Defina com cuidado quantas cópias manter (retenção do servidor cadastrado), e lembre que a conferência
          lê todos os arquivos (a verificação de centenas de GB leva horas).
        </Note>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Configurar</h2>

        <Step n={1} title="Instale o agente no servidor cPanel (como root)">
          <p>
            Igual a <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/linux">Servidor Linux</Link>
            : copie a pasta <Code>agent/</Code> e rode o instalador. Use a <b>versão 1.3.0 ou mais nova</b> do agente (entende{" "}
            <Code>BACKUP_FILES</Code> e confere as contas do dia).
          </p>
          <CopyBlock label="Comandos" text={`scp -r agent/ root@<ip-do-cpanel>:/root/h2node-agent\n# no cPanel, como root:\ncd /root/h2node-agent && ./install.sh --cron "0 22 * * *"`} />
          <p>
            Escolha o horário <b>depois</b> que o backup do cPanel termina, com folga. O backup do WHM começa às 02:00 (padrão) e a
            duração muda muito de um dia para outro: num servidor grande ele pode terminar de madrugada num dia e no meio da
            tarde no outro. Por isso o recomendado é rodar o agente <b>à noite</b> (ex.: 22:00): o WHM já terminou e os dois
            não disputam o disco. A data de <Code>@today</Code> é a do relógio do servidor do cPanel, então o agente tem de rodar
            no <b>mesmo dia</b> em que o backup do WHM começou.
          </p>
          <p>
            <b>Backup do WHM que entra pela noite?</b> Rode o agente no <b>dia seguinte</b> e use <Code>@yesterday</Code> no
            lugar de <Code>@today</Code> (agente 1.4.0 ou mais novo). O cron acompanha os dias do WHM com um dia a mais. Por
            exemplo, WHM na segunda, quarta e sexta, e agente na terça, quinta e sábado:
          </p>
          <CopyBlock label="Comando" text={`cd /root/h2node-agent && ./install.sh --cron "0 22 * * 2,4,6"`} />
          <p>
            Ajuste o <b>intervalo esperado</b> do servidor no painel ao maior espaço entre dois envios (no exemplo, 72 h, de
            sábado para terça). Assim ele não fica &quot;atrasado&quot; nos dias sem backup.
          </p>
          <p>
            Arquivos alterados há menos de 10 minutos (<Code>FILES_MIN_AGE_MINUTES</Code>) ainda estão sendo gravados e não são
            enviados. O horário do WHM fica em WHM → Server Configuration → <i>Configure cPanel Cron Jobs</i> (comando{" "}
            <Code>/usr/local/cpanel/bin/backup</Code>); os dias, em Backup Configuration.
          </p>
        </Step>

        <Step n={2} title="Cadastre o servidor e libere o IP">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/clients">Servidores</Link> → Novo
            servidor, com a chave SSH do agente, e libere o IP de saída do cPanel:
          </p>
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh client <IP-público-do-cpanel>" />
          <p>
            Ajuste a <b>retenção</b> (dias e mínimo de versões) ao espaço que você tem.
          </p>
        </Step>

        <Step n={3} title="Edite /etc/h2node-backup/agent.conf">
          <CopyBlock
            label="agent.conf (trechos)"
            text={`# Pasta de trabalho: precisa caber o MAIOR arquivo cifrado (+1 GB) — use uma partição grande
WORK_DIR="/backup/h2node-work"

# Cada conta do cPanel, só da pasta de HOJE (ex.: /backup/cpanel/2026-10-16/accounts/*.tar.gz)
BACKUP_FILES=(
  "/backup/cpanel/@today/accounts/*.tar.gz"
)

# A pasta "system" é pequena: vai inteira (um único .tar.gz cifrado)
BACKUP_PATHS=(
  "/etc"
  "/backup/cpanel/@today/system"
)

# opcional: não limite o envio durante a noite, ou limite em KB/s
BWLIMIT=""`}
          />
          <Note>
            O que está em <Code>BACKUP_FILES</Code> não passa pelo tar: cada arquivo é cifrado como está. Pastas inteiras vão em{" "}
            <Code>BACKUP_PATHS</Code>. Com o agente no dia seguinte ao WHM, troque <Code>@today</Code> por{" "}
            <Code>@yesterday</Code> nas duas listas. Use <Code>@latest</Code> no lugar de <Code>@today</Code> só se quiser a pasta
            datada mais recente, qualquer que seja a data.
          </Note>
          <Note>
            <b>O token tem de ser o mesmo nas duas listas.</b> Com <Code>@yesterday</Code> na pasta <Code>system</Code> e{" "}
            <Code>@today</Code> nas contas, uma delas sempre procura o dia errado: o backup falha com "nenhum arquivo encontrado
            — @today = AAAA-MM-DD; pastas datadas em /backup/cpanel/: …" (agente 1.4.1 mostra a data procurada e as pastas que
            existem; o <Code>test</Code> também, a partir do 1.4.2).
          </Note>
          <Note>
            <b>O WHM pula dias</b> (ex.: há 2026-10-21 e 2026-10-23, mas não 2026-10-22)? Então nenhuma data fixa serve sempre:
            use <Code>@latest</Code> nas duas listas e agende o agente depois do horário em que o backup do WHM costuma
            terminar. Se a pasta mais recente ainda estiver sendo gravada, as contas que faltarem aparecem como falha.
          </Note>
        </Step>

        <Step n={4} title="Teste e rode o primeiro backup">
          <CopyBlock label="No cPanel" text={`sudo h2node-backup-agent test   # lista quantos arquivos achou e confere o espaço em WORK_DIR\nsudo h2node-backup-agent run`} />
          <p>
            O <Code>test</Code> avisa se o <Code>WORK_DIR</Code> não comporta o maior arquivo e lista as contas sem backup na
            pasta de hoje. Acompanhe o envio em <Code>/var/log/h2node-backup.log</Code>.
          </p>
        </Step>

        <Step n={5} title="Se faltarem contas num dia">
          <p>
            Veja se o WHM terminou antes de o agente rodar: compare a hora da última conta gravada com a hora de início do agente
            (o log do agente está em UTC; o <Code>ls</Code>, no horário do servidor).
          </p>
          <CopyBlock
            label="No cPanel"
            text={`ls /backup/cpanel/AAAA-MM-DD/accounts | wc -l
ls -l --time-style=+%F_%T /backup/cpanel/AAAA-MM-DD/accounts | sort -k6 | tail -1
grep 'AAAA-MM-DD' /var/log/h2node-backup.log | grep -E 'início|enviado|FALHOU'
ls -t /usr/local/cpanel/logs/cpbackup/ | head -3`}
          />
          <p>
            Agente antes do fim do WHM: mova o cron para mais tarde. Contas faltando na própria pasta do WHM: veja o log do
            backup do cPanel (espaço em disco é a causa mais comum). Para reenviar um dia, troque <Code>@today</Code> pela data
            (ex.: <Code>2026-10-17</Code>) no <Code>agent.conf</Code>, rode <Code>h2node-backup-agent run</Code> e volte ao{" "}
            <Code>@today</Code>.
          </p>
        </Step>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Encontrar uma conta ou domínio</h2>
        <p>
          Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/accounts">Contas cPanel</Link> há uma linha por
          conta, com a cópia mais recente, o tamanho, o número de versões e a verificação. Digite parte do nome da conta ou do
          domínio na busca; clicar abre o <b>histórico</b> da conta, com cada versão e os botões Baixar e .gpg. A caixa de busca de{" "}
          <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link> também filtra as execuções que
          contêm uma conta.
        </p>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar uma conta</h2>

        <Step n={1} title="Baixe o .gpg da conta">
          <p>
            Contas grandes não cabem no navegador: o botão <Code>.gpg</Code> baixa o arquivo cifrado, mas o mais prático é copiar
            direto do servidor, em <Code>BACKUP_STORAGE_PATH/store/&lt;servidor&gt;/&lt;execução&gt;/NN-file-conta.tar.gz.gpg</Code>.
          </p>
        </Step>

        <Step n={2} title="Decifre numa máquina segura (com a chave privada)">
          <CopyBlock
            label="Comandos"
            text={`export GNUPGHOME=$(mktemp -d)
gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass --import backup-key.sec.asc
gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass -d 05-file-conta.tar.gz.gpg > conta.tar.gz`}
          />
          <p>
            Veja também <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>.
            Confira o espaço: o arquivo decifrado ocupa o tamanho original.
          </p>
        </Step>

        <Step n={3} title="Restaure no cPanel">
          <CopyBlock label="No cPanel, como root" text={`cp conta.tar.gz /home/\n/scripts/restorepkg /home/conta.tar.gz`} />
          <p>
            O <Code>restorepkg</Code> é o restaurador oficial do cPanel: recria a conta (ou sobrescreve, se já existir) a partir
            do <Code>.tar.gz</Code>. Para só uma parte (um site, um banco), extraia o arquivo e copie o que precisa.
          </p>
          <Note tone="warn">
            Apague <Code>conta.tar.gz</Code> em claro quando terminar (<Code>shred -u</Code>) e desligue o chaveiro temporário
            do <Code>GNUPGHOME</Code>.
          </Note>
        </Step>
      </Card>
    </div>
  );
}

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
            O próprio cPanel continua gerando os backups por conta em <Code>/backup/cpanel/AAAA-MM-DD/accounts/*.tar.gz</Code>.
            O agente do Pulse Backup roda <b>depois</b> dele, no crontab do root, e envia a pasta datada mais recente.
          </li>
          <li>
            Cada arquivo é <b>cifrado como está</b> (sem refazer tar nem compressão), enviado e só então a <b>cópia cifrada</b> é
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
            : copie a pasta <Code>agent/</Code> e rode o instalador. Use a <b>versão 1.1.0 ou mais nova</b> do agente (é a
            que entende <Code>BACKUP_FILES</Code>).
          </p>
          <CopyBlock label="Comandos" text={`scp -r agent/ root@<ip-do-cpanel>:/root/pulse-agent\n# no cPanel, como root:\ncd /root/pulse-agent && ./install.sh --cron "0 6 * * *"`} />
          <p>
            Escolha o horário <b>depois</b> que o backup do cPanel termina, para não enviar um arquivo ainda em gravação (o
            servidor acusaria gzip truncado).
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

        <Step n={3} title="Edite /etc/pulse-backup/agent.conf">
          <CopyBlock
            label="agent.conf (trechos)"
            text={`# Pasta de trabalho: precisa caber o MAIOR arquivo cifrado (+1 GB) — use uma partição grande
WORK_DIR="/backup/pulse-work"

# Backups de conta do cPanel; "@latest" = a pasta datada mais recente
BACKUP_FILES=(
  "/backup/cpanel/@latest/accounts/*.tar.gz"
  # "/backup/cpanel/@latest/system/*"
)

# opcional: não limite o envio durante a noite, ou limite em KB/s
BWLIMIT=""`}
          />
          <Note>
            Pastas como <Code>/etc</Code> continuam em <Code>BACKUP_PATHS</Code>. O que está em <Code>BACKUP_FILES</Code> não
            passa pelo tar: cada arquivo é cifrado como está.
          </Note>
        </Step>

        <Step n={4} title="Teste e rode o primeiro backup">
          <CopyBlock label="No cPanel" text={`sudo pulse-backup-agent test   # lista quantos arquivos achou e confere o espaço em WORK_DIR\nsudo pulse-backup-agent run`} />
          <p>
            O <Code>test</Code> avisa se o <Code>WORK_DIR</Code> não comporta o maior arquivo. Em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link> cada conta aparece
            como um componente do tipo <b>Arquivo</b>. Acompanhe o envio em <Code>/var/log/pulse-backup.log</Code>.
          </p>
        </Step>
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

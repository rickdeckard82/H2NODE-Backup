import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function LinuxHelpPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Servidor Linux: backup e restauração"
        subtitle="Um agente no crontab do root cifra pastas e bancos com a chave pública do servidor e os envia por rsync/SSH."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            O agente junta as <b>pastas</b> escolhidas e os <b>bancos</b> (MySQL/MariaDB, PostgreSQL, SQL Server). Cada pasta ou
            banco vira uma parte, cifrada na hora com <b>GPG</b> (só a chave <i>pública</i> está no cliente).
          </li>
          <li>
            Envia as partes e um <Code>manifest.json</Code> por rsync/SSH (porta 2222) e <b>apaga tudo localmente</b>. A chave SSH
            do cliente só escreve na própria pasta: não lê, não lista, não apaga.
          </li>
          <li>
            O servidor confere SHA-256 e tamanho, decifra em memória e <b>testa o conteúdo</b> (tar íntegro, dump completo). O
            resultado aparece em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>.
          </li>
        </ul>
        <Note>
          Não é preciso clonar o repositório no cliente: só a pasta <Code>agent/</Code> (3 arquivos). Ele precisa de{" "}
          <Code>bash</Code>, <Code>gpg</Code>, <Code>rsync</Code>, <Code>ssh</Code>, <Code>tar</Code>, <Code>gzip</Code> e{" "}
          <Code>flock</Code>; o instalador confere e diz o que falta.
        </Note>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Criar o backup</h2>

        <Step n={1} title="Instale o agente no servidor cliente (como root)">
          <p>No seu computador ou no servidor de backup, copie a pasta do agente para o cliente e instale:</p>
          <CopyBlock
            label="Comandos"
            text={`scp -r agent/ root@<ip-do-cliente>:/root/pulse-agent
# no cliente, como root:
cd /root/pulse-agent && ./install.sh --cron "30 2 * * *"`}
          />
          <p>
            O instalador copia o agente para <Code>/usr/local/sbin/pulse-backup-agent</Code> (com atalho em{" "}
            <Code>/usr/bin</Code>), cria <Code>/etc/pulse-backup/</Code>, agenda no crontab do root (aqui, todo dia às 02:30) e gera a
            chave SSH do agente.
            No fim ele imprime a <b>chave pública SSH</b> (também em <Code>/etc/pulse-backup/id_ed25519.pub</Code>).
          </p>
        </Step>

        <Step n={2} title="Cadastre o servidor no painel">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/clients">Servidores</Link> → <b>Novo
            servidor</b>: nome, <b>identificador</b> (minúsculas, números e hífen; não muda depois) e a chave pública SSH do passo
            anterior. Defina o <b>intervalo esperado</b> (horas) para ser alertado se o backup atrasar e a <b>retenção</b>
            (dias a guardar e mínimo de versões a manter).
          </p>
        </Step>

        <Step n={3} title="Libere o IP do cliente no firewall do servidor de backup">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh client <IP-público-de-saída-do-cliente>" />
          <Note tone="warn">
            O que vale é o IP com que o cliente <b>chega</b> ao servidor. Se ele sai por NAT, é o IP público do NAT, não o interno.
            Descubra no cliente com <Code>curl -s ifconfig.me</Code>. IP errado aparece como <i>timeout</i> na porta 2222, porque o
            ufw descarta em silêncio.
          </Note>
        </Step>

        <Step n={4} title="Grave a configuração no cliente">
          <p>
            Na linha do servidor, o botão <b>Agente</b> mostra, prontos para copiar, o <Code>agent.conf</Code>, a linha do{" "}
            <Code>known_hosts</Code> e o download da chave pública GPG. Grave em <Code>/etc/pulse-backup/</Code>:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>agent.conf</Code> (modo 600; o agente se recusa a rodar se não for root:600);</li>
            <li><Code>known_hosts</Code> (fixa a chave do servidor);</li>
            <li><Code>backup-key.pub.asc</Code> (chave pública GPG).</li>
          </ul>
          <p>
            No <Code>agent.conf</Code> ajuste <Code>BACKUP_PATHS</Code> (comece só com <Code>/etc</Code>) e, se houver bancos, ligue{" "}
            <Code>MYSQL_ENABLED</Code>, <Code>POSTGRES_ENABLED</Code> ou <Code>MSSQL_ENABLED</Code>. Exclusões vão em{" "}
            <Code>EXCLUDES</Code>. Para enviar arquivos que <b>já existem</b> (como os backups de conta do cPanel) use{" "}
            <Code>BACKUP_FILES</Code>: veja <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/cpanel">cPanel / WHM</Link>.
          </p>
          <Note>
            O agente só <b>lê</b> as pastas e arquivos de origem: nunca os altera nem apaga. Apaga apenas as cópias cifradas que ele
            mesmo criou na pasta de trabalho (<Code>WORK_DIR</Code>).
          </Note>
        </Step>

        <Step n={5} title="Teste e rode o primeiro backup">
          <CopyBlock label="No cliente" text={`sudo pulse-backup-agent test   # confere config, chave, cifra, pastas e conexão\nsudo pulse-backup-agent run    # faz o backup agora`} />
          <Note>
            Se aparecer <Code>command not found</Code>, o <Code>PATH</Code> do root/sudo não inclui{" "}
            <Code>/usr/local/sbin</Code>: use o caminho completo <Code>/usr/local/sbin/pulse-backup-agent</Code> ou crie o atalho{" "}
            <Code>ln -s /usr/local/sbin/pulse-backup-agent /usr/bin/pulse-backup-agent</Code> (o instalador novo já faz isso).
          </Note>
          <p>
            Para mudar o horário depois, edite o crontab do root (<Code>crontab -e</Code>): reexecutar o instalador não altera a linha
            existente.
          </p>
          <p>
            A execução aparece em Backups com <b>sucesso</b> e <b>verificado</b>. O log do agente fica em{" "}
            <Code>/var/log/pulse-backup.log</Code>.
          </p>
        </Step>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Se o teste falhar</h2>
        <ul className="list-disc space-y-1.5 pl-5">
          <li>
            <b>command not found</b> — veja o aviso do passo anterior (atalho em <Code>/usr/bin</Code>).
          </li>
          <li>
            <b>Connection timed out</b> na 2222 — o ufw está descartando: o IP de saída do cliente não foi liberado (passo 3). No
            servidor, <Code>sudo tcpdump -ni any &apos;tcp port 2222&apos;</Code> mostra a origem real. Confira também o DNS do{" "}
            <Code>SERVER_HOST</Code> e firewalls no caminho.
          </li>
          <li>
            <b>Permission denied (publickey)</b> — a rede está certa, mas a chave SSH do agente não está cadastrada (ou foi colada
            incompleta) no servidor do painel.
          </li>
          <li>
            <b>Host key verification failed</b> — o <Code>known_hosts</Code> não tem a chave atual do servidor; copie a linha de novo
            pelo botão Agente.
          </li>
          <li>
            <b>Chave GPG / fingerprint</b> — o <Code>GPG_FINGERPRINT</Code> do <Code>agent.conf</Code> precisa ser o da chave
            pública baixada (Configuração → Chaves e servidor).
          </li>
        </ul>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Restaurar</h2>

        <Step n={1} title="Baixe e decifre as partes">
          <p>
            Em Backups, abra a execução. Para arquivos pequenos use <b>Baixar</b> (decifra no navegador). Pastas e dumps grandes são
            melhores com o <Code>gpg</Code> no terminal. Veja{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>. Faça o
            ensaio com a cópia <b>offline</b> da chave privada: é a única prova de que ela e a senha estão corretas.
          </p>
        </Step>

        <Step n={2} title="Pastas">
          <p>Restaure primeiro numa pasta de apoio, confira e só depois copie para o lugar definitivo.</p>
          <CopyBlock
            label="Comandos"
            text={`mkdir -p /restore
gpg ... -d 01-files-etc.tar.gz.gpg | tar -xzp --numeric-owner -C /restore

# um arquivo só:
gpg ... -d 01-files-etc.tar.gz.gpg | tar -xz -C /restore etc/nginx/nginx.conf`}
          />
        </Step>

        <Step n={3} title="Bancos">
          <CopyBlock
            label="Comandos"
            text={`# MySQL / MariaDB (o dump tem CREATE DATABASE/USE)
gpg ... -d 03-mysql-loja.sql.gz.gpg | gunzip | mysql

# PostgreSQL (globais primeiro; o dump do banco tem --create)
gpg ... -d 05-postgresql-globals.sql.gz.gpg | gunzip | sudo -u postgres psql
gpg ... -d 06-postgresql-erp.sql.gz.gpg     | gunzip | sudo -u postgres psql -d postgres

# SQL Server
gpg ... -d 07-mssql-ERP.bak.gz.gpg | gunzip > /var/opt/mssql/data/ERP.bak
chown mssql: /var/opt/mssql/data/ERP.bak
sqlcmd -S localhost -U sa -C -Q "RESTORE DATABASE [ERP] FROM DISK = N'/var/opt/mssql/data/ERP.bak' WITH REPLACE"`}
          />
          <Note tone="warn">
            Restaurar um banco por cima de um em uso sobrescreve dados atuais. Em caso de dúvida, restaure num servidor de teste
            primeiro.
          </Note>
        </Step>
      </Card>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function FtpFilesHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const host = q.data?.net_host || "<servidor>";
  const ftpPort = q.data?.ftp_port ?? 21;
  const pasv = q.data?.ftp_passive_ports ?? "30000-30049";
  const maxMb = q.data?.net_files_max_mb ?? 4096;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Arquivos e bancos por FTP"
        subtitle="Um servidor ou serviço envia dumps .sql, configurações e arquivos .zip por FTP; o Pulse Backup testa, cifra e guarda cada versão."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Use quando não dá para instalar o agente (ou o serviço já gera os próprios arquivos): o servidor envia por FTP e cada
            arquivo vira uma <b>versão</b> em Backups. O servidor é identificado pelo <b>IP de origem</b>, como os equipamentos de
            rede.
          </li>
          <li>
            Ao chegar, o arquivo é <b>testado pela extensão</b>, <b>cifrado</b> com a chave pública GPG e o original em claro é
            apagado. Arquivo igual ao anterior (mesmo nome) aparece como &quot;idêntico ao backup anterior&quot;.
          </li>
          <li>
            Limite por arquivo: <b>{maxMb} MB</b> (<Code>NET_FILES_MAX_MB</Code> no <Code>.env</Code> do servidor de backup).
          </li>
        </ul>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr>
                <th className="th">Arquivo</th>
                <th className="th">O que é testado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              <tr>
                <td className="td font-mono">.sql, .sql.gz</td>
                <td className="td">
                  Dump do <Code>mysqldump</Code>/<Code>mariadb-dump</Code> ou <Code>pg_dump</Code>/<Code>pg_dumpall</Code> com o
                  comentário de fim (dump interrompido falha). SQL sem o cabeçalho dessas ferramentas fica com <b>aviso</b>.
                </td>
              </tr>
              <tr>
                <td className="td font-mono">.zip</td>
                <td className="td">CRC de todos os arquivos de dentro (zip com senha: aviso, conteúdo não testado).</td>
              </tr>
              <tr>
                <td className="td font-mono">.tar.gz, .tgz, .gz</td>
                <td className="td">gzip íntegro até o fim; no tar, todas as entradas legíveis.</td>
              </tr>
              <tr>
                <td className="td font-mono">.pdf</td>
                <td className="td">Cabeçalho <Code>%PDF</Code> e marcador <Code>%%EOF</Code> no fim.</td>
              </tr>
              <tr>
                <td className="td font-mono">.conf, .txt, .csv, .cfg, .ini, .json…</td>
                <td className="td">Texto, sem bytes binários.</td>
              </tr>
              <tr>
                <td className="td">outros</td>
                <td className="td">Só guardados (não vazios).</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Configurar</h2>

        <Step n={1} title="Crie a conta FTP">
          <p>
            Em{" "}
            <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/settings/ftp-accounts">
              Configuração → Contas FTP
            </Link>
            , por exemplo <Code>arquivos</Code>. Senha de 8 a 64 caracteres, sem espaço, <Code>@</Code>, <Code>:</Code> ou{" "}
            <Code>/</Code>.
          </p>
        </Step>

        <Step n={2} title="Cadastre o servidor">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/devices">FTP/TFTP</Link> → <b>Novo
            cadastro</b>: tipo <b>Arquivos e bancos (FTP)</b>, protocolo <b>FTP</b> e o <b>IP de origem</b> com que o servidor chega
            aqui (se sair por NAT, o IP público do NAT). Intervalo esperado: o do agendamento (ex.: <b>24</b> h), para ser alertado
            se o envio parar.
          </p>
        </Step>

        <Step n={3} title="Libere o IP no firewall do servidor de backup">
          <CopyBlock label="Comando" text="sudo ./scripts/ufw-setup.sh device <IP-de-origem> ftp" />
          <p>
            Abre a porta {ftpPort} e a faixa passiva <Code>{pasv}</Code> só para esse IP.
          </p>
        </Step>

        <Step n={4} title="Agende o envio no servidor de origem">
          <p>
            Guarde a senha num <Code>~/.netrc</Code> (modo 600), fora da linha de comando, e use <Code>curl</Code> (ou{" "}
            <Code>lftp</Code>). Exemplo de script para o cron do root:
          </p>
          <CopyBlock
            label="/root/.netrc"
            text={`machine ${host} login arquivos password <SENHA-FTP>`}
          />
          <CopyBlock
            label="/usr/local/sbin/backup-ftp.sh"
            text={`#!/bin/bash
set -euo pipefail
D=/var/backups/ftp
mkdir -p -m 700 "$D" && cd "$D"

# bancos (SEM --skip-comments: o comentário final prova que o dump terminou)
mysqldump --single-transaction --routines --triggers --events --databases erp > erp.sql
sudo -u postgres pg_dump app > app.sql

# arquivos
zip -q -r documentos.zip /srv/documentos
cp /etc/nginx/nginx.conf nginx.conf

for f in erp.sql app.sql documentos.zip nginx.conf; do
  curl -sS --fail --ftp-pasv --netrc -T "$f" ftp://${host}/
done
rm -f erp.sql app.sql documentos.zip nginx.conf`}
          />
          <CopyBlock
            label="Comandos"
            text={`chmod 600 /root/.netrc
chmod 700 /usr/local/sbin/backup-ftp.sh
( crontab -l 2>/dev/null; echo "30 2 * * * /usr/local/sbin/backup-ftp.sh" ) | crontab -`}
          />
          <Note>
            Envie só depois que o arquivo estiver pronto (dump terminado, zip fechado): um arquivo pela metade é guardado como
            falha. Use sempre o mesmo nome para o mesmo arquivo (ou nome + data no fim, como <Code>erp_20261019.sql</Code>):
            é assim que o painel compara com a versão anterior.
          </Note>
          <Note tone="warn">
            FTP trafega em claro, inclusive a senha e o conteúdo, até chegar aqui. Use rede interna ou VPN entre a origem e o
            servidor de backup. Ao chegar, o arquivo é cifrado e o original apagado.
          </Note>
        </Step>

        <Step n={5} title="Confira">
          <p>
            Rode o script uma vez e veja em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>{" "}
            um item por arquivo com <b>sucesso</b> e <b>verificado</b>. No servidor de backup:{" "}
            <Code>docker compose logs -f ftp</Code>.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><Code>ftp_unknown_ip</Code> — o IP que chega não é o cadastrado (passo 2).</li>
            <li>Conecta e não grava — a faixa passiva {pasv} está bloqueada (passo 3).</li>
            <li><Code>ftp_file_too_large</Code> — o arquivo passou de {maxMb} MB e foi descartado.</li>
            <li><b>dump incompleto</b> — o dump foi interrompido ou gerado com <Code>--skip-comments</Code>.</li>
          </ul>
        </Step>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Restaurar</h2>
        <p>
          Baixe o <Code>.gpg</Code> em Backups e decifre com a chave privada (veja{" "}
          <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/help/decrypt">Baixar e decifrar</Link>):
        </p>
        <CopyBlock
          label="Comandos"
          text={`# MySQL / MariaDB (com --databases o dump tem CREATE DATABASE/USE)
gpg -d 01-mysql-erp.sql.gpg | mysql

# PostgreSQL (crie o banco vazio antes)
gpg -d 01-postgresql-app.sql.gpg | sudo -u postgres psql -d app

# arquivos: decifre e use como estão
gpg -d -o documentos.zip 01-file-documentos.zip.gpg`}
        />
      </Card>
    </div>
  );
}

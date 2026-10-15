import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

export default function DecryptHelpPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Baixar e decifrar um backup"
        subtitle="Todo backup é guardado cifrado com a chave GPG do servidor; só quem tem a chave privada abre."
      />

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Opção 1 — pelo painel (arquivos pequenos e médios)</h2>
        <Step n={1} title="Abra o backup">
          <p>
            Em <Link className="text-brand-600 hover:underline dark:text-brand-400" to="/backups">Backups</Link>, clique na
            execução desejada. Só administradores baixam arquivos.
          </p>
        </Step>
        <Step n={2} title="Clique em Baixar">
          <p>
            Abre uma janela pedindo a <b>chave privada</b> (arquivo <Code>.asc</Code>, colado ou escolhido) e a <b>senha</b>{" "}
            da chave (digitada ou do arquivo <Code>backup-key.pass</Code>).
          </p>
        </Step>
        <Step n={3} title="Decifrar e baixar">
          <p>
            O painel baixa o arquivo cifrado, decifra e entrega o resultado. Em arquivos <Code>.gz</Code> há a opção de já
            descompactar (marcada por padrão nas configurações Junos <Code>.conf.gz</Code>).
          </p>
          <Note>
            A decifragem acontece <b>no seu navegador</b>: a chave privada e a senha não são enviadas ao servidor nem
            guardadas, e somem ao fechar a janela.
          </Note>
          <Note tone="warn">
            O navegador mantém o arquivo inteiro na memória. Acima de 512 MB (dumps grandes) use a opção 2.
          </Note>
        </Step>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Opção 2 — no terminal com o gpg (qualquer tamanho)</h2>
        <Step n={1} title="Baixe o .gpg">
          <p>
            No detalhe do backup, o botão <Code>.gpg</Code> baixa o arquivo ainda cifrado. Também está no servidor, em{" "}
            <Code>BACKUP_STORAGE_PATH/store/&lt;origem&gt;/&lt;execução&gt;/</Code>, junto do <Code>manifest.json</Code> com o
            SHA-256 de cada parte.
          </p>
          <CopyBlock label="Comando" text="sha256sum *.gpg   # compare com o manifest.json" />
        </Step>
        <Step n={2} title="Importe a chave privada (numa máquina segura)">
          <p>
            A chave privada nunca fica no painel: use a cópia offline (a mesma de <Code>secrets/private/</Code> do servidor).
          </p>
          <CopyBlock
            label="Comandos"
            text={`export GNUPGHOME=$(mktemp -d)
gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass --import backup-key.sec.asc`}
          />
        </Step>
        <Step n={3} title="Decifre">
          <p>
            Redirecione a saída com <Code>&gt;</Code> (ou use um pipe); o resultado em claro não deve ficar em pasta
            sincronizada.
          </p>
          <CopyBlock
            label="Comandos"
            text={`# arquivo comum / configuração de equipamento (.conf.gz)
gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass -d ARQUIVO.gz.gpg | gunzip > ARQUIVO

# pasta (tar.gz)
mkdir -p /restore && gpg --batch --pinentry-mode loopback --passphrase-file backup-key.pass -d 01-files-etc.tar.gz.gpg | tar -xzp --numeric-owner -C /restore

# MySQL / MariaDB
gpg ... -d 03-mysql-loja.sql.gz.gpg | gunzip | mysql

# PostgreSQL
gpg ... -d 06-postgresql-erp.sql.gz.gpg | gunzip | sudo -u postgres psql -d postgres`}
          />
        </Step>
        <Step n={4} title="Limpe">
          <CopyBlock label="Comandos" text={`shred -u ARQUIVO     # o arquivo em claro\nrm -rf "$GNUPGHOME"   # o chaveiro temporário`} />
        </Step>
      </Card>

      <Card className="space-y-2 p-5 text-sm">
        <h2 className="text-base font-bold">Erros comuns</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>Senha da chave incorreta</b> — confira o <Code>backup-key.pass</Code> (sem espaço nem quebra de linha extra).</li>
          <li><b>Esta chave não é a que cifrou o backup</b> — o backup foi cifrado com outra chave (por exemplo, a do servidor foi recriada). A impressão digital aparece em Configuração → Chaves e servidor.</li>
          <li><b>Chave privada inválida</b> — você colou a chave pública; use o <Code>.asc</Code> da chave <i>privada</i>.</li>
          <li><Code>gunzip: ... No such file</Code> — a saída do gunzip vai com <Code>&gt; arquivo</Code>; um nome solto vira entrada.</li>
        </ul>
      </Card>
    </div>
  );
}

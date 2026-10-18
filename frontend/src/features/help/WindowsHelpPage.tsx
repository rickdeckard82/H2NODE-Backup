import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import type { ServerInfo } from "../../lib/types";
import { CopyBlock } from "../clients/ClientsPage";
import { Code, Note, Step } from "./parts";

const link = "text-brand-600 hover:underline dark:text-brand-400";

export default function WindowsHelpPage() {
  const q = useQuery({ queryKey: ["server-info"], queryFn: () => api.get<ServerInfo>("/server/info") });
  const fpr = q.data?.public_key_fingerprint ?? "—";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Windows: backup de pastas e arquivos"
        subtitle="Aplicativo com interface e ícone na bandeja: escolha pastas e arquivos, agende, e ele cifra e envia por HTTPS."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            O <b>PulseBackup.exe</b> roda com o usuário do Windows, fica no ícone da bandeja (perto do relógio) e faz o backup no
            horário agendado. Fechar a janela não o encerra; “Sair” no ícone, sim.
          </li>
          <li>
            Cada <b>pasta</b> vira um <Code>.tar.gz</Code> e cada <b>arquivo</b> vai como está. Tudo é <b>cifrado no próprio
            computador</b> com a chave pública GPG do servidor antes de sair. Só o arquivo cifrado passa pela pasta de trabalho, um
            item por vez, e é apagado depois do envio.
          </li>
          <li>
            O envio é por <b>HTTPS</b>, pelo mesmo endereço do painel (porta 443), em pedaços de até 32 MiB. Uma queda de rede
            retoma de onde parou. Nada é aberto no firewall do Windows nem do servidor.
          </li>
          <li>
            O token do computador só consegue <b>enviar</b>: não lista, não baixa e não apaga nada no servidor. No Windows, ele
            fica protegido pelo próprio sistema (DPAPI), legível só pelo usuário que conectou.
          </li>
          <li>
            No servidor, o backup segue o mesmo caminho do agente Linux: o worker confere o SHA-256, decifra, testa o
            <Code>.tar.gz</Code> até o fim, e a execução aparece em{" "}
            <Link className={link} to="/backups">
              Backups
            </Link>{" "}
            com retenção e alertas de atraso.
          </li>
        </ul>
      </Card>

      <Card className="space-y-5 p-5">
        <h2 className="text-base font-bold">Configurar</h2>

        <Step n={1} title="Cadastre o computador e gere o token">
          <p>
            Em{" "}
            <Link className={link} to="/clients">
              Servidores
            </Link>{" "}
            → <b>Novo servidor</b>: dê um nome (ex.: <i>PC Financeiro</i>) e deixe a chave SSH em branco. Ajuste o intervalo
            esperado (ex.: 24 h) e a retenção. Depois clique em <b>Windows</b> → <b>Gerar token</b> e copie o endereço e o token.
            O token aparece uma única vez.
          </p>
        </Step>

        <Step n={2} title="Instale o PulseBackup.exe">
          <p>
            Copie o <Code>PulseBackup.exe</Code> para uma pasta fixa (ex.: <Code>C:\Program Files\PulseBackup</Code>) e abra. Ele
            não precisa de administrador. Requer Windows 10 ou 11, que já trazem o WebView2.
          </p>
          <CopyBlock label="Gerar o executável (máquina com Go, Node e Wails)" text={"cd windows-client\nwails build -clean -trimpath\n# resultado: windows-client\\build\\bin\\PulseBackup.exe"} />
        </Step>

        <Step n={3} title="Conecte">
          <p>
            Na aba <b>Servidor</b>, cole o endereço e o token e clique em <b>Testar conexão</b>. Confira a impressão digital da
            chave GPG mostrada pelo aplicativo com a deste servidor:
          </p>
          <CopyBlock label="Impressão digital (Configuração → Chaves e servidor)" text={fpr} />
          <Note tone="warn">
            Só confirme se forem iguais. A chave fica fixada no aplicativo: se o servidor trocar de chave, o backup para e avisa,
            em vez de cifrar para uma chave desconhecida.
          </Note>
        </Step>

        <Step n={4} title="Escolha pastas e arquivos e o horário">
          <p>
            Em <b>Pastas e arquivos</b>, adicione o que entra no backup e, se quiser, padrões a ignorar (<Code>~$*</Code>,{" "}
            <Code>*.tmp</Code>…). Em <b>Agendamento</b>, escolha um horário em que o computador costuma estar ligado (ex.:
            12:30). Marque <b>Iniciar com o Windows</b> e “fazer o backup assim que abrir” se o computador estiver desligado no
            horário.
          </p>
        </Step>

        <Step n={5} title="Teste">
          <p>
            <b>Fazer backup agora</b> na aba Início. A execução aparece em{" "}
            <Link className={link} to="/backups">
              Backups
            </Link>{" "}
            e o computador em Servidores passa a mostrar a versão <Code>win-…</Code> e o Windows.
          </p>
        </Step>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Limitações e problemas comuns</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Arquivos abertos e travados</b> (ex.: <Code>.pst</Code> do Outlook aberto, bancos de dados em uso) são pulados e
            aparecem como <i>aviso</i>. Feche o programa no horário do backup.
          </li>
          <li>
            O backup roda com o <b>usuário logado</b>: arquivos de outros usuários ou sem permissão também são pulados.
          </li>
          <li>
            A <b>pasta de trabalho</b> (padrão em <Code>%LOCALAPPDATA%\PulseBackup\work</Code>) precisa de espaço para o maior
            item compactado. Troque-a na aba Pastas e arquivos.
          </li>
          <li>
            Log do aplicativo: <Code>%LOCALAPPDATA%\PulseBackup\logs\pulse-backup.log</Code> (aba Histórico → Abrir log).
          </li>
          <li>
            <i>token recusado</i>: o token foi trocado ou revogado no painel; gere outro. <i>cliente inativo</i>: reative o
            cadastro em Servidores.
          </li>
        </ul>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Restaurar</h2>
        <p>
          Em Backups, abra a execução e baixe a pasta (<Code>NN-files-Pasta.tar.gz.gpg</Code>) ou o arquivo. Pequenos podem ser
          decifrados no navegador (<b>Baixar</b>); grandes, com o gpg (ver{" "}
          <Link className={link} to="/help/decrypt">
            Baixar e decifrar
          </Link>
          ). O <Code>.tar.gz</Code> abre no próprio Windows 11 (Explorador de Arquivos) ou no 7-Zip.
        </p>
      </Card>
    </div>
  );
}

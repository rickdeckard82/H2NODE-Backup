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
        subtitle="Serviço do Windows com cópia de sombra (VSS), janela de configuração e ícone na bandeja; cifra e envia por HTTPS."
      />

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Como funciona</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            O instalador cria o <b>serviço “Pulse Backup”</b> (conta do sistema, início automático). É ele que agenda e faz os
            backups, <b>mesmo sem ninguém logado</b>, e lê as pastas de qualquer usuário do computador.
          </li>
          <li>
            Antes de cada backup o serviço cria uma <b>cópia de sombra (VSS)</b> de cada disco local envolvido e lê os arquivos
            dela. Arquivos abertos e travados (Outlook <Code>.pst</Code>, planilhas, bancos em uso) entram num estado
            consistente. A cópia é apagada no fim.
          </li>
          <li>
            Cada <b>pasta</b> vira um <Code>.tar.gz</Code> e cada <b>arquivo</b> vai como está. Tudo é <b>cifrado no próprio
            computador</b> com a chave pública GPG do servidor e enviado por <b>HTTPS</b> (porta 443 do painel), em pedaços com
            retomada. Nada é aberto no firewall.
          </li>
          <li>
            Cada usuário vê o <b>ícone na bandeja</b> (estado, “fazer backup agora”). <b>Mudar a configuração</b> (pastas,
            servidor, horário) exige administrador: a janela pede elevação (UAC).
          </li>
          <li>
            O token só consegue <b>enviar</b> (não lista, não baixa, não apaga) e fica no serviço, protegido pelo Windows (DPAPI da
            conta do sistema). No servidor o backup segue o caminho de sempre: o worker confere, decifra e testa, e a execução
            aparece em{" "}
            <Link className={link} to="/backups">
              Backups
            </Link>
            .
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
            → <b>Novo servidor</b>: nome (ex.: <i>PC Financeiro</i>), chave SSH em branco, intervalo esperado (ex.: 24 h) e
            retenção. Depois <b>Windows</b> → <b>Gerar token</b>: copie o endereço e o token (aparece uma única vez).
          </p>
        </Step>

        <Step n={2} title="Instale">
          <p>
            Baixe o <Code>PulseBackup-Setup-&lt;versão&gt;.exe</Code> em{" "}
            <Link className={link} to="/downloads">
              Downloads
            </Link>{" "}
            (ou gere lá um link de 1 h e baixe direto no computador) e rode como administrador. Ele instala em{" "}
            <Code>C:\Program Files\PulseBackup</Code>, registra e inicia o serviço, coloca o ícone na bandeja no login de
            todos os usuários e cria os atalhos no menu Iniciar. Requer Windows 10 ou 11 de 64 bits. Para atualizar, rode o
            instalador novo por cima: a configuração é mantida.
          </p>
          <CopyBlock
            label="Gerar o instalador (máquina com Go, Node, Wails e NSIS) e enviar em Downloads → Enviar arquivo"
            text={"make windows-installer\n# resultado: windows-client/build/bin/PulseBackup-Setup-<versão>.exe"}
          />
          <Note tone="warn">
            O instalador não é assinado digitalmente: o Windows SmartScreen pode avisar “editor desconhecido”. Clique em “Mais
            informações” → “Executar assim mesmo”.
          </Note>
        </Step>

        <Step n={3} title="Conecte (como administrador)">
          <p>
            No fim da instalação a janela de configuração abre (ou use o atalho <b>Configurar (administrador)</b>). Na aba{" "}
            <b>Servidor</b>, cole o endereço e o token e clique em <b>Testar conexão</b>. Confira a impressão digital da chave
            GPG com a deste servidor:
          </p>
          <CopyBlock label="Impressão digital (Configuração → Chaves e servidor)" text={fpr} />
          <Note tone="warn">
            Só confirme se forem iguais. A chave fica fixada: se o servidor trocar de chave, o backup para e avisa, em vez de
            cifrar para uma chave desconhecida.
          </Note>
        </Step>

        <Step n={4} title="Escolha pastas e arquivos e o horário">
          <p>
            Em <b>Pastas e arquivos</b>, adicione o que entra no backup (ex.: <Code>C:\Users</Code> pega todos os usuários) e
            padrões a ignorar (<Code>~$*</Code>, <Code>*.tmp</Code>…). Em <b>Agendamento</b>, o horário e os dias; deixe
            ligadas a <b>cópia de sombra (VSS)</b> e a opção de fazer o backup ao ligar se o computador estiver desligado no
            horário.
          </p>
        </Step>

        <Step n={5} title="Teste">
          <p>
            <b>Fazer backup agora</b> na aba Início (ou no ícone da bandeja). A execução aparece em{" "}
            <Link className={link} to="/backups">
              Backups
            </Link>
            , com “lido da cópia de sombra (VSS)” em cada pasta do disco local, e o computador em Servidores passa a mostrar a
            versão <Code>win-…</Code>.
          </p>
        </Step>
      </Card>

      <Card className="space-y-3 p-5 text-sm">
        <h2 className="text-base font-bold">Limitações e problemas comuns</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <b>Unidades de rede mapeadas</b> (Z:) não existem para o serviço: use <Code>\\servidor\pasta</Code> e dê acesso de
            leitura à conta do computador (<Code>DOMÍNIO\NOME-DO-PC$</Code>). Pastas de rede, pendrives e discos FAT/exFAT são
            lidos sem VSS.
          </li>
          <li>
            <b>VSS falhou</b> (aviso “sem cópia de sombra” no histórico): geralmente falta espaço para cópias de sombra no
            disco (<Code>vssadmin list shadowstorage</Code>) ou o serviço “Cópias de Sombra de Volume” está desativado. O
            backup continua lendo ao vivo.
          </li>
          <li>
            O computador precisa estar <b>ligado</b> no horário (o serviço não o acorda). Com “fazer ao ligar”, um horário
            perdido roda 2 minutos depois que o serviço inicia.
          </li>
          <li>
            A <b>pasta de trabalho</b> (padrão <Code>C:\ProgramData\PulseBackup\work</Code>) precisa de espaço para o maior
            item compactado; troque na aba Pastas e arquivos.
          </li>
          <li>
            Log: aba Histórico → <b>Ver log do serviço</b> (arquivo em <Code>C:\ProgramData\PulseBackup\logs</Code>, só para
            administradores). <i>serviço parado</i>: botão <b>Iniciar serviço</b> na janela ou <Code>services.msc</Code>.
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

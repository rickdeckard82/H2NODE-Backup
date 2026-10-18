export const APP_VERSION = "0.9.1";

export interface ChangelogEntry {
  version: string;
  date: string;
  changes: string[];
}

/** Mais recente primeiro. */
export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "0.9.1",
    date: "2026-10-18",
    changes: [
      "Segurança: 2FA obrigatório para administradores e operadores (MFA_REQUIRED_ROLES). Sem 2FA a conta só consegue ativá-lo, trocar a senha ou sair — o servidor recusa o resto.",
      "Segurança: código 2FA errado passa a contar para o bloqueio progressivo da conta (antes só a senha contava), e conta bloqueada também recusa o código.",
      "Auditoria: toda tentativa de login que falha (senha, usuário inexistente, código 2FA, conta bloqueada) e o logout passam a ser registrados.",
      "Dependências: PyJWT 2.15.1 (corrige avisos publicados na 2.13), pytest 9.1.1 e golang.org/x/crypto v0.58 no cliente Windows.",
    ],
  },
  {
    version: "0.9.0",
    date: "2026-10-18",
    changes: [
      "Nova página Downloads (menu lateral): agente Linux (.tar.gz montado na hora a partir do agente deste servidor), instalador do cliente Windows e chave pública GPG, com tamanho e SHA-256.",
      "Link para o servidor (1 h): link de download sem login, só para aquele arquivo, com os comandos prontos para baixar, conferir o SHA-256 e instalar direto no Linux (curl) ou no Windows (PowerShell).",
      "Administradores enviam o instalador do Windows (ou outro pacote .exe/.msi/.zip/.tar.gz) pela própria página; tudo fica na auditoria.",
    ],
  },
  {
    version: "0.8.1",
    date: "2026-10-18",
    changes: [
      "Cliente Windows 0.2.0: o backup roda num serviço do Windows (conta do sistema, mesmo sem ninguém logado) e lê os arquivos de uma cópia de sombra (VSS) — Outlook .pst, planilhas e bancos abertos entram. A cópia é apagada no fim; sem VSS (pendrive, rede ou falha) lê ao vivo e marca aviso.",
      "Cliente Windows: instalador (PulseBackup-Setup-<versão>.exe, NSIS) que registra e inicia o serviço, abre o ícone da bandeja no login de todos os usuários e cria os atalhos; desinstalador incluso. Mudar a configuração exige administrador (UAC); ver o estado e fazer backup agora, não.",
      "Ajuda → Windows atualizada (instalador, serviço, VSS, unidades de rede).",
    ],
  },
  {
    version: "0.8.0",
    date: "2026-10-18",
    changes: [
      "Cliente Windows (windows-client/): aplicativo com interface e ícone na bandeja para escolher pastas e arquivos, agendar (horário fixo, a cada N horas ou manual, com backup perdido ao ligar) e acompanhar o progresso e o histórico. Cifra no próprio computador com a chave pública (pastas em .tar.gz) e envia por HTTPS em pedaços com retomada.",
      "Envio por HTTPS no servidor (/api/agent/v1): só cria execuções, acrescenta bytes e fecha com o manifesto — não lista, não lê e não apaga. Cai no mesmo caminho do agente Linux (verificação, retenção, alertas).",
      "Servidores → Windows: gerar, trocar e revogar o token de envio do computador (aparece uma única vez; só o hash fica no banco).",
      "Ajuda → Windows: instalação, conexão (conferência da impressão digital da chave), agendamento e restauração.",
    ],
  },
  {
    version: "0.7.3",
    date: "2026-10-18",
    changes: [
      "Agente 1.3.0 (cPanel): confere se todas as contas do servidor têm backup na pasta do dia. Cada conta que faltar (backup do WHM ainda rodando ou conta pulada) aparece como falha e a execução fica parcial, em vez de parecer completa. Respeita contas com backup desligado, suspensas e criadas há menos de 24 h; desligue com CPANEL_CHECK_ACCOUNTS=\"no\".",
      "Ajuda → cPanel / WHM: horário recomendado do agente à noite (depois do backup do WHM) e como investigar um dia com contas faltando.",
    ],
  },
  {
    version: "0.7.2",
    date: "2026-10-18",
    changes: [
      "Contas cPanel: escolha uma data para ver só as contas com cópia naquele dia (e a cópia desse dia, pronta para baixar).",
      "Contas cPanel: clique em Conta, Servidor, Última cópia, Tamanho, Versões ou Verificação para ordenar; clique de novo para inverter (▲/▼).",
    ],
  },
  {
    version: "0.7.1",
    date: "2026-10-18",
    changes: [
      "Menu: Backups e Contas cPanel sobem para logo abaixo de Equipamentos de rede, acima do grupo MikroTik.",
      "Novo MikroTik → Backups: a lista de backups só com os MikroTik (filtros de equipamento, resultado e verificação).",
    ],
  },
  {
    version: "0.7.0",
    date: "2026-10-18",
    changes: [
      "Novo menu MikroTik: o Pulse Backup entra por SSH em cada MikroTik, roda /export show-sensitive (RouterOS 7; /export no 6), cifra em memória e guarda cada versão — sem nada em claro no disco. Versões em que só a data do cabeçalho mudou aparecem como idênticas à anterior.",
      "MikroTik → Usuário de acesso: credenciais (usuário, senha cifrada no servidor, porta) e os comandos RouterOS para criar o usuário somente leitura (grupo ssh,read,sensitive, preso ao IP do servidor).",
      "MikroTik → Hosts: cadastro individual ou importação de lista (IP[:porta] [nome] por linha), intervalo de coleta, \"Coletar agora\", erro da última coleta e chave SSH fixada na primeira coleta (se mudar, a coleta para até alguém aceitar a nova chave).",
      "Novo serviço puller no docker-compose (rede própria com saída; só a chave pública). Ajuda → MikroTik (RouterOS): criação do backup e restauração.",
    ],
  },
  {
    version: "0.6.1",
    date: "2026-10-16",
    changes: [
      "Documentação e Ajuda atualizadas: servidor Linux (atalho do agente em /usr/bin, horário do cron, BACKUP_FILES), baixar e decifrar (Contas cPanel e busca), README, segurança e guias de equipamentos (Fiberhome/UNM2000).",
      "Instalador do agente cria o atalho /usr/bin/pulse-backup-agent (o PATH do root/sudo nem sempre inclui /usr/local/sbin).",
    ],
  },
  {
    version: "0.6.0",
    date: "2026-10-16",
    changes: [
      "Nova página Contas cPanel: uma linha por conta (ou arquivo enviado como está), com a cópia mais recente, tamanho, nº de versões e verificação; busca por conta/domínio e histórico de versões com download (decifrado ou .gpg).",
      "Backups: caixa de busca por conta, pasta ou banco (mostra só as execuções que contêm o nome).",
      "Agente 1.2.0: @today (só a pasta da data de hoje, falha se não existir) e @latest em BACKUP_FILES e BACKUP_PATHS — a pasta system do cPanel vai inteira. Arquivos alterados há menos de 10 min (FILES_MIN_AGE_MINUTES) não são enviados, pois ainda estão sendo gravados.",
    ],
  },
  {
    version: "0.5.2",
    date: "2026-10-16",
    changes: [
      "OLT Fiberhome (FTP): novo campo \"IP da UNM2000 (gerenciador)\" no cadastro. Depois que cada OLT envia o backup, a UNM2000 entra no FTP para apagar/renomear o arquivo; esse IP passa a poder usar o FTP (sem cadastro próprio) e o servidor responde sucesso a esses comandos sem alterar nada — o resto continua só de gravação. A UNM2000 deixa de acusar falha e de repetir a tarefa.",
      "Arquivos <ID>_<MMDD> das OLTs são comparados com o do dia anterior da mesma OLT (\"idêntica ao backup anterior\").",
    ],
  },
  {
    version: "0.5.1",
    date: "2026-10-16",
    changes: [
      "Ajuda → UNM2000: corrigido — cada OLT envia a própria configuração a partir do IP dela, então cada OLT é um equipamento (e não a UNM2000 inteira).",
    ],
  },
  {
    version: "0.5.0",
    date: "2026-10-16",
    changes: [
      "Backup de cPanel/WHM e outros arquivos grandes: o agente (1.1.0) ganhou BACKUP_FILES — cifra cada arquivo como está (ex.: .tar.gz de conta) e o envia um a um, só precisando de disco para o maior. A verificação confere o gzip e o hash do conteúdo. Novo tipo de componente \"Arquivo\".",
      "Backup das OLTs Fiberhome pela UNM2000 (FTP): novo fabricante, com validação do config da OLT e comparação \"idêntica ao anterior\" por OLT.",
      "Ajuda: novas páginas cPanel / WHM e UNM2000 (Fiberhome).",
      "Agente: corrigido o prefixo numérico dos arquivos (todos saíam 01).",
    ],
  },
  {
    version: "0.4.2",
    date: "2026-10-15",
    changes: [
      "Ajuda → Servidor Linux: como o backup funciona, instalação do agente, cadastro, liberação no firewall, teste, solução de problemas e restauração de pastas e bancos.",
    ],
  },
  {
    version: "0.4.1",
    date: "2026-10-15",
    changes: [
      "Ajuda → Datacom (DmOS): como criar o backup por TFTP (script no equipamento e assistant-task agendada) e como restaurar a configuração.",
    ],
  },
  {
    version: "0.4.0",
    date: "2026-10-15",
    changes: [
      "Novo menu Ajuda, abaixo de Configuração: \"Baixar e decifrar\" (pelo painel e pelo gpg) e \"Juniper (Junos)\" (criar o backup por FTP e restaurar a configuração).",
      "Detalhe do backup de equipamento de rede: Baixar e .gpg passam a ser botões no rodapé, ao lado de Excluir backup.",
    ],
  },
  {
    version: "0.3.0",
    date: "2026-10-15",
    changes: [
      "Backups → detalhe → Baixar: pede a chave privada e a senha, decifra o arquivo no próprio navegador e baixa já decifrado (com opção de descompactar o .gz, útil nas configurações Junos). A chave e a senha não saem do navegador nem chegam ao servidor.",
      "O arquivo ainda cifrado continua disponível pelo link .gpg.",
      "Novo script scripts/ufw-docker.sh: faz o ufw valer também para portas publicadas pelo Docker.",
    ],
  },
  {
    version: "0.2.0",
    date: "2026-10-01",
    changes: [
      "Backup de switches e roteadores: receptores FTP e TFTP (Datacom DmOS via TFTP, Huawei VRP e Juniper Junos via FTP), aceitando só os IPs cadastrados e só gravação.",
      "Tela Equipamentos de rede com fabricante, protocolo e IP de origem, e os comandos prontos para colar em cada equipamento.",
      "Configuração → Contas FTP para as contas usadas pelos equipamentos (senha em hash Argon2id).",
      "Cada configuração recebida é validada (Huawei \"return\", Junos .gz íntegro, DmOS), cifrada com a chave GPG na chegada e verificada de novo após decifrar; versões idênticas são sinalizadas.",
      "Intervalo esperado 0 = sob demanda (envio a cada alteração), sem alerta de atraso.",
      "Clientes passam a se chamar Servidores; painel e filtros mostram servidores e equipamentos.",
    ],
  },
  {
    version: "0.1.1",
    date: "2026-10-01",
    changes: [
      "Menu lateral pode ser recolhido (só ícones, com o nome ao passar o mouse) pela seta ao lado do logo; a escolha fica salva no navegador.",
      "Ondas animadas na tela de login, no cabeçalho e no rodapé, como no Pulse RADIUS.",
      "Copyright e versão saem da barra lateral e vão para o rodapé da página, centralizados.",
      "Proxy HTTPS (Caddy) com certificado Let's Encrypt automático; proxy e recepção SSH na rede do host para o ufw filtrar as portas.",
    ],
  },
  {
    version: "0.1.0",
    date: "2026-10-01",
    changes: [
      "Primeira versão: painel web com login (senha + 2FA opcional), cadastro de clientes Linux, recepção de backups por rsync/SSH e agente para o crontab do root.",
      "Backups de pastas e de bancos MySQL/MariaDB, PostgreSQL e SQL Server, cifrados no cliente com a chave pública GPG do servidor.",
      "Verificação automática de cada backup: hash do arquivo cifrado, destinatário GPG e — com a chave privada no worker — teste do conteúdo decifrado (tar íntegro, dump completo).",
      "Painel com execuções por dia, falhas, volume, espaço em disco usado/livre, crescimento do armazenamento e clientes atrasados.",
      "Retenção por cliente (dias + mínimo de backups mantidos) e reverificação periódica dos backups guardados.",
    ],
  },
];

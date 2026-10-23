export const APP_VERSION = "0.9.23";

export interface ChangelogEntry {
  version: string;
  date: string;
  changes: string[];
}

/** Mais recente primeiro. */
export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "0.9.23",
    date: "2026-10-23",
    changes: [
      "Agente 1.4.2: o \"pulse-backup-agent test\" mostra o caminho de fato procurado (com @today/@yesterday/@latest trocados pela data) e as pastas datadas que existem, em vez de só o padrão.",
      "Ajuda cPanel/WHM: quando o WHM pula dias, use @latest nas duas listas.",
    ],
  },
  {
    version: "0.9.22",
    date: "2026-10-23",
    changes: [
      "Contas cPanel: deixam de aparecer os arquivos de equipamentos e de \"Arquivos e bancos\" por FTP (ex.: dumps com data no nome, cada um virando uma \"conta\") e as linhas de falha sem arquivo (padrão como /backup/cpanel/@today/accounts/* ou conta que o WHM não copiou, com 0 B). Cada conta mostra a última cópia que existe de fato; as falhas continuam em Backups.",
      "Agente 1.4.1: quando o padrão com @today/@yesterday/@latest não encontra arquivo, o erro diz a data procurada e as pastas datadas que existem (ex.: \"@today = 2026-10-22; pastas em /backup/cpanel/: 2026-10-19 2026-10-21\").",
      "Ajuda cPanel/WHM: o token (@today, @yesterday ou @latest) tem de ser o mesmo em BACKUP_PATHS e BACKUP_FILES.",
    ],
  },
  {
    version: "0.9.21",
    date: "2026-10-23",
    changes: [
      "Zabbix: o template pulse_backup_zabbix7.yaml deixa de ser recusado na importação com \"UUIDv4 is expected\". Baixe de novo em Configuração → Zabbix.",
    ],
  },
  {
    version: "0.9.20",
    date: "2026-10-23",
    changes: [
      "Integração com Zabbix (Configuração → Zabbix): o Zabbix consulta o painel por HTTPS com um token só de leitura e alerta backup com falha, atrasado, sem verificação ou nunca recebido, worker parado, disco cheio e o próprio painel fora do ar.",
      "Template pronto para Zabbix 7.0 (pulse_backup_zabbix7.yaml) com descoberta automática de servidores e equipamentos, para baixar na mesma página, que mostra quando e de qual IP o Zabbix consultou pela última vez.",
    ],
  },
  {
    version: "0.9.19",
    date: "2026-10-23",
    changes: [
      "FTP Firmwares: cada arquivo pode ter o fabricante (os mesmos do Tipo dos equipamentos: Datacom, Huawei, Juniper, A10, Fiberhome, MikroTik, Genérico), em nova coluna e no mesmo formulário do comentário.",
      "FTP Firmwares: a lista ordena por arquivo, fabricante, tamanho ou data (clique no cabeçalho; outro clique inverte). A escolha fica guardada no navegador.",
    ],
  },
  {
    version: "0.9.18",
    date: "2026-10-22",
    changes: [
      "Login com 2FA: nova opção \"Lembrar este dispositivo por 30 dias\". No navegador lembrado a senha continua sendo pedida, mas o código do autenticador não (TRUSTED_DEVICE_DAYS; 0 desliga).",
      "Os dispositivos lembrados são esquecidos ao trocar ou redefinir a senha, desativar ou redefinir o 2FA, desativar a conta ou em 2FA → \"Esquecer todos\".",
    ],
  },
  {
    version: "0.9.17",
    date: "2026-10-22",
    changes: [
      "FTP Firmwares: cada arquivo pode ter um comentário curto (até 200 caracteres), mostrado abaixo do nome. O painel pede o comentário logo após o envio e o administrador edita depois em \"editar\". Substituir o arquivo mantém o comentário; excluir apaga.",
    ],
  },
  {
    version: "0.9.16",
    date: "2026-10-22",
    changes: [
      "FTP Firmwares: novo card \"Conexões ativas\", atualizado a cada 3 s, com os equipamentos conectados agora (FTP logado e TFTP baixando): IP, usuário, tempo conectado, arquivo em transferência com progresso e velocidade, e se os receptores FTP/TFTP estão no ar.",
    ],
  },
  {
    version: "0.9.15",
    date: "2026-10-22",
    changes: [
      "Nova página FTP Firmwares: envie imagens de firmware pelo painel (com barra de progresso) e os switches, OLTs e roteadores as baixam por TFTP (sem login) ou FTP (login próprio, somente leitura), nas mesmas portas 21 e 69.",
      "Acesso aos firmwares só das redes liberadas na página e, se marcado, dos IPs dos equipamentos cadastrados. Os backups continuam só gravação: nenhuma conta ou IP lê o que foi recebido.",
      "Cada firmware mostra o SHA-256 e os comandos para baixar (URLs tftp:// e ftp://, Huawei VRP, Cisco e teste no Linux).",
    ],
  },
  {
    version: "0.9.14",
    date: "2026-10-22",
    changes: [
      "Novo fabricante A10 (ACOS / Thunder): backup de sistema (backup system) por FTP, validado pelo tar.gz. Inclui a página de ajuda \"A10 (ACOS)\" com a GUI, a CLI e a restauração.",
    ],
  },
  {
    version: "0.9.13",
    date: "2026-10-21",
    changes: [
      "Ajuda: nova página \"Huawei (VRP)\" com o backup por FTP (backup-to-server, ftp client-source) e a restauração da configuração.",
    ],
  },
  {
    version: "0.9.12",
    date: "2026-10-20",
    changes: [
      "Agente 1.4.0: novo token @yesterday em BACKUP_FILES/BACKUP_PATHS, para rodar o agente no dia seguinte ao backup do WHM quando ele demora (ex.: WHM seg/qua/sex e agente ter/qui/sáb). Se a pasta de ontem não existir, a execução acusa falha.",
      "Ajuda cPanel/WHM: como agendar o agente no dia seguinte e ajustar o intervalo esperado.",
    ],
  },
  {
    version: "0.9.11",
    date: "2026-10-20",
    changes: [
      "Huawei (VRP): o vrpcfg.cfg (solto ou no .zip do backup-to-server) deixa de ser reprovado com \"conteúdo não parece texto de configuração\". O VRP grava um byte nulo depois do \"return\" final, e agora esse enchimento no fim do arquivo é ignorado. Use \"Verificar novamente\" nos backups já recebidos.",
    ],
  },
  {
    version: "0.9.10",
    date: "2026-10-19",
    changes: [
      "FTP/TFTP: um servidor atrás do mesmo NAT da UNM2000 pode ter cadastro FTP no IP dela, com Conta FTP própria: o login com essa conta vai para o cadastro e qualquer outra conta continua sendo tratada como a UNM2000.",
    ],
  },
  {
    version: "0.9.9",
    date: "2026-10-19",
    changes: [
      "FTP/TFTP: o mesmo IP pode ter mais de um cadastro. No FTP, cada cadastro do IP escolhe a sua Conta FTP (novo campo) e o login diz de quem é o arquivo; TFTP continua com um cadastro por IP; MikroTik (SSH) não disputa o IP.",
      "FTP/TFTP: o erro de IP repetido diz qual cadastro já usa o IP.",
    ],
  },
  {
    version: "0.9.8",
    date: "2026-10-19",
    changes: [
      "Arquivos e bancos (FTP): os arquivos enviados na mesma conexão FTP viram UMA execução em Backups, com uma parte por arquivo (ex.: o dump .sql.gz e o .zip juntos), como nos servidores com o agente. A execução fica com o pior resultado entre as partes.",
      "Arquivos e bancos (FTP): envio como .part com renomeação no fim passa a funcionar (vale o nome final).",
    ],
  },
  {
    version: "0.9.7",
    date: "2026-10-19",
    changes: [
      "Menu: \"Equipamentos de rede\" passa a se chamar \"FTP/TFTP\" (switches, roteadores e serviços que enviam a configuração por FTP ou TFTP).",
      "FTP/TFTP: novo tipo \"Arquivos e bancos (FTP)\" para servidores e serviços que enviam dumps .sql, configurações (.conf, .txt, .csv) e arquivos .zip/.pdf. Cada arquivo é testado pela extensão (dump completo, CRC do zip…), cifrado e guardado como uma versão; limite próprio de 4 GB por arquivo (NET_FILES_MAX_MB).",
      "Ajuda: nova página \"Arquivos e bancos (FTP)\", com script de exemplo para o cron.",
    ],
  },
  {
    version: "0.9.6",
    date: "2026-10-18",
    changes: [
      "Downloads: só o instalador do Windows mais novo aparece; versões antigas enviadas à mão ficam escondidas.",
      "Downloads: a chave pública aparece como \"chave deste servidor\" (não como arquivo enviado).",
    ],
  },
  {
    version: "0.9.5",
    date: "2026-10-18",
    changes: [
      "Downloads: a lista passa a vir de um endereço novo, para não depender do redirecionamento antigo que os navegadores guardaram em cache.",
    ],
  },
  {
    version: "0.9.4",
    date: "2026-10-18",
    changes: [
      "Downloads: a página voltava vazia (\"Failed to fetch\") porque o nginx do painel redirecionava a lista para um endereço HTTP que o navegador bloqueia. Agora o agente Linux, o instalador do Windows e a chave pública aparecem.",
    ],
  },
  {
    version: "0.9.3",
    date: "2026-10-18",
    changes: [
      "Downloads: um arquivo que o servidor não consegue ler (ex.: permissão) deixa de esvaziar a página inteira — os demais aparecem e a página diz qual arquivo falhou e por quê.",
      "Downloads: erro ao carregar a lista agora aparece na tela, em vez da mensagem de que não há instalador.",
    ],
  },
  {
    version: "0.9.2",
    date: "2026-10-18",
    changes: [
      "Downloads: o instalador do cliente Windows passa a ser compilado pelo próprio servidor (serviço client-builder: Go + Wails + NSIS, sem precisar de Windows) a cada atualização em que o cliente mudou, e aparece sozinho na página, pronto para baixar por HTTPS ou por link de 1 h.",
      "O agente Linux continua sendo montado na hora a partir do agente do servidor: atualizou o servidor, o download já é a versão nova.",
      "Enviar arquivo segue disponível para outros pacotes; o instalador compilado pelo servidor não pode ser substituído nem excluído pela página.",
    ],
  },
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

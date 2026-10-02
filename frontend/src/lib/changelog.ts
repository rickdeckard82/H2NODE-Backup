export const APP_VERSION = "0.2.0";

export interface ChangelogEntry {
  version: string;
  date: string;
  changes: string[];
}

/** Mais recente primeiro. */
export const CHANGELOG: ChangelogEntry[] = [
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

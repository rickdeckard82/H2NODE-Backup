/** Grupo criado no RouterOS para o usuário de backup: só login SSH, leitura e dados sensíveis
 * (o /export show-sensitive precisa do "sensitive" para incluir senhas, chaves e segredos). */
export const ROS_GROUP = "h2node-backup";

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

/** Endereço de origem para o `address=` do usuário: o IP do servidor, se já for um IP. */
export function serverAddress(host: string | undefined | null): string {
  return host && IPV4.test(host) ? `${host}/32` : "<IP-DO-SERVIDOR>/32";
}

/** Comandos a colar no terminal de cada MikroTik para criar o usuário de backup. */
export function routerosUserCommands(username: string, password: string | null, address: string): string {
  return [
    `/user group add name=${ROS_GROUP} policy=ssh,read,sensitive comment="H2NODE Backup: somente leitura"`,
    `/user add name=${username} group=${ROS_GROUP} password="${password || "<SENHA>"}" address=${address} comment="H2NODE Backup"`,
  ].join("\n");
}

export type Vendor = "datacom" | "huawei" | "juniper" | "a10" | "fiberhome" | "mikrotik" | "generic" | "files";
/** Fabricantes que ENVIAM a configuração (FTP/TFTP). O MikroTik é coletado por SSH (menu próprio). */
export type PushVendor = Exclude<Vendor, "mikrotik">;

export const VENDOR_LABEL: Record<Vendor, string> = {
  datacom: "Datacom (DmOS)",
  huawei: "Huawei (VRP)",
  juniper: "Juniper (Junos)",
  a10: "A10 (ACOS)",
  fiberhome: "Fiberhome (OLT / UNM2000)",
  mikrotik: "MikroTik (RouterOS)",
  generic: "Genérico",
  files: "Arquivos e bancos (FTP)",
};

/** Protocolo usual de cada fabricante (sugestão no cadastro). */
export const VENDOR_PROTOCOL: Record<PushVendor, "ftp" | "tftp"> = {
  datacom: "tftp",
  huawei: "ftp",
  juniper: "ftp",
  a10: "ftp",
  fiberhome: "ftp",
  generic: "ftp",
  files: "ftp",
};

export type Health = "ok" | "warning" | "failed" | "overdue" | "never" | "inactive";
export type BackupStatus = "ok" | "warning" | "failed" | "corrupted";
export type VerifyStatus = "pending" | "running" | "ok" | "failed" | "skipped";

export interface Client {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  is_active: boolean;
  kind: "server" | "network";
  vendor: Vendor | null;
  mgmt_ip: string | null;
  manager_ip: string | null;
  protocol: "ftp" | "tftp" | "ssh" | null;
  /** FTP: conta presa ao cadastro (null = qualquer conta). Obrigatória se outro cadastro FTP usa o mesmo IP. */
  ftp_account_id: number | null;
  ftp_user: string | null;
  /** MikroTik: credencial de acesso, porta (null = a da credencial) e estado da coleta. */
  pull_credential_id: number | null;
  pull_port: number | null;
  pull_host_key_fingerprint: string | null;
  pull_next_at: string | null;
  pull_last_at: string | null;
  pull_error: string | null;
  ssh_public_key: string | null;
  ssh_key_fingerprint: string | null;
  /** final do token de envio HTTPS (cliente Windows); null = sem token */
  upload_token_hint: string | null;
  expected_interval_hours: number;
  retention_days: number;
  retention_min_keep: number;
  hostname: string | null;
  os_info: string | null;
  agent_version: string | null;
  last_backup_at: string | null;
  last_status: string | null;
  stored_bytes: number;
  backup_count: number;
  health: Health;
  created_at: string;
  updated_at: string;
}

export interface Backup {
  id: number;
  client_id: number;
  client_slug: string;
  client_name: string;
  run_name: string;
  status: BackupStatus;
  agent_status: string | null;
  started_at: string | null;
  finished_at: string | null;
  received_at: string;
  size_bytes: number;
  plain_size_bytes: number;
  error_message: string | null;
  agent_version: string | null;
  verify_status: VerifyStatus;
  verify_mode: string | null;
  verified_at: string | null;
  verify_message: string | null;
  deleted_at: string | null;
  component_count: number;
}

export interface BackupComponent {
  id: number;
  position: number;
  kind: "files" | "file" | "mysql" | "postgresql" | "mssql" | "config";
  name: string;
  file_name: string | null;
  size_bytes: number;
  sha256: string | null;
  plain_size_bytes: number;
  plain_sha256: string | null;
  status: "ok" | "warning" | "failed";
  message: string | null;
  duration_seconds: number | null;
  verify_status: string | null;
  verify_message: string | null;
  item_count: number | null;
}

export interface BackupDetail extends Backup {
  components: BackupComponent[];
  errors: string[];
  hostname: string | null;
}

export interface SystemUser {
  id: number;
  username: string;
  email: string;
  full_name: string;
  role: "admin" | "operator" | "auditor";
  is_active: boolean;
  timezone: string;
  mfa_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  actor_username: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  before_json: string | null;
  after_json: string | null;
}

export interface ServerInfo {
  public_key_available: boolean;
  public_key_fingerprint: string | null;
  public_key_uid: string | null;
  deep_verify_enabled: boolean;
  ssh_host: string;
  ssh_port: number;
  ssh_host_key: string | null;
  ssh_host_key_fingerprint: string | null;
  net_host: string;
  ftp_port: number;
  ftp_passive_ports: string;
  net_files_max_mb: number;
  tftp_port: number;
  storage_path: string;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
}

export const KIND_LABEL: Record<BackupComponent["kind"], string> = {
  files: "Pasta",
  file: "Arquivo",
  mysql: "MySQL/MariaDB",
  postgresql: "PostgreSQL",
  mssql: "SQL Server",
  config: "Configuração",
};

export interface Account {
  client_id: number;
  client_name: string;
  name: string;
  versions: number;
  last_backup_id: number;
  last_component_id: number;
  last_received_at: string;
  size_bytes: number;
  status: string;
  verify_status: string | null;
  file_name: string | null;
}

export interface AccountVersion {
  backup_id: number;
  component_id: number;
  run_name: string;
  received_at: string;
  size_bytes: number;
  status: string;
  verify_status: string | null;
  verify_message: string | null;
  file_name: string | null;
}

export interface DeviceCredential {
  id: number;
  name: string;
  username: string;
  port: number;
  description: string | null;
  device_count: number;
  created_at: string;
  updated_at: string;
}

export interface FtpAccount {
  id: number;
  username: string;
  description: string | null;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

export type Health = "ok" | "warning" | "failed" | "overdue" | "never" | "inactive";
export type BackupStatus = "ok" | "warning" | "failed" | "corrupted";
export type VerifyStatus = "pending" | "running" | "ok" | "failed" | "skipped";

export interface Client {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  is_active: boolean;
  ssh_public_key: string | null;
  ssh_key_fingerprint: string | null;
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
  kind: "files" | "mysql" | "postgresql" | "mssql";
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
  storage_path: string;
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
}

export const KIND_LABEL: Record<BackupComponent["kind"], string> = {
  files: "Pasta",
  mysql: "MySQL/MariaDB",
  postgresql: "PostgreSQL",
  mssql: "SQL Server",
};

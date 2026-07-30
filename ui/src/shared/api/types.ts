export interface User {
  id: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Host {
  id: string;
  name: string;
  address: string;
  port: number;
  username: string;
  tags: string[];
  is_local: boolean;
  has_password: boolean;
  host_key_fingerprint: string | null;
  last_test_status: string | null;
  last_test_message: string | null;
  last_tested_at: string | null;
  created_at: string;
}

export interface HostInput {
  name: string;
  address: string;
  port: number;
  username: string;
  password?: string;
  tags: string[];
  is_local: boolean;
}

export interface SSHTestResult {
  status: string;
  code: string;
  message: string;
  fingerprint: string | null;
}

export interface DeploymentTarget {
  id: string;
  target_ip: string;
  target_directory: string;
  command: string;
  status: string;
  progress: number;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DeploymentTask {
  id: string;
  master_task_id: string;
  artifact_name: string;
  artifact_sha256: string;
  status: string;
  claimed_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  targets: DeploymentTarget[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string;
  details: Record<string, unknown>;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size: number;
  modified_at: string | null;
  permissions: string;
}

export type MasterScheme = "http" | "https";
export type MasterRuntimeStatus =
  | "unconfigured"
  | "connecting"
  | "online"
  | "error"
  | "stopped";

export interface MasterSettingInput {
  scheme: MasterScheme;
  host: string;
  port: number;
  token: string;
}

export interface MasterSettingResponse {
  scheme: MasterScheme;
  host: string;
  port: number;
  has_token: boolean;
  runtime_status: MasterRuntimeStatus;
}

export interface MasterConnectionTestResponse {
  status: "success";
}

export type UploadTaskStatus =
  | "queued"
  | "uploading"
  | "completed"
  | "failed"
  | "cancelled";

export interface UploadTask {
  id: string;
  file: File;
  destination: string;
  loaded: number;
  total: number;
  status: UploadTaskStatus;
  error?: string;
}

export interface UploadSummary {
  total: number;
  queued: number;
  uploading: number;
  completed: number;
  failed: number;
  cancelled: number;
  loaded: number;
  totalBytes: number;
  percent: number;
}

export interface UploadOptions {
  signal: AbortSignal;
  onProgress: (event: { loaded: number; total?: number }) => void;
}

export interface DeploymentEvent {
  id: number;
  sequence: number;
  target_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  source_ip: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

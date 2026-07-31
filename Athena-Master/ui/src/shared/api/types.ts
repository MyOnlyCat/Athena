export interface User {
  id: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserPage {
  items: User[];
  page: number;
  page_size: number;
  total: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

export interface RegistrationApplication {
  id: string;
  node_id: string;
  reported_name: string;
  hostname: string;
  software_version: string;
  status: "pending" | "approved" | "rejected" | "expired" | "restored";
  rejection_reason?: string;
  identity_verified: boolean;
  received_at: string;
}

export interface RegistrationApplicationPage {
  items: RegistrationApplication[];
  page: number;
  page_size: number;
  total: number;
}

export interface AccessNode {
  node_id: string;
  reported_name: string;
  hostname: string;
  software_version: string;
  management_status: "active" | "disabled" | "rejected" | "pending";
  approved_at: string;
}

export type ConnectivityStatus = "online" | "stale" | "offline";

export interface ListedAccessNode extends AccessNode {
  connectivity_status: ConnectivityStatus;
  last_heartbeat_at: string | null;
}

export interface AccessNodePage {
  items: ListedAccessNode[];
  page: number;
  page_size: number;
  total: number;
}

export interface NodeListParams {
  page: number;
  page_size: number;
  search?: string;
  management_status?: AccessNode["management_status"];
  connectivity_status?: ConnectivityStatus;
  sort_by:
    | "reported_name"
    | "hostname"
    | "software_version"
    | "approved_at"
    | "last_heartbeat_at";
  sort_order: "asc" | "desc";
}

export type HostTestStatus = "success" | "failed" | "pending_trust";
export type HostDetectionFilter = HostTestStatus | "untested";
export type HostTestCode =
  | "SSH_CONNECTED"
  | "SSH_AUTH_FAILED"
  | "SSH_TIMEOUT"
  | "SSH_CONNECTION_FAILED"
  | "SSH_HOST_KEY_UNTRUSTED"
  | "SSH_HOST_KEY_CHANGED";
export type AssetLifecycleStatus = "active" | "retired";

export interface HostAsset {
  node_id: string;
  host_id: string;
  name: string;
  address: string;
  port: number;
  username: string;
  tags: string[];
  is_local: boolean;
  last_test_status: HostTestStatus | null;
  last_test_code: HostTestCode | null;
  last_tested_at: string | null;
  lifecycle_status: AssetLifecycleStatus;
  retired_at: string | null;
}

export interface HostAssetPage {
  items: HostAsset[];
  page: number;
  page_size: number;
  total: number;
}

export interface HostAssetListParams {
  page: number;
  page_size: number;
  search?: string;
  lifecycle_status?: AssetLifecycleStatus;
  detection_status?: HostDetectionFilter;
  tag?: string;
}

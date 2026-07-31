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
  management_status: "active";
  approved_at: string;
}

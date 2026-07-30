export interface User {
  id: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

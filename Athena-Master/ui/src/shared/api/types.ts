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

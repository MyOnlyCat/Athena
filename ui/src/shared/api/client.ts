import axios, { AxiosError } from "axios";

import type {
  ApiErrorBody,
  AuditLog,
  DeploymentEvent,
  DeploymentTask,
  FileEntry,
  Host,
  HostInput,
  MasterConnectionTestResponse,
  MasterSettingInput,
  MasterSettingResponse,
  SSHTestResult,
  UploadOptions,
  User
} from "./types";

export const api = axios.create({ baseURL: "/api/v1", timeout: 20_000 });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("athena_access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function apiMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = (error as AxiosError<ApiErrorBody>).response?.data;
    return body?.message ?? "服务暂时不可用，请稍后重试";
  }
  return error instanceof Error ? error.message : "操作失败";
}

export const authApi = {
  async login(username: string, password: string) {
    const { data } = await api.post<{ access_token: string; user: User }>("/auth/login", {
      username,
      password
    });
    return data;
  },
  async me() {
    return (await api.get<User>("/auth/me")).data;
  },
  async logout() {
    await api.post("/auth/logout");
  }
};

export const hostsApi = {
  list: async () => (await api.get<Host[]>("/hosts")).data,
  create: async (input: HostInput) => (await api.post<Host>("/hosts", input)).data,
  update: async (id: string, input: HostInput) =>
    (await api.put<Host>(`/hosts/${id}`, input)).data,
  remove: async (id: string) => api.delete(`/hosts/${id}`),
  test: async (id: string) => (await api.post<SSHTestResult>(`/hosts/${id}/test`)).data,
  trust: async (id: string, fingerprint: string) =>
    (await api.post<Host>(`/hosts/${id}/trust-fingerprint`, { fingerprint })).data
};

export const usersApi = {
  list: async () => (await api.get<User[]>("/users")).data,
  create: async (username: string, password: string) =>
    (await api.post<User>("/users", { username, password })).data,
  status: async (id: string, is_active: boolean) =>
    (await api.patch<User>(`/users/${id}/status`, { is_active })).data,
  resetPassword: async (id: string, password: string) =>
    api.post(`/users/${id}/reset-password`, { password })
};

export const tasksApi = {
  list: async () => (await api.get<DeploymentTask[]>("/tasks")).data,
  get: async (id: string) => (await api.get<DeploymentTask>(`/tasks/${id}`)).data,
  events: async (id: string) =>
    (await api.get<DeploymentEvent[]>(`/tasks/${id}/events`)).data
};

export const terminalApi = {
  ticket: async (hostId: string) =>
    (await api.post<{ ticket: string; expires_at: string }>("/terminal/tickets", {
      host_id: hostId
    })).data
};

function downloadFilename(contentDisposition: string | undefined, path: string): string {
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // Fall back to the regular filename parameter when the header is malformed.
    }
  }

  const fallback = contentDisposition?.match(/filename="([^"]*)"|filename=([^;\s]+)/i);
  return fallback?.[1] ?? fallback?.[2] ?? path.split("/").pop() ?? "download";
}

export const filesApi = {
  list: async (hostId: string, path: string) =>
    (await api.get<{ path: string; entries: FileEntry[] }>(`/files/${hostId}/list`, {
      params: { path }
    })).data,
  mkdir: async (hostId: string, path: string) =>
    api.post(`/files/${hostId}/directories`, { path }),
  rename: async (hostId: string, source: string, destination: string) =>
    api.patch(`/files/${hostId}/rename`, { source, destination }),
  remove: async (hostId: string, path: string, recursive: boolean) =>
    api.delete(`/files/${hostId}`, { data: { path, recursive } }),
  upload: async (hostId: string, path: string, file: File, options: UploadOptions) =>
    api.post(`/files/${hostId}/upload`, file, {
      params: { path },
      headers: { "Content-Type": "application/octet-stream" },
      signal: options.signal,
      onUploadProgress: options.onProgress,
      timeout: 0
    }),
  download: async (hostId: string, path: string) => {
    const response = await api.get<Blob>(`/files/${hostId}/download`, {
      params: { path },
      responseType: "blob",
      timeout: 0
    });
    const contentDisposition = response.headers["content-disposition"];
    return {
      blob: response.data,
      filename: downloadFilename(
        typeof contentDisposition === "string" ? contentDisposition : undefined,
        path
      )
    };
  }
};

export const masterSettingsApi = {
  get: async () => (await api.get<MasterSettingResponse>("/master-settings")).data,
  test: async (input: MasterSettingInput) =>
    (await api.post<MasterConnectionTestResponse>("/master-settings/test", input)).data,
  update: async (input: MasterSettingInput) =>
    (await api.put<MasterSettingResponse>("/master-settings", input)).data
};

export const auditApi = {
  list: async () => (await api.get<AuditLog[]>("/audit-logs")).data
};

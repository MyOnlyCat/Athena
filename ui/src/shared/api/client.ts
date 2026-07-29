import axios, { AxiosError } from "axios";

import type {
  ApiErrorBody,
  DeploymentTask,
  Host,
  HostInput,
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
  test: async (id: string) => (await api.post(`/hosts/${id}/test`)).data,
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
  get: async (id: string) => (await api.get<DeploymentTask>(`/tasks/${id}`)).data
};

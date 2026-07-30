import axios, { AxiosError } from "axios";

import type { ApiErrorBody, User } from "./types";

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

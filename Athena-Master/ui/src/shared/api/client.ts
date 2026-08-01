import axios, { AxiosError } from "axios";

import type {
  AccessNode,
  AccessNodePage,
  ApiErrorBody,
  HostAssetListParams,
  HostAssetPage,
  NodeListParams,
  RegistrationApplicationPage,
  User,
  UserPage
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

export const administratorsApi = {
  async list(page: number, pageSize: number) {
    return (
      await api.get<UserPage>("/administrators", {
        params: { page, page_size: pageSize }
      })
    ).data;
  },
  async create(username: string, password: string) {
    return (
      await api.post<User>("/administrators", {
        username,
        password
      })
    ).data;
  },
  async status(id: string, isActive: boolean) {
    return (
      await api.patch<User>(`/administrators/${id}/status`, {
        is_active: isActive
      })
    ).data;
  },
  async resetPassword(id: string, password: string) {
    await api.post(`/administrators/${id}/reset-password`, { password });
  }
};

export const registrationApplicationsApi = {
  async list(page: number, pageSize: number) {
    return (
      await api.get<RegistrationApplicationPage>("/registration-applications", {
        params: { page, page_size: pageSize }
      })
    ).data;
  },
  async approve(id: string, token: string) {
    return (
      await api.post<AccessNode>(`/registration-applications/${id}/approve`, {
        token
      })
    ).data;
  },
  async reject(id: string, reason?: string) {
    return (
      await api.post<RegistrationApplicationPage["items"][number]>(
        `/registration-applications/${id}/reject`,
        { reason: reason || null }
      )
    ).data;
  },
  async restore(id: string) {
    return (
      await api.post<RegistrationApplicationPage["items"][number]>(
        `/registration-applications/${id}/restore`
      )
    ).data;
  }
};

export const nodesApi = {
  async list(params: NodeListParams) {
    return (await api.get<AccessNodePage>("/nodes", { params })).data;
  },
  async listAssets(nodeId: string, params: HostAssetListParams) {
    return (await api.get<HostAssetPage>(`/nodes/${nodeId}/assets`, { params })).data;
  }
};

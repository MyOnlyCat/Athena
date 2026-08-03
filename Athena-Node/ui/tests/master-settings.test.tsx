import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRouter } from "../src/app/AppRouter";
import { MasterSettingsPage } from "../src/features/settings/MasterSettingsPage";
import { masterSettingsApi } from "../src/shared/api/client";
import type {
  MasterRuntimeStatus,
  MasterSettingResponse
} from "../src/shared/api/types";
import { ThemeProvider } from "../src/styles/ThemeProvider";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    loading: false,
    user: { id: "user-1", username: "alice" },
    logout: vi.fn()
  })
}));

vi.mock("../src/features/terminal/TerminalPage", () => ({ TerminalPage: () => null }));

const savedSettings: MasterSettingResponse = {
  node_id: "018f47a2-4b5c-7def-8123-456789abcdef",
  node_name: "Athena Node",
  scheme: "https",
  host: "master.example.com",
  port: 8443,
  has_token: true,
  runtime_status: "online",
  registration_status: "not_submitted"
};

const runtimeStatuses: Array<[MasterRuntimeStatus, string]> = [
  ["unconfigured", "未配置"],
  ["connecting", "连接中"],
  ["online", "在线"],
  ["error", "异常"],
  ["disabled", "已禁用"],
  ["authentication_failed", "认证失败"],
  ["connection_failed", "连接失败"],
  ["stopped", "已停止"]
];

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });

  render(
    <QueryClientProvider client={client}>
      <App>
        <MasterSettingsPage />
      </App>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }));
  vi.spyOn(masterSettingsApi, "get").mockResolvedValue(savedSettings);
  vi.spyOn(masterSettingsApi, "test").mockResolvedValue({ status: "success" });
  vi.spyOn(masterSettingsApi, "update").mockResolvedValue(savedSettings);
  vi.spyOn(masterSettingsApi, "register").mockResolvedValue({ status: "pending" });
  vi.spyOn(masterSettingsApi, "registrationStatus").mockResolvedValue({
    status: "pending"
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("loads saved connection details while keeping the Token field blank", async () => {
  renderPage();

  expect(await screen.findByDisplayValue("master.example.com")).toBeInTheDocument();
  expect(await screen.findByDisplayValue("8443")).toBeInTheDocument();
  expect(screen.getByLabelText("Token")).toHaveValue("");
  expect(screen.getByText("已保存")).toBeInTheDocument();
  expect(screen.getByText("在线")).toBeInTheDocument();
  expect(screen.getByText("Athena Node")).toBeInTheDocument();
  expect(screen.getByText("018f47a2-4b5c-7def-8123-456789abcdef")).toBeInTheDocument();
});

test("groups Token controls and configuration actions into consistent UI regions", async () => {
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  const tokenGroup = screen.getByRole("group", { name: "Token 配置" });
  expect(within(tokenGroup).getByLabelText("Token")).toBeInTheDocument();
  expect(within(tokenGroup).getByRole("button", { name: /生成 Token$/ })).toBeInTheDocument();
  expect(within(tokenGroup).getByRole("button", { name: /复制 Token$/ })).toBeInTheDocument();

  const actions = screen.getByRole("group", { name: "配置操作" });
  expect(within(actions).getByRole("button", { name: /连接测试$/ })).toBeInTheDocument();
  expect(within(actions).getByRole("button", { name: /保存并应用$/ })).toBeInTheDocument();
  expect(within(actions).getByRole("button", { name: /申请接入$/ })).toBeInTheDocument();
});

test("requires saving changed settings before submitting a registration application", async () => {
  const user = userEvent.setup();
  const updatedSettings = { ...savedSettings, host: "new-master.example.com" };
  vi.mocked(masterSettingsApi.get)
    .mockResolvedValueOnce(savedSettings)
    .mockResolvedValueOnce(updatedSettings)
    .mockResolvedValueOnce({ ...updatedSettings, registration_status: "pending" });
  vi.mocked(masterSettingsApi.update).mockResolvedValueOnce(updatedSettings);
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  const hostInput = screen.getByLabelText("主节点地址");
  await user.clear(hostInput);
  await user.type(hostInput, "new-master.example.com");

  expect(screen.getByRole("button", { name: /申请接入$/ })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /保存并应用$/ }));
  await waitFor(() => expect(masterSettingsApi.update).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: /申请接入$/ })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: /申请接入$/ }));
  await waitFor(() => expect(masterSettingsApi.register).toHaveBeenCalledTimes(1));
  expect(masterSettingsApi.update).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("待管理员审批")).toBeInTheDocument();
});

test("refreshes a pending registration to approved without a Master callback", async () => {
  vi.mocked(masterSettingsApi.get).mockResolvedValueOnce({
    ...savedSettings,
    registration_status: "pending"
  });
  vi.mocked(masterSettingsApi.registrationStatus).mockResolvedValueOnce({
    status: "approved"
  });

  renderPage();

  expect(await screen.findByText("已批准")).toBeInTheDocument();
  expect(masterSettingsApi.registrationStatus).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("待管理员审批")).not.toBeInTheDocument();
});

test("shows rejection clearly and stops automatic status polling", async () => {
  vi.mocked(masterSettingsApi.get).mockResolvedValueOnce({
    ...savedSettings,
    registration_status: "pending"
  });
  vi.mocked(masterSettingsApi.registrationStatus).mockResolvedValueOnce({
    status: "rejected"
  });
  renderPage();

  expect(await screen.findByText("已拒绝")).toBeInTheDocument();
  expect(screen.getByText("管理员恢复后，请手动重新提交申请。")).toBeInTheDocument();
  expect(masterSettingsApi.registrationStatus).toHaveBeenCalledTimes(1);
});

test("generates a 32-byte Base64URL Token and copies it immediately", async () => {
  const user = userEvent.setup();
  const random = vi.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
    (array as Uint8Array).fill(255);
    return array;
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText }
  });
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  await user.click(screen.getByRole("button", { name: /生成 Token$/ }));

  const generated = `${"_".repeat(42)}8`;
  expect(random).toHaveBeenCalled();
  expect(screen.getByLabelText("Token")).toHaveValue(generated);
  expect(screen.getByRole("button", { name: /申请接入$/ })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /复制 Token$/ }));
  expect(writeText).toHaveBeenCalledWith(generated);
});

test("shows a Chinese validation error for a short manually entered Token", async () => {
  const user = userEvent.setup();
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  await user.type(screen.getByLabelText("Token"), "too-short");
  await user.click(screen.getByRole("button", { name: /保存并应用$/ }));

  expect(await screen.findByText("Token 长度必须为 32 至 256 个字符")).toBeInTheDocument();
  expect(masterSettingsApi.update).not.toHaveBeenCalled();
});

test.each(runtimeStatuses)("renders the %s runtime status in Chinese", async (runtime_status, label) => {
  vi.mocked(masterSettingsApi.get).mockResolvedValueOnce({
    ...savedSettings,
    runtime_status
  });

  renderPage();

  expect(await screen.findByText(label)).toBeInTheDocument();
});

test("submits an empty Token when testing and saving a saved configuration", async () => {
  const user = userEvent.setup();
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  await user.click(screen.getByRole("button", { name: /连接测试$/ }));
  await waitFor(() => expect(masterSettingsApi.test).toHaveBeenCalledWith({
    scheme: "https", host: "master.example.com", port: 8443, token: ""
  }));

  await user.click(screen.getByRole("button", { name: /保存并应用$/ }));
  await waitFor(() => expect(masterSettingsApi.update).toHaveBeenCalledWith({
    scheme: "https", host: "master.example.com", port: 8443, token: ""
  }));
});

test("renders Chinese API errors from connection tests and saves", async () => {
  const user = userEvent.setup();
  const masterConnectionError = Object.assign(new Error("Unable to connect to the master node"), {
    isAxiosError: true,
    response: {
      data: {
        code: "MASTER_CONNECTION_FAILED",
        message: "Unable to connect to the master node"
      }
    }
  });
  vi.mocked(masterSettingsApi.test).mockRejectedValueOnce(masterConnectionError);
  vi.mocked(masterSettingsApi.update).mockRejectedValueOnce(masterConnectionError);
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  await user.click(screen.getByRole("button", { name: /连接测试$/ }));
  expect(await screen.findByText("无法连接到主节点，请检查地址、端口和 Token。")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /保存并应用$/ }));
  expect(await screen.findByText("无法连接到主节点，请检查地址、端口和 Token。"))
    .toBeInTheDocument();
});

test("replaces unstructured English connection errors with a Chinese operator hint", async () => {
  const user = userEvent.setup();
  vi.mocked(masterSettingsApi.test).mockRejectedValueOnce(new Error("Network Error"));
  renderPage();

  await screen.findByDisplayValue("master.example.com");
  await user.click(screen.getByRole("button", { name: /连接测试$/ }));

  expect(await screen.findByText("连接测试失败，请检查配置后重试。")).toBeInTheDocument();
});

test("exposes the master settings page through the navigation menu and route", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });

  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/master-settings"]}>
        <QueryClientProvider client={client}>
          <App>
            <AppRouter />
          </App>
        </QueryClientProvider>
      </MemoryRouter>
    </ThemeProvider>
  );

  expect(await screen.findByRole("heading", { name: "主节点配置" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: /主节点配置$/ })).toBeInTheDocument();
  await screen.findByDisplayValue("master.example.com");
});

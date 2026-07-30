import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRouter } from "../src/app/AppRouter";
import { MasterSettingsPage } from "../src/features/settings/MasterSettingsPage";
import { masterSettingsApi } from "../src/shared/api/client";
import { ThemeProvider } from "../src/styles/ThemeProvider";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    loading: false,
    user: { id: "user-1", username: "alice" },
    logout: vi.fn()
  })
}));

vi.mock("../src/features/terminal/TerminalPage", () => ({ TerminalPage: () => null }));

const savedSettings = {
  scheme: "https" as const,
  host: "master.example.com",
  port: 8443,
  has_token: true,
  runtime_status: "running"
};

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
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("loads saved connection details while keeping the Token field blank", async () => {
  renderPage();

  expect(await screen.findByDisplayValue("master.example.com")).toBeInTheDocument();
  expect(screen.getByDisplayValue("8443")).toBeInTheDocument();
  expect(screen.getByLabelText("Token")).toHaveValue("");
  expect(screen.getByText("已保存")).toBeInTheDocument();
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

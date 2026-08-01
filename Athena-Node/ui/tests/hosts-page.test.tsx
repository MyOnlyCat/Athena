import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { HostsPage } from "../src/features/hosts/HostsPage";
import { hostsApi } from "../src/shared/api/client";
import type { Host } from "../src/shared/api/types";

const host: Host = {
  id: "host-1",
  name: "web-01",
  address: "10.0.0.10",
  port: 22,
  username: "root",
  tags: ["production"],
  is_local: false,
  has_password: true,
  host_key_fingerprint: null,
  last_test_status: null,
  last_test_code: null,
  last_test_message: null,
  last_tested_at: null,
  created_at: "2026-07-30T00:00:00Z"
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });

  render(
    <QueryClientProvider client={client}>
      <App>
        <HostsPage />
      </App>
    </QueryClientProvider>
  );
}

function mockPendingTrustThen(result: { status: string; code: string; message: string }) {
  vi.spyOn(hostsApi, "list").mockReset().mockResolvedValue([host]);
  vi.spyOn(hostsApi, "test")
    .mockReset()
    .mockResolvedValueOnce({
      status: "pending_trust",
      code: "SSH_HOST_KEY_UNTRUSTED",
      message: "请确认主机指纹",
      fingerprint: "SHA256:first"
    })
    .mockResolvedValueOnce({ ...result, fingerprint: "SHA256:first" });
  vi.spyOn(hostsApi, "trust").mockReset().mockResolvedValue({
    ...host,
    host_key_fingerprint: "SHA256:first"
  });
}

async function findTestConnectionButton() {
  const icon = await screen.findByRole("img", { name: "thunderbolt" });
  const button = icon.closest("button");
  if (!button) throw new Error("测试连接控件不是按钮");
  return button;
}

beforeEach(() => {
  vi.spyOn(hostsApi, "getProbeSettings").mockResolvedValue({ interval_minutes: 5 });
  vi.spyOn(hostsApi, "updateProbeSettings").mockImplementation(async (interval_minutes) => ({
    interval_minutes
  }));
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
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("shows the verified SSH success after trusting an untrusted fingerprint", async () => {
  mockPendingTrustThen({
    status: "success",
    code: "SSH_CONNECTED",
    message: "SSH 连接成功"
  });
  const user = userEvent.setup();

  renderPage();

  await user.click(await findTestConnectionButton());
  await user.click(await screen.findByRole("button", { name: "信任此指纹" }));

  expect(hostsApi.trust).toHaveBeenCalledWith("host-1", "SHA256:first");
  expect(hostsApi.test).toHaveBeenCalledTimes(2);
  expect(vi.mocked(hostsApi.trust).mock.invocationCallOrder[0]).toBeLessThan(
    vi.mocked(hostsApi.test).mock.invocationCallOrder[1]
  );
  expect(await screen.findByText("SSH 连接成功")).toBeInTheDocument();
});

test("loads and dynamically saves the global host probe interval", async () => {
  vi.spyOn(hostsApi, "list").mockResolvedValue([host]);
  const user = userEvent.setup();

  renderPage();

  const input = await screen.findByRole("spinbutton", { name: "探活间隔" });
  expect(input).toHaveValue("5");
  await waitFor(() => expect(input).toBeEnabled());
  await user.clear(input);
  await user.type(input, "10");
  await user.click(screen.getByRole("button", { name: "保存间隔" }));

  expect(hostsApi.updateProbeSettings).toHaveBeenCalledWith(10);
  expect(await screen.findByText("探活间隔已保存，并已触发全量探活")).toBeInTheDocument();
});

test("shows the final SSH failure after trusting an untrusted fingerprint", async () => {
  mockPendingTrustThen({
    status: "failed",
    code: "SSH_CONNECTION_FAILED",
    message: "认证失败"
  });
  const user = userEvent.setup();

  renderPage();

  await user.click(await findTestConnectionButton());
  await user.click(await screen.findByRole("button", { name: "信任此指纹" }));

  expect(hostsApi.trust).toHaveBeenCalledWith("host-1", "SHA256:first");
  expect(hostsApi.test).toHaveBeenCalledTimes(2);
  expect(vi.mocked(hostsApi.trust).mock.invocationCallOrder[0]).toBeLessThan(
    vi.mocked(hostsApi.test).mock.invocationCallOrder[1]
  );
  expect(await screen.findByText("认证失败")).toBeInTheDocument();
});

test("shows the trust error without retesting when fingerprint trust fails", async () => {
  vi.spyOn(hostsApi, "list").mockReset().mockResolvedValue([host]);
  vi.spyOn(hostsApi, "test")
    .mockReset()
    .mockResolvedValueOnce({
      status: "pending_trust",
      code: "SSH_HOST_KEY_UNTRUSTED",
      message: "请确认主机指纹",
      fingerprint: "SHA256:first"
    });
  vi.spyOn(hostsApi, "trust").mockReset().mockRejectedValue(new Error("信任请求失败"));
  const user = userEvent.setup();

  renderPage();

  await user.click(await findTestConnectionButton());
  await user.click(await screen.findByRole("button", { name: "信任此指纹" }));

  expect(await screen.findByText("信任请求失败")).toBeInTheDocument();
  expect(hostsApi.test).toHaveBeenCalledTimes(1);
});

test("refreshes the persisted changed-key status when fingerprint confirmation is cancelled", async () => {
  const successfulHost = { ...host, last_test_status: "success" };
  const pendingHost = { ...host, last_test_status: "pending_trust" };
  vi.spyOn(hostsApi, "list")
    .mockResolvedValueOnce([successfulHost])
    .mockResolvedValue([pendingHost]);
  vi.spyOn(hostsApi, "test").mockResolvedValue({
    status: "pending_trust",
    code: "SSH_HOST_KEY_CHANGED",
    message: "主机指纹发生变化",
    fingerprint: "SHA256:changed"
  });
  vi.spyOn(hostsApi, "trust").mockResolvedValue(host);
  const user = userEvent.setup();

  renderPage();

  expect(await screen.findByText("连接正常")).toBeInTheDocument();
  await user.click(await findTestConnectionButton());
  expect(
    await screen.findByRole("dialog", { name: "主机指纹发生变化" })
  ).toBeInTheDocument();
  expect(await screen.findByText("待确认指纹")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  expect(hostsApi.trust).not.toHaveBeenCalled();
});

test("requires explicit confirmation before trusting a changed host fingerprint", async () => {
  vi.spyOn(hostsApi, "list").mockResolvedValue([host]);
  vi.spyOn(hostsApi, "test")
    .mockResolvedValueOnce({
      status: "pending_trust",
      code: "SSH_HOST_KEY_CHANGED",
      message: "主机指纹发生变化",
      fingerprint: "SHA256:changed"
    })
    .mockResolvedValueOnce({
      status: "success",
      code: "SSH_CONNECTED",
      message: "SSH 连接成功",
      fingerprint: "SHA256:changed"
    });
  vi.spyOn(hostsApi, "trust").mockResolvedValue({
    ...host,
    host_key_fingerprint: "SHA256:changed"
  });
  const user = userEvent.setup();

  renderPage();

  await user.click(await findTestConnectionButton());
  expect(
    await screen.findByRole("dialog", { name: "主机指纹发生变化" })
  ).toBeInTheDocument();
  expect(hostsApi.trust).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "信任此指纹" }));

  expect(hostsApi.trust).toHaveBeenCalledWith("host-1", "SHA256:changed");
  expect(await screen.findByText("SSH 连接成功")).toBeInTheDocument();
});

test("fails closed when a fingerprint challenge omits the fingerprint", async () => {
  vi.spyOn(hostsApi, "list").mockResolvedValue([host]);
  vi.spyOn(hostsApi, "test").mockResolvedValue({
    status: "pending_trust",
    code: "SSH_HOST_KEY_CHANGED",
    message: "主机指纹发生变化",
    fingerprint: null
  });
  vi.spyOn(hostsApi, "trust").mockResolvedValue(host);
  const user = userEvent.setup();

  renderPage();

  await user.click(await findTestConnectionButton());

  expect(await screen.findByText("服务器未返回可验证的主机指纹")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "信任此指纹" })).not.toBeInTheDocument();
  expect(hostsApi.trust).not.toHaveBeenCalled();
});

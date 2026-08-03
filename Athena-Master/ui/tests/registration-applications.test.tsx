import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { RegistrationApplicationsPage } from "../src/features/registrations/RegistrationApplicationsPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  restore: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  registrationApplicationsApi: apiMocks,
  apiMessage: (error: unknown) => (error instanceof Error ? error.message : "操作失败")
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });
  return render(
    <App>
      <QueryClientProvider client={queryClient}>
        <RegistrationApplicationsPage />
      </QueryClientProvider>
    </App>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.list.mockResolvedValue({
    items: [
      {
        id: "application-1",
        node_id: "018f47a2-4b5c-7def-8123-456789abcdef",
        reported_name: "上海接入节点",
        hostname: "athena-node-01",
        software_version: "0.1.0",
        status: "pending",
        identity_verified: false,
        received_at: "2026-07-31T03:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  apiMocks.approve.mockResolvedValue({
    node_id: "018f47a2-4b5c-7def-8123-456789abcdef",
    management_status: "active"
  });
  apiMocks.reject.mockResolvedValue({ id: "application-1", status: "rejected" });
  apiMocks.restore.mockResolvedValue({ id: "application-1", status: "restored" });
});

test("marks application data untrusted and approves with a non-disclosed Token", async () => {
  const user = userEvent.setup();
  renderPage();

  expect(await screen.findByText("上海接入节点")).toBeInTheDocument();
  expect(
    screen.getByText(
      `浏览器时区：${
        Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区"
      }`
    )
  ).toBeInTheDocument();
  expect(screen.getByText("身份未验证")).toBeInTheDocument();
  expect(screen.getByText("athena-node-01")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /批\s*准/ }));

  const dialog = await screen.findByRole("dialog", { name: /批准注册申请/ });
  const tokenInput = within(dialog).getByLabelText("Node Token");
  await user.type(tokenInput, "registration-secret-token-value-123");
  await user.click(within(dialog).getByRole("button", { name: /批\s*准/ }));

  await waitFor(() =>
    expect(apiMocks.approve).toHaveBeenCalledWith(
      "application-1",
      "registration-secret-token-value-123"
    )
  );
  await waitFor(() => expect(dialog).not.toBeVisible());
  expect(
    screen.queryByDisplayValue("registration-secret-token-value-123")
  ).not.toBeInTheDocument();
  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
}, 10_000);

test("keeps the application available when Token verification fails", async () => {
  apiMocks.approve.mockRejectedValueOnce(new Error("Token 与注册申请不匹配"));
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: /批\s*准/ }));
  const dialog = await screen.findByRole("dialog", { name: /批准注册申请/ });
  await user.type(within(dialog).getByLabelText("Node Token"), "wrong-token-value-that-is-long-enough");
  await user.click(within(dialog).getByRole("button", { name: /批\s*准/ }));

  expect(await screen.findByText("Token 与注册申请不匹配")).toBeInTheDocument();
  expect(screen.getByText("上海接入节点")).toBeInTheDocument();
}, 10_000);

test("rejects an application with an optional reason", async () => {
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: /拒\s*绝/ }));
  const dialog = await screen.findByRole("dialog", { name: /拒绝注册申请/ });
  await user.type(within(dialog).getByLabelText("拒绝原因"), "来源尚未核实");
  await user.click(within(dialog).getByRole("button", { name: /拒\s*绝/ }));

  await waitFor(() =>
    expect(apiMocks.reject).toHaveBeenCalledWith("application-1", "来源尚未核实")
  );
  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
});

test("shows a rejected application and lets an administrator restore reapplication", async () => {
  apiMocks.list.mockResolvedValueOnce({
    items: [
      {
        id: "application-1",
        node_id: "018f47a2-4b5c-7def-8123-456789abcdef",
        reported_name: "上海接入节点",
        hostname: "athena-node-01",
        software_version: "0.1.0",
        status: "rejected",
        rejection_reason: "来源尚未核实",
        identity_verified: false,
        received_at: "2026-07-31T03:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  const user = userEvent.setup();
  renderPage();

  expect(await screen.findByText("已拒绝")).toBeInTheDocument();
  expect(screen.getByText("来源尚未核实")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /恢复申请/ }));

  await waitFor(() => expect(apiMocks.restore).toHaveBeenCalledWith("application-1"));
  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
});

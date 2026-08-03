import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, test, vi } from "vitest";

import { AuditPage } from "../src/features/audit/AuditPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  auditApi: apiMocks,
  apiMessage: (error: unknown) =>
    error instanceof Error ? error.message : "操作失败"
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.list.mockResolvedValue({
    items: [
      {
        id: "audit-2",
        actor_id: "admin-1",
        actor_username: "admin",
        action: "node.token.rotate",
        target_type: "access_node",
        target_id: "node-1",
        target_label: "上海接入节点",
        result: "success",
        source_ip: "127.0.0.1",
        error_code: null,
        created_at: "2026-08-03T04:05:06Z",
        details: { token: "must-never-render" }
      },
      {
        id: "audit-1",
        actor_id: null,
        actor_username: null,
        action: "auth.login",
        target_type: "administrator",
        target_id: "missing-admin",
        target_label: "missing-admin",
        result: "failure",
        source_ip: "192.0.2.10",
        error_code: "INVALID_CREDENTIALS",
        created_at: "2026-08-03T04:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 2
  });
});

test("shows safe Chinese audit records with actor, target, result and time zone", async () => {
  renderPage();

  expect(await screen.findByText("更换 Node Token")).toBeInTheDocument();
  expect(screen.getByText("管理员登录")).toBeInTheDocument();
  expect(screen.getByText("admin")).toBeInTheDocument();
  expect(screen.getByText("未认证")).toBeInTheDocument();
  expect(screen.getByText("上海接入节点")).toBeInTheDocument();
  expect(screen.getByText("missing-admin")).toBeInTheDocument();
  expect(screen.getByText("成功")).toBeInTheDocument();
  expect(screen.getByText("失败")).toBeInTheDocument();
  expect(screen.getByText("127.0.0.1")).toBeInTheDocument();
  expect(screen.getByText(/浏览器时区/)).toBeInTheDocument();
  expect(screen.getByText(/共 2 条审计记录/)).toBeInTheDocument();
  expect(screen.queryByText("must-never-render")).not.toBeInTheDocument();
  expect(apiMocks.list).toHaveBeenCalledWith(1, 20);
});

test("requests the selected server page", async () => {
  apiMocks.list.mockResolvedValue({
    items: [],
    page: 1,
    page_size: 20,
    total: 21
  });
  const user = userEvent.setup();
  renderPage();

  await screen.findByText("共 21 条审计记录");
  await user.click(screen.getByTitle("2"));

  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledWith(2, 20));
});

test("shows API failures instead of an empty audit history", async () => {
  apiMocks.list.mockRejectedValueOnce(new Error("审计记录加载失败"));
  renderPage();

  expect(await screen.findByText("审计记录加载失败")).toBeInTheDocument();
  expect(screen.queryByText("No data")).not.toBeInTheDocument();
});

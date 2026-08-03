import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { AdministratorsPage } from "../src/features/administrators/AdministratorsPage";
import { AdministratorTable } from "../src/features/administrators/AdministratorTable";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  status: vi.fn(),
  resetPassword: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  administratorsApi: apiMocks,
  apiMessage: (error: unknown) => (error instanceof Error ? error.message : "操作失败")
}));

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "admin-1",
      username: "admin",
      is_active: true,
      last_login_at: null,
      created_at: "2026-07-29T00:00:00Z"
    }
  })
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  });
  return render(
    <App>
      <QueryClientProvider client={queryClient}>
        <AdministratorsPage />
      </QueryClientProvider>
    </App>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("shows administrator state and protects the current account from disable", () => {
  render(
    <AdministratorTable
      currentUserId="admin-1"
      users={[
        {
          id: "admin-1",
          username: "admin",
          is_active: true,
          last_login_at: "2026-07-30T12:00:00Z",
          created_at: "2026-07-29T00:00:00Z"
        }
      ]}
      loading={false}
      page={1}
      pageSize={20}
      total={1}
      onPageChange={() => undefined}
      onStatusChange={() => undefined}
      onResetPassword={() => undefined}
    />
  );

  expect(screen.getByText("admin")).toBeInTheDocument();
  expect(screen.getByText("当前账号")).toBeInTheDocument();
  expect(screen.getByText("已启用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /禁\s*用/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /重置密码/ })).toBeInTheDocument();
});

test("creates an administrator and refreshes the server-paginated list", async () => {
  apiMocks.list.mockResolvedValue({
    items: [
      {
        id: "admin-1",
        username: "admin",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-29T00:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  apiMocks.create.mockResolvedValue({
    id: "admin-2",
    username: "operator",
    is_active: true,
    last_login_at: null,
    created_at: "2026-07-30T00:00:00Z"
  });
  const user = userEvent.setup();
  renderPage();

  expect(await screen.findByText("admin")).toBeInTheDocument();
  expect(
    screen.getByText(
      `浏览器时区：${
        Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区"
      }`
    )
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /创建管理员/ }));
  await user.type(screen.getByLabelText("用户名"), " operator ");
  await user.type(screen.getByLabelText("初始密码"), "OperatorPassword123");
  await user.click(screen.getByRole("button", { name: /创\s*建$/ }));

  await waitFor(() =>
    expect(apiMocks.create).toHaveBeenCalledWith("operator", "OperatorPassword123")
  );
  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
}, 10_000);

test("confirms status changes and password resets before refreshing the list", async () => {
  apiMocks.list.mockResolvedValue({
    items: [
      {
        id: "admin-1",
        username: "admin",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-29T00:00:00Z"
      },
      {
        id: "admin-2",
        username: "operator",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-30T00:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 2
  });
  apiMocks.status.mockResolvedValue({ id: "admin-2", is_active: false });
  apiMocks.resetPassword.mockResolvedValue(undefined);
  const user = userEvent.setup();
  renderPage();

  let operatorRow = await screen.findByRole("row", { name: /operator/ });
  await user.click(within(operatorRow).getByRole("button", { name: /禁\s*用/ }));
  const statusDialog = await screen.findByRole("dialog", { name: /禁用管理员/ });
  await user.click(within(statusDialog).getByRole("button", { name: /禁\s*用/ }));
  await waitFor(() => expect(apiMocks.status).toHaveBeenCalledWith("admin-2", false));

  operatorRow = await screen.findByRole("row", { name: /operator/ });
  await user.click(within(operatorRow).getByRole("button", { name: "重置密码" }));
  const resetDialog = await screen.findByRole("dialog", { name: /重置.*密码/ });
  await user.type(within(resetDialog).getByLabelText("新密码"), "ChangedPassword456");
  await user.click(within(resetDialog).getByRole("button", { name: /重\s*置/ }));

  await waitFor(() =>
    expect(apiMocks.resetPassword).toHaveBeenCalledWith("admin-2", "ChangedPassword456")
  );
  expect(
    await screen.findByText("密码已重置，原有登录凭证已失效")
  ).toBeInTheDocument();
  expect(apiMocks.list.mock.calls.length).toBeGreaterThanOrEqual(3);
}, 10_000);

test("shows the duplicate normalized username error from the API", async () => {
  apiMocks.list.mockResolvedValue({
    items: [],
    page: 1,
    page_size: 20,
    total: 0
  });
  apiMocks.create.mockRejectedValueOnce(new Error("用户名已存在"));
  const user = userEvent.setup();
  renderPage();

  await screen.findAllByText("No data");
  await user.click(screen.getByRole("button", { name: /创建管理员/ }));
  await user.type(screen.getByLabelText("用户名"), " ADMIN ");
  await user.type(screen.getByLabelText("初始密码"), "AnotherPassword456");
  await user.click(screen.getByRole("button", { name: /创\s*建$/ }));

  expect(await screen.findByText("用户名已存在")).toBeInTheDocument();
  expect(apiMocks.create).toHaveBeenCalledWith("ADMIN", "AnotherPassword456");
});

test("shows the last-active-administrator protection from the API", async () => {
  apiMocks.list.mockResolvedValue({
    items: [
      {
        id: "admin-1",
        username: "admin",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-29T00:00:00Z"
      },
      {
        id: "admin-2",
        username: "operator",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-30T00:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 2
  });
  apiMocks.status.mockRejectedValueOnce(new Error("不能禁用最后一个可用管理员"));
  const user = userEvent.setup();
  renderPage();

  const operatorRow = await screen.findByRole("row", { name: /operator/ });
  await user.click(within(operatorRow).getByRole("button", { name: /禁\s*用/ }));
  const dialog = await screen.findByRole("dialog", { name: /禁用管理员/ });
  await user.click(within(dialog).getByRole("button", { name: /禁\s*用/ }));

  expect(await screen.findByText("不能禁用最后一个可用管理员")).toBeInTheDocument();
});

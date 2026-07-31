import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { NodesPage } from "../src/features/nodes/NodesPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  nodesApi: apiMocks
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <App>
      <QueryClientProvider client={queryClient}>
        <NodesPage />
      </QueryClientProvider>
    </App>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.list.mockResolvedValue({
    items: [
      {
        node_id: "019d3a7e-7c42-7000-8000-000000000007",
        reported_name: "上海接入节点",
        hostname: "athena-node-01",
        software_version: "0.2.0",
        management_status: "active",
        connectivity_status: "stale",
        approved_at: "2026-07-31T08:00:00Z",
        last_heartbeat_at: "2026-07-31T09:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
});

test("shows reported identity, management state, connectivity and last heartbeat", async () => {
  renderPage();

  expect(await screen.findByText("上海接入节点")).toBeInTheDocument();
  expect(screen.getByText("athena-node-01")).toBeInTheDocument();
  expect(screen.getByText("版本 0.2.0")).toBeInTheDocument();
  expect(screen.getByText("已启用")).toBeInTheDocument();
  expect(screen.getByText("心跳延迟")).toBeInTheDocument();
  expect(screen.getByText(/浏览器时区：/)).toBeInTheDocument();
});

test("sends search, filtering and sorting to the server", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("上海接入节点");

  const search = screen.getByPlaceholderText("搜索名称、主机名、版本或节点 ID");
  await user.type(search, "上海{Enter}");
  await waitFor(() =>
    expect(apiMocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: "上海" })
    )
  );

  await user.click(screen.getByRole("combobox", { name: "连接状态" }));
  await user.click(await screen.findByText("离线"));
  await waitFor(() =>
    expect(apiMocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ connectivity_status: "offline" })
    )
  );

  await user.click(screen.getByRole("combobox", { name: "排序字段" }));
  await user.click(await screen.findByText("上报名"));
  await waitFor(() =>
    expect(apiMocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: "reported_name" })
    )
  );
});

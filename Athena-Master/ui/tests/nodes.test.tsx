import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";

import { NodesPage } from "../src/features/nodes/NodesPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  listAssets: vi.fn(),
  updateInfo: vi.fn(),
  updateStatus: vi.fn(),
  rotateToken: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  nodesApi: apiMocks
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  const view = render(
    <App>
      <QueryClientProvider client={queryClient}>
        <NodesPage />
      </QueryClientProvider>
    </App>
  );
  return { ...view, queryClient };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.list.mockResolvedValue({
    items: [
      {
        node_id: "019d3a7e-7c42-7000-8000-000000000007",
        reported_name: "上海接入节点",
        display_name: "上海生产节点",
        effective_name: "上海生产节点",
        hostname: "athena-node-01",
        software_version: "0.2.0",
        management_status: "active",
        notes: "由平台组维护",
        management_tags: ["生产", "华东"],
        disable_reason: null,
        connectivity_status: "stale",
        approved_at: "2026-07-31T08:00:00Z",
        last_heartbeat_at: "2026-07-31T09:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  apiMocks.listAssets.mockResolvedValue({
    items: [
      {
        node_id: "019d3a7e-7c42-7000-8000-000000000007",
        host_id: "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
        name: "web-01",
        address: "10.0.0.10",
        port: 22,
        username: "root",
        tags: ["production"],
        is_local: true,
        last_test_status: "failed",
        last_test_code: "SSH_TIMEOUT",
        last_tested_at: "2026-07-31T08:59:00Z",
        lifecycle_status: "active",
        retired_at: null,
        source_node_connectivity_status: "online"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  apiMocks.updateInfo.mockResolvedValue({});
  apiMocks.updateStatus.mockResolvedValue({});
  apiMocks.rotateToken.mockResolvedValue({});
});

test("shows the selected access node's read-only host assets", async () => {
  renderPage();

  expect(await screen.findByText("web-01")).toBeInTheDocument();
  expect(screen.getByRole("radio")).toBeChecked();
  expect(screen.getByText("10.0.0.10:22")).toHaveClass("mono");
  expect(screen.getByText("连接失败")).toBeInTheDocument();
  expect(screen.getByText("SSH_TIMEOUT")).toBeInTheDocument();
  expect(screen.getByText("在管")).toBeInTheDocument();
  expect(apiMocks.listAssets).toHaveBeenCalledWith(
    "019d3a7e-7c42-7000-8000-000000000007",
    expect.objectContaining({ page: 1, page_size: 20 })
  );
});

test("shows reported identity, management state, connectivity and last heartbeat", async () => {
  renderPage();

  expect(await screen.findByRole("heading", { name: "上海生产节点" })).toBeInTheDocument();
  expect(screen.getAllByText("Node 上报名：上海接入节点")).toHaveLength(2);
  expect(screen.getByText("athena-node-01")).toBeInTheDocument();
  expect(screen.getByText("版本 0.2.0")).toBeInTheDocument();
  expect(screen.getByText("已启用")).toBeInTheDocument();
  expect(screen.getByText("心跳延迟")).toBeInTheDocument();
  expect(screen.getByText(/浏览器时区：/)).toBeInTheDocument();
});

afterEach(() => {
  vi.useRealTimers();
});

test("shows delayed and unknown asset state without hiding the last test details", async () => {
  apiMocks.listAssets
    .mockResolvedValueOnce({
      items: [
        {
          node_id: "019d3a7e-7c42-7000-8000-000000000007",
          host_id: "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
          name: "stale-web",
          address: "10.0.0.10",
          port: 22,
          username: "root",
          tags: [],
          is_local: false,
          last_test_status: "failed",
          last_test_code: "SSH_TIMEOUT",
          last_tested_at: "2026-07-31T08:59:00Z",
          lifecycle_status: "active",
          retired_at: null,
          source_node_connectivity_status: "stale"
        }
      ],
      page: 1,
      page_size: 20,
      total: 1
    })
    .mockResolvedValueOnce({
      items: [
        {
          node_id: "019d3a7e-7c42-7000-8000-000000000007",
          host_id: "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
          name: "offline-web",
          address: "10.0.0.10",
          port: 22,
          username: "root",
          tags: [],
          is_local: false,
          last_test_status: "success",
          last_test_code: "SSH_CONNECTED",
          last_tested_at: "2026-07-31T08:59:00Z",
          lifecycle_status: "active",
          retired_at: null,
          source_node_connectivity_status: "offline"
        }
      ],
      page: 1,
      page_size: 20,
      total: 1
    });
  const { unmount } = renderPage();

  expect(await screen.findByText("数据延迟（来源节点心跳延迟）")).toBeInTheDocument();
  expect(screen.getByText("最后检测：连接失败")).toBeInTheDocument();
  expect(screen.getByText("SSH_TIMEOUT")).toBeInTheDocument();

  unmount();
  renderPage();
  expect(await screen.findByText("状态未知（来源节点离线）")).toBeInTheDocument();
  expect(screen.getByText("最后检测：连接正常")).toBeInTheDocument();
  expect(screen.getByText("SSH_CONNECTED")).toBeInTheDocument();
});

test("updates administrator-owned node information without changing reported identity", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByRole("heading", { name: "上海生产节点" });

  await user.click(screen.getByRole("button", { name: "编辑管理信息" }));
  const dialog = await screen.findByRole("dialog", { name: "编辑管理信息" });
  const displayName = within(dialog).getByLabelText("管理显示名");
  await user.clear(displayName);
  await user.type(displayName, "上海核心节点");
  await user.click(within(dialog).getByRole("button", { name: /保\s*存/ }));

  await waitFor(() =>
    expect(apiMocks.updateInfo).toHaveBeenCalledWith(
      "019d3a7e-7c42-7000-8000-000000000007",
      {
        display_name: "上海核心节点",
        notes: "由平台组维护",
        management_tags: ["生产", "华东"]
      }
    )
  );
});

test("disables a node with an optional reason and refreshes the list", async () => {
  const user = userEvent.setup();
  const { queryClient } = renderPage();
  queryClient.setQueryData(["overview"], { cached: true });
  await screen.findByRole("heading", { name: "上海生产节点" });

  await user.click(screen.getByRole("button", { name: "禁用节点" }));
  const dialog = await screen.findByRole("dialog", { name: "禁用接入节点" });
  await user.type(within(dialog).getByLabelText("禁用原因（可选）"), "计划维护");
  await user.click(within(dialog).getByRole("button", { name: "确认禁用" }));

  await waitFor(() =>
    expect(apiMocks.updateStatus).toHaveBeenCalledWith(
      "019d3a7e-7c42-7000-8000-000000000007",
      "disabled",
      "计划维护"
    )
  );
  await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
  expect(queryClient.getQueryState(["overview"])?.isInvalidated).toBe(true);
});

test("refreshes the node list and selected asset page every 30 seconds", async () => {
  vi.useFakeTimers();
  const { unmount } = renderPage();

  await act(async () => {
    await vi.waitFor(() => {
      expect(apiMocks.list).toHaveBeenCalledTimes(1);
      expect(apiMocks.listAssets).toHaveBeenCalledTimes(1);
    });
  });

  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
    await Promise.resolve();
  });
  expect(apiMocks.list).toHaveBeenCalledTimes(2);
  expect(apiMocks.listAssets).toHaveBeenCalledTimes(2);
  await act(async () => unmount());
});

test("reenables a disabled node", async () => {
  const user = userEvent.setup();
  apiMocks.list.mockResolvedValueOnce({
    items: [
      {
        node_id: "019d3a7e-7c42-7000-8000-000000000007",
        reported_name: "上海接入节点",
        display_name: null,
        effective_name: "上海接入节点",
        hostname: "athena-node-01",
        software_version: "0.2.0",
        management_status: "disabled",
        notes: null,
        management_tags: [],
        disable_reason: null,
        connectivity_status: "offline",
        approved_at: "2026-07-31T08:00:00Z",
        last_heartbeat_at: null
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  renderPage();
  await screen.findByRole("heading", { name: "上海接入节点" });

  await user.click(screen.getByRole("button", { name: "启用节点" }));

  await waitFor(() =>
    expect(apiMocks.updateStatus).toHaveBeenCalledWith(
      "019d3a7e-7c42-7000-8000-000000000007",
      "active"
    )
  );
});

test("rotates a Token without leaving the secret visible", async () => {
  const user = userEvent.setup();
  const replacement = "replacement-node-token-value-123456789";
  renderPage();
  await screen.findByRole("heading", { name: "上海生产节点" });

  await user.click(screen.getByRole("button", { name: "更换 Token" }));
  const dialog = await screen.findByRole("dialog", { name: "更换 Node Token" });
  await user.type(within(dialog).getByLabelText("新 Token"), replacement);
  await user.click(within(dialog).getByRole("button", { name: "确认更换" }));

  await waitFor(() =>
    expect(apiMocks.rotateToken).toHaveBeenCalledWith(
      "019d3a7e-7c42-7000-8000-000000000007",
      replacement
    )
  );
  await waitFor(() => expect(screen.queryByDisplayValue(replacement)).not.toBeInTheDocument());
});

test("sends search, filtering and sorting to the server", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByRole("heading", { name: "上海生产节点" });

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

test("sends asset search, tag and status filters to the server", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("web-01");

  await user.type(screen.getByPlaceholderText("搜索资产名称或地址"), "10.0{Enter}");
  await waitFor(() =>
    expect(apiMocks.listAssets).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ search: "10.0" })
    )
  );

  await user.type(screen.getByPlaceholderText("按标签筛选"), "production{Enter}");
  await waitFor(() =>
    expect(apiMocks.listAssets).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ tag: "production" })
    )
  );

  await user.click(screen.getByRole("combobox", { name: "资产状态" }));
  await user.click(await screen.findByText("已退役"));
  await waitFor(() =>
    expect(apiMocks.listAssets).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ lifecycle_status: "retired" })
    )
  );

  await user.click(screen.getByRole("combobox", { name: "检测状态" }));
  await user.click(await screen.findByText("连接正常"));
  await waitFor(() =>
    expect(apiMocks.listAssets).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ detection_status: "success" })
    )
  );

});

test("filters assets that have not been tested", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("web-01");

  await user.click(screen.getByRole("combobox", { name: "检测状态" }));
  await user.click(await screen.findByText("尚未检测"));

  await waitFor(() =>
    expect(apiMocks.listAssets).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ detection_status: "untested" })
    )
  );
});

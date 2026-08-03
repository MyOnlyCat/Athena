import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { act, render } from "@testing-library/react";
import { afterEach, test, vi } from "vitest";

import { NodesPage } from "../src/features/nodes/NodesPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  listAssets: vi.fn(),
  updateInfo: vi.fn(),
  updateStatus: vi.fn(),
  rotateToken: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  apiMessage: vi.fn(),
  nodesApi: apiMocks
}));

afterEach(() => {
  vi.useRealTimers();
});

test("refreshes the node list and selected asset page every 30 seconds", async () => {
  vi.useFakeTimers();
  apiMocks.list.mockResolvedValue({
    items: [
      {
        node_id: "019d3a7e-7c42-7000-8000-000000000007",
        reported_name: "上海接入节点",
        display_name: null,
        effective_name: "上海接入节点",
        hostname: "athena-node-01",
        software_version: "0.2.0",
        management_status: "active",
        notes: null,
        management_tags: [],
        disable_reason: null,
        connectivity_status: "online",
        approved_at: "2026-07-31T08:00:00Z",
        last_heartbeat_at: "2026-07-31T09:00:00Z"
      }
    ],
    page: 1,
    page_size: 20,
    total: 1
  });
  apiMocks.listAssets.mockResolvedValue({
    items: [],
    page: 1,
    page_size: 20,
    total: 0
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  const { unmount } = render(
    <App>
      <QueryClientProvider client={queryClient}>
        <NodesPage />
      </QueryClientProvider>
    </App>
  );

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

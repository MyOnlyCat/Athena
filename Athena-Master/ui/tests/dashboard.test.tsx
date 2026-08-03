import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DashboardPage } from "../src/features/dashboard/DashboardPage";

const apiMocks = vi.hoisted(() => ({
  get: vi.fn()
}));

vi.mock("../src/shared/api/client", () => ({
  overviewApi: apiMocks
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.get.mockResolvedValue({
    nodes: {
      total: 5,
      pending: 1,
      active: 2,
      disabled: 1,
      rejected: 1,
      online: 1,
      stale: 1,
      offline: 1
    },
    assets: {
      active: 3,
      abnormal: 1,
      unknown: 1
    }
  });
});

afterEach(() => {
  vi.useRealTimers();
});

test("shows Chinese node, connectivity and asset health summaries", async () => {
  renderPage();

  expect(await screen.findByText("接入节点总数")).toBeInTheDocument();
  expect(screen.getByText("待审批")).toBeInTheDocument();
  expect(screen.getByText("已启用")).toBeInTheDocument();
  expect(screen.getByText("已禁用")).toBeInTheDocument();
  expect(screen.getByText("已拒绝")).toBeInTheDocument();
  expect(screen.getByText("心跳延迟")).toBeInTheDocument();
  expect(screen.getByText("明确异常资产")).toBeInTheDocument();
  expect(screen.getByText("状态未知资产")).toBeInTheDocument();
  expect(screen.getByText("5")).toBeInTheDocument();
});

test("refreshes the overview every 30 seconds", async () => {
  vi.useFakeTimers();
  renderPage();

  await act(async () => {
    await Promise.resolve();
  });
  expect(apiMocks.get).toHaveBeenCalledTimes(1);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(apiMocks.get).toHaveBeenCalledTimes(2);
});

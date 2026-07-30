import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { test, vi } from "vitest";

import { DashboardPage } from "../src/features/dashboard/DashboardPage";
import { hostsApi, tasksApi } from "../src/shared/api/client";

test("shows recent tasks and an empty-state message when no tasks are available", async () => {
  vi.spyOn(hostsApi, "list").mockResolvedValue([]);
  vi.spyOn(tasksApi, "list").mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage />
    </QueryClientProvider>
  );

  expect(screen.getByRole("heading", { name: "最近任务" })).toBeInTheDocument();
  expect(await screen.findByText("暂无任务")).toBeInTheDocument();
});

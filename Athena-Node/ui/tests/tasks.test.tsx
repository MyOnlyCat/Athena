import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { test, vi } from "vitest";

import { TasksPage } from "../src/features/tasks/TasksPage";
import { TaskStatus } from "../src/features/tasks/TaskStatus";
import { tasksApi } from "../src/shared/api/client";

test("renders stable Chinese deployment status labels", () => {
  const { rerender } = render(<TaskStatus status="running" />);
  expect(screen.getByText("执行中")).toBeInTheDocument();

  rerender(<TaskStatus status="manual_review" />);
  expect(screen.getByText("需人工确认")).toBeInTheDocument();
});

test("labels the task page as current tasks", () => {
  vi.spyOn(tasksApi, "list").mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <QueryClientProvider client={queryClient}>
      <TasksPage />
    </QueryClientProvider>
  );

  expect(screen.getByRole("heading", { name: "当前任务" })).toBeInTheDocument();
  expect(
    screen.getByText(
      `浏览器时区：${
        Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区"
      }`
    )
  ).toBeInTheDocument();
});

import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { test, vi } from "vitest";

import { AppShell } from "../src/app/AppShell";
import { ThemeProvider } from "../src/styles/ThemeProvider";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "alice" },
    logout: vi.fn()
  })
}));

test("renders aligned user identity, theme control, and current-task navigation", async () => {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </ThemeProvider>
  );

  await act(async () => {});

  expect(screen.getByText("alice")).toBeInTheDocument();
  expect(screen.getByText("管理员")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /切换到.+模式/ })).toBeInTheDocument();
  expect(screen.getByText("当前任务")).toBeInTheDocument();
  expect(document.querySelector(".ant-menu-item-divider")).not.toBeInTheDocument();
});

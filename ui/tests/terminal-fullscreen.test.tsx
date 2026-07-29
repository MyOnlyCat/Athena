import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { test, vi } from "vitest";

import { AppRouter } from "../src/app/AppRouter";
import { ThemeProvider } from "../src/styles/ThemeProvider";
import "../src/styles/global.css";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    loading: false,
    user: { id: "user-1", username: "alice" },
    login: vi.fn(),
    logout: vi.fn()
  })
}));

vi.mock("../src/shared/api/client", () => ({
  hostsApi: { list: vi.fn().mockResolvedValue([]) },
  tasksApi: { list: vi.fn().mockResolvedValue([]) }
}));

vi.mock("../src/features/terminal/useTerminalSession", () => ({
  useTerminalSession: () => ({ containerRef: vi.fn(), state: "idle" })
}));

test("opens Web SSH in application fullscreen and lets the operator restore navigation", async () => {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <ThemeProvider>
      <App>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/terminal"]}>
            <AppRouter />
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    </ThemeProvider>
  );

  expect(document.querySelector(".app-sider")).not.toBeVisible();
  expect(document.querySelector(".app-header")).not.toBeVisible();

  await user.click(screen.getByRole("button", { name: "\u9000\u51fa\u5168\u5c4f" }));

  expect(document.querySelector(".app-sider")).toBeVisible();
  expect(document.querySelector(".app-header")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "\u8fdb\u5165\u5168\u5c4f" }));

  expect(document.querySelector(".app-sider")).not.toBeVisible();
  expect(document.querySelector(".app-header")).not.toBeVisible();

  await user.click(screen.getByRole("button", { name: "\u9000\u51fa\u5168\u5c4f" }));
  await user.click(screen.getByText("\u8282\u70b9\u6982\u89c8"));
  await user.click(screen.getByText("\u7f51\u9875 SSH"));

  expect(document.querySelector(".app-sider")).not.toBeVisible();
  expect(document.querySelector(".app-header")).not.toBeVisible();
  expect(screen.getByRole("button", { name: "\u9000\u51fa\u5168\u5c4f" })).toBeInTheDocument();
});

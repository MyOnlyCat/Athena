import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { AppShell } from "../src/app/AppShell";
import { ThemeProvider } from "../src/styles/ThemeProvider";
import { THEME_STORAGE_KEY } from "../src/styles/theme";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "alice", is_active: true },
    logout: vi.fn()
  })
}));

test("renders the Master shell with Node-aligned identity and theme controls", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  const user = userEvent.setup();
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </ThemeProvider>
  );

  expect(screen.getByText("MASTER CONSOLE")).toBeInTheDocument();
  expect(screen.getByText("alice")).toBeInTheDocument();
  expect(screen.getAllByText("管理员")).toHaveLength(2);
  expect(screen.getByText("系统概览")).toBeInTheDocument();
  expect(screen.getByText("注册申请")).toBeInTheDocument();
  expect(screen.getByText("接入节点")).toBeInTheDocument();
  expect(screen.getByText("审计日志")).toBeInTheDocument();

  const themeButton = screen.getByRole("button", { name: "切换到夜间模式" });
  await user.click(themeButton);
  expect(screen.getByRole("button", { name: "切换到日间模式" })).toBeInTheDocument();
});

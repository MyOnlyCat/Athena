import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { test, vi } from "vitest";

import { AppShell } from "../src/app/AppShell";
import { ThemeProvider } from "../src/styles/ThemeProvider";
import { THEME_STORAGE_KEY } from "../src/styles/theme";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "alice" },
    logout: vi.fn()
  })
}));

test("renders aligned user identity, theme control, and current-task navigation", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  const user = userEvent.setup();
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </ThemeProvider>
  );

  expect(screen.getByText("alice")).toBeInTheDocument();
  expect(screen.getByText("管理员")).toBeInTheDocument();
  const themeButton = screen.getByRole("button", { name: "切换到夜间模式" });
  expect(themeButton).toBeInTheDocument();
  expect(screen.getByText("当前任务")).toBeInTheDocument();
  expect(document.querySelector(".ant-menu-item-divider")).not.toBeInTheDocument();

  await user.click(themeButton);

  expect(screen.getByRole("button", { name: "切换到日间模式" })).toBeInTheDocument();
});

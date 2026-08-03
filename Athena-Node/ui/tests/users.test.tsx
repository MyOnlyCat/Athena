import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { AuthProvider } from "../src/features/auth/AuthContext";
import { UserTable } from "../src/features/users/UserTable";
import { UsersPage } from "../src/features/users/UsersPage";
import { usersApi } from "../src/shared/api/client";

test("shows the browser time zone used for user timestamps", () => {
  vi.spyOn(usersApi, "list").mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <App>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <UsersPage />
        </AuthProvider>
      </QueryClientProvider>
    </App>
  );

  expect(
    screen.getByText(
      `浏览器时区：${
        Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区"
      }`
    )
  ).toBeInTheDocument();
});

test("protects current administrator from disable action", () => {
  render(
    <UserTable
      currentUserId="user-1"
      users={[
        {
          id: "user-1",
          username: "admin",
          is_active: true,
          last_login_at: "2026-07-29T12:00:00Z",
          created_at: "2026-07-29T00:00:00Z"
        }
      ]}
      loading={false}
      onStatusChange={() => undefined}
      onResetPassword={() => undefined}
    />
  );

  expect(screen.getByText("当前用户")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /禁\s*用/ })).toBeDisabled();
});

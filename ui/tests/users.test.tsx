import { render, screen } from "@testing-library/react";

import { UserTable } from "../src/features/users/UserTable";

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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { LoginPage } from "../src/features/auth/LoginPage";

test("submits administrator credentials and shows API failure", async () => {
  const user = userEvent.setup();
  const login = vi.fn().mockRejectedValue(new Error("用户名或密码错误"));
  render(<LoginPage onLogin={login} />);

  await user.type(screen.getByLabelText("用户名"), "admin");
  await user.type(screen.getByLabelText("密码"), "wrong");
  await user.click(screen.getByRole("button", { name: /登\s*录/ }));

  expect(login).toHaveBeenCalledWith("admin", "wrong");
  expect(await screen.findByText("用户名或密码错误")).toBeInTheDocument();
});

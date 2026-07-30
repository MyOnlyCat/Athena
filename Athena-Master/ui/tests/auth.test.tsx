import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { LoginPage } from "../src/features/auth/LoginPage";

test("submits Master administrator credentials and shows Chinese API failure", async () => {
  const user = userEvent.setup();
  const login = vi.fn().mockRejectedValue(new Error("用户名或密码错误"));
  render(<LoginPage onLogin={login} />);

  expect(screen.getByText("ATHENA MASTER")).toBeInTheDocument();
  expect(screen.getByText("使用主节点管理员账号继续")).toBeInTheDocument();

  await user.type(screen.getByLabelText("用户名"), "admin");
  await user.type(screen.getByLabelText("密码"), "wrong");
  await user.click(screen.getByRole("button", { name: /登\s*录/ }));

  expect(login).toHaveBeenCalledWith("admin", "wrong");
  expect(await screen.findByText("用户名或密码错误")).toBeInTheDocument();
});

test("shows Chinese required-field messages", async () => {
  const user = userEvent.setup();
  render(<LoginPage onLogin={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: /登\s*录/ }));

  expect(await screen.findByText("请输入用户名")).toBeInTheDocument();
  expect(await screen.findByText("请输入密码")).toBeInTheDocument();
});

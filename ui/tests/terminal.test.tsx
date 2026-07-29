import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ServerSwitcher } from "../src/features/terminal/ServerSwitcher";

test("filters servers and requests a switch", async () => {
  const user = userEvent.setup();
  const switchTo = vi.fn();
  render(
    <ServerSwitcher
      activeHostId="host-1"
      onSelect={switchTo}
      hosts={[
        { id: "host-1", name: "web-01", address: "10.0.0.10", last_test_status: "success" },
        { id: "host-2", name: "db-01", address: "10.0.0.20", last_test_status: "failed" }
      ]}
    />
  );

  await user.type(screen.getByPlaceholderText("搜索服务器"), "db");
  expect(screen.queryByText("web-01")).not.toBeInTheDocument();
  await user.click(screen.getByText("db-01"));
  expect(switchTo).toHaveBeenCalledWith("host-2");
});

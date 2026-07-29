import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { TerminalPage } from "../src/features/terminal/TerminalPage";
import { ServerSwitcher } from "../src/features/terminal/ServerSwitcher";
import { hostsApi } from "../src/shared/api/client";

vi.mock("../src/shared/api/client", () => ({
  hostsApi: { list: vi.fn() }
}));

vi.mock("../src/features/terminal/FileManager", () => ({
  FileManager: () => null
}));

vi.mock("../src/features/terminal/TerminalPane", async () => {
  const { theme } = await import("antd");
  return {
    TerminalPane: () => {
      const { token } = theme.useToken();
      return <output data-testid="terminal-theme-token">{token.colorBgBase}</output>;
    }
  };
});

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

test("keeps Ant Design controls dark in the terminal page scope", () => {
  vi.mocked(hostsApi.list).mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <QueryClientProvider client={queryClient}>
      <App>
        <TerminalPage />
      </App>
    </QueryClientProvider>
  );

  expect(screen.getByTestId("terminal-theme-token")).toHaveTextContent("#0B1020");
});

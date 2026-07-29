import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { TerminalPage } from "../src/features/terminal/TerminalPage";
import { ServerSwitcher } from "../src/features/terminal/ServerSwitcher";
import { hostsApi } from "../src/shared/api/client";
import "../src/styles/global.css";

function parseRgb(value: string) {
  return value.match(/\d+/g)!.slice(0, 3).map(Number);
}

function luminance([red, green, blue]: number[]) {
  const channels = [red, green, blue].map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string, background: string) {
  const foregroundLuminance = luminance(parseRgb(foreground));
  const backgroundLuminance = luminance(parseRgb(background));
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

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

test("keeps native terminal text readable when the outer page is light", () => {
  document.documentElement.dataset.theme = "light";
  vi.mocked(hostsApi.list).mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  const { container } = render(
    <QueryClientProvider client={queryClient}>
      <App>
        <TerminalPage />
      </App>
    </QueryClientProvider>
  );

  const terminalPage = container.querySelector(".terminal-page");
  expect(terminalPage).not.toBeNull();
  const style = getComputedStyle(terminalPage!);
  expect(contrast(style.color, style.backgroundColor)).toBeGreaterThanOrEqual(4.5);
});

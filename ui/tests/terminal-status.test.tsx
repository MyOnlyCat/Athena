import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { TerminalPane } from "../src/features/terminal/TerminalPane";

const terminalSession = vi.hoisted(() => ({ state: "connecting" }));

vi.mock("../src/features/terminal/useTerminalSession", () => ({
  useTerminalSession: () => ({
    containerRef: { current: null },
    state: terminalSession.state
  })
}));

test.each([
  ["connecting", "正在连接"],
  ["connected", "SSH 已连接"],
  ["closed", "远程会话已正常关闭"],
  ["auth_failed", "SSH 认证失败"],
  ["host_key_changed", "SSH 主机密钥已变更"],
  ["network_error", "网络连接失败"],
  ["channel_error", "SSH 通道错误"],
  ["open_error", "SSH 会话打开失败"]
])("renders the %s terminal state with a Chinese operator label", (state, label) => {
  terminalSession.state = state;

  render(
    <TerminalPane
      hostId="host-1"
      hostName="node-1"
      fullscreen={false}
      onToggleFullscreen={vi.fn()}
    />
  );

  expect(screen.getByText(label)).toBeInTheDocument();
});

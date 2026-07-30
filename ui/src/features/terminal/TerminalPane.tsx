import { FullscreenExitOutlined, FullscreenOutlined } from "@ant-design/icons";
import { Button } from "antd";

import {
  type TerminalSessionState,
  useTerminalSession
} from "./useTerminalSession";

const terminalStateLabels: Record<TerminalSessionState, string> = {
  idle: "未连接",
  connecting: "正在连接",
  connected: "SSH 已连接",
  closed: "远程会话已正常关闭",
  auth_failed: "SSH 认证失败",
  host_key_changed: "SSH 主机密钥已变更",
  network_error: "网络连接失败",
  channel_error: "SSH 通道错误",
  open_error: "SSH 会话打开失败"
};

export function TerminalPane({
  hostId,
  hostName,
  fullscreen,
  onToggleFullscreen
}: {
  hostId: string | null;
  hostName?: string;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  const { containerRef, state } = useTerminalSession(hostId);
  return (
    <section className="terminal-center">
      <div className="terminal-toolbar">
        <div className="terminal-title">
          <span className={`terminal-status ${state}`} />
          <strong>{hostName ?? "请选择服务器"}</strong>
          <small>{terminalStateLabels[state]}</small>
        </div>
        <div className="terminal-toolbar-actions">
          <span className="mono terminal-session-label">xterm-256color</span>
          <Button
            type="text"
            icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            aria-label={fullscreen ? "退出全屏" : "进入全屏"}
            onClick={onToggleFullscreen}
          />
        </div>
      </div>
      {hostId ? (
        <div className="xterm-container" ref={containerRef} />
      ) : (
        <div className="terminal-empty large">从左侧选择服务器开始 SSH 会话</div>
      )}
    </section>
  );
}

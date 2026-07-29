import { useTerminalSession } from "./useTerminalSession";

export function TerminalPane({
  hostId,
  hostName
}: {
  hostId: string | null;
  hostName?: string;
}) {
  const { containerRef, state } = useTerminalSession(hostId);
  return (
    <section className="terminal-center">
      <div className="terminal-toolbar">
        <div className="terminal-title">
          <span className={`terminal-status ${state}`} />
          <strong>{hostName ?? "请选择服务器"}</strong>
          <small>{state === "connected" ? "SSH 已连接" : state}</small>
        </div>
        <span className="mono terminal-session-label">xterm-256color</span>
      </div>
      {hostId ? (
        <div className="xterm-container" ref={containerRef} />
      ) : (
        <div className="terminal-empty large">从左侧选择服务器开始 SSH 会话</div>
      )}
    </section>
  );
}

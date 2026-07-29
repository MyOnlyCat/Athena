import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef, useState } from "react";

import { terminalApi } from "../../shared/api/client";

function bytesToBase64(bytes: Uint8Array) {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary);
}

export function useTerminalSession(hostId: string | null) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"idle" | "connecting" | "connected" | "closed">(
    "idle"
  );

  useEffect(() => {
    if (!hostId || !containerRef.current) return;
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Cascadia Code", monospace',
      theme: {
        background: "#070B12",
        foreground: "#D8E2F2",
        cursor: "#5B8CFF",
        selectionBackground: "#274475"
      }
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(containerRef.current);
    fit.fit();
    setState("connecting");
    let socket: WebSocket | null = null;
    let disposed = false;
    const encoder = new TextEncoder();

    terminalApi
      .ticket(hostId)
      .then(({ ticket }) => {
        if (disposed) return;
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(
          `${protocol}//${location.host}/api/v1/terminal/ws/${hostId}`
        );
        socket.onopen = () =>
          socket?.send(
            JSON.stringify({
              ticket,
              cols: terminal.cols,
              rows: terminal.rows
            })
          );
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data);
          if (message.type === "connected") setState("connected");
          if (message.type === "output") terminal.write(Uint8Array.from(atob(message.data), (c) => c.charCodeAt(0)));
          if (message.type === "error") terminal.writeln(`\r\n[连接错误] ${message.code}`);
        };
        socket.onclose = () => setState("closed");
      })
      .catch((error) => {
        terminal.writeln(`\r\n[连接失败] ${error instanceof Error ? error.message : "未知错误"}`);
        setState("closed");
      });

    const input = terminal.onData((data) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({ type: "input", data: bytesToBase64(encoder.encode(data)) })
        );
      }
    });
    const resize = new ResizeObserver(() => {
      fit.fit();
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows })
        );
      }
    });
    resize.observe(containerRef.current);
    return () => {
      disposed = true;
      resize.disconnect();
      input.dispose();
      socket?.close();
      terminal.dispose();
    };
  }, [hostId]);

  return { containerRef, state };
}

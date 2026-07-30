import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef, useState } from "react";

import { terminalApi } from "../../shared/api/client";

export type TerminalSessionState =
  | "idle"
  | "connecting"
  | "connected"
  | "closed"
  | "auth_failed"
  | "host_key_changed"
  | "network_error"
  | "channel_error"
  | "open_error";

function bytesToBase64(bytes: Uint8Array) {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary);
}

function errorState(code: string): TerminalSessionState {
  switch (code) {
    case "TERMINAL_AUTH_FAILED":
      return "auth_failed";
    case "TERMINAL_HOST_KEY_CHANGED":
      return "host_key_changed";
    case "TERMINAL_NETWORK_ERROR":
      return "network_error";
    case "TERMINAL_CHANNEL_ERROR":
    case "TERMINAL_BRIDGE_ERROR":
      return "channel_error";
    default:
      return "open_error";
  }
}

export function useTerminalSession(hostId: string | null) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<TerminalSessionState>("idle");

  useEffect(() => {
    if (!hostId || !containerRef.current) {
      setState("idle");
      return;
    }
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
    let socket: WebSocket | null = null;
    let disposed = false;
    let currentState: TerminalSessionState = "connecting";
    const encoder = new TextEncoder();

    function updateState(nextState: TerminalSessionState) {
      currentState = nextState;
      if (!disposed) setState(nextState);
    }

    updateState("connecting");
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
          try {
            const message = JSON.parse(event.data);
            if (message.type === "connected") updateState("connected");
            if (message.type === "output") {
              terminal.write(
                Uint8Array.from(atob(message.data), (character) =>
                  character.charCodeAt(0)
                )
              );
            }
            if (message.type === "error") {
              updateState(errorState(String(message.code)));
              terminal.writeln(`\r\n[连接错误] ${message.code}`);
            }
          } catch {
            updateState("channel_error");
            terminal.writeln("\r\n[连接错误] 终端消息格式无效");
          }
        };
        socket.onerror = () => {
          if (currentState === "connecting" || currentState === "connected") {
            updateState("network_error");
          }
        };
        socket.onclose = () => {
          if (currentState === "connected") {
            updateState("closed");
          } else if (currentState === "connecting") {
            updateState("network_error");
          }
        };
      })
      .catch((error) => {
        terminal.writeln(`\r\n[连接失败] ${error instanceof Error ? error.message : "未知错误"}`);
        updateState("open_error");
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

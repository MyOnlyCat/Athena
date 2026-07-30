import { useQuery } from "@tanstack/react-query";
import { App, ConfigProvider } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { hostsApi } from "../../shared/api/client";
import { createTheme } from "../../styles/theme";
import { FileManager } from "./FileManager";
import { ServerSwitcher } from "./ServerSwitcher";
import { TerminalPane } from "./TerminalPane";

type TerminalLayoutContext = {
  terminalFullscreen: boolean;
  toggleTerminalFullscreen: () => void;
};

const noop = () => undefined;

export function TerminalPage() {
  return (
    <ConfigProvider theme={createTheme("dark")}>
      <App component={false}>
        <TerminalContent />
      </App>
    </ConfigProvider>
  );
}

function TerminalContent() {
  const { modal } = App.useApp();
  const terminalLayout = useOutletContext<TerminalLayoutContext | null>();
  const query = useQuery({ queryKey: ["hosts"], queryFn: hostsApi.list });
  const trusted = useMemo(
    () => (query.data ?? []).filter((host) => host.host_key_fingerprint),
    [query.data]
  );
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (!activeId && trusted.length) setActiveId(trusted[0].id);
  }, [activeId, trusted]);

  function select(hostId: string) {
    if (!activeId || activeId === hostId) {
      setActiveId(hostId);
      return;
    }
    modal.confirm({
      title: "切换服务器？",
      content: "当前 SSH 会话将被关闭。",
      okText: "切换",
      onOk: () => setActiveId(hostId)
    });
  }

  const active = trusted.find((host) => host.id === activeId);
  return (
    <div className="terminal-page">
      <ServerSwitcher hosts={trusted} activeHostId={activeId} onSelect={select} />
      <TerminalPane
        hostId={activeId}
        hostName={active?.name}
        fullscreen={terminalLayout?.terminalFullscreen ?? false}
        onToggleFullscreen={terminalLayout?.toggleTerminalFullscreen ?? noop}
      />
      {activeId ? (
        <FileManager key={activeId} hostId={activeId} />
      ) : (
        <aside className="file-manager" />
      )}
    </div>
  );
}

import { SearchOutlined } from "@ant-design/icons";
import { Input, Tag } from "antd";
import { useMemo, useState } from "react";

interface ServerItem {
  id: string;
  name: string;
  address: string;
  last_test_status: string | null;
}

interface Props {
  hosts: ServerItem[];
  activeHostId: string | null;
  onSelect: (hostId: string) => void;
}

export function ServerSwitcher({ hosts, activeHostId, onSelect }: Props) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(
    () =>
      hosts.filter((host) =>
        `${host.name} ${host.address}`.toLowerCase().includes(search.toLowerCase())
      ),
    [hosts, search]
  );
  return (
    <aside className="server-switcher">
      <div className="terminal-pane-heading">
        <div>
          <strong>服务器</strong>
          <span>{hosts.length} 台可用</span>
        </div>
      </div>
      <div className="server-search">
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索服务器"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="server-list">
        {filtered.map((host) => (
          <button
            type="button"
            key={host.id}
            className={host.id === activeHostId ? "server-item active" : "server-item"}
            onClick={() => onSelect(host.id)}
          >
            <span
              className={`server-health ${host.last_test_status === "success" ? "ok" : ""}`}
            />
            <span>
              <strong>{host.name}</strong>
              <small className="mono">{host.address}</small>
            </span>
            {host.id === activeHostId && <Tag color="blue">当前</Tag>}
          </button>
        ))}
        {!filtered.length && <div className="terminal-empty">没有匹配的服务器</div>}
      </div>
    </aside>
  );
}

import { DeleteOutlined, EditOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Button, Space, Table, Tag, Tooltip } from "antd";

import type { Host } from "../../shared/api/types";

interface Props {
  hosts: Host[];
  loading: boolean;
  onEdit: (host: Host) => void;
  onDelete: (host: Host) => void;
  onTest: (host: Host) => void;
}

const statusMap: Record<string, { color: string; label: string }> = {
  success: { color: "success", label: "连接正常" },
  failed: { color: "error", label: "连接异常" },
  pending_trust: { color: "warning", label: "待确认指纹" }
};

export function HostTable({ hosts, loading, onEdit, onDelete, onTest }: Props) {
  return (
    <Table
      rowKey="id"
      dataSource={hosts}
      loading={loading}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      columns={[
        {
          title: "主机",
          render: (_, host) => (
            <div>
              <div className="primary-cell">
                {host.name} {host.is_local && <Tag color="blue">当前节点</Tag>}
              </div>
              <div className="secondary-cell">{host.username}</div>
            </div>
          )
        },
        {
          title: "地址",
          render: (_, host) => (
            <span className="mono">
              {host.address}:{host.port}
            </span>
          )
        },
        {
          title: "标签",
          render: (_, host) =>
            host.tags.length ? host.tags.map((tag) => <Tag key={tag}>{tag}</Tag>) : "—"
        },
        {
          title: "SSH 状态",
          render: (_, host) => {
            const state = statusMap[host.last_test_status ?? ""] ?? {
              color: "default",
              label: "未测试"
            };
            return <Tag color={state.color}>{state.label}</Tag>;
          }
        },
        {
          title: "操作",
          align: "right",
          render: (_, host) => (
            <Space>
              <Tooltip title="测试连接">
                <Button icon={<ThunderboltOutlined />} onClick={() => onTest(host)} />
              </Tooltip>
              <Button icon={<EditOutlined />} onClick={() => onEdit(host)}>
                编辑
              </Button>
              <Button danger icon={<DeleteOutlined />} onClick={() => onDelete(host)} />
            </Space>
          )
        }
      ]}
    />
  );
}

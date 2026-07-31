import { useQuery } from "@tanstack/react-query";
import { Input, Select, Space, Table, Tag } from "antd";
import { useState } from "react";

import { nodesApi } from "../../shared/api/client";
import type {
  AccessNode,
  ConnectivityStatus,
  ListedAccessNode,
  NodeListParams
} from "../../shared/api/types";

const MANAGEMENT_LABELS: Record<AccessNode["management_status"], string> = {
  pending: "待审批",
  active: "已启用",
  disabled: "已禁用",
  rejected: "已拒绝"
};

const CONNECTIVITY_LABELS: Record<ConnectivityStatus, string> = {
  online: "在线",
  stale: "心跳延迟",
  offline: "离线"
};

function formatLocalTime(value: string | null): string {
  if (!value) return "尚未收到心跳";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short"
  }).format(new Date(value));
}

export function NodesPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [managementStatus, setManagementStatus] =
    useState<AccessNode["management_status"]>();
  const [connectivityStatus, setConnectivityStatus] =
    useState<ConnectivityStatus>();
  const [sortBy, setSortBy] =
    useState<NodeListParams["sort_by"]>("last_heartbeat_at");
  const [sortOrder, setSortOrder] =
    useState<NodeListParams["sort_order"]>("desc");

  const params: NodeListParams = {
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_order: sortOrder,
    ...(search ? { search } : {}),
    ...(managementStatus ? { management_status: managementStatus } : {}),
    ...(connectivityStatus ? { connectivity_status: connectivityStatus } : {})
  };
  const query = useQuery({
    queryKey: ["nodes", params],
    queryFn: () => nodesApi.list(params)
  });
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区";

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">ACCESS NODES</p>
          <h1>接入节点</h1>
          <p>查看 Node 上报身份、管理状态和按 Master 接收时间推导的连接状态。</p>
          <p className="muted">浏览器时区：{browserTimeZone}</p>
        </div>
      </header>
      <section className="content-card">
        <Space wrap className="table-toolbar">
          <Input.Search
            placeholder="搜索名称、主机名、版本或节点 ID"
            value={searchInput}
            allowClear
            onChange={(event) => setSearchInput(event.target.value)}
            onSearch={(value) => {
              setSearch(value.trim());
              setPage(1);
            }}
            style={{ width: 320 }}
          />
          <Select
            aria-label="管理状态"
            placeholder="管理状态"
            allowClear
            value={managementStatus}
            onChange={(value) => {
              setManagementStatus(value);
              setPage(1);
            }}
            options={[
              { value: "active", label: "已启用" },
              { value: "disabled", label: "已禁用" },
              { value: "rejected", label: "已拒绝" },
              { value: "pending", label: "待审批" }
            ]}
            style={{ width: 132 }}
          />
          <Select
            aria-label="连接状态"
            placeholder="连接状态"
            allowClear
            value={connectivityStatus}
            onChange={(value) => {
              setConnectivityStatus(value);
              setPage(1);
            }}
            options={[
              { value: "online", label: "在线" },
              { value: "stale", label: "心跳延迟" },
              { value: "offline", label: "离线" }
            ]}
            style={{ width: 132 }}
          />
          <Select
            aria-label="排序字段"
            value={sortBy}
            onChange={(value) => {
              setSortBy(value);
              setPage(1);
            }}
            options={[
              { value: "last_heartbeat_at", label: "最后心跳" },
              { value: "reported_name", label: "上报名" },
              { value: "hostname", label: "主机名" },
              { value: "software_version", label: "软件版本" },
              { value: "approved_at", label: "批准时间" }
            ]}
            style={{ width: 132 }}
          />
          <Select
            aria-label="排序方向"
            value={sortOrder}
            onChange={(value) => {
              setSortOrder(value);
              setPage(1);
            }}
            options={[
              { value: "desc", label: "降序" },
              { value: "asc", label: "升序" }
            ]}
            style={{ width: 100 }}
          />
        </Space>
        <Table<ListedAccessNode>
          rowKey="node_id"
          dataSource={query.data?.items ?? []}
          loading={query.isLoading}
          pagination={{
            current: query.data?.page ?? page,
            pageSize: query.data?.page_size ?? pageSize,
            total: query.data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个接入节点`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPageSize === pageSize ? nextPage : 1);
              setPageSize(nextPageSize);
            }
          }}
          columns={[
            {
              title: "接入节点",
              render: (_, node) => (
                <Space direction="vertical" size={0}>
                  <span className="primary-cell">{node.reported_name}</span>
                  <span className="muted">{node.node_id}</span>
                </Space>
              )
            },
            {
              title: "上报环境",
              render: (_, node) => (
                <Space direction="vertical" size={0}>
                  <span>{node.hostname}</span>
                  <span className="muted">版本 {node.software_version}</span>
                </Space>
              )
            },
            {
              title: "管理状态",
              render: (_, node) => (
                <Tag color={node.management_status === "active" ? "success" : "default"}>
                  {MANAGEMENT_LABELS[node.management_status]}
                </Tag>
              )
            },
            {
              title: "连接状态",
              render: (_, node) => (
                <Tag
                  color={
                    node.connectivity_status === "online"
                      ? "success"
                      : node.connectivity_status === "stale"
                        ? "warning"
                        : "error"
                  }
                >
                  {CONNECTIVITY_LABELS[node.connectivity_status]}
                </Tag>
              )
            },
            {
              title: "最后心跳",
              render: (_, node) => formatLocalTime(node.last_heartbeat_at)
            }
          ]}
        />
      </section>
    </div>
  );
}

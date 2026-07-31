import { useQuery } from "@tanstack/react-query";
import { Input, Select, Space, Table, Tag } from "antd";
import { useEffect, useState } from "react";

import { nodesApi } from "../../shared/api/client";
import type {
  AccessNode,
  AssetLifecycleStatus,
  ConnectivityStatus,
  HostAsset,
  HostDetectionFilter,
  HostAssetListParams,
  HostTestStatus,
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

const HOST_STATUS_LABELS: Record<HostTestStatus, string> = {
  success: "连接正常",
  failed: "连接失败",
  pending_trust: "待确认指纹"
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

function pageAfterPaginationChange(
  nextPage: number,
  nextPageSize: number,
  currentPageSize: number
): number {
  return nextPageSize === currentPageSize ? nextPage : 1;
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
  const [selectedNodeId, setSelectedNodeId] = useState<string>();
  const [assetPage, setAssetPage] = useState(1);
  const [assetPageSize, setAssetPageSize] = useState(20);
  const [assetSearchInput, setAssetSearchInput] = useState("");
  const [assetSearch, setAssetSearch] = useState("");
  const [assetLifecycle, setAssetLifecycle] = useState<AssetLifecycleStatus>();
  const [assetDetection, setAssetDetection] = useState<HostDetectionFilter>();
  const [assetTagInput, setAssetTagInput] = useState("");
  const [assetTag, setAssetTag] = useState("");

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
  useEffect(() => {
    const nodes = query.data?.items ?? [];
    if (nodes.length > 0 && !nodes.some((node) => node.node_id === selectedNodeId)) {
      setSelectedNodeId(nodes[0].node_id);
      setAssetPage(1);
    }
  }, [query.data?.items, selectedNodeId]);
  const assetParams: HostAssetListParams = {
    page: assetPage,
    page_size: assetPageSize,
    ...(assetSearch ? { search: assetSearch } : {}),
    ...(assetLifecycle ? { lifecycle_status: assetLifecycle } : {}),
    ...(assetDetection ? { detection_status: assetDetection } : {}),
    ...(assetTag ? { tag: assetTag } : {})
  };
  const assetsQuery = useQuery({
    queryKey: ["node-assets", selectedNodeId, assetParams],
    queryFn: () => nodesApi.listAssets(selectedNodeId!, assetParams),
    enabled: Boolean(selectedNodeId)
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
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedNodeId ? [selectedNodeId] : [],
            onChange: (keys) => {
              setSelectedNodeId(String(keys[0]));
              setAssetPage(1);
            }
          }}
          pagination={{
            current: query.data?.page ?? page,
            pageSize: query.data?.page_size ?? pageSize,
            total: query.data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个接入节点`,
            onChange: (nextPage, nextPageSize) => {
              setPage(pageAfterPaginationChange(nextPage, nextPageSize, pageSize));
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
        <div className="asset-section">
          <h2>主机资产</h2>
          <p className="muted">资产由所选接入节点的完整心跳快照维护，此页面只读。</p>
          <Space wrap className="table-toolbar">
            <Input.Search
              placeholder="搜索资产名称或地址"
              value={assetSearchInput}
              allowClear
              onChange={(event) => setAssetSearchInput(event.target.value)}
              onSearch={(value) => {
                setAssetSearch(value.trim());
                setAssetPage(1);
              }}
              style={{ width: 240 }}
            />
            <Input.Search
              placeholder="按标签筛选"
              value={assetTagInput}
              allowClear
              onChange={(event) => setAssetTagInput(event.target.value)}
              onSearch={(value) => {
                setAssetTag(value.trim());
                setAssetPage(1);
              }}
              style={{ width: 180 }}
            />
            <Select
              aria-label="资产状态"
              placeholder="资产状态"
              allowClear
              value={assetLifecycle}
              onChange={(value) => {
                setAssetLifecycle(value);
                setAssetPage(1);
              }}
              options={[
                { value: "active", label: "在管" },
                { value: "retired", label: "已退役" }
              ]}
              style={{ width: 120 }}
            />
            <Select
              aria-label="检测状态"
              placeholder="检测状态"
              allowClear
              value={assetDetection}
              onChange={(value) => {
                setAssetDetection(value);
                setAssetPage(1);
              }}
              options={[
                { value: "success", label: "连接正常" },
                { value: "failed", label: "连接失败" },
                { value: "pending_trust", label: "待确认指纹" },
                { value: "untested", label: "尚未检测" }
              ]}
              style={{ width: 140 }}
            />
          </Space>
          <Table<HostAsset>
            rowKey="host_id"
            dataSource={assetsQuery.data?.items ?? []}
            loading={assetsQuery.isLoading}
            pagination={{
              current: assetsQuery.data?.page ?? assetPage,
              pageSize: assetsQuery.data?.page_size ?? assetPageSize,
              total: assetsQuery.data?.total ?? 0,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 个主机资产`,
              onChange: (nextPage, nextPageSize) => {
                setAssetPage(
                  pageAfterPaginationChange(nextPage, nextPageSize, assetPageSize)
                );
                setAssetPageSize(nextPageSize);
              }
            }}
            columns={[
              {
                title: "主机资产",
                render: (_, asset) => (
                  <Space direction="vertical" size={0}>
                    <span className="primary-cell">{asset.name}</span>
                    <span className="muted mono">{asset.address}:{asset.port}</span>
                  </Space>
                )
              },
              {
                title: "登录信息",
                render: (_, asset) => (
                  <Space direction="vertical" size={0}>
                    <span>{asset.username}</span>
                    {asset.is_local ? <Tag>本机</Tag> : null}
                  </Space>
                )
              },
              {
                title: "标签",
                render: (_, asset) => asset.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)
              },
              {
                title: "检测状态",
                render: (_, asset) => (
                  <Space direction="vertical" size={0}>
                    <Tag color={asset.last_test_status === "success" ? "success" : "warning"}>
                      {asset.last_test_status
                        ? HOST_STATUS_LABELS[asset.last_test_status]
                        : "尚未检测"}
                    </Tag>
                    <span className="muted">{asset.last_test_code ?? "无错误码"}</span>
                    <span className="muted">{formatLocalTime(asset.last_tested_at)}</span>
                  </Space>
                )
              },
              {
                title: "资产状态",
                render: (_, asset) => (
                  <Tag color={asset.lifecycle_status === "active" ? "success" : "default"}>
                    {asset.lifecycle_status === "active" ? "在管" : "已退役"}
                  </Tag>
                )
              }
            ]}
          />
        </div>
      </section>
    </div>
  );
}

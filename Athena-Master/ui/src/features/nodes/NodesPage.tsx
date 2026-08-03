import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Modal, Select, Space, Table, Tag } from "antd";
import { useEffect, useState } from "react";

import { apiMessage, nodesApi } from "../../shared/api/client";
import {
  OVERVIEW_QUERY_KEY,
  STATUS_REFRESH_INTERVAL_MS
} from "../../shared/api/queryPolicy";
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

interface ManagementInfoForm {
  display_name?: string;
  notes?: string;
  management_tags: string[];
}

interface DisableForm {
  reason?: string;
}

interface TokenForm {
  token: string;
}

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
  const queryClient = useQueryClient();
  const [managementForm] = Form.useForm<ManagementInfoForm>();
  const [disableForm] = Form.useForm<DisableForm>();
  const [tokenForm] = Form.useForm<TokenForm>();
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
  const [managementOpen, setManagementOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [operationPending, setOperationPending] = useState(false);
  const [operationError, setOperationError] = useState<string>();

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
    queryFn: () => nodesApi.list(params),
    refetchInterval: STATUS_REFRESH_INTERVAL_MS
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
    enabled: Boolean(selectedNodeId),
    refetchInterval: STATUS_REFRESH_INTERVAL_MS
  });
  const selectedNode = query.data?.items.find((node) => node.node_id === selectedNodeId);
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区";

  async function refreshNodeState() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: OVERVIEW_QUERY_KEY }),
      query.refetch(),
      assetsQuery.refetch()
    ]);
  }

  function openManagement() {
    if (!selectedNode) return;
    managementForm.setFieldsValue({
      display_name: selectedNode.display_name ?? undefined,
      notes: selectedNode.notes ?? undefined,
      management_tags: selectedNode.management_tags
    });
    setOperationError(undefined);
    setManagementOpen(true);
  }

  async function saveManagement() {
    if (!selectedNode) return;
    try {
      const values = await managementForm.validateFields();
      setOperationPending(true);
      setOperationError(undefined);
      await nodesApi.updateInfo(selectedNode.node_id, {
        display_name: values.display_name?.trim() || null,
        notes: values.notes?.trim() || null,
        management_tags: values.management_tags ?? []
      });
      setManagementOpen(false);
      await refreshNodeState();
    } catch (error) {
      setOperationError(apiMessage(error));
    } finally {
      setOperationPending(false);
    }
  }

  async function disableNode() {
    if (!selectedNode) return;
    try {
      const values = await disableForm.validateFields();
      setOperationPending(true);
      setOperationError(undefined);
      await nodesApi.updateStatus(
        selectedNode.node_id,
        "disabled",
        values.reason?.trim()
      );
      setDisableOpen(false);
      disableForm.resetFields();
      await refreshNodeState();
    } catch (error) {
      setOperationError(apiMessage(error));
    } finally {
      setOperationPending(false);
    }
  }

  async function enableNode() {
    if (!selectedNode) return;
    try {
      setOperationPending(true);
      setOperationError(undefined);
      await nodesApi.updateStatus(selectedNode.node_id, "active");
      await refreshNodeState();
    } catch (error) {
      setOperationError(apiMessage(error));
    } finally {
      setOperationPending(false);
    }
  }

  async function rotateToken() {
    if (!selectedNode) return;
    try {
      const { token } = await tokenForm.validateFields();
      setOperationPending(true);
      setOperationError(undefined);
      await nodesApi.rotateToken(selectedNode.node_id, token);
      tokenForm.resetFields();
      setTokenOpen(false);
      await refreshNodeState();
    } catch (error) {
      setOperationError(apiMessage(error));
    } finally {
      setOperationPending(false);
    }
  }

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
                  <span className="primary-cell">{node.effective_name}</span>
                  <span className="muted">Node 上报名：{node.reported_name}</span>
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
        {operationError ? <Alert type="error" message={operationError} showIcon /> : null}
        {selectedNode ? (
          <section className="asset-section" aria-label="节点管理">
            <Space direction="vertical" size={4}>
              <h2>{selectedNode.effective_name}</h2>
              <span>Node 上报名：{selectedNode.reported_name}</span>
              <span className="muted">{selectedNode.notes || "暂无管理备注"}</span>
              <span>
                {selectedNode.management_tags.map((tag) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </span>
            </Space>
            <Space wrap>
              <Button onClick={openManagement}>编辑管理信息</Button>
              {selectedNode.management_status === "disabled" ? (
                <Button loading={operationPending} onClick={() => void enableNode()}>
                  启用节点
                </Button>
              ) : (
                <Button
                  danger
                  onClick={() => {
                    setOperationError(undefined);
                    setDisableOpen(true);
                  }}
                >
                  禁用节点
                </Button>
              )}
              <Button
                onClick={() => {
                  tokenForm.resetFields();
                  setOperationError(undefined);
                  setTokenOpen(true);
                }}
              >
                更换 Token
              </Button>
            </Space>
          </section>
        ) : null}
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
                    <Tag
                      color={
                        asset.source_node_connectivity_status === "offline"
                          ? "default"
                          : asset.source_node_connectivity_status === "stale"
                            ? "warning"
                            : asset.last_test_status === "success"
                              ? "success"
                              : "warning"
                      }
                    >
                      {asset.source_node_connectivity_status === "offline"
                        ? "状态未知（来源节点离线）"
                        : asset.source_node_connectivity_status === "stale"
                          ? "数据延迟（来源节点心跳延迟）"
                          : asset.last_test_status
                            ? HOST_STATUS_LABELS[asset.last_test_status]
                            : "尚未检测"}
                    </Tag>
                    {asset.source_node_connectivity_status !== "online" ? (
                      <span className="muted">
                        最后检测：
                        {asset.last_test_status
                          ? HOST_STATUS_LABELS[asset.last_test_status]
                          : "尚未检测"}
                      </span>
                    ) : null}
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
      <Modal
        title="编辑管理信息"
        open={managementOpen}
        okText="保存"
        confirmLoading={operationPending}
        onOk={() => void saveManagement()}
        onCancel={() => setManagementOpen(false)}
      >
        <Form form={managementForm} layout="vertical">
          <Form.Item name="display_name" label="管理显示名">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea maxLength={1000} />
          </Form.Item>
          <Form.Item name="management_tags" label="管理标签">
            <Select mode="tags" maxCount={20} tokenSeparators={[","]} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="禁用接入节点"
        open={disableOpen}
        okText="确认禁用"
        okButtonProps={{ danger: true }}
        confirmLoading={operationPending}
        onOk={() => void disableNode()}
        onCancel={() => setDisableOpen(false)}
      >
        <Form form={disableForm} layout="vertical">
          <Form.Item name="reason" label="禁用原因（可选）">
            <Input.TextArea maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="更换 Node Token"
        open={tokenOpen}
        okText="确认更换"
        confirmLoading={operationPending}
        onOk={() => void rotateToken()}
        onCancel={() => {
          tokenForm.resetFields();
          setTokenOpen(false);
        }}
      >
        <Alert
          type="warning"
          message="更新成功后旧 Token 立即失效；新 Token 不会再次显示。"
          showIcon
        />
        <Form form={tokenForm} layout="vertical">
          <Form.Item
            name="token"
            label="新 Token"
            rules={[
              { required: true, message: "请输入新 Token" },
              { min: 32, max: 256, message: "Token 长度必须为 32 至 256 个字符" }
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

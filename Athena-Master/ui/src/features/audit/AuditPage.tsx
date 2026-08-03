import { useQuery } from "@tanstack/react-query";
import { Alert, Table, Tag } from "antd";
import { useState } from "react";

import { apiMessage, auditApi } from "../../shared/api/client";
import type { AuditAction, AuditLog } from "../../shared/api/types";

const ACTION_LABELS: Record<AuditAction, string> = {
  "auth.login": "管理员登录",
  "administrator.create": "创建管理员",
  "administrator.enable": "启用管理员",
  "administrator.disable": "禁用管理员",
  "administrator.password_reset": "重置管理员密码",
  "registration.approve": "批准注册申请",
  "registration.reject": "拒绝注册申请",
  "registration.restore": "恢复注册申请",
  "node.management_info.update": "修改节点管理信息",
  "node.enable": "启用接入节点",
  "node.disable": "禁用接入节点",
  "node.token.rotate": "更换 Node Token"
};

function formatLocalTime(value: string): string {
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

export function AuditPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const query = useQuery({
    queryKey: ["audit-logs", page, pageSize],
    queryFn: () => auditApi.list(page, pageSize),
    refetchOnMount: "always"
  });
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "本地时区";

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">AUDIT</p>
          <h1>审计日志</h1>
          <p>查看安全敏感和人工管理操作。浏览器时区：{browserTimeZone}</p>
        </div>
      </header>
      <section className="content-card">
        {query.isError ? (
          <Alert type="error" showIcon message={apiMessage(query.error)} />
        ) : (
          <Table<AuditLog>
            rowKey="id"
            dataSource={query.data?.items ?? []}
            loading={query.isLoading}
            pagination={{
              current: query.data?.page ?? page,
              pageSize: query.data?.page_size ?? pageSize,
              total: query.data?.total ?? 0,
              showSizeChanger: true,
              showTotal: (count) => `共 ${count} 条审计记录`,
              onChange: (nextPage, nextPageSize) => {
                setPage(nextPageSize === pageSize ? nextPage : 1);
                setPageSize(nextPageSize);
              }
            }}
            columns={[
              {
                title: "时间",
                render: (_, log) => (
                  <time dateTime={log.created_at}>{formatLocalTime(log.created_at)}</time>
                )
              },
              {
                title: "操作者",
                render: (_, log) =>
                  log.actor_username ? (
                    <span className="primary-cell">{log.actor_username}</span>
                  ) : (
                    <Tag>未认证</Tag>
                  )
              },
              {
                title: "操作",
                render: (_, log) => ACTION_LABELS[log.action] ?? log.action
              },
              {
                title: "目标",
                render: (_, log) => (
                  <span className="mono">
                    {log.target_label || log.target_id || "—"}
                  </span>
                )
              },
              {
                title: "结果",
                render: (_, log) => (
                  <Tag color={log.result === "success" ? "success" : "error"}>
                    {log.result === "success" ? "成功" : "失败"}
                  </Tag>
                )
              },
              {
                title: "来源 IP",
                render: (_, log) => (
                  <span className="mono">{log.source_ip || "—"}</span>
                )
              }
            ]}
          />
        )}
      </section>
    </div>
  );
}

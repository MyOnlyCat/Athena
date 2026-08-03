import { useQuery } from "@tanstack/react-query";
import { Table, Tag } from "antd";

import { auditApi } from "../../shared/api/client";

export function AuditPage() {
  const query = useQuery({ queryKey: ["audit"], queryFn: auditApi.list });
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区";
  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">SECURITY</p>
          <h1>审计日志</h1>
          <p>追踪登录用户执行的管理与文件操作。</p>
          <p className="muted">浏览器时区：{browserTimeZone}</p>
        </div>
      </header>
      <section className="content-card">
        <Table
          rowKey="id"
          dataSource={query.data ?? []}
          loading={query.isLoading}
          columns={[
            {
              title: "时间",
              render: (_, item) => new Date(item.created_at).toLocaleString("zh-CN")
            },
            { title: "操作", dataIndex: "action", className: "mono" },
            { title: "来源 IP", dataIndex: "source_ip", className: "mono" },
            { title: "用户 ID", dataIndex: "user_id", className: "mono" },
            {
              title: "结果",
              render: (_, item) => (
                <Tag color={item.result === "success" ? "success" : "error"}>
                  {item.result === "success" ? "成功" : "失败"}
                </Tag>
              )
            }
          ]}
        />
      </section>
    </div>
  );
}

import {
  CheckCircleOutlined,
  CloudServerOutlined,
  DeploymentUnitOutlined,
  DisconnectOutlined
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Progress, Table, Tag } from "antd";

import { hostsApi, tasksApi } from "../../shared/api/client";

export function DashboardPage() {
  const hosts = useQuery({ queryKey: ["hosts"], queryFn: hostsApi.list });
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: tasksApi.list });
  const normal = hosts.data?.filter((host) => host.last_test_status === "success").length ?? 0;
  const running = tasks.data?.filter((task) => ["claimed", "downloading", "running"].includes(task.status)).length ?? 0;

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">NODE OVERVIEW</p>
          <h1>晚上好，管理员</h1>
          <p>这里是当前 Athena 子节点的运行概览。</p>
        </div>
        <div className="live-badge">
          <span /> 节点运行中
        </div>
      </header>
      <section className="metric-grid">
        <article className="metric-card">
          <CloudServerOutlined />
          <p>接入主机</p>
          <strong>{hosts.data?.length ?? 0}</strong>
          <span>当前节点环境</span>
        </article>
        <article className="metric-card">
          <CheckCircleOutlined />
          <p>连接正常</p>
          <strong>{normal}</strong>
          <span>最近 SSH 检测</span>
        </article>
        <article className="metric-card">
          <DeploymentUnitOutlined />
          <p>执行中任务</p>
          <strong>{running}</strong>
          <span>主节点下发</span>
        </article>
        <article className="metric-card warning">
          <DisconnectOutlined />
          <p>连接异常</p>
          <strong>{Math.max(0, (hosts.data?.length ?? 0) - normal)}</strong>
          <span>需要关注</span>
        </article>
      </section>
      <section className="content-card">
        <div className="section-heading">
          <div>
            <h2>最近任务</h2>
            <p>从主节点领取的最新任务状态</p>
          </div>
        </div>
        <Table
          rowKey="id"
          dataSource={(tasks.data ?? []).slice(0, 6)}
          loading={tasks.isLoading}
          pagination={false}
          locale={{ emptyText: "暂无任务" }}
          columns={[
            { title: "任务 ID", dataIndex: "master_task_id", className: "mono" },
            { title: "制品", dataIndex: "artifact_name" },
            {
              title: "目标",
              render: (_, task) => `${task.targets.length} 台主机`
            },
            {
              title: "进度",
              render: (_, task) => (
                <Progress
                  percent={
                    task.targets.length
                      ? Math.round(
                          task.targets.reduce((sum, target) => sum + target.progress, 0) /
                            task.targets.length
                        )
                      : 0
                  }
                  size="small"
                  style={{ width: 140 }}
                />
              )
            },
            {
              title: "状态",
              render: (_, task) => (
                <Tag color={task.status === "succeeded" ? "success" : task.status === "failed" ? "error" : "processing"}>
                  {task.status}
                </Tag>
              )
            }
          ]}
        />
      </section>
    </div>
  );
}

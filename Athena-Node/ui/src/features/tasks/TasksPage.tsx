import { useQuery } from "@tanstack/react-query";
import { Drawer, Progress, Table, Timeline } from "antd";
import { useState } from "react";

import { tasksApi } from "../../shared/api/client";
import type { DeploymentTask } from "../../shared/api/types";
import { TaskStatus } from "./TaskStatus";

export function TasksPage() {
  const query = useQuery({
    queryKey: ["tasks"],
    queryFn: tasksApi.list,
    refetchInterval: (state) =>
      state.state.data?.some((task) =>
        ["claimed", "downloading", "running"].includes(task.status)
      )
        ? 2_000
        : false
  });
  const [selected, setSelected] = useState<DeploymentTask | null>(null);
  const events = useQuery({
    queryKey: ["task-events", selected?.id],
    queryFn: () => tasksApi.events(selected!.id),
    enabled: Boolean(selected)
  });
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区";
  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">DEPLOYMENT</p>
          <h1>当前任务</h1>
          <p>查看主节点下发任务的实时阶段、日志和结果。</p>
          <p className="muted">浏览器时区：{browserTimeZone}</p>
        </div>
      </header>
      <section className="content-card">
        <Table
          rowKey="id"
          dataSource={query.data ?? []}
          loading={query.isLoading}
          onRow={(task) => ({ onClick: () => setSelected(task) })}
          columns={[
            { title: "任务 ID", dataIndex: "master_task_id", className: "mono" },
            { title: "制品", dataIndex: "artifact_name" },
            { title: "目标数", render: (_, task) => task.targets.length },
            {
              title: "进度",
              render: (_, task) => (
                <Progress
                  size="small"
                  percent={
                    task.targets.length
                      ? Math.round(
                          task.targets.reduce(
                            (sum, target) => sum + target.progress,
                            0
                          ) / task.targets.length
                        )
                      : 0
                  }
                />
              )
            },
            {
              title: "状态",
              render: (_, task) => <TaskStatus status={task.status} />
            },
            {
              title: "领取时间",
              render: (_, task) => new Date(task.claimed_at).toLocaleString("zh-CN")
            }
          ]}
        />
      </section>
      <Drawer
        width={680}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.master_task_id}
      >
        {selected?.targets.map((target) => (
          <section key={target.id} className="task-target-card">
            <div>
              <strong className="mono">{target.target_ip}</strong>
              <TaskStatus status={target.status} />
            </div>
            <p className="mono">{target.target_directory}</p>
            <Progress percent={target.progress} />
          </section>
        ))}
        <h3>实时事件</h3>
        <Timeline
          items={(events.data ?? []).map((event) => ({
            color: event.event_type === "stderr" ? "red" : "blue",
            children: (
              <div>
                <small>{new Date(event.created_at).toLocaleTimeString("zh-CN")}</small>
                <pre>
                  {String(
                    event.payload.data ??
                      event.payload.stage ??
                      event.payload.status ??
                      ""
                  )}
                </pre>
              </div>
            )
          }))}
        />
      </Drawer>
    </div>
  );
}

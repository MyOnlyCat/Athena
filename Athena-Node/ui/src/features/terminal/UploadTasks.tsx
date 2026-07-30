import { CloseOutlined } from "@ant-design/icons";
import { Button, Progress, Space, Tooltip } from "antd";

import type { UploadSummary, UploadTask } from "../../shared/api/types";

interface UploadTasksProps {
  tasks: UploadTask[];
  summary: UploadSummary;
  onCancel: (id: string) => void;
  onCancelAll: () => void;
  onClearSettled: () => void;
}

function taskPercent(task: UploadTask) {
  if (task.status === "completed") return 100;
  return task.total ? Math.round((task.loaded / task.total) * 100) : 0;
}

export function UploadTasks({
  tasks,
  summary,
  onCancel,
  onCancelAll,
  onClearSettled
}: UploadTasksProps) {
  if (!tasks.length) {
    return <div className="terminal-empty">暂无上传任务</div>;
  }

  const canCancel = summary.queued + summary.uploading > 0;
  const canClear = summary.completed + summary.failed + summary.cancelled > 0;
  return (
    <section aria-label="Upload tasks" className="upload-tasks">
      <Space>
        <strong>上传队列</strong>
        <span>
          {summary.completed}/{summary.total}
        </span>
        {canCancel && (
          <Button size="small" danger onClick={onCancelAll}>
            全部取消
          </Button>
        )}
        {canClear && (
          <Button size="small" onClick={onClearSettled}>
            清除已结束
          </Button>
        )}
      </Space>
      <Progress percent={summary.percent} size="small" />
      {tasks.map((task) => {
        const cancellable = task.status === "queued" || task.status === "uploading";
        return (
          <div className="upload-task" key={task.id}>
            <Space>
              <span title={task.destination}>{task.file.name}</span>
              <span>{task.status}</span>
              {cancellable && (
                <Tooltip title="取消">
                  <Button
                    aria-label={`Cancel ${task.file.name}`}
                    type="text"
                    size="small"
                    danger
                    icon={<CloseOutlined />}
                    onClick={() => onCancel(task.id)}
                  />
                </Tooltip>
              )}
            </Space>
            <Progress
              percent={taskPercent(task)}
              size="small"
              status={task.status === "failed" ? "exception" : undefined}
            />
            {task.error && <small>{task.error}</small>}
          </div>
        );
      })}
    </section>
  );
}

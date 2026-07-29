import { CloseOutlined } from "@ant-design/icons";
import { Button, Progress, Space, Tooltip } from "antd";

import type { UploadSummary, UploadTask } from "../../shared/api/types";

interface UploadTasksProps {
  tasks: UploadTask[];
  summary: UploadSummary;
  onCancel: (id: string) => void;
  onCancelAll: () => void;
}

function taskPercent(task: UploadTask) {
  if (task.status === "completed") return 100;
  return task.total ? Math.round((task.loaded / task.total) * 100) : 0;
}

export function UploadTasks({
  tasks,
  summary,
  onCancel,
  onCancelAll
}: UploadTasksProps) {
  if (!tasks.length) return null;

  const canCancel = summary.queued + summary.uploading > 0;
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

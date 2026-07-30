import { Tag } from "antd";

const statuses: Record<string, { color: string; label: string }> = {
  claimed: { color: "default", label: "已领取" },
  downloading: { color: "processing", label: "下载制品" },
  running: { color: "processing", label: "执行中" },
  succeeded: { color: "success", label: "成功" },
  failed: { color: "error", label: "失败" },
  manual_review: { color: "warning", label: "需人工确认" }
};

export function TaskStatus({ status }: { status: string }) {
  const item = statuses[status] ?? { color: "default", label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
}

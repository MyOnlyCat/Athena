import { Button, Space, Table, Tag } from "antd";

import type { User } from "../../shared/api/types";

interface Props {
  currentUserId: string;
  users: User[];
  loading: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number, pageSize: number) => void;
  onStatusChange: (user: User) => void;
  onResetPassword: (user: User) => void;
}

function formatLocalTime(value: string | null): string {
  if (!value) return "从未登录";
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

export function AdministratorTable({
  currentUserId,
  users,
  loading,
  page,
  pageSize,
  total,
  onPageChange,
  onStatusChange,
  onResetPassword
}: Props) {
  return (
    <Table<User>
      rowKey="id"
      dataSource={users}
      loading={loading}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (count) => `共 ${count} 个管理员`,
        onChange: onPageChange
      }}
      columns={[
        {
          title: "管理员",
          render: (_, user) => (
            <Space>
              <span className="primary-cell">{user.username}</span>
              {user.id === currentUserId && <Tag color="blue">当前账号</Tag>}
            </Space>
          )
        },
        {
          title: "状态",
          render: (_, user) => (
            <Tag color={user.is_active ? "success" : "default"}>
              {user.is_active ? "已启用" : "已禁用"}
            </Tag>
          )
        },
        {
          title: "最近登录",
          render: (_, user) => formatLocalTime(user.last_login_at)
        },
        {
          title: "操作",
          align: "right",
          render: (_, user) => (
            <Space>
              <Button onClick={() => onResetPassword(user)}>重置密码</Button>
              <Button
                danger={user.is_active}
                disabled={user.id === currentUserId}
                onClick={() => onStatusChange(user)}
              >
                {user.is_active ? "禁用" : "启用"}
              </Button>
            </Space>
          )
        }
      ]}
    />
  );
}

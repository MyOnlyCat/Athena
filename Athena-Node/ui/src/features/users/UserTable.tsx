import { Button, Space, Table, Tag } from "antd";

import type { User } from "../../shared/api/types";

interface Props {
  currentUserId: string;
  users: User[];
  loading: boolean;
  onStatusChange: (user: User) => void;
  onResetPassword: (user: User) => void;
}

export function UserTable({
  currentUserId,
  users,
  loading,
  onStatusChange,
  onResetPassword
}: Props) {
  return (
    <Table
      rowKey="id"
      dataSource={users}
      loading={loading}
      pagination={false}
      columns={[
        {
          title: "用户",
          render: (_, user) => (
            <Space>
              <span className="primary-cell">{user.username}</span>
              {user.id === currentUserId && <Tag color="blue">当前用户</Tag>}
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
          render: (_, user) =>
            user.last_login_at ? new Date(user.last_login_at).toLocaleString("zh-CN") : "从未"
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

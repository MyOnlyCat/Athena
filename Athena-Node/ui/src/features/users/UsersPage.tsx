import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal } from "antd";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { apiMessage, usersApi } from "../../shared/api/client";
import type { User } from "../../shared/api/types";
import { UserTable } from "./UserTable";

export function UsersPage() {
  const { user: currentUser } = useAuth();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["users"], queryFn: usersApi.list });
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<{ username: string; password: string }>();
  const browserTimeZone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区";

  const create = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      usersApi.create(username, password),
    onSuccess: () => {
      message.success("用户已创建");
      setCreating(false);
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error) => message.error(apiMessage(error))
  });

  function toggle(user: User) {
    modal.confirm({
      title: `${user.is_active ? "禁用" : "启用"}用户 ${user.username}？`,
      onOk: async () => {
        await usersApi.status(user.id, !user.is_active);
        queryClient.invalidateQueries({ queryKey: ["users"] });
      }
    });
  }

  function reset(user: User) {
    let password = "";
    modal.confirm({
      title: `重置 ${user.username} 的密码`,
      content: (
        <Input.Password
          autoFocus
          placeholder="至少 12 位"
          onChange={(event) => {
            password = event.target.value;
          }}
        />
      ),
      onOk: async () => {
        if (password.length < 12) throw new Error("密码至少需要 12 位");
        await usersApi.resetPassword(user.id, password);
        message.success("密码已重置");
      }
    });
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">ACCESS CONTROL</p>
          <h1>用户管理</h1>
          <p>维护可登录此子节点的管理员账号。</p>
          <p className="muted">浏览器时区：{browserTimeZone}</p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          创建用户
        </Button>
      </header>
      <section className="content-card">
        <UserTable
          currentUserId={currentUser?.id ?? ""}
          users={query.data ?? []}
          loading={query.isLoading}
          onStatusChange={toggle}
          onResetPassword={reset}
        />
      </section>
      <Modal
        open={creating}
        title="创建管理员用户"
        okText="创建"
        cancelText="取消"
        confirmLoading={create.isPending}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, min: 3 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 12 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

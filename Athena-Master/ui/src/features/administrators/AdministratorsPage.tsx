import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal } from "antd";
import type { Rule, RuleObject } from "antd/es/form";
import { useState } from "react";

import { apiMessage, administratorsApi } from "../../shared/api/client";
import type { User } from "../../shared/api/types";
import { useAuth } from "../auth/AuthContext";
import { AdministratorTable } from "./AdministratorTable";

interface CreateForm {
  username: string;
  password: string;
}

const PASSWORD_COMPLEXITY_RULES: Rule[] = [
  { min: 12, max: 128, message: "密码须为 12–128 个字符" },
  { pattern: /[A-Za-z]/, message: "密码必须包含字母" },
  { pattern: /\d/, message: "密码必须包含数字" }
];

function passwordIdentityRule(username: () => string): RuleObject {
  return {
    validator(_, value: string) {
      if (!value || value.toLocaleLowerCase() !== username().toLocaleLowerCase()) {
        return Promise.resolve();
      }
      return Promise.reject(new Error("密码不能与用户名相同"));
    }
  };
}

export function AdministratorsPage() {
  const { user: currentUser } = useAuth();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [creating, setCreating] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [form] = Form.useForm<CreateForm>();
  const [resetForm] = Form.useForm<{ password: string }>();
  const queryKey = ["administrators", page, pageSize] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => administratorsApi.list(page, pageSize)
  });

  const create = useMutation({
    mutationFn: ({ username, password }: CreateForm) =>
      administratorsApi.create(username.trim(), password),
    onSuccess: async () => {
      message.success("管理员已创建");
      setCreating(false);
      form.resetFields();
      await queryClient.invalidateQueries({ queryKey: ["administrators"] });
    },
    onError: (error) => message.error(apiMessage(error))
  });

  const statusChange = useMutation({
    mutationFn: ({ user, isActive }: { user: User; isActive: boolean }) =>
      administratorsApi.status(user.id, isActive),
    onSuccess: async (_, { isActive }) => {
      message.success(isActive ? "管理员已启用" : "管理员已禁用");
      await queryClient.invalidateQueries({ queryKey: ["administrators"] });
    },
    onError: (error) => message.error(apiMessage(error))
  });

  const resetPassword = useMutation({
    mutationFn: ({ user, password }: { user: User; password: string }) =>
      administratorsApi.resetPassword(user.id, password),
    onSuccess: async () => {
      message.success("密码已重置，原有登录凭证已失效");
      setResetTarget(null);
      resetForm.resetFields();
      await queryClient.invalidateQueries({ queryKey: ["administrators"] });
    },
    onError: (error) => message.error(apiMessage(error))
  });

  function confirmStatusChange(user: User) {
    const isActive = !user.is_active;
    const action = isActive ? "启用" : "禁用";
    modal.confirm({
      title: `${action}管理员 ${user.username}？`,
      content: isActive
        ? "启用后，该管理员可以重新登录。"
        : "禁用会立即撤销该管理员的全部现有登录凭证。",
      okText: action,
      cancelText: "取消",
      okButtonProps: { danger: !isActive },
      onOk: () => statusChange.mutateAsync({ user, isActive })
    });
  }

  return (
    <div className="page-stack">
      <header className="page-header page-header-split">
        <div>
          <p className="eyebrow">ADMINISTRATORS</p>
          <h1>管理员</h1>
          <p>维护可登录 Athena-Master 的管理员账号。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreating(true)}
        >
          创建管理员
        </Button>
      </header>
      <section className="content-card">
        <AdministratorTable
          currentUserId={currentUser?.id ?? ""}
          users={query.data?.items ?? []}
          loading={query.isLoading}
          page={query.data?.page ?? page}
          pageSize={query.data?.page_size ?? pageSize}
          total={query.data?.total ?? 0}
          onPageChange={(nextPage, nextPageSize) => {
            setPage(nextPageSize === pageSize ? nextPage : 1);
            setPageSize(nextPageSize);
          }}
          onStatusChange={confirmStatusChange}
          onResetPassword={setResetTarget}
        />
      </section>
      <Modal
        open={creating}
        title="创建管理员"
        okText="创建"
        cancelText="取消"
        confirmLoading={create.isPending}
        onCancel={() => {
          setCreating(false);
          form.resetFields();
        }}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: "请输入用户名" }]}
          >
            <Input maxLength={64} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            dependencies={["username"]}
            rules={[
              { required: true, message: "请输入初始密码" },
              ...PASSWORD_COMPLEXITY_RULES,
              ({ getFieldValue }) =>
                passwordIdentityRule(() =>
                  String(getFieldValue("username") ?? "").trim()
                )
            ]}
          >
            <Input.Password maxLength={128} autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={resetTarget !== null}
        title={`重置 ${resetTarget?.username ?? ""} 的密码`}
        okText="重置"
        cancelText="取消"
        confirmLoading={resetPassword.isPending}
        onCancel={() => {
          setResetTarget(null);
          resetForm.resetFields();
        }}
        onOk={() => resetForm.submit()}
      >
        <Form
          form={resetForm}
          layout="vertical"
          onFinish={({ password }) => {
            if (resetTarget) resetPassword.mutate({ user: resetTarget, password });
          }}
        >
          <Form.Item
            name="password"
            label="新密码"
            rules={[
              { required: true, message: "请输入新密码" },
              ...PASSWORD_COMPLEXITY_RULES,
              passwordIdentityRule(() => resetTarget?.username ?? "")
            ]}
          >
            <Input.Password maxLength={128} autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

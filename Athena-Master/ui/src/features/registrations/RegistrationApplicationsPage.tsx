import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal, Space, Table, Tag } from "antd";
import { useState } from "react";

import {
  apiMessage,
  registrationApplicationsApi
} from "../../shared/api/client";
import { OVERVIEW_QUERY_KEY } from "../../shared/api/queryPolicy";
import type { RegistrationApplication } from "../../shared/api/types";

function formatLocalTime(value: string): string {
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

export function RegistrationApplicationsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [approvalTarget, setApprovalTarget] =
    useState<RegistrationApplication | null>(null);
  const [rejectionTarget, setRejectionTarget] =
    useState<RegistrationApplication | null>(null);
  const [form] = Form.useForm<{ token: string }>();
  const [rejectionForm] = Form.useForm<{ reason?: string }>();
  const query = useQuery({
    queryKey: ["registration-applications", page, pageSize],
    queryFn: () => registrationApplicationsApi.list(page, pageSize)
  });
  const approval = useMutation({
    mutationFn: ({ id, token }: { id: string; token: string }) =>
      registrationApplicationsApi.approve(id, token),
    onSuccess: async () => {
      form.resetFields();
      setApprovalTarget(null);
      message.success("注册申请已批准");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["registration-applications"] }),
        queryClient.invalidateQueries({ queryKey: OVERVIEW_QUERY_KEY })
      ]);
    },
    onError: (error) => message.error(apiMessage(error))
  });
  const rejection = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      registrationApplicationsApi.reject(id, reason),
    onSuccess: async () => {
      rejectionForm.resetFields();
      setRejectionTarget(null);
      message.success("注册申请已拒绝");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["registration-applications"] }),
        queryClient.invalidateQueries({ queryKey: OVERVIEW_QUERY_KEY })
      ]);
    },
    onError: (error) => message.error(apiMessage(error))
  });
  const restoration = useMutation({
    mutationFn: (id: string) => registrationApplicationsApi.restore(id),
    onSuccess: async () => {
      message.success("注册申请已恢复，Node 可手动重新提交");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["registration-applications"] }),
        queryClient.invalidateQueries({ queryKey: OVERVIEW_QUERY_KEY })
      ]);
    },
    onError: (error) => message.error(apiMessage(error))
  });

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">REGISTRATION APPLICATIONS</p>
          <h1>注册申请</h1>
          <p>申请资料在 Token 验证前均不可信，请通过可信渠道核对接入节点。</p>
        </div>
      </header>
      <section className="content-card">
        <Table<RegistrationApplication>
          rowKey="id"
          dataSource={query.data?.items ?? []}
          loading={query.isLoading}
          pagination={{
            current: query.data?.page ?? page,
            pageSize: query.data?.page_size ?? pageSize,
            total: query.data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条申请`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPageSize === pageSize ? nextPage : 1);
              setPageSize(nextPageSize);
            }
          }}
          columns={[
            {
              title: "接入节点",
              render: (_, application) => (
                <Space direction="vertical" size={0}>
                  <span className="primary-cell">
                    {application.reported_name}
                  </span>
                  <span>{application.node_id}</span>
                </Space>
              )
            },
            {
              title: "上报环境",
              render: (_, application) => (
                <Space direction="vertical" size={0}>
                  <span>{application.hostname}</span>
                  <span>版本 {application.software_version}</span>
                </Space>
              )
            },
            {
              title: "可信状态",
              render: (_, application) => (
                <Space direction="vertical" size={0}>
                {application.identity_verified ? (
                  <Tag color="success">身份已验证</Tag>
                ) : application.status === "rejected" ? (
                  <Tag color="error">已拒绝</Tag>
                ) : application.status === "expired" ? (
                  <Tag>已过期</Tag>
                ) : application.status === "restored" ? (
                  <Tag color="processing">已恢复</Tag>
                ) : (
                  <Tag color="warning">身份未验证</Tag>
                )
                }
                {application.rejection_reason && <span>{application.rejection_reason}</span>}
                </Space>
              )
            },
            {
              title: "接收时间",
              dataIndex: "received_at",
              render: formatLocalTime
            },
            {
              title: "操作",
              align: "right",
              render: (_, application) =>
                application.status === "pending" ? (
                  <Space>
                    <Button onClick={() => setRejectionTarget(application)}>
                      拒绝
                    </Button>
                    <Button
                      type="primary"
                      onClick={() => setApprovalTarget(application)}
                    >
                      批准
                    </Button>
                  </Space>
                ) : application.status === "rejected" ? (
                  <Button
                    loading={restoration.isPending}
                    onClick={() => restoration.mutate(application.id)}
                  >
                    恢复申请
                  </Button>
                ) : application.status === "expired" ? (
                  <Tag>已过期</Tag>
                ) : application.status === "restored" ? (
                  <Tag color="processing">等待 Node 重新提交</Tag>
                ) : (
                  <Tag color="success">已批准</Tag>
                )
            }
          ]}
        />
      </section>
      <Modal
        open={approvalTarget !== null}
        destroyOnHidden
        title={`批准注册申请：${approvalTarget?.reported_name ?? ""}`}
        okText="批准"
        cancelText="取消"
        confirmLoading={approval.isPending}
        onCancel={() => {
          form.resetFields();
          setApprovalTarget(null);
        }}
        onOk={() => form.submit()}
      >
        <p>请输入通过可信渠道从 Node 获取的同一 Token。Token 不会回显。</p>
        <Form
          form={form}
          preserve={false}
          layout="vertical"
          onFinish={({ token }) => {
            if (approvalTarget) {
              approval.mutate({ id: approvalTarget.id, token });
            }
          }}
        >
          <Form.Item
            name="token"
            label="Node Token"
            rules={[
              { required: true, message: "请输入 Node Token" },
              { min: 32, max: 256, message: "Token 长度必须为 32 至 256 个字符" }
            ]}
          >
            <Input.Password autoComplete="new-password" maxLength={256} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={rejectionTarget !== null}
        destroyOnHidden
        title={`拒绝注册申请：${rejectionTarget?.reported_name ?? ""}`}
        okText="拒绝"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        confirmLoading={rejection.isPending}
        onCancel={() => {
          rejectionForm.resetFields();
          setRejectionTarget(null);
        }}
        onOk={() => rejectionForm.submit()}
      >
        <Form
          form={rejectionForm}
          preserve={false}
          layout="vertical"
          onFinish={({ reason }) => {
            if (rejectionTarget) rejection.mutate({ id: rejectionTarget.id, reason });
          }}
        >
          <Form.Item name="reason" label="拒绝原因">
            <Input.TextArea maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

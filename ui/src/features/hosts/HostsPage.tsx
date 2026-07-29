import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch
} from "antd";
import { useState } from "react";

import { apiMessage, hostsApi } from "../../shared/api/client";
import type { Host, HostInput } from "../../shared/api/types";
import { HostTable } from "./HostTable";

export function HostsPage() {
  const { message, modal } = App.useApp();
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["hosts"], queryFn: hostsApi.list });
  const [editing, setEditing] = useState<Host | null | "new">(null);
  const [form] = Form.useForm<HostInput & { tagsText: string }>();

  const save = useMutation({
    mutationFn: async (values: HostInput & { tagsText: string }) => {
      const payload = {
        ...values,
        tags: values.tagsText
          ? values.tagsText.split(",").map((item) => item.trim()).filter(Boolean)
          : []
      };
      delete (payload as Partial<typeof payload>).tagsText;
      return editing === "new"
        ? hostsApi.create(payload)
        : hostsApi.update((editing as Host).id, payload);
    },
    onSuccess: () => {
      message.success("主机信息已保存");
      setEditing(null);
      client.invalidateQueries({ queryKey: ["hosts"] });
    },
    onError: (error) => message.error(apiMessage(error))
  });

  function openEditor(host?: Host) {
    setEditing(host ?? "new");
    form.setFieldsValue(
      host
        ? { ...host, password: undefined, tagsText: host.tags.join(", ") }
        : {
            name: "",
            address: "",
            port: 22,
            username: "root",
            password: "",
            is_local: false,
            tags: [],
            tagsText: ""
          }
    );
  }

  async function testHost(host: Host) {
    try {
      const result = await hostsApi.test(host.id);
      if (result.code === "SSH_HOST_KEY_UNTRUSTED" || result.code === "SSH_HOST_KEY_CHANGED") {
        modal.confirm({
          title: result.code === "SSH_HOST_KEY_CHANGED" ? "主机指纹发生变化" : "确认主机指纹",
          content: <span className="mono">{result.fingerprint}</span>,
          okText: "信任此指纹",
          onOk: () => hostsApi.trust(host.id, result.fingerprint)
        });
      } else {
        message[result.status === "success" ? "success" : "error"](result.message);
      }
      client.invalidateQueries({ queryKey: ["hosts"] });
    } catch (error) {
      message.error(apiMessage(error));
    }
  }

  function removeHost(host: Host) {
    modal.confirm({
      title: `删除主机 ${host.name}？`,
      content: "删除后无法再通过此节点连接该服务器。",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await hostsApi.remove(host.id);
        client.invalidateQueries({ queryKey: ["hosts"] });
      }
    });
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">INFRASTRUCTURE</p>
          <h1>主机管理</h1>
          <p>管理当前节点可访问的 SSH 主机与连接状态。</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => query.refetch()}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>
            添加主机
          </Button>
        </Space>
      </header>
      <section className="content-card">
        <HostTable
          hosts={query.data ?? []}
          loading={query.isLoading}
          onEdit={openEditor}
          onDelete={removeHost}
          onTest={testHost}
        />
      </section>
      <Modal
        open={editing !== null}
        title={editing === "new" ? "添加 SSH 主机" : "编辑 SSH 主机"}
        okText="保存"
        cancelText="取消"
        confirmLoading={save.isPending}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(values) => save.mutate(values)}>
          <Form.Item name="name" label="主机名称" rules={[{ required: true }]}>
            <Input placeholder="例如：web-01" />
          </Form.Item>
          <div className="form-grid">
            <Form.Item name="address" label="IP / 主机名" rules={[{ required: true }]}>
              <Input placeholder="10.0.0.10" />
            </Form.Item>
            <Form.Item name="port" label="SSH 端口" rules={[{ required: true }]}>
              <InputNumber min={1} max={65535} style={{ width: "100%" }} />
            </Form.Item>
          </div>
          <div className="form-grid">
            <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item
              name="password"
              label={editing === "new" ? "密码" : "新密码（留空不修改）"}
              rules={editing === "new" ? [{ required: true }] : []}
            >
              <Input.Password />
            </Form.Item>
          </div>
          <Form.Item name="tagsText" label="标签">
            <Input placeholder="production, web" />
          </Form.Item>
          <Form.Item name="is_local" label="标记为当前节点" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

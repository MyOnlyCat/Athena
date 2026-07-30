import { SaveOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Tag } from "antd";
import axios from "axios";
import { useEffect, useState } from "react";

import { apiMessage, masterSettingsApi } from "../../shared/api/client";
import type { ApiErrorBody, MasterSettingInput, MasterSettingResponse } from "../../shared/api/types";

type MasterSettingsForm = Omit<MasterSettingInput, "token"> & { token?: string };

function toFormValues(settings: MasterSettingResponse): MasterSettingsForm {
  return {
    scheme: settings.scheme,
    host: settings.host,
    port: settings.port,
    token: ""
  };
}

function masterSettingsMessage(error: unknown, operation: "test" | "save"): string {
  if (axios.isAxiosError(error)) {
    const code = (error.response?.data as Partial<ApiErrorBody> | undefined)?.code;
    if (code === "MASTER_CONNECTION_FAILED") {
      return "无法连接到主节点，请检查地址、端口和 Token。";
    }
  }
  const message = apiMessage(error);
  if (/[\u3400-\u9FFF]/.test(message)) return message;
  return operation === "test"
    ? "连接测试失败，请检查配置后重试。"
    : "保存主节点配置失败，请检查配置后重试。";
}

export function MasterSettingsPage() {
  const [form] = Form.useForm<MasterSettingsForm>();
  const settings = useQuery({ queryKey: ["master-settings"], queryFn: masterSettingsApi.get });
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings.data) form.setFieldsValue(toFormValues(settings.data));
  }, [form, settings.data]);

  async function payload(): Promise<MasterSettingInput> {
    const values = await form.validateFields();
    return { ...values, token: values.token ?? "" };
  }

  async function testConnection() {
    try {
      setError(null);
      setTesting(true);
      await masterSettingsApi.test(await payload());
    } catch (requestError) {
      setError(masterSettingsMessage(requestError, "test"));
    } finally {
      setTesting(false);
    }
  }

  async function save(values: MasterSettingsForm) {
    try {
      setError(null);
      setSaving(true);
      const updated = await masterSettingsApi.update({ ...values, token: values.token ?? "" });
      form.setFieldsValue(toFormValues(updated));
      await settings.refetch();
    } catch (requestError) {
      setError(masterSettingsMessage(requestError, "save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-stack master-settings-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">CONTROL PLANE</p>
          <h1>主节点配置</h1>
          <p>配置此节点连接主节点的地址和访问令牌。</p>
        </div>
        {settings.data && <Tag>{settings.data.runtime_status}</Tag>}
      </header>
      <Card className="content-card" variant="borderless" loading={settings.isLoading}>
        {error && <Alert className="master-settings-error" type="error" message={error} showIcon />}
        <Form form={form} layout="vertical" onFinish={save}>
          <div className="form-grid">
            <Form.Item name="scheme" label="协议" rules={[{ required: true }]}>
              <Select options={[{ value: "https", label: "HTTPS" }, { value: "http", label: "HTTP" }]} />
            </Form.Item>
            <Form.Item name="host" label="主节点地址" rules={[{ required: true }]}>
              <Input autoComplete="url" placeholder="master.example.com" />
            </Form.Item>
          </div>
          <div className="form-grid">
            <Form.Item name="port" label="端口" rules={[{ required: true }]}>
              <InputNumber min={1} max={65535} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="Token" extra={settings.data?.has_token ? "已保存" : "尚未保存"}>
              <Form.Item name="token" noStyle>
                <Input.Password aria-label="Token" autoComplete="new-password" />
              </Form.Item>
            </Form.Item>
          </div>
          <p className="master-settings-help">留空会复用当前已保存的 Token。</p>
          <Space>
            <Button icon={<ThunderboltOutlined />} loading={testing} onClick={testConnection}>
              连接测试
            </Button>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
              保存并应用
            </Button>
          </Space>
        </Form>
      </Card>
    </div>
  );
}

import { CopyOutlined, KeyOutlined, SaveOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tag
} from "antd";
import axios from "axios";
import { useEffect, useState } from "react";

import { apiMessage, masterSettingsApi } from "../../shared/api/client";
import type {
  ApiErrorBody,
  MasterRuntimeStatus,
  MasterSettingInput,
  MasterSettingResponse
} from "../../shared/api/types";

type MasterSettingsForm = Omit<MasterSettingInput, "token"> & { token?: string };

const runtimeStatusLabels: Record<MasterRuntimeStatus, string> = {
  unconfigured: "未配置",
  connecting: "连接中",
  online: "在线",
  error: "异常",
  stopped: "已停止"
};

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

function generateToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const binary = String.fromCharCode(...Array.from(bytes));
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
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

  function createToken() {
    form.setFieldValue("token", generateToken());
    void form.validateFields(["token"]);
  }

  async function copyToken() {
    const token = form.getFieldValue("token");
    if (!token) {
      setError("请先生成或输入 Token。");
      return;
    }
    try {
      await navigator.clipboard.writeText(token);
      setError(null);
    } catch {
      setError("复制 Token 失败，请手动复制。");
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
        {settings.data && <Tag>{runtimeStatusLabels[settings.data.runtime_status]}</Tag>}
      </header>
      <Card className="content-card" variant="borderless" loading={settings.isLoading}>
        {error && <Alert className="master-settings-error" type="error" message={error} showIcon />}
        {settings.data && (
          <section className="master-settings-identity" aria-labelledby="node-identity-title">
            <div>
              <span id="node-identity-title">接入节点身份</span>
              <strong>{settings.data.node_name}</strong>
            </div>
            <div>
              <span>节点 ID</span>
              <code>{settings.data.node_id}</code>
            </div>
          </section>
        )}
        <Form form={form} layout="vertical" onFinish={save}>
          <div className="master-settings-form-heading">
            <h2>连接配置</h2>
            <p>设置主节点地址和用于身份验证的访问令牌。</p>
          </div>
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
            <Form.Item
              label="Token"
              extra={
                <>
                  <span className="master-settings-token-status">
                    {settings.data?.has_token ? "已保存" : "尚未保存"}
                  </span>
                  {settings.data?.has_token
                    ? "留空将继续使用当前 Token。"
                    : "生成值仅显示在当前输入框，请立即复制并妥善保存。"}
                </>
              }
            >
              <Space.Compact block role="group" aria-label="Token 配置">
                <Form.Item
                  name="token"
                  noStyle
                  rules={[
                    {
                      validator: (_, value: string | undefined) => {
                        if (!value || (value.length >= 32 && value.length <= 256)) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error("Token 长度必须为 32 至 256 个字符"));
                      }
                    }
                  ]}
                >
                  <Input.Password aria-label="Token" autoComplete="new-password" />
                </Form.Item>
                <Button icon={<KeyOutlined />} onClick={createToken}>
                  生成 Token
                </Button>
                <Button icon={<CopyOutlined />} onClick={copyToken}>
                  复制 Token
                </Button>
              </Space.Compact>
            </Form.Item>
          </div>
          <div className="master-settings-actions" role="group" aria-label="配置操作">
            <Button icon={<ThunderboltOutlined />} loading={testing} onClick={testConnection}>
              连接测试
            </Button>
            <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
              保存并应用
            </Button>
          </div>
        </Form>
      </Card>
    </div>
  );
}

import {
  CopyOutlined,
  FormOutlined,
  KeyOutlined,
  SaveOutlined,
  ThunderboltOutlined
} from "@ant-design/icons";
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
import { useEffect, useRef, useState } from "react";

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
  disabled: "已禁用",
  authentication_failed: "认证失败",
  connection_failed: "连接失败",
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
  const initialized = useRef(false);
  const settings = useQuery({
    queryKey: ["master-settings"],
    queryFn: async () => {
      const current = await masterSettingsApi.get();
      if (current.registration_status !== "pending") return current;
      const registration = await masterSettingsApi.registrationStatus();
      return { ...current, registration_status: registration.status };
    },
    refetchInterval: (query) =>
      query.state.data?.registration_status === "pending" ? 60_000 : false
  });
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  useEffect(() => {
    if (settings.data && !initialized.current) {
      form.setFieldsValue(toFormValues(settings.data));
      initialized.current = true;
      setHasUnsavedChanges(false);
    }
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
      setHasUnsavedChanges(false);
      await settings.refetch();
    } catch (requestError) {
      setError(masterSettingsMessage(requestError, "save"));
    } finally {
      setSaving(false);
    }
  }

  async function register() {
    try {
      setError(null);
      setRegistering(true);
      await masterSettingsApi.register();
      form.setFieldValue("token", "");
      await settings.refetch();
    } catch (requestError) {
      setError(masterSettingsMessage(requestError, "save"));
    } finally {
      setRegistering(false);
    }
  }

  function createToken() {
    form.setFieldValue("token", generateToken());
    setHasUnsavedChanges(true);
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
        {settings.data && (
          <Space>
            {settings.data.registration_status === "pending" && (
              <Tag color="processing">待管理员审批</Tag>
            )}
            {settings.data.registration_status === "approved" && (
              <Tag color="success">已批准</Tag>
            )}
            {settings.data.registration_status === "rejected" && (
              <Tag color="error">已拒绝</Tag>
            )}
            {settings.data.registration_status === "expired" && (
              <Tag>已过期</Tag>
            )}
            {settings.data.registration_status === "restored" && (
              <Tag color="processing">可重新申请</Tag>
            )}
            <Tag>{runtimeStatusLabels[settings.data.runtime_status]}</Tag>
          </Space>
        )}
      </header>
      <Card className="content-card" variant="borderless" loading={settings.isLoading}>
        {error && <Alert className="master-settings-error" type="error" message={error} showIcon />}
        {settings.data?.registration_status === "rejected" && (
          <Alert
            type="error"
            message="管理员恢复后，请手动重新提交申请。"
            showIcon
          />
        )}
        {settings.data?.registration_status === "expired" && (
          <Alert type="warning" message="申请已过期，请手动重新提交。" showIcon />
        )}
        {settings.data?.registration_status === "restored" && (
          <Alert type="info" message="管理员已恢复申请，请手动重新提交。" showIcon />
        )}
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
        <Form
          form={form}
          layout="vertical"
          onFinish={save}
          onValuesChange={() => setHasUnsavedChanges(true)}
        >
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
            <Button
              icon={<FormOutlined />}
              loading={registering}
              disabled={hasUnsavedChanges || !settings.data?.has_token}
              onClick={register}
            >
              申请接入
            </Button>
          </div>
        </Form>
      </Card>
    </div>
  );
}

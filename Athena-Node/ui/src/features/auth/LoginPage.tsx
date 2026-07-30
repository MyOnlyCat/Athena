import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input } from "antd";
import { useState } from "react";

interface Props {
  onLogin: (username: string, password: string) => Promise<void>;
}

export function LoginPage({ onLogin }: Props) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(values: { username: string; password: string }) {
    setLoading(true);
    setError("");
    try {
      await onLogin(values.username, values.password);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-brand">
        <div className="brand-mark large">A</div>
        <p className="eyebrow">ATHENA DISTRIBUTED OPERATIONS</p>
        <h1>让每一个节点，都清晰可控</h1>
        <p>主机接入、网页终端、文件管理和制品发布，一个控制台完成。</p>
        <div className="signal-grid" aria-hidden="true">
          {Array.from({ length: 24 }).map((_, index) => (
            <span key={index} />
          ))}
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <p className="eyebrow">ATHENA NODE</p>
          <h2>管理员登录</h2>
          <p className="muted">使用子节点管理员账号继续</p>
          {error && <Alert type="error" showIcon message={error} />}
          <Form layout="vertical" onFinish={submit} requiredMark={false}>
            <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
              <Input prefix={<UserOutlined />} autoComplete="username" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true }]}>
              <Input.Password
                prefix={<LockOutlined />}
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登录
            </Button>
          </Form>
          <p className="login-footnote">安全连接 · 凭据加密存储</p>
        </div>
      </section>
    </main>
  );
}

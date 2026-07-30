import { SafetyCertificateOutlined } from "@ant-design/icons";
import { Card } from "antd";

export function DashboardPage() {
  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">MASTER OVERVIEW</p>
          <h1>系统概览</h1>
          <p>主节点基础服务已就绪，等待接入节点。</p>
        </div>
      </header>
      <Card className="foundation-card">
        <SafetyCertificateOutlined />
        <div>
          <h2>管理入口运行正常</h2>
          <p>数据库、管理员认证和本地开发代理已经启用。</p>
        </div>
      </Card>
    </div>
  );
}

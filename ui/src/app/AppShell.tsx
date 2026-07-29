import {
  AuditOutlined,
  BulbOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  LogoutOutlined,
  MoonOutlined,
  SettingOutlined,
  TeamOutlined
} from "@ant-design/icons";
import { Avatar, Button, Layout, Menu, Space } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/AuthContext";
import { useTheme } from "../styles/ThemeProvider";

const { Sider, Header, Content } = Layout;

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { mode, toggleTheme } = useTheme();
  return (
    <Layout className="app-layout">
      <Sider width={224} className="app-sider">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <strong>Athena</strong>
            <span>NODE CONSOLE</span>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)}
          items={[
            { key: "/", icon: <DashboardOutlined />, label: "节点概览" },
            { key: "/hosts", icon: <CloudServerOutlined />, label: "主机管理" },
            { key: "/terminal", icon: <SettingOutlined />, label: "网页 SSH" },
            { key: "/tasks", icon: <DeploymentUnitOutlined />, label: "当前任务" },
            { key: "/users", icon: <TeamOutlined />, label: "用户管理" },
            { key: "/audit", icon: <AuditOutlined />, label: "审计日志" }
          ]}
        />
        <div className="sider-status">
          <span className="status-dot" />
          <div>
            <strong>子节点在线</strong>
            <small>等待主节点任务</small>
          </div>
        </div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div />
          <Space size={12}>
            <Button
              type="text"
              icon={mode === "dark" ? <BulbOutlined /> : <MoonOutlined />}
              aria-label={mode === "dark" ? "切换到日间模式" : "切换到夜间模式"}
              onClick={toggleTheme}
            />
            <Avatar>{user?.username.slice(0, 1).toUpperCase()}</Avatar>
            <div className="user-summary">
              <strong>{user?.username}</strong>
              <span>管理员</span>
            </div>
            <Button
              type="text"
              icon={<LogoutOutlined />}
              aria-label="退出登录"
              onClick={() => logout()}
            />
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

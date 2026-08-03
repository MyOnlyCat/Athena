import {
  AuditOutlined,
  BulbOutlined,
  ClusterOutlined,
  DashboardOutlined,
  FormOutlined,
  LogoutOutlined,
  MenuOutlined,
  MoonOutlined,
  TeamOutlined
} from "@ant-design/icons";
import { Avatar, Button, Drawer, Layout, Menu, Space } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/AuthContext";
import { useTheme } from "../styles/ThemeContext";

const { Sider, Header, Content } = Layout;

const NAVIGATION_ITEMS = [
  { key: "/", icon: <DashboardOutlined />, label: "系统概览" },
  { key: "/applications", icon: <FormOutlined />, label: "注册申请" },
  { key: "/nodes", icon: <ClusterOutlined />, label: "接入节点" },
  { key: "/administrators", icon: <TeamOutlined />, label: "管理员" },
  { key: "/audit", icon: <AuditOutlined />, label: "审计日志" }
];

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { mode, toggleTheme } = useTheme();
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);

  function navigateFromMobileMenu(path: string) {
    navigate(path);
    setMobileNavigationOpen(false);
  }

  return (
    <>
      <Layout className="app-layout">
        <Sider width={224} className="app-sider">
          <div className="brand">
            <div className="brand-mark">A</div>
            <div>
              <strong>Athena</strong>
              <span>MASTER CONSOLE</span>
            </div>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            onClick={({ key }) => navigate(key)}
            items={NAVIGATION_ITEMS}
          />
          <div className="sider-status">
            <span className="status-dot" />
            <div>
              <strong>主节点在线</strong>
              <small>单进程 · 单实例</small>
            </div>
          </div>
        </Sider>
        <Layout>
          <Header className="app-header">
            <Button
              type="text"
              className="mobile-menu-button"
              icon={<MenuOutlined />}
              aria-label="打开导航菜单"
              aria-expanded={mobileNavigationOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMobileNavigationOpen(true)}
            />
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
      <Drawer
        title="Athena Master 导航"
        placement="left"
        width={280}
        open={mobileNavigationOpen}
        destroyOnHidden
        onClose={() => setMobileNavigationOpen(false)}
      >
        <Menu
          id="mobile-navigation"
          mode="inline"
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigateFromMobileMenu(key)}
          items={NAVIGATION_ITEMS}
        />
      </Drawer>
    </>
  );
}

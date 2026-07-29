import { Spin } from "antd";
import { Navigate, Route, Routes } from "react-router-dom";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { LoginPage } from "../features/auth/LoginPage";
import { useAuth } from "../features/auth/AuthContext";
import { HostsPage } from "../features/hosts/HostsPage";
import { UsersPage } from "../features/users/UsersPage";
import { AppShell } from "./AppShell";

function Placeholder({ title }: { title: string }) {
  return (
    <div className="empty-page">
      <p className="eyebrow">ATHENA NODE</p>
      <h1>{title}</h1>
      <p>该模块正在加载。</p>
    </div>
  );
}

export function AppRouter() {
  const auth = useAuth();
  if (auth.loading) return <Spin fullscreen tip="正在验证登录状态" />;
  if (!auth.user) return <LoginPage onLogin={auth.login} />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="hosts" element={<HostsPage />} />
        <Route path="terminal" element={<Placeholder title="网页 SSH" />} />
        <Route path="tasks" element={<Placeholder title="发布任务" />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="audit" element={<Placeholder title="审计日志" />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

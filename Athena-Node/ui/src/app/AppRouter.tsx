import { Spin } from "antd";
import { Navigate, Route, Routes } from "react-router-dom";

import { AuditPage } from "../features/audit/AuditPage";
import { useAuth } from "../features/auth/AuthContext";
import { LoginPage } from "../features/auth/LoginPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { HostsPage } from "../features/hosts/HostsPage";
import { MasterSettingsPage } from "../features/settings/MasterSettingsPage";
import { TasksPage } from "../features/tasks/TasksPage";
import { TerminalPage } from "../features/terminal/TerminalPage";
import { UsersPage } from "../features/users/UsersPage";
import { AppShell } from "./AppShell";

export function AppRouter() {
  const auth = useAuth();
  if (auth.loading) return <Spin fullscreen tip="正在验证登录状态" />;
  if (!auth.user) return <LoginPage onLogin={auth.login} />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="hosts" element={<HostsPage />} />
        <Route path="terminal" element={<TerminalPage />} />
        <Route path="master-settings" element={<MasterSettingsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="audit" element={<AuditPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

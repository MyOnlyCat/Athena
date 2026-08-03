import { Spin } from "antd";
import { Navigate, Route, Routes } from "react-router-dom";

import { AdministratorsPage } from "../features/administrators/AdministratorsPage";
import { AuditPage } from "../features/audit/AuditPage";
import { useAuth } from "../features/auth/AuthContext";
import { LoginPage } from "../features/auth/LoginPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { NodesPage } from "../features/nodes/NodesPage";
import { RegistrationApplicationsPage } from "../features/registrations/RegistrationApplicationsPage";
import { AppShell } from "./AppShell";

export function AppRouter() {
  const auth = useAuth();
  if (auth.loading) return <Spin fullscreen tip="正在验证登录状态" />;
  if (!auth.user) return <LoginPage onLogin={auth.login} />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="applications" element={<RegistrationApplicationsPage />} />
        <Route path="nodes" element={<NodesPage />} />
        <Route path="administrators" element={<AdministratorsPage />} />
        <Route path="audit" element={<AuditPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

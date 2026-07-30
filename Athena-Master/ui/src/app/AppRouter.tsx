import { Spin } from "antd";
import { Navigate, Route, Routes } from "react-router-dom";

import { AdministratorsPage } from "../features/administrators/AdministratorsPage";
import { useAuth } from "../features/auth/AuthContext";
import { LoginPage } from "../features/auth/LoginPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { FoundationPage } from "../features/foundation/FoundationPage";
import { AppShell } from "./AppShell";

export function AppRouter() {
  const auth = useAuth();
  if (auth.loading) return <Spin fullscreen tip="正在验证登录状态" />;
  if (!auth.user) return <LoginPage onLogin={auth.login} />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route
          path="applications"
          element={
            <FoundationPage
              eyebrow="REGISTRATION APPLICATIONS"
              title="注册申请"
              description="节点接入审批将在后续需求中提供。"
            />
          }
        />
        <Route
          path="nodes"
          element={
            <FoundationPage
              eyebrow="ACCESS NODES"
              title="接入节点"
              description="节点状态与主机资产将在后续需求中提供。"
            />
          }
        />
        <Route path="administrators" element={<AdministratorsPage />} />
        <Route
          path="audit"
          element={
            <FoundationPage
              eyebrow="AUDIT"
              title="审计日志"
              description="操作审计将在后续需求中提供。"
            />
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App, ConfigProvider } from "antd";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { AppRouter } from "./app/AppRouter";
import { AuthProvider } from "./features/auth/AuthContext";
import "./styles/global.css";
import { theme } from "./styles/theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false }
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider theme={theme}>
      <App>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <BrowserRouter>
              <AppRouter />
            </BrowserRouter>
          </AuthProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>
  </StrictMode>
);

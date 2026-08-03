import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { AuditPage } from "../src/features/audit/AuditPage";
import { auditApi } from "../src/shared/api/client";

test("shows the browser time zone used for audit timestamps", () => {
  vi.spyOn(auditApi, "list").mockResolvedValue([]);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AuditPage />
    </QueryClientProvider>
  );

  expect(
    screen.getByText(
      `浏览器时区：${
        Intl.DateTimeFormat().resolvedOptions().timeZone || "浏览器本地时区"
      }`
    )
  ).toBeInTheDocument();
});

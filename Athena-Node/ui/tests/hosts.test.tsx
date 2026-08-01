import { render, screen } from "@testing-library/react";

import { HostTable } from "../src/features/hosts/HostTable";

test("renders current node, address, and connection status", () => {
  render(
    <HostTable
      hosts={[
        {
          id: "host-1",
          name: "node-local",
          address: "10.0.0.10",
          port: 22,
          username: "root",
          tags: ["production"],
          is_local: true,
          has_password: true,
          host_key_fingerprint: "SHA256:trusted",
          last_test_status: "success",
          last_test_code: "SSH_CONNECTED",
          last_test_message: "SSH 连接成功",
          last_tested_at: null,
          created_at: "2026-07-29T00:00:00Z"
        }
      ]}
      loading={false}
      onEdit={() => undefined}
      onDelete={() => undefined}
      onTest={() => undefined}
    />
  );

  expect(screen.getByText("node-local")).toBeInTheDocument();
  expect(screen.getByText("当前节点")).toBeInTheDocument();
  expect(screen.getByText("10.0.0.10:22")).toBeInTheDocument();
  expect(screen.getByText("连接正常")).toBeInTheDocument();
});

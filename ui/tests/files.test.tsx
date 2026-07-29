import { render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { vi } from "vitest";

import { FileManager } from "../src/features/terminal/FileManager";
import { filesApi } from "../src/shared/api/client";

test("renders remote path and file operations", async () => {
  vi.spyOn(filesApi, "list").mockResolvedValue({ path: "/", entries: [] });
  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  expect(screen.getByText("远程文件")).toBeInTheDocument();
  expect(screen.getAllByText("/").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: /上传/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /新建目录/ })).toBeInTheDocument();
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/"));
});

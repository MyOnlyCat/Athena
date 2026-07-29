import { render, screen, waitFor } from "@testing-library/react";
import { App, Modal } from "antd";
import userEvent from "@testing-library/user-event";
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

test("uses the scoped app modal for deletion confirmation", async () => {
  const confirm = vi.fn();
  vi.spyOn(App, "useApp").mockReturnValue({
    message: { error: vi.fn(), success: vi.fn() },
    modal: { confirm },
    notification: {}
  } as never);
  vi.spyOn(Modal, "confirm").mockImplementation(() => ({}) as never);
  vi.spyOn(filesApi, "list").mockResolvedValue({
    path: "/",
    entries: [
      {
        name: "release.tgz",
        path: "/release.tgz",
        type: "file",
        size: 1024,
        modified_at: null,
        permissions: "-rw-r--r--"
      }
    ]
  });
  const user = userEvent.setup();

  render(<FileManager hostId="host-1" />);

  await screen.findByText("release.tgz");
  await user.click(screen.getByRole("button", { name: "delete" }));

  expect(confirm).toHaveBeenCalledWith(
    expect.objectContaining({ title: "删除 release.tgz？", okButtonProps: { danger: true } })
  );
});

import { render, screen, waitFor } from "@testing-library/react";
import { App, Modal } from "antd";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { FileManager } from "../src/features/terminal/FileManager";
import { api, filesApi } from "../src/shared/api/client";

afterEach(() => vi.restoreAllMocks());

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

test("submits a typed path when Enter is pressed", async () => {
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/", entries: [] })
    .mockResolvedValueOnce({ path: "/var/log", entries: [] });
  const user = userEvent.setup();

  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await user.clear(pathInput);
  await user.type(pathInput, "/var/log");
  await user.keyboard("{Enter}");

  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/var/log"));
  expect(pathInput).toHaveValue("/var/log");
});

test("keeps the committed path when a typed path request fails", async () => {
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/", entries: [] })
    .mockRejectedValueOnce(new Error("Path unavailable"));
  const user = userEvent.setup();

  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await user.clear(pathInput);
  await user.type(pathInput, "/var/log");
  await user.keyboard("{Enter}");

  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/var/log"));
  await waitFor(() => expect(pathInput).toHaveValue("/"));
});

test("returns a blob and RFC 5987 filename from a download response", async () => {
  const blob = new Blob(["artifact-content"]);
  vi.spyOn(api, "get").mockResolvedValue({
    data: blob,
    headers: {
      "content-disposition": "attachment; filename=\"fallback.txt\"; filename*=UTF-8''release%20notes.txt"
    }
  } as never);

  await expect(filesApi.download("host-1", "/opt/release/fallback.txt")).resolves.toEqual({
    blob,
    filename: "release notes.txt"
  });
});

test("uses the response filename when downloading a file", async () => {
  vi.spyOn(filesApi, "list").mockResolvedValue({
    path: "/",
    entries: [
      {
        name: "fallback.txt",
        path: "/fallback.txt",
        type: "file",
        size: 1024,
        modified_at: null,
        permissions: "-rw-r--r--"
      }
    ]
  });
  vi.spyOn(filesApi, "download").mockResolvedValue({
    blob: new Blob(["artifact-content"]),
    filename: "release-notes.txt"
  } as never);
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:artifact")
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const anchor = document.createElement("a");
  const click = vi.spyOn(anchor, "click").mockImplementation(() => undefined);
  const user = userEvent.setup();

  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  await screen.findByText("fallback.txt");
  vi.spyOn(document, "createElement").mockReturnValue(anchor as never);
  await user.click(screen.getByRole("button", { name: "download" }));

  await waitFor(() => expect(click).toHaveBeenCalled());
  expect(anchor.download).toBe("release-notes.txt");
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:artifact"));
});

test("reports download failures", async () => {
  const error = vi.fn();
  vi.spyOn(App, "useApp").mockReturnValue({
    message: { error, success: vi.fn() },
    modal: { confirm: vi.fn() },
    notification: {}
  } as never);
  vi.spyOn(filesApi, "list").mockResolvedValue({
    path: "/",
    entries: [
      {
        name: "artifact.txt",
        path: "/artifact.txt",
        type: "file",
        size: 1024,
        modified_at: null,
        permissions: "-rw-r--r--"
      }
    ]
  });
  vi.spyOn(filesApi, "download").mockRejectedValue(new Error("Download unavailable"));
  const user = userEvent.setup();

  render(<FileManager hostId="host-1" />);

  await screen.findByText("artifact.txt");
  await user.click(screen.getByRole("button", { name: "download" }));

  await waitFor(() => expect(error).toHaveBeenCalledWith("Download unavailable"));
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

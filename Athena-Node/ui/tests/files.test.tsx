import { act, render, screen, waitFor } from "@testing-library/react";
import { App, Modal } from "antd";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { FileManager } from "../src/features/terminal/FileManager";
import { api, filesApi } from "../src/shared/api/client";

afterEach(() => vi.restoreAllMocks());

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function waitForListingReady() {
  await waitFor(() => {
    expect(document.querySelector(".file-manager .ant-spin-container")).not.toHaveClass(
      "ant-spin-blur"
    );
  });
}

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

test("rejects a non-absolute remote path before making an API request", async () => {
  const error = vi.fn();
  vi.spyOn(App, "useApp").mockReturnValue({
    message: { error, success: vi.fn() },
    modal: { confirm: vi.fn() },
    notification: {}
  } as never);
  vi.spyOn(filesApi, "list").mockResolvedValue({ path: "/", entries: [] });
  const user = userEvent.setup();

  render(<FileManager hostId="host-1" />);

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledTimes(1));
  await user.clear(pathInput);
  await user.type(pathInput, "var/log");
  await user.keyboard("{Enter}");

  expect(filesApi.list).toHaveBeenCalledTimes(1);
  expect(error).toHaveBeenCalledWith("远程路径必须是绝对路径");
  expect(pathInput).toHaveValue("var/log");
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
  expect(api.get).toHaveBeenCalledWith(
    "/files/host-1/download",
    expect.objectContaining({
      params: { path: "/opt/release/fallback.txt" },
      responseType: "blob",
      timeout: 0
    })
  );
});

test("uploads without a total-duration timeout while preserving AbortSignal cancellation", async () => {
  const controller = new AbortController();
  const onProgress = vi.fn();
  const artifact = new File(["artifact"], "artifact.jar");
  vi.spyOn(api, "post").mockResolvedValue({} as never);

  await filesApi.upload("host-1", "/opt/artifact.jar", artifact, {
    signal: controller.signal,
    onProgress
  });

  expect(api.post).toHaveBeenCalledWith(
    "/files/host-1/upload",
    artifact,
    expect.objectContaining({
      params: { path: "/opt/artifact.jar" },
      signal: controller.signal,
      onUploadProgress: onProgress,
      timeout: 0
    })
  );
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
  await waitForListingReady();
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
  await waitForListingReady();
  await user.click(screen.getByRole("button", { name: "download" }));

  await waitFor(() => expect(error).toHaveBeenCalledWith("Download unavailable"));
});

test("ignores a stale successful path listing", async () => {
  const first = deferred<{ path: string; entries: never[] }>();
  const second = deferred<{
    path: string;
    entries: [
      {
        name: string;
        path: string;
        type: "file";
        size: number;
        modified_at: null;
        permissions: string;
      }
    ];
  }>();
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/", entries: [] })
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const user = userEvent.setup();

  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await user.clear(pathInput);
  await user.type(pathInput, "/a");
  await user.keyboard("{Enter}");
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/a"));
  await user.clear(pathInput);
  await user.type(pathInput, "/b");
  await user.keyboard("{Enter}");
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/b"));

  await act(async () => {
    second.resolve({
      path: "/b",
      entries: [
        {
          name: "latest.txt",
          path: "/b/latest.txt",
          type: "file",
          size: 1,
          modified_at: null,
          permissions: "-rw-r--r--"
        }
      ]
    });
    await second.promise;
  });
  await screen.findByText("latest.txt");
  await act(async () => {
    first.resolve({ path: "/a", entries: [] });
    await first.promise;
  });

  expect(pathInput).toHaveValue("/b");
  expect(screen.queryByText("latest.txt")).toBeInTheDocument();
});

test("does not roll back a newer path when a stale listing fails", async () => {
  const first = deferred<{ path: string; entries: never[] }>();
  const second = deferred<{ path: string; entries: never[] }>();
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/", entries: [] })
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const user = userEvent.setup();

  render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await user.clear(pathInput);
  await user.type(pathInput, "/a");
  await user.keyboard("{Enter}");
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/a"));
  await user.clear(pathInput);
  await user.type(pathInput, "/b");
  await user.keyboard("{Enter}");
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledWith("host-1", "/b"));

  await act(async () => {
    second.resolve({ path: "/b", entries: [] });
    await second.promise;
  });
  expect(pathInput).toHaveValue("/b");
  await act(async () => {
    first.reject(new Error("Path unavailable"));
    await first.promise.catch(() => undefined);
  });

  expect(pathInput).toHaveValue("/b");
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
  await waitForListingReady();
  await user.click(screen.getByRole("button", { name: "delete" }));

  expect(confirm).toHaveBeenCalledWith(
    expect.objectContaining({ title: "删除 release.tgz？", okButtonProps: { danger: true } })
  );
});

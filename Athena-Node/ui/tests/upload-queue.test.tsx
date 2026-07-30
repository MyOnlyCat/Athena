import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { FileManager } from "../src/features/terminal/FileManager";
import { useUploadQueue } from "../src/features/terminal/useUploadQueue";
import { filesApi } from "../src/shared/api/client";

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

function file(name: string, size = 100) {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

test("starts no more than three uploads, reports per-file progress, and continues after failure", async () => {
  const uploads = Array.from({ length: 5 }, () => deferred<unknown>());
  const options: Array<{
    signal: AbortSignal;
    onProgress: (event: { loaded: number; total?: number }) => void;
  }> = [];
  vi.spyOn(filesApi, "upload").mockImplementation(
    (_hostId, _path, _file, uploadOptions) => {
      options.push(uploadOptions);
      return uploads[options.length - 1].promise as never;
    }
  );
  const completed = vi.fn();
  const { result } = renderHook(() => useUploadQueue("host-1", completed));

  act(() => {
    result.current.enqueue(
      [file("one.bin"), file("two.bin"), file("three.bin"), file("four.bin"), file("five.bin")],
      "/releases"
    );
  });

  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(3));
  expect(result.current.tasks).toHaveLength(5);
  expect(filesApi.upload).toHaveBeenNthCalledWith(
    1,
    "host-1",
    "/releases/one.bin",
    expect.any(File),
    expect.objectContaining({ signal: expect.any(AbortSignal) })
  );

  act(() => options[1].onProgress({ loaded: 40, total: 100 }));
  expect(result.current.tasks.find((task) => task.file.name === "two.bin")).toMatchObject({
    loaded: 40,
    total: 100,
    status: "uploading"
  });
  expect(result.current.tasks.find((task) => task.file.name === "one.bin")?.loaded).toBe(0);

  await act(async () => {
    uploads[0].reject(new Error("disk full"));
    await uploads[0].promise.catch(() => undefined);
  });
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(4));
  expect(result.current.tasks.find((task) => task.file.name === "one.bin")).toMatchObject({
    status: "failed",
    error: "disk full"
  });

  await act(async () => {
    uploads[1].resolve({});
    await uploads[1].promise;
  });
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(5));
  expect(result.current.tasks.find((task) => task.file.name === "two.bin")?.status).toBe(
    "completed"
  );
  expect(completed).not.toHaveBeenCalled();
});

test("coalesces all successful completions in one enqueue batch into one refresh", async () => {
  const uploads = [deferred<unknown>(), deferred<unknown>(), deferred<unknown>()];
  vi.spyOn(filesApi, "upload")
    .mockReturnValueOnce(uploads[0].promise as never)
    .mockReturnValueOnce(uploads[1].promise as never)
    .mockReturnValueOnce(uploads[2].promise as never);
  const completed = vi.fn();
  const { result } = renderHook(() => useUploadQueue("host-1", completed));

  act(() => result.current.enqueue(
    [file("one.bin"), file("two.bin"), file("three.bin")],
    "/releases"
  ));
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(3));

  await act(async () => {
    uploads[0].resolve({});
    await uploads[0].promise;
  });
  await act(async () => {
    uploads[1].resolve({});
    await uploads[1].promise;
  });
  expect(completed).not.toHaveBeenCalled();

  await act(async () => {
    uploads[2].resolve({});
    await uploads[2].promise;
  });
  await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
});

test("cancels one active upload and all queued work independently", async () => {
  const signals: AbortSignal[] = [];
  vi.spyOn(filesApi, "upload").mockImplementation(
    (_hostId, _path, _file, { signal }) => {
      signals.push(signal);
      return new Promise(() => undefined) as never;
    }
  );
  const { result } = renderHook(() => useUploadQueue("host-1", vi.fn()));

  act(() => {
    result.current.enqueue(
      [file("one.bin"), file("two.bin"), file("three.bin"), file("four.bin")],
      "/tmp"
    );
  });
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(3));

  const firstId = result.current.tasks[0].id;
  act(() => result.current.cancel(firstId));
  expect(signals[0].aborted).toBe(true);
  expect(result.current.tasks[0].status).toBe("cancelled");

  act(() => result.current.cancelAll());
  expect(result.current.tasks.every((task) => task.status === "cancelled")).toBe(true);
  expect(signals.every((signal) => signal.aborted)).toBe(true);
});

test("host changes abort active requests and cancel active plus queued tasks", async () => {
  const signals: AbortSignal[] = [];
  vi.spyOn(filesApi, "upload").mockImplementation(
    (_hostId, _path, _file, { signal }) => {
      signals.push(signal);
      return new Promise(() => undefined) as never;
    }
  );
  const { result, rerender } = renderHook(
    ({ hostId }) => useUploadQueue(hostId, vi.fn()),
    { initialProps: { hostId: "host-1" } }
  );

  act(() => {
    result.current.enqueue(
      [file("one.bin"), file("two.bin"), file("three.bin"), file("four.bin"), file("five.bin")],
      "/tmp"
    );
  });
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(3));

  rerender({ hostId: "host-2" });

  await waitFor(() =>
    expect(result.current.tasks.every((task) => task.status === "cancelled")).toBe(true)
  );
  expect(signals).toHaveLength(3);
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  expect(filesApi.upload).toHaveBeenCalledTimes(3);
});

test("unmount aborts requests and ignores their later progress and settlement", async () => {
  const uploads = Array.from({ length: 3 }, () => deferred<unknown>());
  const options: Array<{
    signal: AbortSignal;
    onProgress: (event: { loaded: number; total?: number }) => void;
  }> = [];
  vi.spyOn(filesApi, "upload").mockImplementation(
    (_hostId, _path, _file, uploadOptions) => {
      options.push(uploadOptions);
      return uploads[options.length - 1].promise as never;
    }
  );
  const completed = vi.fn();
  const { result, unmount } = renderHook(() => useUploadQueue("host-1", completed));

  act(() => result.current.enqueue([file("one.bin"), file("two.bin"), file("three.bin")], "/"));
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(3));
  unmount();

  expect(options.every(({ signal }) => signal.aborted)).toBe(true);
  await act(async () => {
    options[0].onProgress({ loaded: 100, total: 100 });
    uploads.forEach((upload) => upload.resolve({}));
    await Promise.all(uploads.map((upload) => upload.promise));
  });
  expect(completed).not.toHaveBeenCalled();
});

test("continues tracking uploads after StrictMode replays mount effects", async () => {
  const upload = deferred<unknown>();
  const options: Array<{
    signal: AbortSignal;
    onProgress: (event: { loaded: number; total?: number }) => void;
  }> = [];
  vi.spyOn(filesApi, "upload").mockImplementation(
    (_hostId, _path, _file, uploadOptions) => {
      options.push(uploadOptions);
      return upload.promise as never;
    }
  );
  const { result } = renderHook(() => useUploadQueue("host-1", vi.fn()), {
    reactStrictMode: true
  });

  act(() => result.current.enqueue([file("strict.bin")], "/tmp"));
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(1));
  act(() => options[0].onProgress({ loaded: 50, total: 100 }));
  expect(result.current.tasks[0].loaded).toBe(50);

  await act(async () => {
    upload.resolve({});
    await upload.promise;
  });
  await waitFor(() => expect(result.current.tasks[0].status).toBe("completed"));
});

test("reports a completed zero-byte upload as 100 percent", async () => {
  vi.spyOn(filesApi, "upload").mockResolvedValue({} as never);
  const { result } = renderHook(() => useUploadQueue("host-1", vi.fn()));

  act(() => result.current.enqueue([file("empty.txt", 0)], "/tmp"));

  await waitFor(() => expect(result.current.tasks[0].status).toBe("completed"));
  expect(result.current.summary.percent).toBe(100);
});

test("file selection snapshots the committed directory, accepts multiple files, and clears input", async () => {
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/releases", entries: [] })
    .mockResolvedValue({ path: "/other", entries: [] });
  const uploadOne = deferred<unknown>();
  const uploadTwo = deferred<unknown>();
  vi.spyOn(filesApi, "upload")
    .mockReturnValueOnce(uploadOne.promise as never)
    .mockReturnValueOnce(uploadTwo.promise as never);
  const user = userEvent.setup();
  const { container } = render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await waitFor(() => expect(pathInput).toHaveValue("/releases"));
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).toHaveAttribute("multiple");
  await user.upload(input!, [file("one.bin"), file("two.bin")]);

  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(2));
  expect(filesApi.upload).toHaveBeenNthCalledWith(
    1,
    "host-1",
    "/releases/one.bin",
    expect.any(File),
    expect.any(Object)
  );
  expect(filesApi.upload).toHaveBeenNthCalledWith(
    2,
    "host-1",
    "/releases/two.bin",
    expect.any(File),
    expect.any(Object)
  );
  expect(input).toHaveValue("");

  await user.clear(pathInput);
  await user.type(pathInput, "/other");
  await user.keyboard("{Enter}");
  await act(async () => {
    uploadOne.resolve({});
    uploadTwo.resolve({});
    await Promise.all([uploadOne.promise, uploadTwo.promise]);
  });
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledTimes(3));
  expect(filesApi.list).toHaveBeenLastCalledWith("host-1", "/other");
});

test("defers an upload refresh until pending navigation commits and refreshes that directory", async () => {
  const navigation = deferred<{ path: string; entries: never[] }>();
  const refresh = deferred<{ path: string; entries: never[] }>();
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/releases", entries: [] })
    .mockReturnValueOnce(navigation.promise)
    .mockReturnValueOnce(refresh.promise);
  const upload = deferred<unknown>();
  vi.spyOn(filesApi, "upload").mockReturnValue(upload.promise as never);
  const user = userEvent.setup();
  const { container } = render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await waitFor(() => expect(pathInput).toHaveValue("/releases"));
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  await user.upload(input!, file("release.bin"));
  await waitFor(() => expect(filesApi.upload).toHaveBeenCalledTimes(1));

  await user.clear(pathInput);
  await user.type(pathInput, "/var/log");
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(filesApi.list).toHaveBeenNthCalledWith(2, "host-1", "/var/log")
  );

  await act(async () => {
    upload.resolve({});
    await upload.promise;
  });
  expect(filesApi.list).toHaveBeenCalledTimes(2);

  await act(async () => {
    navigation.resolve({ path: "/var/log", entries: [] });
    await navigation.promise;
  });
  await waitFor(() =>
    expect(filesApi.list).toHaveBeenNthCalledWith(3, "host-1", "/var/log")
  );
  await act(async () => {
    refresh.resolve({ path: "/var/log", entries: [] });
    await refresh.promise;
  });

  expect(pathInput).toHaveValue("/var/log");
});

test("invalidates a successful upload refresh when the host changes before listing settles", async () => {
  const refresh = deferred<{ path: string; entries: never[] }>();
  vi.spyOn(filesApi, "list")
    .mockResolvedValueOnce({ path: "/releases", entries: [] })
    .mockReturnValueOnce(refresh.promise);
  vi.spyOn(filesApi, "upload").mockResolvedValue({} as never);
  const user = userEvent.setup();
  const { container, rerender } = render(
    <App>
      <FileManager hostId="host-1" />
    </App>
  );

  const pathInput = await screen.findByRole("textbox", { name: "Remote path" });
  await waitFor(() => expect(pathInput).toHaveValue("/releases"));
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  await user.upload(input!, file("release.bin"));
  await waitFor(() => expect(filesApi.list).toHaveBeenCalledTimes(2));

  rerender(
    <App>
      <FileManager hostId="" />
    </App>
  );
  await act(async () => {
    refresh.resolve({ path: "/stale-host", entries: [] });
    await refresh.promise;
  });

  expect(pathInput).toHaveValue("/releases");
});

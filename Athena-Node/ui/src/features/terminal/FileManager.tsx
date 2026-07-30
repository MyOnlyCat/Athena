import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  ProfileOutlined,
  ReloadOutlined,
  UploadOutlined
} from "@ant-design/icons";
import { App, Badge, Breadcrumb, Button, Drawer, Input, Space, Spin, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";

import { apiMessage, filesApi } from "../../shared/api/client";
import type { FileEntry } from "../../shared/api/types";
import { UploadTasks } from "./UploadTasks";
import { useUploadQueue } from "./useUploadQueue";

function formatFileSize(size: number): string {
  if (size <= 0) return "0.00 MB";
  return `${Math.max(size / (1024 * 1024), 0.01).toFixed(2)} MB`;
}

function breadcrumbItems(path: string, navigate: (path: string) => void) {
  const segments = path.split("/").filter(Boolean);
  return [
    {
      title: (
        <button
          aria-label="跳转到根目录"
          className="path-breadcrumb-link mono"
          type="button"
          onClick={() => navigate("/")}
        >
          /
        </button>
      )
    },
    ...segments.map((segment, index) => {
      const target = `/${segments.slice(0, index + 1).join("/")}`;
      return {
        title: (
          <button
            aria-label={`跳转到 ${target}`}
            className="path-breadcrumb-link mono"
            type="button"
            onClick={() => navigate(target)}
          >
            {segment}
          </button>
        )
      };
    })
  ];
}

export function FileManager({ hostId }: { hostId: string }) {
  const { message, modal } = App.useApp();
  const [path, setPath] = useState("/");
  const [pathDraft, setPathDraft] = useState("/");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadTasksOpen, setUploadTasksOpen] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const listRequestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const pathRef = useRef("/");
  const navigationPendingRef = useRef(false);
  const refreshInFlightRef = useRef(false);
  const refreshPendingRef = useRef(false);

  function commitListing(result: { path: string; entries: FileEntry[] }) {
    pathRef.current = result.path;
    setPath(result.path);
    setPathDraft(result.path);
    setEntries(result.entries);
  }

  async function navigate(nextPath: string) {
    if (!hostId || !mountedRef.current) return;
    if (!nextPath.startsWith("/")) {
      message.error("远程路径必须是绝对路径");
      return;
    }
    const requestId = ++listRequestIdRef.current;
    navigationPendingRef.current = true;
    setLoading(true);
    try {
      const result = await filesApi.list(hostId, nextPath);
      if (!mountedRef.current || requestId !== listRequestIdRef.current) return;
      commitListing(result);
    } catch (error) {
      if (!mountedRef.current || requestId !== listRequestIdRef.current) return;
      setPathDraft(pathRef.current);
      message.error(apiMessage(error));
    } finally {
      if (mountedRef.current && requestId === listRequestIdRef.current) {
        navigationPendingRef.current = false;
        setLoading(false);
        if (refreshPendingRef.current) {
          refreshPendingRef.current = false;
          void refreshCurrent();
        }
      }
    }
  }

  async function refreshCurrent() {
    if (!hostId || !mountedRef.current) return;
    if (navigationPendingRef.current || refreshInFlightRef.current) {
      refreshPendingRef.current = true;
      return;
    }

    refreshInFlightRef.current = true;
    const requestId = ++listRequestIdRef.current;
    setLoading(true);
    try {
      const result = await filesApi.list(hostId, pathRef.current);
      if (!mountedRef.current || requestId !== listRequestIdRef.current) return;
      commitListing(result);
    } catch (error) {
      if (!mountedRef.current || requestId !== listRequestIdRef.current) return;
      message.error(apiMessage(error));
    } finally {
      refreshInFlightRef.current = false;
      if (mountedRef.current && requestId === listRequestIdRef.current) {
        setLoading(false);
      }
      if (
        mountedRef.current &&
        refreshPendingRef.current &&
        !navigationPendingRef.current
      ) {
        refreshPendingRef.current = false;
        void refreshCurrent();
      }
    }
  }

  const uploadQueue = useUploadQueue(hostId, () => {
    void refreshCurrent();
  });

  useEffect(() => {
    mountedRef.current = true;
    pathRef.current = "/";
    navigationPendingRef.current = false;
    refreshInFlightRef.current = false;
    refreshPendingRef.current = false;
    void navigate("/");
    return () => {
      mountedRef.current = false;
      listRequestIdRef.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId]);

  function createDirectory() {
    let name = "";
    modal.confirm({
      title: "新建目录",
      content: <Input onChange={(event) => (name = event.target.value)} />,
      onOk: async () => {
        await filesApi.mkdir(hostId, `${path.replace(/\/$/, "")}/${name}`);
        await refreshCurrent();
      }
    });
  }

  async function download(entry: FileEntry) {
    try {
      const { blob, filename } = await filesApi.download(hostId, entry.path);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      message.error(apiMessage(error));
    }
  }

  function rename(entry: FileEntry) {
    let name = entry.name;
    modal.confirm({
      title: `重命名 ${entry.name}`,
      content: (
        <Input
          defaultValue={entry.name}
          onChange={(event) => (name = event.target.value)}
        />
      ),
      onOk: async () => {
        const parent = entry.path.slice(0, entry.path.lastIndexOf("/")) || "/";
        await filesApi.rename(hostId, entry.path, `${parent}/${name}`);
        await refreshCurrent();
      }
    });
  }

  function remove(entry: FileEntry) {
    modal.confirm({
      title: `删除 ${entry.name}？`,
      content:
        entry.type === "directory" ? "目录及其中内容将被递归删除。" : "此操作无法撤销。",
      okButtonProps: { danger: true },
      onOk: async () => {
        await filesApi.remove(hostId, entry.path, entry.type === "directory");
        await refreshCurrent();
      }
    });
  }

  return (
    <aside className="file-manager">
      <div className="terminal-pane-heading">
        <div className="file-heading-content">
          <strong>远程文件</strong>
          <Breadcrumb
            className="path-breadcrumb"
            items={breadcrumbItems(path, (target) => void navigate(target))}
          />
        </div>
        <Tooltip title="刷新">
          <Button
            type="text"
            icon={<ReloadOutlined />}
            onClick={() => void refreshCurrent()}
          />
        </Tooltip>
      </div>
      <div className="file-actions">
        <Button
          size="small"
          icon={<UploadOutlined />}
          onClick={() => uploadRef.current?.click()}
        >
          上传
        </Button>
        <Button size="small" icon={<FolderAddOutlined />} onClick={createDirectory}>
          新建目录
        </Button>
        <Badge
          count={uploadQueue.summary.queued + uploadQueue.summary.uploading}
          size="small"
          overflowCount={99}
        >
          <Button
            size="small"
            icon={<ProfileOutlined />}
            onClick={() => setUploadTasksOpen(true)}
          >
            任务
          </Button>
        </Badge>
        <input
          hidden
          multiple
          ref={uploadRef}
          type="file"
          onChange={(event) => {
            const selected = Array.from(event.currentTarget.files ?? []);
            if (selected.length) {
              uploadQueue.enqueue(selected, path);
              setUploadTasksOpen(true);
            }
            event.currentTarget.value = "";
          }}
        />
      </div>
      <Input
        aria-label="Remote path"
        className="path-bar mono"
        value={pathDraft}
        onChange={(event) => setPathDraft(event.target.value)}
        onPressEnter={() => void navigate(pathDraft)}
      />
      <Spin wrapperClassName="file-list-loading" spinning={loading}>
        <div className="file-list">
          {path !== "/" && (
            <button
              type="button"
              className="file-row"
              onDoubleClick={() =>
                void navigate(path.slice(0, path.lastIndexOf("/")) || "/")
              }
            >
              <FolderOpenOutlined /> <span>..</span>
            </button>
          )}
          {entries.map((entry) => (
            <div
              className="file-row"
              key={entry.path}
              onDoubleClick={() =>
                entry.type === "directory" && void navigate(entry.path)
              }
            >
              {entry.type === "directory" ? <FolderOpenOutlined /> : <FileOutlined />}
              <span title={entry.name}>{entry.name}</span>
              <small>
                {entry.type === "file" ? formatFileSize(entry.size) : ""}
              </small>
              <Space size={2} className="file-row-actions">
                {entry.type === "file" && (
                  <Button
                    type="text"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={() => void download(entry)}
                  />
                )}
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => rename(entry)}
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => remove(entry)}
                />
              </Space>
            </div>
          ))}
          {!loading && !entries.length && <div className="terminal-empty">目录为空</div>}
        </div>
      </Spin>
      <Drawer
        title="上传任务"
        placement="right"
        width={420}
        open={uploadTasksOpen}
        onClose={() => setUploadTasksOpen(false)}
      >
        <UploadTasks
          tasks={uploadQueue.tasks}
          summary={uploadQueue.summary}
          onCancel={uploadQueue.cancel}
          onCancelAll={uploadQueue.cancelAll}
          onClearSettled={uploadQueue.clearSettled}
        />
      </Drawer>
    </aside>
  );
}

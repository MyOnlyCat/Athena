import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  UploadOutlined
} from "@ant-design/icons";
import { App, Button, Input, Modal, Space, Spin, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";

import { apiMessage, filesApi } from "../../shared/api/client";
import type { FileEntry } from "../../shared/api/types";

export function FileManager({ hostId }: { hostId: string }) {
  const { message, modal } = App.useApp();
  const [path, setPath] = useState("/");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  async function load(nextPath = path) {
    if (!hostId) return;
    setLoading(true);
    try {
      const result = await filesApi.list(hostId, nextPath);
      setPath(result.path);
      setEntries(result.entries);
    } catch (error) {
      message.error(apiMessage(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("/");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId]);

  function createDirectory() {
    let name = "";
    modal.confirm({
      title: "新建目录",
      content: <Input onChange={(event) => (name = event.target.value)} />,
      onOk: async () => {
        await filesApi.mkdir(hostId, `${path.replace(/\/$/, "")}/${name}`);
        await load();
      }
    });
  }

  async function download(entry: FileEntry) {
    const response = await filesApi.download(hostId, entry.path);
    const url = URL.createObjectURL(response.data);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = entry.name;
    anchor.click();
    URL.revokeObjectURL(url);
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
        await load();
      }
    });
  }

  function remove(entry: FileEntry) {
    Modal.confirm({
      title: `删除 ${entry.name}？`,
      content:
        entry.type === "directory" ? "目录及其中内容将被递归删除。" : "此操作无法撤销。",
      okButtonProps: { danger: true },
      onOk: async () => {
        await filesApi.remove(hostId, entry.path, entry.type === "directory");
        await load();
      }
    });
  }

  async function upload(file: File) {
    try {
      await filesApi.upload(hostId, `${path.replace(/\/$/, "")}/${file.name}`, file);
      message.success("文件上传完成");
      await load();
    } catch (error) {
      message.error(apiMessage(error));
    }
  }

  return (
    <aside className="file-manager">
      <div className="terminal-pane-heading">
        <div>
          <strong>远程文件</strong>
          <span className="mono">{path}</span>
        </div>
        <Tooltip title="刷新">
          <Button type="text" icon={<ReloadOutlined />} onClick={() => load()} />
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
        <input
          hidden
          ref={uploadRef}
          type="file"
          onChange={(event) =>
            event.target.files?.[0] && void upload(event.target.files[0])
          }
        />
      </div>
      <button
        type="button"
        className="path-bar mono"
        onClick={() => path !== "/" && void load("/")}
      >
        {path}
      </button>
      <Spin spinning={loading}>
        <div className="file-list">
          {path !== "/" && (
            <button
              type="button"
              className="file-row"
              onDoubleClick={() => load(path.slice(0, path.lastIndexOf("/")) || "/")}
            >
              <FolderOpenOutlined /> <span>..</span>
            </button>
          )}
          {entries.map((entry) => (
            <div
              className="file-row"
              key={entry.path}
              onDoubleClick={() => entry.type === "directory" && void load(entry.path)}
            >
              {entry.type === "directory" ? <FolderOpenOutlined /> : <FileOutlined />}
              <span title={entry.name}>{entry.name}</span>
              <small>{entry.type === "file" ? `${Math.ceil(entry.size / 1024)} KB` : ""}</small>
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
    </aside>
  );
}

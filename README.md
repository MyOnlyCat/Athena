# Athena-Node（雅典娜子节点）

Athena-Node 是部署在目标网络中的轻量子节点。它管理本节点可访问的 SSH
主机，提供网页终端和 SFTP 文件管理，并从 Athena 主节点领取制品发布任务。

## 已交付能力

- 管理员认证、用户管理和审计。
- SSH 主机、加密凭据、连接测试及 TOFU 指纹确认。
- 基于 xterm.js 的二进制网页终端；进入 `/terminal` 时默认使用应用内全屏布局。
- 远程路径跳转、新建目录、重命名、删除、下载及最多三个文件并发上传。
- 在 `/master-settings` 测试、保存并即时应用主节点连接，不需要重启 API。
- HMAC 签名心跳、任务领取、制品校验、受控并发发布及事件回传。

## 快速启动

1. 复制 `.env.example` 为 `.env`。
2. 生成 Fernet 密钥：
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. 设置随机的 `ATHENA_JWT_SECRET`、`ATHENA_CREDENTIAL_KEY` 和管理员密码。
4. 可选：设置初始 `ATHENA_MASTER_NODE_URL` 与 `ATHENA_NODE_TOKEN`。
5. 执行 `docker compose up -d --build`。
6. 访问 `http://服务器地址:8080`。

首次启动会用环境变量中的管理员信息创建账号；已存在账号不会被覆盖。业务数据和
下载制品保存在 Docker 命名卷 `athena_data` 中。

### 主节点配置优先级

`ATHENA_MASTER_NODE_URL` 与 `ATHENA_NODE_TOKEN` 只提供尚未保存数据库配置时的
启动默认值。一旦在“主节点配置”页面成功保存，数据库中的 `scheme`、`host`、
`port` 和加密 Token 在后续启动时整体优先于环境变量。

读取配置时 API 从不返回 Token，只返回 `has_token`。表单中的 Token 留空会复用
当前有效 Token；“连接测试”不会保存或应用设置，“保存并应用”会先测试候选连接，
成功提交数据库后再替换正在运行的主节点客户端、资产同步器和任务执行器。测试或
提交失败时保留旧配置与旧运行时。

## 本地开发

后端需要 Python 3.12，前端需要 Node.js 22：

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
$env:ATHENA_JWT_SECRET="development-secret-at-least-32-characters"
$env:ATHENA_CREDENTIAL_KEY="<44 字符 Fernet 密钥>"
$env:ATHENA_BOOTSTRAP_USERNAME="admin"
$env:ATHENA_BOOTSTRAP_PASSWORD="change-me-now"
.\.venv\Scripts\uvicorn app.main:create_app --factory --reload
```

```powershell
cd ui
npm ci
npm run dev
```

Vite 默认运行于 `http://localhost:5173`，并将 HTTP 与 WebSocket `/api`
请求代理到 `http://127.0.0.1:8000`。登录后可访问 `/`、`/hosts`、
`/terminal`、`/master-settings`、`/tasks`、`/users` 和 `/audit`。

## 操作提示

- 只有已确认 SSH 指纹的主机才出现在网页终端服务器列表中。
- 切换主机会先确认并关闭当前 SSH 会话；离开终端页面也会关闭 WebSocket。
- 文件选择时会固定当时的目标目录。每次最多并发上传三个文件，其他文件排队；
  可取消单项或全部任务。切换主机或离开页面会中止未完成上传。
- 下载使用服务端 `Content-Disposition` 文件名并由浏览器保存；详情与中断后的
  远端文件处理见[文件传输指南](docs/file-transfers.md)。

## 文档

- [本地 API](docs/api/local-api.md)
- [WebSocket 协议](docs/api/websocket-protocol.md)
- [主节点协议](docs/api/master-node-protocol.md)
- [文件传输指南](docs/file-transfers.md)
- [OpenAPI JSON](docs/api/openapi.json)
- [统一样式规范](docs/style-guide.md)
- [任务清单](TASKS.md)
- [更新日志](CHANGELOG.md)

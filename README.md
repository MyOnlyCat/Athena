# Athena

Athena 是面向多网络环境的主从节点运维与发布平台。本仓库采用单仓库结构，统一管理
Athena-Node、Athena-Master、部署入口和项目文档。

## 当前状态

- **Athena-Node：部分完成。** 已具备管理员认证、SSH 主机管理、网页终端、SFTP
  文件管理、审计、主节点连接配置和发布任务执行等基础能力，仍需在真实部署环境中
  完成 SSH/生产部署验收与后续迭代；Node–Master 第一阶段协议已有跨进程自动化集成
  验收。
- **Athena-Master：基础应用、注册生命周期和认证心跳已完成。** 已具备可迁移的 SQLite
  数据库、初始化管理员登录、管理员账号维护、两阶段 Node 注册审批、注册生命周期保护、
  基于原始字节的 HMAC 心跳认证、持久 nonce 防重放、原子主机资产快照、接入节点与
  资产查询、节点生命周期与 Token 轮换、聚合健康概览、安全敏感操作审计、健康检查、
  中文管理界面和 Windows 本地启动入口。第一阶段按单 Master 最多 100 个接入节点、
  单进程/单 worker/本地 SQLite 的边界验收。

## 仓库结构

```text
Athena/
├── Athena-Node/       # 已部分完成的子节点
│   ├── api/           # FastAPI 后端
│   ├── ui/            # React 管理界面
│   └── deploy/        # Nginx 配置
├── Athena-Master/     # 主节点 API、管理界面与本地启动入口
├── docs/              # 统一文档、协议、设计和实施计划
├── compose.yaml       # 当前 Athena-Node 部署入口
├── .env.example
├── TASKS.md
└── CHANGELOG.md
```

## Athena-Node 已有能力

- 管理员认证、用户管理和操作审计。
- SSH 主机、加密凭据、连接测试和 TOFU 指纹确认。
- 基于 xterm.js 的二进制网页终端和应用内全屏。
- 远程路径导航、新建、重命名、删除、下载和三文件并发上传。
- 主节点连接测试、加密保存和运行时即时替换。
- HMAC 签名心跳、任务领取、制品校验、受控并发发布和事件回传。

## 使用 Docker Compose

环境要求：Docker 和 Docker Compose。

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少替换以下值：

- `ATHENA_JWT_SECRET`：不少于 32 字符的随机值。
- `ATHENA_CREDENTIAL_KEY`：有效的 Fernet 密钥。
- `ATHENA_BOOTSTRAP_PASSWORD`：高强度管理员密码。

然后启动当前可用的 Athena-Node：

```powershell
docker compose up -d --build
```

默认访问地址为 `http://服务器地址:8080`。首次启动会创建管理员账号；已有账号不会
被覆盖。业务数据和下载制品保存在 Docker 命名卷 `athena_data` 中。

> `compose.yaml` 当前不包含 Athena-Master 服务；Master 第一阶段使用独立的 Windows
> 本地启动入口。

## 本地开发

后端需要 Python 3.12，前端需要 Node.js 22。Windows 开发环境可以双击：

```text
Athena-Node\ui\start-dev.cmd
```

也可以分别启动：

```powershell
cd Athena-Node\api
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
```

配置必要的 `ATHENA_*` 环境变量后运行：

```powershell
.\.venv\Scripts\uvicorn app.main:create_app --factory --reload
```

前端：

```powershell
cd Athena-Node\ui
npm ci
npm run dev
```

Master 可直接运行：

```powershell
Athena-Master\ui\start-dev.cmd
```

Master API 和 UI 默认使用 `127.0.0.1:8001` 与 `127.0.0.1:5174`。其目录结构与 Node
保持一致，但两个应用独立安装、独立迁移且不互相导入内部模块。

## 文档

- [Athena-Node 组件说明](Athena-Node/README.md)
- [Athena-Master 状态说明](Athena-Master/README.md)
- [本地 API](docs/api/local-api.md)
- [WebSocket 协议](docs/api/websocket-protocol.md)
- [主从节点协议](docs/api/master-node-protocol.md)
- [OpenAPI JSON](docs/api/openapi.json)
- [文件传输指南](docs/node/file-transfers.md)
- [统一样式规范](docs/node/style-guide.md)
- [任务清单](TASKS.md)
- [更新日志](CHANGELOG.md)

## Git 历史

本仓库保留了 Athena-Node 的既有提交历史。Athena-Node 已从独立嵌套仓库迁入
Athena 单仓库；原 `MyOnlyCat/Athena-Nod` 仓库不被删除或强制更新，仅作为历史
备份保留。

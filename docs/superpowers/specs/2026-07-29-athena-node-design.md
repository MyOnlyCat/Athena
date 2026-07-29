# Athena-Node 子节点系统设计

**日期：** 2026-07-29  
**状态：** 已确认，待书面审阅  
**适用目录：** `ui/`、`api/`

## 1. 目标与范围

Athena-Node 是部署在受管网络中的雅典娜子节点。它保存当前节点可访问主机的 SSH 信息，提供管理员登录、主机管理、连接测试、网页 SSH 和远程文件管理，并作为执行代理从雅典娜主节点领取制品发布任务。

首版包含：

- 管理员创建用户、禁用或启用用户、重置密码、用户登录和退出。
- 使用用户名和密码管理 SSH 主机，包括当前节点自身。
- 测试 SSH 连接并保留服务器主机密钥指纹。
- 三栏式网页 SSH：左侧服务器切换，中间终端，右侧文件目录。
- 通过 SFTP 浏览、上传、下载、新建、重命名和删除远程文件。
- 启动和主机变化时向雅典娜主节点汇报完整节点状态。
- 每 60 秒从主节点领取发布任务，下载并校验制品，在指定机器和目录执行指定命令。
- 实时回传发布进度、日志和最终结果。
- 使用 Docker Compose 统一部署 UI、API、Nginx 和持久化数据。
- 提供任务清单、更新日志、本地 API、主节点协议、样式规范和部署文档。

首版不包含角色权限、私钥 SSH、主节点 UI、制品构建、命令审批流、批量脚本中心或终端输入审计。

## 2. 技术选型

### 2.1 推荐方案

- UI：React、TypeScript、Vite、Ant Design、xterm.js。
- API：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、SQLite、AsyncSSH、APScheduler。
- 认证：JWT 访问令牌、Argon2 密码哈希。
- 凭据：Fernet 对称加密，密钥仅通过运行环境或挂载文件提供。
- 代理：Nginx 托管构建后的 UI，并代理 HTTP 与 WebSocket。
- 测试：Pytest、Vitest、React Testing Library、临时 SQLite、可替换的 SSH 与主节点客户端。

选择 FastAPI 是因为异步 WebSocket、SSH 和任务进度流是核心能力。系统借鉴 Spug 3.0 的 `account`、`host`、`deploy`、`file` 和 `consumer` 模块边界，但不复制其较重的 Django 运行时。

### 2.2 已排除方案

- Django、Channels、Paramiko：与 Spug 最接近，但对子节点负担较重，异步 SSH 和定时任务整合复杂。
- ttyd 或 Wetty 独立终端：终端搭建快，但难以统一鉴权、服务器切换与 SFTP 文件管理。

## 3. 系统边界与组件

### 3.1 UI

- `auth`：登录状态、路由守卫和退出。
- `dashboard`：节点、主节点、主机和最近任务概览。
- `hosts`：主机增删改查、连接测试和指纹确认。
- `terminal`：服务器列表、xterm.js 会话和 SFTP 文件管理。
- `users`：创建、启禁用和重置密码。
- `tasks`：任务、目标、进度和日志查询。
- `audit`：审计日志查询。
- `shared`：HTTP 客户端、WebSocket 协议、主题变量、错误提示和通用组件。

### 3.2 API

- `auth`：JWT 签发、校验和当前用户解析。
- `users`：用户生命周期和密码策略。
- `hosts`：主机数据、凭据加解密、连接测试和指纹管理。
- `terminal`：浏览器 WebSocket 与 AsyncSSH 通道桥接。
- `files`：基于 AsyncSSH SFTP 的远程文件操作。
- `node_sync`：主节点签名、心跳、主机清单汇报和重试。
- `deployments`：任务领取、幂等落库、制品下载、校验、分发、命令执行和事件回传。
- `audit`：敏感信息过滤和操作日志。
- `core`：配置、数据库、统一错误、请求 ID、日志和应用生命周期。

各组件通过显式服务接口协作。SSH、制品下载和主节点通信均封装为可替换适配器，以便测试不依赖真实外部服务。

## 4. 页面与交互

### 4.1 登录

登录页使用深色品牌背景。用户输入账号和密码；禁用用户、密码错误、服务不可用和请求超时使用不同中文提示。登录成功后进入概览页。

### 4.2 概览

展示：

- 子节点状态、节点 ID 和运行时间。
- 主节点连接状态和最近成功心跳时间。
- 主机总数、连接正常数和异常数。
- 运行中、成功和失败的最近发布任务。

### 4.3 主机管理

主机字段为名称、IP 或主机名、SSH 端口、用户名、密码、标签和是否为当前节点。列表不返回密码。新增和修改可立即发起连接测试；保存、修改或删除成功后异步触发完整主机清单汇报。

主机测试结果区分：

- DNS 解析失败。
- TCP 连接超时。
- 连接被拒绝。
- SSH 认证失败。
- 主机密钥首次确认。
- 主机密钥变化。
- 连接成功。

当前节点自身是一条普通主机记录，通过 `is_local` 标记。系统只允许存在一条 `is_local=true` 的记录。

### 4.4 Web SSH 与文件管理

桌面端固定为三栏：

- 左栏：服务器搜索、状态、名称与 IP；点击后切换服务器。
- 中栏：xterm.js 终端，占主要宽度。
- 右栏：当前目录、面包屑、文件列表和操作工具栏。

切换服务器时，若当前会话仍连接，先提示用户确认并关闭旧 SSH/SFTP 连接。终端支持窗口尺寸变化、粘贴和全屏。右侧支持刷新、上传、下载、新建目录、重命名和删除。删除操作必须二次确认。窄屏下文件区折叠为右侧抽屉。

文件管理开放 SSH 用户本身可访问的目录，不额外模拟系统权限。默认单文件上传上限为 1 GiB，可通过 `ATHENA_MAX_UPLOAD_BYTES` 修改。

### 4.5 用户管理

所有已登录用户具有相同的管理员能力。管理员可以创建用户、启用或禁用用户、重置密码。系统禁止禁用当前登录用户，也禁止禁用最后一个可用用户。首个管理员通过 `ATHENA_BOOTSTRAP_USERNAME` 和 `ATHENA_BOOTSTRAP_PASSWORD` 初始化；完成初始化后环境变量不会覆盖现有密码。

### 4.6 任务与审计

任务页显示主节点任务 ID、制品信息、目标机器、目标目录、命令摘要、阶段、进度、开始结束时间、退出码和过滤后的实时日志。

审计记录登录、退出、用户变更、主机变更、连接测试、终端建立与关闭、主机指纹确认和文件操作。系统不记录 SSH 终端输入，不记录密码、JWT、节点 Token 或完整带签名下载 URL。

## 5. 视觉规范

采用深色运维控制台风格：

| 语义 | 颜色 |
| --- | --- |
| 页面背景 | `#0B1020` |
| 面板背景 | `#121A2B` |
| 边框 | `#24324A` |
| 主色 | `#5B8CFF` |
| 成功 | `#2DD4A8` |
| 警告 | `#F6C85F` |
| 危险 | `#FF6B7A` |
| 主文字 | `#E8EEF8` |
| 次文字 | `#93A4BD` |
| 终端背景 | `#070B12` |

圆角统一为 8 px，表单和常规按钮高度为 36 px，页面间距以 8 px 为基准。状态不能只用颜色表达，同时使用图标和文字。焦点环使用主色并满足键盘可见性。

## 6. 数据模型

### 6.1 `users`

- `id`: UUID 主键。
- `username`: 唯一、忽略大小写匹配。
- `password_hash`: Argon2 哈希。
- `is_active`: 是否允许登录。
- `last_login_at`: 最近登录时间。
- `created_at`、`updated_at`: UTC 时间。

### 6.2 `hosts`

- `id`: UUID 主键。
- `name`: 展示名称。
- `address`: IP 或 DNS 主机名。
- `port`: 1 至 65535，默认 22。
- `username`: SSH 用户名。
- `encrypted_password`: Fernet 密文。
- `tags`: JSON 字符串数组。
- `is_local`: 当前节点标记，唯一条件约束。
- `host_key_fingerprint`: 已确认的 SHA-256 指纹。
- `last_test_status`、`last_test_message`、`last_tested_at`: 最近测试结果。
- `created_at`、`updated_at`: UTC 时间。

主节点任务通过目标 IP 匹配 `hosts.address`。为避免歧义，IP 形式的 `address` 必须唯一；DNS 名称可以存在，但不能作为发布任务目标。

### 6.3 `deployment_tasks`

- `id`: UUID 主键。
- `master_task_id`: 主节点任务 ID，唯一。
- `artifact_url`: 加密或脱敏保存。
- `artifact_sha256`: 64 位小写十六进制摘要。
- `artifact_name`: 安全化文件名。
- `status`: `claimed`、`downloading`、`running`、`succeeded`、`failed`、`manual_review`。
- `claimed_at`、`started_at`、`finished_at`: UTC 时间。
- `error_code`、`error_message`: 过滤后的错误。

### 6.4 `deployment_targets`

- `id`: UUID 主键。
- `task_id`: 所属任务。
- `host_id`: 匹配到的本地主机。
- `target_ip`: 主节点下发 IP。
- `target_directory`: 远程绝对目录。
- `command`: 主节点下发的原始命令。
- `status`: `pending`、`uploading`、`executing`、`succeeded`、`failed`、`manual_review`。
- `progress`: 0 至 100。
- `exit_code`: 远程命令退出码。
- `started_at`、`finished_at`: UTC 时间。

### 6.5 `deployment_events`

- `id`: 单调递增主键，用作事件序号。
- `task_id`、`target_id`: 关联任务和目标。
- `event_type`: `stage`、`progress`、`stdout`、`stderr`、`result`。
- `payload`: 过滤后的 JSON。
- `created_at`: UTC 时间。
- `delivered_at`: 主节点确认接收时间。

未送达事件持久化在 SQLite，重试成功后标记 `delivered_at`。

### 6.6 `audit_logs`

- `id`: UUID 主键。
- `user_id`: 系统任务允许为空。
- `action`: 稳定动作代码。
- `resource_type`、`resource_id`: 操作对象。
- `result`: `success` 或 `failure`。
- `source_ip`: 请求来源。
- `details`: 已过滤 JSON。
- `created_at`: UTC 时间。

### 6.7 `node_settings`

仅保存节点 ID、节点名称、最近心跳时间等运行状态。主节点 URL、节点 Token、JWT 密钥和凭据加密密钥由环境变量或 Docker Secret 提供，不写入数据库。

## 7. 本地 API

统一前缀为 `/api/v1`。除登录与健康检查外均要求 JWT。错误响应固定为：

```json
{
  "code": "HOST_AUTH_FAILED",
  "message": "SSH 认证失败",
  "request_id": "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
  "details": {}
}
```

主要接口：

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /users`
- `POST /users`
- `PATCH /users/{user_id}/status`
- `POST /users/{user_id}/reset-password`
- `GET /hosts`
- `POST /hosts`
- `GET /hosts/{host_id}`
- `PUT /hosts/{host_id}`
- `DELETE /hosts/{host_id}`
- `POST /hosts/{host_id}/test`
- `POST /hosts/{host_id}/trust-fingerprint`
- `WS /terminal/ws/{host_id}`
- `GET /files/{host_id}/list`
- `POST /files/{host_id}/directories`
- `POST /files/{host_id}/upload`
- `GET /files/{host_id}/download`
- `PATCH /files/{host_id}/rename`
- `DELETE /files/{host_id}`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/events`
- `GET /audit-logs`
- `GET /health`

终端 WebSocket 首帧为短时一次性终端票据，不在 URL 中放 JWT。客户端发送 `input`、`resize`、`ping`，服务端发送 `output`、`connected`、`error`、`closed`。

完整请求和响应模式由实现生成的 OpenAPI 文件定义；WebSocket 协议在独立接口文档中定义。

## 8. 主节点协议

统一前缀为主节点的 `/api/node/v1`。

### 8.1 签名

每个请求包含：

- `X-Node-Id`
- `X-Timestamp`: Unix 秒，允许与主节点相差 300 秒。
- `X-Nonce`: 每次请求唯一的随机值。
- `X-Signature`: HMAC-SHA256 十六进制摘要。

签名原文为：

```text
HTTP_METHOD
PATH_WITH_QUERY
X_TIMESTAMP
X_NONCE
SHA256_HEX_OF_BODY
```

主节点保存 10 分钟内已使用的 `(node_id, nonce)`，拒绝重放。

### 8.2 心跳与完整主机清单

`POST /nodes/heartbeat` 在以下时机调用：

- API 启动成功后。
- 主机新增、修改、删除或指纹确认后。
- 正常运行期间每 60 秒。

请求包含节点版本、启动时间、系统摘要和完整主机清单。主机清单只包含 ID、名称、地址、端口、用户名、标签、是否当前节点和最近状态，不包含密码。

### 8.3 任务领取

`POST /nodes/{node_id}/tasks/claim` 每 60 秒调用。请求声明最大领取数和当前运行任务数。主节点返回零个或多个任务，并为每个任务提供租约。

任务至少包含：

- `task_id`
- `artifact.url`
- `artifact.sha256`
- `artifact.name`
- `targets[].ip`
- `targets[].directory`
- `targets[].command`

子节点通过 `master_task_id` 唯一约束实现幂等。同一主节点任务不重复落库或执行。

### 8.4 事件回传

`POST /tasks/{task_id}/events` 批量上传连续事件。每个事件包含子节点单调递增的 `sequence`、目标 IP、事件类型、时间和负载。主节点返回已确认的最大连续序号。

连接失败时事件保存在 SQLite，并按 2、4、8、16、30 秒退避重试，之后每 30 秒重试。日志事件最多 16 KiB；更长输出拆分成多个有序事件。

### 8.5 发布执行

流程为：

1. 验证任务结构、目标 IP、目录和 SHA-256 格式。
2. 幂等写入任务和目标。
3. 下载制品到本地任务临时目录，同时回传下载进度。
4. 校验 SHA-256；不匹配则停止整个任务。
5. 为每个目标按 IP 查找主机，建立 SSH/SFTP 连接。
6. 上传到目标目录内的唯一临时文件。
7. 使用 SFTP 重命名将临时文件原子移动为制品文件名。
8. 将目标目录作为远程进程工作目录，执行主节点下发的原始命令。
9. 分别流式回传 stdout 和 stderr，记录退出码。
10. 汇总目标和任务结果。

多个目标最多并发 4 台，可通过 `ATHENA_DEPLOY_CONCURRENCY` 修改。同一主机通过进程内锁和 SQLite 运行状态避免并发发布。

服务重启后：

- 尚未开始远程命令的任务可以从安全阶段继续。
- 已进入 `executing` 但未获得退出码的目标标记为 `manual_review`，不自动重复命令。
- 已完成任务只补发未确认事件，不重复执行。

## 9. 安全设计

- 用户密码使用 Argon2id。
- SSH 密码使用 Fernet 加密；缺少或错误的加密密钥时 API 拒绝启动。
- SSH 主机密钥使用 TOFU。首次连接返回待确认指纹；管理员确认后保存。后续指纹变化时拒绝连接。
- JWT 默认有效期 30 分钟；退出使当前令牌的唯一 ID 进入数据库撤销表直至过期。
- 登录接口按来源 IP 和账号组合限速：5 次失败后锁定 15 分钟。
- WebSocket 使用短时、一次性票据；空闲 30 分钟关闭；每个用户最多 5 个会话。
- 所有文件路径拒绝空字节。路径规范化由远程 SFTP 实现完成，权限完全服从远程 SSH 用户。
- 发布命令不与目录或文件名进行 shell 字符串拼接；工作目录通过 SSH 进程参数设置。
- 下载仅允许 HTTPS，除非开发环境显式设置 `ATHENA_ALLOW_HTTP_ARTIFACTS=true`。
- 日志过滤 Authorization、Cookie、密码、JWT、节点 Token 和 URL 敏感查询参数。

## 10. 错误处理与可观测性

- 每个 HTTP 请求生成或透传 `X-Request-Id`。
- API 日志采用结构化 JSON，包含时间、级别、请求 ID、动作代码和结果。
- 外部错误转换为稳定业务错误码，UI 不展示 Python 堆栈。
- 主节点不可用不影响本地 SSH 管理，但概览明确显示离线和最近成功时间。
- 主机变化汇报失败进入后台重试，不回滚已成功的本地 CRUD。
- 发布制品校验失败、目标主机不存在或主机指纹异常均停止对应安全边界并实时上报。
- 数据库使用 WAL、外键约束和合理忙等待；Docker 每日复制 SQLite 数据文件和 WAL 检查点由部署方备份策略负责。

## 11. Docker 与运行

交付物包含：

- UI 多阶段 Dockerfile：Node 构建，Nginx 运行。
- API Dockerfile：Python 3.12 slim、非 root 用户、健康检查。
- 根级 Docker Compose：UI 暴露 `8080`，API 仅在内部网络开放。
- Nginx：`/api/` 反代 API，WebSocket 路径启用 Upgrade，静态资源长缓存。
- 数据卷：SQLite、上传临时文件和运行日志。
- `.env.example`：列出全部必要变量且不包含真实密钥。

开发预览：

- UI 使用 Vite，绑定 `0.0.0.0`。
- API 使用 Uvicorn，绑定 `0.0.0.0`。
- UI 将 `/api` 代理至本地 API。
- 完成实现并验证后提供 `http://<局域网地址>:5173` 和 API 文档地址。

## 12. 测试与验收

### 12.1 API 自动化测试

- 登录成功、失败、禁用、限速和退出撤销。
- 创建、启禁用、重置密码以及最后可用用户保护。
- SSH 密码加密、密钥错误和列表脱敏。
- 主机 CRUD、唯一当前节点和连接测试错误映射。
- TOFU 首次确认和指纹变化拒绝。
- 终端票据一次性、并发限制、断开清理和 resize 转发。
- SFTP 列表、上传限制、下载、重命名、删除和审计。
- HMAC 签名向量、时间偏差和重放拒绝。
- 任务幂等、目标匹配、SHA-256 失败、并发限制和重启恢复。
- 事件序号、批量确认、敏感信息过滤和失败重试。

### 12.2 UI 自动化测试

- 登录状态和受保护路由。
- 主机表单校验、连接测试和指纹确认。
- 服务器搜索、切换确认和终端状态。
- 文件操作确认、上传进度和错误提示。
- 用户禁用与重置密码交互。
- 任务阶段、进度和日志渲染。

### 12.3 集成与 Docker 验收

- 使用临时 SQLite、模拟 SSH 服务器和模拟主节点完成端到端发布。
- 构建 UI 与 API 镜像。
- 启动 Compose 后完成健康检查、初始化管理员登录和数据卷重启持久化。
- 验证 Nginx HTTP 与 WebSocket 代理。
- 验证真实浏览器中的登录、主机列表和三栏终端布局。

## 13. 文档交付

- `TASKS.md`：按阶段维护可勾选任务清单。
- `CHANGELOG.md`：采用 Keep a Changelog 格式。
- `docs/api/local-api.md`：本地 REST 与 WebSocket 接口。
- `docs/api/master-node-protocol.md`：供主节点 Codex 实现的完整协议与示例。
- `docs/api/openapi.json`：由 FastAPI 应用生成。
- `docs/style-guide.md`：颜色、排版、间距、状态与组件规范。
- `README.md`：开发、测试、预览与 Docker 部署。

## 14. 实施顺序

1. 基础工程、配置、数据库和统一错误。
2. 登录与用户管理。
3. 主机管理、凭据加密、连接测试和 TOFU。
4. Web SSH、服务器切换和 SFTP 文件管理。
5. 主节点签名、心跳、主机汇报和协议文档。
6. 任务领取、制品处理、发布执行和实时事件。
7. 概览、任务、审计页面。
8. Docker、完整文档、集成测试和预览。

每一阶段采用测试先行，并产生可独立验证的交付物。


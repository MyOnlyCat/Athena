# Athena-Node 本地 API

基础路径为 `/api/v1`。除 `POST /auth/login` 和 `GET /health` 外，HTTP
接口均使用 `Authorization: Bearer <JWT>`。错误统一返回：

```json
{"code":"ERROR_CODE","message":"可读错误信息","request_id":"UUID"}
```

响应携带 `X-Request-Id`；请求提供同名 Header 时会原样沿用。

## 健康检查

`GET /health` 返回：

```json
{"status":"ok","service":"athena-node-api"}
```

## 认证和用户

| 方法 | 路径 | 请求 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | `{"username":"admin","password":"..."}` | 获取访问令牌和用户 |
| GET | `/auth/me` | - | 当前用户 |
| POST | `/auth/logout` | - | 吊销当前令牌，返回 204 |
| GET | `/users` | - | 用户列表 |
| POST | `/users` | `{"username":"ops","password":"至少12字符"}` | 创建用户 |
| PATCH | `/users/{user_id}/status` | `{"is_active":false}` | 启用或禁用 |
| POST | `/users/{user_id}/reset-password` | `{"password":"至少12字符"}` | 重置密码，返回 204 |

## SSH 主机

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/hosts` | 列出主机 |
| GET | `/hosts/probe-settings` | 查询全局自动探活间隔 |
| PUT | `/hosts/probe-settings` | 更新 `{"interval_minutes":5}` 并立即全量探活 |
| POST | `/hosts` | 新增主机，返回 201 |
| GET | `/hosts/{host_id}` | 查询主机 |
| PUT | `/hosts/{host_id}` | 更新主机 |
| DELETE | `/hosts/{host_id}` | 删除主机，返回 204 |
| POST | `/hosts/{host_id}/test` | 测试 SSH；首次或变更时返回待确认指纹 |
| POST | `/hosts/{host_id}/trust-fingerprint` | 确认 `{"fingerprint":"SHA256:..."}` |

新增主机请求：

```json
{
  "name": "web-01",
  "address": "10.0.0.11",
  "port": 22,
  "username": "deploy",
  "password": "ssh-password",
  "tags": ["production"],
  "is_local": false
}
```

密码只写不读，响应仅包含 `has_password`。主机变更会唤醒主节点资产同步。更新
地址或端口会清除已确认指纹，必须重新测试并确认；只更新名称、账号、标签等
非端点字段会保留原指纹。

API 启动后立即对全部主机执行一次 SSH 探活，之后按全局间隔循环。间隔为
1–1440 分钟的整数，数据库尚无配置时默认使用
`ATHENA_HOST_PROBE_INTERVAL_MINUTES`（默认 5）。网页主机管理页保存新间隔后无需
重启 API：配置会持久化到数据库、立即触发一次全量探活，并重置后续计时。每轮最多
并发探测 5 台主机，上一轮未结束时不会启动重叠轮次。

## 主节点配置

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/master-settings` | 返回当前有效地址、`has_token` 和运行状态 |
| POST | `/master-settings/test` | 测试候选连接，不保存、不应用 |
| PUT | `/master-settings` | 保存并即时应用候选连接 |
| POST | `/master-settings/registration` | 使用已保存配置申请接入 |
| POST | `/master-settings/registration/status` | 主动同步 Master 审批状态 |

请求体：

```json
{"scheme":"https","host":"master.example.com","port":443,"token":""}
```

`scheme` 只能是 `http` 或 `https`；`host` 是不带协议、路径和用户信息的主机名
或 IP；端口范围为 1–65535。Token 留空会复用当前有效 Token。响应示例：

```json
{
  "scheme": "https",
  "host": "master.example.com",
  "port": 443,
  "has_token": true,
  "runtime_status": "online"
}
```

响应永不包含明文 Token。没有数据库行时，服务从
`ATHENA_MASTER_NODE_URL` 和 `ATHENA_NODE_TOKEN` 得到初始配置；一旦成功保存，
数据库行整体优先于环境变量，重启后仍然生效。

`POST /master-settings/test` 访问候选地址的 Master 公共健康接口；Token 留空时使用
当前有效值。`PUT /master-settings` 串行完成候选运行时准备、加密保存和数据库提交，
然后停止旧轮询客户端并激活新客户端。连接测试、准备或提交失败时，
旧数据库配置与旧运行时保持不变。连接失败返回
`MASTER_CONNECTION_FAILED`，校验失败返回 422。

修改页面表单后必须先保存并应用，才能申请接入。待审批时页面每 5 秒调用本地状态同步
接口；Node 使用已保存 Token 向 Master 发送签名查询，仅在 Master 验证节点已经批准
后把本地 `registration_status` 更新为 `approved`。

`runtime_status` 是稳定枚举：`unconfigured` 表示缺少有效主机或 Token；
`connecting` 表示运行时正在等待首次成功同步；`online` 表示最近一次心跳和任务
轮询成功；`error` 表示心跳、轮询或后台工作循环失败；`stopped` 表示运行时没有
活动配置或已经停止。

## 终端和文件

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/terminal/tickets` | 请求 `{"host_id":"..."}`，返回 201 和 30 秒一次性票据 |
| WS | `/terminal/ws/{host_id}` | 网页终端，见 [WebSocket 协议](websocket-protocol.md) |
| GET | `/files/{host_id}/list?path=/` | 目录列表 |
| POST | `/files/{host_id}/directories` | `{"path":"/tmp/a"}`，返回 204 |
| PATCH | `/files/{host_id}/rename` | `{"source":"...","destination":"..."}`，返回 204 |
| DELETE | `/files/{host_id}` | `{"path":"...","recursive":true}`，返回 204 |
| POST | `/files/{host_id}/upload?path=...` | 原始二进制请求体，返回 204 |
| GET | `/files/{host_id}/download?path=...` | 流式 `application/octet-stream` 下载 |

文件接口只接受已确认指纹的 SSH 主机。远程路径必须是 POSIX 绝对路径，且不能
包含空字节。上传请求体不是 multipart，而是
`Content-Type: application/octet-stream` 的文件原始字节；默认上限 1 GiB，
可通过 `ATHENA_MAX_UPLOAD_BYTES` 调整。下载响应包含兼容 ASCII 的
`filename` 和 RFC 5987 UTF-8 `filename*`。

前端的三并发上传、取消、路径导航和下载行为见
[文件传输指南](../node/file-transfers.md)。

## 发布任务和审计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/tasks` | 本节点任务及目标机器状态 |
| GET | `/tasks/{task_id}` | 单个任务 |
| GET | `/tasks/{task_id}/events` | 按序号排列的事件历史 |
| GET | `/audit-logs?limit=100` | 最新审计，`limit` 范围 1–500 |

完整 HTTP 字段及约束以 [OpenAPI JSON](openapi.json) 为准。WebSocket 路由不会
出现在 OpenAPI 中。主节点调用不经这些本地管理接口，而使用独立的 HMAC
签名协议。

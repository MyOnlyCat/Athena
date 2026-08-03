# Athena Master 与接入节点协议

版本：`v1`  
主节点前缀：`/api/node/v1`  
编码：UTF-8 JSON

本文档描述 Athena-Node 主动访问 Athena-Master 的 v1 协议。Master 不回连 Node。

## 注册申请与审批

Node 管理员先在本地保存 Master 地址和节点独占 Token，再使用独立的“申请接入”
操作提交：

`POST /api/node/v1/registration-applications`

请求使用下文相同的 HMAC 认证头。JSON 正文固定包含 `node_id`、`reported_name`、
`hostname` 和 `software_version`，不包含 Token。Master 在 JSON 解析前读取原始
body，并保存原始字节、认证头、接收时间和来源 IP；此时所有申请资料均标记为
“身份未验证”，不能视为已认证事实。请求时间戳与 Master 接收时间的偏差不能超过
300 秒。

Master 管理接口均要求管理员 Bearer Token：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `GET` | `/api/v1/registration-applications` | 服务端分页列出申请 |
| `POST` | `/api/v1/registration-applications/{id}/approve` | 输入同一 Node Token 并批准 |
| `POST` | `/api/v1/registration-applications/{id}/reject` | 拒绝申请，可附带原因 |
| `POST` | `/api/v1/registration-applications/{id}/restore` | 恢复已拒绝身份的申请资格 |

审批时 Master 使用保存的原始 body 和认证头重新计算 HMAC，不重新序列化 JSON。
Token 不匹配时返回 `401 REGISTRATION_TOKEN_INVALID`，申请保持待审批。验证成功后
创建已启用接入节点，并使用 `ATHENA_MASTER_CREDENTIAL_KEY` 加密保存 Token，同时
保存不可逆 HMAC-SHA256 指纹来保证 Token 全局唯一。重复 Token 返回
`409 REGISTRATION_TOKEN_DUPLICATE`，且不泄露关联节点。Token 明文、密文及可用于
认证的派生值都不会通过 API 返回。

待审批申请七天后自动标记为 `expired`，不能再批准；已拒绝和已过期申请在状态变更
30 天后由后台维护任务清理，正式接入节点不会被物理删除。同一 Node ID 被拒绝后，
提交返回 `409 REGISTRATION_REJECTED`；管理员恢复原申请后，Node 管理员必须手动
重新提交。每个 Node ID 每分钟最多提交一次，每个来源 IP 每分钟最多十次；最多保留
1,000 条待审批申请。超限分别返回 `429 REGISTRATION_RATE_LIMITED` 或
`429 REGISTRATION_CAPACITY_REACHED`，且不创建部分记录。

Node 在本地处于待审批状态时，定期调用：

`POST /api/node/v1/registration-applications/status`

请求正文为 `{}`，并使用节点 Token 生成 HMAC 认证头。未批准时 Master 根据最新申请
返回 `pending`、`rejected`、`expired` 或 `restored`；批准后仅在签名与加密保存的
Token 匹配时返回 `approved`，Token 不匹配返回
`401 REGISTRATION_TOKEN_INVALID`。Node 持久化返回状态：`pending` 每 60 秒主动
查询；`rejected` 停止自动申请；`expired` 和 `restored` 提示管理员手动重新提交。
状态同步始终由 Node 发起，不需要 Master 回连。

由于两阶段审批前 Master 尚未持有 Token，未批准节点的状态查询只能校验认证头格式和
时间窗口，不能验证 HMAC；返回的生命周期状态不构成节点身份认证。批准后的状态查询
必须通过 HMAC 验证。部署从旧版本升级时会为已有 Token 回填指纹；若历史数据已存在
重复 Token，Master 会拒绝启动并要求先为受影响节点配置不同 Token，不会静默接受或
泄露 Token。

## 节点认证

每个子节点在主节点配置唯一 `node_id` 和共享 `node_token`。所有请求包含：

| Header | 说明 |
| --- | --- |
| `X-Node-Id` | 子节点唯一 ID |
| `X-Timestamp` | Unix 秒，主节点允许 ±300 秒 |
| `X-Nonce` | 32 位随机十六进制字符串 |
| `X-Signature` | HMAC-SHA256 小写十六进制 |

签名原文：

```text
HTTP_METHOD
PATH_WITH_QUERY
X_TIMESTAMP
X_NONCE
SHA256_HEX_OF_EXACT_BODY_BYTES
```

主节点必须使用收到的原始 body 字节校验，不能重新序列化 JSON。主节点保存 `(node_id, nonce)` 10 分钟，重复 nonce 返回 HTTP 409。

```python
import hashlib
import hmac


def verify(secret, method, path, timestamp, nonce, body, signature):
    canonical = "\n".join([
        method.upper(), path, timestamp, nonce,
        hashlib.sha256(body).hexdigest(),
    ])
    expected = hmac.new(
        secret.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

固定测试向量：

```text
secret=node-secret
method=POST
path=/api/node/v1/nodes/node-1/tasks/claim?limit=2
timestamp=1785333600
nonce=nonce-123
body={"running_tasks":0}
signature=89fc0647ffaec69188abcac1bc0eb747ac6bf869a35aac18753dfa9ee6e70caa
```

## 子节点连接配置与热替换

子节点本地提供以下已认证接口：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `GET` | `/api/v1/master-settings` | 返回有效地址、`has_token` 和 `runtime_status` |
| `POST` | `/api/v1/master-settings/test` | 访问候选 Master 公共健康接口；不保存、不应用 |
| `PUT` | `/api/v1/master-settings` | 加密保存并即时应用 |
| `POST` | `/api/v1/master-settings/registration` | 使用已保存配置申请接入 |
| `POST` | `/api/v1/master-settings/registration/status` | 主动同步审批状态 |

`ATHENA_MASTER_NODE_URL` 和 `ATHENA_NODE_TOKEN` 是首次启动默认值。数据库尚无
`master_settings` 行时使用它们；成功保存后，数据库中的协议、主机、端口和
加密 Token 整体优先，重启不会重新被环境变量覆盖。

GET 响应只用 `has_token` 表示 Token 是否存在，永不返回明文或密文。测试和保存
请求的 `token` 为空字符串时复用当前有效 Token。Token 使用本节点
`ATHENA_CREDENTIAL_KEY` 加密落库。

保存按单一重配置锁串行执行：

1. 校验候选地址和 Token。
2. 准备新的客户端、资产同步器和任务执行器；新工作循环在激活前等待。
3. 加密保存并提交数据库。
4. 停止并关闭旧工作循环、执行器和 HTTP 客户端，再激活候选运行时。

保存不要求 Node 已获批准或心跳成功，因此可以先持久化配置再申请接入；连接测试仍是
独立且不保存的操作。页面表单有未保存修改时禁用“申请接入”，申请接口只读取已保存
配置。候选准备或数据库提交失败时不替换旧运行时，数据库提交失败时还会清理候选资源。
`registration_status` 为 `not_submitted`、`pending`、`approved`、`rejected`、
`expired` 或 `restored`，
`runtime_status` 为 `unconfigured`、`connecting`、`online`、`disabled`、
`authentication_failed`、`connection_failed`、`error` 或 `stopped`。正常心跳间隔为
60 秒；禁用或认证失败固定每 300 秒探测；连接失败使用带抖动的指数退避并在 300 秒
封顶，成功后恢复 60 秒间隔。

## 心跳与完整主机清单

`POST /api/node/v1/nodes/heartbeat`

在启动、主机增删改、指纹确认以及每 60 秒调用：

```json
{
  "protocol_version": "v1",
  "node": {
    "id": "019d3a7e-7c42-7000-8000-000000000007",
    "name": "上海接入节点",
    "version": "0.1.0",
    "hostname": "athena-node-01",
    "reported_at": "2026-07-29T14:00:00Z"
  },
  "hosts": [
    {
      "id": "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
      "name": "web-01",
      "address": "10.0.0.10",
      "port": 22,
      "username": "root",
      "tags": ["production"],
      "is_local": true,
      "last_test_status": "success",
      "last_test_code": "SSH_CONNECTED",
      "last_tested_at": "2026-07-29T13:59:30Z"
    }
  ]
}
```

密码、密文和自由文本连接错误不会上报。`hosts` 是节点的完整当前清单。检测状态为
`success`、`failed`、`pending_trust` 或 `null`；已检测主机必须同时携带标准
`last_test_code` 和 UTC RFC 3339 `last_tested_at`，尚未检测时三者均为空。
`success` 只对应 `SSH_CONNECTED`，`pending_trust` 只对应
`SSH_HOST_KEY_UNTRUSTED`；失败状态使用 `SSH_AUTH_FAILED`、`SSH_TIMEOUT`、
`SSH_CONNECTION_FAILED` 或 `SSH_HOST_KEY_CHANGED`。

Master 严格拒绝未知字段、重复 host ID、字符串形式端口、非布尔本机标记、非法端口、
非法检测状态、重复或超限标签以及不带时区的检测时间。任一主机非法时整次心跳回滚，
不会更新最后心跳、部分资产或退役状态。每个 Node 最多上报 500 条主机资产，心跳正文
最多 5 MiB，全局最多保留 10,000 条在管资产。

成功快照以 `(node_id, host_id)` 更新资产，不按 IP 跨 Node 合并。本次缺少、上次仍在管
的资产会被软退役；相同身份再次出现时恢复为在管并更新最新字段。

`protocol_version` 与 Node 软件版本彼此独立，当前仅接受 `v1`。Master 必须先使用
收到的原始正文完成 HMAC 验证，再解析 JSON；不支持的协议版本返回
`426 NODE_PROTOCOL_UNSUPPORTED`。成功心跳使用 Master 接收时间更新上报名、hostname、
软件版本和最后心跳，Node 的 `reported_at` 仅作诊断。

响应：

```json
{"accepted_at":"2026-07-29T14:00:01Z","next_heartbeat_seconds":60}
```

每个节点的心跳至少间隔十秒，Node API 的进程内总限制为每节点每分钟二十次。正常
心跳间隔为 60 秒。Master 将 `(node_id, nonce)` 存入 SQLite 并保留十分钟，进程重启
不会清除有效窗口内的防重放记录。通过节点身份与签名验证后，即使请求随后因负载、
协议版本或限流被拒绝，该 nonce 仍会被持久消费，重放返回
`409 NODE_NONCE_REPLAYED`。

管理员通过 `GET /api/v1/nodes` 查看接入节点。接口要求管理员 Bearer Token，支持：

| 参数 | 说明 |
| --- | --- |
| `page` / `page_size` | 服务端分页，`page_size` 最大 100 |
| `search` | 搜索上报名、hostname、软件版本或 Node ID |
| `management_status` | 按管理状态筛选 |
| `connectivity_status` | `online`、`stale` 或 `offline` |
| `sort_by` / `sort_order` | 按上报字段、批准时间或最后心跳升降序排列 |

连接状态只使用 Master 接收时间推导：少于 120 秒为 `online`，120–300 秒（含边界）
为 `stale`，超过 300 秒或从未收到心跳为 `offline`。管理界面映射为“在线”、
“心跳延迟”和“离线”，并按浏览器时区显示最后心跳。

管理员还可维护与心跳上报字段隔离的节点管理信息：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `PATCH` | `/api/v1/nodes/{node_id}/management-info` | 替换管理显示名、备注和标签 |
| `PATCH` | `/api/v1/nodes/{node_id}/status` | `active` / `disabled`，原因可空 |
| `POST` | `/api/v1/nodes/{node_id}/token` | 输入新 Token 手动轮换 |

管理显示名为空时页面回退到 Node 上报名，但仍同时标注原始上报名。心跳不会覆盖管理
字段。禁用节点的已认证业务请求返回 `403 NODE_DISABLED`，且不消费 nonce 或更新心跳、
资产；身份和历史数据保留。重新启用后 Node 在下一次五分钟探测时自动恢复。Token
轮换执行长度、全局唯一、加密存储和不回显约束；若新值与当前 Token 相同则返回
`409 NODE_TOKEN_UNCHANGED`，提交成功后旧 Token 立即失效。

管理员通过 `GET /api/v1/nodes/{node_id}/assets` 查看所选接入节点的只读主机资产。
接口支持服务端分页，并提供以下筛选：

| 参数 | 说明 |
| --- | --- |
| `page` / `page_size` | 服务端分页，`page_size` 最大 100 |
| `search` | 搜索资产名称或地址 |
| `lifecycle_status` | `active`（在管）或 `retired`（已退役） |
| `detection_status` | `success`、`failed`、`pending_trust` 或 `untested` |
| `tag` | 按单个完整标签筛选 |

响应保留最后检测状态、标准错误码和检测时间；时间使用 UTC RFC 3339，页面按浏览器
时区显示。每项资产还返回 `source_node_connectivity_status`：`online`、`stale` 或
`offline`。页面对 `stale` 显示“数据延迟（来源节点心跳延迟）”，对 `offline` 显示
“状态未知（来源节点离线）”，同时继续展示最后检测结果与时间。Master 页面不会编辑
Node 上报的资产字段。

管理员通过 `GET /api/v1/overview` 获取健康概览。响应包含：

- 接入节点总数及 `pending`、`active`、`disabled`、`rejected` 管理状态数量；
- `online`、`stale`、`offline` 正式接入节点数量；
- 在管资产总数、明确异常和状态未知数量。

仅在线 Node 上报为 `failed` 的在管资产计入明确异常；离线 Node 下的在管资产计入状态
未知。心跳延迟 Node 的资产显示数据延迟，不计入明确异常或状态未知。概览、节点列表和
当前资产查询每 30 秒轮询；注册与节点管理操作成功后立即刷新相关缓存。以上统计使用
数据库聚合查询，不加载全部节点或资产。

## 领取发布任务

`POST /api/node/v1/nodes/{node_id}/tasks/claim`

请求：

```json
{"running_tasks":1,"limit":4}
```

响应：

```json
{
  "tasks": [
    {
      "task_id": "release-20260729-001",
      "lease_id": "lease-01",
      "lease_expires_at": "2026-07-29T14:10:00Z",
      "artifact": {
        "url": "https://artifacts.example.com/signed/app.jar",
        "sha256": "52a4f0d4c750c2e78af9f23474b4e23a18f415778cb7649f10e1a4bd375a7204",
        "name": "app.jar",
        "size": 104857600
      },
      "targets": [
        {
          "ip": "10.0.0.10",
          "directory": "/opt/apps/example",
          "command": "systemctl restart example"
        }
      ]
    }
  ]
}
```

约束：

- `task_id` 全局唯一且永久不复用。
- 主节点使用租约防止重复领取。
- 制品 URL 是短时 HTTPS 地址，SHA-256 为 64 位小写十六进制。
- 目标 IP 必须匹配子节点上报的 IP。
- 目录必须是 POSIX 绝对路径。
- 命令由子节点原样执行。
- 无任务返回 HTTP 200 和 `{"tasks":[]}`。

## 任务事件

`POST /api/node/v1/tasks/{task_id}/events`

```json
{
  "events": [
    {
      "sequence": 1,
      "target_ip": "10.0.0.10",
      "type": "stage",
      "occurred_at": "2026-07-29T14:01:00Z",
      "payload": {"stage":"downloading","message":"开始下载制品"}
    },
    {
      "sequence": 2,
      "target_ip": "10.0.0.10",
      "type": "progress",
      "occurred_at": "2026-07-29T14:01:02Z",
      "payload": {"progress":35}
    }
  ]
}
```

事件类型为 `stage`、`progress`、`stdout`、`stderr`、`result`。主节点按任务保存序号并幂等接收重复批次，返回最大连续确认序号：

```json
{"acknowledged_sequence":2}
```

子节点仅标记连续确认事件。失败时按 2、4、8、16、30 秒退避，之后每 30 秒重试。单个日志事件 JSON 负载不超过 16 KiB。

## 状态

任务状态：`claimed`、`downloading`、`running`、`succeeded`、`failed`、`manual_review`。

目标状态：`pending`、`uploading`、`executing`、`succeeded`、`failed`、`manual_review`。

子节点重启时，已进入 `executing` 且没有退出码的目标转为 `manual_review`，不会自动再次执行命令。

## 错误

```json
{
  "code": "NODE_SIGNATURE_INVALID",
  "message": "节点签名无效",
  "request_id": "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
  "details": {}
}
```

| HTTP | code | 场景 |
| --- | --- | --- |
| 401 | `NODE_SIGNATURE_INVALID` | 签名不匹配 |
| 401 | `NODE_TIMESTAMP_INVALID` | 时钟偏差超过 300 秒 |
| 403 | `NODE_DISABLED` | 节点已被管理员禁用 |
| 404 | `NODE_NOT_FOUND` | 节点未注册 |
| 409 | `NODE_NONCE_REPLAYED` | nonce 重放 |
| 422 | `NODE_AUTH_INVALID` | 认证头格式无效 |
| 422 | `NODE_PAYLOAD_INVALID` | 心跳正文无效或节点身份不匹配 |
| 413 | `NODE_PAYLOAD_TOO_LARGE` | 心跳正文超过 5 MiB |
| 422 | `ASSET_CAPACITY_EXCEEDED` | 全局在管资产将超过 10,000 条 |
| 426 | `NODE_PROTOCOL_UNSUPPORTED` | 正文协议版本不受支持 |
| 409 | `TASK_LEASE_CONFLICT` | 任务已被领取 |
| 422 | `TASK_PAYLOAD_INVALID` | 任务结构无效 |
| 429 | `NODE_RATE_LIMITED` | 节点请求过快 |
| 503 | `MASTER_TEMPORARILY_UNAVAILABLE` | 主节点暂不可用 |

## 主节点验收

- 固定测试向量通过。
- 拒绝过期时间戳和重复 nonce。
- 心跳完整覆盖主机清单且不接收密码。
- 同一任务不能重复租给不同节点。
- 重复事件批次不生成重复日志，只确认连续事件序号。
- 主节点 UI 能按目标实时展示阶段、进度、stdout、stderr 和结果。

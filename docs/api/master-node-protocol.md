# Athena 主节点与子节点协议

版本：`v1`  
主节点前缀：`/api/node/v1`  
编码：UTF-8 JSON

本文档供雅典娜主节点后端 Codex 直接实现。主节点构建制品；Athena-Node 仅领取任务、下载校验、传输、执行命令和回传进度。

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

## 心跳与完整主机清单

`POST /api/node/v1/nodes/heartbeat`

在启动、主机增删改、指纹确认以及每 60 秒调用：

```json
{
  "node": {
    "id": "node-shanghai-01",
    "name": "上海子节点",
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
      "last_test_status": "success"
    }
  ]
}
```

密码和密文不会上报。`hosts` 是节点的完整当前清单。

响应：

```json
{"accepted_at":"2026-07-29T14:00:01Z","next_heartbeat_seconds":60}
```

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
| 404 | `NODE_NOT_FOUND` | 节点未注册 |
| 409 | `NODE_NONCE_REPLAYED` | nonce 重放 |
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


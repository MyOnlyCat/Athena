# Athena Master 与接入节点协议

- 版本：`v1`
- 主节点前缀：`/api/node/v1`
- 编码：UTF-8 JSON；Artifact endpoint 返回二进制

状态：注册、审批、旧心跳部分已由第一阶段实现；本文第二阶段任务、安全信封和扩展心跳
是已确认的目标契约，尚待按协调升级计划实施。开发期直接更新 v1，不代表当前二进制已
具备本文全部能力。

本文档描述 Athena-Node 主动访问 Athena-Master 的 v1 协议。Master 不回连 Node。

第一阶段单个 Master 最多管理 100 个已批准接入节点；第 101 个申请在审批时返回
`422 ACCESS_NODE_CAPACITY_EXCEEDED`，申请保持待审批且不会创建部分节点记录。每个
Node 最多上报 500 条主机资产，全局最多保留 10,000 条在管资产，单次心跳正文最多
5 MiB。

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
path=/api/node/v1/nodes/node-1/tasks/claim?wait_seconds=25
timestamp=1785333600
nonce=0123456789abcdef0123456789abcdef
body={"protocol_version":"v1","available_slots":2,"leases":[],"accepted_key_ids":["master-signing-test"]}
signature=00e61bbc737817797316d90470f5ef19c761d4e72a1036aacbfa984f625b50e5
```

## 传输安全与响应可信度

Athena 使用 HTTP 明文传输，只允许部署在防火墙、VLAN 或 VPN 隔离的可信管理网络。
HTTP 不提供保密性，Node Token、JWT、密码、发布脚本、日志和 Artifact 内容都可能被
链路观察者读取。管理界面必须持续显示“HTTP 明文模式”警告；协议签名不等同于 TLS。

Node 获批并完成下述公钥登记后，安全职责分为三层：

- Node 到 Master 的所有请求继续使用 HMAC-SHA256、时间戳、nonce 和精确正文摘要认证；
- Master 的普通响应使用 Ed25519 签名并绑定原请求 nonce，防止响应伪造、篡改和重放；
- Preflight、Prepare、Activate 和 Key Rotation 使用独立、可持久化的 Ed25519 信封。Node 重启后
  也只能依据已经验签并持久化的信封执行。

在管理员 Credential、Node Token 和 Master 私钥都未泄露的前提下，这些控制可阻止
链路攻击者直接伪造远程执行授权。HTTP 上窃取到的管理员 JWT 仍可被用于请求 Master
创建并批准一条由 Master 合法签名的恶意 Release；因此隔离网络是强制安全边界，而不
只是保密性建议。攻击者也始终可以丢包、延迟或制造拒绝服务。

### Master 公钥初始登记

Node 获批后、第一次领取任务前调用：

`POST /api/node/v1/nodes/{node_id}/trust/bootstrap`

请求使用现有 Node HMAC，正文包含 `protocol_version` 和 32 字节随机 `challenge`。响应
包含 `master_instance_id`、`key_id`、Ed25519 raw public key、`issued_at` 和
`bootstrap_proof`。proof 使用 Node Token 对下列精确 UTF-8 原文计算 HMAC-SHA256：

```json
{
  "protocol_version": "v1",
  "challenge": "base64url-32-random-bytes"
}
```

```json
{
  "master_instance_id": "019f0000-0000-7000-8000-000000000001",
  "key_id": "master-signing-2026-01",
  "algorithm": "Ed25519",
  "public_key": "base64url-raw-32-bytes",
  "issued_at": "2026-08-04T02:00:00Z",
  "bootstrap_proof": "64-lowercase-hex"
}
```

```text
ATHENA-MASTER-KEY-BOOTSTRAP-V1
NODE_ID
REQUEST_NONCE
CHALLENGE
MASTER_INSTANCE_ID
KEY_ID
PUBLIC_KEY
ISSUED_AT
```

各字段之间是单个 LF，末尾没有 LF；challenge 与 public key 均使用不带 padding 的
Base64URL。

Node 校验 nonce、challenge、时间窗和 proof 后，在同一 SQLite 事务中保存 Master
instance、Key ID 和公钥。只有本地从未保存信任锚点，或管理员显式执行“重置信任”并使
Node 进入 `trust_reset_pending` 时允许 bootstrap。已有锚点时响应不得静默替换公钥。

### 公钥轮换

正常轮换使用旧 Ed25519 私钥签署 `key-rotation` 信封，payload 绑定 `rotation_id`、
Master instance、旧/新 Key ID、新公钥、`not_before`、`old_key_accept_until` 和
`issued_at`。Node 用旧公钥验签、持久化新公钥，再通过 HMAC 请求确认 rotation ID。

在某 Node 确认新 Key 前，发给该 Node 的普通外层响应和轮换信封必须继续由它已接受的
旧 Key 签名，避免验证循环。Master 永久保存完整轮换证书链；Key ID 不得复用，Node
拒绝链环、降级和同一 Key ID 的不同公钥。宽限期结束后，Master 只有在全部未禁用 Node
已确认时才能删除旧私钥；若管理员选择让长期离线/禁用 Node 错过旧 Key，必须先把它
标为 `trust_reset_required`，它恢复后不能领取任务，且只能经本地管理员显式重置后
bootstrap。旧私钥泄露时不得使用链式轮换，必须走同一显式信任重置流程。

### Ed25519 信封与普通响应签名

Preflight、Prepare、Activate 和 Key Rotation 使用统一信封：

```json
{
  "kind": "prepare",
  "key_id": "master-signing-2026-01",
  "payload_b64": "base64url-exact-json-bytes",
  "signature_b64": "base64url-ed25519-signature"
}
```

`payload_b64`、`signature_b64` 和 raw public key 均使用不带 padding 的 Base64URL；Key ID
是可打印 ASCII。Master 对 payload JSON 只序列化一次，持久化并重发完全相同的 UTF-8
bytes；禁止从数据库字段重新拼装已签名信封。固定 fixtures 冻结数字、转义、字段顺序和
空值表示，payload 禁止浮点数和重复对象键。

签名原文为：

```text
b"ATHENA-V1\x00" + KIND_ASCII + b"\x00" + KEY_ID_ASCII
+ b"\x00" + DECODED_PAYLOAD_BYTES
```

Node 先对原始 payload bytes 验签，再以禁止未知字段的严格 v1 model 解析，不能重新
序列化后验签。`kind` 参与 domain separation，Prepare 不能作为 Activate 使用。

普通 JSON 响应返回 `X-Master-Key-Id`、`X-Master-Timestamp`、`X-Request-Nonce` 和
`X-Master-Signature`。响应签名原文为：

```text
ATHENA-MASTER-RESPONSE-V1
HTTP_STATUS
PATH_WITH_QUERY
REQUEST_NONCE
MASTER_TIMESTAMP
SHA256_HEX_OF_EXACT_RESPONSE_BODY
```

`X-Master-Timestamp` 是十进制 Unix 秒，`X-Master-Signature` 是不带 padding 的 Base64URL
Ed25519 signature；各行之间是单个 LF，末尾没有 LF。bootstrap proof 则使用小写十六
进制 HMAC-SHA256。Node 按与请求相同的 ±300 秒窗口校验响应时间。

Node 只有在响应签名通过后才接受事件 ACK、租约决定、公钥轮换、Preflight 或任务信封。
公钥登记前的注册申请和待审批状态仍受“注册申请与审批”一节的受限信任约束，不构成
执行授权。
Artifact 正文不额外签名，因为 Prepare 已绑定 Artifact ID、size 和 SHA-256，Node
必须全量校验。

完成公钥登记后，任何缺少有效签名的响应（包括 Nginx/代理自行生成的 5xx HTML）都只
归一为本地 `MASTER_RESPONSE_UNTRUSTED` 连接故障，不得确认事件、续租、改变 Task 状态
或执行信封；Node 按连接失败退避重试。

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
  "execution": {
    "task_protocol_revision": "release-1",
    "capabilities": [
      "release-preflight-v1",
      "release-prepare-activate-v1",
      "artifact-range-v1"
    ],
    "max_concurrency": 4,
    "available_slots": 4,
    "spool_free_bytes": 21474836480,
    "spool_low_space": false,
    "accepted_key_ids": ["master-signing-2026-01"]
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

Master 在认证、签名、防重放和限流前置检查之后，直接从已签名的原始 JSON 字节读取
`protocol_version`。格式正确的非空字符串若不是 `v1`，即使同时携带 v1 不认识的未来
字段，也统一返回 `426 NODE_PROTOCOL_UNSUPPORTED`；只有确认版本为 `v1` 后才执行
禁止额外字段的严格 v1 模型校验。缺失、空值或非字符串版本返回
`422 NODE_PAYLOAD_INVALID`。整个流程不重新序列化正文，也不改变签名输入。

密码、密文和自由文本连接错误不会上报。`execution` 是 Node 当前任务能力和本地 spool
容量快照；Master 要求精确 `task_protocol_revision=release-1` 和所需 capability，不能只
依据宽泛的 `protocol_version=v1` 或软件版本。尚未完成公钥登记的 Node 使用空
capability/Key ID 列表，不能领取任务。

`max_concurrency`/`available_slots` 的单位是 Target work lane。一个 Node Task 的
`capacity_cost=min(该 Task 目标数, max_concurrency)`，预留期间占用这些 lane；目标多于
lane 时由 Node 在同一 Task 内排队。`available_slots` 不得大于 `max_concurrency`。低磁盘
时 `spool_low_space=true` 且必须停止领取新 Node Task，但不停止心跳、lease/event
delivery。`hosts` 是节点的完整当前清单。检测状态为
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
心跳间隔为 60 秒。Master 将 `(node_id, nonce)` 存入 PostgreSQL 并保留十分钟，进程重启
不会清除有效窗口内的防重放记录。通过节点身份与签名验证后，即使请求随后因负载、
协议版本或限流被拒绝，该 nonce 仍会被持久消费，重放返回
`409 NODE_NONCE_REPLAYED`。

尚未获批的申请发送心跳时返回 `404 NODE_NOT_APPROVED`，已拒绝申请返回
`409 REGISTRATION_REJECTED`，完全未知且没有申请记录的 Node ID 返回
`404 NODE_NOT_FOUND`。Master 发生可恢复的数据库不可用时返回
`503 MASTER_TEMPORARILY_UNAVAILABLE`；Node 将结构化或非 JSON 的 Master 5xx 响应
统一归一为该机器码，状态显示为“连接失败”，并从约 5 秒开始按带抖动的指数退避，
最长不超过 300 秒，成功后恢复正常 60 秒间隔。

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
“心跳延迟”和“离线”，并固定按 `Asia/Shanghai`（UTC+8）显示最后心跳。

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
| `sort_by` | `name`、`address`、`port`、`username`、`last_test_status`、`last_tested_at` 或 `retired_at`；默认 `name` |
| `sort_order` | `asc` 或 `desc`；默认 `asc` |

响应保留最后检测状态、标准错误码和检测时间；时间使用 UTC RFC 3339，页面固定按
`Asia/Shanghai`（UTC+8）显示。每项资产还返回 `source_node_connectivity_status`：`online`、`stale` 或
`offline`。页面对 `stale` 显示“数据延迟（来源节点心跳延迟）”，对 `offline` 显示
“状态未知（来源节点离线）”，同时继续展示最后检测结果与时间。Master 页面不会编辑
Node 上报的资产字段。无论升序或降序，所选排序字段的空值都排在非空值之后；相同值
再按 `host_id` 升序排列，保证跨页结果稳定。

管理员通过 `GET /api/v1/overview` 获取健康概览。响应包含：

- 接入节点总数及 `pending`、`active`、`disabled`、`rejected` 管理状态数量；待审批和
  已拒绝按尚无正式身份的唯一 Node ID 的最新申请状态统计，重复与历史申请不重复计数；
- `online`、`stale`、`offline` 正式接入节点数量；
- 在管资产总数、明确异常和状态未知数量。

仅在线 Node 上报为 `failed` 的在管资产计入明确异常；离线 Node 下的在管资产计入状态
未知。心跳延迟 Node 的资产显示数据延迟，不计入明确异常或状态未知。概览、节点列表和
当前资产查询每 30 秒轮询；注册与节点管理操作成功后立即刷新相关缓存。以上统计使用
数据库聚合查询，不加载全部节点或资产。

## 管理操作审计

管理员通过 `GET /api/v1/audit-logs` 查看只读操作审计。接口要求管理员 Bearer Token，
使用 `page` 和 `page_size` 做服务端分页，`page_size` 最大为 100；记录按 UTC 时间和 ID
倒序稳定排列。每项包含操作者 ID/用户名、稳定动作码、目标类型/ID/显示名、
`success` 或 `failure` 结果、来源 IP、失败机器码和 UTC RFC 3339 时间。页面固定按
`Asia/Shanghai`（UTC+8）显示并标注时区。

记录范围包括管理员登录和账号维护、注册申请与 Node 生命周期，以及 Project、权限、
Credential Grant、Builder Image、Cache Volume、配置版本、Build Run、人工上传、Release
创建/批准/预约/取消/裁决/继续/重试/回滚。未认证登录失败的操作者为空，提交用户名仅
作为目标；无论账号是否存在，响应均使用相同的认证失败契约。

审计记录不复制通用请求正文。密码、JWT、Node Token 明文/密文/指纹、Credential 密文、
变量密文、注册原始正文、构建/发布脚本正文和签名都不得进入审计。Node 注册提交、状态
查询、心跳、资产快照和协议事件本身不重复生成操作审计；Node Task Event 是独立执行
记录。审计 UI 只读，默认至少保留 180 天且可由平台配置，历史记录不得通过业务 API
修改或删除。

## 兼容性与第二阶段协调升级

项目仍处于开发阶段，第二阶段直接重写 v1 的任务草案，不新增 v2，也不维护旧任务
草案兼容。Master 与 Node 必须协调升级；未达到最低软件版本或尚未建立 Master 签名
信任的 Node 可以继续心跳和展示资产，但不得领取 Node Task。正式生产发布后，删除
字段、改变语义或增加必填字段等破坏性修改才使用新协议版本。

协调升级顺序：

1. 冻结新 Build Run 和 Release，等待没有已开始副作用的任务；备份旧 Master SQLite、
   所有 Node SQLite、Artifact/日志和各类密钥。
2. 启动 PostgreSQL，执行 Master Alembic migration 和旧 SQLite 离线导入及校验。
3. 启动新 Master API/UI 与 Worker，但保持 `release_enabled=false`。
4. 逐台停止、迁移并升级 Node，完成 Master Ed25519 公钥 bootstrap 或链式轮换确认。
5. Master 确认所有发布 Node 的软件版本、心跳、长轮询和 Key ID 正常，执行跨 Node
   无业务 smoke Release 后再开启发布。
6. 失败时使用 PostgreSQL、SQLite、Artifact、日志、签名 Key、Credential Key 和配置的
   同一套备份回滚；不能只回滚二进制、数据库或密钥中的一个部分。

Master 永远不会回连 Node，也不使用 WebSocket 下发任务。Master 为永久单实例，数据库
为 PostgreSQL；Node 保持 SQLite。

## Node Preflight

Release Configuration Version 启用前，Master 可通过同一长轮询通道下发签名
`preflight` 信封；claim 响应的 `preflight_envelopes` 与 Release 的 Prepare/Activate
分开。Node Preflight 不是 Node Task，也不产生 Release Attempt。

`kind=preflight` 的严格 payload 为：

```json
{
  "protocol_version": "v1",
  "preflight_id": "019f0000-0000-7000-8000-000000000090",
  "release_configuration_version_id": "019f0000-0000-7000-8000-000000000091",
  "configuration_digest": "64-lowercase-hex",
  "node_id": "node-shanghai",
  "not_before": "2026-08-04T01:55:00Z",
  "expires_at": "2026-08-04T02:10:00Z",
  "targets": [
    {
      "host_id": "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
      "address": "10.0.0.10",
      "port": 22,
      "username": "deploy",
      "host_key_fingerprint": "SHA256:example",
      "destination": {
        "mode": "file",
        "parent_directory": "/opt/apps/demo",
        "artifact_name": "demo.jar",
        "final_path": "/opt/apps/demo/demo.jar"
      },
      "required_tools": ["bash", "sha256sum"]
    }
  ],
  "issued_at": "2026-08-04T02:00:00Z"
}
```

Node 必须先验签，再校验 audience、时间窗、身份和未处理的 `preflight_id`；相同 ID/相同
exact bytes 幂等返回已保存结果，相同 ID/不同 bytes 为安全冲突。允许的动作仅包括：

- 校验 SSH 连接、Host Key Fingerprint 和身份快照；
- 检查父目录/同文件系统 staging/history 的权限和基础磁盘容量；
- 检查 `sh`/`bash`、`sha256sum` 和所需解压工具；
- 检查首次接管状态和当前内容摘要；路径所有权由 Master PostgreSQL 判定；
- 在预定父目录创建并删除一个 Athena probe 临时文件。

Preflight 不得下载 Artifact、执行用户脚本、备份、重命名或修改正式路径。Node 通过
`POST /api/node/v1/preflights/{preflight_id}/result` 幂等回传每个 Host 的结构化
`status`、稳定 error code、实测 identity、工具、基础 free bytes、existing-content 状态和
current digest；不回传自由文本凭据错误。请求使用 HMAC，响应使用 Master Ed25519
response signature。Release 真正执行时仍须在 Prepare 阶段按实际 Artifact 大小、归档
展开量、历史和安全余量重新检查磁盘与漂移。

## 领取发布任务

`POST /api/node/v1/nodes/{node_id}/tasks/claim?wait_seconds=25`

请求：

```json
{
  "protocol_version": "v1",
  "available_slots": 3,
  "leases": [
    {
      "node_task_id": "019f0000-0000-7000-8000-000000000101",
      "lease_id": "019f0000-0000-7000-8000-000000000102",
      "lease_epoch": 1,
      "phase": "preparing",
      "last_event_sequence": 17
    }
  ],
  "accepted_key_ids": ["master-signing-2026-01"]
}
```

响应：

```json
{
  "accepted_at": "2026-08-04T02:00:00Z",
  "key_rotations": [],
  "preflight_envelopes": [],
  "prepare_envelopes": [],
  "activate_envelopes": []
}
```

约束：

- `wait_seconds` 最大为 25 秒；每个 Node 最多一个领取型长轮询，重复请求返回
  `409 NODE_LONG_POLL_CONFLICT`。
- 等待期间 Master 不持有 PostgreSQL transaction 或 connection；空结果也返回经过
  Ed25519 响应签名的 HTTP 200。
- 请求 nonce 在进入等待前消费。心跳、Task claim、lease renew 和 event delivery
  独立运行，任务领取不再附着在 60 秒心跳上。
- `available_slots` 是可用 Target work lane，不得超过心跳中的值；Master 使用 claim、
  最新心跳和 PostgreSQL 已有 reservation 三者计算出的最小可用量。每个 Node Task 的
  `capacity_cost=min(目标数,max_concurrency)`，Master 只有在 slots 足够时才预留。
- Master 只有在当前 Release Batch 所需的全部 Node 在线、容量可用且目标 Host lock 可
  取得时，才在一个 PostgreSQL 事务中预留整批并创建 Prepare。首个 Batch 还必须能在
  `start_deadline` 前完成 Prepare/Activate；后续 Batch 不再使用该启动 deadline。
- `node_task_id`、`preflight_id`、Prepare `envelope_id`、`batch_activation_id` 和每目标
  `activation_id` 全局唯一且永久不复用。

### Prepare 信封

Prepare 只授权从 Master 下载 Artifact、SFTP 上传到 Athena staging、远端 SHA-256、
磁盘/权限/身份/漂移检查和清理本 lease 的 staging。它不授权执行发布前脚本、备份、
替换正式路径或执行发布后脚本。

Prepare payload 至少包含：

```json
{
  "protocol_version": "v1",
  "envelope_id": "019f0000-0000-7000-8000-000000000103",
  "node_task_id": "019f0000-0000-7000-8000-000000000101",
  "release_id": "019f0000-0000-7000-8000-000000000104",
  "release_attempt_id": "019f0000-0000-7000-8000-000000000105",
  "release_batch_id": "019f0000-0000-7000-8000-000000000106",
  "node_id": "node-shanghai",
  "lease_id": "019f0000-0000-7000-8000-000000000102",
  "lease_epoch": 1,
  "capacity_cost": 1,
  "lease_expires_at": "2026-08-04T02:01:30Z",
  "not_before": "2026-08-04T02:00:00Z",
  "start_deadline": "2026-08-04T02:30:00Z",
  "snapshot_digest": "64-lowercase-hex",
  "artifact": {
    "artifact_id": "019f0000-0000-7000-8000-000000000107",
    "name": "demo.jar",
    "size": 104857600,
    "sha256": "64-lowercase-hex",
    "download_path": "/api/node/v1/tasks/019f0000-0000-7000-8000-000000000101/artifact"
  },
  "targets": [
    {
      "target_attempt_id": "019f0000-0000-7000-8000-000000000108",
      "host_id": "019fae08-0ab1-7da1-9d22-612a0c5bb9ed",
      "address": "10.0.0.10",
      "port": 22,
      "username": "deploy",
      "host_key_fingerprint": "SHA256:example",
      "destination": {
        "mode": "file",
        "parent_directory": "/opt/apps/demo",
        "artifact_name": "demo.jar",
        "final_path": "/opt/apps/demo/demo.jar",
        "file_mode": "0755"
      },
      "history_limit": 5,
      "expected_current_digest": null,
      "environment_bundle": {
        "digest": "64-lowercase-hex",
        "entries": [
          {
            "name": "SPRING_PROFILES_ACTIVE",
            "variable_version_id": "019f0000-0000-7000-8000-000000000110",
            "sensitive": false,
            "value": "prod"
          }
        ]
      },
      "pre_script": {
        "interpreter": "bash",
        "working_directory": "/opt/apps/demo",
        "body": "",
        "timeout_seconds": 300
      },
      "post_script": {
        "interpreter": "bash",
        "working_directory": "/opt/apps/demo",
        "body": "systemctl restart demo",
        "timeout_seconds": 300
      }
    }
  ],
  "issued_at": "2026-08-04T02:00:00Z"
}
```

Node 必须以 `host_id` 查本地 Host，并比较 address、port、username 和 Host Key
Fingerprint 快照。认证密码或私钥允许使用 Node 中轮换后的当前值。身份不一致时不得
连接目标。Node 验签后先在 SQLite 中持久化 `(envelope_id, node_task_id, lease_epoch)`
和原始 payload digest；完全相同的重复投递幂等返回本地状态，不重复准备，相同 ID 的
不同 bytes 是安全冲突。

Master 不得在 `not_before` 前下发 Prepare。Node 即使提前收到并持久化，也不得下载
Artifact 或接触 Target Host，必须等到本地校验时间不早于 `not_before`；若时间窗或
lease 无法满足则上报拒绝。首个 Batch 的 `start_deadline` 要求 Activate commit 和 Node
本地接受时间均不晚于它；首批已合法 Activate 后，后续 Batch 的该字段为 null。

`destination` 是按 `mode` 判别的严格 union。文件模式必须同时签署
`parent_directory + artifact_name + canonical final_path + file_mode`；目录模式必须签署
`final_directory + archive_format`，其中 format 仅为 `zip`、`tar.gz` 或 `tgz`。Node 不
自行猜测最终路径。`environment_bundle` 只包含 Release 快照显式引用的变量 Version、
解析值和整体 digest；Athena 不注入动态路径变量。含敏感值的 exact Prepare 在 Master
PostgreSQL 中必须加密，在 Node SQLite 中也必须用 Node Credential Key 加密，且不得
进入日志、审计、read model 或只读 UI，但 HTTP 传输仍是明文。
`expected_current_digest` 为上次成功文件 SHA-256 或目录 manifest SHA-256；首次发布为
null，并要求目标不存在或为空，不能自动接管现有内容。

每个 Target Attempt 使用绑定 `target_attempt_id + lease_epoch` 的独占 staging，例如
`<sibling>/.athena-staging/<target_attempt_id>/<lease_epoch>/`。旧 epoch 只能清理自己的
路径，不能触碰新 epoch。Node 上报该 staging 的最终 digest，Activate 必须精确绑定该
epoch 和 digest；验签后的 Node 也要在跨越副作用边界前再次校验。

### Artifact Range 下载

```http
GET /api/node/v1/tasks/{node_task_id}/artifact?lease_id={lease_id}&lease_epoch={epoch}
Range: bytes=1048576-
```

GET 使用现有 HMAC，空 body 参与摘要。Master 校验请求 Node 是 Task 接收方、lease tuple
当前有效、Task 未终止/过期，且 Artifact 与 Prepare 绑定的 ID、size、SHA-256 一致。
支持标准 `200`/`206`、`Accept-Ranges: bytes`、`Content-Range` 和稳定
`ETag: "sha256:<64-hex>"`。Node 只有在 Artifact metadata 与 ETag 全部一致时续传，
必须核对返回起点和本地 `.part` 长度并最终全量计算 SHA-256。Prepare 不接受任意 URL。

### Lease renew 与 fencing

`POST /api/node/v1/tasks/{node_task_id}/lease/renew`

每个请求携带 `node_task_id + node_id + lease_id + lease_epoch`。只有该专用 endpoint 能
延长 lease；claim 和 events 只报告状态，不续期。响应经过 Master response signature：

```json
{
  "node_task_id": "019f0000-0000-7000-8000-000000000101",
  "lease_id": "019f0000-0000-7000-8000-000000000102",
  "lease_epoch": 1,
  "decision": "renewed",
  "lease_expires_at": "2026-08-04T02:03:00Z"
}
```

`decision` 为 `renewed`、`fenced` 或 `cancel_after_safe_point`。只有验签后的 `renewed` 才
更新 Node 本地期限；取消决定必须绑定同一 tuple，Node 停在设计规定的安全点并发送
`cancellation_acknowledged`。`lease_epoch` 从 1 单调递增；只有尚未签发 Activate 且旧
lease 过期时，Master 才能创建新 lease ID 并增加 epoch。Node 收到更高 epoch 后停止旧
epoch 的安全步骤并只清理自己的 staging，不能接受更低 epoch 或同 epoch 的不同 lease ID。

建议 lease 默认 90 秒，Node 至少每 30 秒调用 renew。首批在 `start_deadline` 前提交
Activate 后，合法执行可在该时间后完成并继续续租。

## 任务事件

`POST /api/node/v1/tasks/{node_task_id}/events`

```json
{
  "protocol_version": "v1",
  "lease_id": "019f0000-0000-7000-8000-000000000102",
  "lease_epoch": 1,
  "events": [
    {
      "sequence": 18,
      "target_attempt_id": "019f0000-0000-7000-8000-000000000108",
      "type": "target_ready",
      "occurred_at": "2026-08-04T02:00:20Z",
      "payload": {
        "artifact_sha256": "64-lowercase-hex",
        "remote_size": 104857600,
        "staging_digest": "64-lowercase-hex",
        "observed_current_digest": null,
        "remote_free_bytes": 10737418240
      }
    }
  ]
}
```

稳定事件类型为：

- `task_accepted`
- `stage`
- `target_ready`
- `stdout`
- `stderr`
- `side_effect_started`
- `target_result`
- `task_result`
- `activation_declined`
- `cancellation_acknowledged`

唯一键为 `(node_task_id, sequence)`。重复的完全相同事件幂等接收；相同 sequence 内容
不同为冲突。新事件必须从当前最大连续确认序号的下一项开始，缺口返回
`409 NODE_EVENT_SEQUENCE_GAP` 和 `expected_sequence`。成功响应返回已持久化的最大连续
序号，并可携带 Activate：

```json
{
  "acknowledged_sequence": 18,
  "activate_envelopes": []
}
```

Node 只有在验证 Master 响应签名后才删除已确认事件。未确认事件持久化在 Node SQLite；
失败时指数退避并持续重传原 sequence。单个日志事件 JSON 不超过 16 KiB，日志达到上限
后可截断，但必须投递截断标记。

Activate 前已 fenced 的 epoch 只允许重传 Master 曾确认过的 event，不接受新的状态。
Activate 后不再生成新 epoch；即使原 lease 时间已过，原授权 Node 仍可用该 tuple 提交
日志和终局结果，Master 标记为 `late_evidence` 并连续 ACK，但不得据此自动覆盖 Unknown
或既有人工裁决。Artifact 下载、Prepare 和任何新副作用始终拒绝过期 lease。

### Activate 与副作用门

当前 Release Batch 的全部 Target Attempt 都上报带 staging digest 的 `target_ready`，且
全部 Node 在线、lease 有效、Host reservation 仍持有时，Master 才在一个 PostgreSQL
事务中为整批记录副作用授权。首个 Batch 还必须在 `start_deadline` 前完成该事务；后续
Batch 不受原启动 deadline 限制。事务为每个 Node 生成一份绑定自身 audience、Node Task、
lease 和目标子集的 Activate envelope，共享 `batch_activation_id`，但不是跨 Node 广播
同一 envelope。

Activate payload 至少包含：

```json
{
  "protocol_version": "v1",
  "batch_activation_id": "019f0000-0000-7000-8000-000000000109",
  "node_task_id": "019f0000-0000-7000-8000-000000000101",
  "release_batch_id": "019f0000-0000-7000-8000-000000000106",
  "node_id": "node-shanghai",
  "lease_id": "019f0000-0000-7000-8000-000000000102",
  "lease_epoch": 1,
  "prepare_payload_sha256": "64-lowercase-hex",
  "targets": [
    {
      "target_attempt_id": "019f0000-0000-7000-8000-000000000108",
      "activation_id": "019f0000-0000-7000-8000-000000000111",
      "staging_digest": "64-lowercase-hex",
      "expected_current_digest": null
    }
  ],
  "activate_before": "2026-08-04T02:30:00Z",
  "issued_at": "2026-08-04T02:00:21Z"
}
```

Node 必须验证 Activate 与本地原始 Prepare、Node、lease/epoch 完全匹配，Prepare payload
摘要一致，每个 Target Attempt 属于 Prepare 且没有重复，并再次核对签署的 staging/current
digest。首批当前时间不得晚于 `activate_before`；后续批次该字段为 null。

相同 envelope ID、完全相同 exact bytes/signature 的重投是幂等状态查询，不视为错误；
相同 ID 的不同内容返回 `ENVELOPE_ID_CONFLICT`。每个 Target Attempt 独立持久化
`activation_id` 和 `activation_consumed_at`。Node 紧邻发布前脚本、历史备份或正式替换中
最早的外部修改前，再持久化该目标的 `side_effect_started_at`；任一提交失败不得执行。

Master 一旦提交 `side_effect_authorized`，就保守地认为授权可能送达。之后 lease 丢失
不得签发新 activation 或新 epoch；即使尚无 `side_effect_started` 证据，无法证明结果时
也进入 Unknown Execution。

## 状态

Node Task 状态：`reserved`、`preparing`、`ready`、`activated`、`executing`、
`succeeded`、`failed`、`unknown`、`expired`、`cancelled`。

Target Attempt 状态：`pending`、`preparing`、`ready`、`activated`、`executing`、
`succeeded`、`failed`、`unknown`、`cancelled`。

`unknown` 对应领域术语 **Unknown Execution**。Activate 前 lease 过期可以增加 epoch 并
安全重新准备；Master 已提交 Activate 后授权可能送达，即使尚不能证明脚本开始，lease
过期、Node checkpoint 缺失/损坏或结果不可证实也转为 `unknown`。SSH 在副作用后断开且
无法证明退出状态同样为 Unknown，绝不自动重执行命令。

任一 Target Attempt 失败或 unknown 后，尚未开始的后续 Release Batch 停止。Unknown
必须由具备权限的用户填写说明并裁决；裁决成功后继续后续批次仍是独立动作。只有明确
失败的目标可创建新的 failed-target Release Attempt。回滚从 Master 历史 Artifact 创建
新的 Release，不是 Node 本地动作。

### 重启与断线

- Master 重启后以 PostgreSQL 中的 Release、lease、epoch、Prepare、Activate 和连续
  ACK 为事实来源；进程内长轮询 waiter 丢失后 Node 重连。
- Master 只能重发原始完全相同的 Activate；Node 幂等返回每目标现有 checkpoint，不能
  重复执行，也不能重新签发新的 activation ID。Activate 后 lease 失效转 Unknown。
- Node 持久化可信 Key、原始 Prepare/Activate bytes、Range metadata、events 和 checkpoint。
- Node 只有 Prepare 时可在有效 lease 内续传；被 fenced 后清理 staging。
- Activate 已保存但未消费时，仅在 lease 和时间窗仍有效时消费；否则发
  `activation_declined`。
- `side_effect_started` 已提交但无确定结果时，Node 恢复为 Unknown，不重新执行脚本。
- Artifact 下载只在同一 lease epoch 内 Range 续传；event ACK 丢失时重传原序号。

## 错误

```json
{
  "code": "NODE_SIGNATURE_INVALID",
  "message": "节点签名无效"
}
```

协议稳定错误使用 `code` 与中文 `message`。`MASTER_*` 和 `TASK_ENVELOPE_*` 验证失败
主要由 Node 在本地呈现并停止处理，其余为 Master HTTP 响应：

| HTTP | code | message | 场景 |
| --- | --- | --- | --- |
| 401 | `NODE_SIGNATURE_INVALID` | 节点签名无效 | 签名不匹配 |
| 401 | `NODE_TIMESTAMP_INVALID` | 节点时间戳无效 | 时钟偏差超过 300 秒 |
| 403 | `NODE_DISABLED` | 接入节点已被禁用 | 节点已被管理员禁用 |
| 404 | `NODE_NOT_APPROVED` | 节点尚未批准 | 有申请但尚未形成正式身份 |
| 404 | `NODE_NOT_FOUND` | 接入节点不存在 | 没有正式身份或申请记录 |
| 409 | `REGISTRATION_REJECTED` | 接入申请已被拒绝，请联系管理员恢复后手动重试 | 最新申请已拒绝 |
| 409 | `NODE_NONCE_REPLAYED` | 节点 nonce 已被使用 | nonce 重放 |
| 422 | `NODE_AUTH_INVALID` | 节点认证头无效 | 认证头格式无效 |
| 422 | `NODE_PAYLOAD_INVALID` | 心跳负载无效 | 心跳正文结构无效 |
| 422 | `NODE_PAYLOAD_INVALID` | 心跳负载中的节点身份不匹配 | 正文与认证节点不一致 |
| 413 | `NODE_PAYLOAD_TOO_LARGE` | 心跳正文超过 5 MiB 限制 | 心跳正文过大 |
| 422 | `ACCESS_NODE_CAPACITY_EXCEEDED` | 接入节点数量已达到 100 个支持上限 | 批准第 101 个接入节点 |
| 422 | `ASSET_CAPACITY_EXCEEDED` | 在管主机资产数量超过 10000 条限制 | 全局在管资产将超限 |
| 426 | `NODE_PROTOCOL_UNSUPPORTED` | 节点协议版本不受支持 | 正文协议版本不受支持 |
| 429 | `NODE_RATE_LIMITED` | 节点请求过于频繁，请稍后重试 | 每节点分钟总额度超限 |
| 429 | `NODE_RATE_LIMITED` | 心跳请求过于频繁，请稍后重试 | 心跳间隔少于十秒 |
| 401 | `MASTER_KEY_PROOF_INVALID` | Master 公钥登记证明无效 | Node 本地 bootstrap proof 验证失败 |
| 401 | `MASTER_RESPONSE_SIGNATURE_INVALID` | Master 响应签名无效 | Node 本地响应验签失败 |
| 502 | `MASTER_RESPONSE_UNTRUSTED` | Master 响应不可验证 | Node 收到无签名的代理/网络响应 |
| 401 | `TASK_ENVELOPE_SIGNATURE_INVALID` | 任务信封签名无效 | Node 本地 Preflight/Prepare/Activate 验签失败 |
| 403 | `ARTIFACT_ACCESS_DENIED` | 无权下载该制品 | Node 没有有效 Task/lease 授权 |
| 409 | `NODE_LONG_POLL_CONFLICT` | 节点已有任务长轮询 | 同一 Node 发起第二个 claim |
| 409 | `NODE_EVENT_SEQUENCE_GAP` | 任务事件序号不连续 | 事件未从连续 ACK 后开始 |
| 409 | `LEASE_FENCED` | 任务租约已失效 | lease ID 或 epoch 不是当前值 |
| 409 | `ENVELOPE_ID_CONFLICT` | 信封 ID 与已保存内容冲突 | 相同 ID 出现不同 exact bytes/signature |
| 409 | `ACTIVATE_PREPARE_MISMATCH` | 激活许可与准备任务不匹配 | Activate 没有绑定本地 Prepare |
| 410 | `NODE_TASK_EXPIRED` | Node 任务已过期 | Task 或开始窗口已过期 |
| 416 | `ARTIFACT_RANGE_INVALID` | 制品 Range 无效 | 起点、范围或本地断点不合法 |
| 422 | `NODE_CAPACITY_INVALID` | Node 可用容量无效 | claim 容量超过本地/心跳上限 |
| 422 | `NODE_EVENT_INVALID` | Node 任务事件无效 | 事件类型或状态转换非法 |
| 422 | `TARGET_IDENTITY_CHANGED` | 目标主机身份已变化 | Host 身份与 Release 快照不一致 |
| 503 | `MASTER_TEMPORARILY_UNAVAILABLE` | 主节点暂时不可用，请稍后重试 | 可恢复的 Master 数据库不可用 |

正文大小、认证头格式、时间窗口、未知/未批准/已拒绝身份、错误签名和禁用状态在消费
nonce 前拒绝。已认证且启用的节点会先持久化消费 nonce，再检查分钟限流、心跳间隔、
正文结构、协议版本和资产容量；这些后续校验失败时使用同一 nonce 重试会得到
`409 NODE_NONCE_REPLAYED`。错误请求不得更新最后心跳、部分资产或退役状态。

## 协议验收

- 固定测试向量通过。
- Node 真实提交申请、Master 审批、Node 主动同步状态和完整资产心跳链路通过。
- 拒绝错误签名、过期时间戳和重复 nonce，且错误请求不改变节点与资产状态。
- 资产 `[A, B]` 更新为 `[A]` 时 B 软退役，再次出现时恢复；禁用节点后同步失败，
  重新启用后自动恢复。
- 100 个接入节点、每 Node 500 条资产、全局 10,000 条在管资产与 5 MiB 正文边界有
  自动化覆盖。
- 所有 API 时间以带时区的 UTC RFC 3339 返回，相关页面固定按
  `Asia/Shanghai`（UTC+8）显示并标注时区。
- Master PostgreSQL 迁移、初始化管理员登录、API 健康检查、UI 启动和 UI 到 API
  代理冒烟通过。
- Master 固定 Preflight、Prepare、Activate、响应签名和 Key Rotation 测试向量均被 Node 接受；
  修改任意字节、Node audience、lease、摘要或 kind 都被拒绝。
- 独立 25 秒长轮询、lease fencing、Artifact Range、连续事件 ACK 和 Node SQLite
  恢复通过自动化测试。
- 跨 Node Batch 在所有 Target ready 前没有任何脚本或正式路径修改；Activate 响应
  丢失后进入 Unknown 且不自动重复远程副作用。
- Node 仍使用 SQLite，Master 正式运行不再包含 SQLite 路径；Master/Node 协调升级和
  成套备份回滚通过演练。

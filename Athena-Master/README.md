# Athena-Master

Athena-Master 是 Athena 的中心管理节点。当前已提供 FastAPI 后端、React 管理界面、
SQLite/Alembic 持久化、管理员认证与账号管理、完整节点注册生命周期、健康检查和
Windows 本地开发入口。已获批 Node 可发送 v1 认证心跳，管理员可分页、筛选和排序查看
接入节点及其连接状态，并原子汇总每个 Node 的完整主机资产快照。管理员还可维护独立
显示名、备注、管理标签、启用状态和 Node Token。系统概览使用数据库聚合查询展示节点
管理/连接状态与资产健康；只读审计记录安全敏感和人工管理动作的成功与失败结果。

CI/CD 第二阶段架构已经确认但尚未实施。目标将 Master 迁移到 PostgreSQL，并增加本地
Build Worker、Artifact Store、Release Orchestration 和签名 Node 拉取协议；当前 SQLite
和单 worker 描述仅代表第一阶段现状。

## 项目结构

Master 与 Node 使用一致的组件布局，便于在两个独立应用之间定位同类代码；两者不互相
导入内部模块。

```text
Athena-Master/
├── api/
│   ├── alembic/             # 数据库迁移
│   ├── app/
│   │   ├── api/             # HTTP 路由与依赖
│   │   ├── core/            # 配置、数据库与错误契约
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── schemas/         # API 数据结构
│   │   └── services/        # 认证与管理员账号管理
│   └── tests/               # API 行为测试
└── ui/
    ├── scripts/             # Windows 本地启动与自检
    ├── src/
    │   ├── app/             # 路由和应用外壳
    │   ├── features/        # 按功能组织的页面
    │   ├── shared/          # API 客户端与共享类型
    │   └── styles/          # 与 Node 一致的主题系统
    └── tests/               # UI 行为测试
```

## Windows 本地开发

环境要求为 Python 3.12 或更高版本、Node.js 20 或更高版本和 npm。双击或运行：

```powershell
Athena-Master\ui\start-dev.cmd
```

脚本会创建 API 虚拟环境、安装依赖、执行 `alembic upgrade head`，然后以单 worker
启动 API 和 UI。默认地址：

- UI：`http://127.0.0.1:5174`
- API 健康检查：`http://127.0.0.1:8001/api/v1/health`
- 本地初始化账号：`admin / change-me-now-123`

本地密码仅用于开发，不能直接用于生产。启动入口不依赖 Docker。

## 生产配置

生产环境使用 `ATHENA_MASTER_` 前缀，并必须显式提供：

- `ATHENA_MASTER_JWT_SECRET`
- `ATHENA_MASTER_CREDENTIAL_KEY`
- `ATHENA_MASTER_BOOTSTRAP_USERNAME`
- `ATHENA_MASTER_BOOTSTRAP_PASSWORD`
- `ATHENA_MASTER_DATA_DIR`
- `ATHENA_MASTER_DATABASE_URL`

缺少任一配置时应用拒绝启动。JWT 默认有效期为 30 分钟；退出会立即撤销当前 JWT。
连续五次错误登录会按规范化用户名与来源 IP 锁定 15 分钟。

## 管理员账号

“管理员”页面提供服务端分页列表，并显示账号启用状态与最近登录时间。所有管理员共享
同一 admin 权限，不提供角色模型。已登录管理员可以：

- 创建管理员；用户名去除首尾空格并按不区分大小写的形式判重。
- 禁用或重新启用其他管理员，但不能禁用当前账号或最后一个可用管理员。
- 重置管理员密码。

管理员密码必须为 12–128 个字符，同时包含字母和数字，且不能与用户名相同。禁用账号
或重置密码会增加该账号的持久化认证版本，立即撤销此前签发的全部 JWT；重新启用账号
不会恢复旧登录凭证。

## 接入节点注册

Node 使用本地持久化 UUIDv7 身份和 Token 对注册申请的原始 JSON 字节签名，正文不
传输 Token。Master 的“注册申请”页面将资料明确标为“身份未验证”。管理员必须从
可信渠道取得同一 Token 并在审批对话框中输入；Master 使用收到时保存的原始字节
重新验证签名，验证成功后才创建已启用接入节点。

Master 使用 `ATHENA_MASTER_CREDENTIAL_KEY` 对 Node Token 加密落库。API、页面和
错误响应不会返回 Token 明文或密文。注册协议和接口详见
[Master 与接入节点协议](../docs/api/master-node-protocol.md)。

管理员可以拒绝申请（原因可选），也可以恢复已拒绝身份的重新申请资格。待审批申请
七天后自动过期；后台维护任务清理状态变更超过 30 天的已拒绝/已过期申请。提交入口
限制为每 Node ID 每分钟一次、每来源 IP 每分钟十次和最多 1,000 条待审批申请。
审批 Token 使用不可逆指纹保证全局唯一，同时仍只以加密原文执行 HMAC 认证。
旧数据库若已有重复 Node Token，启动时的指纹回填会明确拒绝继续运行，管理员必须先
为受影响节点配置不同 Token，系统不会自动选择或泄露冲突 Token。

第一阶段最多批准 100 个接入节点。批准第 101 个申请返回
`422 ACCESS_NODE_CAPACITY_EXCEEDED`，申请保持待审批且不会创建部分节点记录。

## 认证心跳与接入节点状态

已获批 Node 使用 `POST /api/node/v1/nodes/heartbeat` 上报 v1 心跳。Master 在解析 JSON
前，以 HTTP method、带查询参数的路径、时间戳、nonce 和原始正文摘要验证
HMAC-SHA256；签名使用常量时间比较。时间戳允许与 Master 接收时间相差最多 300 秒，
nonce 必须是 32 位小写十六进制字符串。

Master 将 `(node_id, nonce)` 持久化到 SQLite 并保留十分钟，因此进程重启不会清空仍在
有效窗口内的防重放状态。通过身份和签名验证后，即使请求随后因负载、协议版本或限流
被拒绝，nonce 也会被消费。每个接入节点的心跳至少间隔十秒，所有 Node API 共享进程内
每分钟二十次额度；正常心跳间隔为 60 秒。认证与防重放检查通过后，Master 先从原始
JSON 读取 `protocol_version`，再执行 v1 严格字段校验；任何格式正确但不受支持的非空
版本都返回 HTTP 426，即使正文同时包含未来版本字段。缺失、空值或非字符串版本仍按
无效负载返回 HTTP 422。

成功心跳只以 Master 接收时间更新最后心跳，同时更新 Node 上报名、hostname 和软件
版本。Node 正文中的 `reported_at` 仅用于诊断，不参与连接状态计算：

- 少于 120 秒：在线。
- 120–300 秒（含边界）：心跳延迟。
- 超过 300 秒或从未收到心跳：离线。

“接入节点”页面当前将最后心跳按浏览器时区展示；第二阶段全部业务页面会固定为
`Asia/Shanghai`（UTC+8）。对应管理 API
`GET /api/v1/nodes` 提供服务端分页、文本搜索、管理/连接状态筛选及排序。

桌面端将紧凑节点列表放在左侧，所选节点的完整详情与资产表放在右侧；视口小于 768px
时改为同页顺序布局，主导航收进抽屉，页面无需横向滚动即可完成节点选择和资产查看。

## 接入节点生命周期管理

“接入节点”页面同时显示管理员维护的显示名与 Node 上报名。管理显示名为空时回退到
Node 上报名；心跳只更新上报名、hostname、版本和运行信息，不覆盖显示名、备注或管理
标签。管理员管理接口均要求 Bearer Token：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `PATCH` | `/api/v1/nodes/{node_id}/management-info` | 替换显示名、备注与管理标签 |
| `PATCH` | `/api/v1/nodes/{node_id}/status` | 禁用或重新启用，禁用原因可空 |
| `POST` | `/api/v1/nodes/{node_id}/token` | 手动更换 Node Token |

禁用不会删除节点身份、最后心跳或主机资产。Node 使用正确签名访问心跳接口时收到
`403 NODE_DISABLED`，且 nonce、最后心跳和资产均不改变；重新启用后下一次有效探测
自动恢复。Token 更换继续执行 32–256 字符、全局唯一、凭据密钥加密和永不回显规则；
与当前 Token 相同的值返回 `409 NODE_TOKEN_UNCHANGED`。更新提交后旧 Token 立即失效。
Token 轮换不是双 Token 切换，管理员应先在 Node 本地
准备新 Token，再在 Master 输入相同值，并接受短暂离线窗口。

## 主机资产快照

心跳中的 `hosts` 是完整快照。Master 在同一短事务内更新本次资产、软退役缺失资产，
并在相同 `(node_id, host_id)` 再次出现时恢复原记录。资产不会按 IP 跨接入节点合并；
任一资产无效时，最后心跳、已有资产和退役状态均保持不变。

心跳严格限制为每 Node 500 条资产、全局 10,000 条在管资产和 5 MiB 正文。资产字段
不包含密码、密文或自由文本连接错误，只保留标准 SSH 检测状态、机器码和 UTC 检测
时间。“接入节点”页面在选择 Node 后提供只读资产表，以及在管/已退役、名称或地址、
标签和检测状态的服务端分页筛选。对应 API 为
`GET /api/v1/nodes/{node_id}/assets`。资产可按 `name`、`address`、`port`、`username`、
`last_test_status`、`last_tested_at` 或 `retired_at` 升降序排列；空值始终置后，相同值以
`host_id` 升序稳定分页。页面更改排序字段或方向时会回到第一页，并把排序参数交给服务端。

资产响应包含 `source_node_connectivity_status`。来源 Node 为 `stale` 时，页面显示
“数据延迟（来源节点心跳延迟）”；来源 Node 为 `offline` 时，页面显示
“状态未知（来源节点离线）”。两种情况下仍保留最后检测状态、标准错误码和检测时间，
避免将历史结果误报为当前健康，又不丢失排障线索。

HMAC 认证不加密心跳正文；明文 HTTP 会暴露节点身份、内网地址、用户名和标签。Athena
只支持防火墙、VLAN 或 VPN 隔离的可信管理网络，不提供 HTTPS/TLS 保密性。当前第一阶段
Master 响应未签名，不能作为生产远程执行授权；第二阶段将使用 Ed25519 响应签名和
Prepare/Activate 信封。详见[Master 与接入节点协议](../docs/api/master-node-protocol.md)。

## 健康概览

管理员接口 `GET /api/v1/overview` 返回接入节点管理状态、连接状态和在管资产健康汇总。
待审批与已拒绝数量按尚无正式身份的唯一 Node ID 的最新申请状态统计；重复和历史申请
不会重复计数。已启用与已禁用数量来自正式接入节点。连接状态只统计正式接入节点，并
沿用少于 120 秒在线、120–300 秒延迟、超过 300 秒离线的边界。

资产统计只包含在管资产：仅在线 Node 最近上报为 `failed` 的资产计入明确异常；离线
Node 下的资产计入状态未知；心跳延迟 Node 的资产不冒充当前异常或正常。统计直接在
数据库内聚合，不读取全部节点或资产记录。系统概览、节点列表和当前资产页每 30 秒
刷新，注册审批、拒绝/恢复以及节点管理操作成功后会立即使概览失效并重新获取。

## 操作审计

管理员接口 `GET /api/v1/audit-logs` 提供只读、服务端分页的操作审计，页面按浏览器
时区显示时间并明确标注时区。每条记录包含 UTC 时间、操作者、动作、目标、结果、
来源 IP 和失败机器码。当前记录以下动作的成功与失败：

- 管理员登录、账号创建、启用/禁用和密码重置；未认证登录失败不会把提交者标记为
  已验证操作者，账号存在与否使用相同的失败响应。
- 注册申请批准、拒绝和恢复。
- 接入节点启用/禁用、Token 更换和管理信息修改。

成功动作的业务变更与审计记录在同一数据库事务提交；失败动作在业务事务回滚后记录。
审计模型不接收请求正文或任意详情字典，因此管理员密码、JWT、Node Token 明文、
密文、指纹、注册原始正文和签名没有写入路径，也不会由 API 或页面返回。Node 注册
提交/状态查询、心跳、正常资产同步、概览查询和周期连接状态推导不写审计，避免产生
机器流量噪声。

数据库引擎隐藏 SQL 参数；可恢复的数据库异常只记录通用异常类型，不记录 SQL、绑定
参数或堆栈，避免凭据密文、Token 指纹等敏感数据库值通过服务日志泄露。

第一阶段审计不提供写入、删除、导出、报表、复杂检索或自动清理接口，也不使用轮询。
页面每次进入时重新读取最新记录。

## 运行边界

第一阶段仅支持单进程、单 worker、单实例和本地 SQLite。SQLite 启用 WAL、外键和
5 秒 busy timeout；数据库必须位于本机磁盘，不能放在网络文件系统。启动多个 Master
实例或 worker 不受支持。

管理界面拒绝第三方脚本和内联脚本属性；Vite 开发所需的 React Refresh 启动片段只通过
固定 SHA-256 内容哈希放行，不开放任意内联脚本。Vite 开发/预览服务发送 CSP 响应头，
静态 `index.html` 也带有等价的脚本约束。Ant Design 运行时样式需要
`style-src 'unsafe-inline'`，该例外不适用于脚本。生产反向代理必须发送或保留同等 CSP
响应头，尤其是只能由响应头生效的 `frame-ancestors 'none'`；启动冒烟会计算实际内联
片段哈希并校验关键指令，依赖升级改变启动片段时必须同步审查 CSP 哈希。

正式运行前必须先执行：

```powershell
cd Athena-Master\api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1
```

可从 `Athena-Master\ui` 运行真实启动冒烟；脚本使用临时 SQLite 和动态端口，依次验证
全部迁移、初始化管理员登录、API 健康检查、UI 以及 UI 到 API 的代理链路，并在退出时
清理子进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-start-dev.ps1
```

升级时固定先 Master、后 Node：停止两端服务并成套备份数据库与凭据密钥；升级 Master
并执行迁移、单 worker 启动和健康检查后，再升级 Node、执行迁移并确认首次心跳与完整
资产快照。回滚时数据库、密钥和程序必须成套恢复。

第一阶段不包含 Master Docker Compose、制品/任务下发、远程执行、Master 回连或
WebSocket、RBAC、高可用、多实例/多 worker 及跨 Node 资产合并。

## 可重复的第一阶段验收

在已安装两端开发依赖和 UI 依赖的仓库根目录按顺序运行；Node API 全量测试包含真实
TCP 的 Node–Master 注册、审批、心跳和资产生命周期集成用例：

```powershell
cd Athena-Node\api
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest -q

cd ..\..\Athena-Master\api
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest -q

cd ..\..\Athena-Node\ui
npm test -- --run
npm run lint
npm run typecheck
npm run build

cd ..\..\Athena-Master\ui
npm test -- --run
npm run lint
npm run typecheck
npm run build
powershell -ExecutionPolicy Bypass -File .\scripts\test-start-dev.ps1
```

节点通信接口见[Master 与接入节点协议](../docs/api/master-node-protocol.md)，后续工作见
[任务清单](../TASKS.md)。CI/CD 的权威范围与实施顺序分别见
[第二阶段设计](../docs/superpowers/specs/2026-08-04-athena-cicd-design.md)和
[第二阶段实施计划](../docs/superpowers/plans/2026-08-04-athena-cicd.md)。

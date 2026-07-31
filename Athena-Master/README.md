# Athena-Master

Athena-Master 是 Athena 的中心管理节点。当前已提供 FastAPI 后端、React 管理界面、
SQLite/Alembic 持久化、管理员认证与账号管理、完整节点注册生命周期、健康检查和
Windows 本地开发入口。心跳、资产汇总和审计仍由后续需求实现。

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

## 运行边界

第一阶段仅支持单进程、单 worker、单实例和本地 SQLite。SQLite 启用 WAL、外键和
5 秒 busy timeout；数据库必须位于本机磁盘，不能放在网络文件系统。启动多个 Master
实例或 worker 不受支持。

正式运行前必须先执行：

```powershell
cd Athena-Master\api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1
```

节点通信接口见[Master 与接入节点协议](../docs/api/master-node-protocol.md)，后续工作见
[任务清单](../TASKS.md)。

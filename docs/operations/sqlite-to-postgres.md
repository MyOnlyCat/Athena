# Master SQLite 到 PostgreSQL 离线迁移

本文说明如何把 Athena 第一阶段 Master 的 SQLite 数据停机迁移到 PostgreSQL。迁移保留
用户、撤销令牌、注册申请、接入节点、nonce、主机资产和审计记录，并保留原 SQLite
文件作为回退证据。

这不是在线迁移或双写方案。迁移期间必须停止 Master；迁移后的 Master 只接受
`postgresql+asyncpg`。Athena-Node 继续使用自己的 SQLite，不执行本流程。

## 前提与安全边界

- 使用与旧 Master 完全相同的 Credential Encryption Key。更换 Key 会使已加密 Node
  Token 无法校验。
- PostgreSQL 必须为空，或已经是同一 SQLite 来源完整导入且校验通过的结果。工具不会
  合并两套 Master 数据，也不会覆盖有差异的目标行。
- PostgreSQL 先通过当前 Alembic 链升级到唯一 head；应用不会用 `create_all` 补表。
- 迁移工具以只读方式打开 SQLite。无论成功或失败，都不得移动、删除或改写原文件。
- 备份目录、迁移报告、Credential Key 和部署配置都可能包含敏感运维信息，应限制访问。

建议先在隔离 PostgreSQL 上完整演练，再安排生产停机窗口。

## 1. 停止写入并备份

1. 停止旧 Master API，确认没有进程继续写 SQLite。
2. 记录旧程序版本、SQLite 路径、配置来源和当前 UTC 时间。
3. 把 SQLite、Credential Key 和部署配置备份到同一个受保护目录。Credential Key
   应从原 Secret 管理方式导出，不要粘贴到命令历史或迁移报告。
4. 记录原文件 SHA-256，迁移后再次计算并比较。

PowerShell 示例：

```powershell
$source = (Resolve-Path 'D:\athena-master\data\athena-master.db').Path
$backup = 'D:\athena-backups\phase1-to-postgres-20260808'
New-Item -ItemType Directory -Path $backup -ErrorAction Stop
Get-FileHash -Algorithm SHA256 -LiteralPath $source |
    Format-List | Out-File (Join-Path $backup 'source-before.sha256.txt')
```

后续迁移命令的 `--backup-dir` 还会在写 PostgreSQL 前保存源数据库证据；这不替代对
Credential Key 和部署配置的协调备份。

## 2. 准备 PostgreSQL

生产 Compose 只包含 `postgres` 和 `master-api`。API 容器不挂载 Docker Socket，启动
命令会先执行 `alembic upgrade head`，成功后才启动单 worker Uvicorn。

从仓库根目录复制 `.env.example` 为未纳入版本控制的 `.env`，替换所有占位秘密，并确保
容器内数据库 URL 的主机名为 `postgres`：

```text
ATHENA_MASTER_DATABASE_URL=postgresql+asyncpg://athena_master:URL_ENCODED_PASSWORD@postgres:5432/athena_master
```

先检查配置，只启动 PostgreSQL，并构建迁移 CLI 使用的 API 镜像。此时不要启动
`master-api`；它会初始化管理员并使目标不再为空：

```powershell
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml config --quiet
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml up -d --wait postgres
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml build master-api
```

不要把数据库 URL 或 Credential Key 写进命令参数；两个工具只从以下环境变量读取：

```text
ATHENA_MASTER_DATABASE_URL
ATHENA_MASTER_CREDENTIAL_KEY
```

推荐在一次性 `master-api` 容器内升级并确认只有一个 head，这样 URL 中可以继续使用内部
DNS 名 `postgres`：

```powershell
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml run --rm --no-deps master-api python -m alembic heads
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml run --rm --no-deps master-api python -m alembic upgrade head
```

Master 与 Alembic 默认都固定使用 `public` schema，并共享语句、事务空闲和锁等待超时。
如需使用其他 schema，必须同时设置 `ATHENA_MASTER_DATABASE_SCHEMA`；不要只修改 PostgreSQL
用户的默认 `search_path`。

如果迁移 CLI 改在宿主机运行，则 PostgreSQL 必须通过回环地址或其他受信地址显式开放，
并把当前进程的 `ATHENA_MASTER_DATABASE_URL` 临时改为该地址；生产 Compose 默认不把
PostgreSQL 端口发布到宿主机。

## 3. 在临时 PostgreSQL 演练

测试 Compose 使用固定测试账号、只绑定回环地址，并把数据放在容器 tmpfs。它不能用于
生产数据：

```powershell
docker compose -f Athena-Master\deploy\compose.test.yaml up -d --wait postgres-test
$env:ATHENA_MASTER_DATABASE_URL = 'postgresql+asyncpg://athena_test:athena_test@127.0.0.1:55432/athena_test'
$env:ATHENA_TEST_POSTGRES_URL = $env:ATHENA_MASTER_DATABASE_URL
```

演练结束后删除临时容器及数据：

```powershell
docker compose -f Athena-Master\deploy\compose.test.yaml down --volumes
```

## 4. 预检并导入

`--schema` 默认是 `public`；只有已经为测试隔离创建并授权的 schema 才应传其他值。
以下生产示例把源文件以只读方式、把备份目录以读写方式挂入一次性容器：

```powershell
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml run `
    --rm --no-deps `
    --volume "${source}:/migration/source.db:ro" `
    --volume "${backup}:/migration/backup" `
    master-api python -m app.cli.migrate_sqlite_to_postgres `
    --sqlite /migration/source.db `
    --backup-dir /migration/backup `
    --schema public `
    --report-json /migration/backup/migration-report.json
```

工具会在写入前检查源 schema、目标 Alembic head、目标是否为空或完全一致、外键与唯一
约束，以及 Credential Key 能否解密现有 Node Token。导入在 staging schema 或单个事务
中完成；任一步骤失败都不会向正式目标留下部分数据。

保留原始 ID、UTC 时间、密码 hash、认证版本、原始注册字节、Token 密文与指纹、JSON
标签、nonce 和审计字段。SQLite 中没有时区偏移的历史时间按 UTC 解释，不按宿主机时区
转换。

## 5. 只读校验与重复执行

```powershell
docker compose --env-file .env -f Athena-Master\deploy\compose.yaml run `
    --rm --no-deps `
    --volume "${source}:/migration/source.db:ro" `
    --volume "${backup}:/migration/backup" `
    master-api python -m app.cli.verify_postgres_import `
    --sqlite /migration/source.db `
    --schema public `
    --report-json /migration/backup/verification-report.json
```

校验在 PostgreSQL 只读事务中执行，比较每张表的行数和规范化 SHA-256 摘要，并检查
主键、唯一约束、外键、必填字段和密文可解密性。再次运行校验不得插入、更新或删除行。
再次运行导入时，完全一致的已确认目标只做校验并退出；任何差异都会拒绝执行，而不是
upsert 或覆盖。

再次确认源文件未变化：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath $source | Format-List
```

只有以下结果全部成立才可进入切换：

- Alembic 只有一个 head，模型 metadata 与迁移结果一致。
- 所有表计数、摘要、外键和约束通过。
- 至少一个代表性加密 Node Token 可使用原 Credential Key 解密。
- 原 SQLite 的 SHA-256 未变化，备份副本和两份 JSON 报告均已保存。

## 6. 切换与回退

1. 校验通过后才启动新 Master：
   `docker compose --env-file .env -f Athena-Master\deploy\compose.yaml up -d --wait master-api`。
2. 验证健康检查、管理员登录、注册申请、Node 心跳、资产查询、Token 轮换和审计查询。
3. 确认现有 Node 首次心跳和完整资产快照成功；不要迁移或删除 Node SQLite。
4. 保留原 SQLite、旧程序、Credential Key 和旧配置，直到观察窗口结束。

若切换失败，停止新 Master。回退必须恢复成套的旧程序、原 SQLite、Credential Key 和旧
配置；不能让新程序连接 SQLite，也不能只替换数据库或 Key。由于导入从不修改原
SQLite，可以在确认旧配置后重新启动第一阶段 Master。不要删除失败的 PostgreSQL 或
迁移报告，它们是诊断证据。

## 常见拒绝原因

- `ATHENA_MASTER_DATABASE_URL` 缺失或不是 `postgresql+asyncpg`：显式设置正确 URL。
- PostgreSQL 不在 Alembic head：先运行 `python -m alembic upgrade head`。
- 目标非空且摘要不一致：停止操作，使用新的空数据库或人工调查来源；不要强制覆盖。
- Token 无法解密：恢复原 Credential Key，禁止生成新 Key 后继续导入。
- SQLite 结构未知、残缺或存在孤儿记录：保留原件，先在副本上修复并重新演练。
- 报告写入失败或备份空间不足：迁移不应继续；更换有足够空间且受保护的目录。

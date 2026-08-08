# Athena CI/CD Phase 2 Implementation Plan

> 对应设计：[Athena CI/CD 第二阶段设计](../specs/2026-08-04-athena-cicd-design.md)。每个 Task 都必须先补测试或固定契约，再实现最小通过改动；未运行的检查不得报告为通过。

**Goal:** 在永久单 Master 架构上实现 Master Docker 构建、本地 Artifact Store、一次性预约发布、批准、签名 Node 拉取协议，以及对无代理 Linux Target Host 的可靠文件/目录发布。

**Architecture:** Master API 与本地 Build Worker 共享 PostgreSQL 显式状态表；Worker 独占 Rootless Docker。`ReleaseOrchestration.decide/exchange` 是发布写入的唯一 Interface，查询由独立 `ReleaseQueries` Module 提供。Node 保持 SQLite，通过 HMAC HTTP 长轮询领取 Ed25519 Prepare/Activate，并以 SSH/SFTP 操作 Target Host。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、asyncpg、SQLite、React、TypeScript、Docker Compose、Rootless Docker/BuildKit、Ed25519、SSH/SFTP

## 全局实施规则

- Master 和 Node 任务协议作为一次协调升级交付，开发期直接替换 v1 草案，不做旧任务兼容层。
- Master 正式测试和运行只使用 PostgreSQL；Node 继续使用 SQLite。
- 关系状态表是事实来源；事件只做幂等收件、日志和审计，禁止 Event Sourcing。
- Router 不得直接改 Release 状态表；所有发布写入经过 `decide` 或 `exchange`。
- API 进程不得访问 Docker Socket；只有 Worker 可以访问 Rootless Docker。
- 所有 schema、签名和恢复测试先于远程副作用实现。
- 每个 Task 完成后运行本 Task 的定向测试、静态检查和 `git diff --check`；阶段合并前运行 Master/Node API 与 UI 全量测试。
- 所有日期持久化为 UTC，页面固定使用 `Asia/Shanghai`；不接受浏览器时区作为业务时间。
- 任何真实 SSH/SFTP、Docker、PostgreSQL 或磁盘故障场景无法在开发机运行时，记录明确阻碍并保留集成测试，不得用 mock 结果宣称生产验收。
- 新建 `app/modules`、`adapters`、`workers`、`cli`、`read_models` 及其子目录时同时创建显式 `__init__.py`，不依赖偶然的 namespace package 行为。

---

## Task 0：冻结领域、协议和固定测试向量

**Files**

- Modify: `CONTEXT.md`
- Modify: `docs/api/master-node-protocol.md`
- Modify: `README.md`
- Create: `docs/api/fixtures/v1-prepare-node-task.json`
- Create: `docs/api/fixtures/v1-activate-batch.json`
- Create: `docs/api/fixtures/v1-node-preflight.json`
- Create: `docs/api/fixtures/v1-key-rotation.json`
- Create: `Athena-Master/api/tests/contracts/test_release_directive_vectors.py`
- Create: `Athena-Node/api/tests/contracts/test_release_directive_vectors.py`

**Steps**

- [ ] 固定 Ed25519 domain separator、原始 payload bytes、Base64URL、Key ID、响应签名、bootstrap proof 和 rotation chain 格式。
- [ ] 固定独立 Preflight 信封及结果回传；它不得复用 Release Node Task 或获得副作用权限。
- [ ] 固定 `PrepareNodeTask → target_ready → ActivateBatch`、lease epoch、连续事件 ACK、Artifact Range 和错误码。
- [ ] 固定两端共享 JSON fixtures 及公私钥测试向量；任意字段、Node audience、摘要、lease 或字节变化都应验签失败。
- [ ] 明确不兼容 Node 可以继续心跳/资产上报，但返回 `426 NODE_PROTOCOL_UNSUPPORTED` 且不能领取任务。
- [ ] 删除协议中 IP Target、任意 Artifact URL、单一原样 command、`manual_review`、HTTPS 必选和“未来草案”语义。

**Verification**

```powershell
cd Athena-Master/api
pytest tests/contracts/test_release_directive_vectors.py
cd ../../Athena-Node/api
pytest tests/contracts/test_release_directive_vectors.py
```

Expected: 两端对固定 Prepare、Activate、响应签名和轮换向量得到完全相同结果。

---

## Task 1：Master PostgreSQL 底座与 SQLite 离线迁移

**Files**

- Modify: `Athena-Master/api/pyproject.toml`
- Modify: `Athena-Master/api/alembic.ini`
- Modify: `Athena-Master/api/app/core/config.py`
- Modify: `Athena-Master/api/app/core/database.py`
- Modify: `Athena-Master/api/app/main.py`
- Modify: `Athena-Master/api/alembic/env.py`
- Modify: `Athena-Master/api/tests/conftest.py`
- Create: `Athena-Master/api/app/cli/migrate_sqlite_to_postgres.py`
- Create: `Athena-Master/api/app/cli/verify_postgres_import.py`
- Create: `Athena-Master/api/tests/postgres.py`
- Create: `Athena-Master/api/tests/test_sqlite_postgres_migration.py`
- Create: `Athena-Master/api/tests/test_alembic_metadata.py`
- Create: `Athena-Master/deploy/compose.yaml`
- Create: `Athena-Master/deploy/compose.test.yaml`
- Create: `docs/operations/sqlite-to-postgres.md`
- Modify: `.env.example`

**Steps**

- [ ] 加入 `asyncpg`；`aiosqlite` 只保留给离线导入工具。
- [ ] 让 `alembic.ini` 的默认 URL 成为不可运行占位；migration/test 必须显式提供 PostgreSQL URL，避免误把 SQLite 当作验收库。
- [ ] 让正式 Master 只接受 `postgresql+asyncpg`，配置连接池、transaction timeout 和 statement timeout；生产启动不再 `create_all`，数据库必须在 Alembic head。
- [ ] 删除 test 环境的 `Base.metadata.create_all` 捷径。fixture 为每个 test worker 创建隔离 schema、设置 `search_path`、运行 Alembic head，并在结束后回收。
- [ ] 用 test Compose 提供固定 PostgreSQL；`ATHENA_TEST_POSTGRES_URL` 缺失时集成测试明确失败，不静默退回 SQLite。
- [ ] 在空 PostgreSQL 运行现有 `0001`–`0008`，修正 SQLite 专属 SQL 和类型。
- [ ] 在 Alembic head 后运行 metadata comparison，ORM 与 migration 有差异时失败。
- [ ] 把全部 Master 测试切到隔离 PostgreSQL schema，并验证注册、审批、心跳、资产、Token 轮换和审计无回归。
- [ ] 实现停机离线导入：先备份 SQLite、Credential Key 和配置，再导入原 ID、UTC 时间、Token 密文/指纹、资产和审计；校验计数、约束、外键与密文可解密性。
- [ ] 导入写 staging schema 或单事务；中断后可安全重跑，不修改原 SQLite。
- [ ] 初版 Compose 只启动 `postgres` 和 `master-api`，用于阶段验收。

**Verification**

```powershell
docker compose -f Athena-Master\deploy\compose.test.yaml up -d postgres-test
$env:ATHENA_TEST_POSTGRES_URL = 'postgresql+asyncpg://athena_test:athena_test@127.0.0.1:55432/athena_test'
cd Athena-Master/api
pytest tests/test_sqlite_postgres_migration.py tests/test_registration_applications.py tests/test_heartbeats.py tests/test_asset_snapshots.py tests/test_audit.py
pytest tests/test_alembic_metadata.py
$env:ATHENA_MASTER_DATABASE_URL = $env:ATHENA_TEST_POSTGRES_URL
alembic upgrade head
```

Expected: 第一阶段数据和 API 全部在 PostgreSQL 通过；正式配置为 SQLite 时 Master 拒绝启动。

---

## Task 2：RBAC、Project、Credential Grant 与 Host Grant

**Files**

- Create: `Athena-Master/api/alembic/versions/0009_rbac_projects.py`
- Create: `Athena-Master/api/alembic/versions/0010_credentials_host_grants.py`
- Create: `Athena-Master/api/app/models/rbac.py`
- Create: `Athena-Master/api/app/models/project.py`
- Create: `Athena-Master/api/app/models/credential.py`
- Create: `Athena-Master/api/app/schemas/rbac.py`
- Create: `Athena-Master/api/app/schemas/project.py`
- Create: `Athena-Master/api/app/schemas/credential.py`
- Create: `Athena-Master/api/app/services/authorization.py`
- Create: `Athena-Master/api/app/services/projects.py`
- Create: `Athena-Master/api/app/services/credentials.py`
- Create: `Athena-Master/api/app/api/v1/projects.py`
- Create: `Athena-Master/api/app/api/v1/platform.py`
- Modify: `Athena-Master/api/app/api/deps.py`
- Modify: `Athena-Master/api/app/services/auth.py`
- Modify: `Athena-Master/api/app/services/audit.py`
- Modify: `Athena-Master/api/app/models/__init__.py`
- Modify: `Athena-Master/api/app/main.py`

**Steps**

- [ ] 建立 `permissions`、`roles`、`role_permissions`、平台/Project scope 的 role assignment、`projects` 和 `project_members`。
- [ ] 建立加密 `credentials`/version、`credential_grants`、`project_host_grants`、静态 `host_groups` 和 `project_variables`。
- [ ] 以设计规格冻结的机器权限码为数据库种子和唯一授权契约；UI route/button 与 API tests 直接断言权限码，不根据角色显示名推断。
- [ ] 把旧管理员迁移为 `platform_admin`；种子模板不替代后端细粒度权限检查。
- [ ] 区分 Credential 的 use/read/manage；API 响应永不包含密文，审计只记录 credential ID/version。
- [ ] Project API 只能返回和选择已授权 Host、Host Group、Cache 和 Credential。
- [ ] 让自批满足：创建人与批准人可以相同，但必须具备 `release.approve` 且调用两个不同命令。

**Tests**

- Create: `Athena-Master/api/tests/test_authorization.py`
- Create: `Athena-Master/api/tests/test_projects.py`
- Create: `Athena-Master/api/tests/test_credential_grants.py`
- Create: `Athena-Master/api/tests/test_host_grants.py`

**Verification**

```powershell
cd Athena-Master/api
pytest tests/test_authorization.py tests/test_projects.py tests/test_credential_grants.py tests/test_host_grants.py tests/test_auth.py
```

Expected: 权限撤销立即阻止新动作，Project 成员不能引用未授权资源，任何读接口都不泄露凭据。

---

## Task 3：Source、Build Configuration 与平台构建资源

**Files**

- Create: `Athena-Master/api/alembic/versions/0011_build_definitions.py`
- Create: `Athena-Master/api/app/models/build.py`
- Create: `Athena-Master/api/app/schemas/build.py`
- Create: `Athena-Master/api/app/services/source_configurations.py`
- Create: `Athena-Master/api/app/services/build_configurations.py`
- Create: `Athena-Master/api/app/services/builder_images.py`
- Create: `Athena-Master/api/app/services/build_caches.py`
- Create: `Athena-Master/api/app/adapters/git_remote.py`
- Create: `Athena-Master/api/app/adapters/registry_manifest.py`
- Create: `Athena-Master/api/app/api/v1/build_configurations.py`
- Modify: `Athena-Master/api/app/api/v1/platform.py`
- Modify: `Athena-Master/api/app/models/__init__.py`
- Modify: `Athena-Master/api/app/main.py`

**Steps**

- [ ] 建立一个 Project 一套启用 Source Configuration、多套 Build Configuration 和不可变 Version。
- [ ] 通过只读 `GitRemoteAdapter` 支持 branch/tag/commit 解析为完整 SHA、浅/完整历史、递归 submodule 和 Git LFS；Git LFS 关闭却检出 pointer 时明确失败。Git HTTPS/SSH Credential 分离于 Registry Credential。
- [ ] 通过 Registry manifest resolver 固定 Builder Image Digest；Task 5 的 checkout/build Adapter 复用这些解析结果，不能在 Worker 启动时重新解析移动 Tag。
- [ ] 建立不可变 Digest 的 Builder Image Version 和管理员登记 Cache Volume/Project Grant。
- [ ] Build Configuration Version 保存模块目录、镜像或 Dockerfile、shell、多行脚本、资源/超时、Cache refs、变量 refs、Artifact Glob 和固定文件名。
- [ ] 实现 draft/preflight/enable/archive；预检只验证输入和访问，不运行实际构建。
- [ ] 对停用 Credential/Image/Cache 传播 `invalid_dependency`：禁止新 Build Run，已排队未开始的 Run 转 `blocked` 并要求重新创建，运行中的 Run 继续，除非管理员显式取消；加入三种状态测试。

**Tests**

- Create: `Athena-Master/api/tests/test_source_configurations.py`
- Create: `Athena-Master/api/tests/test_source_snapshots.py`
- Create: `Athena-Master/api/tests/test_build_configurations.py`
- Create: `Athena-Master/api/tests/test_builder_images.py`
- Create: `Athena-Master/api/tests/test_build_cache_grants.py`

**Acceptance:** 分支移动不改变已解析 Source Snapshot；版本启用后不可改；Project 不能填任意宿主挂载路径。

---

## Task 4：Artifact Store、人工分块上传与保留

**Files**

- Create: `Athena-Master/api/alembic/versions/0012_artifacts_build_runs.py`
- Create: `Athena-Master/api/app/models/artifact.py`
- Modify: `Athena-Master/api/app/models/build.py`
- Create: `Athena-Master/api/app/schemas/artifact.py`
- Create: `Athena-Master/api/app/modules/artifact_store/interface.py`
- Create: `Athena-Master/api/app/modules/artifact_store/module.py`
- Create: `Athena-Master/api/app/adapters/local_artifact_store.py`
- Create: `Athena-Master/api/app/services/artifact_uploads.py`
- Create: `Athena-Master/api/app/services/artifact_retention.py`
- Create: `Athena-Master/api/app/api/v1/artifacts.py`
- Modify: `Athena-Master/api/app/core/config.py`
- Modify: `Athena-Master/api/app/models/__init__.py`
- Modify: `Athena-Master/api/app/main.py`

**Interface**

```python
begin_upload(...)
append_upload(...)
complete_upload(...) -> Artifact
admit_build_output(...) -> Artifact
open_blob(artifact_id, byte_range) -> ByteStream
retain_and_collect(now) -> RetentionReport
```

**Steps**

- [ ] 建立 `artifact_blobs`、`artifacts`、`artifact_upload_sessions`、`artifact_holds`、`build_runs` 和日志索引。
- [ ] 用 SHA-256 内容寻址、临时文件 + fsync + 原子 rename；不信任数据库相对路径越出 Artifact 根目录。
- [ ] 上传采用连续 offset/`Content-Range`，可恢复、可取消、可过期清理；完成后不可覆盖。
- [ ] 直接上传必须绑定 Build Configuration，继承固定名和版本唯一规则，不创建伪 Build Run。
- [ ] 本 Task 先实现 manual pin、上传/入库临时引用和通用 hold primitives；Task 7 接入预约/运行/Unknown/回滚窗口 hold，Task 8 在 Node Task 授权后调用 `open_blob`，此处不伪造尚不存在的 Node Task Adapter。
- [ ] 回收物理文件时保留 `artifact_blobs` tombstone 行和 Artifact provenance，把 `storage_path` 置空并记录 `deleted_at`；不可用 Blob 明确拒绝新 Release。
- [ ] 实现软/硬低磁盘水位：软水位拒绝构建/上传，硬水位只允许安全读取和运维清理。

**Tests**

- Create: `Athena-Master/api/tests/test_artifact_store.py`
- Create: `Athena-Master/api/tests/test_artifact_uploads.py`
- Create: `Athena-Master/api/tests/test_artifact_retention.py`
- Create: `Athena-Master/api/tests/test_artifact_disk_guard.py`

**Acceptance:** 相同内容只存一个 Blob；Artifact 来源仍独立；断点上传续传；受保护 Artifact 永不被清理。

---

## Task 5：Build Run 队列、Build Worker 与完整 Master Compose

**Files**

- Create: `Athena-Master/api/app/worker_main.py`
- Create: `Athena-Master/api/app/workers/build_worker.py`
- Create: `Athena-Master/api/app/workers/maintenance_worker.py`
- Create: `Athena-Master/api/app/adapters/git_checkout.py`
- Create: `Athena-Master/api/app/adapters/buildkit.py`
- Create: `Athena-Master/api/app/adapters/build_logs.py`
- Create: `Athena-Master/api/app/services/build_runs.py`
- Create: `Athena-Master/api/app/api/v1/builds.py`
- Create: `Athena-Master/api/Dockerfile`
- Create: `Athena-Master/ui/Dockerfile`
- Create: `Athena-Master/deploy/nginx.conf`
- Modify: `Athena-Master/deploy/compose.yaml`
- Modify: `Athena-Master/api/app/core/config.py`
- Modify: `.env.example`

**Steps**

- [ ] 创建 Build Run 时解析并锁定 Commit、配置 Version、镜像 Digest，或由 Dockerfile、`.dockerignore`、build arguments 和基础镜像 Digest 组成的内容键，以及 Cache/变量版本和所有限制的完整快照。
- [ ] 用 PostgreSQL `FOR UPDATE SKIP LOCKED` 实现 FIFO、默认全局并发 1；不使用进程内队列。
- [ ] 每次运行创建独立工作区和临时容器，复用 Docker daemon、镜像层及受管 Cache Volume；禁止 Docker Socket 入容器、privileged、DinD、host network 和端口。
- [ ] 支持受管 Builder Image 或 BuildKit 构建的临时镜像，以及显式 BuildKit Secret。
- [ ] Builder layer/临时镜像实施容量与年龄清理；运行中和排队快照引用不可回收。可写 Cache/Workspace 只落在管理员预先配置 hard filesystem/project quota 的路径，不用“监测后终止”冒充硬限制。
- [ ] 强制 CPU/memory/pids/temp disk/timeout；Artifact Glob 恰好一个普通文件才调用 `admit_build_output`。
- [ ] 取消优雅终止后强杀/清理且不登记 Artifact；Worker 恢复清理带标签孤儿并标 `interrupted`，不自动重试。
- [ ] Compose 最终包含 `master-api`、`master-worker`、`postgres`、`master-ui`；只有 Worker 挂 Rootless Docker Socket。

**Tests**

- Create: `Athena-Master/api/tests/workers/test_build_worker.py`
- Create: `Athena-Master/api/tests/workers/test_build_cancellation.py`
- Create: `Athena-Master/api/tests/workers/test_build_recovery.py`
- Create: `Athena-Master/api/tests/integration/test_buildkit_build.py`
- Create: `Athena-Master/api/tests/integration/test_buildkit_cache_retention.py`
- Create: `Athena-Master/api/tests/integration/test_compose_smoke.py`

**Acceptance:** 真实多模块仓库可分别构建两个 Artifact；共享层/缓存但工作区和容器独立；API 容器不存在 Docker Socket。

---

## Task 6：Release Configuration、Node Preflight 与路径所有权

**Files**

- Create: `Athena-Master/api/alembic/versions/0013_release_definitions.py`
- Create: `Athena-Master/api/app/models/release.py`
- Create: `Athena-Master/api/app/schemas/release.py`
- Create: `Athena-Master/api/app/modules/release_configuration/interface.py`
- Create: `Athena-Master/api/app/modules/release_configuration/module.py`
- Create: `Athena-Master/api/app/services/release_preflight.py`
- Create: `Athena-Master/api/app/api/v1/release_configurations.py`
- Modify: `Athena-Master/api/app/models/__init__.py`
- Modify: `Athena-Master/api/app/main.py`

**Steps**

- [ ] 建立 Release Configuration/Version、显式 Host/Host Group selector、Preflight directive/result 和 `managed_target_paths`。
- [ ] 明确 file 模式填写父目录并拼固定文件名；directory 模式填写 Athena 独占最终目录。
- [ ] 用拒绝 `/`/NUL/`..` 的 POSIX 规范化、唯一约束、host advisory transaction lock 和祖先/后代检查拒绝所有权冲突；同一配置的新 Version 可在启用事务中原子接管旧 claim。
- [ ] 配置启用时展开当时 Host Group 做 Preflight/claim；创建 Release 时重新展开为不可变目标。组新增成员必须先补 Preflight/claim，已创建 Release 不变化。
- [ ] 本 Task 只完成 Preflight 严格 schema、请求状态和 In-Memory Adapter；Task 8 接通签名 transport，Task 9 实现 Node executor，在 Task 10 真实验收前 production `enable` 保持 feature gate。
- [ ] 配置 Preflight 仅检查 SSH/指纹、temp create/delete、基础磁盘、工具、内容摘要和首次接管；路径冲突由 Master 判定，实际 Artifact/展开/历史容量在 Prepare 重检。
- [ ] 发现现有文件或非空目录但没有 Athena installation 时返回迁移提示，不自动接管。
- [ ] 身份 address/port/username/fingerprint 改变使预约阻塞，只能取消并基于新身份创建/批准 Release；Node 本地 Credential-only 轮换不改变身份。

**Tests**

- Create: `Athena-Master/api/tests/test_release_configurations.py`
- Create: `Athena-Master/api/tests/test_managed_target_paths.py`
- Create: `Athena-Master/api/tests/test_release_preflight.py`
- Create: `Athena-Master/api/tests/test_target_identity_snapshots.py`

---

## Task 7：ReleaseOrchestration 深 Module 与调度器

**Files**

- Create: `Athena-Master/api/alembic/versions/0014_release_orchestration.py`
- Create: `Athena-Master/api/alembic/versions/0015_release_signing_keys.py`
- Create: `Athena-Master/api/alembic/versions/0016_notifications.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/__init__.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/interface.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/module.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/states.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/snapshots.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/scheduler.py`
- Create: `Athena-Master/api/app/modules/release_orchestration/signing.py`
- Create: `Athena-Master/api/app/read_models/releases.py`
- Create: `Athena-Master/api/app/api/v1/releases.py`
- Create: `Athena-Master/api/app/api/v1/node_tasks.py`
- Create: `Athena-Master/api/app/models/notification.py`
- Create: `Athena-Master/api/app/services/notifications.py`
- Create: `Athena-Master/api/app/api/v1/notifications.py`
- Modify: `Athena-Master/api/app/models/artifact.py`
- Modify: `Athena-Master/api/app/worker_main.py`
- Modify: `Athena-Master/api/app/services/audit.py`
- Modify: `Athena-Master/api/app/main.py`

**Interface**

```python
ReleaseOrchestration.decide(CommandContext, ReleaseIntent) -> DecisionReceipt
ReleaseOrchestration.exchange(AuthenticatedNode, NodeMessage) -> NodeReply
ReleaseQueries.get/list/logs(...) -> read-only projection
```

**Steps**

- [ ] 建立 Release、Approval、Attempt、Batch、Target Attempt、Node Task/Target、lease、event inbox、host reservation、installation、idempotency、signing key 和 notification 表；继续扩展现有 `audit_logs`，不创建同义 `audit_events`。
- [ ] 在 `states.py` 固定唯一合法转换；router 和 scheduler 不能另写转换逻辑。
- [ ] `decide` 实现 Create/Approve/Cancel/ResolveUnknown/ContinueAfterUnknown/RetryFailed；Master Worker 的 scheduler 用 system principal 提交内部 `ReconcileDueReleases`，所有权限/审计/通知与状态同事务，scheduler 不直写表。
- [ ] 创建 Release 时重新展开 Host Group、校验 Preflight/path claim，并固化目标。立即发布固定 `scheduled_at=created_at`；首批必须在 `start_deadline` 前 Activate，批准不延长，首批开始后后续批不再受该 deadline。
- [ ] 调度当前批时同时取得全部 Node Target lane 容量与 Host reservation；每 Node Task 的 `capacity_cost=min(target_count,max_concurrency)`。
- [ ] `exchange` 接收 Prepare ready/staging digest；整批 ready 后在单一事务中记录 `side_effect_authorized`，为每个 Node 保存独立 exact Activate bytes/signature，并为每个 Target 保存独立 activation/checkpoint。
- [ ] 含敏感 environment bundle 的 exact envelope 使用 Credential Key 加密落库，仅摘要/Key ID 可查询；不得进入日志、审计或 read model。
- [ ] 把 scheduled/running/Unknown/current-installation/每逻辑 Release Configuration 最近 N 成功 Artifact hold 接入 Task 4；Blob tombstone 不可创建 Release。
- [ ] Activate 可能送达后 lease 失效只转 Unknown；禁止新 activation、epoch 或自动副作用重试。
- [ ] 批内全成功自动推进；失败/Unknown 停止。Unknown 裁决成功与 Continue 是两个命令。
- [ ] 定向重试新建 Attempt 只含失败 Target，继承原批准快照但要求 `release.retry` 的独立确认/审计和新立即窗口；Rollback 复制历史成功 Release 的 Artifact 与完整配置快照创建新 Release 并重新批准。
- [ ] `ReleaseQueries` 只读显式表和日志索引，不重放 `node_task_events`。

**Tests**

- Create: `Athena-Master/api/tests/release_orchestration/test_decide.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_exchange.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_state_table.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_scheduling.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_batch_barrier.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_leases.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_unknown_resolution.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_targeted_retry.py`
- Create: `Athena-Master/api/tests/release_orchestration/test_read_projection.py`

**Acceptance:** `rg` 不应发现 router 直接更新 Release 表；跨 Node 批次在所有 ready 前没有任何 Activate；签发后断线只会 Unknown。

---

## Task 8：Master–Node v1 安全通道

**Master Files**

- Modify: `Athena-Master/api/app/services/signing.py`
- Modify: `Athena-Master/api/app/services/heartbeats.py`
- Create: `Athena-Master/api/app/services/master_response_signing.py`
- Create: `Athena-Master/api/app/services/signing_key_rotation.py`
- Create: `Athena-Master/api/app/api/v1/node_trust.py`
- Modify: `Athena-Master/api/app/api/v1/node_tasks.py`
- Modify: `Athena-Master/api/app/api/v1/registration_applications.py`
- Modify: `Athena-Master/api/app/services/registrations.py`
- Modify: `Athena-Master/api/app/schemas/heartbeat.py`
- Modify: `Athena-Master/api/app/core/errors.py`
- Modify: `Athena-Master/api/app/main.py`
- Modify: `Athena-Master/deploy/nginx.conf`

**Node Files**

- Modify: `Athena-Node/api/app/services/signing.py`
- Modify: `Athena-Node/api/app/services/master_client.py`
- Create: `Athena-Node/api/app/services/directive_verifier.py`
- Create: `Athena-Node/api/app/services/master_trust.py`
- Modify: `Athena-Node/api/app/core/config.py`
- Modify: `Athena-Node/api/app/main.py`

**Steps**

- [ ] 用 Node Token/HMAC challenge 实现首次公钥 bootstrap；已有 trust anchor 时拒绝静默替换。
- [ ] 普通响应绑定 request nonce、status、path、timestamp 和 exact body 做 Ed25519 验签。
- [ ] Node 信任建立后，无签名的代理/Nginx 5xx 归一为 `MASTER_RESPONSE_UNTRUSTED`，不能确认事件/lease/状态；确保 Node routes 的成功与错误响应都经过签名接线。
- [ ] 实现旧 Key 签新 Key、重叠窗口、完整证书链、Key ID 永不复用、Node ACK 和显式 trust reset；未 ACK Node 的外层响应继续用旧 Key，错过旧 Key 的 Node 进入 `trust_reset_required`。
- [ ] Task claim 最长约 25 秒且等待期间不持有 PostgreSQL transaction/connection；心跳继续独立。
- [ ] 心跳固定 `task_protocol_revision`、capability、Target lane、spool disk 和 accepted Key ID；旧 v1 Node 不能凭 protocol version 领取任务。
- [ ] 接通独立签名 Preflight transport/result；Task 6 的 production enable gate 仅在真实 Node executor 可用后解除。
- [ ] Artifact GET 校验 Node HMAC、Task 归属、lease tuple，支持 Range/ETag；Task 不再接受任意 URL。
- [ ] 只有专用 renew endpoint 能续租，并返回签名 `renewed/fenced/cancel_after_safe_point`；claim/events 不隐式续租。
- [ ] 事件按连续 sequence 幂等接收，ACK 响应签名；Activate 后过期 tuple 的新事件只作为 late evidence，Node 只在验签后删除本地事件。

**Tests**

- Create: `Athena-Master/api/tests/test_node_trust.py`
- Create: `Athena-Master/api/tests/test_node_long_poll.py`
- Create: `Athena-Master/api/tests/test_node_events.py`
- Create: `Athena-Master/api/tests/test_node_artifact_range.py`
- Create: `Athena-Master/api/tests/test_node_preflight_transport.py`
- Create: `Athena-Master/api/tests/test_node_lease_control.py`
- Create: `Athena-Node/api/tests/test_directive_verifier.py`
- Create: `Athena-Node/api/tests/test_master_response_signatures.py`
- Create: `Athena-Node/api/tests/test_master_key_rotation.py`

---

## Task 9：Node 持久状态、Prepare/Activate 与 SSH/SFTP 发布

**Files**

- Create: `Athena-Node/api/alembic/versions/0010_release_protocol_v1.py`
- Create: `Athena-Node/api/alembic/versions/0011_ssh_private_keys.py`
- Rewrite: `Athena-Node/api/app/models/deployment.py`
- Rewrite: `Athena-Node/api/app/schemas/deployment.py`
- Modify: `Athena-Node/api/app/schemas/task.py`
- Modify: `Athena-Node/api/app/services/deployments.py`
- Modify: `Athena-Node/api/app/services/executor.py`
- Modify: `Athena-Node/api/app/services/deployment_gateway.py`
- Modify: `Athena-Node/api/app/services/artifacts.py`
- Modify: `Athena-Node/api/app/services/events.py`
- Modify: `Athena-Node/api/app/services/master_runtime.py`
- Modify: `Athena-Node/api/app/services/inventory_sync.py`
- Modify: `Athena-Node/api/app/services/ssh.py`
- Modify: `Athena-Node/api/app/models/host.py`
- Modify: `Athena-Node/api/app/models/__init__.py`
- Modify: `Athena-Node/api/app/api/v1/tasks.py`
- Modify: `Athena-Node/api/app/main.py`
- Modify: `Athena-Node/api/tests/test_database_upgrade.py`
- Create: `Athena-Node/api/app/services/release_preparer.py`
- Create: `Athena-Node/api/app/services/release_activator.py`
- Create: `Athena-Node/api/app/services/archive_extractor.py`
- Create: `Athena-Node/api/app/services/history_retention.py`
- Create: `Athena-Node/api/app/services/disk_guard.py`

**Steps**

- [ ] 迁移开发期 deployment 表为 `node_tasks`、`target_attempts`、`node_events`、`trusted_master_keys`、`executed_directives`、`artifact_parts`、`managed_installations` 和本地安装历史/manifest，保留用户、Host 和 Master 设置，并更新 upgrade head 断言。
- [ ] 把运行时拆为心跳、25 秒 task poll、lease renew、event delivery；Node 低磁盘停止 claim 但继续事件投递。
- [ ] 实现严格 Preflight executor/result，只探测身份、工具、基础容量、内容和 temp create/delete，不运行脚本或修改正式路径。
- [ ] Prepare 验签并持久化后，按 `host_id` 查 Host，核对 address/port/username/fingerprint；使用当前本地加密 SSH Credential。
- [ ] 含敏感 environment bundle 的原始信封用 Node Credential Key 加密落库；日志、Task API 和只读 UI 只返回名称/digest，不返回值。
- [ ] Artifact Range 下载到 `.part`，严格验证 offset/ETag/size/SHA；同一 Node Task 下载一次并 fan-out。
- [ ] SFTP staging 绑定 `target_attempt_id + lease_epoch`，旧 epoch 不能写/清理新路径；ready 上报 staging/current digest，支持同 lease 安全续传。
- [ ] 每个 Target Attempt 独立幂等持久化 activation；相同 exact envelope 重投只返回 checkpoint，同 ID 不同 bytes 拒绝。在发布前脚本、备份或替换中最早的外部修改前写 `side_effect_started`，命令无自动重试。
- [ ] file 模式只管理固定文件；directory 模式只接受 zip/tar.gz/tgz，拒绝绝对路径、`..`、device、hardlink、symlink，并整体替换目录。
- [ ] 首次非空目标拒绝接管；外部漂移阻断；历史只保留最近 N 个成功版本。
- [ ] 副作用后 SSH/Node 重启或结果不可证实转 Unknown；不重新执行。Master 连续 ACK 最终事件后删除本地 Artifact。

**Tests**

- Rewrite: `Athena-Node/api/tests/test_deployments.py`
- Rewrite: `Athena-Node/api/tests/test_artifacts.py`
- Rewrite: `Athena-Node/api/tests/test_event_delivery.py`
- Create: `Athena-Node/api/tests/test_prepare_activate_barrier.py`
- Create: `Athena-Node/api/tests/test_sftp_resume.py`
- Create: `Athena-Node/api/tests/test_file_release.py`
- Create: `Athena-Node/api/tests/test_directory_release.py`
- Create: `Athena-Node/api/tests/test_archive_security.py`
- Create: `Athena-Node/api/tests/test_drift_detection.py`
- Create: `Athena-Node/api/tests/test_unknown_recovery.py`
- Create: `Athena-Node/api/tests/test_low_disk_guard.py`
- Create: `Athena-Node/api/tests/test_ssh_private_key_auth.py`

---

## Task 10：跨端集成与故障矩阵

**Files**

- Create: `Athena-Master/api/tests/integration/test_master_node_release.py`
- Create: `Athena-Master/api/tests/integration/test_cross_node_batch.py`
- Create: `Athena-Master/api/tests/integration/test_lost_activation_response.py`
- Create: `Athena-Master/api/tests/integration/test_release_restart_matrix.py`
- Create: `Athena-Master/api/tests/integration/test_target_ssh_release.py`
- Create: `Athena-Master/api/tests/integration/compose.yaml`
- Create: `Athena-Master/api/tests/integration/conftest.py`
- Create: `Athena-Master/api/tests/integration/ssh-target/Dockerfile`
- Modify: `Athena-Master/api/pyproject.toml`

**Steps**

- [ ] 用专用 test Compose 建立 PostgreSQL、Master、两个真实 Node 进程和两个容器化 SSH Target；固定隔离 network、测试 Host Key/Credential、volume 和故障注入控制点。
- [ ] 注册 `integration` 与 `acceptance` pytest marker：默认快速测试不依赖 Docker；integration 运行真实 PG/SSH/BuildKit；acceptance 运行完整 Compose/故障矩阵。环境缺失必须明确 fail/skip reason，普通 `pytest` 通过不能冒充 acceptance。
- [ ] 覆盖立即/预约、file/directory、跨 Node batch、前后脚本、失败停止、定向重试和 Rollback Release。
- [ ] 在 claim、Range、ready、Activate commit/response、side-effect checkpoint、SSH、event ACK 各位置注入断线与进程重启。
- [ ] 证明 Activate 前可安全恢复，Activate 可能送达后不重复副作用且无法证明时为 Unknown。
- [ ] 保持旧 epoch SFTP writer 在 fencing 后继续写，证明 lease-isolated staging 不能污染新 epoch；重投相同 Activate 只返回 checkpoint，同 ID 不同 bytes 被拒绝。
- [ ] 覆盖 Host identity change、Credential-only rotation、漂移、首次接管、磁盘不足、日志截断和 Node 事件积压。

**Acceptance:** 每个故障点只有一个可解释状态和一个允许的恢复动作；不存在“失败后自动重跑远程命令”。

---

## Task 11：Master 项目化 UI、Node 只读 UI 与站内通知

**Master UI Files**

- Modify: `Athena-Master/ui/src/app/AppRouter.tsx`
- Modify: `Athena-Master/ui/src/app/AppShell.tsx`
- Modify: `Athena-Master/ui/src/features/auth/AuthContext.tsx`
- Modify: `Athena-Master/ui/src/shared/api/client.ts`
- Modify: `Athena-Master/ui/src/shared/api/types.ts`
- Create feature directories: `Athena-Master/ui/src/features/projects/`, `builds/`, `artifacts/`, `releases/`, `platform/`, `notifications/`
- Create: `Athena-Master/ui/src/shared/time/chinaTime.ts`

**Node UI Files**

- Modify: `Athena-Node/ui/src/features/tasks/TasksPage.tsx`
- Modify: `Athena-Node/ui/src/features/tasks/TaskStatus.tsx`
- Modify: `Athena-Node/ui/src/shared/api/client.ts`
- Modify: `Athena-Node/ui/src/shared/api/types.ts`

**Steps**

**11A — Project/RBAC/平台资源**

- [ ] 实现 Source/Build/Release/Variables/Grants/Members，以及 Builder Image、Cache、Credential、Host Group、签名 Key 状态和平台限制；页面直接按稳定权限码控制 route/button，后端继续独立拒绝越权。

**11B — Build/Artifact**

- [ ] 实现构建队列/取消/日志、Artifact 分块上传、Blob availability、hold/pin 和保留诊断。

**11C — Release/Unknown**

- [ ] 实现创建、Preflight 迁移提示、快照审阅、批准、预约、Batch/Node/Target 层级、Unknown 裁决、独立继续、定向重试和复制历史快照的回滚。

**11D — Node 只读/通知/全局规则**

- [ ] Node Task 页面只读展示 Prepare、等待 Activate、每目标 checkpoint、Unknown、日志、磁盘和连接诊断。
- [ ] 首版只实现 Task 7 已提供的站内通知和已读状态，不接 Webhook、邮件或聊天工具。
- [ ] 所有业务时间固定按中国标准时间输入/显示并明确标注 UTC+8，API 发送 UTC；HTTP 模式持续显示明文风险警告。

**Tests**

- Create: `Athena-Master/ui/tests/projects.test.tsx`
- Create: `Athena-Master/ui/tests/builds.test.tsx`
- Create: `Athena-Master/ui/tests/artifact-upload.test.tsx`
- Create: `Athena-Master/ui/tests/releases.test.tsx`
- Create: `Athena-Master/ui/tests/release-approval.test.tsx`
- Create: `Athena-Master/ui/tests/unknown-resolution.test.tsx`
- Create: `Athena-Master/ui/tests/permissions.test.tsx`
- Create: `Athena-Master/ui/tests/china-time.test.ts`
- Modify: `Athena-Node/ui/tests/tasks.test.tsx`

---

## Task 12：自动清理、日志、备份恢复与生产切换

**Files**

- Create: `Athena-Master/api/app/cli/backup.py`
- Create: `Athena-Master/api/app/cli/restore.py`
- Create: `Athena-Master/api/app/cli/verify_backup.py`
- Create: `docs/operations/backup-restore.md`
- Create: `docs/operations/master-compose.md`
- Create: `docs/operations/coordinated-upgrade.md`
- Modify: `Athena-Master/deploy/compose.yaml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Steps**

- [ ] 维护 Worker 清理上传会话、孤儿工作区、Blob physical content、超期日志、Dockerfile 临时 Builder Image 和 BuildKit cache；尊重全部 Artifact hold、运行/排队引用和审计保留。
- [ ] Compose 固定 Rootless Docker 的宿主 UID、`XDG_RUNTIME_DIR`、socket 权限、Worker CLI/buildx 和 quota-capable workspace/cache volume；API 不挂 socket。
- [ ] 备份 PostgreSQL、Artifact、日志、Ed25519 Key Ring、Credential Key、配置清单并生成 SHA-256 manifest。
- [ ] 恢复 CLI 在停机状态验证版本和 manifest，整套原子切换；拒绝局部恢复。
- [ ] 编写协调升级：冻结新 Build/Release → 旧 SQLite/Node/密钥备份 → PG 导入 → Master release disabled 启动 → Worker 验证 → 逐 Node 升级/trust → 跨 Node smoke → 开启 release。
- [ ] 在隔离目录执行完整恢复演练，再允许生产切换。

**Tests**

- Create: `Athena-Master/api/tests/operations/test_backup_restore.py`
- Create: `Athena-Master/api/tests/operations/test_coordinated_upgrade.py`
- Create: `Athena-Master/api/tests/integration/test_phase_two_acceptance.py`

**Final Verification**

```powershell
cd Athena-Master/api
docker compose -f ../deploy/compose.test.yaml up -d postgres-test
$env:ATHENA_TEST_POSTGRES_URL = 'postgresql+asyncpg://athena_test:athena_test@127.0.0.1:55432/athena_test'
pytest -m "not integration and not acceptance"
docker compose -f tests/integration/compose.yaml up -d --build
pytest -m integration
pytest -m acceptance
docker compose -f tests/integration/compose.yaml down
docker compose -f ../deploy/compose.test.yaml down
ruff check .
mypy app
cd ../ui
npm test -- --run
npm run typecheck
npm run lint
npm run build

cd ../../Athena-Node/api
pytest -m "not integration and not acceptance"
ruff check .
mypy app
cd ../ui
npm test -- --run
npm run typecheck
npm run lint
npm run build

cd ../../
docker compose -f Athena-Master/deploy/compose.yaml config --quiet
git diff --check
```

最终验收以设计规格第 18 节全部场景为准。全部场景、完整备份恢复和真实 SSH/Docker/PostgreSQL 集成均有证据后，才能把 Phase 2 标记为可生产部署。

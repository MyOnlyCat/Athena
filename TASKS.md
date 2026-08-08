# Athena 任务清单

## 仓库迁移

- [x] 保留 Athena-Node 既有 Git 历史
- [x] 将 Git 根目录提升到 Athena 层级
- [x] 将组件代码归入 `Athena-Node/` 和 `Athena-Master/`
- [x] 将详细文档集中到根级 `docs/`
- [x] 完成迁移后的全量验证
- [x] 推送到 `MyOnlyCat/Athena`

## Athena-Node

- [x] Python/FastAPI、SQLite 与 Alembic 基础工程
- [x] 管理员登录、退出、创建/禁用用户与重置密码
- [x] SSH 主机增删改查、凭据加密、连接测试与指纹确认
- [x] Web SSH 一次性票据、二进制终端和应用内全屏
- [x] 远程路径导航、文件操作、三文件并发上传和浏览器下载
- [x] 主节点配置读取、测试、加密保存和运行时即时替换
- [x] 节点资产汇报、任务轮询、制品校验和发布进度回传
- [x] 任务记录、事件详情和操作审计页面
- [x] Docker Compose、Nginx 和持久化数据卷
- [x] 本地 API、WebSocket、主从节点协议和文件传输文档
- [ ] 修复或稳定化 `terminal-fullscreen.test.tsx` 的五秒超时
- [ ] 在真实 SSH 主机和主节点环境中完成端到端验证
- [ ] 完成生产部署、安全加固和运维验收

## Athena-Master

- [x] 建立可登录的 Master 基础应用、SQLite 迁移、中文 UI 外壳和本地启动入口
- [x] 提供服务端分页的管理员账号创建、启停、密码重置和全量 JWT 撤销
- [x] 明确第二阶段领域模型、持久化方案和架构决策
- [x] 实现节点注册、认证、心跳和资产汇总
- [x] 提供接入节点与主机资产健康概览
- [x] 提供安全敏感操作审计和只读分页管理页面
- [ ] 实现制品管理、发布编排和任务调度
- [ ] 实现发布事件汇总和管理界面
- [x] 建立与 Athena-Node 协议的端到端测试
- [ ] 提供容器部署、升级和灾难恢复文档

## CI/CD 第二阶段

权威设计见 [CI/CD 第二阶段设计](docs/superpowers/specs/2026-08-04-athena-cicd-design.md)，
落地顺序见 [实施计划](docs/superpowers/plans/2026-08-04-athena-cicd.md)。以下均为待实施，
不因设计完成而标记为功能完成。

- [x] 完成领域词汇、关键 ADR、v1 协议安全模型和实施拆分
- [ ] 将 Master 生产数据库切换到 PostgreSQL，并提供旧 SQLite 离线迁移
- [ ] 实现 Project、细粒度 RBAC、Credential Grant 和 Host Grant
- [ ] 实现 Source/Build Configuration、Builder Image 与 Build Cache Volume
- [ ] 实现本地内容寻址 Artifact Store、人工分块上传和自动保留清理
- [ ] 实现独立 Build Worker、Rootless Docker 构建和完整 Master Compose
- [ ] 实现 Release Configuration、Node Preflight、目标路径所有权和漂移检查
- [ ] 实现 `ReleaseOrchestration.decide/exchange`、预约、批准、批次和 Unknown
- [ ] 实现 Ed25519 Prepare/Activate、任务长轮询、lease fencing、Range 与连续事件 ACK
- [ ] 重构 Node 文件/目录发布、SSH 私钥认证、安全解压和本地历史保留
- [ ] 实现 Master 项目化 UI、站内通知和 Node 只读诊断 UI
- [ ] 完成跨 Node 故障矩阵、成套备份恢复和生产切换验收

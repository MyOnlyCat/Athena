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

- [ ] 明确主节点领域模型和持久化方案
- [ ] 实现节点注册、认证、心跳和资产汇总
- [ ] 实现制品管理、发布编排和任务调度
- [ ] 实现发布事件汇总、审计和管理界面
- [ ] 建立与 Athena-Node 协议的端到端测试
- [ ] 提供容器部署、升级和灾难恢复文档

# Athena-Node

Athena-Node 是部署在目标网络中的子节点，负责管理本节点可访问的 SSH 主机，提供
网页终端和 SFTP 文件管理，并从 Athena-Master 领取制品发布任务。

当前版本已部分完成，包含 API、管理界面和容器部署配置；仍需真实环境集成验证和
生产验收。

## 快速入口

- Docker Compose：在 Athena 仓库根目录执行 `docker compose up -d --build`。
- Windows 本地开发：运行 `ui\start-dev.cmd`。
- API：Python 3.12，项目位于 `api/`。
- UI：Node.js 22，项目位于 `ui/`。

## 文档

- [Athena 项目总览](../README.md)
- [本地 API](../docs/api/local-api.md)
- [WebSocket 协议](../docs/api/websocket-protocol.md)
- [主从节点协议](../docs/api/master-node-protocol.md)
- [OpenAPI JSON](../docs/api/openapi.json)
- [文件传输指南](../docs/node/file-transfers.md)
- [统一样式规范](../docs/node/style-guide.md)
- [任务清单](../TASKS.md)
- [更新日志](../CHANGELOG.md)

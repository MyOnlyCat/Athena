# Athena-Node

Athena-Node 是部署在目标网络中的子节点，负责管理本节点可访问的 SSH 主机，提供
网页终端和 SFTP 文件管理，并从 Athena-Master 领取制品发布任务。

当前版本已部分完成，包含 API、管理界面和容器部署配置；仍需真实环境集成验证和
生产验收。

## 申请接入 Master

在“主节点配置”页面填写 Master 地址与 32–256 字符的节点独占 Token。可以使用页面
生成 32 随机字节的 Base64URL Token；生成值只在当前输入框显示，应立即通过可信渠道
交给 Master 管理员。

“保存并应用”不要求节点已获批准；“连接测试”通过 Master 公共健康接口检查候选地址，
不保存配置；修改表单后必须先“保存并应用”，才能点击“申请接入”。申请正文经过签名
且不包含 Token。提交成功后页面显示“待管理员审批”。Master 管理员输入同一 Token
审批成功后，Node 会主动发送签名状态查询并显示“已批准”，不需要 Master 回连 Node。
待审批时每 60 秒查询一次。申请被拒绝后页面显示“已拒绝”并停止自动申请；管理员在
Master 恢复资格后，Node 管理员需点击“申请接入”手动重新提交。过期、限流、容量和
其他注册错误均保留 Master 的稳定错误码与中文提示。

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

Windows 启动器会在启动 API 前执行数据库迁移。对于历史版本通过 SQLAlchemy
`create_all` 创建、但尚无 `alembic_version` 的完整旧库，启动器会先生成
`.pre-alembic-0007_node_identity.bak` 备份，验证结构与 `0007` 完全匹配后再建立
基线并升级。无法识别的结构会拒绝自动修改，并提示人工检查。

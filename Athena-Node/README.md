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

获批后，Node 在心跳中发送本地完整主机清单，包括 Node 内主机 ID、名称、地址、端口、
用户名、标签、本机标记、标准 SSH 检测状态、机器码和 UTC 检测时间。密码、加密凭据
和自由文本连接错误不会进入心跳。主机删除后下一次快照会让 Master 软退役对应资产，
相同主机身份再次出现时会恢复。

获批 Node 正常每 60 秒发送心跳。Master 返回“节点已禁用”或认证失败时，Node 页面
分别显示“已禁用”或“认证失败”，并每五分钟低频探测；重新启用或 Token 配置一致后
自动恢复 60 秒心跳。Master 无法连接时页面显示“连接失败”，Node 使用带抖动的指数
退避，从约 5 秒逐步增加且最长不超过五分钟；一次成功请求会重置退避。待审批状态仍
每 60 秒查询，已拒绝状态停止自动申请并等待管理员恢复后手动重新提交。

手动更换 Token 时，先在 Node 的“主节点配置”页面保存新 Token，再由 Master 管理员在
“接入节点”页面输入相同值。Master 更新成功后旧 Token 立即失效，因此操作可能产生
短暂离线；页面和 API 均不会回显保存后的 Token。

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
基线并升级。当前迁移会继续增加注册状态和标准 SSH 检测码列；无法识别的结构会拒绝
自动修改，并提示人工检查。检测码迁移会从已知检测状态和中文结果安全回填标准机器码；
无法可靠映射的旧检测结果会重置为尚未检测，避免生成 Master 必然拒绝的心跳快照。

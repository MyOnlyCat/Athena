# Athena 单仓库迁移设计

## 目标

将现有 Athena-Node 和尚未开发的 Athena-Master 统一迁移到
`https://github.com/MyOnlyCat/Athena.git`，保留 Athena-Node 的完整 Git
提交历史，并将项目级文档整理到 Athena 仓库根层级。

迁移完成后，Athena-Node 不再是嵌套的独立 Git 仓库；原
`Athena-Node/.git` 中的历史将提升为根目录 `Athena/.git` 的历史。原远程仓库
`MyOnlyCat/Athena-Nod` 不删除、不覆写，作为历史备份保留。

## 目标结构

```text
Athena/
├── .git/
├── .gitignore
├── README.md
├── TASKS.md
├── CHANGELOG.md
├── compose.yaml
├── Athena-Node/
│   ├── README.md
│   ├── api/
│   ├── deploy/
│   └── ui/
├── Athena-Master/
│   └── README.md
└── docs/
    ├── node/
    ├── api/
    └── superpowers/
        ├── plans/
        └── specs/
```

## Git 历史与远程

1. 迁移前提交需要保留的 Athena-Node 未跟踪开发成果。
2. 将 Athena-Node 的 Git 元数据提升到 Athena 根目录。
3. 使用 Git 记录一次明确的目录重组提交，使历史重命名检测可以追踪原文件。
4. 将当前远程重命名为 `athena-node-legacy`，只保留为只读历史来源。
5. 将新的 `origin` 指向 `https://github.com/MyOnlyCat/Athena.git`。
6. 从现有 `feat/athena-node-v1` 历史创建迁移分支，不直接覆写目标默认分支。
7. 推送迁移分支；在 GitHub 上以 `main` 为目标创建合并请求。若空仓库尚不能创建
   合并请求，则将迁移分支作为首个远程分支，并在确认后建立或快进 `main`。

## 代码与未跟踪文件

现有 Athena-Node 的已跟踪代码全部迁入 `Athena-Node/`。

以下未跟踪成果属于当前开发内容，应在迁移前纳入历史：

- `ui/start-dev.cmd`
- `ui/scripts/start-dev.ps1`
- `ui/scripts/test-start-dev.ps1`
- 快速开发启动脚本的设计和实施计划

以下运行产物不进入 Git，并由根级 `.gitignore` 排除：

- `preview-*.log`
- Python 虚拟环境、缓存、数据库和覆盖率输出
- Node.js 依赖、构建输出和 TypeScript 增量文件
- 本地环境变量文件
- 工作树辅助目录

`Athena-Master` 当前没有实现文件。仓库只提交
`Athena-Master/README.md`，明确它的状态、预期职责和暂不提供启动方式，避免用空
目录制造已实现的假象。

## 文档归属

Athena 根目录文档面向整个系统：

- `README.md`：项目定位、当前完成度、目录结构、组件入口和开发状态。
- `TASKS.md`：统一记录 Node 已完成项、Master 待开发项及仓库迁移状态。
- `CHANGELOG.md`：保留既有 Node 更新记录，并增加单仓库迁移条目。

详细文档集中在根级 `docs/`：

- Node 使用和文件传输文档进入 `docs/node/`。
- 本地 API、WebSocket、主从节点协议和 OpenAPI 文件进入 `docs/api/`。
- 设计规格与实施计划统一进入 `docs/superpowers/`。

组件目录中的 README 只说明组件职责、实现状态、启动入口，以及指向根级文档的
相对链接，不复制详细内容。迁移时更新全部相对链接。

## Compose 与路径

根级 `compose.yaml` 继续作为当前可运行 Athena-Node 的部署入口。构建上下文、
Dockerfile、挂载文件和 Nginx 配置路径全部更新为 `Athena-Node/` 下的新位置。

Athena-Master 尚未实现，因此不在 Compose 中添加占位服务。

## 验证

迁移必须完成以下检查：

1. `git status` 仅包含预期迁移变更，运行日志未被跟踪。
2. `git log --follow` 能从新路径追踪到 Athena-Node 既有提交。
3. 根级 README 和组件 README 中的本地链接均指向存在的文件。
4. Compose 配置解析成功，所有构建和挂载路径存在。
5. PowerShell 快速启动脚本通过语法检查和自检。
6. Athena-Node API 测试通过。
7. Athena-Node UI 测试、类型检查、代码规范检查和生产构建通过。
8. 新远程指向 `MyOnlyCat/Athena`，旧远程仅以
   `athena-node-legacy` 名称保留。

依赖或本机工具缺失导致某项无法运行时，应记录具体阻碍；不得把“未运行”描述为
“已通过”。

## 安全与回退

- 不删除或强制推送原 `MyOnlyCat/Athena-Nod` 仓库。
- 不提交 `.env`、密钥、Token、数据库、日志或依赖目录。
- 迁移前记录当前分支和提交 SHA。
- 本地目录重组使用 Git 可追踪的移动；若验证失败，可以从迁移前提交恢复，而不影响
  原远程。
- 目标仓库当前为空，因此不需要合并未知的既有文件；若发布前远程状态发生变化，停止
  推送并重新核对。

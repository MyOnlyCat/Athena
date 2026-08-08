# Athena

Athena 是面向多网络环境的集中构建与无代理发布平台。Master 管理项目、制品和发布意图，Node 代表其所在网络执行目标主机上的发布。

## 项目与构建

**Project（项目）**:
权限、变量、源码和交付配置的协作范围；一个项目可以包含多套模块构建配置。
_Avoid_: 应用、构建配置菜单

**Source Configuration（源码配置）**:
项目访问一个 Git 仓库所需的地址、凭据引用和检出策略。
_Avoid_: Git 用户、代码地址

**Source Snapshot（源码快照）**:
一次构建所绑定的不可变 Git Commit；分支和 Tag 只是解析它的入口。
_Avoid_: 当前分支、最新代码

**Build Configuration（构建配置）**:
从源码快照生成一个主制品的版本化定义；多模块项目以多套构建配置表达。
_Avoid_: Pipeline、流水线、构建任务模板

**Build Run（构建运行）**:
用户针对一套构建配置和源码快照发起的一次不可变构建尝试。
_Avoid_: Build Job、构建任务

**Builder Image（构建镜像）**:
供构建运行执行脚本的受管基础环境，可以来自管理员登记的镜像或项目 Dockerfile。
_Avoid_: Docker、构建容器配置

**Build Cache Volume（构建缓存卷）**:
平台管理员授权给项目复用的构建依赖缓存。
_Avoid_: 宿主目录、共享代码目录

## 制品

**Artifact（制品）**:
一次成功构建或人工上传形成的不可变单文件交付物，具有版本标签和内容摘要。
_Avoid_: 包、上传文件、构建结果文件

**Artifact Blob（制品内容）**:
由内容摘要标识、可被多个制品记录共同引用的物理文件内容。
_Avoid_: 制品缓存

**Artifact Store（制品库）**:
Master 保存制品内容并维护其保留与可回滚性的权威来源。
_Avoid_: Node 缓存、共享目录

## 发布

**Release Configuration（发布配置）**:
一套构建配置如何发布到获授权目标主机的版本化定义，包括目标顺序、批大小、路径和脚本。
_Avoid_: 发布任务模板、环境配置

**Release（发布）**:
将一个已存在制品按照发布配置快照交付到不可变目标清单的用户意图，可立即执行或一次性预约。
_Avoid_: Deployment、发版单、发布任务

**Release Attempt（发布尝试）**:
一次发布或其失败目标重试所产生的独立执行记录。
_Avoid_: 重跑、重新执行原任务

**Release Batch（发布批次）**:
一次发布尝试中允许并行执行、且必须整体就绪后才能开始的一组有序目标。
_Avoid_: 构建批次、波次

**Node Task（Node 任务）**:
Master 从一个发布批次拆分给单个 Node 的已签名执行授权。
_Avoid_: Release、DeploymentTask、远程命令

**Node Preflight（Node 预检）**:
Master 委托 Node 对发布配置的目标身份、路径、工具和容量执行的无副作用检查；它不授予制品替换或脚本执行权限。
_Avoid_: Node Task、试发布

**Target Attempt（目标尝试）**:
Node 通过 SSH/SFTP 在一台目标主机上执行一次制品替换和发布脚本的记录。
_Avoid_: 主机任务、IP 任务

**Rollback Release（回滚发布）**:
选择历史制品创建的新发布，而不是对旧发布执行逆向操作。
_Avoid_: 自动回滚、恢复旧任务

**Unknown Execution（执行状态未知）**:
Master 已授权或系统可能已经跨越目标副作用边界，但无法证明最终结果、因而必须人工裁决的目标状态。
_Avoid_: 可重试失败、超时失败

## 受管基础设施

**Node（接入节点）**:
主动连接 Master、代表一个网络区域并通过 SSH/SFTP 管理其目标主机的执行端。
_Avoid_: Runner、Agent、从节点

**Target Host（目标主机）**:
由一个 Node 管理、无需安装 Athena Agent 的 Linux 主机，以 Node ID 与 Host ID 共同标识。
_Avoid_: 目标 IP、服务器地址

**Build Worker（构建 Worker）**:
属于单 Master 的后台执行角色，消费持久化构建队列并产生制品。
_Avoid_: Build Runner、远程 Runner

**Credential Grant（凭据授权）**:
允许项目使用某项凭据而不获得其明文的授权关系。
_Avoid_: 共享密码、查看权限

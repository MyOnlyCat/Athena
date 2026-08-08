# Master 后端测试

## 使用 start-dev.cmd

从仓库根目录直接运行：

    Athena-Master\ui\start-dev.cmd

首次使用时复制无秘密示例并填写本机内网地址：

    Copy-Item Athena-Master\api\tests\internal-postgres.env.example Athena-Master\api\tests\internal-postgres.env

internal-postgres.env 已被 Git 忽略，不得提交真实账号或密码。当调用方没有显式设置
ATHENA_MASTER_DATABASE_URL 时，启动脚本会读取该本地文件，并使用配置的 schema。脚本会先
创建 schema（如尚不存在），再执行 Alembic 迁移并启动 API 和 UI，不会写入 public schema。

## 运行后端测试

可以设置进程级 ATHENA_TEST_POSTGRES_URL，或复用上述本地 internal-postgres.env。从仓库
根目录运行：

    Athena-Master\api\scripts\test-internal-postgres.ps1

运行单个测试文件时，可以显式传递 pytest 参数：

    Athena-Master\api\scripts\test-internal-postgres.ps1 -PytestArguments @("-q", "tests/test_health.py")

脚本只在子进程运行期间设置 ATHENA_TEST_POSTGRES_URL，不会打印连接地址。测试夹具会创建形如
athena_test_<随机值> 的独立 schema，执行 Alembic 迁移，并在结束后删除该 schema；不会使用或修改
public schema。

直接运行 pytest 时仍要求调用方显式提供 ATHENA_TEST_POSTGRES_URL。这是有意设计，用于避免测试在
未知数据库上静默执行。真实凭据只能存在于本地忽略文件或受保护的环境变量中。

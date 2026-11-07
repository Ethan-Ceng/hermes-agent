# PostgreSQL 初始化与启动就绪阶段性独立审查

## 审查范围

- 日期：2026-11-07；分支：`feat/postgresql-session-storage`；基准：`fe57209323`。
- 独立 Reviewer，只读生产代码；未读取凭据，未连接数据库，未安装、移除或修改数据库扩展，未执行 Git 写操作。
- 阅读当前 `hermes_db/schema.py`、`hermes_db/health.py` 的完整 diff，以及工厂/Native registry、连接管理、CLI 命令、搜索迁移的相关路径；核对新增 `test_startup_requirements.py`、原 `test_schema.py`、用户指南及计划差异。
- 本轮针对 Task 5 的 pg_trgm 前置检查和启动就绪改动，不是 Tasks 6–18 的完整后端验收。

## 问题列表

本轮未发现可定位的 blocking、major 或 minor 生产代码缺陷。

### [suggestion] 完成本阶段时同步计划的当前门禁摘要

位置：`docs/plans/postgresql-session-storage-plan.md:1183`、`:1214`。

计划前部已记录管理员启用 pg_trgm、Task 4 环境与配置契约通过、严格完成 4/18；末尾仍以当前状态口吻写验收库未启用扩展、前置被 pg_trgm 阻塞及完成 3/18。历史执行记录可以保留，但当前门禁摘要应更新为尚待后续业务/并发/故障验收及既有完整回归问题，避免下次恢复重复处理已解决的前置条件。

## 核对结果

- 初始化：`_prepare_schema` 在事务级升级互斥锁及本地超时设置后检查扩展，再执行 `CREATE SCHEMA` 和 Alembic；缺项抛出 `StorageSchemaError`，没有自动安装扩展。新增检查不增加外部效果或跨连接写入；原迁移仍在显式命令的单一事务内执行。
- 普通启动：`native_registry._construct_store` 调用 `check_schema`；后者由 `schema_status` 的短连接检查 revision 和扩展。新逻辑只执行读取/事务本地配置，没有启动 DDL，也没有失败后转用 SQLite 的路径。
- 健康：`configured_probe` 在已有同一短连接内复用 `status_on_connection`，缺项返回既有脱敏 degraded 结构，不误报 ok；满足就绪后才做当前 store 的最小读探针。
- 修复提示：status 在缺项时返回 `missing_extensions` 和 `action_required`，`ready=false`；factory 启动错误和显式 upgrade 错误包含管理员可执行的 `CREATE EXTENSION IF NOT EXISTS pg_trgm;`，并要求在配置对应数据库执行后重试升级。CLI 保持非零退出码。修复 SQL 只是提示，不会由程序执行。
- 范围与可维护性：共用连接内就绪判断，避免 health 与 startup 的扩展条件分叉；没有更换会话后端、读取旧数据、变更提示缓存或引入新的配置开关。

## 测试与无法验证项

新增五项真实 PG 测试通过 SQLAlchemy 执行事件隐藏扩展查询结果，保留真实管理员扩展。测试调用实际 factory、health、CLI 和升级路径，断言缺项拒绝、可执行提示及无 DDL；观察运行时 SQL 来验证副作用，没有读取生产源文件。原实现红灯日志显示：初始化已发出 45 条 DDL 才发现缺扩展、当前 revision 的 status 错误报 ready，以及新增 status 字段尚不存在。前两项是有效行为回归，后一项是输出契约缺口，不能混同为三个独立正确性缺陷。

本 Reviewer 已读取完整结果摘要：

| 验证 | 已观察证据 |
| --- | --- |
| 真实 Schema + 新 startup 要求 | `.build/postgresql/pg-task5-schema-startup-tests.log`：2 文件，10 passed / 0 failed，7.7s |
| 扩大离线回归 | `.build/postgresql/pg-task5-offline-regression.log`：101 文件，536 passed / 0 failed / 2 skipped，52.5s |
| 先红后绿 | `.build/postgresql/pg-task5-startup-red.log` 与上述绿灯日志 |

以上为主 Agent 已执行日志的独立核对，本 Reviewer 没有另行连接数据库重跑。扩展缺失由故障注入模拟，未执行真实卸载或真实管理员安装流程；这符合不修改管理员扩展的边界。两个 skipped 不计通过，默认离线回归中的 integration 未执行也不计真实 PG 通过。未在本轮独立核对全部静态检查或发行构建完成结果。

## 门禁与结论

Task 5 当前生产改动未发现阻塞问题；已观察的 10 项真实初始化/启动验证及 536 项离线回归支持此阶段行为。当前计划摘要仍应收口更新，剩余业务、并发、故障、完整分支回归和发行验收不能由本阶段证据替代。

**整体结论：`CHANGES_REQUIRED`。不批准完整分支。** 本结论不表示上述初始化改动存在已确认重大代码缺陷，也不把先前已解决的扩展前置继续当作当前阻塞。

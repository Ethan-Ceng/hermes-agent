# hermes_db 分包 Task1 基线与依赖账本

本文件与 [机器清单](hermes-db-package-baseline.json) 是历史基线：其中的旧路径、patch 字符串和源码片段描述 `cbfc773dd7`，不是重构后的活跃调用说明。后续移动不改写这份历史证据；最终落位维护在 [映射](hermes-db-package-map.json)。

## 隔离与来源

- 正式 checkout：`D:/AI/hermes-agent`，文档分支 `docs/hermes-db-package-layout`，规划提交 `7f5f1e74ed7bddee669c96e3170d329b2637d5ab`；开始时工作区干净。
- 实施 checkout：`D:/AI/hermes-db-packages`，独立 worktree，普通分支 `refactor/hermes-db-packages`，从规划提交建立。正式目录的源码和当前分支不变。
- 首次 PM/应用导入之前显式绑定本 checkout 的 `.build/package-layout/profile` 与 `.build/package-layout/runtime`；这些路径均为本地执行证据，不是产品运行配置。
- PM bootstrap 仅读取既有测试环境的 Python 3.14.9；实际运行 `python -m pm.build_env --source . --out .build/package-layout/test-env --group dev --group test --extra postgresql --extra telegram --extra discord`，返回该新环境的 `Scripts/python.exe`。未修改原环境，未使用 raw pip/uv。
- PM 首次下载遭遇一次 SSL EOF，自动重试后退出 0；记录于本地 `pm-build.log`。Windows 不为 Matrix SDK 通过背书，Task6 使用现有 Ubuntu-26.04 WSL2 的真实 Linux SDK 环境；WSL 不解除原 Task24 的非 WSL 门禁。
- `cbfc773dd7` 与 `0d69702244` 的差异只有两个原统一后端文档；规划提交没有运行代码差异。398 个 Git 规范 blob SHA256 全部匹配映射，无新增或未归属源码。

## 可复现清单

在冻结基准、隔离环境下运行 `python scripts/hermes_db_layout_audit.py`。脚本不导入应用，也不连接数据库；验证 398 个源 hash 后生成历史 JSON。它刻意拒绝在移动后重写基线。

JSON 和 [引用台账](hermes-db-package-reference-baseline.json) 合计包含：359 个拥有公共定义的模块、所有公共函数/类/方法的参数默认值、返回标注及装饰器、继承基类、DTO 字段、239 个跨项目依赖拥有者、逐模块内部依赖、全仓 Python 模块字符串（含测试 patch）、动态 import/getattr、配置及领域注册值和固定锚点。对运行签名的验证仍由真实合同执行，静态清单不能替代行为证据。

公共 Session/Runtime 方法以各定义类及基类列表冻结；Session 的 36 个能力类、Runtime 的 10 个能力类连同 facade 自有方法须全部映射至最终显式委托。公共错误只保留原定义身份；Projects/Verification/Kanban/Rooms/plugin record 的外部 DTO/异常定义单独冻结在 `identity_definitions`。内部类移动允许改变 Python 归属路径，不允许复制一份类型维持旧路径。

## 动态入口与持久名称

| 读取点（历史基准路径） | 消费者/协议 | 落位任务与约束 |
| --- | --- | --- |
| domains/cron.py `cron_{topic}` | Cron 装饰器调用原函数名 | Task4 改域内路由；topic/函数名不改 |
| domains/kanban.py `kanban_{topic}` | Board/Worker/CLI 分流 | Task10 显式模块表；RPC command 和回执 operation 值不改 |
| domains/rooms.py `{topic}` | typed room location、直接资源和 Profile 入口 | Task9 显式域内路由，保持 owning Profile 与同一连接 |
| domains/catalog.py、tables/__init__.py | DomainSpec 的表模块加载 | 表模块全部留原位；Task2 仅移动目录能力定义 |
| domains/kanban_wire.py | DTO `kind`、CommandRefusal.name 的闭合表 | Task10/14/16 保留现有 DTO/异常构造身份；不加载任意类名 |
| operations/worker_retain_queue.py、discord_recovery_store.py | 闭合具名方法 getattr | Task5/8/13 保留实际允许的方法及 RPC handler 表 |
| matrix_crypto.py、matrix_codec.py、matrix_olm_cache.py | mautrix/Olm SDK pickle、日期/时长 JSON | Task6 保留 SDK pickle 字节和对象身份；本地模块路径不写进 pickle |
| domains/kanban_worker.py、operations/worker_*.py | owner-only 领域 RPC/回执/序号 | Task8/13 同步导入与 handler；不改变逻辑 verb、payload 和身份 |
| move_values.py、session_read_snapshot.py | 目标摘要、pin 身份 | Task2/7/12 保持完整资源身份/实例，不用包路径取代 |

核对的持久格式是显式 JSON/字节/SDK Olm pickle；未发现把 hermes_db Python 完整模块名保存成反序列化地址的生产路径。模块路径字符串主要用于 imports、动态路由与测试 patch。此结论限定为本次静态生产读取点核对，后续需真实旧数据重开、RPC 重放及 SDK round-trip 证明兼容，不能据此跳过 Task17。

## 依赖分类与后续处置

机器台账按源文件、模块、符号、行号记录全部边；以下是可审议分类，不把 239 个拥有者整体豁免。

| 分类 | 具名范围 | 处置 |
| --- | --- | --- |
| 已确认共享的纯决策 | `hermes_cli.kanban_block_policy.block_transition`；`hermes_cli.kanban_failure_policy.failure_budget` | 允许复用，保持无配置/存储 I/O |
| 已确认共享的纯值转换 | `hermes_cli.kanban_transfer_values.reanchor_tables`；`hermes_cli.timefmt.EPOCH_MIN/EPOCH_MAX/coerce_epoch` | 仅这些符号；不调用同模块 SQLite reanchor；时间转换原 warning 语义保留 |
| Agent 持久标记 | `agent.conversation_compression_archive.ABSORBED_ROW_IDS/MERGED_DURABLE_ROWS/OWN_ROW/RETIRED_DURABLE_ROWS`；`agent.message_metadata.CANONICAL_ROW/DB_ROW_SNAPSHOT/MESSAGE_UID/RESTORED_FROM_STORE` | 既有值协议，保持身份和值；不搬整个 Agent 业务入 DB |
| 公开插件协议/值 | `plugins.plugin_storage_types` 中 PluginRecord/PluginStore/错误与 encode_value/validate_key（具体读取见 JSON） | 保持现有公开身份，不增 plugin API；Task5/16 逐边核对 |
| Native SQLite 兼容桥接 | legacy_sqlite.py、sqlite/native.py 对 hermes_state 与既有 Native 入口的调用 | Task2 下沉 backends/sqlite；仍惰性，仅 SQLite 分支 |
| 历史迁移例外 | migrations/merge_data_repair.py 的 Agent 标记/格式依赖 | 只允许必要 import 调整；算法与历史 SQL 保留 |
| 明确组合/适配 | db_setup Profile 绑定、secret_scope、events、DTO/RPC、room_router、Profile transfer | Task2/7/8/9 后在 integration 组合；不可下沉 core |
| 待关闭的私有门面依赖 | Projects 私有规范化；Kanban CLI validation/dispatch/notify/workspace/transfer；Rooms 完整 gateway 门面与 RouterCalls 继承；metrics sender/engagement 门面；hermes_state Native Mixin | Task11–16 提取实际共享规则或在 integration 注入窄能力，不能因机械搬迁扩大豁免 |
| 仍需逐符号审议 | context_compressor、transcript_repair、skill_commands、session_activity、kanban_respawn_policy、kanban_swarm_plan、shared_metrics_contract、owner_identity、hosted_rooms_common 及 JSON 其余边 | 有些函数名称看似纯但实际 late-import 私有门面/运行状态；本轮未给予整模块纯规则豁免，Task12–16 必须核对真实消费者 |

`plugin_api.json` 与 `boundary_lint_baseline.json` 的 SHA256 已冻结；现有 26 项 hermes_db 接线例外仅能精确迁移，不能全量重新生成 baseline 掩盖新穿越。

## 固定锚点与缺证边界

31 个 Alembic revision 文件的 Git blob SHA256、revision/down_revision，以及 29 个表定义模块和 tables/__init__ 共同计 61 个锚点已冻结；`REQUIRED_REVISION` 保持 `0031_merge_data_repair`。DomainSpec 的 16 个逻辑域键、revision/table_modules、settings 字段/默认值同时冻结。后续表/版本资源不移位，不增加 revision，不迁移任何正式数据。

Task1 实际命令、计数、退出码及未验证项见计划对应条目。本次不把历史 686 PG、36 专项、32 SDK 或 Native503 当成重构后证据。原统一后端 Task24 与七项非 WSL 缺证独立保留；本 Task1 的基线通过也不解除它们。

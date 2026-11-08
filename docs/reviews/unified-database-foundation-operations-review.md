# 统一数据库基础设施与运维独立审查

## 审查范围

- 基准：`a875342384`；受审提交：`3febe6fc31`，完整范围为 `a875342384..3febe6fc31`。
- 审查者：独立 Reviewer；未修改生产代码、未提交、未操作正式 Profile/服务/业务表。
- 日期：2026-11-08。
- 输入：根及相关 `AGENTS.md`、`supercoder:code-review`、`docs/designs/unified-database-backends.md`、`docs/plans/unified-database-backends-plan.md`。核对实际 diff、原消费者及相关符号的 `git log -p -S`，不以执行账本中的完成结论代替审查。
- 范围：统一配置/秘密绑定；factory/domain/schema/短连接生命周期；verification、Projects、Cron；Profile 创建/改名/删除；health、backup/restore、updater、worktrees、维护和后台 Profile 绑定（Task 1–7、20–21）。Kanban/Rooms 深层、插件/metrics 由其他 Reviewer 审查；本报告包含 Cron 与 Rooms 的消费者交界。

## 问题列表

### [blocking] Profile 删除在确认后重新选择数据集，可删除另一个 store

位置：`hermes_cli/profiles.py:1705`、`hermes_cli/profiles.py:1775`；`hermes_cli/data_cleanup_storage.py:64`。

问题：`delete_profile` 在摘要及输入确认之前没有捕获数据库身份，直到关闭服务、建立 tombstone 后才调用 `purge_profile_store(profile_dir)`；该函数此时重新读取 config 并调用 `capture_removal`。因此确认期间将 Profile 的 `store_id` 或连接目标改成其他数据集，执行阶段会无条件把新数据集当作已授权的删除对象。`uninstall --data` 的 `DataRemovalPlan` 已实现正确的确认前捕获，但 Profile 删除没有沿用该边界。

可复现证据：`tests/hermes_db/postgresql/test_review_foundation_profile_delete.py` 在 fixture 拥有的随机 Schema 中创建 store two 的 `other-profile-record`；待删 Profile before 原来选择 store one，输入确认回调改为 two 再返回 before。真实 `delete_profile` 报成功并删除本地目录，随后重开 store two，记录已经不存在。此测试未使用正式 Profile，服务/进程操作使用 fixture seam。

- 日志：`.build/postgresql/review-foundation-profile-delete-red.log`。
- 结果：0 passed、1 failed，runner 退出 1；失败断言为 `delete followed retargeted config and erased peer store`。
- 命令：`scripts/run_tests.sh tests/hermes_db/postgresql/test_review_foundation_profile_delete.py -j 1 -- -m integration --postgres-test-config=.build/postgresql/private/acceptance-postgresql.yaml`。

影响：确认前后的配置变化会导致跨 store 的不可逆数据删除，违反设计中“确认前捕获 Profile/store_id/目标，执行时重新核对”的明确要求。

建议：在摘要和确认前创建删除计划，执行时仅使用该计划中的捕获身份调用 `purge_store`。原选择 SQLite 时也必须冻结这一选择，执行前改为 PG 必须拒绝；不能以捕获值 None 为由重新解析并删除 PG。覆盖 store/目标变化与 SQLite→PG 变化，拒绝时保留恢复文件。

### [major] Cron 的显式房间目标仍通过旧路径选择，PG 下写入源 Profile 的同名房间

位置：`cron/scheduler_delivery_room.py:44`、`cron/scheduler_delivery_room.py:54`、`cron/scheduler_delivery_room.py:62`；与 `hermes_db/domains/rooms.py:80` 的新分流交界。

问题：`_room_stores(profile)` 为显式目标 Profile 生成 `home / state.db`，但没有绑定目标 Profile，也没有捕获其 `RoomStoreRef`。新 `room_operation` 的 PG 分支明确不从旧路径推断 Profile，而是使用当前 Profile；因此从 one 运行 `room:same-room@two` 时，探测和写入都落到 one。旧共享分支还把 `default_db_path()` 当作 Path 调用 `with_name`，不适用于新的 PG 引用。

可复现证据：`tests/hermes_db/postgresql/test_review_foundation_room_routing.py` 在同一 fixture 随机 Schema 中创建两个 store、相同 room_id 和各自 owner，再于 one scope 调用真实 `deliver_to_room(..., same-room@two)`。函数返回成功，PG 实读却是 source_events=1、target_events=0；没有 SQLite 连接。

- 日志：`.build/postgresql/review-foundation-room-routing-red.log`。
- 结果：0 passed、1 failed，runner 退出 1。
- 命令：`scripts/run_tests.sh tests/hermes_db/postgresql/test_review_foundation_room_routing.py -j 1 -- -m integration --postgres-test-config=.build/postgresql/private/acceptance-postgresql.yaml`。

影响：Cron 输出进入用户未选择的 Profile/房间，并且向调用方报告投递成功。目标独有 room_id 时则无法投递；混合 SQLite/PG Profile 也不能由 ambient 后端决定目标。

建议：按已解析的目标 home 在操作前选择后端，PG 捕获明确的 Profile/store/target 房间引用并以它完成探测和发布；SQLite 才使用既有 session/shared/root legacy 查找。以双 Profile 同 ID 和混合后端验证只写目标。该发现已通知主 Agent 和 Rooms Reviewer，避免重复计算。

### [major] Bot Chat 发现和延迟 Cron 投递仍把 state.db 文件作为 Profile 存在条件

位置：`tools/bot_live_delivery.py:57`、`cron/bot_chat_legacy.py:76`；实际调用者 `cron/scheduler_delivery.py:767`。

问题：`find_canonical_live_owner` 在 endpoint 已 ready 后，仍因 `state.db` 不存在返回 None；其 `_bot_chat_tip` 已在会话阶段使用后端能力，外层 guard 却没有迁移。`bot_chat_legacy._dispose` 同样把没有该文件的有效 PG 目标永久标为 ambiguous。这不是仅旧数据导入路径：`_deliver_to_bot_chat` 在目标停止/启动中时仍调用 `defer` 写入新待投递记录，后续 tick 通过该 drain 处理。

可复现证据：`.build/postgresql/review_foundation/test_bot_chat_pg.py` 创建临时 PG 配置，分别控制 ready endpoint/tip seam 和 live owner/transport seam。第一项 owner 得到 None，第二项新 queued 记录变 ambiguous、transport 未调用。该证据是无网络的消费者边界测试，不冒充实际 PG/真实 daemon E2E。

- 日志：`.build/postgresql/review-foundation-bot-chat-red.log`。
- 结果：0 passed、2 failed；runner 失败。该次外层随后读日志的命令退出码为 0，不把它登记为测试通过。
- 命令：`scripts/run_tests.sh .build/postgresql/review_foundation/test_bot_chat_pg.py -j 1`。

影响：PG 单后端正常不生成 state.db，故常规 Bot Chat/Cron 投递被拒绝；停止期间持久排队的输出也不能在重启后恢复。

建议：使用目标 Profile 的有效身份与所选 store 能力判断；保留真正已删除 Profile 的拒绝，不通过制造 state.db 哨兵文件绕过。补真实 PG tip、首次无 Bot Chat、重启后 deferred 记录恢复及已删除目标的行为合同。

### [major] 当前完整 PG 门禁仍有与已实现能力矛盾的测试

位置：`tests/hermes_db/postgresql/test_domain_schema.py:72`。

问题：测试在升级当前完整 Schema 后仍断言 `full_system_ready` 为 false、Matrix unsupported、acquire Matrix 抛 not implemented，与 HEAD 的 catalog 和 Task 19–23 完成状态矛盾。完整 PG 首轮日志已经实际失败，不能以早期 Task 2 该文件通过的账本覆盖当前结果。

证据：`.build/postgresql/unified-task24-full-pg-first.log` 的该文件为 3 passed、1 failed，失败于第 72 行；本次独立读取了失败内容。

建议：改成当前完整初始化 ready 的行为合同，再用实际移除领域表/显式 unsupported fixture 验证“不在普通 open 执行 DDL、明确拒绝缺能力”。保留首轮失败并重新执行门禁。

## 独立验证与测试质量

所有测试使用 `scripts/run_tests.sh`、PM 解释器 `D:/AI/hermes-agent/.build/postgresql/full-test-env/Scripts/python.exe`、`HERMES_TEST_FILE_RETRIES=0`。PG 仅传私有配置路径，归属核对和随机 Schema 由现有测试 fixture 执行；未打印 DSN/凭据。

- `contracts/test_domain_resources.py`：4 passed、1 POSIX 专属 skip，runner 退出 0；Windows 没有伪装 fork/OS。
- 独立 PG 针对性回归：verification_store、projects_store、cron_executions、cron_delivery_store、cron_notepad、profile_file_scope、backup_backend、worktree_storage 共 8 文件，40 passed、0 failed、0 skipped，runner 退出 0；`.build/postgresql/review-foundation-focused-pg.log`。
- 独立新增边界重现：Bot Chat 2 failed、房间目标 1 failed、Profile 删除 1 failed。两个 PG 重现测试是本 Reviewer 新增、未提交；生产代码未改。
- 现有领域合同能覆盖具体存储操作、作用域、部分并发/故障和重开；但上述调用链显示“各域 API 单独正确”和“联合探针通过”尚不能证明全部实际消费者已迁移。

## 其余审查判断与无法验证项

- 本范围未再发现已确认的秘密输出、隐式 PG→SQLite 回落、常规启动 DDL 或 verification/Projects/Cron SQL 缺少 store_id 的问题。新领域资源使用短操作借连接，文件/网络等待与 SQL 大体分离；这些判断不覆盖其他 Reviewer 的深层协议范围。
- 原生 Desktop preflight 的后端分流及 fail-closed 路径已读取；本 Reviewer 未另外执行 TypeScript 构建/桌面真实更新，不能代替 Task 24 的最新证据。
- Task 22/23 的独立发行、全部 SDK 和真实普通 daemon 证据仅作已存在输入；本 Reviewer 没有重新独立执行全部矩阵，也未将它们替代当前发现的失败。
- Task 24 完整 PG/原生宽回归正在由主 Agent 执行。审查时日志已经有失败，完整最终汇总及整改后重跑尚未提供。
- 会话阶段遗留的 7 项非 WSL POSIX 私有启动页验收在当前 Windows+WSL 环境不适用，缺少适用原生主机证据；明确保留为未验收，不能改平台条件制造通过。
- 本报告针对固定受审提交；后续修复需要重新审查实际增量并提供最新红绿证据，不能自动视为本报告已批准。

## 合并门禁

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 无 blocking | 失败 | Profile 删除可追随确认期间改指的 store 并误删数据 |
| 无未处理 major | 失败 | 房间目标错误、Bot Chat/延迟投递拒绝、当前 PG 门禁失败 |
| 所有验收满足 | 未满足 | 实际消费者遗漏及非 WSL POSIX 启动页仍未验收 |
| 本范围现有针对性回归 | 部分通过 | PG 40 passed；新边界重现 4 failed |
| 最终完整测试/构建 | 无法确认通过 | Task 24 进行中且首轮已有失败；本 Reviewer 未重跑全部构建 |
| 显式升级/发行 | 部分核对 | 独立领域 fixture 显式初始化通过；Task 23 完整发行仅核对既存证据 |

## 结论

`CHANGES_REQUIRED`。固定受审提交存在一个可复现的数据误删 blocking 和未处理 major；不能批准合并，也不能声明 `READY_TO_MERGE`。修复后需同时复验现有领域合同、实际消费者、失败门禁及所有仍适用的原生验收。

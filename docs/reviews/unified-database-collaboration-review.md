# 统一数据库后端：Kanban 与 Hosted Rooms 独立代码审查

## 审查范围

- 基准：`a875342384`；受审提交：`3febe6fc313faf34693ce9cb2075a3a894ea82d3`。
- 日期：2026-11-08；独立 Reviewer，不承担本轮实现，不修改生产代码或受版本管理的测试，不提交。
- 输入：root、`cron/`、`hermes_cli/`、`gateway/`、`tui_gateway/`、`tests/` 的 AGENTS.md，`supercoder:code-review`，`docs/designs/unified-database-backends.md`，`docs/plans/unified-database-backends-plan.md`。
- 范围：Kanban Board/任务图/run/派发/worker RPC/精确回执、订阅、归档导入导出、附件和 workspace 文件意图、维护与提交后 outbox；Hosted Rooms 元数据/事件/副本/driver/work/policy/router/附件，以及原生 RPC 和 Desktop/TUI 实际消费者；Profile rename 文件引用重定位接口。
- 对照相关完整 diff 与当前调用链，重点追踪 `connect_closing → BoardResource → domain_operation → Core operations`、`worker_kanban → frozen_context → CommandReceipt`、`dispatch_group_control → CanonicalHostedRoomService`、`methods_groups_forward → owner RPC`、附件/文件清理与维护、`move_directory → reanchor → marker`。基础、小领域、运维、插件、metrics、Matrix 由其他 Reviewer 覆盖，本报告不替代其结论。

## 问题列表

### [major] 房间资源改为 RoomStoreRef 后，原生与 Desktop 群聊入口仍调用 Path 接口

位置：`gateway/session_group_controls.py:66`；`tui_gateway/methods_groups_forward.py:70`、`:105`、`:118`、`:188`；类型变化来源 `gateway/session_hosted_storage.py:12` 与 `gateway/hosted_rooms.py:412`。

问题：PG 的 `coordination_path()` / `default_db_path()` 返回捕获的 `RoomStoreRef`。原生 `dispatch_group_control()` 在通用入口取 `.resolve`，任何 groups 请求均在业务操作前抛 AttributeError。Desktop/TUI 的 `forward()` 对带 room_id 的调用先执行 `_standalone_holder()`，其中 `.is_file()` 同样崩溃；`groups.list` 在 `_list → _root_home → Path(RoomStoreRef)` 抛 TypeError，即使网关已就绪。`methods_groups._room_method` 在自己的 try 块之前调用 forwarding，所以不是已处理的业务拒绝。

证据：真实 PG 配置和实际 PG session store 的隔离探针中，`test_canonical_group_entry_accepts_pg_location` 在 line 66 得到上述 AttributeError；forwarding 的 groups.list 和 groups.state 两例分别在 line 70 / 105 失败。只替代外部 owner transport，不替代 PG/location API。日志：`.build/postgresql/unified-review-collab-native-groups.log`（1 failed），`.build/postgresql/unified-review-collab-forward.log`（2 failed）。

影响：领域 API 测试通过仍不足以让原生/桌面群聊实际可用；`profiles.list` 共用的 dispatcher 也经过同一 location guard。

建议：逐入口区分 SQLite 文件与 PG captured reference；PG 检查 Profile/store/target，不能伪装 Path。PG 没有 SQLite standalone-import/handoff，应在正确 owning Profile 中直接走实际 owner 路由；保留 SQLite 原有 handoff 协议。对原生通用 dispatch 和桌面实际 forwarding 都补行为合同，不能仅测 `_group` 或 service 类。

### [major] 附件引用按原始路径计数，删除一个别名会删除仍被另一附件引用的文件

位置：`hermes_db/operations/kanban_artifacts.py:17`、`:26`、`:67`、`:131`；删除出口 `hermes_db/operations/kanban_attachment_cleanup.py:47`。

问题：添加附件时已有规范 `attachments.path_key`，但 blob 锁/cleanup key、remaining 引用查询仍用未经规范的 `stored_path` bytes。相同文件的规范路径与 `subdir/../proof.txt` 是两个合法引用；删除规范路径行时，remaining 查询看不到别名行，提交 cleanup token 后 unlink 真实文件。另一附件行仍存在，其文件已丢失。

证据：`test_alias_attachment_retains_shared_file` 用实际 PG `add_attachment` 创建两行，不改表。删除第一行后，第二行仍由 `get_attachment()` 返回，读取其文件抛 FileNotFoundError。日志 `.build/postgresql/unified-review-collab-probe.log`，第三例失败。代码历史核对：本类 PG cleanup/引用协议由本变更新增；SQLite 数据没有被读取或迁移。

影响：正常附件 API 可以产生持久的悬空元数据并误删活引用内容；跨 Board 同样受影响。属于数据正确性问题，不依赖对抗性 LLM 或外部权限绕过。

建议：用同一规范文件身份执行锁、活引用计数和 cleanup CAS。保持本机文件门→store 文件栅栏→Board→blob 的既有顺序，unlink 在事务外。兼容既有 PG 非规范 stored_path 与未决 token；不能只规范新写，或丢弃旧 token。可用现有 path_key 进行受栅栏保护的折叠/幂等对账，无法确认的旧引用应保留并明确要求对账。

### [major] 一个 Board 永久只能拥有一种 file_job action，成功导入后无法归档或删除

位置：`hermes_db/operations/kanban_file_jobs.py:81`（尤其 line 85–87）；调用者 `hermes_db/operations/kanban_boards.py:167`；表键 `hermes_db/tables/kanban_file_jobs.py:9`。

问题：file_job 主键为 store_id+board_id；`record()` 看到已有作业时，即使 `state=done`，也拒绝任何不同 action。成功 import 保留 `action=import,state=done`；之后 archive/delete 必定报“先完成现有作业”，但作业已经完成，维护也无法解除。成功 archive 后再 hard-delete 同样永久拒绝。

证据：`test_imported_board_can_be_retired` 实际 export/import 后 remove_board(archive=True)，以及 `test_completed_archive_can_be_deleted` 实际 create/archive 后 remove_board(archive=False)，均在 file_jobs.py:86 抛 StorageBusyError。日志 `.build/postgresql/unified-review-collab-probe.log` 前两例。`git log -p -S 'def record(conn, store, row, fields'` 核对该行为由 `297bd9069e` 新增，设计只要求未决意图禁止切换，不要求已完成意图永久阻止生命周期。

影响：导入的 Board 和已归档的 Board 无法按现有 CLI/API 生命周期管理，重试/重启不能恢复。

建议：允许已完成作业以明确状态转换进入后续退休作业，保留待清理 stage、旧代次路径和删除栅栏。仅拒绝未决且不兼容的 action；增加 import→archive、import→delete、archive→delete 及后续 slug 重建合同。

### [major] 认领拒绝的事务没有回执，COMMIT 确认丢失后相同 command 可变为成功认领

位置：`hermes_db/operations/kanban_claims.py:32`（line 35–40 提前返回）；补回执边界 `gateway/session_worker_kanban.py:74`；相关机制 `hermes_db/domains/kanban.py:19`、`hermes_db/operations/kanban_command_receipts.py:27`。

问题：成功 claim 使用 `store.command_result`，但父依赖未满足等提前返回没有记录原始 None 结果；父依赖拒绝还会在该事务写 claim_rejected 事件。worker `_execute` 只能在业务方法返回之后另开事务补回执。如果第一次拒绝事务实际 COMMIT 后 ACK 丢失，方法异常退出，补回执永远不执行。此时父任务完成，同一 command_id/request_digest 重试会创建新 run、返回成功 claim，而不是重放原来的 None。

证据：`test_unknown_rejected_claim_replays_original_verdict` 通过普通 create_task 建未完成父任务与 todo 子任务。按既有 receipt 测试的同样 seam，让真实 dialect.do_commit() 完成后再抛 OperationalError；捕获 UnknownCommitError。随后普通 complete_task 完成父任务，ready 重算使子任务可运行；完全相同 CommandReceipt 重试 claim 不抛 CommandReplay。未手工修改任务状态。日志 `.build/postgresql/unified-review-collab-claim.log`（1 failed，9.55s）。

影响：精确结果回执和 unknown-commit 合同只覆盖成功路径；迟到重放可以在业务前提已改变后产生新的执行权限。

建议：认领操作每个 verdict，包括 None/False/拒绝，必须在决定该 verdict 的原事务记录。审计其他 command 的提前返回、写审计后 raise 以及多事务路径（例如 completion guards），避免单靠外层另开事务补回执。

## 交界确认

独立核对了基础 Reviewer 的 Cron 房间路由发现：`cron/scheduler_delivery_room.py:54` 返回目标 Profile 的 Path，却没有绑定该 Profile；`room_operation` 对 PG 下普通 Path 改用当前 Profile 的 `capture_room_store()`，因此 Path 中的目标 home 不构成 scope，可能命中当前 store 的同 ID 房间。fallback 还会对 RoomStoreRef 调用 `.with_name()`。这项由基础 Reviewer 提供独立双 Profile 红测和主报告，本报告不重复计数。

## 验证、限制与门禁

本 Reviewer 的独立探针仅放在忽略目录 `.build/postgresql/review_collab_probe.py`，未修改已有测试或生产源码。均经 `scripts/run_tests.sh`；Windows 3.14.9 PM 解释器 `.build/postgresql/full-test-env/Scripts/python.exe`，`HERMES_TEST_FILE_RETRIES=0`，fixture 核对独立测试数据库归属并仅操作随机 Schema，启用 SQLite audit guard。未操作正式 Profile、服务、SQLite 或正式业务表。

命令形式（PowerShell 设置 HERMES_PYTHON 后经 `D:/Programs/Git/bin/bash.exe`）：

```text
scripts/run_tests.sh .build/postgresql/review_collab_probe.py -j 1 -- -p tests.hermes_db.conftest -m integration --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

最初三例与后续 `-k unknown_rejected`、`-k desktop_group`、`-k canonical_group` 分开执行，共 7 个独立失败场景；各退出 1，未重试。首次未提前加载 PG 插件的调用退出 4、零测试，已纠正，不当作产品失败。由于 `.build` 路径不经常规 tests 路径的 marker 注册，日志包含一个 allow_network 未注册告警，不影响实际随机 Schema、fixture 或失败堆栈。

设计与实现中已确认的正向结构：PG 领域操作使用具名 Core API，无伪 SQLite Connection；Board/store 和房间/store 查询显式 scope；read UoW 采用 REPEATABLE READ，因此 Kanban 多表 snapshot 不是默认 READ COMMITTED 撕裂；外部 hook/文件/网络等待不应借用领域事务，workspace token、附件 namespace、import stage 与 owner target 均有持久身份机制。上述结构不抵消实际消费者遗漏与红测。

| 门禁 | 结果 | 依据 |
| --- | --- | --- |
| 无 blocking | 本范围未发现已证实 blocking | 发现按 major 分类 |
| 无未处理 major | 失败 | 上述四项均在受审提交复现 |
| 完整业务入口可用 | 失败 | 原生 groups 与桌面 forwarding 都在 PG location 类型边界崩溃 |
| 精确回执/unknown commit | 失败 | 拒绝认领同 request 改变 verdict |
| 文件活引用与恢复 | 失败 | 别名引用误删；完成 file_job 阻断后续生命周期 |
| Task24 全套最新复验 | 无法验证 | 审查时父任务仍执行完整 PG/原生宽回归；不能借 Task22/23 替代 |
| 非 WSL 私有启动页七项适用主机证据 | 未满足 | 当前 Windows+WSL 无对应主机证据，保留原门禁 |
| 修复后独立复验 | 未执行 | 本报告冻结原始受审提交；后续修改须重新独立审查 |

## 审查结论

`CHANGES_REQUIRED`。四项 major 有真实 PG、实际领域 API/入口和失败堆栈证据，当前不可批准合并。完整验证、适用主机缺口与整改后独立复验必须单列；不得把已有领域测试通过或零 SQLite 连接概括为全系统入口已经可用。

## 第二轮独立复审记录（工作区整改，尚未最终批准）

2026-11-08 收到 Root 的整改说明后，独立读取实际工作区 diff，重新沿所有 worker COMMANDS 的拒绝/跨事务路径、附件旧别名与未决 token、file_job 转移、房间实际入口追踪。以下为过程证据；整改同时进行，因此每轮测试只证明其进程实际加载的版本，最终版本仍需再次核对与复验。

- Root 的新写入口规范路径、全 store path_key 引用计数和 token 校验，已通过额外三例实库行为：重建旧 PG raw stored_path/blob 行后，删除一条引用保留实际文件，删除最后旧别名引用才移除；旧 raw alias cleanup token 无活引用可重放清理；有 canonical 活引用时保留文件并拒绝新引用。不是仅验证新写被规范化。
- `request_changes` 最初仍有四个事务内提前拒绝遗漏，已通知 Root；其随后的补丁已在独立 lost-COMMIT-ACK 探针通过：先拒绝，普通 review handoff/claim 后相同 command 仍重放原 False tuple。
- 7 个既有 PG 合同文件独立集中复验：33 passed / 3 failed，retries=0，日志 `.build/postgresql/unified-review-collab-second-contracts.log`。两处是将附件预检移入文件门后，既有退休/并发合同先等待文件门而无法快速观察持久 token，Root 已恢复门前快检并保留门内复查。第三处是 completion 新增前置 write 后，既有全局 do_commit 故障注入命中前置事务，尚未执行所声称的主完成/附件事务；Root 已改为观察实际附件 INSERT 后故障注入。上述失败不能省略，也不能作为已修代码的新证据。

### [major] 缺失 PG phantom-warning 分流使提交后 outbox 永久停在首阶段

位置（发现时）：`hermes_cli/kanban_db.py:2672`，`hermes_db/operations/kanban_effects.py:53`。

`_flag_phantom_prose_refs` 由 PG 完成 outbox 的第一阶段调用，却仍使用原生 `write_txn`。正常完成 summary 包含不存在的 `t_deadbeef` 时，该函数的 PG 扫描命中后立刻触发 StorageNotReadyError；after_commit 将其留为 pending，之后 ready/workspace/hook 阶段均不执行。独立实际业务探针创建父任务与 todo 子任务，完成父任务返回 True 且父为 done，但子仍为 todo，日志明确记 StorageNotReadyError。不是伪造存储错误。

证据：`.build/postgresql/review_collab_second_probe.py::test_phantom_completion_warning_does_not_stall_outbox`；日志 `.build/postgresql/unified-review-collab-second-probe-final.log`。Root 随后加入 domain_operation 与 Core warning 审计，并开始处理 warning 提交确认丢失后的去重；最新实现尚待本 Reviewer 的实际 phase replay/后续阶段排空合同。

### [major] PG owner 不存在时，显式 foreign Profile 的本地群聊列表读到 launch store

位置（第一轮修复后）：`tui_gateway/methods_groups_forward.py:159` 与 `tui_gateway/methods_groups.py:351`。

PG forwarding 分支在目标 owner 不存在时返回 None，本地 groups.list handler 随即使用 ambient default_db_path，整个 handler 当时未绑定请求 Profile。两个真实 PG store 放同 room_id、不同名称，在 launch scope 请求 profile=foreign，实际返回 launch room。实库探针通过实际 HandlerRegistry 注册与调用，不替代房间存储；仅替代外部网关发现为 absent。日志 `.build/postgresql/unified-review-collab-second.log`。

Root 随后把整个 room handler/能力查询置于目标 runtime scope，并匹配本地 service dataset。复审还发现该 wrapper 对 `_bound_server` / capabilities helper 的裸全局读取与 HandlerRegistry 的 server-globals rebind 不兼容；第二轮日志出现 `_bound_server` NameError。该注册 seam 也已通知 Root，正在整改，不能把 helper 单独测试通过当作实际 server 注册后入口通过。

过程测试异常：第一次把 `.build` 探针和正常 tests 路径混跑并显式 `-p tests.hermes_db.conftest`，导致正常 tests 的重复插件注册、7 文件零测试；已分离并改用正常发现，得到上述 33/3 的真实结果。第二探针最终 4 passed / 2 failed：四例正向如前，两例分别是已证实的 phantom outbox 停滞与新 wrapper rebind NameError，日志 `.build/postgresql/unified-review-collab-second-probe-final.log`。该过程不构成最终批准。

### [major] 实际 server 的 groups.capabilities 仍直接创建 SQLite run store

位置：`tui_gateway/methods_groups.py:158`；实际落点 `gateway/platforms/api_server_run_idempotency.py:74`。

在最新 scope/helper rebind 修复后，独立直接调用真实 `tui_gateway.server._methods["groups.list"]` 已通过；继续调用同一实际注册表的 `groups.capabilities`，owner absent 的本地分支进入 `_room_link_run_storage_durable()`，直接构造原生 RunIdempotencyStore。它无条件连接 `runs_idempotency.db`，且该原生类的失败分支还会连 `:memory:`。这绕过统一 PG 选择；SQLite audit guard 在首次连接即拦截，不让错误被 capabilities 的异常边界掩盖。

证据：`.build/postgresql/review_collab_second_probe.py::test_actual_server_registered_groups_handlers_use_bound_module_helpers`；日志 `.build/postgresql/unified-review-collab-latest-independent.log`。这一轮共 7 passed / 1 failed，另有 audit teardown error（同一次违规尝试的保留见证），不是两个独立产品问题。

影响：真实 Desktop/TUI 群聊能力查询在 PG 运行时仍依赖自有 SQLite，违背单后端验收，即使领域 API、owner forwarding 与 service 测试均通过。

建议：通过已有 `hermes_db.api_resources.open_run_store` / ProfileRunStores 选择后端，仅把原生 RunIdempotencyStore 作为延迟 SQLite factory。该 helper 仅探测 durable 能力，可短期打开并关闭资源；若缓存则必须有 owning Profile、配置目标验证与明确的生命周期关闭。不能简单返回 True 或禁用 RoomLink 来过零 SQLite 门禁。

最新独立正向七例包括：foreign owner absent 的实际 handler 返回目标 store、request_changes 拒绝 COMMIT-loss 重放、旧别名/旧 token 三例、phantom 完成后子任务 ready，以及 warning 自身真实 COMMIT 后丢 ACK 再重放阶段：仅一条 warning、子任务 ready、后续 outbox 全部排空。对应最新代码的范围进展不抵消本节新发现，整体仍为 CHANGES_REQUIRED。

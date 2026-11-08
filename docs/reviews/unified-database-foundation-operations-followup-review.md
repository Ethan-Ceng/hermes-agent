# 统一数据库基础设施与运维整改增量复审

## 审查范围

- 日期：2026-11-08；审查者：原实现 Agent 之外的独立 Reviewer。
- 前次冻结报告：`docs/reviews/unified-database-foundation-operations-review.md`，其受审范围及 `3febe6fc31` 的 `CHANGES_REQUIRED` 结论保持原样。
- 本次对象：HEAD 仍为 `3febe6fc313faf34693ce9cb2075a3a894ea82d3` 时的未提交工作区整改增量；不代表未来提交、整个工作区或全部数据库领域的批准。
- 生产范围：`hermes_cli/profiles_deletion_storage.py`、`data_cleanup_storage.py`、`profiles.py`；`gateway/control_socket.py`、`run_bootstrap.py`、`run_profile_reconcile.py`；`tools/bot_live_delivery.py`、`cron/bot_chat_legacy.py`、`cron/scheduler_delivery_room.py`。
- 测试增量核对：`tests/hermes_db/postgresql/test_domain_schema.py`、`test_health_archive_refs.py`、`test_startup_requirements.py`，以及它们引用的 `contracts/test_storage_health_refs.py`、`test_profile_moves.py`；检查主 Agent 从独立 probe 复制出的 `tests/hermes_db/test_profile_deletion_storage.py`。
- 本 Reviewer 未编辑生产代码、仓库测试、前次报告，也未提交。新增诊断及测试仅位于忽略的 `.build/postgresql/review_foundation/`；本次只新增此报告。

## 原发现逐项状态

| 原问题 | 本次状态 | 代码与验证依据 |
| --- | --- | --- |
| blocking：确认期间改库使 Profile 删除误删其他 store | 本范围整改已确认 | `prepare` 在摘要/确认前捕获 target 和 root 的 backend/settings/scope/identity；确认后、identity purge 前、整 store purge 前分别核对。实际 acquire 使用被冻结的 settings/scope，不在核对后再次解析配置来选择数据库。独立 probe 验证 root/target 改 store、SQLite→PG 以及核对至 acquire 之间的变化均不误写 peer。 |
| major：Cron 显式房间目标写入源 Profile | 本范围整改已确认 | `deliver_to_room` 解析目标后，将整个构造、探测与发布置于目标 `_owning_profile`；PG 使用显式 `RoomStoreRef`，不把引用当 SQLite Path。独立实际 PG→SQLite 同 room_id 验证只写目标；主 Agent 的 PG→PG 原红测转绿日志另行核对。 |
| major：Bot Chat 与延迟 Cron 投递依赖 state.db | 本范围整改已确认 | 两处旧文件 guard 改用目标 Profile 的 `session_store_exists`；tip 继续由选定会话 store 读取。主 Agent 的两项真实 PG tip/持久 deferred 记录合同已转绿；复审读取实际测试和完整结果摘要，未把 seam mock 说成真实网络/daemon E2E。 |
| major：Schema 门禁仍断言 Matrix 未实现 | 测试合同已纠正，运行门禁待正式复跑 | 新合同要求完整 schema 所有已登记域 supported/ready，实际 acquire Matrix；随后真实 DROP Matrix Olm 表，要求 readiness 失败、Matrix open 抛 `StorageSchemaError` 且表未被普通 open 重建。不能仅凭代码变更将旧失败日志登记为通过。 |

首次增量读取还发现两项接线问题，均在主 Agent 后续修改后重新核对：身份检查曾误插入 migrate handler，purge handler 先写后引用未定义变量；Cron 起初仅在构造引用时绑定目标，PG→SQLite 仍会回到源 Profile。它们均已在本报告对应的当前增量中纠正。

另一个旧 handler 风险也已闭合：仅向旧 `purge-profile-identity` 增加参数，再拒绝无身份 token 的成功回复，会让旧服务先产生副作用。当前身份受约束调用改走独立的 `purge-profile-identity-checked` verb，旧服务不认识该 verb，不能先写其未经核对的数据库。新 checked handler 要求身份参数，并在任何持久或内存路由修改前比较实际已持有的 routing_db。普通旧 verb 保留历史调用语义。

## 独立 11 项 probe

所有测试均经 `scripts/run_tests.sh`、PM 解释器 `D:/AI/hermes-agent/.build/postgresql/full-test-env/Scripts/python.exe`，`HERMES_TEST_FILE_RETRIES=0`，单 runner、`-j 1`。PG 只传私有配置文件路径，复用归属核对后的随机 Schema fixture；未打印凭据、未操作正式 Profile/服务。

独立源文件：`.build/postgresql/review_foundation/test_deletion_routing_followup.py`。主 Agent 已将这些业务合同复制为 `tests/hermes_db/test_profile_deletion_storage.py`，去掉在测试目录内不需要的 `pytest_plugins` 声明；该正式测试文件尚待主 Agent 最新复跑。本 Reviewer 的通过记录针对原 `.build` probe，不将复制视为重新执行。

| Probe | 数量 | 结果与实际判据 |
| --- | --- | --- |
| live handler 实际持有身份匹配/不匹配 | 2 | 正确身份才产生 db/routing 副作用；不同身份在副作用前拒绝，成功回复携带核对后的 token。这里用具名观察 seam 验证 handler 边界，不宣称实网控制 socket。 |
| 旧 handler 拒绝 | 1 | 模拟已发布旧 handler 忽略未知参数的真实语义；当前 client 使用 checked 新 verb，旧 handler 未产生任何修改。 |
| SQLite 独立性 | 1 | 新解释器主动禁止导入 SQLAlchemy/psycopg/Alembic；冻结删除计划仍能处理 SQLite root 路由身份，保留会话历史。 |
| PG 源→SQLite 目标的相同 room_id | 1 | 真实 PostgreSQL 与 SQLite 各自有房间和 owner；实际投递只增加 SQLite 目标事件，PG 源事件保持空。此为两个 Profile 的混合后端合同，不替代单 PG Profile 的零 SQLite 审计。 |
| 确认后 root/target 改 store | 2 | identity purge 和整 store purge 均拒绝；三个实际 PG store 的历史和路由记录全部保留。 |
| root 核对与 acquire 之间改库 | 1 | 在真实 factory acquisition seam 注入配置变化；实际仅清理原冻结 root 的路由，peer 路由仍在。 |
| target 核对与 acquire 之间改库 | 1 | 在真实 domain acquisition seam 注入配置变化；实际仅清空原冻结 target，peer 历史仍在。 |
| 确认后 root/target SQLite→PG | 2 | 两条入口都在持久副作用前拒绝，peer 历史与路由仍在。 |
| 合计 | 11 | 11 passed、0 failed、0 skipped；两次集中执行均退出 0。 |

命令与日志：

- 第一批：`scripts/run_tests.sh .build/postgresql/review_foundation/test_deletion_routing_followup.py -j 1 -- -p tests.hermes_db.conftest -m 'integration or not integration' --postgres-test-config=.build/postgresql/private/acceptance-postgresql.yaml`，当时文件中 5 项，5 passed；`.build/postgresql/review-foundation-deletion-routing-followup-loaded.log`。
- 后续补齐确认/获取窗口：同一命令增加 `-k 'confirmed_root or change_between or sqlite_to_pg'`，6 passed；`.build/postgresql/review-foundation-frozen-deletion-races.log`。
- 初次 `.build` 参数插件没有预加载，pytest 拒绝 `--postgres-test-config`，0 collected；`.build/postgresql/review-foundation-deletion-routing-followup.log`。已保留，不记作代码失败或通过；随后显式加载参数插件才执行上述业务合同。

主 Agent 既有整改绿测，已独立读取摘要和测试内容：

- `.build/postgresql/unified-task24-delete-bot-first-fix.log`：2 文件、3 passed，包含原 Profile 删除红测及 Bot Chat 两项真实 PG 合同。
- `.build/postgresql/unified-task24-collaboration-first-fix.log`：2 文件、8 passed，包含原 Cron 双 PG Profile 房间目标红测。此日志中的其他协作领域不因本 Reviewer 读取摘要而视为已完成独立深层复审。

## Schema、health、startup 测试是否放宽门禁

在此次读取的指定测试增量中，未发现通过删除关键断言、关闭 SQLite 审计或跳过功能来制造通过。

- `test_domain_schema.py` 删除的是已过时的“Matrix 不支持”前提，替换为更完整的正反业务合同：全部能力 ready、真实 Matrix acquire、实际缺 Matrix 表拒绝、普通 open 不创建被删表；原有缺 sessions 表拒绝仍保留。
- `test_health_archive_refs.py` 与 `contracts/test_storage_health_refs.py` 的 fixture 原来只替换 `resolve_db_configuration`，而生产健康探测现在先调用 `storage_backend`。补充同一 PG 后端选择 seam 使 fixture 自洽；可用状态、无 state.db、持久 spillover 保留和作用域等业务断言没有删掉。
- `test_startup_requirements.py` 同样补齐后端选择 fixture，并要求 degraded 结果明确携带所选 backend；缺扩展时拒绝初始化、返回管理员操作提示、普通启动/诊断不执行 DDL 的断言全部保留，没有让应用代管扩展或服务。
- `contracts/test_profile_moves.py` 把真实 SQLite 输入文件的制作移动到独立子进程，PG 业务进程仍对 SQLite payload 明确拒绝。没有给 PG guard 加豁免，也没有把 SQLite→PG 数据导入改为允许；这符合原设计对外部 SQLite 文件输入单独测试的边界。

这些是代码/合同核对结论。完整最新 schema/health/startup 实库复跑以及正式复制后的 11 项测试运行门禁，仍由主 Agent 记录；本报告不把静态核对替代运行结果。

## 未覆盖项与全局门禁

- 本次只复审上述整改增量。Kanban/Rooms 深层、插件/metrics/Matrix 及其他 Reviewer 后续整改，不在此报告的批准范围。
- Task 24 完整 PostgreSQL、原生宽回归、生成契约、TypeScript/发行/真实入口的最终汇总和整改后重跑尚未由本报告独立验收。既有失败必须保留实际处置，不用这 11 项局部通过覆盖。
- 原会话阶段的 7 项非 WSL POSIX 私有启动页验收仍缺适用原生主机证据；当前 Windows+WSL 不能补齐，未伪装平台、未扩大超时或删除平台门禁。
- ACP 启动诊断是单独的观察证据：同 fixture 形状的隔离 daemon 在 34.27 秒 ready，采样见 Git/文件比较/工具路径解析，未见 metadata 网络阻塞；尚缺同条件 a875 A/B，不能据此把所有原生 setup 失败归为既有问题或宣布修复。
- 所有局部通过记录对应未提交工作区。最终受审提交发生变化后仍需核对增量与相应最新验证，不能自动继承批准。

## 复审结论

本次指定生产整改范围未发现仍未处理的 blocking/major；原数据误删、房间选错 Profile 和 Bot Chat 文件 guard 三项业务发现已由当前实现与上述证据闭合。Schema 门禁的测试合同已正确更新，正式运行结果仍待复跑登记。

整体交付结论仍为 `CHANGES_REQUIRED`：完整最终验证和适用平台验收尚未完成。本报告仅记录局部整改复审通过，不批准合并、不声明 `READY_TO_MERGE`，也不改写前次固定提交的审查结论。

## 冻结 58d 原生宽回归补证

本节追加于冻结提交 `58d0003f83d1c99505e1173508ea7e2934d89411` 的原生宽回归期间。Reviewer 只读检查生产与仓库测试，未修改它们；按主 Agent 明确要求，顺序执行一次 shutdown 的 baseline/head 窄复验。本节不把先前 `/mnt/d` 跨版本 runner 的 partial 输出当作冻结验收，也不以窄跑通过冲销宽回归失败。生产冻结版本仍为 58d；主 Agent 后来保存的仅测试修正提交 `d402ff3a06` 不在本节实际 A/B checkout 中。

### Compression deterministic fallback：因果未定

冻结日志 `.build/postgresql/unified-task24-frozen-native-areas.log:389` 记录 `test_compression_stall_deterministic_fallback.py` 为 5 passed、1 failed。失败项为 `test_over_window_request_commits_the_deterministic_fallback_on_the_first_stall`。第 406–418 行可见：primary summary 已 dispatch，随后记录 `stall_interrupted`，取消 worker 在 2 秒 grace 内未退出；deterministic rung 已启动，但在 `conversation_compression.py:2983` 的 summary dispatch 前检查到 fence 取消，最终 `no_progress`。两个 attempt 的 telemetry 分别为 aborted、4048/3988 ms。当前 inline 仅保留失败文件输出最后 30 行（`scripts/run_tests_parallel.py:890`），没有完整 assertion traceback；不能将推断的失败断言冒充已观察的 traceback。

测试与实际调用链的核对结果：

- `tests/agent/test_compression_stall_deterministic_fallback.py:36` 明确构造临时路径的原生 SQLite `SessionDB`，并传入真实 `AIAgent`；`agent/agent_init.py:1115` 保存该实例，`conversation_compression.py:2731` 的 lease、其 cooldown 读写使用该实例。没有发现该测试把 session lease 改选到 PostgreSQL 的直接路径。
- 测试把 `call_llm` 替换为等待取消的 stub，关闭 fallback chain；`fast_timeouts` 保留原合同 `(2.0, 20.0)`。本用例的 70k tokens 超过 64k window，`conversation_compression.py:1210` 将 primary pre-commit ceiling 收敛到 idle 2 秒；`_run_pinned_compression_retry` 又为 deterministic rung 分配自己的预算。日志中的网络围栏 metadata 警告早于压缩开始，不能据此认定 summary 网络调用卡住。
- deterministic worker 在 dispatch 前仍要做 snapshot、lease/cooldown 读取、memory context 和 heartbeat 等准备（`compression_facade.py:144`、`conversation_compression.py:4078`、`:4105`、`:3809`）。当前日志没有阶段耗时或超时瞬间线程栈，无法区分 SQLite/锁等待、文件系统或调度延迟及其他间接影响。压缩入口的 `shared_metrics_events.begin_compression_attempt` 只写 `threading.local`，本身不打开新 metrics store。
- a875→58d 的 compression facade、conversation compression、context compressor、thread context、原生 `hermes_state*` 与该测试没有 diff。这缩小直接修改面，但不能排除新增 backend 消费者造成的间接资源争用，也不证明问题已存在于 baseline。

主 Agent 同环境按 a875→58d 顺序执行的 `.build/postgresql/unified-task24-compression-baseline.log` 与 `unified-task24-compression-head.log` 均为 6 passed、0 failed，分别约 14.2/13.8 秒；它们是单文件 `-j 1`，冻结宽回归为 6412 文件 `-j 3`。因此本项分类为 **需要同条件观测，尚不能判定 backend 实质因果**，不归为已证实的环境问题或既有失败。

下一最小观测是在保留原 deadline 的前提下，取得最终完整 traceback，并仅在隔离诊断层记录 primary/retry 的 worker 入场、lease 取得、cooldown 读取、summary dispatch 时间及取消时线程栈；随后比较 a875/58d 在相同并发负载下的同一合同。不建议先扩大 timeout、跳过断言或修改 Agent 核心。

### Shutdown：窄 A/B 未复现，宽回归存在跨测试污染证据

同一冻结日志第 1414–1435 行另有 2 项失败：

1. `TestRunningFireOwnerRegistry.test_shutdown_sees_all_concurrent_direct_fire_owners` 在 `tests/cron/test_shutdown_interrupt.py:211` 的 `entered.wait(timeout=2)` 抛 `BrokenBarrierError`。测试第 208–210 行启动线程，第 217–220 行才 `release.set()`/join，失败路径没有 `try/finally` 收束；autouse fixture 第 20–32 行只清 module 集合，不 join 工作线程。现有日志未给出两个 worker 在 barrier 前的阻塞栈，第一超时根因未定。
2. 后续 `TestExecutionScopedInterruption.test_replacement_execution_of_same_job_is_not_poisoned` 在第 373 行要求一次 `mark_job_run`，实际收到两次。其中 `job-1/replacement-owner` 匹配当前用例输入；额外 `same-job/old-owner` 匹配前一 barrier 用例的输入，强支持前一失败线程在 fixture 清理后继续运行并命中下一测试的 facade mock seam。尚未观察 thread id，不能把该推断升级为完整线程级根因证明；也不能将第二失败独立登记为 ownership 业务回归。

`run_one_job` 在进入被测试替换的 `_run_with_fire_claim_heartbeat` 前，仍会创建 durable execution、处理 handoff 和绑定 owner（`cron/scheduler.py:2792` 起）。新增 execution domain wrapper 与 SQLite 防误连 backend 检查属于该路径的变化面，可能增加配置访问；没有阻塞采样就不能排除它们，也不能用 scheduler facade 主体无 diff 来判定既有。第一失败应继续作为未分类的宽回归失败保留。

Reviewer 实际按顺序执行以下两条命令，测试均经 helper 内的 `scripts/run_tests.sh`；共享已准备的 PM Linux 解释器，`HERMES_TEST_FILE_RETRIES=0`，`-j 1`，原 deadline，`--tb=long`，未操作正式 Profile/服务，也未传 PostgreSQL 凭据：

```text
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --native --state task24-baseline-linux-state.json --log review-foundation-shutdown-baseline-ab.log tests/cron/test_shutdown_interrupt.py -j 1 -- --tb=long
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --native --state task24-native-checkout-state.json --log review-foundation-shutdown-head-ab.log tests/cron/test_shutdown_interrupt.py -j 1 -- --tb=long
```

| 实际 checkout（另行只读 rev-parse 核对） | 结果 | 原始日志 |
| --- | --- | --- |
| `a8753423841362c6c8d76e2dca094c95d690ba27` | 25 passed、0 failed，退出 0，11.9 秒 | `.build/postgresql/review-foundation-shutdown-baseline-ab.log` |
| `58d0003f83d1c99505e1173508ea7e2934d89411` | 25 passed、0 failed，退出 0，4.7 秒 | `.build/postgresql/review-foundation-shutdown-head-ab.log` |

这一次顺序窄 A/B 没有复现，不能说明在冻结宽回归的并发条件下两版本等价，也不能据运行时间差宣布性能结论。若继续诊断，最小观测是在隔离层于原 2 秒 barrier 失败时捕获两个 worker 栈，并在保留业务断言的前提下确保诊断清理始终 release/join，防止首个失败污染后续证据。

本次观察时冻结宽回归已经累计上述 3 failed 且仍运行；不能用任何局部绿测报告整体通过。全局结论保持 **`FAILED` / `CHANGES_REQUIRED`**，完整冻结回归、这些失败的处置与原 7 项适用非 WSL POSIX 主机验收仍未由本节闭合。

### 后续测试清理整改的独立复核

仅复核 `tests/cron/test_shutdown_interrupt.py` 当前未提交的唯一测试整改（新增 faulthandler 导入及第 210–230 行清理）；未修改生产或仓库测试。原 `entered.wait(timeout=2)`、每线程 `join(timeout=2)`、完整 owner 集合/重复 job 计数及最终 registry 清空断言均保留。`except BrokenBarrierError` 输出栈后 bare raise，没有返回成功或吞掉异常；其他业务断言仍直接失败。finally 先设置原 release Event、abort 原 Barrier，再 join 每个已成功启动的线程，最后统一断言没有线程存活，不会因第一个存活线程而跳过后续线程的 join。

独立 `.build/postgresql/review_foundation/test_shutdown_cleanup_probe.py` 直接调用当前原测试方法，隔离 scheduler 的执行 seam，不读源码断言，也不操作数据库。两个确定性失败分支分别检查：

- 将两个真实 worker 保留在 rendezvous 之前，直至原主线程 `wait(timeout=2)` 实际超时；原 `BrokenBarrierError` 仍向外抛出，原 Event 已 set、Barrier 已 broken、两个实际启动线程都已退出，恰好输出一次栈。
- rendezvous 正常完成后，让原第一项业务断言失败；原 `AssertionError` 仍向外抛出，两个线程都已退出，未输出 barrier 诊断栈。未增加原 timeout 或修改任何业务断言。

首次将真实 faulthandler 输出至诊断临时文件，2 passed（`review-foundation-shutdown-cleanup-probe.log`）；随后专门核对与原测试相同的默认 stderr 路径，在 pytest 捕获下仍输出实际线程栈并保留原异常，2 passed（`review-foundation-shutdown-cleanup-default-stack.log`，退出 0、3.7 秒）。两次均为原生 Windows PM 解释器、canonical runner、`HERMES_TEST_FILE_RETRIES=0`、单 runner `-j 1`。主 Agent 的 `unified-task24-shutdown-cleanup-windows.log` 另记录原 25 项为 25 passed、0 failed，已独立读取。

本范围未发现整改会吞掉已观察的 barrier/owner 失败或制造错误通过。它改善失败后的清理和证据质量，**没有修复或解释原始 2 秒超时**。若 worker 阻塞在 Event/Barrier 以外的不可中断 I/O，bounded join 不能强制终止它；存活断言仍会让测试失败，不能把本次 probe 扩大为所有阻塞情形都保证无存活线程。冻结 58d 宽回归现已新增 command discovery 第 4 项失败，尚未因本次测试清理而重跑或关闭；全局仍为 `FAILED`。

### Command discovery：原技能差异与新增 RPC 超时分开保留

冻结日志第 1808–1825 行的实际失败是 `test_ordinary_daemon_discovery_matches_legacy_extensions`，第 134 行报告 daemon 比 legacy 多一个 `/sdlc-review`（usage 0、origin bundled），该文件 1 failed、1 passed。Reviewer 按相同 PM Linux 环境、原 deadline、retries 0、canonical runner `-j 1 -- --tb=long`，在上述两个固定 checkout 顺序 A/B：

| checkout | 窄跑结果 | 原始日志 |
| --- | --- | --- |
| a875 baseline | 2 passed、0 failed，退出 0，16.2 秒 | `.build/postgresql/review-foundation-command-discovery-baseline-ab.log` |
| 58d head | 1 failed、1 passed，退出 1，59.1 秒 | `.build/postgresql/review-foundation-command-discovery-head-ab.log` |

58d 窄跑没有重现技能差异，而是在 `_legacy_ws_snapshot`→`_rpc_result(ws, rid=0)` 的原 20 秒 `asyncio.timeout` 内收不到 legacy WebSocket 的第一个 `commands.catalog` 结果，实际抛 `TimeoutError`。这是另一个失败信号，不能替换冻结日志的技能差异，也不能由 baseline 一次通过便认定是新增 backend 的稳定回归。原 runner 会在文件完成后删除测试 temproot（`scripts/run_tests_parallel.py:685–691`），这次输出没有保留超时瞬间的服务子进程栈。

按主 Agent 随后要求，Reviewer 在 58d 原生 checkout 的忽略 `.build` 内加入独立观察层，tracked 源码/测试保持 clean、ref 仍为 58d：`review_foundation/test_command_discovery_stack_probe.py` 直接调用原用例；仅对本测实际创建并持有的 `Popen`、且精确启动序列为当前解释器 `-m gateway.run` 或 `-m hermes_cli.main serve` 的两个子进程，在其 env 的 PYTHONPATH 前置临时 sitecustomize 注册 SIGUSR1 faulthandler。只有原 `_rpc_result` 实际触发 20 秒 `TimeoutError` 后，才向仍活的这些 handle 发信号、从新增日志内容输出仅含路径/行号/函数名的栈帧，并重抛原异常；不扫描其他进程，不重新发请求，不增加 RPC deadline。追加的最多 2 秒仅等待已经失败后的诊断输出，不把观察等待变成业务通过。

这一次有观测的原单用例为 **1 passed**、退出 0、11.5 秒（`.build/postgresql/review-foundation-command-discovery-owned-stack.log`）。原技能差异和 RPC 超时都未发生，因此本次没有发送 SIGUSR1，也没有失败栈；不将无异常的一次观察称为找到了根因或修复。

静态调用链缩小了下一次观察范围：

- `run_bootstrap.py:784` 同步调用 bundled `sync_skills`，返回后才构造 runner；READY 在第 881 行发布。没有直接证据支持“bundled sync 在 READY 之后还未完成”。`sync_skills`、技能 catalog/cache、command discovery 和该测试在 a875→58d 没有修改；这不能排除间接时序影响。
- `/sdlc-review` 带有 `environments: [kanban]`。该 relevance gate 经 `agent.skill_utils._detect_kanban`→`tools.kanban_tools._profile_has_kanban_toolset`，读取 ContextVar/配置，无直接数据库调用。`gateway/session_local_inventory.py:116–124` 会暂时 pop 全局技能 cache，在 `scoped_kanban_toolset_selection(["kanban"])` 下扫描后恢复；`tools.skills_tool.py:85` 的 cache signature 只含目录、disabled 与平台，不含该 ContextVar。并发 discovery 若在临时发布窗口读取，存在看见不同 relevance 结果的静态可能，但这段逻辑 baseline 已有，尚未证明它发生在本次失败。该文件本次后端变更仅涉及项目查询的 StorageError 传播，不能把相关性当作技能差异的因果。

后续最小证据应是失败时两个实际服务进程栈，以及同次请求的技能文件集合/manifest、relevance ContextVar、cache signature 和 cache 命中状态；不应先增加 deadline 或把业务对比断言删除。此处不登记未经复现的 cache 猜测为已确认产品缺陷。

截至本节，冻结原生宽回归 4 项失败仍未闭合。主 Agent 另已报告 PostgreSQL 处于 recovery mode；本 Reviewer 本节未运行 PG 测试、未操作服务或正式 Profile，也不把该不可用状态登记为功能通过或跳过。全局继续为 **`FAILED` / `CHANGES_REQUIRED`**，包括原 7 项非 WSL POSIX 主机证据缺口。

### 技能 cache 窗口的确定性行为见证与反证

随后按主 Agent 要求，Reviewer 在相同 a875/58d 隔离 checkout 中对上述 cache 候选做了确定性见证。先以 `git log -p -S 'saved = skills_tool._SKILLS_CACHE.pop' -- gateway/session_local_inventory.py` 核对意图：`c31291a765e4e8c59f59a9ecc242637a8739a4f2` 明确要求 CLI snapshot 临时纳入 Kanban 技能计数，并恢复 cache，使 TUI/Desktop/messaging 和 agent 自身技能索引保留各自视图。`80f37e36eda72c612c1ad8a87cd528b1c46786ee` 对 environment detector 的历史修复也明确指出 Kanban relevance 依赖执行上下文，不能记住进程第一个调用者的答案。

探针 `.build/postgresql/review_foundation/test_skill_inventory_cache_overlap.py` 使用临时 Profile、固定无 Kanban opt-in 的真实配置和实际 `environments: [kanban]` SKILL.md。两个线程各自绑定同一个 owning Profile：inventory 线程调用原 `_cli_skills`，仅在实际 `find_all_skills` 已扫描、写入 cache 并返回后，通过包装调用的 Event 暂停；普通线程仍处于原 `kanban_toolset_requested() is None`、真实 environment detector 为 false 的 scope。没有构造假 cache 记录、没有把普通 scope 改为 Kanban，没有读取源码作测试断言；所有数据与线程均为该 probe 所有，finally 释放并 join worker。

先行版本只检查真实 `scan_skill_commands`/`get_skill_commands`，a875 为 1 passed（`review-foundation-skill-cache-baseline-command-guard-green.log`）。这给出重要反证：`agent/skill_commands.py:486` 会再次读取 SKILL.md 并执行 environment relevance 检查，不能从底层 catalog 暂时含有该技能就推断 slash 命令一定被污染。此前本报告的静态候选推测由此收窄，**未证实普通 slash 层泄漏，不能解释冻结 `/sdlc-review` delta**。

补充记录底层真实列表后，两个 revision 都实际失败在同一列表隔离断言，canonical runner、retries 0、`-j 1 -- --tb=long`，均退出 1：

| 真实观察 | a875 baseline | 58d head |
| --- | --- | --- |
| 普通 scope environment detector / inventory selection | false / true | false / true |
| inventory 开始前普通 `find_all_skills` 含 gated skill | false | false |
| inventory 实际扫描结果含 gated skill | true | true |
| 暂停窗口内普通 `find_all_skills` 含 gated skill | **true** | **true** |
| 同窗口普通 `scan_skill_commands` 含 gated command | false | false |
| inventory 恢复后普通 catalog / command cache 含 gated skill | false / false | false / false |
| worker 完整退出 | true | true |

原始红测：`.build/postgresql/review-foundation-skill-cache-baseline-red.log`、`review-foundation-skill-cache-head-red.log`，分别 1 failed（pytest 0.34/0.30 秒）。精确触发位置为 `_cli_skills` 第 117–124 行临时发布/恢复同一全局 entry，普通 `tools.skills_tool._skill_catalog` 第 241–245 行命中仅由目录/disabled/platform 签名约束的 cached relevance 结果。恢复后原 catalog 被恢复，普通命令层自身的二次 relevance 检查在观察全过程中有效。

此项分级为 **minor：既有的底层技能列表 relevance 隔离问题**。它不是 PostgreSQL 业务问题，不是经验证的未授权工具执行，也不是本次新增 backend 回归；a875 与 58d 的真实行为证据一致。按主 Agent 的范围要求，只独立记录，不扩展本次后端生产整改。若后续单独修复，最小方向是让 CLI inventory 的临时 relevance 扫描不发布到普通调用者共用的 catalog entry，或为不同 relevance scope 提供完整一致的 cache 隔离；保留 CLI 正确计数及普通 slash 二次检查。

原 command discovery 技能差异和独立 RPC 超时仍待失败时证据闭合，不因这个已存在的列表问题而被标记为已解释。主 Agent 此后通知 PostgreSQL 已由用户恢复并核对两主机 readiness/非 recovery，66a 完整 PG 批次已重启；本节没有代替其最终结果验收。总体仍为 **`FAILED` / `CHANGES_REQUIRED`**。

### Hot Profile park：有观测窄跑未复现，冻结失败保留

冻结 Native 后续增至 6 failed。其中 `tests/gateway/test_multiplex_hot_serve_live.py::test_invalid_hot_profile_config_is_parked_and_unserved` 在第 295 行读取 `result['parked']` 时抛 `KeyError`（冻结日志第 2446–2453 行）；原 assertion 的诊断 tuple 尚未求值，因而没有实际 result 或 mux 日志。此处只审计这一项，新增 admission arrival-order 超时不在本节的独立诊断范围内。

Reviewer 在忽略的 `.build/postgresql/review_foundation/test_hot_profile_park_observation.py` 包装原模块实际 `control` 调用，直接运行原用例与原 mux/peer fixtures。只有 `rescan-profiles` 返回缺少 parked 或原 control 本身抛异常时，才输出完整脱敏 return/异常与该 fixture 所有的 stdout、gateway.log、errors.log；原 return 原样交给原测试，不更改任何 assertion、90 秒 boot、10 秒 socket、5 秒服务 future 或其他 deadline。两个 checkout 均只新增自有 `.build` 观察层，无生产或仓库测试修改。

按 **58d→a875** 顺序执行一次同环境、有观测的原单 case，canonical runner、retries 0、`-j 1 -- --tb=long`：

| checkout | 结果 | 日志 |
| --- | --- | --- |
| 58d head | 1 passed、退出 0，7.1 秒 | `.build/postgresql/review-foundation-hot-profile-head-observed.log` |
| a875 baseline | 1 passed、退出 0，8.1 秒 | `.build/postgresql/review-foundation-hot-profile-baseline-observed.log` |

原 case 对新建 invalid-hot 和把已服务 boot 改为无效配置的两条 rescan/park/撤销路由合同都执行通过；本次没有出现缺 parked，观察器未触发失败日志输出。因此既没有失败时真实 reply，也没有证据将冻结失败定性为既有问题或环境时序。

静态异常边界的具体结论：

- 原 `control` 第 44 行先断言 socket envelope `ok`，然后才返回 `result`。直接由 handler 外逸的 `StorageConfigurationError` 属于 Exception，`GatewayControlServer` 第 352–353 行会生成 `ok: false`，原测试应先在 control 内失败，而不是走到第 295 行的 KeyError。
- `_serve_profile_runtime` 第 431–444 行对构建/打开 secondary runtime 的 Exception（包括 StorageConfigurationError）已有 park 路径；adapter validation 的 `MultiplexConfigError` 在 `_apply_profile_changes` 第 278–289 行撤销并 park。reconcile 的普通返回合同包含 parked，当前 diff 没有改写这些 park 分支。
- `run_bootstrap.py:350–353` 的控制 handler 在原 5 秒 `future.result` 超时后，会正常返回 `{multiplex, pending, served_profiles}`，其中没有 parked。这是与现有 KeyError 相容的具体代码候选，但没有失败时 reply 就不能认定此次实际发生了 pending；也不能排除先 pending、后台稍后才失败的其他根因。

本节未发现可凭当前证据确认的新增配置异常外逸，也没有宣布原失败已经修复。观察层可在下一次原条件失败时保留缺失的结果与自有日志；不建议凭一次窄跑绿修改原 deadline 或放宽 parked 业务断言。冻结 Native 的 6 项失败、完整 PG 新批次最终结果及原平台缺口继续保留，总体 **`FAILED` / `CHANGES_REQUIRED`**。

### 原 5 秒 pending 合同的确定性 daemon 见证

主 Agent 随后要求只验证上述异步控制合同。Reviewer 先用 `git log -p -S` 核对 `ae601a7632824571b56c2788df17e0c92558d5b5` 与 `291959504057e02e2659a30e35219f352e97c648`：原设计在 a875 之前就明确为控制请求设置 5 秒 bounded wait；慢 adapter/reconcile 在后台继续执行，调用者得到 pending，不能把 pending 当作终态失败或已经完成。

新增自有诊断文件 `.build/postgresql/review_foundation/test_hot_profile_pending_gate.py` 与 `hot_profile_gate_sitecustomize/sitecustomize.py`，两个隔离 checkout 的 tracked 源码和仓库测试不变。观察层只给本测实际创建并持有、精确 argv 为当前解释器 `-m hermes_cli.main gateway run --quiet` 的子进程注入临时 import hook；在正常模块导入时包装实际 `_serve_profile_runtime`，仅当 name 为 invalid-hot 且 home 等于本 fixture 的临时 Profile 路径时，在第一次实际 serve 之前等待本测文件门闩。它保持事件循环可响应，不改 clock、socket response、future timeout、park 结果或原用例的任何 assertion；其他 Profile 和进程不被暂停。

原 control 返回后，观察层确认已进入实际门闩并记录完整真实 result，再释放门闩，通过原 identify 和状态文件观察实际的无效 WhatsApp 配置最终 park/unserve。随后仍将先前真实 pending result 原样返回给原用例，原用例继续在第 295 行读取不存在的 parked 而失败。finally 释放门闩并收束本测所有持有的子进程；未扫描或暂停其他进程。

按 a875→58d 顺序、同一原生 PM Linux 环境、canonical runner、retries 0、`-j 1 -- --tb=long` 的实际结果：

| 观察 | a875 baseline | 58d head |
| --- | --- | --- |
| 原 control 的 ok 断言 | 通过 | 通过 |
| 实际 rescan result | `{multiplex: true, pending: true, served_profiles: [default, boot]}` | 同左 |
| 原 control 请求实测耗时 | 5.0056 秒 | 5.0055 秒 |
| 释放门闩后的真实 identify / gateway_state | 两者均记录 invalid-hot parked | 同左 |
| 实际 served set | 只含 default、boot；invalid-hot 已 unserved | 同左 |
| 实际 mux 日志 | 原 WhatsApp open-policy `MultiplexConfigError`，随后 invalid-hot unserved | 同左 |
| 保留的原用例失败 | 第 295 行 `KeyError: 'parked'` | 同左 |
| pytest / runner | 1 failed、退出 1（10.43 秒） | 1 failed、退出 1（9.98 秒） |

完整红测日志：`.build/postgresql/review-foundation-hot-profile-pending-baseline-red.log`、`review-foundation-hot-profile-pending-head-red.log`。两日志另有诊断目录下 `spawns_gateway_lookalike` 的 UnknownMarkWarning，未跳过测试、未改变上述真实 daemon 执行或失败位置；失败原因明确为原用例 KeyError。

由此可以确认：**当实际 reconcile 超过原 5 秒控制预算时，原测试直接索引 parked 与既有异步 pending 合同不兼容；这个受控失败路径在 a875 已存在，58d 的实际 park/unserve 流程仍能完成。** 这不是把 fake parked 回包代替业务执行，也没有证据支持为本路径修改生产的配置异常边界或延长控制 timeout。

本见证仍不能补造冻结宽回归当时未打印的 reply，不能断定那次 6 项失败中的此项实际就是 pending，更不证明使那次 reconcile 变慢的具体原因。冻结原生失败日志继续保留；如后续整改测试，必须明确区分 pending 和终态，并验证真实 park、撤销服务及状态发布，不能只接受 pending 就判通过。全局继续 **`FAILED` / `CHANGES_REQUIRED`**。

### 新测试 helper 复审与真实 pending 正向复验

主 Agent 依据上述合同只修改测试，新增 `rescan_and_wait_parked`；本 Reviewer 未编辑生产或仓库测试。受审及实跑文件 blob 为 `c4c46a7bf2bafcab33a782036dee1fd302ca6d22`。静态复审未发现放宽业务门禁：每个场景只发一次 rescan；非明确 `pending is True` 时仍要求原 parked 字段并精确比较集合，缺字段/错误回包继续失败；pending 分支要求 multiplex 为 True，在该文件已有的 20 秒 eventual 窗口中只轮询实际 identify，要求精确 parked 集合及全部目标 home 已撤出 served set。原新建/已服务 Profile 两场景的 served 和 gateway_state 断言均保留，生产原 5 秒等待没有改动。

独立正向 probe 为 `.build/postgresql/review_foundation/test_hot_profile_pending_gate_positive.py`，复用前节同一真实 daemon 文件门闩。它在当前 Root 的 `task24-linux-state.json`（source 为 `/mnt/d/AI/hermes-agent`）运行，没有修改正在做冻结宽回归的 58d/66a checkout。与前次红测不同：实际 pending 返回后，观察层不等待最终 park；新 helper 的第一个 identify 得到真实 parked 空集合，观察层才释放门闩，并原样返回该尚未完成的 reply。因此后续等待和终态判据由受审 helper 自身执行，没有合成或提前等待终态。

实际命令经既有 helper 内的 canonical runner、PM Linux 解释器、retries 0、`-j 1 -- --tb=long`：

```text
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --native --state task24-linux-state.json --log review-foundation-hot-profile-pending-positive.log .build/postgresql/review_foundation/test_hot_profile_pending_gate_positive.py -j 1 -- --tb=long
```

结果为 **1 passed、0 failed、退出 0，case 68.0 秒**（不含 `/mnt/d` canonical 预编译等待）。持久的原始行为观察在 `.build/postgresql/review-foundation-hot-profile-pending-positive-observation.json`，`validated: true`：

- 两个原场景共 2 次 rescan，每个场景仅一次；第一实际 result 为 multiplex/pending True、served default/boot，原控制请求实测 5.00546 秒。
- 新 helper 自己读取了 58 次实际 identify，其中前 56 次 parked 仍为空；之后实际 invalid-hot 被 park/withdraw，新 helper 才让原用例继续。
- 第二场景的实际 rescan 终态 parked 为 invalid-hot/boot，实际 served 只剩 default；原用例全部状态文件与 served 断言执行完成。
- 唯一持有的本测 daemon 已退出并被回收，门闩 finally 释放。所有数据都是临时 Profile/文件，未操作正式实例。

这项局部测试整改及其 pending 等待路径已得到独立正向证据。原 a875/58d 两份门闩红测、冻结原生失败及当时 reply 未知的边界全部保留；主 Agent 的整文件 7 项日志 `unified-task24-hot-profile-async-contract.log` 在本节读取时仍运行，本报告不以单个 probe 代替其最终结果。其他未闭合失败、完整冻结/PG 门禁和平台证据缺口均不受本次通过影响，整体仍 **`FAILED` / `CHANGES_REQUIRED`**。

### 新增 major：可选 Project 展示击穿 safe launch 的冻结策略合同

**状态：已复现的新增产品回归，整改尚待独立验收。** 冻结原生日志第 5473–5487 行的 `tests/hermes_cli/test_safe_mode.py` 在第二次真实 `--safe-mode` CLI 请求失败（exit 1、request_failed）。此项不能归为时序或仅由预期的坏 YAML 警告造成；相同环境顺序 A/B 已复现直接因果。

意图已以 `git log -p -S` 核对：`ee6b11605014e2dc9dc33f546bb7fcee02576701` 明确规定 safe/ignore-user-config 为 owner 冻结策略，真实隔离 worker 不读 Profile YAML/插件/规则文件，且损坏 config.yaml 后第二次 safe launch 仍成功；`111ee7249e614bffa2555f6ee6895735ee8e5cb7` 又将这个冻结快照合同接入 `load_user_config_effective`。当前 effective loader 第 63–69 行仍优先返回 `worker_config_snapshot`，没有证据表明已经绑定的 worker 绕过该 seam 重读 YAML。

独立观察层 `.build/postgresql/review_foundation/test_safe_mode_observed.py` 直接运行原用例与真实 PTY/daemon/loopback model。原 CLI 非零时，在原断言触发前保存本测 owner 的 stdout/gateway/errors 日志及原审计 hook 已记录的 config.yaml 打开栈；不打印凭据或配置内容，不改原期限、断言或任一生产函数。

| 固定 checkout | 实际结果 | 日志 |
| --- | --- | --- |
| a875 baseline | 原完整 safe-mode 合同 1 passed，退出 0，37.1 秒 | `.build/postgresql/review-foundation-safe-mode-baseline-observed.log` |
| 58d head | 原相同 `SAFE_PROBE_two` exit 1/request_failed，1 failed，退出 1，18.57 秒 | `.build/postgresql/review-foundation-safe-mode-head-observed.log` |

head 日志第 304–353 行保留了 owner 的完整实际异常链：

```text
session.create -> AuthorityConnection._create -> resume
-> snapshot_info (session_local_inventory.py:202)
-> session_inventory:144 -> _project(cwd):66
-> projects_db.connect_closing:147 -> connect:124
-> resolve_db_configuration:101 -> _storage_config:87/90
-> live config.yaml parse failure -> StorageConfigurationError
```

原审计 hook 的实际 config-open 栈也记录同一 owner PID 的 `_project`→Projects connect→`load_user_config_effective`→`read_config_doc`，与上述异常栈相符。错误发生在本次 `session.create` 的 owner 展示信息生成阶段，还未进入这次 prompt/worker turn；不是 worker 的冻结快照被破坏。

精确新增触发点：`hermes_cli/projects_db.py:124` 从原直接打开 SQLite 文件改为每次 Projects connect 重新解析选定 storage；`gateway/session_local_inventory.py:68` 新增 `except StorageError: raise`。该 inventory 的第 144 行在可选 banner Project 标签查询时调用它，且发生在第 145 行已有 `owner_scope(authority)` 之前。因此损坏 live YAML 的 StorageConfigurationError 从可选 inventory 逃逸，导致整个 create/resume RPC 被映射为 request_failed。普通 fail-closed storage 选择本身必须保留；问题是 bypass 会话被要求完成这项额外 live-config 展示查询。

最小保持目标的方向：

- 对 `policy.ignore_user_config`（safe_mode 已蕴含它）的 inventory，保持可选 project 标签为 None，不做该附加 Projects 查询；会话、admission、worker 的实际持久化仍使用既有 owner authority/store，不回落数据库、不变成内存 turn，也不关闭 safe 功能。
- 普通 Project 查询应置于已有明确 `owner_scope(authority)` 内；本 probe 仅一个 Profile，未单独声称已证明多 Profile 串库。
- 如需要在 bypass banner 仍显示项目名，应由 owner 已持有的明确 settings/scope/domain 资源读取。冻结的 agent 默认配置与持久 store 身份是两种边界，不能因 snapshot 缺 storage 配置而为已选 PG owner 改开 SQLite，也不能在多 Profile owner 绑定一次性的全局 worker policy。
- 不将 `db_setup` 改为 fail-open，不让 PG 配置错误回落 SQLite/内存，不以删除坏 YAML 阶段或放宽 safe-mode 审计断言制造通过。整改后仍需原完整三阶段（普通 sentinel、两次 safe launch、config-only 插件语义）的真实正向复验及相应后端边界验证。

本项是本轮新增 **major**，与之前已确认闭合的数据删除/Bot Chat/房间整改分开记录；在当前冻结版本上它仍阻止批准。冻结原生此时已累计 12 failed，其他失败与完整最终验证仍按各自证据处置。整体继续 **`FAILED` / `CHANGES_REQUIRED`**。

### safe-mode major 的最小整改与新增 PG 合同复审

主 Agent 随后修改 `gateway/session_local_inventory.py`：普通 `_project(cwd)` 移入既有 `owner_scope(authority)`；`policy.ignore_user_config` 时保留 `project: None`，不做附加 Project 标签查询。Reviewer 只读复审实际 diff 与测试/日志，未改生产、仓库测试或活跃冻结 checkout，也未提交。此次受审生产 blob 为 `5028965b9752a1f9b7ac865a1d371d1a218abc53`，新增测试 blob 为 `685f27ab49721b9c5c36bf14fe45da7dc79c2ddf`。

在该最小 diff 中未发现新的 blocking/major 或功能/后端回退路径。跳过范围只有 bypass inventory 的可选项目名；实际会话/路由/worker 持久资源仍由已持有的 owner authority 选择，未把 agent 冻结默认值用于重选存储。普通 Projects 的 `_project` StorageError 传播和 db_setup fail-closed 保留，既没有新增 SQLite/内存 fallback，也没有关闭 safe/config-only 功能。普通查询在 owner scope 内是正向修复，避免借用前景 Profile。

新增 `tests/hermes_db/postgresql/test_local_inventory_storage.py` 的三项实际合同及证据已独立读取：

| 合同 | 原目标红测 | 当前绿测所证明的行为 |
| --- | --- | --- |
| 同 workspace、前景与 owner 两个 PG Profile 各有项目 | 原查询实际取出 foreground project，断言 owner project 失败 | 在 foreground scope 中构建第二 Profile 的真实 authority，库存项目名来自 owner project；owner store_id 为 surface-two |
| `ignore_user_config=True, safe_mode=False` | 真实 snapshot_info→Projects→坏 live YAML 抛 StorageConfigurationError | 既有 PG 会话的实际 snapshot 成功，project 为 None，owner 会话仍可读；直接 `_project` 对同坏配置仍明确拒绝 |
| `ignore_user_config=True, safe_mode=True` | 同上，在实际 snapshot_info 目标路径失败 | 同一 bypass 合同成功，恢复配置后重新经公共 factory 获取可读该 session，另一个 store 不含该 session |

`unified-task24-inventory-target-red.log` 为 **3 failed**（pytest 15.91 秒）；`unified-task24-inventory-owner-green.log` 为 **3 passed、0 failed**（runner 19.7 秒）。虽然 runner 的静态测试数量估计为 2，参数化实际执行的是 3 项，不将估计数当作跳过。surface_config 使用真实已升级、归属核对的随机 PG namespace、两 store_id 和 pool_size/connection_budget 1；没有 fake store 或模拟 SQL 结果。

SQLite 门禁没有放宽：使用 postgresql 目录的 autouse `pg_sqlite_guard`，既替换 `sqlite3.connect`，又对 `sqlite3.connect` audit 事件拒绝；teardown 还检查所有尝试，即使业务捕获拒绝也会失败。测试文件没有加豁免、关闭 guard 或改内存后端。独立读取的代码还保留普通坏配置的 StorageConfigurationError 反向断言。

验证范围必须保持明确：

- 当前两个 bypass 项先在配置有效时真实 `create_local_session`，再写坏 YAML，随后执行实际 snapshot_info。这是本次 inventory 修复的目标边界；先前“坏配置下新建会话”的初版更早在 routing/storage 解析失败，并未命中 inventory，不能登记为本修复的目标红测。计划账本已保留该事实，没有把早期拒绝隐藏为业务通过。
- 当前绿测证明已存在 PG 会话在坏配置下的 snapshot、原 owner 持久数据可读、恢复配置后公共 factory 重新获取及 peer store 隔离。owner authority 在重新获取时仍存活，未证明关闭所有 owner/连接后的独立进程重启恢复。
- 它不等价于“损坏 PG Profile 配置后新建 safe session 的全 RPC/worker E2E”；生产 routing 和其 fail-closed 未改。该更早边界不因本次三绿而扩大为通过或自动判定已修复。
- 原完整 `tests/hermes_cli/test_safe_mode.py` 仍需在主 Agent 的新冻结快照执行：包括真实 CLI/PTY、普通 sentinel、两次 safe launch、worker 文件打开审计与 config-only 插件语义。Reviewer 按要求未覆盖活跃 58d/66a checkout，正在等待新快照信息；不以这三项 PG 测试替代原合同。

因此本项状态更新为：**源修复及目标 PG 子合同复审符合预期，原 major 的完整验收仍待最新冻结原合同复跑。** 当前未新增需要生产修改的审查问题；完整原生/PG 结算与其他门禁继续保留，整体 **`FAILED` / `CHANGES_REQUIRED`**。

### 8d6f 原合同独立复验：Projects 目标闭合，另有 config-only metrics major

Reviewer 核对新独立 Native checkout 为 `8d6f7bdaebf8fc1749d155a455bbb2730d492ae3`、tracked clean，PM 解释器仍为既有 task24-full-test-env。按要求实际运行未包装的原 `tests/hermes_cli/test_safe_mode.py`，canonical runner、`-j 1`、retries 0、原 deadline。受审 inventory blob 仍为 `5028965b9752a1f9b7ac865a1d371d1a218abc53`；原 safe-mode 测试在 58d/8d6f 的 blob 都是 `592775ba89d09819b573e17e0cc3a6015c82445a`，没有修改审计或行为断言。

该完整原合同 **1 failed、退出 1，89.63 秒**，日志 `.build/postgresql/review-foundation-safe-mode-owner-accepted.log`。文件名 accepted 是运行前预设名，实际失败，不登记为通过。它已执行通过普通 sentinel 控制、第一次 safe worker 无文件泄漏、坏 YAML 后第二次 safe launch、原文件不改与工具一致性，最后在第 252 行 config-only worker 的 `.env` 打开审计断言失败。

因此原先 Projects inventory 击穿 `session.create` 的 major 可按具体根因闭合：8d6f 已通过其此前失败的完整真实阶段，并有前节三项 PG owner/持久化子合同支撑。**完整 safe-mode 合同仍未通过，新增的独立 major 不能被该局部闭合掩盖。** 8d6f 的 PG 测试改为以 pytest_plugins 注册原 surface fixture，核心三项业务断言及 SQLite audit guard 未减少。

对新的 `.env` 失败，Reviewer 仅扩展忽略目录的观察器，保留原 safe-mode 用例与原审计 hook，打印本测子进程的实际 start 角色（不打印 argv 的凭据）及 config.yaml/.env 打开栈。8d6f 再次有观测执行为 **1 failed、退出 1，16.49 秒**（`.build/postgresql/review-foundation-safe-mode-owner-env-observed.log`），仍在原第 252 行失败，没有调整超时。实际 start 记录第 353 行证明 PID 2854967 是本测 owner 2854573 启动的 managed worker；第 1116 行为该 config-only worker 的真实 `.env` 打开审计：

```text
conversation_loop._restore_or_build_system_prompt
-> lifecycle.invoke_hook -> observability.observe_lifecycle
-> relay_shared_metrics.observe_lifecycle:1435
-> _reconcile_send_consent_once:1411
-> db_setup.storage_backend:118 -> _owning_profile:26
-> secret_scope.build_profile_secret_scope:411
-> load_env_file:386 -> owning Profile .env
```

新增触发点是 `hermes_cli/observability/relay_shared_metrics.py:1411`：原先 `not send and not metrics.sqlite3.exists()` 即短路退出，如今先调用 storage_backend 再判断 SQLite/no-store。config-only 按原设计保留插件/lifecycle，所以进入此路径；`storage_backend` 虽声明 driver/secret-free，却通过 `_owning_profile` 在调用 snapshot-aware loader 之前先 hydrate `.env`。冻结 worker config loader 本身仍优先使用 snapshot，错误在更外侧的秘密作用域准备，不是 YAML loader 的 snapshot seam 失效。

此为 **major：config-only worker 的冻结 Profile 文件隔离合同回归**。先前 a875 同环境完整原用例为 1 passed，已覆盖该末尾审计；8d6f 原合同与带实际栈观察的原合同连续复现，不能先归为既有问题或时序。它不表示已证明数据出网或系统沙箱逃逸，而是明确的会话配置/文件 I/O 合同被新增 consumer 破坏。

最小整改必须同时保持两种边界：纯 backend 探测应尊重已绑定的冻结 worker 配置，且不 hydrate Profile 秘密/文件；真实持久 acquire 仍须使用明确 owner/settings/scope 与 owner-only 约束，不能因为 agent 默认 snapshot 缺 storage 字段而给 PG owner 改开 SQLite。若 consent store 仅 owner 持有，应沿 owner 明确资源处理；不以关闭 config-only 的插件/lifecycle、删除 `.env` 断言或 SQLite/内存 fallback 掩盖问题。该交界已及时发给主 Agent，请其与 metrics Reviewer 一起处理。

本节未修改生产、仓库测试或快照 tracked 文件。原 Projects major 目标闭合，新 config-only metrics major **未整改验收**，原完整 safe-mode 合同及全局仍为 **`FAILED` / `CHANGES_REQUIRED`**。

### 51b3 原完整 CLI 合同通过，局部 major 闭合

主 Agent 的 selector 窄修为 `51b3e61c6c2c6338f84acc5965f32c078a58d520`。Reviewer 独立核对 `task24-selector-checkout-state.json` 对应该完整 ref、tracked clean，沿用原 task24-full-test-env；未修改快照、生产、测试断言或期限。`db_setup.py` 受审 blob 为 `380006f7c23d1b6250a3d6572494fc403eeb537d`。原 safe-mode 测试 blob 仍为 `592775ba89d09819b573e17e0cc3a6015c82445a`，与 58d/8d6f 相同。

本次实际运行原文件，而非诊断包装或 selector mock：

```text
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --native --state task24-selector-checkout-state.json --log review-foundation-safe-mode-selector-accepted.log tests/hermes_cli/test_safe_mode.py -j 1 -- --tb=long
```

canonical runner、retries 0、原各阶段 deadline；实际 **1 passed、0 failed、退出 0，总 case 96.1 秒**。日志 `.build/postgresql/review-foundation-safe-mode-selector-accepted.log` 记录 100% 完成，无文件重试。原断言全部执行通过：普通 owner sentinel 正向控制、safe worker 隔离/持久 admission、坏 YAML 后第二次 safe launch 且配置内容未改、工具保持一致，以及 config-only 保留插件 discovery、worker 未打开 config.yaml 或 `.env`。

窄修只在 `worker_config_snapshot() is not None` 时跳过多余的 `_owning_profile` 秘密 hydration；仍通过原 snapshot-aware `_storage_config`、`_storage`、`_backend`，没有新增 backend 默认值或 fake policy 来源。未绑定 worker policy 的普通 owner 路径、真实 `resolve_db_configuration`/acquire、owner-only、明确资源身份检查均未由该 diff 放宽。六项永久新进程合同的源码另已静态核对：ordinary/ignore/safe × SQLite/PG，真实绑定 snapshot、阻止 Profile config/.env 打开并禁止导入 PG drivers；不以这些窄探测替代本次真实 CLI 全链通过。

据此，**本 Reviewer 发现的 CLI Projects 展示击穿创建，以及 config-only selector 触碰 `.env` 两项 major，按原完整 CLI 合同均已整改验收闭合**。保留原 a875 绿、58d Projects 红、8d6f 末阶段 `.env` 红及审计栈，不覆写失败证据。

批准范围必须限定：这个原 CLI 用例没有 PG opt-in managed worker 的指标持久化，也没有 PG Profile 遗留 metrics.sqlite3 反例。plugins/metrics Reviewer 正在处理这两项真实交界（`review-pg-managed-metrics-red.log`），不能用本次 CLI 绿外推所有 worker 指标或全部 PG no-SQLite 业务均通过。owner PG 组、Root 报告的其他检查以及本次 CLI 独立结果各自保留归属；完整全局结算、其他原生失败和适用平台缺口仍未由本节验收。整体继续 **`FAILED` / `CHANGES_REQUIRED`**。

## 6923825 后两项 Native 宿主夹具合同复审

本节只读审查当前 HEAD `692382575fc96dcfc630be4e5f43ac8ea29fd2df` 后的两个未提交测试 diff，不修改生产或仓库测试、不运行新的重复 runner、不改原冻结报告。受审内容 blob：`tests/tools/test_command_guards.py`=`16f345b5ed0849617408e20f191ff5d965efb065`；`tests/tools/test_termux_api_detection.py`=`c9617690bbabecc08a250cc1817ce17df7deb1f9`。

**本次两项测试修正未发现新增 blocking/major，可接受其局部合同调整；整体仍 FAILED / CHANGES_REQUIRED。** 它们没有修改生产保护、后端选择、OS 探测或任何 deadline。

| 位置 | 冻结真实失败及修正后的合同 |
| --- | --- |
| `tests/tools/test_command_guards.py:80–94` | 冻结 `2a2684390016a1bfadc4c759bf2151945425f077` 的 PM Linux 解释器位于 `/tmp/...`。旧目标 `rm -rf /tmp` 是运行时解释器的祖先目录，实际日志明确 `Runtime self-delete block: the Python interpreter...`；返回 approved=False、callback=0 是正确硬保护，不应为了让 callback 被调用而关掉它。现 deny 测试只改为本测试 tmp_path 下独立 `approval-target`，保留 approved=False、callback 恰一次和 allow_permanent=True；新增真实 `Path(sys.executable).resolve().parent` 删除目标，令 callback 返回 session 仍要求 approved=False 且从未调用 callback，直接加强“不可审批覆盖运行时保护”的行为合同。两项只调用 guard 进行判定，没有执行删除命令。 <!-- no-tmp: ok — 历史红测的故障目标与解释器祖先路径证据，不是新建临时目录或执行命令 --> |
| `tests/tools/test_termux_api_detection.py:189–201` | 冻结结果已经含 `Termux:API microphone recording available (sounddevice not required)`，没有 app 缺失警告；available=False 来自原生 WSL 缺少音频转发的另一条警告。当前断言要求真实 detect_audio_environment 产出 Termux 成功 notice，并继续拒绝误导的 app 缺失 warning；不再将整台宿主的 available 强行规定为 True。邻接的 clean-probes-no-match 负例仍要求 available=False 和 app 缺失 warning，原探针 ladder 返回 True/False 的合同亦保留。 |

生产顺序已逐行追踪：`tools/approval.py:1152–1174` 的 `_floor_block` 在 `check_all_command_guards:1248` 的人工/allowlist/模式判断前执行；运行时匹配来自 `agent.runtime_self_protection.command_deletes_runtime`，不是测试替换。`tools/voice_mode.py:255–277` 仅在 binary 和 app fallback 成功时给 Termux notice，而 `detect_audio_environment:328–351` 独立记录 WSL 警告、以 `not warnings` 汇总 available。新断言正好对应这两个不同层次，不删除或伪造实际警告、不把宿主其他不可用条件伪装为成功。

按 root 意图核查要求还读取 `git log -p -S`：运行时不可删除 floor 来自 `541e4dc0ba6d50e3e4554611c3e6b2c0865187c4`，其注释明确不能由 yolo/mode=off/cron approve 覆盖；Termux 原回归测试来自 `0a5c5519fcb503fcff40f9183a4a0a72a6b42caf`，目标是探针不确定时信任已存在 binary、消除错误 app 缺失提示，并保留确认缺失的反例。`a875342384..692382575f` 对 `tools/approval.py`、`agent/runtime_self_protection.py`、`tools/voice_mode.py` 无 diff；此事实仅支持这些生产合同未被本后端范围改写，不冒称它本身是宽回归基准通过证据。

本次 diff 没有新增 `sys.platform`、`is_wsl`、container 等宿主事实补丁，没有改变 timeout/sleep。Termux package-manager 命令、PATH 和音频导入仍沿用原测试夹具；这是实际公开检测函数下的可控依赖合同，不是实际 Android/Termux 麦克风端到端验收，也不证明 WSL 音频已可用。

已直接读取并保留以下 Root 执行日志；本 Reviewer 未冒称独立代跑：

- `.build/postgresql/unified-task24-native-host-fixtures-red.log`：冻结 2a 的原两文件 **24 passed / 2 failed，exit 1**，包含以上完整真实输出。
- `.build/postgresql/unified-task24-windows-host-fixtures-green.log`：当前两文件 **27 passed / 0 failed，runner 4.2s**，19 个 guard 与 8 个 Termux 项。
- `.build/postgresql/unified-task24-native-host-fixtures-green.log`：当前两文件 **27 passed / 0 failed，runner 7.0s**，原生 Linux PM 解释器，19+8 项均执行。

上述日志都通过 canonical `scripts/run_tests.sh`、无文件重试结算；本次不重复已完成的同一窄范围测试。该证据允许局部测试整改，不能擦除此前冻结宽回归失败、代替后续新冻结完整验收、关闭其他 metrics/发行门禁或填补非 WSL POSIX 私有启动页的平台证据缺口。全局结论保持 **FAILED / CHANGES_REQUIRED**。

## 29796fc 更新收尾编译夹具的独立复审

范围为 HEAD `29796fc67d3580adbea66ce83306ded4ee7007c0` 上 `tests/hermes_cli/test_update_finish.py` 的单文件 +6 行候选；本 Reviewer 只读完整 diff、真实 builder/历史意图及脱敏观察产物，未改生产、仓库测试或候选、未重复 runner、未提交。已核对当前文件 SHA256 为 `f19186d5373dd2b743407dd5604bedf47582edcb2934473952676c89f5fc15b9`，与 `task24-update-candidate-state.json` 的单文件候选标识相同；该状态记录独立候选目录、上述基准 ref 和真实 PM Linux 解释器。准备脚本从冻结 checkout clone/checkout 基准，仅覆盖该测试文件并复用已准备 node_modules，未覆盖旧冻结证据树。

**这六行是合理的测试输入补齐及成功产物断言，未发现新增 blocking/major；只允许该局部测试修正，全局继续 FAILED / CHANGES_REQUIRED。**

真实发布合同来自 `c1f19acb7f8d6716750778e2565fd67f85d66090`（`fix(tui): ship runtime Python helpers with the built product`），已逐项阅读该提交的 builder、freshness、文档、实际消费者和 JS 测试：

- `scripts/build/tui.mjs:70–77` 在 esbuild 成功后必须把源 `ui-tui/scripts/gateway_bootstrap.py` 与 `clipboard_image.py` 拷贝进产品 `dist/scripts/`，然后才记录产品 receipt。`frontend-common.mjs:139–140` 只有 compile 全部成功才 publish，失败清理 scratch，因此仅 esbuild 输出成功不代表产品已经发布。
- `ui-tui/src/lib/pythonHelpers.ts` 优先取随编译产物携带的 helper；gateway/clipboard 消费者走这个 helper 路径，以支持 Python 包与 TUI 位于不同发布目录。freshness 同时把两文件列为输入。原提交的 JS 产品测试还在删除源目录后从发布产物读 helper，表明它们不是可省略的测试噪声。

观察证据 `.build/postgresql/unified-task24-update-compiler-observed.log` 为原两目标 **2 failed、14 deselected**，未当作完整文件结算。两个 `update-finish-test_*.json` 均记录真实 esbuild `Done in 1/2ms`，随后 `cpSync` 对 fixture 的 `ui-tui/scripts/gateway_bootstrap.py` 抛 `ENOENT/lstat`；因此没有发布 `ui-tui/dist/entry.js`。success case 在后续执行该文件时非零，compiler-failure case 在要求此前 TUI 成功的存在断言失败。后者另外仍真实产生 web `TS2322`/`TypeScript build failed`，没有被替换成假异常。completion child 的 code=0 与 C3“已提交代码的 build 失败作为 owed follow-up”合同一致，不能把它误读为编译产品通过。

修正只在 `_npm_graph:424–427` 用 `shutil.copy2` 把仓库实际两个 helper 作为真实输入放入所选临时 source，不预制 dist、不替换 builder/编译器、不略过 helper 发布。成功用例 `:456–457` 新增两个 `dist/scripts` 文件存在断言。原真实 Node 运行、npm lifecycle 所选解释器、web 编译、父 update lock 保留、配置迁移、原 receipt/plan/token、install stamp 与 completion 结果断言均保留。真实 TypeScript 失败用例 `:486–522` 也保持原非零编译输出、成功 TUI/缺失 web、维护和重启继续、receipt build follow-up、pending tail 与无 install stamp；并未把失败改成成功。

候选完整文件现已结束，本 Reviewer 已读取 `.build/postgresql/unified-task24-update-compiler-candidate.log`：canonical runner、`-j 1`、retries=0，**16 passed / 0 failed / 0 skipped、exit 0、40.4s**。原 `platforms('posix')` 和 child 90 秒 deadline 未改，没有 fake OS、增加期限、削弱 lock/receipt 或关闭失败路径。本结果为 Root 在独立候选执行，本 Reviewer 未冒称代跑，也不将它外推到 Windows、完整更新发行 E2E、全后端/全原生矩阵或其余失败根因。另行进行的 managed compression 30 秒失败诊断不在本节结论中，局部重跑通过不能由此宣称其根因已确认或修复。整体仍 **FAILED / CHANGES_REQUIRED**。

## 69d Managed Store double 与 Relay 同步合同复审

本节只读 HEAD `69d455ccd377085b15dbb49f789bc9a3d5e8b8aa` 后的测试夹具候选，不修改生产/仓库测试、不提交、不重复 runner。原 69d 全矩阵仍不得外推为通过；本节不代替等待最终日志后的分域结论。

### Store double 的身份缺口

源码阶段发现 `test_managed_worker_rpc_close._execute` 的 Store double 不含 owner_read；新生产执行入口确实会 `quiesce→owner_binding→owner_read('storage.identity')`。Root 扩展核对同类五文件后，真实日志 `unified-task24-69d455-managed-fixtures-red.log` 为 **10 passed / 21 failed**，均保留实际 AttributeError 栈；69d 宽回归的 `test_authority_turn_error_surface.py` 另有 **7 passed / 1 failed**，失败项复用 `test_managed_worker_route_key._execute` 的同一个 Store double。这是新增必需身份合同未补入单元替身的测试门禁缺口，不能把真实生产 quiesce 改成对缺方法容错来消除它。

当前 `tests/gateway/fixtures/worker_store_identity.py::SQLiteWorkerStoreIdentity` 的修正合理：

- `__init__(rpc, scope, *args)` 从真实 RuntimeSessionStore 构造参数的 `scope['profile_id']` 取得本测试 owner home；这些 caller 均由原 assignment 使用绝对 tmp_path 构建。没有硬编码默认 Profile、读取真实用户配置或从 ambient env 另猜身份。
- `owner_read` 只允许 `storage.identity` 且参数为空；返回与真实 SQLite owner 相同的五字段 `{version:1, backend:'sqlite', profile_home, store_id:None, target:None}`，由原 `owner_binding` 校验/缓存。没有预填 PG 绑定、伪造 worker 进程标志或 monkeypatch quiesce。
- 五个 Store 只继承此方法并删除原空构造；各自 get_messages、token flush、finish、close、事件记录和全部业务断言未动。生产 `managed_worker.py`、`worker_metrics_shutdown.py` 相对 69d 无 diff。SQLite 正确早返不等于省略 PG 指标屏障，后者仍有独立真 PG/SDK 合同。

上一轮读取 `task24-runtime-candidate-state.json` 时，其 source 为目录 `task24-runtime-candidate-4a8548b0a1`，八个 overlay SHA256 已逐项与当时实际文件核对一致；identity helper SHA256=`8c6ac6de7ceef2ff1bdf27d67f3f62698c86e76bcd0853bd7fb0d199f7e051dc`。该候选还含另一个 Reviewer 范围的 Matrix 关闭实现/测试，不能把它当成纯测试候选或声称本 Reviewer 通过了 Matrix 实现审查。下文新九文件候选是另一个目录与另次执行。

已读取 Root 独立候选日志 `unified-task24-runtime-close-candidate.log`：canonical runner、retries=0、`-j 3`，七文件 **37 passed / 0 failed、exit 0、40.3s**。其中五个 managed 单元文件 **31 passed**，Matrix close **2 passed**，实际 SQLite SDK 独立合同 **4 passed**。本 Reviewer 未代跑；当时这批没有 authority error-surface 或 Relay 全文件，不能把后来结果追记入此 37 项。

### Relay 的 ACK 与实际模型入口

69d 宽回归 `test_relay_native_turn_lifecycle.py` 为 **9 passed / 1 failed**；实际失败在旧 `:249`，首条已有 EYES、第二条 admission 已提交但 `executed=[]`。已读取 `02438db863e199431b85021806a3467b0c9324a4` 的意图及当前生产调用链：`producer_turn` 先 `await _open`，其中先执行 `on_processing_start`（发送 EYES），随后才 yield 给实际模型路径。因此“EYES 已出现”不能证明 `_stub_model` 已经 append 执行记录；不据原断言失败猜测业务队列已乱序。

当前测试只有三行同步增量：创建 entered Event；在原 held 模型入口、原 release.wait 之前 set；在发送第二条之前真实等待 entered。`_stub_model` 先 append `executed` 再调用 held，故该 Event 正好确认首模型已入场，且 release 尚未设置，第二条仍排在一个实际被 gate 的运行 turn 后。它没有伪造 executed/reply/ACK 或先放行首条。原第二条提交后无 ACK、`executed=['first']`、释放后 `['first','second']`、两条各自精确反应序列、首条 reply 先于第二条 ACK 的断言全部保留。

新增 entered 阶段等待使用 20 秒；既有 ACK/commit/settled 各 20 秒上限不变，生产期限和 OS 判断未动。这个新语义阶段是补齐错误同步前提，不是将原失败等待直接延长；总测试可能多等待该阶段，不能宣称总 wall-clock 上限完全没变。当前 relay 文件 SHA256=`a7a0bcb5d789992d028e7e12a2e67cf1fbf4cfc54a1e40aefddc11cc07d0c9b2`。首次源码复审只接受方向并保留待验；现以下述真实结算更新该局部状态。

### 两批后续真实结算

再次读取当前 `task24-runtime-candidate-state.json`，source 已为新的 `task24-runtime-candidate-37e796ff48`，仍以 69d 为基准，九个 overlay 比前一候选多 Relay 文件。九个 SHA256 已重新逐项核对当前文件全部一致。该目录不冒称为运行旧 37 项的目录；也不把运行中的原冻结 69d 宽回归换成候选源码。

| 已完整读取的 Root 日志 | 本次实际结算与范围 |
| --- | --- |
| `unified-task24-matrix-and-relay-native-candidate.log` | PM Linux、canonical runner、retries=0、`-j 3`，**25 files、288 passed / 0 failed / 1 原有 xfailed、exit 0、64.9s**。Relay 全文件 10 pass，authority error-surface 全文件 8 pass；其余为列出的文件名含 matrix 的 gateway 合同，包含普通矩阵命名，不能泛称整个 Matrix SDK/PG 协议验收。原 xfail 位于 suppression contract matrix，未由本次测试修正新增。 |
| `unified-task24-worker-fixtures-relay-windows.log` | PM Windows、canonical runner、retries=0、`-j 3`，**7 files、48 passed / 0 failed / 1 Linux 平台 skipped、exit 0、70.7s**。五个 managed 文件、authority 全文件 8 pass、Relay 全文件 10 pass；原 Linux 专属 hard-stop 用例按真实宿主跳过，不修改或假冒 OS。 |

据此，Store double 及其 authority helper 复用路径、Relay 原十项合同在上述候选/宿主范围内均已实际通过，局部整改可以接受。它们没有关闭 PG 服务故障、原 69d 全 Native 运行结果、其他分域最终复审或非 WSL 平台缺口。37/288/48 三批有重叠且候选目录不同，不能相加作为独立覆盖数。本 Reviewer 只核对产物与源码，没有代跑；当前最终统一静态检查仍在运行，不提前计为通过。

这两项局部测试修正未发现新增 blocking/major，也没有通过修改保护/关闭功能取得绿色。69d 完整 PG 批次真实失败、其他 Native 结果和适用平台证据仍须各自结算；全局继续 **FAILED / CHANGES_REQUIRED**。

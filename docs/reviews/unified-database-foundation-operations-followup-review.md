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

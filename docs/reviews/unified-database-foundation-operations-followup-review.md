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

# 统一数据库协作域整改复审

## 审查范围

- 日期：2026-11-08；独立 Reviewer。
- 基准仍为 `a875342384`，当前 HEAD 为 `3febe6fc313faf34693ce9cb2075a3a894ea82d3` 加未提交整改工作区；本报告仅适用于本次核对的文件，不外推到后续修改。
- 保留 [原审查报告](unified-database-collaboration-review.md) 的全部原始发现、失败日志和过程记录，本报告不改写历史失败为通过。
- 本轮逐项读取实际整改：Board file_job 完成态转移与 stage 清理、附件规范路径及旧 raw 别名/token、所有 worker COMMANDS 的拒绝回执边界、phantom-warning Core 分流与 outbox、原生/桌面房间位置和 Profile scope、实际 server 注册及 capabilities run-store 选择。
- 本轮不改生产源码或仓库已有测试，不提交；独立探针仍放忽略目录 `.build/postgresql/`。

## 问题处置

| 原发现 | 实际整改与复审证据 | 当前处置 |
| --- | --- | --- |
| RoomStoreRef 被当作 Path，原生/桌面入口崩溃 | 原生入口比较 location_root；PG forwarding 绕过 SQLite handoff；handler 全程绑定目标 runtime scope；实际 server 注册的 groups.list/capabilities 均执行成功 | 已关闭本发现 |
| 附件路径别名误删活引用 | 新写保存绝对位置，blob 锁/引用计数采用规范 path_key，清理在 token 与全 store canonical 活引用核对后进行；门前快速预检与门内复查同时保留 | 已关闭本发现 |
| 已完成 file_job 永久阻止后续生命周期 | done import→archive/delete 与 archive→delete 有明确转换；未清 stage 仍保留阻塞，成功清理后才解除 stage 引用；固定旧代次归档目录随 hard delete 清理 | 已关闭本发现 |
| 拒绝 claim 在 COMMIT-loss 后改变 verdict | claims 每个 None verdict 与同事务 receipt；heartbeat/block/unblock/schedule/failure 同类 False 路径补齐；request_changes 的事务内拒绝也记录原始 tuple；complete 的失败写/审计拒绝保存原事务回执 | 已关闭本发现 |
| phantom-warning 卡住 outbox，ready/workspace/hook 不执行 | `_flag_phantom_prose_refs` 已有具名 PG 分流，warning 在短事务中登记；实际 warning COMMIT 后确认丢失、phase 重放后只有一条 warning，子任务 ready、整个 outbox 排空 | 已关闭本发现 |
| foreign Profile owner absent 时读取 launch store | `methods_groups_scope.invoke` 包住整个 handler，包括 forwarding 与本地 fallback；双 PG store 同 room_id 的实际 handler 返回 foreign room | 已关闭本发现 |
| scoping wrapper 与 HandlerRegistry rebind 不兼容 | scope sibling 动态读取 module._bound_server；capabilities helper 在 register 中正确 rebind/publish；实际 `tui_gateway.server._methods` 调用验证，不仅是 helper 单测 | 已关闭本中间整改问题 |
| capabilities 直接构造 SQLite RunIdempotencyStore | PG 通过既有 open_run_store 在所选 Profile 短期 acquire/close；原生类仅作延迟 SQLite factory；StorageError 显式传播 | 已关闭本发现 |

旧 PG 兼容未被新写规范化测试替代：独立构造前版已保存的 raw stored_path/blob 行，验证规范引用删除后别名仍可读、最后别名删除才清理实际文件；旧 raw cleanup token 无活引用可重放，有 canonical 活引用时保留文件且新引用被拒绝。

跨事务核对结论：`request_review` 的前置拒绝来自只读准备，没有已提交的主业务写；最终 handoff 的成功/False 与回执共用主事务。`request_changes` 的事务内拒绝现已修复。completion 的前置/guard/acceptance 可以有准备事务，最终完成的主写与回执仍在同一事务；审计拒绝的 event 与 CommandRefusal 已原子登记。文件准备、外部 acceptance 查询与 observer 等待不放进长 SQL 事务。未发现需要进一步处置的新 blocking/major。

## 最新独立验证

独立执行：

```text
HERMES_PYTHON=D:/AI/hermes-agent/.build/postgresql/full-test-env/Scripts/python.exe
HERMES_TEST_FILE_RETRIES=0
D:/Programs/Git/bin/bash.exe scripts/run_tests.sh .build/postgresql/review_collab_second_probe.py -j 1 -- -p tests.hermes_db.conftest -m integration --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

结果：**8 passed，0 failed，0 skip，退出 0，retries=0**；实际 pytest 8 项，runner 静态估算显示约 7 不影响真实收集结果。日志 `.build/postgresql/unified-review-collab-closure-independent.log`，耗时 65.1 秒。

八项实际行为：

1. request_changes 原拒绝真实 COMMIT 后丢 ACK，在正常 review handoff/claim 后仍精确重放原 False tuple。
2. owner absent 时，foreign Profile 的实际注册 groups.list handler 返回 foreign 数据，而不是 launch 数据或接受任意 error。
3. phantom summary 完成后，子任务正常 ready 且 warning 已落库。
4. 旧 raw 路径两引用按最后引用清理实际文件。
5. 旧 raw cleanup token 无活引用时重放清理并确认 token。
6. 旧 raw cleanup token 有 canonical 活引用时保留文件并拒绝新引用。
7. 真实 `tui_gateway.server._methods` 注册后的 groups.list 与 groups.capabilities 成功，无 SQLite 连接尝试。
8. warning 自身真实 COMMIT 后丢 ACK，重放 phase 后 warning 恰为一条、后续阶段全部排空。

所有 probe 使用 PM Windows Python 3.14.9、实际 PG fixture、归属核对的随机 Schema、临时 Profile，启用全进程 SQLite audit guard。没有给 capabilities 或后台路径开豁免；没有操作正式 Profile、SQLite、服务或正式业务表。复验后的非秘密模块 SHA-256 记录在 `.build/postgresql/review-collab-closure-source.json`。

另外独立读取原始汇总与各文件结果：Root 的 `.build/postgresql/unified-task24-collaboration-recovery-regressions.log` 为 7 文件 69 passed / 0 failed；`.build/postgresql/unified-task24-closure-edges.log` 为 5 文件 14 passed / 0 failed。后者包括两类审计 CommandRefusal 的真实 COMMIT-loss 重放。这些属于经核对的补充证据，不冒称本 Reviewer 重新执行的 83 项。

此前独立 33 passed / 3 failed 记录继续保留：两项文件门顺序回归已恢复门前快检；completion 故障注入改为观察实际 kanban_attachments INSERT 后才丢主 COMMIT ACK，不再误击前置准备事务。最新相关绿测具备正确的业务触发点与文件保留断言。

## 无法验证项与总体门禁

- 本协作域已复现的代码缺陷，在当前核对版本内未留下未处置 blocking/major。
- 最新 Native 宽回归尚由父任务重跑；此前 FakeService 缺 db_path 与原生同 home 的 state.db/shared-state.db 匹配问题不能凭口述宣布通过。本 Reviewer 未独立执行该最新 Native 批次。
- 最终全域 PG/Native 宽回归、最新静态/发行检查、其他 Reviewer 的全部整改以及最终代码提交，仍由总体 Task24 门禁核对。
- 非 WSL 私有启动页七项的适用主机证据缺口继续保留；本次八项 PG 结果不能替代。

## 结论

本次协作域已发现问题的整改复审通过，当前范围未发现新增未处置 blocking/major。总体合并结论继续保留 **`CHANGES_REQUIRED`**，等待尚未完成的总体验证与适用平台证据；本报告不授权宣称全系统 `APPROVED` 或 `READY_TO_MERGE`。

## 冻结 58d 后维护故障夹具复核

2026-11-08 再次核对冻结提交 `58d0003f83d1c99505e1173508ea7e2934d89411` 后 `tests/hermes_db/postgresql/test_domain_maintenance.py` 的测试整改；该次修正不改变生产实现。此前旧夹具无条件令第一个 write 事务提交后抛 UnknownCommitError，新增 completion 前置事务使其不再命中它原本声称的主完成事务。

新 `lose_completion_ack` 在调用真实 `repo.event` 成功登记 `kind="completed"` 后捕获该 Connection；`lost` 先完整退出原 `Transactions.write`，确认同一个真实事务正常 COMMIT、连接归还后才抛 UnknownCommitError。若业务 body 回滚或真实 COMMIT 失败，原 context manager 会直接抛错，不会执行后面的注入。这仍是客户端确认丢失的故障注入，不声称做过网络丢包，也不替代驱动错误分类测试。

两项原有业务证据完整保留：父任务已 done、子任务维护前仍 todo、hook 尚未触发；从另一 Profile 作用域对拥有者 home 连续维护后，子任务 ready、hook 仅一次；归档 Board 的未决完成意图仍可恢复、workspace 被清理且原 Board 的 hook 恰一次。`assert completed` 还防止故障夹具未命中目标写入时悄悄通过。未发现断言放松或存储 mock 替代。

独立窄复验：

```text
scripts/run_tests.sh tests/hermes_db/postgresql/test_domain_maintenance.py -j 1 -- -m integration -k 'committed_completion_recovers_downstream or archived_board_cannot_poison' --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

仍使用既有 PM Windows 解释器、retries=0、归属核对的随机 Schema/临时 Profile/SQLite audit guard。结果 **2 passed / 0 failed，退出 0，34.6 秒**；日志 `.build/postgresql/unified-review-maintenance-ack-independent.log`。另读取 Root 全文件日志 `.build/postgresql/unified-task24-maintenance-confirmation-final.log`，确认 10 passed / 0 failed 的原始汇总，但不冒称本 Reviewer 重跑全部十项。

本次测试整改复核通过；它只补正这两项 unknown-commit 恢复证据，不改变前述总体门禁状态。全 PG、Native 与其他最终验证仍须按实际最终汇总判定，不能用此 2 项或全文件 10 项提前宣布总体验收通过。

## 最后生产 120bf8c9d6c9 / HEAD 20a4789b35 的有界复审

本轮只读复核最后生产提交 `120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b` 与当前 HEAD `20a4789b35d4b38eec098c5a1203699200833474`。HEAD 相对最后生产提交只有 CLI 测试及文档；当前其他 Reviewer 的暂存变化也仅为文档。本 Reviewer 未代跑测试、连库、修改生产/测试或提交，仅核对实际源码、已有永久合同与父任务产物日志。

增量范围仍以此前独立复核的 58d→69d 为基础：Kanban、Cron、rooms、附件、工作区、outbox 及 Profile 改名核心实现没有在该增量继续变化；相关交界新增 owner storage identity、verification/RetainDB 的 worker 通道、metrics quiesce、inventory 归属与非文件 Profile 初始化已逐项追到实际调用者。69d→当前 HEAD 没有再修改这些协作生产路径；唯一新增生产修改为 MatrixRuntime.close 的 pending task 等待方式，由 Matrix 专域审查负责。本域未发现这项变更引入新的 Profile 路由或协作持久化入口。

同时读取 69d 后的 worker 生命周期单测整改：SQLiteWorkerStoreIdentity 只为原有 SQLite store doubles 补充 storage.identity 协议，未替换生产 guard 或取消原行为断言。relay 排队测试新增真实执行进入事件，再提交第二条输入，固定“已运行”的前提；原业务等待与结果断言保留。这些单测不充当 PG worker 持久化证据，后者由下表实际 managed 合同提供。

### 当前实际 PG 结算

已只读核对 `.build/postgresql/unified-task24-120bf8c9d6c9-full-pg-linux-serial.log` 的收集范围、逐文件结果和终态：**127 files / 689 passed / 0 failed / 0 skipped，exit 0，2474.4 秒**。范围明确包含全部 PG 目录、distribution 和显式的普通 Kanban daemon 场景。本轮采用跨文件 `-j 1`；文件内并发、故障注入、业务期限和 SQLite guard 没有因串行调度而取消。以下是该完整批次内的实际结果，不能再与 689 相加：

| 原发现 / 实际交界 | 永久合同及本次结果 |
| --- | --- |
| 普通 Kanban owner→真实 worker→模型工具→重开回执 | `scenarios/kanban_full_gateway.py` **1 passed**；另 `test_kanban_worker_e2e.py` **2 passed** |
| done file_job 转移、活引用附件路径别名、拒绝 claim 回执、原生/桌面 group typed ref | `test_review_collaboration.py` **7 passed** |
| 旧 raw alias/token、foreign Profile、实际 server 注册/capabilities、phantom warning 与 COMMIT-loss outbox 恢复 | `test_collaboration_recovery_edges.py` **8 passed** |
| Cron 显式房间 Profile 的同 room_id 隔离 | `test_review_foundation_room_routing.py` **1 passed** |
| 完成审计/产物/COMMIT-loss、具名命令回执 | `test_kanban_completion.py` **6 passed**；`test_kanban_command_receipts.py` **4 passed** |
| 工作区/Board 退休/附件删除意图、实际完成提交丢确认后的维护恢复 | `test_domain_maintenance.py` **10 passed** |
| 真实 CanonicalService 普通/文件 Send、冻结附件与物化 | `test_room_attachment_service.py` **1 passed**，并保留同批 rooms/附件并发、故障、限制等合同 |
| verification 普通/config-only 真实 worker、owner 重启与 peer 隔离 | `test_managed_verification.py` **2 passed** |
| worker 时间/retention 权限、同 Connection 回执、真实 COMMIT 丢确认与重放 | `test_worker_domain_receipts.py` **2 passed** |
| RetainDB 实际 sync_turn 持久入队、HTTP 等待、原 worker 退出、新 owner/worker 恢复与 peer 隔离 | `test_managed_retain_queue.py` **2 passed** |
| RetainDB typed namespace/token、旧 lease receipt 非当前授权、真实通道断开与 sticky journal | `test_worker_retain_commands.py` **3 passed**；`test_worker_retain_transport.py` **3 passed** |

本次结果补齐了本 Reviewer 旧 `worker-domain-consumers-review.md` / `worker-domain-first-fix-review.md` 中 RetainDB“尚未实施”的历史状态。当前 owner proxy、固定 store/plugin/destination、同事务 receipt、发送前 fresh owns_claim、断线 sticky 与真实 managed 恢复实现/合同已核对，原 owner-only 获取失败及后续通道问题在上述范围内已有整改证据；未发现以关闭 provider、删除 sync_turn、内存 pending、放宽 guard 或延长生产期限取绿。细节同时保留在独立插件 Reviewer 的 `unified-database-retaindb-worker-boundary-review.md`，这里不改写其原红现场。

### 其他当前产物与历史失败

另已读取以下真实终态，均为父任务执行产物，**不冒称本 Reviewer 独立重跑**：

- Windows 数据库 Native 合同：`unified-task24-120bf8c9d6c9-db-native-windows.log`，**228 files / 579 passed / 0 failed / 5 skipped，520.0 秒**；Linux 对应日志 `...-db-native-linux.log`，**228 files / 584 passed / 0 failed / 0 skipped，563.9 秒**。它们不等同于全部 Native 八目录宽回归。
- `unified-task24-20a478-full-branch-checks.log`：**14 checks ok，598 Python files，相对 a87534238413 的 health 0 blocking / 0 advisory**。这不是本轮追加报告后的再次静态运行。
- 最后生产的 Windows/Linux SQLite、PostgreSQL 四套独立 PM 环境准备日志均已读取；完整 PG 中 distribution **4 passed**、distribution initialization **2 passed**。Windows distribution 独立批次为 **4 passed / 0 failed / 2 skipped**，平台 skip 不冒算通过。
- `unified-task24-120bf8c9d6c9-contracts-and-tui-build.log` 包含 generated_contracts=true、strict_typescript=true 及新 TUI entry 产物；父账本记录退出 0。

前两份完整 PG 失败仍保留：`unified-task24-69d455-full-pg-linux.log` 为 **157 passed / 0 failed / 533 errors**；`unified-task24-120bf8c9d6c9-full-pg-linux.log` 为 **240 passed / 1 failed / 451 errors**，均为 `-j 3` 的非零批次。最新 `-j 1` 全绿证明当前列出的业务合同实际执行通过，不能反向证明旧 recovery 失败已定因或只由资源竞争造成，更不能删除它们的日志与账本。

### 剩余限制与结论

当前协作域源码、旧 major 的永久合同与最新 PG 真实执行未发现新增未处理 blocking/major；这是一项**有界领域结论**。以下总体限制继续有效：

1. `unified-task24-worker-host-loaded-observed.log` 的三个 Native 原文件联合批次仍为 **13 passed / 1 failed，exit 1，369.7 秒**。失败为 `test_managed_worker_launch.py::test_ordinary_owner_launches_tool_worker_and_detach_does_not_cancel[controls]`，原 20 秒窗口未见 approval prompt。不能由 owner 的 fsync/selector 采样推断 worker 根因，也不能因为 PG 串行通过就宣称它与本分支无关。
2. 旧 history、压缩和 host 的间歇失败仍未完成根因闭环；窄绿及负载观测不替代解释。最后生产的完整 Native 宽复验仍待结算。
3. 非 WSL 私有启动页七项仍缺适用主机证据，PG/WSL/当前双主机数据库合同不能代替它们。
4. 其他领域审查、当前生产与发行产物的最终门禁仍由总体审查合并，不将局部合同成功外推为全部并发、故障和平台情形已穷尽。

因此当前全局继续 **`FAILED / CHANGES_REQUIRED`**，Task24 不标完成，不给出全系统 `APPROVED` 或 `READY_TO_MERGE`。本节取代前文“等待 PG 完整批次”的当前状态，同时保留全部原失败、当时未完成项及其后续整改记录。

## 2026-11-09：Native pause-record 新失败的只读诊断

本轮仅按父任务要求读取原日志、生产/测试源码、CLI/项目指引与 Git 历史，没有重跑用例、连库、读取活进程状态、操作进程/服务或改生产/测试。检查时 HEAD 为 `99bd92d5ecdf63c93a01561d58769fd51360cbdf`，生产仍为 120bf8c9d6c9；该恢复点对本问题的相关代码没有修改。

### 确定事实

仍在执行的 20a478 全宽日志 `.build/postgresql/unified-task24-20a478-full-native-observed.log:4877` 结算原文件 **42 passed / 1 failed，53.7 秒**。失败为 `tests/hermes_cli/test_update_pause_record.py:739` 的 `test_an_accepted_stop_the_record_could_not_checkpoint_outlives_the_request_ttl[False]`，实际 `owed={'p': 71887}`，预期 `{}`。这是该文件的终态，不是整轮宽回归终态。

原 testcase 的 checkpoint 前提成立：`root.chmod(0o555)` 后 mark_stop_sent 的原始输出为 PermissionError(13)，且 `saved['stop_sent']==[]` 已通过；不能把问题解释成该次 checkpoint 实际成功。之后原目录已恢复 0755，marker 的 written_at 被改成当前 UTC 的 120 秒前。`gateway/status.py:1606` 的 TTL 为 **60 秒**，`:1619` 的 stale 判断为 UTC age > TTL。此 case 未调用 consume；同一参数化的 consumed=True 则要求已接受的 stop 在整个 drain 期间保留 restart debt。

### 实际协议与尚缺的分支证据

`hermes_cli/update_pause_record.py:857` 的实际算法为：先取得 `(asked, unknown)=_asked(token)`，再仅移除 `_live_pids(token) - asked - unknown` 中的 PID。因此，在本案 stop_sent 为空的前提下，p 保留至少有以下一种原因：

| 分支 | 必须补看的实际值 |
| --- | --- |
| PID 不在 live 集合 | saved.identities 中的 ct、真正 incarnation verdict；不能只由 os.getpid() 推断此协议的 live=True |
| asked 包含 PID | 主 marker/accepted receipt 的实际匹配结果；原请求过期不意味着 accepted receipt 也过期 |
| unknown 包含 PID | marker 或 `.accepted` 的真实读/解析拒绝；源码有意保持未知 stop 的债务 |

`_request_on_disk`（`:811`）同时读取原请求（60 秒 TTL）和 accepted receipt（无 TTL）。`_names_request`（`:828`）把 FileNotFoundError 判为 False，其余读/解析错误判为 None；匹配的 accepted receipt 或原请求 accepted=true 可以越过原请求 TTL。现有 traceback 没有保存两个 reader 的返回值、marker 的 accepted 字段、accepted 路径/内容或读错误，不能从最终 profiles 反推出是哪条证据分支。

identity 还有一条需要观察、尚未证实的分叉：`identity()`（`:74`）调用 fresh `update_lock.process_create_time`，记录 `ct:<seconds.3f>`；`identity_is_live()`（`:86`）调用统一 incarnation 协议。对本 PID，`update_lock._real_world()` / `_own_create_time()` 使用按 PID 缓存的 `_OWN_CT`，`_incarnation`（`:326`）通常要求两者在 **0.005 秒**内一致，另保留既有整秒兼容规则。若缓存 ct 与新读 ct 不一致，或缓存 ct 为空而新录 ct 非空，本 PID 可以被判为不同 incarnation，因而不会作为“同一 live、从未被 stop”移除。这只是源码允许的解释；日志没有两份 ct，不能据此声称缓存或宿主时钟已是根因。

需区分未知与明确不匹配：`identity_is_live` 使用 `incarnation_live(...) is not False`，通常的不可证明结果 None 仍算 live；笼统的“读进程状态失败”不能直接解释本案。另 `gateway.status` 的 Linux target_start_time 使用内核 start ticks，与 pause record 的 epoch ct 是两套各自同源比较的指纹，源码没有拿两者混比。

### 历史与基线关系

- `cff9e7a0f5` 的意图是 accepted stop 的无 TTL receipt，提交说明同时明确“Unconsumed requests still expire”。
- `7b68039222` 明确规定读拒绝/畸形为 unknown，继续保留债务；未消费的过期请求仍应过期。
- `ab8ef5a850` 统一本 PID 的 incarnation 判断，避免只因 PID 相同就接管旧 incarnation；不能为了这条断言改成裸 PID liveness。
- 对 `a875342384..20a4789b35` 和 `a875342384..99bd92d5ecdf`，`update_pause_record.py`、`update_lock.py`、`gateway/status.py` 与该原测试文件均 **无 diff**。已有 58d 宽日志中原文件 **43 passed / 33.3 秒**，69d 宽日志中 **43 passed / 32.6 秒**。

这些事实表明没有本分支直接修改该协议的证据；它们不是同一现场的 fresh baseline A/B，也不能排除分支的间接触发、既有问题或宿主条件变化。当前不能把失败定性为“已知基线问题”“负载导致”或“仅测试假设错误”。两个 wide diagnostics 插件的源码 hook 仅针对 managed-worker/压缩及 keyless-host 文件，没有为 pause-record 捕获上述分支值。

### 最小后续证据建议（由 Root 决定执行）

保留原 non-root Linux 宿主、chmod 前提、60/120 秒语义、actor/marker 和全部原断言。若进行下一次 canonical runner 观察，优先保持原**完整文件内顺序**，因为 `_OWN_CT` 是同一 pytest 进程内的缓存；只窄跑 False 的新进程可能隐藏此前缓存条件。一次绿应记录“未复现”，不能替代原红或反复盲跑。

观测层只包装实际调用并原样返回/重抛：记录 `_asked` 的 A/U、`_live_pids` 的 L、两个 `_names_request` verdict；在真实 `_incarnation(pid, recorded, world)` 调用处记录 recorded、world.pid/world.ct 和结果；在真实 creation-time/cache 调用处记录已发生的返回值。不要额外调用 `_asked`、`identity_is_live` 或 creation-time probe 来“再检查一次”，以免首次填充缓存或改变观察时点。

失败时另存本测试的 marker/accepted 的路径及白名单字段（target_pid、stopper_pid、target_start_time、written_at、accepted）和实际 read errno/解析错误，以及 drop 输入/输出中的 stop_sent、identities、profiles。原样保存到不会随 pytest fixture 清理的本次诊断目录，不扫描其他 Profile 或测试 home；不以这些读数执行 stop、restart、kill 或服务操作。

该最小证据可以将原因分到 TTL/accepted/unknown/identity 中的一条，再决定是否需要针对性复现或基线对照。当前不建议改 TTL、删除 chmod 控制、强行清债务、重置缓存或放宽 incarnation 规则。

### 本轮结论

已确认真实合同失败及其精确源码分叉，**根因尚未获得必要现场数据**。没有新增已验证的生产 major 归因，但该失败继续作为未闭合 Native 门禁；不能用历史 43 项绿或当前 PG 689 项绿将其关闭。Task24 和全局审查继续 **`FAILED / CHANGES_REQUIRED`**。

## 2026-11-09：pause 分支观测与 groups-route-parity 新现场

本轮继续只读，未开启测试、连库、操作进程/服务或改生产/测试。下述重跑均为父任务执行，本 Reviewer 核对原始日志/JSON及实际调用链。

### Pause：本次未复现，不关闭原红

`unified-task24-pause-record-branch-observed.log` 为原完整文件 **43 passed / 0 failed，40.1 秒**。已读取 `pause-record-observed-false.json` 与 `pause-record-observed-true.json`：

- False：原 stop_sent=[]，主请求和 accepted reader 均 False，asked/unknown 均为空，live 包含本 PID 332970；cached ct=1794159032.07，与 fresh 结果及记录的 `ct:1794159032.070` 一致，真实 incarnation verdict=True，最终 profiles={}。
- True：主请求过期返回 False，accepted receipt 返回 True；asked 包含该 PID、unknown 为空、live 包含该 PID，最终债务保持。缓存/新读 ct 同样一致。

这次准确走到了前节预期的两个分支，没有复现旧 PID 71887 的失败，也没有提供旧现场为何偏离的证据。原 wide 的 42 pass / 1 fail 不改写为通过；缓存差异等仍只是待捕获的解释，不能因本次 ct 一致而宣称已经排除。

### Groups-route-parity：确定现场与原契约

原 wide `.build/postgresql/unified-task24-20a478-full-native-observed.log:6335` 显示 `tests/tui_gateway/test_groups_route_parity.py` **3 passed / 1 failed，28.2 秒**。完整可用 inline traceback 的失败链为原文件 `:134` → `test_hosted_room_attachment_routes.py:75` → `test_hosted_room_driver_runtime.py:431`；`_wait_for(timeout=10.0)` 抛出 condition-not-reached。文件总耗时包括其他 case、准备与关闭，不能据 28.2 秒推断某个 IO 阶段耗时。

失败 case 绑定真实 Native room/附件库中的 note.txt 与 shot.png，冻结 task manifest（event/member 归属），然后用 HostedRoomServerRPC 驱动 member turn。它的 session server 是原 `_server_module()` 的本地 SimpleNamespace：session.list 为空，create 返回 runtime；prompt.submit 将 params 放入 submits，**同步**调用 `_hosted_terminal_callback({'status':'settled','text':'Read it.'})`。该 case 没有真实模型 HTTP、外部推理或 managed worker，不能借别的 worker/model 慢点解释它。

待完成的业务结果是 task settled、恰好一次 submit、文档路径仍可读且字节为 exact bytes、`_hosted_images` 中唯一图片字节与 PNG 相同。当前失败发生在这些后续断言之前；原日志没有保存 task 最终状态、submits 是否到达或文件准备阶段。

原 helper 先 runtime.start，再等待 **task 进入 TERMINAL_STATUSES 或 runtime.status().last_error 非空**，finally 原样 `assert runtime.stop(timeout=5.0)`。inline 最终仍是原 10 秒 timeout，未出现 stop 断言失败，表明原 stop 已返回成功；这不提供 stop 之前的 durable/task 状态，也不能排除 stop 等待期间才有晚到进展。

### 实际 runtime / driver / 附件调用链

```text
HostedRoomRuntime.start → supervisor._worker_loop → _run_cycle
→ room thread._run_room_once → _process_room
→ acquire/recover lease → start_task → _execute_attempt
→ RecordingTurnLocks → resolve/create session → bind/mark submitted
→ HostedRoomServerRPC.submit
→ capture_lease → prepare_before_submit(bound_submission_payload)
→ event/member-authorized HostedRoomAttachmentStore.read
→ capture_native_media / restore_native_media → document/image owner-local paths
→ fake prompt.submit → immediate _on_terminal → state.settle_task
→ terminal publication / driver observation
```

RecordingTurnLocks 是原测试的立即进入 context manager，不是实际等待审批的 profile lock。附件错误处理与普通 driver 错误通常会设置 last_error 或 terminal failed，使原等待提早返回；但 last_error 不是所有分支的证明：`_run_room_once` 静默处理 LeaseHeldError，`_on_terminal` 静默丢弃被 fence 的 StaleLeaseError / 部分 StaleTaskError。主管/room 线程尚未进入某阶段、阻塞中的原 DB/file 调用，或主 predicate 的原 get_task 读跨过 deadline，也都没有被当前 inline 分辨。以上是待观测分叉，**不是已确认根因**。

相对 a875，原 parity 测试及 session_hosted_attachments/session_ingress_media 没有 diff。Runtime 与 ServerRPC 的两处生产变化是 Path→normalize_location，此 case 输入 Path 仍返回 Path；附件 store 另有本分支新增的所选后端选择/SQLite location guard，不能把所有新调用成本直接视为已经排除。共享 `_legacy_runtime` 在 58d 加入固定业务 clock，避免该路由合同把 0.4 秒 lease 因磁盘/CPU延迟误判到期；原 10 秒外部等待与 5 秒 stop 未变。上述文件在 58d→20a 没有继续修改。

历史 `857d224808` 的明确意图是两条 groups 路由都携带 event/member 授权的文件，文档通过 prompt 路径行、图片通过进程内 `_hosted_images` 传递，不能退回“不支持附件”绕过。58d 原 wide 此文件 **4 passed / 3.4 秒**，69d 原 wide **4 passed / 3.1 秒**；它们只是历史对照，不能替代当前失败或 fresh baseline A/B。

### 最小后续取证建议（不由本 Reviewer 执行）

1. 保留原完整 4-case 文件顺序、真实 Native room/附件、原固定业务 clock、0.4 秒 lease、10 秒 wait、5 秒 stop 和全部文件结果断言。若一次观察绿，只记录未复现，不扩大超时或反复盲跑。
2. 包装**实际读取 seam** `tests.tui_gateway.test_hosted_room_attachment_routes._wait_for`，在原 timeout 抛出、原 helper 的 finally stop **之前**保存现场后原样重抛；只在 stop 后抓取会丢失最重要的进展状态。parity 模块导入的 helper 仍从该 globals 读取 `_wait_for`，不能只 patch 定义模块中已被导出的旧引用。
3. 以有界内存事件记录真实调用的进入/返回/异常及 monotonic 时间：supervisor/room cycle、lease acquire/recover、start/bind/mark submitted、附件 read、capture/restore、ServerRPC._call 的方法名、fake submit、callback 和 settle。重点记录静默 LeaseHeld/StaleLease/StaleTask 的实际异常；不要额外调用业务函数、再启动 driver 或通过新连接“复查”。
4. 保存原 predicate 已实际返回的 task/status，以及 cycles、current task、leases、blocked/deferred 状态、submits 数量、callback 进入/退出和 execution/cancel/lease generation；分别标注观察时点，不能拼成原子快照。原 get_task 每次进入/返回的耗时也需记录，区分 main poll 与 room worker。原 timeout 时可采本测试 runtime 自己的 supervisor/room Python thread stacks；不采其他用户进程。
5. 只在失败时一次写本测持久诊断产物，附件仅记录 manifest/路径/尺寸等白名单，不逐调用新增 fsync 或打印文件正文。不重置 lease、不改变 authority、scope 或存储实现，也不将 fixture 的同步 terminal callback 替换成别的完成机制。

当前缺的最小判断是：task/lease 在 10 秒内走到了哪一阶段、有没有发生静默 fence、submit/callback 是否真正到达，以及原 predicate 是否长时间停在自己的读调用。取得这些数据前，不能归因为 IO、CPU、固定 clock 或某个数据库冷启动，更不能用调大 timeout 宣布修复。

本节确认两份新观察的准确范围：pause **未复现**；groups 是尚未定因的真实 Native 超时。原红和所有总体平台/宽回归限制继续保留，Task24 与全局结论仍 **`FAILED / CHANGES_REQUIRED`**。

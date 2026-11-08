# 69d 候选 Plugins / SDK 独立分域审查（进行中）

输入为 `69d455ccd377085b15dbb49f789bc9a3d5e8b8aa`，重点复核冻结 58d 之后 Plugins/RetainDB/metrics/Matrix/Telegram 与单后端、发行验收增量，并重读当前生产代码及此前独立 major 的闭环记录。Reviewer 仅写本报告和 ignored 诊断，不改生产/仓库测试、安装、提交、管理数据库服务或正式 Profile。完整结果仍待 Root 汇总；本报告不是全域最终批准。

## 当前新问题

### [major，后续修正已获局部闭环] Matrix close 在等待清理回调时可能热循环并阻塞网关事件循环

位置：`hermes_db/matrix_runtime.py:129`，`MatrixRuntime.close` 的 `while self.pending: await asyncio.gather(*tuple(self.pending), return_exceptions=True)`；正常入口为 `plugins/platforms/matrix/adapter.py:1319` → `adapter_storage._StoreLifecycle.stop:58` → `PostgresCryptoStore.close:46`。

问题：`_wait` 把实际 driver awaitable 包装为 Task，加入 pending，并通过 `_finished` 完成回调删除。SDK caller 被取消时 shield 保留 driver Task，本来是必要的同步驱动边界。但 driver Task 已 done、`_finished` 回调仍排队时，另一个已唤醒的 disconnect 可以先进入 close。Python 3.14 对全部已 done 子任务的 gather 可以同步返回，await 不让出事件循环，pending 不会被清理，while 热循环，实际停止永不返回。

历史核对：这段实现最早来自 Task19 提交 `90f82575b0`，不是 58d→69d 新增行；但它属于 unified PG Matrix 实现并仍存在于当前候选，不能因之前局部绿测没有覆盖而放行。此前 ratchet 并发与 SDK 吞 StorageError 两项 major 的原修正仍在，本问题是新的独立关闭窗口。

独立有界调度复现：`.build/postgresql/test_review_matrix_close_scheduler.py`，SHA256 `74C7B62640B161C69FE4FD1872546B8390DCDEF62FB90C1E20BD61CEAA65D050`；经既有 PM Linux Python3.14.9/实际 mautrix SDK 的 `scripts/run_tests.sh`，retries=0。真实 SDK CryptoStore/SyncStore 类型，使用生产 `_wait`、`PostgresCryptoStore.close`、`_StoreLifecycle.stop` 和 `MatrixAdapter.disconnect` 正常关闭函数体；只在同步工作完成的 observer seam 用 Event 对齐一个合法调度次序。外层 SDK caller 先被取消，实际线程仍运行并完成，disconnect 被唤醒后必须排空残余工作。3 秒 SIGALRM 仅给观察设置硬上限，不改业务期限、不以 sleep 驱动时序。

日志 `.build/postgresql/review-matrix-close-scheduler.log`：**1 failed / exit 1**，runner 11.5s、pytest 10.73s；硬截断栈完整经过上述生产关闭链 → `matrix_runtime.py:129` → Python3.14 `gather/_done_callback`。脱敏红测观测已保留为 `.build/postgresql/review-matrix-close-scheduler-red-observed.json`（原输出路径随后由绿测更新）：runtime.closed=True、SDK caller cancelled=True、pending 唯一 driver Task done=True/cancelled=False，close 仍未返回。

证据边界：由于独立测试 PG 服务当时进入 recovery mode，按 Root 要求本 probe **没有 capture/open、PG fixture、数据库连接或 SQL**。CryptoStore 仅连接其实际 close 协议与 runtime，adapter 只提供关闭函数实际读取的生命周期字段；同步线程返回观察结果，不能冒称它已执行 PG 查询/提交或加密重开。该运行证明的是实际关闭调度缺陷，非“PG 数据已丢失”。对应实库 driver/commit 的关闭补验须待服务恢复后按拥有者随机 Schema 单次执行。

影响：一次合法的取消/完成竞态可使 Matrix 断开/监督恢复占住事件循环，阻止其他 Profile/平台任务和正常关闭。不能靠关闭超时的同 loop timer 解除忙循环。

最小建议：关闭时等待实际清理能完成的 `asyncio.wait` / settlement 屏障，保留 `_wait` shield 和 `_finished` 异常观察，不靠 sleep(0)、放宽期限或提前丢弃 pending。永久回归覆盖上述已完成但回调未执行的次序；另应核对取消 close 不会通过 gather 取消同步 driver 的包装 Task、使真实线程尚在运行却丢失 pending 跟踪。后者本 Reviewer 尚未单独执行，不另登记为独立已复现问题。Root 负责实现与红绿，当前未关闭本 major。

## 之前 major 的当前代码闭环

| 领域 | 当前源码核对与真实证据范围 |
| --- | --- |
| RetainDB managed owner-only、未知确认、旧租约 | ed0 bridge 在 69d 保留。owner identity 优先于 agent snapshot；closed operations 与 receipt 同 Connection，固定 owner store/plugin、destination 保持每 Profile 合法业务 namespace。send 前 fresh owns_claim 检查 PG status/token/lease；原 token 不能吞掉 retake。WebSocketException/OSError 捕获与稳定 request_id、sticky journal/finish 拒绝仍在。既有真实 managed sync_turn→HTTP→PG acknowledged/失败重开、HTTP 未释放退出后 claimed 恢复、peer/SQLite guard 的局部证据仍适用；HTTP 成功本身不当持久化证明。 |
| metrics ordinary/config-only | 2a 的已采用 owner facade、exact receipt metrics fence、真实 owner consent、quiesce/bind_profile_home、flush post-maintenance 保留。当前 collection/send gate 顺序与原 independent owner withdrawal probe 一致。模型指标和 owner 重开、peer 与旧 SQLite 全拒绝曾有真实 Windows/Linux局部运行；不是只检查 runtime 构造。 |
| metrics 跨 root | 本地 effect/intent/receipt 同事务；root 独立提交后 source CAS。withdraw/晚日 retire、same pool1、rootSQLite/不同拥有者 Schema target 已有实际证据；不同 Schema 是同一授权数据库中的不同 ResourceKey，不冒称第二数据库服务。当前 drain 结束重查 pending，有残留拒绝 flush ACK。 |
| metrics 故障与 SDK 屏障 | live child PID/birth/claim/register/adopt 的真实 gateway handler 已证明：flush receipt commit 后维护失败保留磁盘原 seq，cached receipt 重放再次维护，之后才允许 finish。它是进程内 handler 调用，不是 WebSocket 故障。Nemo subscriber 的真实事件/PG commit 确认丢失屏障另有局部合同，不能将其当网络层断线证明。 |
| Telegram 原基线 major | 692382 的私有 settlement marker 在 69d 保留，finished 在 coroutine.close/release_claim 后完成 marker，stop 等待 asyncio.wait。此前独立真实 PTB 三项、Root 原94项及其余Telegram合同119项已闭合；原 a875/58d/2a 红与中途被否定的 task-gather 候选继续留账，不被“基线已有”抹掉。 |
| Matrix 原 ratchet/吞错 major | 当前 Olm cache 每次仍做真实 generation 读、共享同一 Session 对象；保存失败/取消或事务回滚后 poison，has_session 前后检查；SDK内部吞错由 checkpoint 在 handler 边界抛回，sync 游标只在批次完成后提交，StorageError 走既有 retry supervisor。旧真实 SDK/PG 并发、群密钥、游标失败与新 SDK/store 重开合同仍有局部闭合证据；本轮新增 close major 独立列出，不能被这些历史通过覆盖。 |

## 单后端与发行证据边界

重读 `test_single_backend`、`single_backend_guard`、联合业务与独立发行支持代码：PG audit 拒绝所有 SQLite connect，包括别名/直接构造；SQLite 拒绝 sqlalchemy/psycopg/alembic。实际 SQLite Matrix SDK 上游需要 asyncpg 的异常类型，测试保留真实 SDK 类型但拒绝其 connect/create_pool，不能说该 SDK 场景没有导入任何 PG 相关类型。用户 SQLite 文档只在独立输入进程读取，不借此豁免 PG 自有业务库。

联合业务写/新进程读回涉及实际 counters、plugin KV/Discord recovery、RetainDB 与 Matrix 密码学结果；它们不是仅以 .db 文件不存在或 HTTP 回复作为成功。联合脚本的 owner 业务覆盖仍须与后补真实 managed worker 合同一起阅读，不能再次把 owner 脚本当完整 worker 消费者。

已读取四套69d独立 PM state 与准备日志，Linux/Windows 分别有 SQLite/PG 新 payload 和独立解释器。**环境已构建不等于最新发行行为验收通过**；PG 服务不可用后不能将 preparation 或纯 migration resources probe 代替真实 PG installed business 运行。Matrix close 如需新生产提交，还须重新冻结并更新对应载荷结果。

## 69d 当前批次账本（未作总体结算）

| 产物 | 已核对的真实结果 |
| --- | --- |
| `unified-task24-69d455-tracked-branch-checks.log` | 全分支artifact **14 checks ok**，587个 Python 文件 health **0 blocking / 0 advisory**；静态通过不证明异步关闭次序 |
| `unified-task24-69d455-db-native-windows.log` | **226 文件、579 passed / 0 failed / 3 skipped**，565.8s；这是 Native DB 选择范围，不是完整真实 PG 集成通过 |
| `unified-task24-69d455-full-pg-linux.log` | **126 文件、157 passed / 0 failed / 533 errors**，103文件非零、328.2s；首个连接中断后服务报告 recovery mode，整体失败，不能将 setup errors 算成业务断言失败或反推已通过 |
| `unified-task24-69d455-full-native.log` | 完整八目录仍运行，本报告不汇总未结算计数、不据中途绿色外推最终结果 |
| 四套69d PM payload state / preparation log | 只证明新环境准备完成；独立发行最终行为结果仍待结算 |

## 当前门禁

新 Matrix close major 已有独立调度红证据，PG 服务恢复及对应实际持久化补验未完成；全域 Native、最新发行结果与非 WSL 七项适用主机缺口亦未闭合。此前分域局部 major 关闭不外推全系统。当前候选不能批准；Task24 保持 **FAILED / CHANGES_REQUIRED**，后续将按 Root 提供的完整当前 ref 结果追加结算。

## Matrix close 调度修正后的局部复审

Root 在69d后仅将 `MatrixRuntime.close` 的 pending 循环改为 `await asyncio.wait(tuple(self.pending))`，另加解释该回调/取消边界的注释。事务 actor.done 等待、`_wait` shield、`_finished` 清理及异常观察均保留。wait 对已 done 的 future 仍允许已排队完成回调运行；取消 close 不会传播成取消 pending driver Task。逐行复审未发现这一最小修改的新问题，也没有通过丢弃 pending 或缩短实际同步工作来取绿。

新永久 `tests/hermes_db/contracts/test_matrix_close.py` 两项已读：第一项用实际 SDK close 协议与线程调度覆盖 done-before-release；第二项把 SDK caller 取消后进入真正 disconnect，再取消 disconnect，必须保持真实线程仍在运行、driver Task 在 pending 且未被取消，直到释放线程后再次 disconnect 才能完成。两者都明确没有配置/数据库/SQL，不以此冒充 PG 持久化合同。

红测账本校正已核对：`unified-task24-matrix-close-permanent-red.log` 初版 **1 passed / 1 failed**，其中第一项超时用了 AssertionError，确实被 adapter 的普通 Exception 边界捕获，不能算该项产品通过。Root 改为专用 `_CloseDeadline(BaseException)`，保留同样3秒硬预算；`unified-task24-matrix-close-permanent-red-corrected.log` 原生产代码下 **2 failed**，6.85s，分别是实际关闭热循环与取消 disconnect 导致 pending 过早清空。此第二项现在已有 Root 实际红证据，取代前节仅列静态待证风险的状态。

Reviewer 随后通过独立 `task24-runtime-candidate-state.json` 快照，复跑**完全未修改**的原 ignored probe，仍经 Native canonical runner/retries=0、无 PG：`review-matrix-close-candidate-fixed.log` **1 passed / 0 failed / exit 0**，5.4s。原 SHA256 `74C7B62640B161C69FE4FD1872546B8390DCDEF62FB90C1E20BD61CEAA65D050` 未变；绿观测 `.build/postgresql/review-matrix-close-scheduler-observed.json` 结果为 closed、database_used=False。不是重写反例来适配新实现。

当前工作区与快照 overlay 的关键 SHA256 已核对相同：

| 文件 | SHA256 |
| --- | --- |
| `hermes_db/matrix_runtime.py` | `d775f4ff5b2ebd29d333d9dd938b1babc3187dc68b46a3ee97406a73cf71f3bc` |
| `tests/hermes_db/contracts/test_matrix_close.py` | `daf6e435c35111e50060ee9c406b8f299b11ff6d7335d33b7d5ac463816432ae` |

已读取 Root `unified-task24-runtime-close-candidate.log`：该69d基础+8文件hash overlay 的七文件 **37 passed / 0 failed / 0 skipped**，40.3s。准确分解为 close 两项（0.9s）、`contracts/test_single_backend.py` 四项（其中含一项完整实际 SQLite SDK 新进程恢复）、五个 managed 测试夹具文件31项。不能把 single_backend 的四项全说成四项 SDK，也不能把五个夹具文件当作31条真实 PG managed 业务；它们未使用 PG。overlay其余文件属于明确的测试替身 owner identity 合同修正，不是为本 Matrix 生产修复开放 fallback。

**本 close 调度修正在无需 PG 的实际 SDK 生命周期范围，已有独立红→绿与永久双边界证据。** PG 服务仍未恢复，真实同步 psycopg driver/commit 的关闭补验未执行；本轮新增 Ruff/static 仍待 Root 结算，不能引用69d旧587文件通过为新 overlay全分支通过。完整强验收/Native宽回归/最终发行及非WSL主机缺口继续保留；不将此局部结论写成该 major 全域最终验收或总体批准，整体仍 **FAILED / CHANGES_REQUIRED**。

## 新增 PG 关闭合同的只读范围审核（当时尚未运行）

已读完新增 `tests/hermes_db/postgresql/test_matrix_close.py` 的 `cancel_close=False/True` 两参数、实际 `_unit/unit_of_work`、Core `put_next_batch`、PG fixture 和正常 adapter 关闭函数。**两参数均尚未运行**：服务仍不可用，Reviewer 没有执行 test/fixture/连接探测，不记 red 或 green。

主路径的真实 PG 覆盖设计合理：

- `new_store/open/put_next_batch('before-close')` 都使用真实 PostgresCryptoStore 与实际 Profile/代次资源；持有的操作直接调用真实 Core `put_next_batch`，`driver` 执行真实 `matrix_runtime._unit(reference, write, True, {})`，没有换成伪连接、内存值或假的 SQL 提交。
- `_unit` 的 context manager 真正退出后才返回线程结果；其中包括实际 PG write transaction 的 COMMIT/连接归还。观察 wrapper 仅在这个真实成功返回后 `committed.set()`，因此不会把“Core SQL函数已执行”混同“COMMIT完成”。
- SDK caller 在事务被 Event 暂停时取消；可选取消 close 分支要求 driver 仍未退出、pending 非空且包装 Task 未被取消。最终关闭仍走 `MatrixAdapter.disconnect → _StoreLifecycle.stop → PostgresCryptoStore.close`，相同完成/清理调度有独立5秒硬观察上限，没有改生产期限。
- 关闭完成后才要求 `checkedout()==0`，避免用并发业务中的全局瞬时 pool 值误判持连接；随后新 store 真读回 committed-during-close，另一真实 Profile/store 的同账号/设备读到 None，包含持久结果与隔离，不能仅靠 driver_finished 或 close 返回判定成功。PG fixture 的 owning random Schema 与全 SQLite拒绝 guard 保留。

这验证的是一个真实短 Core unit 在 caller/close 取消下仍完成并可重开读取的合同，不额外声称覆盖全部 SDK 显式多操作事务、COMMIT确认不明、数据库服务重启或新进程恢复。它也尚未实际证明这些预期成立。

### [minor，测试清理] 真实 unit 失败后 cleanup 可能等待未唤醒的 closing

位置：`tests/hermes_db/postgresql/test_matrix_close.py:91`（本次读取版本）。若 `_unit`/COMMIT 抛错，`committed` 不会 set，`disconnect_after_commit` 仍等待；即使5秒硬观察使主断言失败，finally 的 gather 仍包含该未完成 closing，可能再次无界等待。建议 finally 在 gather 前取消未 done 的 closing，保留真实原失败；不要为解决清理将 failed unit 也记成 committed。这是源码可验证的测试异常清理建议，已发 Root；不是新生产 major，也不是已执行 PG 红测。后续处置按实际增量另记。

Root 随即在 finally 增加 `if closing is not None and not closing.done(): closing.cancel()`。Reviewer 已只读核对：取消的是本测试真实持有的 closing task，未把失败 unit 伪记为 committed、未取消 tracked driver、未改变事务/重开/peer/期限断言，故该 minor 的源码处置可接受。PG两参数仍未执行；这两行后新增静态结果由 Root 后续结算。

另已读取新局部产物：`unified-task24-matrix-close-fixture-checks.log` 为 **14 checks ok、10文件health 0/0**，取代前节“新静态待结算”的当时状态；`unified-task24-matrix-and-relay-native-candidate.log` 为 **25文件288 passed / 0 failed**，64.9s；`unified-task24-worker-fixtures-relay-windows.log` 为 **7文件48 passed / 0 failed / 1 Linux平台skip**，70.7s。后两批是 Native Matrix适配/Relay/authority/managed测试边界；其中带 matrix 名称的 multiplex/native-producer/suppression 文件是跨平台组合矩阵，不能全称为 Matrix SDK 测试，更不能计作真实 PG 关闭两参数已运行。

局部代码/合同审核不改变总体状态：PG关闭实际补验、全域回归、最新发行和非WSL适用主机证据仍待，继续 **FAILED / CHANGES_REQUIRED**。

## 服务恢复后的实际 PG 关闭证据及本 major 局部状态

Root 已只读核对服务恢复后完成以下标准 runner 实证；Reviewer 逐项读取完整日志、最新源码及新 overlay state，**本轮没有重复连接 PG、运行测试或管理服务**。前节“PG合同尚未运行/实库补验未完成”是当时状态，现由本节取代。

最新测试保留真实 new_store/open/seed、同步 `_unit`/Core写入/COMMIT、caller 与 close 取消、正常 adapter 关闭链、fresh store持久读回、peer空和池归还断言。观察调度只作两点收紧：真实 COMMIT 等待使用10秒异步界限；只有成功收到该观察之后才启动原5秒 close硬alarm，避免 signal 落在空闲 event loop/等待数据库阶段。没有延长 close观察期限或在写失败时伪置 committed，finally仍取消本测试拥有的未完成 closing。

已核对新十文件overlay state：`/var/tmp/hermes-unified-matrix-runtime-13a6905cae/source`，基础69d不变；`hermes_db/matrix_runtime.py` 仍为前述 `d775f4ff...71f3bc`，新 PG test SHA256 为 `1aab841c1fa4416599ecf482414d2ea1d90569f8fc85d0614eea57253bacbc06`，均与当前文件一致。此前八/九文件快照不覆写，不能混计为同一输入。

| 日志 | 已核对的实际结果与意义 |
| --- | --- |
| `unified-task24-matrix-close-real-pg-baseline-red.log` | 同一最新PG测试对照旧69d runtime，**2 failed / 0 passed**，runner14.0s、pytest13.17s。False分支真实COMMIT后仍在旧gather触及5秒 `_CloseDeadline`；True分支取消disconnect后pending实际过早清空。不是连接/setup错误，也证明新alarm放置没有让旧问题逃过回归 |
| `unified-task24-matrix-close-real-pg-first.log` | 修正runtime、真实PG双参数 **2 passed / 0 failed / 0 skipped、退出0**，7.6s；成功必须包含新store读回 committed-during-close、peer None、checkedout=0，不能只靠HTTP/close返回判断 |
| `unified-task24-matrix-sdk-pg-after-close-fix.log` | 当前十个Matrix PG文件 **31 passed / 0 failed / 0 errors / 0 skipped、退出0**，72.5s，包含close两项，以及实际Olm/group/session、并发共享ratchet、SDK handler/游标、身份、故障、监督与新进程恢复等原合同。双参数前批是这31项的重叠子范围，不累计成33条独立合同 |

结合 Reviewer 原独立无PG有界红→绿、永久无PG两项校正红→绿、当前真实PG旧runtime双红/修正双绿及完整Matrix文件组，**本次 Matrix close major 的代码、实际SDK关闭调度及同步PG提交/关闭持久化边界已有充分局部整改证据，局部状态可关闭**。此前被怀疑的取消close丢driver跟踪也已由真实PG对照直接证实并随同修正。未发现该最小等待修改的新问题。

这不批准69d原生产代码，也不把未提交overlay当最终发行。Root仍需最后静态结算、保存明确恢复提交后按统一新ref重跑完整PG、完成Native宽回归/故障与新的独立发行载荷复验，非WSL七项适用主机证据仍缺；旧69d完整PG recovery-mode失败和未结束的Native批不抹除。Task24与总体审查继续 **FAILED / CHANGES_REQUIRED**。

# 统一数据库后端：审查汇总与最终门禁

## 审查范围

- 日期：2026-11-09；分支：`feat/postgresql-session-storage`。
- 实施基准：`a8753423841362c6c8d76e2dca094c95d690ba27`；规划提交：`d9984f73af`。
- 最后生产版本：`120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b`；最终 CLI 测试修正/当前宽回归冻结版本：`20a4789b35d4b38eec098c5a1203699200833474`。二者之后的 `bdb2bf505d`、`194647f52b`、`8a3c2f39d8` 只有证据文档，生产未变。
- 历史检查点：原独立审查 `3febe6fc31`、生产整改 `58d0003f83d1c99505e1173508ea7e2934d89411`、测试合同修正 `d402ff3a06b15c45a150eb2459191bfc5a4a7e22`；以下历史结果保留其原版本归属。
- 输入：[统一设计](../designs/unified-database-backends.md)、[实施账本](../plans/unified-database-backends-plan.md)、实际 diff、标准 runner 原始日志及下面的独立审查/复审。
- 本文件由实施 Agent 汇总，不冒称独立终审。分域审查者独立于生产实现；原报告及红测保留。完整最终验证尚未通过，独立全局终审仍待执行。

## 独立发现及整改证据

| 范围与原发现 | 当前实际修改及验证 | 独立记录 |
| --- | --- | --- |
| 基础/运维：确认后改指配置可误删另一 store（blocking）；显式 Cron 房间错选 Profile；Bot Chat 仍以 state.db 文件为条件；过时 Schema 合同 | 删除前冻结 root/target 配置和身份，打开真实 handle 再核对；新增 checked control verb 防止旧服务假成功。绑定目标完整 scope；session_store_exists 取代文件判断。永久实库拒绝 retarget、SQLite→PG 变化及 live 身份不匹配；独立 11 项通过。完整 Schema/health 合同已经更新，但总门禁须读最新完整结果 | [原审查](unified-database-foundation-operations-review.md)、[复审](unified-database-foundation-operations-followup-review.md) |
| Kanban/Rooms：RoomStoreRef 被当 Path；附件别名导致活文件被删除；已完成 file_job 阻断下一生命周期；拒绝认领缺原子回执 | typed location 与拥有者 scope 进入原生/桌面入口；规范文件身份参与锁和跨 Board 活引用判断，保留未决旧 token；已完成 action 可进入后续退休但未清 stage 仍受栅栏保护；失败/拒绝结果与业务事务保存精确回执 | [原审查](unified-database-collaboration-review.md)、[复审](unified-database-collaboration-followup-review.md) |
| 协作增量：phantom warning 阻断提交后 outbox；foreign Profile 本地列表泄漏 launch scope；实际 server capabilities 仍开 SQLite | Core 审计及同 run/payload 去重；全 handler 绑定目标完整 runtime scope；实际 capabilities 按统一选择获取并关闭短期 run store。真实 server、确认丢失后维护、下游 ready/hook 和零 SQLite 永久合同通过 | [第二轮原发现](unified-database-collaboration-review.md)、[复审](unified-database-collaboration-followup-review.md) |
| 插件/Matrix：真实 SDK 内部吞 PG 异常仍推进游标；锁前读取的独立 Olm 快照使并发消息无法解密 | handler checkpoint 保留被吞 StorageError，等待解密后派生 handler；每次仍查 PG/generation 并共享实际 SDK 可变 ratchet。保存失败/取消使旧 store 不可继续，显式事务同一 gate 顺序，实际 fatal/retry supervisor 重建 SDK/store。真实两端加解密、重开、取消与提交失败已有独立证据 | [原审查](unified-database-plugins-acceptance-review.md)、[SDK 复审](unified-database-matrix-followup-review.md)、[supervisor 复审](unified-database-matrix-supervisor-followup-review.md) |
| Cron 消费者增量：gateway wrapper 因 SQLite 文件不存在而跳过 PG 投递队列；坏 YAML 绕过 run_job 失败合同 | Native 无文件短路留在 Native 分支，真实 gateway→scheduler 排空 PG 队列；配置解析失败转为秘密安全的 StorageConfigurationError，执行准备返回失败 tuple。真实跨 store 同 ID/重开/投递不占连接 7 项与坏配置窄验通过 | [消费者复审](unified-database-cron-consumers-followup-review.md) |
| 实际 managed Worker：verification、RetainDB 与 metrics 被 owner-only guard 拒绝；config-only 指标可能读旧 SQLite | 从实际已采用身份获取 owner 数据集，具名短操作经原 `worker.persist` 在业务 Connection 内保存 receipt；保留 owner-only、原 journal/未知提交/finish 栅栏。RetainDB HTTP 在连接外，发前检查当前 lease；metrics 使用 owner 当前同意窗口、持久 root intent 及真实 SDK quiesce。当前全 PG 批包含普通/config-only 实际模型、写入、新 owner 恢复和 peer 隔离；不是仅 owner 函数测试 | [基础/worker复审](unified-database-foundation-operations-followup-review.md)、[RetainDB复审](unified-database-retaindb-worker-boundary-review.md)、[metrics复审](unified-database-worker-metrics-implementation-review.md) |
| Matrix 关闭增量：Python3.14 对全 done Task 的 gather 同步热循环，取消 close 会丢实际 driver 跟踪 | pending driver 改为 `asyncio.wait`，保留真实同步 PG unit/COMMIT；旧 runtime 对同一 PG 合同双红，新实现双绿，当前完整 PG 再次执行真实 SDK 取消/正常 adapter 关闭/fresh store 读回/peer 空/pool 归还。31 项 Matrix 是689的子集 | [最终SDK候选复审](unified-database-plugins-final-candidate-review.md) |
| Native Telegram 基线及测试前提：PTB stop 早于 claim 回调结算；Store double 缺身份协议、Relay ACK 被当成模型进入、CLI argv/account home 输入污染 | PTB 以真实 claim settlement Future 完成后排空，独立实际 SDK 三项与原119项通过；其余仅修正明确夹具协议/实际执行阶段及原生路径，生产保护和原业务期限不放宽。最终当前 Native 宽回归仍需结算 | [Native生命周期复审](unified-database-native-late-failures-review.md)、[基础复审](unified-database-foundation-operations-followup-review.md) |

这些记录证明已发现的生产缺陷及指定补查已整改，不等同于整个分支已无问题。新回归失败还没有完成归因，不能用分域绿测盖过它们。

## 测试证据及其边界

全部 Python 测试经 `scripts/run_tests.sh`、PM 管理解释器、retries=0。PG 实库只使用核对归属的随机 Schema；全 PG 业务进程的 audit 拒绝全部 SQLite connect、别名、URI、内存库和直接 Connection，包括吞掉错误或后台线程的尝试。独立四入口正控制保证 guard 不是空断言。完整业务还验证真实写入、双 store 同键隔离、退出后新解释器反序读回与实际 SDK 加解密，不能将“未出现 .db 文件”计作完成。明确 SQLite 的独立发行子进程、不同 Profile 各自选择后端的 mixed 合同另列，不混称整个进程零 SQLite。

### 当前已结算结果

原始日志均在忽略目录 `.build/postgresql/`，版本、完整命令和恢复位置以实施账本为准。下列已被对应独立 Reviewer 阅读；本汇总不冒称 Reviewer 重跑这些 Root 执行的批次。

| 当前检查 | 实际结果与范围 |
| --- | --- |
| 120bf8 全 PG、独立发行、普通 Kanban daemon | `unified-task24-120bf8c9d6c9-full-pg-linux-serial.log`：**127文件689 passed / 0 failed / 0 errors / 0 skipped，退出0，2474.4秒**。完整PG目录、distribution和显式普通daemon场景；跨文件-j1，文件内真实并发/故障、原期限、严格guard不改。不声称此前并行服务故障已定因 |
| 当前 Matrix 实际 SDK/PG | 上述689中的10文件31项，含实际Olm/group加解密、SDK吞错边界、游标、ratchet并发、关闭与新进程恢复；先前独立局部31与之重叠，不相加。MemoryStateStore只提供SDK房间元数据，CryptoStore/SyncStore均真实PG |
| 当前 managed 领域 | 真实普通/config-only verification与metrics、RetainDB sync_turn/HTTP/503及未结束HTTP后的持久恢复、Core receipt/未知提交/旧lease/真实WS通道、SDK barrier与维护handler，均按分域报告列明的实际范围包含于689。handler维护故障不冒称整个WS失联链，两个Schema不冒称两台数据库服务 |
| 120bf8 双宿主 DB Native | Linux `...-db-native-linux.log`：**228文件584 passed / 0 failed / 0 skipped，退出0，563.9秒**；Windows `...-db-native-windows.log`：**228文件579 passed / 0 failed / 5平台skipped，退出0，520.0秒**。marker排除的PG文件收集不算实库执行 |
| 120bf8 四套独立 PM 载荷 | Windows/Linux各有新source及SQLite/PG解释器，载荷外CWD/-I及实际来源归属保留。Linux发行6项包含于689；Windows `...-distribution-windows.log`：**4 passed / 0 failed / 2 Linux SDK skipped，退出0，31.7秒**。SQLite独立业务/实际SDK与PG显式升级/完整业务/新解释器恢复均按原范围执行 |
| 20a478 PG目录外 integration 补证 | mixed metrics **1 passed，4.5秒**；Profile删除文件integration **7 passed，24.4秒**，均退出0。后一批为6项冻结身份参数+1项PG source→SQLite room target，与已跑的该文件4项非integration合为11项分批覆盖。两份日志 `unified-task24-20a478-{mixed-profile-backends,profile-deletion-integration}.log`；不计入689的全PG零SQLite |
| 当前完整分支静态/生成/构建 | `unified-task24-20a478-full-branch-checks.log`：**14 checks ok，598 Python files health 0 blocking/0 advisory，退出0**；120bf8生成契约check、strict TypeScript及完整TUI实际build退出0。旧Electron noEmit/预检22项只保留其原源码未改的历史范围 |
| Native原失败文件覆盖 | 69d完整6412文件为**63024 passed / 140 failed / 726 skipped，退出1**；最终63个非零文件中，120的59文件replay与额外3文件精确覆盖62，唯一缺失private launch平台文件。replay为315 pass/4 fail/7 skip，额外3文件239 pass/1 macOS skip；不能说62文件全绿 |
| 最新三文件实际观察 | `worker-host-loaded-observed`：**13 passed / 1 failed，369.7秒，退出1**，controls原20秒未见approval；PG/Windows批结束后 `worker-host-timed-observed`：**14 passed / 0 failed / 0 skipped，112.6秒，退出0**。保留原20/30秒及所有业务断言，仅增加现场观察；后次绿不证明旧失败因果 |
| 当前20a478最终 Native | `unified-task24-20a478-full-native-observed.log`：**原八目录6412文件仍在运行，已见启动锁probe一项红**，-j4、原期限、retries0并保留worker/Host观察。该旧测试错误要求0.3秒预算内至少两次尝试，原函数受控复核耗时反例同断言1红，保留真实flock的双预算参数候选整文件8绿、独立复审接受、14静态/health1文件0通过；不将候选绿改成原批绿。FAL同ref独立PM环境另38 pass/0 fail/0 skip、退出0、1.9秒 |

### 历史检查点结果

以下按当时输入保留，不以旧批次替代上面的当前生产结果；表内当时的“仍运行”不表示这些旧进程现在仍存活。

| 检查 | 原始结果与范围 |
| --- | --- |
| 58d 全 PG 与独立发行 | `unified-task24-frozen-pg-and-distribution.log`：113 文件、654 passed / 4 failed / 0 skipped，退出 1。完整失败记录保留 |
| 上述两项 maintenance 失败 | 旧夹具错误地在首个前置 write 后丢 ACK。现只在真实 completed 主事务 COMMIT 后注入；原 done、子任务恢复、恰一次 hook、归档 workspace 断言不变。全文件 10 passed，独立窄验 2 passed；均退出 0 |
| 上述 Matrix sessions 失败 | 旧测试在重开后仍提交旧 store 的独立 ratchet；当前用重新加载的对象继续真实双向加解密及保存，再次重开验证时间和加解密。全文件 4 passed，独立 1 passed；均退出 0 |
| 上述跨执行 Profile Worker 超时 | 原 30 秒结果回执边界失败，独立全文件 2 passed。只补脱敏日志，未增 deadline/放松断言。尚未稳定复现原超时，不能宣布根因已解决 |
| d402 新冻结全 PG、发行、普通 daemon | `unified-task24-corrected-pg-and-daemon.log`：114 文件、336 passed / 0 failed / 325 errors，49 文件非零、退出 1、681.9 秒。原 maintenance/Matrix sessions/Worker 四项均实际通过，普通 daemon 通过；约58%时首见数据库 recovery mode，后续 setup/teardown 大量连接失败。不是完整绿色门禁 |
| 服务恢复后66a完整 PG/发行/daemon | `unified-task24-pg-after-service-recovery.log`：114 文件、659 passed / 0 failed / 0 errors / 0 skipped、退出0、1276.2秒。标准runner、retries0、原SQLite guard及真实业务/双store/重启/SDK合同均开启；生产仍58d，后续只有测试/文档变更。不外推为Native或全局门禁通过 |
| Windows 核心普通合同 | `unified-task24-windows-core-final.log`：212 文件、573 passed / 0 failed / 3 平台 skipped，退出 0。integration 被排除，不计为完整 PG 证据 |
| Windows 实际 daemon/worker | `unified-task24-windows-daemon-workers.log`：3 文件、4 passed / 0 skipped，退出 0。实际 gateway.run、同/跨执行 Profile worker、交互入口、工具写入、持久回执及重启，SQLite 全拒绝 |
| d402 SQLite 独立能力 | `unified-task24-sqlite-sdk-final.log`：4 passed / 0 skipped，退出 0。实际 SQLite SDK、全域双 Profile、新进程恢复；核心拒绝 PG 依赖，SDK 特例只允许上游实际依赖的异常类型但拒绝 PG connect/create_pool |
| 58d 四套新 PM 发行环境 | 新 Windows/Linux × SQLite/PG source-bundle 构建成功；`-I`、载荷外 CWD、installed source 归属及完整业务/显式升级证明：Windows 4 passed / 2 Linux SDK skipped，Linux 6 passed / 0 skipped。仅测试/文档后续变化没有改变该生产载荷 |
| 静态、契约与 Desktop | 58d 全分支 14 检查通过、547 个 Python 文件 health 0 blocking/0 advisory；d402 测试修正 14 检查通过、3 个 Python 文件 health 0。生成契约 check、strict TypeScript、Electron noEmit 退出 0；Desktop 备份预检 Vitest 22 passed |
| 58d Linux 八目录 Native 宽回归 | `unified-task24-frozen-native-areas.log` 仍运行，已有 compression、shutdown、command discovery、arrival-order、hot-profile及managed普通turn共7项失败；没有完整成功汇总 |
| 仅观测的 Native 诊断 | 忽略目录探针导入原两文件合同，在原 deadline 观察线程栈；31 passed，退出 0，未复现失败。导入式探针不替代原文件隔离回归，也没有捕获原失败瞬间的栈 |
| shutdown fixture 清理修正 | 仅测试改为 finally release/abort/join 所有实际启动线程；原2秒边界、owner与registry断言保留，原barrier失败输出栈后重抛。Windows原文件25 passed，冻结66a Linux原文件25 passed；独立确定性barrier失败/owner断言失败两项证明原异常保留且线程退出。尚未证明原始超时根因已解决 |

局部批次可能相互重叠，不将计数相加为所谓总通过数。每条完整命令、初轮失败、资源归属和恢复点以实施账本 Task24 为准。忽略目录原始日志不含 DSN/密码；重跑仅传私有配置路径。

## 未解决的门禁与无法验证项

1. 当前20a478八目录宽回归尚未终止；不能用69d旧成功文件、多个replay、静态或数据库合同替称一次当前完整Native绿色。原未清理线程、命令发现/异步pending前提等整改的有界复验以独立follow-up和账本为准，原完整红记录保留。
2. managed history/压缩、controls审批及Host注入的间歇失败仍缺完整因果。loaded批13/1和timed批14/0分别留账；通过用例慢fsync累计不能代替controls失败缺失的worker时间线。原PG跨执行Worker30秒超时及后续实库正例也分别保留。当前宽批已增加早期线程栈和失败timing，不修改期限或真实持久化来取绿。
3. 非WSL POSIX私有启动页七项仍缺适用主机。Windows与真实Ubuntu/WSL不能证明该政策；没有伪造OS/is_wsl，也没有删除这些原用例，仍等用户可用的现成执行入口。
4. 之前的数据库服务中断不因串行689通过而被解释为已修复。69d完整126文件157 pass/533 errors、120并行127文件240 pass/1 fail/451 errors均退出1；真实WAL中断/UnknownCommit及recovery症状、只核对归属的中断Schema清理继续留账。应用未管理服务，当前业务复验已有真实绿色，但不外推为所有跨文件负载组合通过。
5. 完整批次结束及失败处置后仍需独立全局终审，并按实际整改影响复验。本文件只是实施Agent对独立分域报告和原日志的汇总；各独立报告当前整体仍为CHANGES_REQUIRED，没有授权全系统完成或合并。

## 合并门禁

| 门禁 | 当前结果 | 理由 |
| --- | --- | --- |
| 原已证实 blocking 整改 | 指定范围复审通过 | 确认前冻结身份、实际 handle 核对、新 checked verb 的真实红绿证据 |
| 原已发现 major 整改 | 指定范围复审通过，不能外推全局 | 分域独立 follow-up；未知回归因果尚未关闭 |
| 全部验收标准满足 | 未通过 | 完整回归、适用主机、最终独立门禁仍不齐 |
| 最新完整 PG 绿色 | 通过 | 当前生产120bf8完整127文件689项、退出0；文件内并发/故障及全PG guard保持，目录外mixed/deletion另8项补证不混计 |
| 最新完整 Native 绿色 | 尚未结算 | 当前20a478八目录6412文件运行中；历史间歇未定因及七项平台缺口保留，FAL另38项通过 |
| 独立安装与显式迁移 | 指定范围通过 | 120bf8四套新PM环境、载荷外真实导入、有效历史前向/重复升级、完整域及双Profile新进程恢复；不沿用旧58d载荷冒称当前 |
| 静态/契约/适用类型检查 | 已记录范围通过 | 当前生产契约/strictTS/TUI、20a478全分支14项/598Python health0；本次报告文档新增检查另记 |
| 最终独立审查 APPROVED | 未完成 | 本文件为实施 Agent 汇总；现有各独立报告总体仍 CHANGES_REQUIRED |

## 当前结论

**`CHANGES_REQUIRED`，验证状态 `FAILED`，Task24 保持 in_progress，仍为 23/24。**

没有推送、发布、PR 或合并。正式 Profile 仍按实施账本记录保留 SQLite；测试采用隔离 Profile，没有操作既有业务表或管理 PG 服务。新数据集、不迁移旧 SQLite、不双写/回迁、文件职责和用户管理服务的设计边界保持不变。

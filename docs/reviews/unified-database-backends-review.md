# 统一数据库后端：审查汇总与最终门禁

## 审查范围

- 日期：2026-11-08；分支：`feat/postgresql-session-storage`。
- 实施基准：`a8753423841362c6c8d76e2dca094c95d690ba27`；规划提交：`d9984f73af`。
- 原独立审查版本：`3febe6fc31`；生产整改恢复版本：`58d0003f83d1c99505e1173508ea7e2934d89411`；仅测试合同修正版本：`d402ff3a06b15c45a150eb2459191bfc5a4a7e22`。
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

这些记录证明已发现的生产缺陷及指定补查已整改，不等同于整个分支已无问题。新回归失败还没有完成归因，不能用分域绿测盖过它们。

## 测试证据及其边界

全部 Python 测试经 `scripts/run_tests.sh`、PM 管理解释器、retries=0。PG 实库只使用核对归属的随机 Schema；自动 audit 拒绝全部 SQLite connect、别名、URI、内存库和直接 Connection，包括吞掉错误或后台线程的尝试。独立四入口正控制保证 guard 不是空断言。完整业务还验证真实写入、双 store 同键隔离、退出后新解释器反序读回与实际 SDK 加解密，不能将“未出现 .db 文件”计作完成。

| 检查 | 原始结果与范围 |
| --- | --- |
| 58d 全 PG 与独立发行 | `unified-task24-frozen-pg-and-distribution.log`：113 文件、654 passed / 4 failed / 0 skipped，退出 1。完整失败记录保留 |
| 上述两项 maintenance 失败 | 旧夹具错误地在首个前置 write 后丢 ACK。现只在真实 completed 主事务 COMMIT 后注入；原 done、子任务恢复、恰一次 hook、归档 workspace 断言不变。全文件 10 passed，独立窄验 2 passed；均退出 0 |
| 上述 Matrix sessions 失败 | 旧测试在重开后仍提交旧 store 的独立 ratchet；当前用重新加载的对象继续真实双向加解密及保存，再次重开验证时间和加解密。全文件 4 passed，独立 1 passed；均退出 0 |
| 上述跨执行 Profile Worker 超时 | 原 30 秒结果回执边界失败，独立全文件 2 passed。只补脱敏日志，未增 deadline/放松断言。尚未稳定复现原超时，不能宣布根因已解决 |
| d402 新冻结全 PG、发行、普通 daemon | `unified-task24-corrected-pg-and-daemon.log`：114 文件、336 passed / 0 failed / 325 errors，49 文件非零、退出 1、681.9 秒。原 maintenance/Matrix sessions/Worker 四项均实际通过，普通 daemon 通过；约58%时首见数据库 recovery mode，后续 setup/teardown 大量连接失败。不是完整绿色门禁 |
| Windows 核心普通合同 | `unified-task24-windows-core-final.log`：212 文件、573 passed / 0 failed / 3 平台 skipped，退出 0。integration 被排除，不计为完整 PG 证据 |
| Windows 实际 daemon/worker | `unified-task24-windows-daemon-workers.log`：3 文件、4 passed / 0 skipped，退出 0。实际 gateway.run、同/跨执行 Profile worker、交互入口、工具写入、持久回执及重启，SQLite 全拒绝 |
| d402 SQLite 独立能力 | `unified-task24-sqlite-sdk-final.log`：4 passed / 0 skipped，退出 0。实际 SQLite SDK、全域双 Profile、新进程恢复；核心拒绝 PG 依赖，SDK 特例只允许上游实际依赖的异常类型但拒绝 PG connect/create_pool |
| 58d 四套新 PM 发行环境 | 新 Windows/Linux × SQLite/PG source-bundle 构建成功；`-I`、载荷外 CWD、installed source 归属及完整业务/显式升级证明：Windows 4 passed / 2 Linux SDK skipped，Linux 6 passed / 0 skipped。仅测试/文档后续变化没有改变该生产载荷 |
| 静态、契约与 Desktop | 58d 全分支 14 检查通过、547 个 Python 文件 health 0 blocking/0 advisory；d402 测试修正 14 检查通过、3 个 Python 文件 health 0。生成契约 check、strict TypeScript、Electron noEmit 退出 0；Desktop 备份预检 Vitest 22 passed |
| 58d Linux 八目录 Native 宽回归 | `unified-task24-frozen-native-areas.log` 仍运行，已有 compression、shutdown 及 command discovery 共 4 项失败；没有完整成功汇总 |
| 仅观测的 Native 诊断 | 忽略目录探针导入原两文件合同，在原 deadline 观察线程栈；31 passed，退出 0，未复现失败。导入式探针不替代原文件隔离回归，也没有捕获原失败瞬间的栈 |
| shutdown fixture 清理修正 | 仅测试改为 finally release/abort/join 所有实际启动线程；原2秒边界、owner与registry断言保留，原barrier失败输出栈后重抛。Windows原文件25 passed，冻结66a Linux原文件25 passed；独立确定性barrier失败/owner断言失败两项证明原异常保留且线程退出。尚未证明原始超时根因已解决 |

局部批次可能相互重叠，不将计数相加为所谓总通过数。每条完整命令、初轮失败、资源归属和恢复点以实施账本 Task24 为准。忽略目录原始日志不含 DSN/密码；重跑仅传私有配置路径。

## 未解决的门禁与无法验证项

1. Linux Native compression deterministic fallback 在完整批次失败；同环境顺序 a875/58d 窄验各 6 passed，仅说明未稳定复现。原事件显示 fallback 在 summary dispatch 前被 deadline fence 取消，尚缺原失败瞬间的 worker 栈，不能推断为 backend 产品缺陷或既有波动。
2. shutdown barrier 2 秒失败后，未清理的 same-job/old-owner 线程污染下一测试 mock。顺序 a875/58d 窄验各 25 passed；原首个超时原因未明，原 fixture 无 finally release/join 的事实已由独立 Reviewer 记录。不能用后续绿测抹去完整批次失败。
3. 原 PG 跨执行 Profile Worker 结果回执超时尚缺稳定复现；新完整批次中两项实际通过，但整批因 recovery mode 非零，不能宣布根因解决。不得延长 deadline、关闭功能或绕开真实 owner/worker 协议取得绿色结果。
4. 非 WSL POSIX 私有启动页七项缺适用主机。当前 Windows 与真实 Ubuntu/WSL SDK 测试不能证明非 WSL 政策；没有伪造 OS/is_wsl 或跳过必需验收，仍等待用户可用的现有执行入口。
5. 完整批次结束及失败处置后，仍需独立全局终审，并按审查整改的实际影响复验。此汇总不是该独立终审。
6. d402 完整批次因测试数据库 recovery mode 非零结束，恢复模式原因尚未查明。用户处理服务后第一次仍not yet accepting connections，后续Windows/Linux只读探测均核对指定测试数据库及in_recovery=false。对两个日志候选先核对数据库、角色owner及唯一标记，只删除仍存在的一项，另一项已不存在；未操作其他Schema。66a完整114文件PG/发行/daemon已重新启动，日志unified-task24-pg-after-service-recovery.log，结果尚未返回；恢复连接不替代完整业务验收。
7. Native command discovery 比较时 daemon 缺少 legacy 已看到的 `/sdlc-review` bundled skill，原断言及完整批次失败保留，尚未确定与本次 backend 变更的因果；独立 A/B 核对中。

## 合并门禁

| 门禁 | 当前结果 | 理由 |
| --- | --- | --- |
| 原已证实 blocking 整改 | 指定范围复审通过 | 确认前冻结身份、实际 handle 核对、新 checked verb 的真实红绿证据 |
| 原已发现 major 整改 | 指定范围复审通过，不能外推全局 | 分域独立 follow-up；未知回归因果尚未关闭 |
| 全部验收标准满足 | 未通过 | 完整回归、适用主机、最终独立门禁仍不齐 |
| 最新完整 PG/Native 绿色 | 未通过 | PG新批次也非零且依赖当前recovery mode；Native仍运行且已有失败 |
| 独立安装与显式迁移 | 指定范围通过 | 四套新 PM 环境，0004 有效历史前向升级与重复升级、完整域、双 Profile 新进程恢复 |
| 静态/契约/适用类型检查 | 已记录范围通过 | 上述真实结果，不替代业务验收 |
| 最终独立审查 APPROVED | 未完成 | 本文件为实施 Agent 汇总；现有各独立报告总体仍 CHANGES_REQUIRED |

## 当前结论

**`CHANGES_REQUIRED`，验证状态 `FAILED`，Task24 保持 in_progress，仍为 23/24。**

没有推送、发布、PR 或合并。正式 Profile 仍按实施账本记录保留 SQLite；测试采用隔离 Profile，没有操作既有业务表或管理 PG 服务。新数据集、不迁移旧 SQLite、不双写/回迁、文件职责和用户管理服务的设计边界保持不变。

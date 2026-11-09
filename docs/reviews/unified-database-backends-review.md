# 统一数据库后端：当前验收汇总与门禁

## 当前结论

**验证状态：BLOCKED；独立审查总体：CHANGES_REQUIRED；Task 24 仍为 in_progress，完成 23/24。**

七项非 WSL 私有启动页缺少适用主机结果，是尚未闭合的验收 major，不能批准全系统交付或宣称Task24完成。下方旧独立总体门禁只适用于合并前冻结引用。用户随后发起的本地develop合并整改单列核对，不以旧批准/旧689项外推新源码。本文件是实施 Agent 的汇总，不是独立批准。

## 当前本地develop合并整改（2026-11-09）

后续运行更新：用户另行要求重启供验收，正式Schema已显式升级0031，新PID37296运行已验收源码0d69702244，
两个Profile各16域ready，Webapp控制状态serving/直连HTTP200并已打开；旧SQLite保持原哈希。
这是授权的运行升级与只读就绪检查，不是新的独立全系统批准；详细操作、首次配置冻结拒绝及恢复点见
[计划的用户验收重启段](../plans/unified-database-backends-plan.md#2026-11-09合并代码后的用户验收重启)。下方“正式Schema仍0028”是此前合并整改阶段的历史边界，不能当当前运行状态。

- 用户既有合并：ours `264dc20077`、incoming `781dc1e05fc7e781b714790d6ea2ab459835b3bb`；原19文本冲突已解决，自动合并文件及三方备份保留，以本地提交标题`Merge develop into feat/postgresql-session-storage`保存本次收尾，不是Task24完成提交。
- 当前运行源码冻结tree `bb811be4a8132bcdb52190ab730ae1ab329b8512`。Stored transcript/picker/Worker/归档/refusal、房间grant债务/home/实际HTTP/关闭键、Kanban新消费者等语义缺口已整改；新增0029–0031只作用于明确升级的PG候选，正式Schema仍0028，本轮不重启正式Profile。
- 新合同六文件36pass/0fail（246秒），包含实际collector/HTTP/supervisor、双进程恢复、真实COMMIT后丢ACK及旧PG空展示身份两方向分页。空身份曾稳定0pass/2fail，已最小补齐后转绿，不以更改seed掩盖缺口。
- v3四PM独立载荷：Windows4pass/2个Linux平台skip（45.7秒）、Linux Native4pass（87.4秒）、Linux PG2pass（43.4秒），实际0004升级/十领域/SDK新进程恢复和拒绝SQLite均保留；Probe只修正实际stdio重定向后的回执流，没有假分页或放宽业务断言。
- 最后`checks-staged-v3-receipt.log`：15检查通过、health1045文件0blocking/0advisory、exit0、327.6秒。PG全目录131文件`pg-suite-v3.log`已自然终态686pass/0fail/34skip、exit0、2024.6秒。34skip恰为11个Linux Matrix/单后端文件32项及发行2项，另有Linux实际SDK/独立载荷通过，不称Windows当地执行；旧637pass/5fail/29errors/34skip探索失败保留。
- 本轮限定独立报告：[基础/运维](unified-database-merge-foundation-review.md)、[协作/房间/Kanban](unified-database-merge-collaboration-review.md)、[插件/发行](unified-database-merge-plugins-review.md)。本轮blocking/major均已局部闭合，三域均有限接受本次本地合并整改；该结论不能解除整体七项主机缺口，或替代尚未重跑的当前全仓Native宽批及完整Desktop/TUI TypeScript构建。
- 非WSL交付包已刷新为bb811be4源码及SHA256，23932条跟踪内容逐项核对；actual applicable-host run仍未执行，原6c9包只能作为历史。

完整命令、原失败、回执诊断、秘密回显处置及恢复点见[实施计划](../plans/unified-database-backends-plan.md#当前合并整改恢复点)。

## 合并前冻结范围与来源（历史）

- 分支：`feat/postgresql-session-storage`；基础：`a8753423841362c6c8d76e2dca094c95d690ba27`；规划：`d9984f73af`。
- 最终代码提交：`6c9e28665b1766c295023018a03e390dd264c230`。
- 最新生产实现及四套 PM 发行载荷来源：`120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b`。之后只有测试和文档变化；相对该版本及原 Native 冻结 `20a4789b35` 的生产 diff 均为空。
- `.build/postgresql/task24-final-code-reference-6c9e286.json` 已绑定五个变化测试的提交字节/实际 SHA256、14 份日志摘要及日志 SHA256、生产等价关系和 23/24 计划状态。该清单不替代业务测试。
- 原始日志保留于忽略目录 `.build/postgresql/`；完整实际命令、失败过程和恢复位置见[实施计划](../plans/unified-database-backends-plan.md)及[调试记录](../debug/unified-database-final-regressions.md)。

## 合并前设计验收逐项映射（历史）

依据[统一设计的验收与证据](../designs/unified-database-backends.md#验收与证据)，不使用旧会话阶段 835 项作为新领域完成证据。

| 要求 | 当前直接证据与限制 |
| --- | --- |
| SQLite/PG 各自通过业务合同，SQLite 不依赖 PG extra/实例 | 双宿主完整 DB Native、独立 SQLite PM 载荷、实际 SDK 业务及新进程恢复；不是仅导入检查 |
| PG 新数据集完整启动、全域读写、关闭和重启恢复 | 当前生产完整 PG 127 文件 689 项通过，包含真实 ordinary daemon、独立发行和新解释器恢复；会话、Projects、证据、Cron、Kanban、房间、附件元数据、指标和维护插件均有实际消费者合同 |
| PG 业务进程拒绝所有 SQLite 连接 | audit 覆盖 connect、别名、URI、内存库、直接 Connection 及被吞掉/后台发起的尝试，另有正控制；同时检查真实业务、持久行、隔离及重启。独立 SQLite 发行子进程和跨 Profile mixed 合同明确另列，不把整个联合 runner 进程树说成零 SQLite |
| store/Board/插件/房间隔离及真实并发 | 同 ID peer 隔离、配额、claim、序号、CAS、回执与终态包含于实际 PG 合同；mixed-root 和 Profile 删除/跨后端房间另有 8 项补证 |
| 故障及 unknown 语义，无 SQLite/内存回落 | 真实断连、池预算、SQL 错误、确认丢失、重放、旧 lease 与 managed owner 通道合同；跨文件串行不改变文件内部真实并发/期限 |
| Schema、升级和独立发行 | 四套 Windows/Linux、SQLite/PG PM 载荷；新 Schema、重复/前向升级、安装后真实来源和数据恢复。数据库服务/扩展由用户管理，没有 SQLite 数据迁移/双写/回迁 |
| Matrix 完整 SDK 加密协议及 PG 持久化 | 实际 mautrix SDK 及加密对象、PG 读写/重开、ratchet 并发、游标、取消、COMMIT 和关闭；31 项是 689 的子集。MemoryStateStore 仅承担 SDK 房间元数据，CryptoStore/SyncStore 真实使用 PG |
| 标准 runner、PM、最终验证及独立审查 | Python 测试统一 scripts/run_tests.sh、retries=0；最终代码相对 a875 全分支 14 检查通过，603 Python health 0/0；三分域独立复审已更新，整体不批准 |
| 非 WSL 适用平台及波动历史 | **未满足：七项缺真实非 WSL POSIX 主机**。没有伪装 OS/is_wsl，没有删除用例或放宽原业务期限；历史失败/未知原因保留 |

配置、Markdown、工作区和附件内容仍为文件。2026-11-09用户另行明确授权两个正式Profile切换本机PG并重启；当前网关26656已运行、两Profile独立store_id、16领域ready，原SQLite保留，完整操作和恢复记录见[计划的本机试运行段](../plans/unified-database-backends-plan.md#2026-11-09用户授权两个正式profile本机pg试运行)。切换前实查代码已为9b292893eb，旧SQLite/a875记录是历史检查点。此次运行就绪不替代完整业务/适用平台验收。没有打印数据库秘密、提交真实.env、操作既有业务表、安装/启动/运维PG服务、推送、发布、创建PR或合并。

## 当前验证结果

以下范围有交集，不能相加成新的测试总数。PG 实库使用核对归属的随机 Schema。

| 批次 | 实际结果、退出状态与归属 |
| --- | --- |
| 完整 PG/发行/普通 Kanban daemon | `unified-task24-120bf8c9d6c9-full-pg-linux-serial.log`：127 文件 **689 passed/0 failed/0 skipped**，exit0，2474.4 秒；跨文件 -j1，文件内部并发/故障/期限不变 |
| Matrix 实际 SDK/PG | 10 文件 31 项包含于上述 689；原 runtime 同一关闭合同双红、修正双绿、全组再验均保留 |
| 双宿主 DB Native | Linux 228 文件 **584 passed/0 failed/0 skipped**，exit0；Windows 228 文件 **579 passed/0 failed/5 平台 skipped**，exit0；日志为 `unified-task24-120bf8c9d6c9-db-native-{linux,windows}.log` |
| 四套独立 PM 载荷 | Linux发行 4 项 + PG初始化发行 2 项包含于 689；Windows发行 **4 passed/0 failed/2 Linux SDK skipped**，exit0、31.7 秒。不能把 Windows 跳过项说成通过 |
| PG 目录外补证 | `unified-task24-20a478-mixed-profile-backends.log`：1 passed/4.5 秒；`...-profile-deletion-integration.log`：7 passed/24.4 秒，均 exit0。后者为 6 项删除身份参数和 1 项 PG→SQLite 房间，不并入零 SQLite 689 |
| 原八目录完整 Native | `unified-task24-20a478-full-native-observed.log`：6412 文件 **63150 passed/15 failed/726 skipped**，exit1、7722.3 秒。原批次保持失败，不改名为通过 |
| 当前剩余文件联合复验 | `unified-task24-profile-prepared-native-joint.log`：6 文件 **688 passed/0 failed/0 skipped**，exit0、485.9 秒、-j4；原 server637 + pause43 + groups4 + notification1 + profile相位2 + cleanup1 |
| FAL 独立 PM SDK 环境 | `unified-task24-20a478-fal-native.log`：38 passed/0 failed/0 skipped，exit0；该文件不在原 6412 中，单独结算 |
| 最终全分支静态 | `unified-task24-6c9e286-final-branch-checks.log`：`PM Python -X utf8 scripts/check --commit 6c9e28665b1766c295023018a03e390dd264c230 --base a875342384`，**14 checks ok，603 Python files health 0 blocking/0 advisory，exit0** |
| 生成契约/类型/构建 | 当前生产 120bf8 的生成契约、strict TypeScript、实际 TUI build exit0；此前 Electron noEmit/预检 22 项仅按原源码未改范围保留，不称本轮重跑 |

原计划 Task 24 从规划提交起即允许原生目录按依赖/平台分批。独立来源核对解析原 6412 个唯一逐文件行并逐一比较 Git blob：仅五个 selected 测试变化，全部来自原八个非零文件，生产 diff 为空。该事实与当前完整文件补验共同支持有界的分批结算；它不能把原批次变成一次完整绿色，也不证明所有负载组合或历史异常原因。

## 原八个非零文件逐项处置

| 原文件/失败数 | 当前完整文件与处置 | 剩余限制 |
| --- | --- | --- |
| boot reserve probe / 1 | 双预算参数及其余真实锁/跨进程合同 8 项通过；只修正“首轮已耗尽预算仍须至少两次尝试”的错误前提 | 不是物理墙钟性能保证 |
| hygiene adoption / 1 | 原 3 项通过，另真实库相位和故障清理 2 项通过；保留实际 goal/store、0.3/5/15 秒及业务断言 | 新失败 profile 定位 post-turn 冷准备，不冒称原 full 12 秒现场也有同一精细时序 |
| pause record / 1 | 当前原完整 43 项及 -j4 联合通过；真实 False/True marker、incarnation、债务分支正确 | 原宽红原因未明，保留可靠性风险，不称代码已修复或与分支无关 |
| private launch / 7 | 同文件其余 5 项原批通过；七项仍缺非 WSL POSIX 实机 | **必需验收阻塞，不能用 Windows/WSL 取代** |
| async delegation / 1 | 原完整 35 passed/1 macOS skipped；同 elapsed-dispatch probe 1 项通过。固定年龄上限改成实际采样时刻投影，真实 worker/ledger 保留 | 不把逻辑 clock offset 当实测延迟；macOS skip 明列 |
| groups route / 1 | 当前原完整 4 项及联合通过；真实 lease、两附件读取、submit/callback、settle/gen1 和原字节断言通过 | 原 10 秒超时原因未明；本次没有失败前快照，不补造旧因果 |
| notification poller / 1 | 原 Linux/Windows 合同及真实 acquire 相位通过；当前联合原 1 项通过，两个 join3 保留，真实库在 fixture 计时前准备 | 只覆盖已准备 session 重建/停止，不保证任意首次初始化中强制 3 秒中断 |
| TUI server / 2 | 原完整 637 项当前联合通过；两 profile 真 store ref 覆盖 build/join，worker 仍真实 open 同 handle；故障清理/双宿主均补证 | 原 15 秒时点为首次 schema DDL；底层慢因、旧额外 None 归属不补造。后发现的 nested5 本次约0.524秒 True、trace触及20000 cap，历史原因继续留账 |

原七个非平台非零文件均有当前完整文件结果，最后四个为实际 -j4 联合。[Foundation](unified-database-foundation-operations-followup-review.md)、[协作](unified-database-collaboration-followup-review.md)、[插件/验收](unified-database-plugins-final-candidate-review.md)已分别核对来源和各自实际范围，未发现必须盲目再跑全 6412 或另加特定并发组合的具体非平台 blocking/major 依据。新出现的失败仍必须按真实现场重新分级，不能用这次绿色覆盖将来红测。

## 原重大问题及独立复审

| 范围 | 原问题与当前闭合证据 | 独立记录 |
| --- | --- | --- |
| 身份/运维 | 删除确认后配置改指可误删 peer store；现冻结 root/target、核对实际 handle/身份及 checked verb；目标 Cron/Bot Chat/健康按统一所选 store | [原审查](unified-database-foundation-operations-review.md)、[复审](unified-database-foundation-operations-followup-review.md) |
| Kanban/Rooms/附件 | typed location、owner scope、活引用/规范文件身份、file_job生命周期、事务内拒绝回执与 outbox 审计均有永久真实 PG 合同 | [原审查](unified-database-collaboration-review.md)、[复审](unified-database-collaboration-followup-review.md) |
| Matrix | 实际 SDK 吞存储错误/游标、共享 ratchet、事务取消及 COMMIT/close driver 边界已有实际 PG 红绿和完整 SDK 回归 | [SDK](unified-database-matrix-followup-review.md)、[supervisor](unified-database-matrix-supervisor-followup-review.md)、[最终候选](unified-database-plugins-final-candidate-review.md) |
| managed Worker | verification、RetainDB、metrics经真实 owner receipt/同意窗口持久化，保留 lease、unknown、quiesce；包含实际普通/config-only模型入口和新 owner/peer | [RetainDB](unified-database-retaindb-worker-boundary-review.md)、[metrics](unified-database-worker-metrics-implementation-review.md)、[基础](unified-database-foundation-operations-followup-review.md) |
| Cron/Native SDK | 无 SQLite 文件短路，目标 scope/投递队列真实工作；Telegram drain/claim 结算保留，原生命周期回归与 SDK 合同复审 | [Cron](unified-database-cron-consumers-followup-review.md)、[Native](unified-database-native-late-failures-review.md) |

## 未验证项、风险及恢复

1. 七项非 WSL 私有启动页必须在适用主机执行。已准备本地 `.build/postgresql/private-launch-host-6c9e286/`：仅包含冻结提交的源码 archive、PM隔离运行脚本、README与校验和。脚本 `bash -n` 已通过；**没有在适用主机完成执行**，不计为验收。
2. 当前代码引用、五测试 hash、14 日志 hash 及相对 a875 全分支检查已冻结；[独立总体复核](unified-database-foundation-operations-followup-review.md#最终冻结-6c9e286-的独立总体门禁结算)已经逐项确认来源、九项映射及原八非零处置，结论 BLOCKED/CHANGES_REQUIRED。追加总体结论后的最后文档14检查通过、无Python measured变化、exit0（final-gate-docs-checks）；随后仅补结果/恢复文字并diff-check，以本地标题docs(storage): preserve final blocked acceptance gate保存。
3. 历史 managed/Host、pause/groups/nested等待与数据库服务恢复实例的完整原因未明。PG 串行689通过不证明原 WAL中断/recovery已被应用修复；没有管理服务。历史原始红和诊断自身失败保留于账本。
4. 后续如有生产/共享依赖变更，须重新匹配验证范围；当前测试/文档变更不重跑不受影响的PG/发行。若原合同再次失败，以新现场处理。

当前需要继续完成七项实机与最终门禁；**不批准合并，不创建 Task 24 完成提交，不将目标标为完成。**

验收包另经只读完整性检查：24,395个归档条目、Git pax冻结提交及三文件hash匹配，没有本地.env/.git/.build；未在适用主机执行。首个校验器错误假定tar根目录name保留末尾斜线，实际合法目录头不带斜线；修正精确根目录判断后同一未改变的packet通过，原失败日志保留，不计作业务红绿。

另直接核对git log --reverse d9984f73af..3febe6fc31及rev-list计数：恰23个按Task1–23领域顺序对应的本地提交。Task24及后续整改/证据提交不冒称第24项完成。当前独立必需工作已结算，下一动作取决于实际适用主机结果。

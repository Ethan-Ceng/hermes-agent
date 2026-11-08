# 统一数据库最终验证：未决回归调试记录

日期：2026-11-08。执行账本：[Task24](../plans/unified-database-backends-plan.md)。审查汇总：[当前门禁](../reviews/unified-database-backends-review.md)。本文件记录证据链，不宣布这些回归已解决。

## 版本与观察条件

- 基准为 `a875342384`，生产整改冻结版本为 `58d0003f83`；`d402ff3a06` 和 `66a987c9ea` 只修改测试合同、诊断及文档。已用 `git diff 58d0003f83 --name-only` 核对未继续修改生产代码。
- Linux 为真实 Ubuntu/WSL。冻结 checkout 在现有隔离 Linux 本机测试根，具体根与提交见忽略目录的 `task24-*-state.json`；原先跨版本 `/mnt/d` 宽跑的 partial 日志不作为冻结验收。
- 全部 Python 合同由 PM 解释器经 `scripts/run_tests.sh` 执行，retries=0。没有延长业务 deadline、伪造 OS 或关闭功能。诊断探针与原文件隔离回归分别登记，不把导入式探针当作完整回归。

## Compression deterministic fallback

预期：超过窗口的请求首个 summary stall 后，通过真实 lease/fence 流程提交 deterministic fallback。

实际：冻结宽回归 `test_over_window_request_commits_the_deterministic_fallback_on_the_first_stall` 失败。原日志显示取消 worker 在2秒 grace 后仍未退出，fallback 已启动但在 summary dispatch 前被 fence 取消；两个 attempt 的 telemetry 分别约4048/3988毫秒、均 aborted，没有提交新摘要。

证据：`unified-task24-frozen-native-areas.log`；相同 PM 环境依次在 a875、58d 窄跑原文件各6 passed（`unified-task24-compression-{baseline,head}.log`），没有稳定复现。额外原 deadline 观测探针导入 compression/shutdown 合同共31 passed，也没有取得原失败瞬间的 worker 栈。

当前判断：没有足够证据确认新增 backend 的因果，也没有足够证据认定是既有波动。测试使用真实临时 SQLite SessionDB；pre-summary attempt telemetry 本身不打开 metrics store，不支持直接归因 PG 连接。没有修改 Agent 压缩、缓存前缀、lease/fence 或原2秒窗口。

下一观测：原失败瞬间仍存活 worker 的阶段/线程栈与 lease/fence 状态，不能用调大 timeout 替代。

## Cron shutdown barrier 与跨测试线程

预期：两个同 job、不同 owner 的实际 in-flight registry 同时可见，shutdown 分别标记；失败后测试不能留线程写入后续测试的 seam。

实际：冻结 `test_shutdown_sees_all_concurrent_direct_fire_owners` 在原 `Barrier.wait(timeout=2)` 抛 BrokenBarrierError；随后 replacement 测试的 mock 多出 `same-job/old-owner` call，正是上一测试输入。原 fixture 只清全局集合，原线程 release/join 位于成功路径，故第一失败可以污染第二项。第一 barrier 超时原因尚未知。

独立顺序 a875/58d 原文件各25 passed（`review-foundation-shutdown-{baseline,head}-ab.log`），未复现第一超时。只根据已确认的清理缺口修测试：finally 设置原 Event、abort 原 Barrier、join 所有实际启动线程，再统一断言无存活线程；原2秒 rendezvous/join、owner和registry断言均保留。原 BrokenBarrierError 输出无局部值的 faulthandler 栈后重抛。

`66a987c9ea` 的原文件 Windows25 passed、Linux25 passed（`unified-task24-shutdown-cleanup-{windows,linux}.log`）。独立确定性探针令原2秒 barrier 失败，以及在正常 rendezvous 后令原 owner 断言失败；两项均保留原异常、两个线程退出、清理完成（`review-foundation-shutdown-cleanup-default-stack.log`）。探针只证明失败清理，不替代 Cron 持久业务。

当前判断：清理缺口已修并独立复核；原2秒超时未解释。若 worker 在其他不可中断 I/O，bounded join 不能强制结束它，存活断言仍必须失败。不能把清理修正外推为首个 timeout 已解决。

## Command discovery 技能差异和 RPC 超时

预期：同一 Profile/技能快照下普通 daemon 与 legacy 的 catalog、slash completion 相同，拒绝 foreign Profile。

冻结失败的方向：daemon **多出** `/sdlc-review`，原 `delta` 是 `(daemon_value, legacy_value)`，值为 `({'usage': 0, 'origin': 'bundled'}, None)`。早期实施汇总误记为 daemon 缺少，已对照实际测试修正，未按错误方向改生产代码。

顺序 a875/58d 原文件窄 A/B：baseline2 passed；head1 failed/1 passed，但 head 是 legacy WebSocket 的第一个 `commands.catalog` 在原20秒期限超时，没有重现上述技能差异（`review-foundation-command-discovery-{baseline,head}-ab.log`）。这两个失败信号必须分开保留。

独立观测层只对本测真实创建并持有的两个 Popen、且启动序列精确为当前解释器 `-m gateway.run` 或 `-m hermes_cli.main serve` 的子进程注册 faulthandler SIGUSR1。仅原20秒超时发生后才对仍活的这些 handle 发信号，读取其测试日志中的栈帧并重抛原异常；不扫描其他PID，不重新发请求，不增加RPC期限。有观测的单项为1 passed，没有触发信号或取得失败栈（`review-foundation-command-discovery-owned-stack.log`）。

已排除/收窄的假设：

- bundled `sync_skills` 在构造 runner/发布READY之前同步返回，没有支持“READY后仍未同步”的直接证据。
- sdlc-review 的 Kanban relevance gate 读取 ContextVar/配置，没有直接数据库读取。
- CLI inventory 临时扫描的共享 catalog 窗口确有既有问题，但不能据此推断 slash 命令泄漏，见下一节反证。

当前判断：原技能差异和独立 RPC 超时仍未定因，未改变技能过滤、提示缓存或超时。

## 既有底层 catalog minor：记录并延后独立修复

独立真实 Event 窗口探针在 a875、58d 均失败于普通 `find_all_skills` 看见 inventory 的 Kanban-only 条目：普通 detector=false、inventory selection=true；窗口前不含、窗口内含、恢复后不含。原技能为临时 Profile 的实际 SKILL.md，没有构造假 cache 记录或修改普通 scope 配置。

重要反证：同窗口真实 `scan_skill_commands` 及恢复后 `get_skill_commands` 始终排除该命令，`_scan_skill_md` 会再次检查 relevance。两个版本输出均为 ordinary catalog during=true、ordinary slash during=false、after restore=false、worker settled=true（`review-foundation-skill-cache-{baseline,head}-red.log`）。此项不能解释原 daemon/legacy slash delta。

历史意图经 `git log -p -S` 核对：`c31291a765` 要求 CLI inventory 临时纳入 Kanban 计数并恢复其他视图；`80f37e36ed` 要求 Kanban relevance 随执行上下文判断。独立 Reviewer 分为 minor：既有底层列表隔离问题，不是已证实的未授权工具执行或本次新增 backend 回归。

处置：保留独立报告与两版本红测，延后单独修复。原因为它在 a875 已存在、命令层反证有效且不能解释当前失败；不以这个假设扩大统一数据库后端生产整改。此决定不删除或关闭原 command discovery 失败。

## 其他冻结 Native 失败

- `test_native_admission_arrival_order.py::test_stop_fences_inputs_still_capturing_or_waiting[paused]`：原3秒等待 both kept 超时，teardown出现读尚在途时关闭 SessionDB 的 warning。不能把该后果当作首个失败根因，尚未改入口/Stop语义或deadline。
- `test_multiplex_hot_serve_live.py::test_invalid_hot_profile_config_is_parked_and_unserved`：访问 `result['parked']` 抛 KeyError，冻结当次reply未知。独立门闩让a875/58d实际handler均在原5秒后返回pending，释放后实际park/unserve仍完成，而旧测试同位置KeyError。当前仅测试改为识别明确pending并在已有20秒eventual窗口等待精确parked集合及实际withdraw，立即完成仍校验原parked；每场景只发一次rescan，原状态文件断言保留。真实正向门闩1passed，新helper确实读取尚未完成状态后自行轮询终态。整7文件Root/mnt/d窄验6passed/1failed，失败为另一场景startup90秒仍starting，发生在新helper调用之前；不能据此说整文件已绿，拟新native冻结checkout复验，不改生产deadline。
- `test_session_mutation_compress_managed.py[False]`：原30秒等待HISTORY_9普通turn terminal超时，尚未到手动compress操作。不能按文件名先归为压缩算法缺陷，独立只读观测准备中。

完整 Native 批次仍运行。最终失败计数和完整 traceback须读其最终输出，不以此阶段列表替代完整汇总。

## PG Worker 与数据库服务恢复

58d完整PG批次中跨执行Profile Worker的30秒结果回执边界曾失败。同文件独立两项通过，d402完整批次该两项也通过；没有稳定复现或提高deadline。实际工具写入、owner回执、clean exit及重启断言均保留，测试所有者/worker日志只做秘密安全的补充输出。

d402完整批次随后在约58%出现服务端 recovery mode：最终114文件336 passed、325 errors、49文件非零，不能计通过。用户处理服务后，首次仍not yet accepting connections，之后Windows/Linux只读查询都确认指定独立数据库身份及pg_is_in_recovery=false。只对本批次日志中两个Schema候选先验证数据库、当前角色owner和唯一测试标记，再删除仍存在的一项，另一项已不存在；未操作其他Schema或管理服务。

当前66a完整PG/发行/普通daemon重跑日志为 `unified-task24-pg-after-service-recovery.log`，已完整659 passed/0 failed/0 errors/0 skipped、退出0、1276.2秒。原Worker两项也在此实际通过。保留原超时及旧批次服务中断证据；完整PG绿色不替代尚未通过的Native宽回归与未决调试。

## 配置 owner 与安全启动

当前归档验证直接解析 YAML 触发配置架构 guard，已改为复用配置 owner 的纯原始文档解析入口，不用 live defaults/overlay 替代归档证明。Windows 原配置及新归档合同48项、实际PG备份10项通过，独立同合同48项及ZIP/quick拒绝覆盖11项通过；最终新发行载荷与完整回归尚待。

safe-mode 的新增 owner 栈显示，忽略用户配置的会话在可选 Project 标签查询中重读坏 YAML，发生在 worker 之前。普通标签查询原本也在 owner_scope 外，真实PG双Profile取得了前景Profile项目。当前最小修复将普通查询移到owner_scope内，bypass不查询该附加标签。新PG永久合同3红→3绿；原完整CLI/worker合同须在新冻结checkout复验。新测只证明正常创建后坏配置的snapshot及持久handle/peer隔离，不扩大为坏storage配置下新PG创建或跨进程重启成功。

remote fresh Profile 的 staging 查询也被真实plane原合同拒绝。a875/58d同条件均失败且git历史确认会话阶段已存在；当前沿用既有supports_file_tooling边界，只对本地复制配置分配新身份，远端fresh的最终配置归其backend。Windows fresh已过，但完整文件99pass/6个其他dotenv/home失败仍保留，不能标为完整通过。

## 托管进程的领域消费者

预期：真实PG owner采用的compute worker只通过已认证owner通道操作持久数据集，agent的ignore-user-config默认快照不改变该身份。实际独立PG daemon/模型红测发现verification、RetainDB及metrics仍直接acquire，被owner-only拒绝；config-only指标还尝试遗留SQLite，被全连接audit拒绝。模型完成不证明这些消费者工作。原因是先前领域测试只覆盖owner，缺少实际托管入口；不移除guard、不禁用功能。

首步verification以`c0558e9c13`补owner identity/read及现有worker.persist领域效果，真实证据/回执同Connection；worker不接受时间/retention伪造。Core真实rollback/COMMIT丢ACK及Windows/Linux普通/ignore实际编辑→PG→新owner恢复/peer已通过，冻结Linux三文件8pass。RetainDB复用此通道，严格固定拥有者/plugin，保留跨会话destination分区；原生SQL在传入receipt连接完成，owner重算指纹和PG租约。独立边界报告为`docs/reviews/unified-database-retaindb-worker-boundary-review.md`。

RetainDB初版桥接另有确定根因：WorkerRPC原样重抛实际WebSocket断线，而writer只捕获StorageError/WorkerPersistenceError/OSError，读断线不产生sticky写journal，导致线程死亡但worker可finish。独立真实WS1011→PG probe先1fail，再增加WebSocketException边界处理后原probe不变1pass；enqueue保留原异常并附request_id，不改变未知提交的重放规则。永久transport最初两项确实2fail；修复后read观测曾在HTTP调用与ack开始间隙提前读取，改为等待真实PG acknowledged及空journal。此为测试竞态，不清空或绕过journal。

永久关闭测试第一次错误检查daemon日志中的worker警告，改为实际worker退出时HTTP仍未release、PG行仍claimed的业务断言；原join10与HTTP hold预算保持。Windows真实provider.sync_turn/HTTP/预算1并发owner读、503/pending及未结束HTTP/claimed两种关闭、新owner新会话恢复/peer两项通过；transport read/已提交ack/已提交enqueue丢确认三项通过，flush/finish在未确认journal时拒绝，显式同receipt恢复后才允许结束。Windows两文件6pass和生命周期两文件4pass分别见`unified-task24-retain-request-id-green.log`与`unified-task24-retain-lifecycle-green.log`，SQLite/plugins六文件44pass。最新Linux全批和静态按计划记录实际结算，不预记通过；metrics实际托管消费者尚未整改，不据此关闭全系统验收。

## 调试结论

两个宿主前提现已按原意图收窄：command guards使用独立临时审批目标并新增真实运行时目录优先硬拒；Termux fallback核对其成功notice，保留独立WSL警告，不再推断整台宿主音频可用。原2a冻结24pass/2fail→Windows/Linux各27pass；未修改生产guard/voice代码或fake机器事实。静态14检查和独立fixture复核通过，仍需其余原失败文件及实际编译器合同复验。

Telegram原cancel-before-entry在2a当前冻结也稳定红。SDK22.8在stop开始即running=False，导致停止中派生的error callback没有SDK task-set所有权；Hermes原claim pin还在。初版Task集合gather候选在Python3.14全done优化下热循环，独立3秒及Root180.1秒栈均明确指向stop，而非让测试多等。现用真实清理完成后的settlement Future，原94项与平台3文件119项及独立正常/派生/取消stop三项通过；原断言/期限未改。旧候选进程已按出生时间、完整命令、解释器、cwd及专有测试临时根核对后终止，不再遗留热循环。

metrics最新整改已补闭合owner领域短写、KV root intent及提交后维护，业务/SDK/PG回执与Windows原生指标688项的局部证据见实施计划。owner engagement Path(None)永久红测已关闭且SQLite路径调用兼容；真实SDK barrier测试前两次的缓存/线程Profile夹具问题保留原日志，并据HX002让入口按实际owner绑定路径scope后通过。必要journal仍阻止提前finish，没以模型成功替代指标持久。当前Linux指标全域、最后静态及冻结发行尚未完成，全局依然FAILED。

保持 **UNRESOLVED / FAILED**。配置归属、verification、RetainDB及metrics等分域已有局部整改/独立证据，不能替代宽回归红测的逐项闭合和新生产载荷完整复验。下一步继续这些实际失败的证据驱动整改，再执行最终独立审查。非WSL POSIX七项适用主机证据仍另行缺失，不能由以上WSL调试替代。

## 真实编译器下的更新收尾夹具

冻结297原失败清单实跑48文件761pass/10fail，另FAL38pass。实际编译器已在隔离checkout按锁安装，更新收尾原文件14pass/2fail；只读观测插件保留两个child输出，原2项复现仍2fail。两者相同根因是微型workspace没有ui-tui/scripts/gateway_bootstrap.py与clipboard_image.py；真实esbuild先成功，随后生产builder复制必需运行时辅助脚本时ENOENT，故无TUI产品。源码历史c1f19acb7f已明确该发布输入，不能修改生产builder跳过它。

候选只在_npm_graph补齐这两个真实输入，并检查成功产品包含它们；原编译产物执行、web bundle内容、selected PM Python、更新锁/回执和故意TypeScript失败的owed-build断言均保留。红测日志unified-task24-update-compiler-observed.log，脱敏child输出update-finish-test_*.json；候选与冻结297源码分开，证据state为task24-update-candidate-state.json并记录修改文件SHA256。完整原文件已实际16pass/0fail/0skip、退出0/40.4秒（unified-task24-update-compiler-candidate.log）；独立复核和静态仍待，不据此关闭全局验收。

## managed压缩的间歇性终态超时

同一297冻结失败清单48文件中，False分支在HISTORY_8的30秒admission终态期限失败，True通过；没有以单项历史绿掩盖它。新增仅在未跟踪pytest插件的daemon yield异常边界保存本次拥有者日志及session_admissions/worker_executions，先于测试自有进程finally清理，脱敏且只写忽略目录。没有更改生产行为、测试期限或接受条件。

原冻结单文件实跑2pass/0fail/102.5秒（compress-observed）；原失败清单同组6文件-j4实跑52pass/0fail/107.8秒（compress-load-observed），均退出0。仍未再次触发原超时，故没有失败时新增日志，不能宣称根因已确认或生产修复。后续完整门禁保留该原红与故障观测；若重现继续沿最早偏差追踪。

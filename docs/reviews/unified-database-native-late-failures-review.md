# Native 后段失败独立追加审查

范围：冻结 `58d0003f83d1c99505e1173508ea7e2934d89411` 宽回归后段的 remote config、Photon、achievements、Telegram admission、command guards、Termux audio、fal SDK；并核对 Root 的 remote fresh-profile 局部修复。只修改独立报告及 ignored 观测脚本；未修改生产/仓库测试、安装依赖、改变工具环境或延长 deadline。

本轮原宽回归已输出最终摘要：`.build/postgresql/unified-task24-frozen-native-areas.log:8117`，6412 files、62870 passed、44 failed、220 errors、726 skipped，49 failed files，其中 1 个 import/collection failure。**完整整改、复验和验收批次仍未结算**；这个摘要不等于整改完成。

## 同条件基线证据

通过原 `run_matrix_linux.py --native` → `scripts/run_tests.sh`，同一真实 Linux Python 3.14.9 / 依赖环境、原 runner 隔离、`-j 1`、retries 0、相同 `-k`，各执行一次冻结 58d 和已有 `a8753423841362c6c8d76e2dca094c95d690ba27` Native snapshot。没有修改测试或 mock 宿主平台。

日志：`.build/postgresql/review-native-late-failures-58d.log` 与 `review-native-late-failures-base.log`。双方均 **5 files / 0 passed / 7 failed / exit 1**（分别 4.9s、5.0s）。七项依次为 remote fresh-profile、achievements 三项、Telegram error-before-entry cancel、command deny callback、Termux inconclusive probe。对应错误一致。因此这些问题在本次 a875→58d 变更之前已有同条件红证据，不能标为这一 diff 新引入；也不能因此消去失败。

`git diff a875..58d` 对 Telegram admission、对应 Telegram 测试、command guards、voice mode、对应两项 tools 测试及 achievements plugin 没有生产/测试差异。历史 `f874e6be49` 已引入 `profile_storage.fork_storage_identity` 和 achievements 的统一 store 获取。这里的“基线已有”只指已实际测试的 a875，不代表已验证上游 main 或其他 SDK/宿主。

## [major，基线已有] Remote fresh-profile 读取非法 staging 配置

原宽回归日志 6403 起：`test_fresh_profile_creation_succeeds_against_a_healthy_plane`，104 passed / 1 failed。原合同在 `tests/plugins/config_backends/test_remote_backend.py:1205`，明确 staging home 不经 remote backend 读取，创建完成后没有隐藏 staging 残留、没有点名前缀 profile 请求。

精确调用链：`hermes_cli/profiles.py:1408` 的 `finish_profile_layout(staging, ...)` → `profiles_initialization.py:66` 的 `fork_storage_identity(profile_dir)` → 修复前 `profile_storage.py:13` 的 `load_user_config_effective(staging/config.yaml, fail_closed=True)` → config cache version → `plugins/config_backends/remote/backend.py:194` 拒绝 `.fresh.staging-PID` 非正式 Profile home。调用发生在 `profiles.py:1409` publish rename 之前。真实 StubPlane 健康；这是调用方违反已有 backend 边界，不是网络或 SDK 缺失。A/B 均复现。

Root 局部修复加入 `if not supports_file_tooling(): return`。审查此 diff 后，边界与已有 `profiles_config.py:13` 一致；`profiles.py:1114` 的 clone source 入口本来就通过 `require_file_tooling('Profile clone')` 拒绝非文件 backend。fresh 的 source 为 None，未复制源配置中的 PG store_id 或 `.file-store-id`，因此此 guard 跳过的是复制身份拆分，不是运行时 storage backend 选择。

独立实际 Linux 窄验：`.build/postgresql/review-remote-fresh-guard-working-tree.log`，原 fresh 合同 **1 passed / 104 deselected / exit 0 / retries 0**，2.6s。该次使用当前工作区源码，不冒充旧冻结 58d；修复文件 SHA256 前后均 `EAC2607D9E10B9E764BF3D16416B11D72B91815866A3D0413862FEC465F1B854`。

PG 身份边界核对：最终正式 home 仍由 `db_setup.resolve_db_configuration` 读取 backend 的有效配置，`db_setup.py:68` 的 `DatabaseScope(..., store_id)` / `require_store_id()`、profile secret 和 Schema 校验未绕过。此 fresh 用例没有 PG 配置，不能证明远端管理面给两个新 Profile 分配不同 store_id；本地 PG clone 的独立 store_id / file owner 合同及全 105 项仍需 Root 最新完整证据。未发现这三行 guard 自身引入新的运行时后端豁免。

## Achievements：已证实替身合同缺属性，未证明实对象故障

原宽回归日志 6630 起：3 passed / 3 failed。直接失败 `test_scan_sessions_default_scans_all_history_not_first_200` 在 plugin `scan_sessions:574` → `hermes_db.health.storage_identity:22`，`_FakeSessionDB` 没有 `db_path`。`tests/plugins/test_achievements_plugin.py:68` 的替身确实只定义 session_count、scan_delay 等统计字段。

另外两项（首次后台扫描一直 pending；750 session 的 partial publication 为 0）来自同一替身：`_run_scan_and_update_cache:805` 捕获扫描异常，记录 failed / last_error，未建立最终缓存，故后续仍返回 pending。不能将它们当成已证实的性能 timeout 或真实扫描丢数据。实际 SQLite `SessionDB.__init__` 在 `hermes_state.py:585` 始终设置 `db_path`；实际 PG scope 的 identity 走另一分支。

独立单次 ignored 观测：`.build/postgresql/test_review_achievements_fixture_contract.py`，日志 `review-achievements-fixture-contract.log`，**4 passed / exit 0 / retries 0**，4.2s。只在内存包装原 `_FakeSessionDB.__init__`，补 `db_path = tmp_path / 'state.db'`，随后直接调用原三个失败用例，保留全部原断言：500 条全历史、50 条后台完成、750 条至少两次递增 partial。第四项直接调用原 `test_scan_sessions_never_opens_a_writable_session_db`，真实临时 SQLite store、原只读打开监视及原结果断言均通过。

最小建议：修正仓库测试替身以满足已存在的实际 SessionDB 身份合同，或使用真实临时 SessionDB；保留原扫描/后台断言。不要给生产 identity 增加缺属性回落来迁就替身。本观测不替代 PG `test_achievements_native_storage.py` 的真实 store 隔离、不可用无 SQLite 回落和 initiating-profile 线程合同；本轮未新执行这些 PG 测试。

## [major，基线已有] Telegram 取消前入口后的 claim 未按原合同释放

原宽回归日志 6726 起：93 passed / 1 failed。原 `test_only_pre_handoff_failure_reopens_admission[error_before_entry-cancel]` 在 `_check_error_cancel_before_entry:420`，`await app.stop()` 后仍保留 `_inflight_update_ids['111:10']`，claim 为 `accepted=False, failed=True, owners=1`，dispatch task 仍 pending。A/B 单项同样失败。

真实 Linux SDK 已安装为 **python-telegram-bot 22.8**；只读 source 证据在 `.build/postgresql/review-native-telegram-sdk-source.log`。SDK `Application.__create_task` 注册自己的完成 callback，`stop` 等待其 task set；Hermes `plugins/platforms/telegram/update_admission.py:241` 在同一 task seam 增加 claim owner，并另挂 `finished` callback，`_release_claim:259` 以 owners 归零释放 admission。测试故意在 callback 进入之前取消真实 SDK 创建的 task，并要求原回调 coroutine 关闭、停止后可重放一次。

这不是 SDK 缺失，也不能仅据 traceback 宣称某个 callback 已永久丢失或只是应多等一拍。已证实的缺口是 SDK 停止返回时原 admission 生命周期合同未满足；确切调度/所有权根因仍需 Root 观测。建议围绕真实 PTB cancel-before-entry 与 stop 边界修复/验证，保留原重放和 coroutine close 断言；不要延长等待或把 pending claim 当成功。

## 宿主条件：command guards 与 Termux

- `tests/tools/test_command_guards.py:83`：原宽回归 17 passed / 1 failed，A/B 同红。测试把整个系统临时根传入递归删除命令，**只作分类，并未执行删除**。真实解释器和 runtime 同在该根内（精确路径见忽略目录task24-native-checkout-state.json），`tools/approval.py:1167` 正确触发 runtime self-delete hard block，故审批 callback 为 0 次。不是缺工具，也没有理由降低生产自删保护。最小测试方向是让审批流程测试使用不包含真实解释器/运行树的临时目标，并单独保留真实运行树 hard-block 合同。
- `tests/tools/test_termux_api_detection.py:192`：原宽回归 7 passed / 1 failed，A/B 同红。测试注入 Termux binary/probe 结果，却在真实 WSL 上调用全局 `detect_audio_environment`；`tools/voice_mode.py:331` 正确识别 WSL，缺可用音频桥时添加 warning，最后 `available = not warnings`。Termux API fallback 已产生成功 notice，失败的是用例进一步假设整个宿主可用。不得将其归为未安装 Android app，也不应伪造 `is_wsl=False` 来取绿；应让此用例只验证原 fallback 合同，或在真实目标宿主验证全局可用性。

## 已证实工具 / SDK 前提缺失

| 文件 | 原结果与直接原因 | 本轮证据边界 |
| --- | --- | --- |
| `tests/plugins/platforms/photon/test_spectrum_patch.py` | 2 failed，两个真实 Node 子进程启动均 `FileNotFoundError: 'node'`，源码第 97 / 245 行 | 已知缺前提，未重复红跑；需 Root 新 Linux PATH 完整复验。 |
| `tests/plugins/platforms/photon/test_url_send_path.py` | 8 setup errors，`verdicts:72` 启动 Node 不存在 | 同上；尚未运行 send builder 断言。 |
| `tests/plugins/platforms/photon/test_zombie_stream_watchdog.py` | 2 passed / 4 failed，`_run_staleness_harness:54` 启动 Node 不存在 | 同上；不能把 4 项判为 watchdog 业务回归。 |
| `tests/tools/test_fal_sdk.py` | 真正的 collection error，模块第 5 行 `import fal_client` 失败，0 tests ran | `pyproject.toml:254` 的独立 `fal` extra 锁定 `fal-client==0.14.1`；原 full env 未选择此 extra。未安装或红跑。需 Root 用 PM 创建含该 extra 的新测试环境再运行，不能算通过。 |
| `tests/tools/test_plugin_guard.py` | 131 passed / 6 setup errors，`tests/pm/_fixtures.py:147` 缺 PATH uv | Root 已完成的新工具批次包含此文件，日志现为 137 passed。 |

Root 执行的 `.build/postgresql/unified-task24-native-tools-recheck.log` 已逐文件核对：29 files / **424 passed / 0 failed**，251.9s。它覆盖前份工具审计的 6 个指定文件及扩展 uv / Node 清单，实际工具 state 记录 Linux uv 0.13.5、Node 26.12.1、npm 12.0.2。这是 Root 的完整结果，不冒充 Reviewer 执行；其中不含上述 Photon 三文件或 fal SDK，所以不能外推到它们。

## 结论

本轮发现的 remote/achievements/Telegram/两个 tools 问题均已有明确 a875 同条件证据；其中 remote 有当前局部修复的独立 Linux fresh 绿证据，achievements 有替身缺属性的完整观测证据。其余失败、完整 remote/PG 身份回归、Photon/fal 新前提复验和 Task 24 总体仍未结算。保留原失败和限定范围的复验记录，整体 **FAILED / CHANGES_REQUIRED**，不作总体 APPROVED。

## Task24 Telegram 基线 major：2a268 后整改独立复审

本节是上述 Telegram 基线问题的后续，不回写旧 A/B 为新引入问题。输入为已提交 `2a2684390016a1bfadc4c759bf2151945425f077` 和唯一生产变更 `plugins/platforms/telegram/update_admission.py`；原 `tests/plugins/test_telegram_update_admission.py` 的 94 项内容及业务期限未修改。Reviewer 未改生产/仓库测试、未安装或提交，诊断仅写 ignored 文件并沿既有 PM Linux/canonical runner，retries=0。

### 原基线与 SDK 协议

Root 冻结当前 2a 的 `.build/postgresql/unified-task24-telegram-preentry-current-red.log` 已读取：原 `error_before_entry-cancel` **1 failed / 93 deselected**，仍在 app.stop 后 `_inflight_update_ids` owners=1 处失败。这与本报告最初 a875/58d 同条件红一致，不是统一数据库 diff 新引入。

再次核对实际安装 **python-telegram-bot 22.8** 的 `Application.stop`、`__create_task`、`__create_task_callback` 与 `process_error`：stop 先将 running=False，再等待已有 SDK task set 的一个快照；`__create_task` 只在 running=True 时登记 SDK set。一个已有 handler 在停止过程中报错，`process_error(block=False)` 仍会通过相同私有 seam 派生真实 error task，但它已不在 SDK 自动等待集合中。Hermes 的 claim owner 在该 seam 已增加，必须等自己的完成回调执行 coroutine.close / release 后才算 admission 已结算。不能仅以 SDK task.done 或 SDK stop 返回证明这一步发生。

自等待核对：PTB 明确为 handler/job/error callback 内请求停止提供 `stop_running`；在 SDK 已跟踪的 task 内直接 await stop，本来就可能在 SDK 自身 gather 中等待自己。本次未发现当前生产 disconnect 路径新增合法自等待情形，不能把该 SDK 既有不当调用方式归为本 diff 新 major。当前变更也未通过略过现有 claim 来掩盖它。

### [major，初次候选已否定] 等待已完成 Task 导致 stop 热循环

Root 初次未提交候选给 claim 增加 `_claim_tasks`，stop 在 super.stop 后 `while set: await asyncio.gather(*set)`。它**没有通过**本次验收：Python 3.14 在全部子 task 已 done 时 gather 可同步完成，await 不让出事件循环，已排队的 Hermes finished 回调无法执行 discard/release，while 持续热循环。

精确证据：Reviewer `.build/postgresql/test_review_telegram_stop_boundary.py`，SHA256 `DE656500C3AACA2101EBFAD62EC91BA13EBF7B4DE8B82985E048DE5722685D25`。直接调用原失败用例、原 fixture 与全部原断言，仅包装观察并加 **3 秒 SIGALRM 硬上限**；没有延长业务期限或靠循环重试。日志 `review-telegram-stop-boundary.log` 为 **1 failed / exit 1**，runner 8.2s。截断栈为候选 `update_admission.py:268 → asyncio.gather → Python3.14 tasks.py:920`。脱敏 `review-telegram-stop-boundary-observed.json` 同时记录 running=False、集合唯一 task 为 `Application:111:process_error:non_blocking` 且 done=True/cancelled=True，claim owners 仍为 1。

Root 的 `unified-task24-telegram-preentry-target-green.log` 虽名含 green，实际 30 秒 faulthandler 栈同样停在该 stop 行，之后触及 180 秒观察 runner 上限；不能记绿。首个旧 full 候选日志也未提供完成 summary，本节不把它当通过。Reviewer 的窄探针已自行限时退出，未按 argv 扫描/停止其他进程或 WSL。

最小整改依据是等待“claim 完成回调真正结算”的独立 marker，而非再等待已经 done 的 SDK task。不以 sleep(0)、延长期限或删除原释放/重放断言处理。

### 当前 settlement 修正与独立正例

Root 最新 diff 为每个 claim owner 创建私有 settlement Future；真实 finished callback 先关闭被取消但未进入的原 coroutine、调用原 `_release_claim`，随后从集合移除 marker 并完成 Future。stop 在原 super.stop 后用 `asyncio.wait(tuple(markers))` 等待；若晚到 error task 又派生后续任务则下一轮继续等待。一个 event-loop callback 内的移除/完成之间没有 await；取消 stop 不会通过 wait 取消 marker 或其业务 task。原 claim failed/accepted/completed 判定、bot 归属及 receipt 逻辑不改。逐行复审未发现该增量的新增问题。

Reviewer 新独立文件 `.build/postgresql/test_review_telegram_settlement.py`，SHA256 `BA9CB7184C5063E797C82B3FB14221FF6986A4D44FB9F1EDB31E7F0EEFECD4B8`；`review-telegram-settlement.log` **3 passed / 0 failed / exit 0**，4.9s，脱敏观测 `review-telegram-settlement-observed.json`：

- 原 error_before_entry 原函数、全部原重放/coroutine-close 断言在同样 3 秒观察上限内通过，最终 settlement 集合为空。
- 真实 PTB handler 在 running=False 后失败，真实非阻塞 error callback 再创建一个等待 Event 的 descendant；SDK 自身 task set 已空时 stop 仍不返回，直至该 late descendant 的真实回调释放 claim。
- 在同一 late descendant 边界取消 stop，marker 与 descendant 均未被取消，claim 继续 pin；释放业务 Event 后真实完成回调归零，native handoff 的 seen receipt 保留。未设置假的 worker/SDK 状态、未以假 stop 或手工释放 claim 代替。

Root 最新完整日志已读：`unified-task24-telegram-preentry-settlement-green.log` 原单项 **1 passed / 0 failed**，2.4s；`unified-task24-telegram-settlement-full.log` 为 **4 文件、119 passed / 0 failed**，15.0s，包含原 admission 全部 **94 项**及 Telegram 插件侧另三文件 25 项。这是 Root 的标准 runner 证据，与本 Reviewer 的三项独立运行分别记账。

该 Telegram 基线 major 及中途 Task-gather 热循环候选，在当前 settlement 局部范围已获得整改与独立正例。它不消去旧失败记录，也不代表整个 Native 宽回归、最终统一冻结/发行复验或非 WSL 适用平台证据已完成；Task24 总体仍 **FAILED / CHANGES_REQUIRED**。

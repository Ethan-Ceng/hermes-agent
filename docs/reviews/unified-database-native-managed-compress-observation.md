# Native managed turn 超时独立观测

2026-11-08。独立只读诊断；未改生产代码、仓库测试、deadline 或提交。总体仍为 `FAILED / CHANGES_REQUIRED`。

## 原失败与实际调用链

`unified-task24-frozen-native-areas.log:2854` 起记录 `test_session_mutation_compress_managed.py` 的 False 参数在 `HISTORY_9 terminal` 原30秒等待超时，另一参数通过。共享 `run_compress_case` 必须先完成16个普通 HISTORY turn，随后才调用 `session.mutate(operation='compress')`。因此原失败尚未进入被测手动压缩操作，不能按文件名归为压缩执行失败。

已读实际 fixture 及调用链：`prompt.submit` → admission 持久化及 `SessionAuthority._drain` → `execute_finite_admission`/`execute_admission` → `admit_managed`/`execute_managed` → 新建真实 `agent.managed_worker` → hello/身份核验与 reservation → loopback 模型真实 turn → result/finish 协议及 worker 持久终态 → owner settlement 将 admission 置 terminal。原30秒条件把这些阶段共同纳入等待；没有现场状态便无法确定是哪一阶段延迟。

## 唯一一次带观测复验

使用既有 `task24-native-checkout-state.json` 的真实 Linux PM 环境与冻结源码 `58d0003f83d1c99505e1173508ea7e2934d89411`，未修改 native snapshot 的 tracked 文件。观测层位于忽略目录：

- `.build/postgresql/review_native_managed_compress_observation.py`
- 输出 `.build/postgresql/review_native_managed_compress_observation.json`
- 标准 runner 日志 `.build/postgresql/review-native-managed-compress-observed.log`

观测层直接调用原 False 用例，只在内存包装共享 fixture 的 daemon 上下文以持有本测 Popen，以及原 `async_wait_until`。predicate、timeout、interval 和原所有后续断言均原样传递。仅当原 HISTORY terminal 的30秒等待实际抛超时断言，才在原 daemon finally 前以只读 SQLite 连接采集 admission/worker/receipt/会话状态，并读取该 owned home 的有界、再次脱敏的 worker/daemon 日志。不扫描进程，不操作别的 Profile/Popen；清理由原 fixture 处理自己的 daemon。

通过 `run_matrix_linux.py --native --state task24-native-checkout-state.json` 调用 canonical `scripts/run_tests.sh`，`-j 1 -s`、retries=0。文件上限300秒与 canonical 默认300秒相同；每次业务等待仍为原30秒。

结果：退出0，**1 passed、0 failed，106.3秒**。原完整 False 用例实际执行完毕，包括16个 HISTORY、压缩后的普通 turn、配置冻结、历史保留、admission owner/幂等、managed worker 终态/outbox 排空及真实 daemon 重启后的 mutation 重试断言。

| 观测项 | 实际值 |
| --- | --- |
| 原 terminal 等待次数 | 17次，全部 timeout=30且通过 |
| 原故障位置 HISTORY_9 | 4.1002秒，通过 |
| 本次最长 HISTORY_15 | 24.9360秒，通过 |
| 真实 daemon 生命周期 | 2次，由原 fixture 持有、清理 |
| 原用例内部耗时 | 99.6544秒 |
| 超时现场采样 | 0次 |

绿路径按授权不额外读取 admission/worker 日志，故没有伪造“故障时刻状态”的证据。本次 HISTORY_15 接近原30秒，仅说明该普通 turn 的组合耗时有波动；没有证据把它具体归因于 CPU、模型、SQLite 锁、worker 启动或 owner 结算。

## 结论

原 HISTORY_9 超时本次**未复现**，根因仍未确定。保留原宽回归失败及此次单次绿证据，不宣称已经修复，也不扩大 deadline、禁用 managed worker 或放宽压缩/重启断言。该结果不能外推 Task24 总体完成。

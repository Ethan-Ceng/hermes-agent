# Native paused admission 独立观测

## 范围与结论

2026-11-08，按 systematic-debugging 仅增加观测层，诊断冻结 `58d0003f83d1c99505e1173508ea7e2934d89411` Native 宽回归中的 `tests/gateway/test_native_admission_arrival_order.py::test_stop_fences_inputs_still_capturing_or_waiting[paused]`。

**一次窄观测未复现：1 passed / 0 failed，退出 0。** 原宽回归失败继续保留；本次结果不足以判定根因，不称为已修复、既有问题或资源波动。按要求没有盲目重复运行，也没有运行额外 baseline 来争取通过。

## 原始失败

`unified-task24-frozen-native-areas.log:2404` 起记录该文件 9 passed / 1 failed。paused 用例在原 3.0 秒 deadline 等待 `both kept` 超时；teardown 同时记录 SessionDB 读仍在进行时连接关闭的 warning。该 warning 出现在 teardown，不能单凭时间相邻断言它导致此前的 admission 超时。

预期合同：x0 被真实 SQLite 标为 unknown 后，队列属于 paused FIFO；媒体 x1 尚在捕获、文本 x2 在同 route 等待时，Stop 保留这些 followers。释放 capture 后，两个真实 admission 应保持 queued，顺序为 x1-video、x2-text。

## 观测方式

仅在拥有的忽略目录新增 `.build/postgresql/review_native_arrival_observation.py`，复制到冻结 Linux Native checkout 的 `.build/review-collaboration/test_arrival_observation.py`。未修改仓库测试或生产文件。使用原 `_held_owner` 创建真实 SessionAuthority、WhatsApp 来源、SQLite SessionDB、捕获 Event 与实际 admit Tasks，并直接调用原 paused 测试协程。

包装层保留：

- 原 `entered.wait(5)`、capture release 等待与实际 media capture；
- 原 2.0 秒负窗口和 `both kept` 3.0 秒 deadline；
- 原入队、unknown 数据写入、真实 Stop 和全部业务断言；
- 原 finally，并且最后只 join 由本次原 helper 创建的 Task handles，不触碰其他测试/服务任务。

原 `async_wait_until` 原样执行，仅在 `both kept` 失败时尝试从仍开放的真实 DB 读取本测三个 request_id 的精简状态，以及实际 Task stacks/异常、route 状态；随即原样重抛。观测不替代入队、scope 或持久化实现，也不伪造平台。

## 命令与结果

运行目录来自现有 `task24-native-checkout-state.json` 的 source，Linux PM 解释器为既有 `task24-full-test-env/bin/python`；HERMES_HOME/RUNTIME 使用该隔离 Native state，retries=0。所有测试经强制 runner：

```text
bash scripts/run_tests.sh .build/review-collaboration/test_arrival_observation.py -j 1 -- -s --tb=short
```

日志：`.build/postgresql/unified-review-native-arrival-observation.log`。实际 **1 passed / 0 failed，退出 0，3.5 秒**。本次原用例的两条 queued 顺序断言通过；没有输出原超时或 read-in-flight teardown warning。

## 证据限制

首轮包装层只把 JSON 观测结果 print 到 pytest stdout。runner 对成功文件不回显且不持久保存该输出，因此日志仅保留成功汇总，本轮无法再检视 `entered.wait` 的实际布尔值、精确时间戳或 Task 快照。不得把这些缺失字段描述为直接观察到的事实。总文件运行 3.5 秒短于原 entered.wait 的 5 秒 timeout，可支持“未走满该 timeout”的推断，但不代替原始观测值。

已在拥有的 Windows `.build` 观测脚本补上旁置 JSON 持久化，供后续明确需要时使用；**没有再次执行**。首轮复制到冻结 Linux checkout 的脚本仍对应当时的观测版本，日志历史不被覆盖。

目前能确认：本次原 paused 合同在同冻结实现、实际 Linux/SQLite 和原时间边界内成立。不能确认：宽回归失败时究竟是 capture 未进入、admit Task 异常、route 被错误 fence、提交尚未完成还是其他原因。没有宽回归当时仍开放的 DB/Task 快照，根因仍未知。

## 门禁

维持原宽回归失败与总体门禁；不得用这一项窄通过宣布 Native 全绿或总体验收通过。Root 决定后续根因调查与修改，本 Reviewer 未改实现、未改仓库测试、未提交。

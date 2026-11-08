# Cron 实际投递入口与配置拒绝增量复审

## 范围与依据

- 日期：2026-11-08；独立 Reviewer。
- 对象：HEAD `3febe6fc313faf34693ce9cb2075a3a894ea82d3` 之上的未提交工作区增量：`cron/scheduler.py`、新增 `cron/scheduler_delivery_queue.py`、`hermes_cli/db_setup.py`、`gateway/session_cron.py`，以及 `tests/hermes_db/postgresql/test_cron_delivery_store.py` 的消费者合同。
- 承接 `unified-database-foundation-operations-review.md`、`unified-database-foundation-operations-followup-review.md`；两份原报告均未改写。
- 本次只编辑此新增报告；未修改生产代码或仓库测试。独立 probe 位于 `.build/postgresql/review_foundation/test_cron_config_followup.py`。

## 两项问题与整改判断

### PG 实际 gateway drain 被旧文件 guard 跳过

原问题位置：`cron/scheduler.py:1356`。`gateway/run.py` 的 `_drain_restart_safe_cron_deliveries` 最终调用该生产 wrapper，而 wrapper 原先仅因 `cron/deliveries.db` 不存在返回 0。PG 没有这个文件，导致持久队列无法经普通 gateway 排空。此前 watch 测试直接调用 `queue.drain`，没有覆盖此路径。

已读取真实红测 `.build/postgresql/unified-task24-cron-gateway-red.log`：测试经 gateway 跨 Profile scope 和实际 scheduler wrapper，预期发送 `persisted`，实际发送列表为空，1 failed。

当前整改：scheduler facade 转发到主题 sibling；新 sibling 仅在 backend 为 SQLite 且文件不存在时快返，PG 真实调用领域队列 drain。发送回调在调用时读取 facade 的 `_deliver_result`、`_mark_incident_alerted`，保留生产消费者和现有补丁缝；失败投递、所有目标 suppressed 时不登记 alerted 的条件与原实现一致，没有以禁用发送通过。

扩展后的实际入口合同从另一个 ambient Profile 调用 gateway drain，两个 store 使用相同 execution_id；要求只有拥有者内容被发送、peer 仍 pending、拥有者 delivered，重开后再次 drain 不重复发送；发送回调检查连接池 checkedout 为 0，并断言仍无本地 deliveries.db。PG 目录原有 SQLite 全拒绝审计保留。

判断：该 major 在当前指定增量中已修正。主 Agent 最新 `.build/postgresql/unified-task24-cron-delivery-accepted.log` 为完整文件 7 passed、0 failed，包含 gateway 实际入口和两项配置错误诊断；本 Reviewer 独立读取了测试源码、红测首失败及最新结果。本次没有重复执行同一实库文件，不把日志核对称为独立重跑。

### Cron identity 读取先于 run_job，坏配置泄出 ParserError

原触发链：`gateway/session_cron.py` 的 `_run_identified` → 新领域分流的 `cron.executions.get_execution` → `resolve_db_configuration` → fail-closed 配置读取。在进入 `run_job` 原有失败结果处理之前，坏 YAML 原始 parser 异常已经逃出。

已读取 `.build/postgresql/unified-task24-cron-config-red.log` 的完整窄红测栈：现有 `test_corrupt_config_yaml_refuses_even_with_job_model` 因 `ruamel.yaml.parser.ParserError` 失败，栈明确经过上述三层，不是仅有 deadline 或资源警告。

当前整改：

- `db_setup._storage_config` 为后端选择和完整配置解析复用同一入口，捕获 `YAMLError`/`OSError`，只暴露拥有者配置路径和修复提示；使用 `raise ... from None`，不把 parser 原始配置片段拼入异常链。
- `_run_identified` 在账本读取的 `StorageError` 边界返回原 Cron 失败 tuple，使用既有错误文档格式化，不继续启动 job/model；成功分支仍绑定并 finally 释放 execution identity。
- 未将坏配置改为空配置，没有 fallback 到 SQLite，没有重试写入或猜测数据库提交状态。

判断：该行为违约在当前指定增量中已修正。主 Agent 最新 `.build/postgresql/unified-task24-cron-config-accepted.log` 为现有坏 YAML 窄合同 1 passed，保留“不构造 AIAgent”和既有可操作错误提示断言。

## 独立 probe 与真实验证记录

本 Reviewer 另执行一批 3 项 probe：

| Probe | 结果与判据 |
| --- | --- |
| 真实 `_run_identified` 遇坏 YAML | 返回失败 tuple、final_response 为空；job/model spy 零调用、SQLite connect spy 零调用；整个结果不含配置私有标记；CronExecution ContextVar 与调用前相同。 |
| `storage_backend` 遇 PermissionError | 统一报 `StorageConfigurationError`；格式化 traceback 不包含原 I/O 异常私有文本。 |
| `resolve_db_configuration` 遇 PermissionError | 同上，完整解析入口与后端选择入口保持一致。 |

命令：`scripts/run_tests.sh .build/postgresql/review_foundation/test_cron_config_followup.py -j 1`。使用 PM 解释器 `D:/AI/hermes-agent/.build/postgresql/full-test-env/Scripts/python.exe`、`HERMES_TEST_FILE_RETRIES=0`；3 passed、0 failed、0 skipped，runner 退出 0。日志 `.build/postgresql/review-foundation-cron-config-followup.log`。

PG 验证仅由既有 fixture 使用私有配置路径及归属核对后的随机 Schema；本 Reviewer 未打印凭据、未操作正式 Profile/服务。

保留一次名为 green 但实际失败的中间记录：`.build/postgresql/unified-task24-cron-config-drain-green.log`。该次新发送逻辑已运行，但 peer 断言误用 queued，实际领域状态为 pending；另一个测试文件未加载 PG 参数插件而 0 collected。它不是通过证据。后续分开运行、修正测试术语后，上述 delivery 7 passed 与 config 1 passed 才是有效结果；没有删掉 peer 状态或隔离断言来换绿。

## 验证边界与剩余门禁

- 本次错误脱敏结论只覆盖新增 storage 入口异常及 Cron 返回结果/错误文档，不声称审计了所有既有组件日志的脱敏。
- 实库投递通过证明当前进程中的持久队列、gateway scope、实际 wrapper、连接释放及再次打开；不把同进程重开说成新的独立 daemon 进程重启验收。
- 未复跑全部原生 Cron、API、Agent 并发与 daemon 矩阵。Task 24 原生宽回归已有多项失败，除本次具备明确红绿证据的坏 YAML 项外，其余仍需完整首栈、同条件基准 A/B 或针对性诊断；不能因源文件无 diff、旧绿或本批通过就判作既有问题。
- 完整 PG/原生/构建/发行最终汇总、其他 Reviewer 的后续整改及适用的 7 项非 WSL POSIX 私有启动页验收，均不由本批局部结果替代。

## 结论

当前指定的两项 Cron 消费者整改未发现仍未处理的 blocking/major；新增领域分流没有以 SQLite 回落、关闭功能或删除关键业务断言换取通过。

整体交付仍为 `CHANGES_REQUIRED`：最终广泛验证及适用平台门禁尚未完成。本报告不批准合并、不声明 `READY_TO_MERGE`，也不修改前次固定提交的审查结论。

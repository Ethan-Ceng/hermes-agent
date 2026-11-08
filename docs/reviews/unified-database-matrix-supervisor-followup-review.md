# Matrix 永久回归与监督恢复增量复审

2026-11-08。独立 Reviewer，承接 Matrix 初审及 `unified-database-matrix-followup-review.md`。本次只审查后续 `has_session`、同步循环监督恢复接线与永久测试；未改实现、仓库测试或提交。原报告的历史结论保持原样。

## 增量核对

未发现新的未处理 blocking/major。

- `hermes_db/matrix_crypto.py:110`：`has_session` 在 PG 读取前后均检查 ratchet 是否仍可用。后一次检查有必要：读取等待期间另一个保存可能失败并 poison；SDK 不应据过时的 False 继续申请远端 one-time key。当前实现保持真实 PG scope/generation 读取，没有以缓存替代持久查询。
- `plugins/platforms/matrix/adapter_sync.py:12`：初次读取游标和批次处理中的 StorageError 均进入既有 fatal/retry supervisor，设置 `matrix_storage`、`retryable=True`、停止 running 状态，并通知监督器。不会继续每5秒复用不确定 ratchet。`adapter.py` 的 `_sync_loop` 是实际委托入口。
- 实际接线已追踪至 `BasePlatformAdapter._notify_fatal_error` 的 detached/shield 保护，以及 GatewayRunner 的 queue-before-disconnect；默认和多 Profile 接线仍使用既有 owning-profile handler。此次额外动态检查执行了真实主监督器队列/断开流程；未将简单回调通知等同于实际完成入队。
- `test_matrix_sdk_edges.py` 保留前次4项实际 SDK/PG 边界，新增实际 adapter sync loop 失败通知、旧游标不变、新 SDK/store 重开后继续推进的合同。原两条并发/吞错回归仍在 `test_matrix_sdk_concurrency.py`。测试没有改弱为只断言方法存在或 `.db` 缺失。

## Reviewer 实际运行

使用现有 Linux PM 环境、真实 mautrix 0.21.1/libolm、核对归属的随机 PostgreSQL Schema；PG 业务 SQLite 全拒绝。全部经 `scripts/run_tests.sh`，无重试、无公网 Matrix 请求。

1. `.build/postgresql/test_review_matrix_supervisor.py`：两项独立诊断实际 `2 passed`，23.3秒，证据在 `review-matrix-supervisor-incremental.log`。
   - 真实 SDK 正等待 `has_session` 的 PG 读取时，另一真实更新回滚并 poison；读取返回后明确 StorageClosedError，远端 OTK claim 未发生。
   - 实际 Matrix sync loop 接实际 `GatewayRunner._handle_adapter_fatal_error`，真实加入重连队列，真实 disconnect 取消 Matrix carrier 后 detached handler 完成；队列保留原 adapter，未退出网关。新 store 仍读到旧游标。仅抑制启动真正外部 reconnect watcher，避免公网连接；未替换队列/断开实现。
2. 永久合同补跑：`scripts/run_tests.sh tests/hermes_db/postgresql/test_matrix_sdk_edges.py tests/hermes_db/postgresql/test_matrix_sdk_concurrency.py -j 1 -- -m integration --postgres-test-config=<私有路径>`，日志 `review-matrix-permanent-incremental.log`，退出0，`7 passed, 0 failed`，41.0秒（edges5、concurrency2）。

第一次尝试把 `.build` 和正常 tests 放在同批并共用 `-p tests.conftest ...`，导致正常 tests 的 conftest 重复注册，永久文件0执行、runner退出1；这是 reviewer 参数错误，不是业务失败。该次 `.build` 两项已实际通过，未重复运行；随后正常 tests 单独去掉 `-p` 补跑，得到上述7项通过。

Root 提供的 `unified-task24-matrix-recovery-final.log` 已读取：实际17 passed。其 Native `contracts/test_single_backend.py` 被 `-m integration` 排除，不计作4项新 Native 通过证据，本次也没有据此扩大结论。

复验时关键文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| hermes_db/matrix_crypto.py | 9FE1970599C44E9AF1FF7790208534BDB77CA90F0814A99E92A1D65E06AEC120 |
| plugins/platforms/matrix/adapter.py | 693DCD1BDFF2E259D62035D78D5811732E0FCE9F6A762F92C2D3951900ECB228 |
| plugins/platforms/matrix/adapter_sync.py | D4F47B39F8156F03691AAA4E4243E881D9118BA48116F16EF54B86A726007400 |
| plugins/platforms/matrix/adapter_pg_client.py | B347E7388408746EDD69432BED9F9E475E93D6E46AF4E9D10A69DC74FEBDDECF |
| tests/hermes_db/postgresql/test_matrix_sdk_edges.py | 4294FAAEB44ED7B167E15CF981A2C4032CFDD1472377CDF541B7482F1A4007C1 |

## 门禁结论

本次 Matrix 增量复审通过：原两项 major 保持已关闭，前次“关键补查行为尚待永久化”已由永久7项真实回归及本次独立执行补齐；监督恢复和 has_session 等待期间 poison 的边界有新增独立实证。

整个分支仍保持 `FAILED / CHANGES_REQUIRED` 的总体门禁：本报告不替代 Task24 全域最新结果、其他 Reviewer 的范围、新提交独立发行载荷或已知适用主机缺口，也不批准合并。

# 统一数据库协作域整改复审

## 审查范围

- 日期：2026-11-08；独立 Reviewer。
- 基准仍为 `a875342384`，当前 HEAD 为 `3febe6fc313faf34693ce9cb2075a3a894ea82d3` 加未提交整改工作区；本报告仅适用于本次核对的文件，不外推到后续修改。
- 保留 [原审查报告](unified-database-collaboration-review.md) 的全部原始发现、失败日志和过程记录，本报告不改写历史失败为通过。
- 本轮逐项读取实际整改：Board file_job 完成态转移与 stage 清理、附件规范路径及旧 raw 别名/token、所有 worker COMMANDS 的拒绝回执边界、phantom-warning Core 分流与 outbox、原生/桌面房间位置和 Profile scope、实际 server 注册及 capabilities run-store 选择。
- 本轮不改生产源码或仓库已有测试，不提交；独立探针仍放忽略目录 `.build/postgresql/`。

## 问题处置

| 原发现 | 实际整改与复审证据 | 当前处置 |
| --- | --- | --- |
| RoomStoreRef 被当作 Path，原生/桌面入口崩溃 | 原生入口比较 location_root；PG forwarding 绕过 SQLite handoff；handler 全程绑定目标 runtime scope；实际 server 注册的 groups.list/capabilities 均执行成功 | 已关闭本发现 |
| 附件路径别名误删活引用 | 新写保存绝对位置，blob 锁/引用计数采用规范 path_key，清理在 token 与全 store canonical 活引用核对后进行；门前快速预检与门内复查同时保留 | 已关闭本发现 |
| 已完成 file_job 永久阻止后续生命周期 | done import→archive/delete 与 archive→delete 有明确转换；未清 stage 仍保留阻塞，成功清理后才解除 stage 引用；固定旧代次归档目录随 hard delete 清理 | 已关闭本发现 |
| 拒绝 claim 在 COMMIT-loss 后改变 verdict | claims 每个 None verdict 与同事务 receipt；heartbeat/block/unblock/schedule/failure 同类 False 路径补齐；request_changes 的事务内拒绝也记录原始 tuple；complete 的失败写/审计拒绝保存原事务回执 | 已关闭本发现 |
| phantom-warning 卡住 outbox，ready/workspace/hook 不执行 | `_flag_phantom_prose_refs` 已有具名 PG 分流，warning 在短事务中登记；实际 warning COMMIT 后确认丢失、phase 重放后只有一条 warning，子任务 ready、整个 outbox 排空 | 已关闭本发现 |
| foreign Profile owner absent 时读取 launch store | `methods_groups_scope.invoke` 包住整个 handler，包括 forwarding 与本地 fallback；双 PG store 同 room_id 的实际 handler 返回 foreign room | 已关闭本发现 |
| scoping wrapper 与 HandlerRegistry rebind 不兼容 | scope sibling 动态读取 module._bound_server；capabilities helper 在 register 中正确 rebind/publish；实际 `tui_gateway.server._methods` 调用验证，不仅是 helper 单测 | 已关闭本中间整改问题 |
| capabilities 直接构造 SQLite RunIdempotencyStore | PG 通过既有 open_run_store 在所选 Profile 短期 acquire/close；原生类仅作延迟 SQLite factory；StorageError 显式传播 | 已关闭本发现 |

旧 PG 兼容未被新写规范化测试替代：独立构造前版已保存的 raw stored_path/blob 行，验证规范引用删除后别名仍可读、最后别名删除才清理实际文件；旧 raw cleanup token 无活引用可重放，有 canonical 活引用时保留文件且新引用被拒绝。

跨事务核对结论：`request_review` 的前置拒绝来自只读准备，没有已提交的主业务写；最终 handoff 的成功/False 与回执共用主事务。`request_changes` 的事务内拒绝现已修复。completion 的前置/guard/acceptance 可以有准备事务，最终完成的主写与回执仍在同一事务；审计拒绝的 event 与 CommandRefusal 已原子登记。文件准备、外部 acceptance 查询与 observer 等待不放进长 SQL 事务。未发现需要进一步处置的新 blocking/major。

## 最新独立验证

独立执行：

```text
HERMES_PYTHON=D:/AI/hermes-agent/.build/postgresql/full-test-env/Scripts/python.exe
HERMES_TEST_FILE_RETRIES=0
D:/Programs/Git/bin/bash.exe scripts/run_tests.sh .build/postgresql/review_collab_second_probe.py -j 1 -- -p tests.hermes_db.conftest -m integration --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

结果：**8 passed，0 failed，0 skip，退出 0，retries=0**；实际 pytest 8 项，runner 静态估算显示约 7 不影响真实收集结果。日志 `.build/postgresql/unified-review-collab-closure-independent.log`，耗时 65.1 秒。

八项实际行为：

1. request_changes 原拒绝真实 COMMIT 后丢 ACK，在正常 review handoff/claim 后仍精确重放原 False tuple。
2. owner absent 时，foreign Profile 的实际注册 groups.list handler 返回 foreign 数据，而不是 launch 数据或接受任意 error。
3. phantom summary 完成后，子任务正常 ready 且 warning 已落库。
4. 旧 raw 路径两引用按最后引用清理实际文件。
5. 旧 raw cleanup token 无活引用时重放清理并确认 token。
6. 旧 raw cleanup token 有 canonical 活引用时保留文件并拒绝新引用。
7. 真实 `tui_gateway.server._methods` 注册后的 groups.list 与 groups.capabilities 成功，无 SQLite 连接尝试。
8. warning 自身真实 COMMIT 后丢 ACK，重放 phase 后 warning 恰为一条、后续阶段全部排空。

所有 probe 使用 PM Windows Python 3.14.9、实际 PG fixture、归属核对的随机 Schema、临时 Profile，启用全进程 SQLite audit guard。没有给 capabilities 或后台路径开豁免；没有操作正式 Profile、SQLite、服务或正式业务表。复验后的非秘密模块 SHA-256 记录在 `.build/postgresql/review-collab-closure-source.json`。

另外独立读取原始汇总与各文件结果：Root 的 `.build/postgresql/unified-task24-collaboration-recovery-regressions.log` 为 7 文件 69 passed / 0 failed；`.build/postgresql/unified-task24-closure-edges.log` 为 5 文件 14 passed / 0 failed。后者包括两类审计 CommandRefusal 的真实 COMMIT-loss 重放。这些属于经核对的补充证据，不冒称本 Reviewer 重新执行的 83 项。

此前独立 33 passed / 3 failed 记录继续保留：两项文件门顺序回归已恢复门前快检；completion 故障注入改为观察实际 kanban_attachments INSERT 后才丢主 COMMIT ACK，不再误击前置准备事务。最新相关绿测具备正确的业务触发点与文件保留断言。

## 无法验证项与总体门禁

- 本协作域已复现的代码缺陷，在当前核对版本内未留下未处置 blocking/major。
- 最新 Native 宽回归尚由父任务重跑；此前 FakeService 缺 db_path 与原生同 home 的 state.db/shared-state.db 匹配问题不能凭口述宣布通过。本 Reviewer 未独立执行该最新 Native 批次。
- 最终全域 PG/Native 宽回归、最新静态/发行检查、其他 Reviewer 的全部整改以及最终代码提交，仍由总体 Task24 门禁核对。
- 非 WSL 私有启动页七项的适用主机证据缺口继续保留；本次八项 PG 结果不能替代。

## 结论

本次协作域已发现问题的整改复审通过，当前范围未发现新增未处置 blocking/major。总体合并结论继续保留 **`CHANGES_REQUIRED`**，等待尚未完成的总体验证与适用平台证据；本报告不授权宣称全系统 `APPROVED` 或 `READY_TO_MERGE`。

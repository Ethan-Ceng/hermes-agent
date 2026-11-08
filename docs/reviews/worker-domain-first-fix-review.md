# Worker verification owner 通道独立整改复审

## 范围

2026-11-08，独立 Reviewer，按 `supercoder:code-review` 复审当前未提交的首步 owner identity、closed domain read 与 verification 写转发。完整读取 `agent/runtime_domain_store.py`、`gateway/session_worker_domains.py`、`session_worker_reads.py`、`hermes_db/operations/worker_domains.py`、`worker_handlers.py`、`hermes_db/runtime_workers.py`、verification domain/operations，以及实际 caller、worker Core、receipt 与 repository 清理逻辑。

复验使用 `task24-linux-state.json` 的当前工作区源码，既有 Linux PM Python 与真实 PG 隔离 fixture；源码清单 `.build/postgresql/review-worker-domain-policy-source.json`。仅写忽略的 `.build` 观测/诊断与审查报告，未改生产或仓库测试，未提交。RetainDB 本轮尚未实施。

## 问题列表与整改状态

### [major，已整改复验] 首版 worker 可通过自选 cutoff 删除同 store 其他会话的验证状态

首版位置：`hermes_db/operations/worker_domains.py:67` 的 `record_verification`，传入 worker 的 `created_at`、`cutoff`、`per_root_limit`、`total_limit`。仅检验时间格式与数值区间后，直接调用全 store retention。`hermes_db/repositories/verification.py:79` 的 prune 不局限本 session，因此仅校验 evidence.session_id 等于 assignment 仍不足。

独立实际 PG 见证使用合法本 session `same`，只将 cutoff 设为 `9999-12-31T00:00:00+00:00`：命令成功返回 evidence id=3，但同 store 的 foreign session 状态/事件从 **1/1 变为 0/0**，peer store 同 ID 仍 **1/1**。日志 `.build/postgresql/unified-review-worker-domain-retention-red.log`：**0 passed / 1 failed，exit 1，15.1 秒**；JSON `review-worker-domain-retention-evidence.json`。首版 handler 与 probe 分别保存在 `review_worker_domains_before_retention_fix.py`、`review_worker_domain_pruning_red_v1.py`，未抹掉原破坏证据。

Root 随后收紧协议：record 只接受 evidence；mark_edited 只接受 session_id/root/changed。owner 在原 Core 回执事务内生成 UTC 时间、30 天 cutoff、每 session/root 100 条与全 store 10000 条既有上限。普通 owner operations.record 的自定义参数接口保留。严格 fields 校验拒绝 worker 指定清理、时钟、数据集字段。

独立反向见证已通过：分别拒绝 created_at/cutoff/per_root_limit/total_limit/store_id/scope/target，以及 mark_edited 的 edited_at；随后合法新 record 与 mark_edited 均成功，同 store foreign 与 peer 的 state/events 保持 **1/1**，返回时间为 owner 当前 UTC。日志 `.build/postgresql/unified-review-worker-domain-retention-green.log`：**1 passed / 0 failed，exit 0，7.5 秒**；JSON `review-worker-domain-retention-green-evidence.json`。这是修正为正确拒绝并再执行合法协议的测试，没有把旧“命令应无异常”断言当成绿。

### 原 verification worker 获取失败：实际 consumer 路径整改通过

原 clean verification probe 保留原 actor、request marker、21 字节文件写入、90 秒业务等待、20 秒 child exit 等待及全进程 SQLite guard，直接在当前源码运行一次。结果 `.build/postgresql/unified-review-pg-worker-verification-first-fix.log`：**1 passed / 0 failed，exit 0，46.0 秒**。

实际 owner PID 2865402；真实 managed spawn/child guard 已捕获。文件写入成功、最终模型回复持久化、PG admission 与 worker terminal、owner 重查 verification_state 含该 session 的真实 changed path，verification factory 拒绝 **0**、SQLite 尝试 **0**。证据另存 `.build/postgresql/review-pg-worker-domains-first-fix-evidence.json`。该次 ordinary 完整见证在收紧 retention 前完成；后续新协议还由下面 config-only 完整见证覆盖。

### 当前局部结论

已发现的首版 retention major 完成整改及独立反向验证；本轮 verification owner 通道未发现其他未处理 blocking/major。原 RetainDB retain_queue major 继续保留，不能用 verification 的结果算作其通过。

## 权限、事务与身份复核

- `gateway/session_worker_reads.py` 先检查 serving、精确参数 shape 和 worker:adopt。storage.identity 与 domain.read 都沿现有 verify_read，核对实际 Profile、PID/birth、adoption claim、session/generation、当前 epoch 与 running 状态；domain read 只开放 verification.status，参数强制匹配当前 assignment session。没有 SQL、连接字符串或客户端选择 store/target 的入口。
- `storage_identity` 来自 `connection.authority.db`。响应仅含协议版本、后端、home、store_id 及 `resource_key` 摘要；该摘要排除密码、用户名等凭据，未把 DSN 返回 worker。WorkerDomainStore 在本地默认配置选择前取得该 binding，复用既有 RuntimeSessionStore，关闭的是短期 proxy，不关闭会话 store。
- 写入复用 `_apply` 的 durable journal/sequence 与 worker.persist。CoreEffect 在原 Connection 上执行 verification SQL；ReceiptDomainResource.read/write 只 yield 这个连接，不另开事务、提交或连接。receipt SQL、业务变化和序号更新由同一外层事务提交；真实回滚全部撤销，提交确认丢失后按原 sequence/digest 重放已有 receipt，handler 不再次生成时间或插入事件。
- record 只将分类后的固定 evidence 字段传给 owner。owner 的保留参数由既有常量决定；mark_edited 时间也由 owner 生成。原 store 锁、共享完整 verify 与保留策略仍走同一原 operations/repository，没有另造 SQL 实现或取消 guard。

## 默认 SQLite snapshot 与实际 owner PG

额外通过真实 session.create(ignore_user_config=True) 启动 config-only managed worker，保持原文件编辑见证；现有 `HERMES_VERIFY_ON_STOP=1` 使该模式的验证消费者实际启用。观测 hook 只记录真正的 `_bind_safe_worker_policy` 参数，不删除或改写 snapshot。

实际 child PID **2867947** / owner PID **2867753**，绑定值为 ignore_user_config=true、safe_mode=false、**snapshot_backend=sqlite**。即使默认 snapshot 选择 SQLite，文件编辑水位仍落入 owner 的 PG verification_state，模型回复持久化，admission/worker terminal，verification 拒绝 **0**、SQLite 尝试 **0**。最新协议完整验证日志 `.build/postgresql/unified-review-worker-domain-config-only-v2.log`：**1 passed / 0 failed，exit 0，62.3 秒**；JSON `review-worker-domain-config-only-evidence.json`。

首次诊断错误地额外断言默认 snapshot 字面不含 storage；当前 DEFAULT_CONFIG 已有 STORAGE_CONFIG，因此仅该观测前提失败，实际业务链当时已成功落 PG。该日志 `unified-review-worker-domain-config-only.log`、v1 observer 与 first-observation JSON 均保留，未记为生产红。v2 记录实际 backend 并验证真实默认 SQLite/owner PG 冲突，未伪造省略字段的 snapshot。旧 snapshot 真的省略 storage 时，当前 worker_resource 也在读取它之前取得 owner binding；此兼容路径为静态确认，本次实际执行的是当前真实默认 SQLite snapshot。

## 证据与剩余门禁

上述独立测试全部经现有 orchestrator → scripts/run_tests.sh，retries=0，使用归属核对的随机 Schema、临时 Profile 和真实 ordinary daemon/managed worker。没有管理正式服务、修改正式 Profile/SQLite 或既有业务表，没有打印私有 PG 配置内容。

另独立运行最新永久 `tests/hermes_db/postgresql/test_worker_domain_receipts.py` 两项：**2 passed / 0 failed，exit 0，8.5 秒**，日志 `.build/postgresql/unified-review-worker-domain-receipts-policy.log`。真实 evidence SQL 后 receipt 故障回滚、真实 COMMIT 后注入确认丢失并按原序号重放、同 ID peer 隔离、拒绝 foreign session/任意 SQL，以及正常新协议保持 foreign 数据均通过。该故障注入是客户端在真实事务提交后收到 UnknownCommitError，未声称做过网络丢包。

共享 probe 的 `review-pg-worker-domains-evidence.json` 会随同名 case 重跑更新；当前 verification 已是 green。原 clean red 的不可变日志仍为 `unified-review-pg-worker-verification-red.log`，初版 combined red case 仍在 JSON 的 project_and_verification，原报告保留的 PID/栈对应当时现场；first-fix green 已另存文件避免混淆。

RetainDB 原 major 未实施/未重跑。实际终端工具的证据分类到 worker RPC 端到端流程尚未由本 Reviewer 单独执行；record 的同事务回滚/未知提交回放已由上述永久 Core 合同独立通过。最终通用 worker/Native 回归、其他领域、最新生产提交与发行载荷及非 WSL 七项平台证据仍由总门禁核对。

## 结论

verification 的 owner 转发、owner 时钟/保留策略和已执行消费者复审通过。总体继续 **`CHANGES_REQUIRED`**：RetainDB 仍有实际复现的未处理 major，且本轮局部结果不能替代最终全域验收。

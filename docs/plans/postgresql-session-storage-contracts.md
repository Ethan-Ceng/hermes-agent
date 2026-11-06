# PostgreSQL 会话存储契约清单

日期：2026-11-06。Task 1 基于当前开发基线的 AST 声明与引用核对；不是 PostgreSQL 验证报告。

## 作用域与引用规则

- 连接目标、共享 schema、稳定 store_id、Profile 文件目录是四个不同概念。Profile 在组合入口由服务端解析 store_id；PG 必须显式配置非空 store_id，禁止按本地绝对路径生成。账号授权不在本轮实现。
- 所有业务表都有 store_id；主键/唯一键/索引以 store_id 为前缀，跨表外键包含 store_id。外部原有 ID 不被强制改成 UUID。
- sessions: (store_id,id)；messages: (store_id,id)，UID 唯一性按当前会话/谱系业务规则加 store_id，不能把 absorbed UID 当独立消息。system_prompts: (store_id,hash)。usage: (store_id,session_id,model,billing_provider,billing_base_url,billing_mode,task)。
- admissions: (store_id,admission_id)，去重 (store_id,principal_id,target_session_id,request_id)；worker: (store_id,execution_id)；receipt: (store_id,execution_id,sequence)；epoch: 每 store 一个 singleton。
- 路由: (store_id,scope,session_key)，代次: (store_id,source,session_key)，租约/压缩: (store_id,稳定谱系根)，心跳: (store_id,backend_id)，state_meta: (store_id,key)。墓碑和终态回执独立于可删正文，不因外键级联丢失。
- API response/conversation/key/admission/output-order 和 Run 幂等保留现有 API scope，再在所有键与引用前加 store_id；投递 obligation 在 store_id 内唯一。response 与 admission 引用不可跨 store。
- 相同 session_id、request_id、message_uid、execution_id、response_id 和 obligation_id 在不同 store 可同时存在。仅凭 ID 的查询、更新、删除、聚合、健康/清理任务均不合约。返回不存在与越权统一由上层授权边界决定，数据库查询永远限定作用域。

## 完整操作与锁定规则

| 操作 | 所有者 / Task | 原子边界与返回 | 失败与行为基准 |
| --- | --- | --- | --- |
| 工厂/句柄/池 | 3 | 不持有回合连接；不可变 scope；SQLite 复用 registry | 配置、缺驱动、连接、schema 错误明确失败，无降级；test_shared_session_db_registry |
| create/ensure/提示/usage | 6 | 会话与 prompt hash/计费各维度一次事务；现有 str/dict/None 返回 | 不重编码提示/工具快照；tests/hermes_state/test_hermes_state.py |
| append/batch/replace/归档/显示代表 | 7 | 锁定同一谱系，保护检查、身份、插入、计数、revision、显示顺序同一事务；现有行 ID/记录返回 | 所有旁路字段保真；任何步骤失败全部回滚 |
| epoch/准入/领取/结算/取消/steer/rehome/recover/mutate | 8 | epoch 栅栏、去重摘要、容量、FIFO、generation、watermark 和结果回执同一短事务；dict/bool/None 或原 RuntimeStoreError | test_runtime_admission；不同 payload 的同 key 冲突，旧代次不能写入 |
| Worker/异步委派 | 9 | receipt 与 mutation 在同一 Connection；执行 sequence 与摘要核对，重复返回原回执 | Worker 仍通过 owner RPC，不能直连绕过；tests/hermes_state/test_worker* |
| 压缩/turn lease | 10 | 稳定谱系根串行化领取/接管/续租/发布；holder 条件更新；bool/dict/ID 返回 | 过期未接管允许原 holder 续租；test_session_turn_lease、test_compression_lease_refresh_before_publish |
| routing/generation/heartbeat/hygiene | 11 | 保留 routing store 与 active store 分离；reset 增代、压缩不重置 conversation 身份 | 删除后世代不复用，后台任务显式绑 Profile |
| retirement/branch/rewind/rewrite/export | 12 | 锁定谱系，保留 terminal receipt、墓碑、route retirement；正文删除和终态栅栏同一事务 | test_terminal_retirement、test_retired_fence_outlives_horizon；不实现旧数据导入 |
| response/Run 幂等 | 13 | reserve/lookup/terminal/retention/输出顺序在短事务内；保留 fingerprint 与原回执 | test_api_idempotency_after_delete、test_api_idempotency_namespace；PG 不回落内存 |
| 投递义务 | 14 | 记录/领取/尝试/终态/恢复为条件事务；网络发送在事务外 | 不能自动重试未知发送结果；test_delivery_ledger* |
| 搜索 | 15 | 作用域、来源、active/compacted 过滤；稳定并列排序与分页；list/dict 返回 | 固定 CJK/代码/路径/布尔/前缀语料；test_search_or_relaxed_fallback |
| 健康/引用/分析/本地维护 | 16 | 普通业务查询替代 _conn 与 db_path；SQLite 文件能力单独处理 | PG 错误不得被解释为本地库未初始化或空归档引用 |
| 入口/后台/关闭 | 17 | 统一工厂与所有者 Profile；注入对象由持有方释放 | 所有隐含直连及 JSONL/memory fallback 纳入失败测试 |

所有多对象操作遵守同一锁顺序：store 的 epoch/control 栅栏 → 按稳定 ID 排序的谱系根 → 会话 → admissions/workers → messages/receipts/路由。不存在的根先用有作用域唯一键的持久控制记录创建，再锁定；不能只锁不存在的业务行。具体 PG 锁实现与争用证据在 Tasks 7–10 落实，不宣称此处已验证。

消息 ID 的 sequence 分配不代表提交顺序。同一谱系的追加、领取 watermark、替换和压缩发布必须共享根锁，在锁内分配 ID 和读取 watermark；不同谱系的 ID 不用于决定当前谱系尾部。压缩持锁只用于快照与最终提交，中间 LLM 调用释放连接；最终以 watermark 合并晚到尾部，不能覆盖。Task 7 原型若不能证明 ID 契约，则先记录偏差，引入显式会话序号，禁止保留未经证明的 id > mark。

重试仅限确认回滚的死锁/serialization failure，且重跑完整无外部效果事务。提交阶段断连是未知提交，须凭请求/回执查询；不能重跑 LLM、工具或发送。公开业务冲突保留 RuntimeStoreError 的 code/返回语义；驱动异常映射配置、连接、schema、事务冲突与未知提交，不在日志携带 SQL 参数或 DSN。

## 新数据类型与编码边界

- 整数使用有符号 64 位，时间/当前费用使用 DOUBLE PRECISION；保持现有 NULL 与 0/1 返回行为。所有当前业务列都保留，不将“无旧数据”解释为删除旁路字段。
- 标识/路由键为无 NUL 的 Unicode 文本；进入数据库前明确拒绝非法标识。用户正文、提示、推理、工具内容允许结构化 list/dict、str、None 及当前允许的 bytes/数字。
- SQLite 的 content JSON sentinel 含 NUL，PG TEXT 不支持 NUL，不能原样复用编码器。PG 正文使用有类型标签的 BYTEA 编码（JSON 结构保持现有映射/数字行为，bytes 不经有损文本转换）；提示/工具原文等需精确保真的字段用 BYTEA 保存 UTF-8 字节。检索投影独立解码并去除不可索引控制字符，绝不写回原文。
- prompt hash、请求指纹和消息 UID 使用现有规范输入计算，先计算再编码入库，不以 JSONB 的规范化输出重新计算。旁路 JSON 若需保持字面格式则保留原文本字节；受控状态 JSON 可使用 JSONB，不复制旧格式容错路径。
- display_identity 保留 bytes→BYTEA；reactions、api_content、reasoning_details、reasoning/tool UIDs、absorbed UIDs、active/compacted/display_order 均随替换/压缩尾部完整携带。孤立 surrogate 按当前消息 sanitization 处理；精确原文不重新排版。

## SessionDB 方法索引

下表逐项列出实际继承到 SessionDB 的公开声明（包括无静态消费者的候选 API）。签名/返回注解以链接源码为准；SQLite 没有注解的方法不杜撰返回类型。事务与异常遵守上述主题边界并在实现时由对应行为测试固定。静态消费者列为保守 attribute 匹配，可能包含同名独立存储；动态 getattr/透传接口另在入口清单核对。SQLite 维护和旧数据接口不进入跨后端协议。

| 方法（源码签名与返回） | Task | 当前生产消费者 | 现有行为测试 |
| --- | --- | --- | --- |
| [close](../../hermes_state.py#L1523) `self` → `见实现` | 3/16 | `agent/conversation_compression.py`, `agent/runtime_session_child.py`, `agent/runtime_session_store.py`, `agent/tool_executor.py`, `cron/scheduler.py`, `cron/scheduler_delivery.py`, `gateway/hosted_room_attachments.py`, `gateway/platforms/api_server.py`, `gateway/platforms/api_server_response_store.py`, `gateway/platforms/api_server_run_idempotency.py`, `gateway/platforms/api_server_runs.py`, `gateway/platforms/base.py`, `gateway/run_plugin_injection.py`, `gateway/run_shutdown.py`, `gateway/runtime_ownership.py`, `gateway/session_controls.py`, `gateway/session_ingress_media.py`, `gateway/session_managed_worker.py`, `gateway/session_tui_side.py`, `gateway/shutdown_flush.py`, `gateway/slash_commands.py`, `gateway/wake.py`, `hermes_cli/backup.py`, `hermes_cli/backup_restore.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/cli_snapshot.py`, `hermes_cli/doctor_state.py`, `hermes_cli/gateway_session_store.py`, `hermes_cli/kanban_db_connect.py`, `hermes_cli/kanban_db_dispatch.py`, `hermes_cli/main.py`, `hermes_cli/main_agent_cmds.py`, `hermes_cli/main_tui_launch.py`, `hermes_cli/oneshot.py`, `hermes_cli/prune_advisor.py`, `hermes_cli/session_lost_and_found.py`, `hermes_cli/session_recovery.py`, `hermes_cli/sessions_adopt.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/sessions_cmd_journal_mode.py`, `hermes_cli/sessions_repair_profiles.py`, `hermes_cli/sqlite_util.py`, `hermes_cli/status.py`, `hermes_cli/terminal_breadcrumbs.py`, `hermes_cli/update_cmd_maint.py`, `hermes_cli/web_routers/cron.py`, `hermes_cli/web_routers/profiles.py`, `hermes_cli/web_routers/sessions.py`, `hermes_cli/web_routers/status.py`, `hermes_cli/web_server_lifecycle.py`, `hermes_cli/web_server_sessions.py`, `plugins/hermes-achievements/dashboard/plugin_api.py`, `plugins/hermes-achievements/tests/test_achievement_engine.py`, `plugins/platforms/discord/recovery.py`, `run_agent.py`, `tools/bot_live_delivery.py`, `tools/cronjob_tools.py`, `tools/kanban_tools.py`, `tools/process_registry_results.py`, `tui_gateway/agent_callbacks.py`, `tui_gateway/change_watcher.py`, `tui_gateway/compute_host.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_prompt.py`, `tui_gateway/methods_session.py`, `tui_gateway/server.py`, `tui_gateway/session_lifecycle.py`, `tui_gateway/session_registry.py` | `tests/acp_adapter/test_acp_reattach_unknown_notice.py`, `tests/acp_adapter/test_empty_session_persistence.py`, `tests/acp_adapter/test_events.py`, `tests/acp_adapter/test_failed_turn_closure.py` |
| [get_meta](../../hermes_state.py#L1646) `self, key: str` → `Optional[str]` | 3/16 | `gateway/session_ancillary.py`, `gateway/session_recovery.py`, `gateway/session_viewer_automation.py`, `gateway/session_viewer_close.py`, `hermes_cli/goals.py` | `tests/agent/test_vault_backends.py`, `tests/agent/test_vault_store.py`, `tests/gateway/relay/test_relay_discord_interaction_labels.py`, `tests/gateway/test_derived_generation_after_sweep.py` |
| [set_meta](../../hermes_state.py#L1653) `self, key: str, value: str, *, cursor: Optional[sqlite3.Cursor]=None` → `None` | 3/16 | `gateway/session_recovery.py`, `hermes_cli/goals.py` | `tests/gateway/fixtures/ancillary_reads_peer.py`, `tests/gateway/test_authority_listing_loop_turns.py`, `tests/gateway/test_heartbeat_watch_restore.py`, `tests/gateway/test_local_session_lineage.py` |
| [retag_kanban_worker_sessions](../../hermes_state.py#L1665) `self, workspaces_root: str` → `int` | 3/16 | `hermes_cli/kanban_db_dispatch.py` | `tests/hermes_cli/test_kanban_worker_session_source.py` |
| [is_kanban_owned_session](../../hermes_state.py#L1688) `self, session_id: str` → `bool` | 3/16 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_cli/test_kanban_resume_guard.py` |
| [list_meta_prefix](../../hermes_state.py#L1710) `self, prefix: str` → `list[tuple[str, str]]` | 3/16 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_session_mutation_compress_preview.py`, `tests/hermes_cli/test_loops.py` |
| [set_latest_user_api_content](../../hermes_state_api_content.py#L17) `self, session_id: str, content: Any, api_content: str` → `int` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_api_content_row_addressed_backfill.py`, `tests/agent/test_api_content_sidecar.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/hermes_state/test_hermes_state.py` |
| [set_message_api_content](../../hermes_state_api_content.py#L41) `self, session_id: str, row_id: int, content: Any, api_content: str` → `int` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_api_content_row_addressed_backfill.py`, `tests/hermes_state/test_compaction_carried_tail_not_cloned.py`, `tests/hermes_state/test_runtime_worker_metadata.py` |
| [reopen_if_explicitly_closed](../../hermes_state_compression.py#L184) `self, session_id: str, *, provenance: str, patience_s: Optional[float]=None` → `Optional[str]` | 10 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [stamp_legacy_compression_chains](../../hermes_state_compression.py#L227) `self` → `int` | 16 | `gateway/session_authority.py` | 主题契约新增覆盖 |
| [find_live_compression_child](../../hermes_state_compression.py#L241) `self, parent_session_id: str` → `Optional[dict[str, Any]]` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_rotation_state.py`, `tests/hermes_state/test_compression_lineage_guard.py`, `tests/tui_gateway/test_manual_compress_history_fence.py` |
| [reopen_orphaned_compression_session](../../hermes_state_compression.py#L269) `self, session_id: str` → `bool` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_compression_lineage_guard.py`, `tests/hermes_state/test_runtime_worker_compression_cleanup.py` |
| [publish_compression_child](../../hermes_state_compression.py#L373) `self, *, parent_session_id: str, child_session_id: str, source: str, messages: list[dict[str, Any]], model: str &#124; None=None, model_config: dict[str, Any] &#124; None=None, system_prompt: str &#124; None=None, cwd: str &#124; None=None, profile_name: str &#124; None=None, compression_lock_holder: str &#124; None=None, require_compression_lease: bool=True, require_lease_refresh: bool=False, lease_ttl_seconds: float=300.0, watermark: Optional[int]=None, watermark_ceiling: Optional[int]=None` → `None` | 10 | `agent/conversation_compression.py` | `tests/acp_adapter/test_gateway_compressed_reopen.py`, `tests/agent/test_anthropic_preserved_thinking_replay.py`, `tests/agent/test_compression_boundary_hook.py`, `tests/agent/test_compression_concurrent_fork.py` |
| [record_compression_failure_cooldown](../../hermes_state_compression.py#L493) `self, session_id: str, cooldown_until: float, error: Optional[str]=None` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_compression_rotation_state.py`, `tests/agent/test_compression_stall_interrupt.py`, `tests/agent/test_context_compressor.py` |
| [get_compression_failure_cooldown](../../hermes_state_compression.py#L508) `self, session_id: str` → `Optional[dict[str, Any]]` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_attempt_lifecycle.py`, `tests/agent/test_compression_stall_interrupt.py`, `tests/agent/test_context_compressor.py`, `tests/agent/test_context_engine_host_contract.py` |
| [get_compression_failure_cooldown_row](../../hermes_state_compression.py#L516) `self, session_id: str` → `dict[str, Any]` | 10 | `agent/runtime_session_store.py` | `tests/agent/test_compression_concurrent_fork.py`, `tests/hermes_state/test_runtime_worker_compression.py`, `tests/hermes_state/test_runtime_worker_context.py` |
| [restore_compression_failure_cooldown_row](../../hermes_state_compression.py#L522) `self, session_id: str, snapshot: dict[str, Any]` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_concurrent_fork.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [clear_compression_failure_cooldown](../../hermes_state_compression.py#L551) `self, session_id: str` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_rotation_state.py`, `tests/agent/test_compression_stall_deterministic_fallback.py`, `tests/gateway/test_hygiene_warning_lifecycle.py`, `tests/gateway/test_session_hygiene.py` |
| [get_compression_fallback_streak](../../hermes_state_compression.py#L572) `self, session_id: str` → `int` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compaction_anti_thrash.py`, `tests/agent/test_compression_rotation_state.py`, `tests/agent/test_context_engine_host_contract.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [set_compression_fallback_streak](../../hermes_state_compression.py#L576) `self, session_id: str, streak: int` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_rotation_state.py`, `tests/agent/test_context_compressor_bench_probe.py`, `tests/agent/test_context_engine_host_contract.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [get_compression_ineffective_count](../../hermes_state_compression.py#L581) `self, session_id: str` → `int` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_anti_thrash_persistence.py`, `tests/agent/test_compression_anti_thrash_recovery.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [set_compression_ineffective_count](../../hermes_state_compression.py#L587) `self, session_id: str, count: int` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_anti_thrash_persistence.py`, `tests/agent/test_compression_anti_thrash_recovery.py`, `tests/agent/test_compression_rotation_state.py`, `tests/agent/test_idle_compaction_lock_and_guards.py` |
| [get_compression_recovery_deadline](../../hermes_state_compression.py#L592) `self, session_id: str` → `float` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_anti_thrash_recovery.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [set_compression_recovery_deadline](../../hermes_state_compression.py#L602) `self, session_id: str, deadline: float` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_anti_thrash_recovery.py`, `tests/hermes_state/test_runtime_worker_compression.py`, `tests/hermes_state/test_runtime_worker_context.py` |
| [get_compression_overload_streak](../../hermes_state_compression.py#L612) `self, session_id: str` → `int` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_context_compressor_overload.py` |
| [set_compression_overload_streak](../../hermes_state_compression.py#L616) `self, session_id: str, streak: int` → `None` | 10 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [increment_compression_overload_streak](../../hermes_state_compression.py#L621) `self, session_id: str` → `Optional[int]` | 10 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [refresh_compression_lock](../../hermes_state_compression.py#L633) `self, session_id: str, holder: str, ttl_seconds: float=300.0` → `bool` | 10 | `agent/conversation_compression.py` | `tests/gateway/fixtures/compression_persistence_worker.py`, `tests/hermes_state/test_compression_lineage_guard.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_runtime_worker_compression.py` |
| [try_acquire_compression_lock](../../hermes_state_compression.py#L651) `self, session_id: str, holder: str, ttl_seconds: float=300.0` → `bool` | 10 | `agent/conversation_compression.py` | `tests/acp_adapter/test_gateway_compressed_reopen.py`, `tests/agent/test_compress_signal_leak.py`, `tests/agent/test_compression_attempt_telemetry.py`, `tests/agent/test_compression_concurrent_fork.py` |
| [release_compression_lock](../../hermes_state_compression.py#L676) `self, session_id: str, holder: str` → `None` | 10 | `agent/conversation_compression.py` | `tests/acp_adapter/test_gateway_compressed_reopen.py`, `tests/agent/test_compression_review.py`, `tests/agent/test_compression_worker_isolation.py`, `tests/gateway/fixtures/compression_persistence_worker.py` |
| [try_acquire_session_turn_lease](../../hermes_state_compression.py#L719) `self, session_id: str, holder: str, *, ttl_seconds: float=300.0, patience_s: Optional[float]=None` → `bool` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_cross_process_turn_lease.py`, `tests/agent/test_turn_budget_durable_rows.py`, `tests/agent/test_turn_facade_lease.py`, `tests/gateway/fixtures/persistence_worker.py` |
| [acquire_session_turn_lease](../../hermes_state_compression.py#L744) `self, session_id: str, holder: str, *, ttl_seconds: float=300.0, wait_seconds: float=1800.0, poll_interval_seconds: float=1.0, on_wait=None, wait_notice_interval_seconds: float=15.0, should_abort=None, acquire_patience_s: float=0.5, on_contended=None` → `bool` | 10 | `agent/runtime_session_store.py`, `agent/turn_facade_lease.py` | `tests/agent/test_cross_process_turn_lease.py`, `tests/agent/test_runtime_session_store.py`, `tests/gateway/test_api_delegation_delivery_contract.py`, `tests/hermes_state/test_session_turn_lease.py` |
| [session_turn_lease_expires_at](../../hermes_state_compression.py#L806) `self, session_id: str, holder: str` → `Optional[float]` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_turn_facade_lease.py` |
| [refresh_session_turn_lease](../../hermes_state_compression.py#L817) `self, session_id: str, holder: str, *, ttl_seconds: float=300.0, patience_s: Optional[float]=None` → `bool` | 10 | `agent/turn_facade_lease.py` | `tests/agent/test_cross_process_turn_lease.py`, `tests/agent/test_turn_facade_lease.py`, `tests/gateway/fixtures/persistence_worker.py`, `tests/hermes_state/test_session_turn_lease.py` |
| [release_session_turn_lease](../../hermes_state_compression.py#L833) `self, session_id: str, holder: str` → `None` | 10 | `agent/turn_facade_lease.py` | `tests/agent/test_cross_process_turn_lease.py`, `tests/agent/test_turn_budget_durable_rows.py`, `tests/gateway/fixtures/persistence_worker.py`, `tests/gateway/test_api_delegation_delivery_contract.py` |
| [get_compression_lock_holder](../../hermes_state_compression.py#L844) `self, session_id: str` → `Optional[str]` | 10 | `agent/conversation_compression.py` | `tests/agent/test_compress_signal_leak.py`, `tests/agent/test_compression_attempt_lifecycle.py`, `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_compression_refusal_restores_transcript.py` |
| [finalize_orphaned_compression_sessions](../../hermes_state_compression.py#L852) `self` → `int` | 10 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_ledger_delete_consistency.py`, `tests/tui_gateway/test_lazy_session_regressions.py` |
| [get_compression_chain](../../hermes_state_compression.py#L884) `self, session_id: str` → `list[str]` | 10 | `tools/cronjob_tools.py` | `tests/hermes_state/test_hermes_state.py` |
| [get_compression_tip](../../hermes_state_compression.py#L897) `self, session_id: str` → `Optional[str]` | 10 | `acp_adapter/gateway_session_meta.py`, `agent/session_persistence.py`, `cron/scheduler.py`, `gateway/platforms/api_server.py`, `gateway/platforms/api_server_bot_chat.py`, `gateway/run_heartbeat_acceptance.py`, `gateway/run_notifications_ownership.py`, `gateway/session_ancillary.py`, `gateway/session_authority.py`, `gateway/session_automation.py`, `gateway/session_bot.py`, `gateway/session_controls.py`, `gateway/session_detached.py`, `gateway/session_listing.py`, `gateway/session_local_title.py`, `gateway/session_onboarding.py`, `gateway/session_transcript.py`, `gateway/session_tui_reads.py`, `gateway/session_viewer_close.py`, `hermes_cli/main.py`, `hermes_cli/sessions_adopt.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/terminal_breadcrumbs.py`, `hermes_cli/web_routers/sessions.py`, `tools/bot_live_delivery.py`, `tools/process_registry_results.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_session.py` | `tests/agent/test_compression_closed_adoption.py`, `tests/cron/test_cron_memory_contract.py`, `tests/cron/test_scheduler.py`, `tests/cron/test_sessiondb_init_hang.py` |
| [get_compression_lineage](../../hermes_state_compression.py#L916) `self, session_id: str` → `list[str]` | 10 | `acp_adapter/catalog.py`, `gateway/session_api.py`, `gateway/session_authority.py`, `gateway/session_automation.py`, `gateway/session_bot.py`, `gateway/session_history_mount.py` | `tests/agent/test_prompt_cache_scope.py`, `tests/gateway/fixtures/compression_persistence_worker.py`, `tests/hermes_state/test_compression_lineage_guard.py`, `tests/hermes_state/test_hermes_state.py` |
| [append_delegation_delivery](../../hermes_state_detached_results.py#L24) `self, session_id: str, content: str, metadata: dict[str, Any]` → `int` | 7 | `gateway/wake.py` | 主题契约新增覆盖 |
| [append_completion_note](../../hermes_state_detached_results.py#L33) `self, session_id: str, admission_id: str, content: str, display_kind: str, metadata: dict[str, Any]` → `int` | 7 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [record_gateway_session_peer](../../hermes_state_gateway.py#L234) `self, session_id: str, *, source: str, user_id: str &#124; None=None, session_key: str &#124; None=None, chat_id: str &#124; None=None, chat_type: str &#124; None=None, thread_id: str &#124; None=None, display_name: str &#124; None=None, origin_json: str &#124; None=None, include_compression_ancestors: bool=False, transport_profile: str &#124; None=None` → `None` | 11 | `gateway/platforms/api_server.py` | `tests/gateway/test_api_runs_legacy_declared_key.py`, `tests/gateway/test_api_server_declared_conversation.py`, `tests/gateway/test_api_source_binding.py`, `tests/gateway/test_authority_cold_route_recovery.py` |
| [save_gateway_routing_entry](../../hermes_state_gateway.py#L304) `self, session_key: str, entry_json: str, *, scope: str=''` → `None` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_active_turn_recovery.py`, `tests/gateway/test_authority_cold_route_recovery.py`, `tests/gateway/test_routing_entry_origin_heal.py`, `tests/gateway/test_routing_save_fast_path.py` |
| [replace_gateway_routing_entries](../../hermes_state_gateway.py#L319) `self, entries: dict[str, str], *, scope: str=''` → `set[str]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_session_mutation_retirement.py`, `tests/gateway/test_session_time_persistence.py` |
| [load_gateway_routing_entries](../../hermes_state_gateway.py#L337) `self, *, scope: str=''` → `dict[str, str]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_api_server_declared_conversation.py`, `tests/gateway/test_completion_missing_origin.py`, `tests/gateway/test_delete_secondary_profile_multiplex.py`, `tests/gateway/test_delete_session_no_resurrect.py` |
| [list_never_active_keyed_sessions](../../hermes_state_gateway.py#L342) `self, *, older_than_days: float` → `list[dict[str, Any]]` | 11 | `hermes_cli/sessions_cmd.py` | `tests/acp_adapter/test_empty_session_persistence.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_never_active_keyed_prune.py`, `tests/hermes_state/test_reset_lineage_delete_queued_work.py` |
| [gateway_routing_entry_for_session](../../hermes_state_gateway.py#L383) `self, session_id: str` → `Optional[dict[str, Any]]` | 11 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [retire_gateway_routes](../../hermes_state_gateway.py#L418) `self, session_ids, *, namespace, expiring=()` → `None` | 11 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [prune_never_active_keyed_sessions](../../hermes_state_gateway.py#L434) `self, *, older_than_days: float, sessions_dir: Optional[Path]=None, deleted_ids: Optional[list]=None` → `tuple[int, int, int]` | 11 | `gateway/session_prune.py`, `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_never_active_keyed_prune.py`, `tests/hermes_state/test_reset_lineage_delete_queued_work.py` |
| [list_gateway_sessions](../../hermes_state_gateway.py#L471) `self, *, platform: Optional[str]=None, active_only: bool=True` → `list[dict[str, Any]]` | 11 | `hermes_cli/status.py` | `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_hermes_state.py` |
| [find_latest_gateway_session_for_peer](../../hermes_state_gateway.py#L496) `self, *, source: str, user_id: Optional[str]=None, session_key: Optional[str]=None, chat_id: Optional[str]=None, chat_type: Optional[str]=None, thread_id: Optional[str]=None` → `Optional[dict[str, Any]]` | 11 | `gateway/platforms/api_server.py`, `gateway/session_api.py` | `tests/gateway/test_handoff_owned_recovery.py`, `tests/gateway/test_session_continuity.py`, `tests/gateway/test_session_degraded_db_continuity.py`, `tests/gateway/test_session_store_expiry_finalized.py` |
| [find_orphaned_gateway_sessions](../../hermes_state_gateway.py#L540) `self, *, max_gap_s: Optional[float]=None` → `list[dict[str, Any]]` | 11 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_orphan_gateway_session_repair.py` |
| [adopt_orphaned_gateway_session](../../hermes_state_gateway.py#L598) `self, orphan_id: str, donor_id: str` → `bool` | 11 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_orphan_gateway_session_repair.py` |
| [increment_hygiene_failure_streak](../../hermes_state_gateway.py#L649) `self, session_key: str` → `int` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_codex_hygiene_compaction.py`, `tests/gateway/test_session_hygiene_turnhold_adoption.py` |
| [reset_hygiene_failure_streak](../../hermes_state_gateway.py#L667) `self, session_key: str` → `None` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_session_hygiene_turnhold_adoption.py` |
| [rekey_profile_state](../../hermes_state_gateway.py#L673) `self, old_name: str, new_name: str` → `dict[str, int]` | 11 | `gateway/run_profile_reconcile.py`, `hermes_cli/profile_identity.py` | `tests/hermes_state/test_rekey_profile_state.py` |
| [purge_profile_state](../../hermes_state_gateway.py#L782) `self, profile: str` → `dict[str, int]` | 16 | `gateway/run_profile_reconcile.py`, `hermes_cli/profile_identity.py` | `tests/hermes_state/test_purge_profile_state.py` |
| [session_gateway_runtime](../../hermes_state_gateway.py#L855) `session_meta: Optional[dict[str, Any]]` → `dict[str, Any]` | 11 | `gateway/session_local_migration.py`, `hermes_cli/cli_model_switch_mixin.py`, `tui_gateway/agent_factory.py` | `tests/gateway/test_named_custom_provider_session_identity.py`, `tests/hermes_cli/test_resume_model_restore.py` |
| [register_backend_heartbeat](../../hermes_state_gateway.py#L901) `self, *, backend_id: str, pid: int, started_at: float, last_heartbeat: Optional[float]=None, profile: str='', host: str=''` → `None` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_profile_identity_purge.py`, `tests/hermes_cli/test_profiles.py`, `tests/hermes_state/test_orphan_sweep_cross_backend.py`, `tests/hermes_state/test_purge_profile_state.py` |
| [clear_backend_heartbeat](../../hermes_state_gateway.py#L918) `self, backend_id: str` → `bool` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_orphan_sweep_cross_backend.py` |
| [prune_stale_heartbeats](../../hermes_state_gateway.py#L926) `self, *, max_age_seconds: float` → `list[str]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_orphan_sweep_cross_backend.py` |
| [list_backend_heartbeats](../../hermes_state_gateway.py#L939) `self` → `list[dict[str, Any]]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_orphan_sweep_cross_backend.py`, `tests/tui_gateway/test_backend_heartbeat.py` |
| [request_handoff](../../hermes_state_gateway.py#L946) `self, session_id: str, platform: str` → `bool` | 11 | `hermes_cli/cli_commands_mixin.py`, `tui_gateway/methods_session.py` | `tests/conformance/persistence/test_cell2_consume_once.py`, `tests/gateway/test_async_session_db.py`, `tests/gateway/test_handoff_watcher_resilience.py`, `tests/hermes_cli/test_gateway_session_store.py` |
| [get_handoff_state](../../hermes_state_gateway.py#L955) `self, session_id: str` → `Optional[dict[str, Any]]` | 11 | `hermes_cli/cli_commands_mixin.py`, `tui_gateway/methods_session.py` | `tests/gateway/test_handoff_watcher_resilience.py`, `tests/hermes_cli/test_handoff_slow_dispatch_timeout.py`, `tests/hermes_cli/test_session_handoff.py`, `tests/hermes_state/test_session_db_read_path_split.py` |
| [list_pending_handoffs](../../hermes_state_gateway.py#L968) `self` → `list[dict[str, Any]]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_cli/test_session_handoff.py`, `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_session_db_read_path_split.py`, `tests/hermes_state/test_writer_conn_thread_safety.py` |
| [claim_handoff](../../hermes_state_gateway.py#L980) `self, session_id: str` → `bool` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_async_session_db.py`, `tests/hermes_cli/test_handoff_slow_dispatch_timeout.py`, `tests/hermes_cli/test_session_handoff.py` |
| [has_pending_handoffs](../../hermes_state_gateway.py#L987) `self` → `bool` | 11 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [complete_handoff](../../hermes_state_gateway.py#L991) `self, session_id: str` → `None` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_cli/test_handoff_slow_dispatch_timeout.py`, `tests/hermes_cli/test_session_handoff.py` |
| [fail_handoff](../../hermes_state_gateway.py#L997) `self, session_id: str, error: str, *, only_states: Optional[tuple[str, ...]]=None` → `bool` | 11 | `hermes_cli/cli_commands_mixin.py`, `tui_gateway/methods_session.py` | `tests/hermes_cli/test_handoff_slow_dispatch_timeout.py`, `tests/hermes_cli/test_session_handoff.py` |
| [reclaim_stale_running_handoffs](../../hermes_state_gateway.py#L1011) `self, error: str` → `list[str]` | 11 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_handoff_watcher_resilience.py` |
| [prune_empty_ghost_sessions](../../hermes_state_maintenance.py#L113) `self, sessions_dir: Optional[Path]=None` → `int` | 11/16 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_cli/test_gateway_session_store.py`, `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_ledger_delete_consistency.py` |
| [sweep_orphaned_sessions](../../hermes_state_maintenance.py#L160) `self, *, max_idle_seconds: float, sources: tuple[str, ...]=('tui', 'desktop', 'subagent'), exclude_ids: tuple[str, ...]=(), exclude_pinned: bool=False, heartbeat_staleness_seconds: Optional[float]=None, heartbeat_ownership_grace_seconds: Optional[float]=None, respect_gateway_heartbeats: bool=True` → `list[str]` | 11/16 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_compression_terminal_activity_persist.py`, `tests/hermes_state/test_orphan_sweep_cross_backend.py`, `tests/hermes_state/test_pinned_lineage.py`, `tests/hermes_state/test_sweep_orphaned_sessions.py` |
| [list_prune_candidates](../../hermes_state_maintenance.py#L270) `self, older_than_days: Optional[float]=None, source: str &#124; None=None, *, whole_lineages: bool=False, **filters` → `list[dict[str, Any]]` | 11/16 | `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/sessions.py` | `tests/acp_adapter/test_session.py`, `tests/hermes_cli/test_prune_spares_pinned.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_pinned_lineage.py` |
| [count_prune_matches](../../hermes_state_maintenance.py#L282) `self, older_than_days: Optional[float]=None, source: str &#124; None=None, *, pinned_only: bool=False, **filters` → `int` | 11/16 | `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_prune_spares_pinned.py`, `tests/hermes_state/test_hermes_state.py` |
| [count_open_prune_matches](../../hermes_state_maintenance.py#L293) `self, older_than_days: Optional[float]=None, source: str &#124; None=None, **filters` → `int` | 11/16 | `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/sessions.py` | `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_hermes_state_archive_open.py` |
| [archive_stale_sessions](../../hermes_state_maintenance.py#L306) `self, idle_days: float, *, exclude_pinned: bool=True` → `int` | 11/16 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_auto_archived_lineage_reactivation.py`, `tests/hermes_state/test_canonical_title_guard.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_pinned_archived_sidebar.py` |
| [maybe_auto_archive](../../hermes_state_maintenance.py#L333) `self, idle_days: float=3, min_interval_hours: int=24, exclude_pinned: bool=True` → `dict[str, Any]` | 11/16 | `gateway/run.py`, `hermes_cli/web_server_sessions.py` | `tests/hermes_state/test_startup_maintenance_lease.py` |
| [prune_sessions](../../hermes_state_maintenance.py#L364) `self, older_than_days: Optional[float]=90, source: str &#124; None=None, sessions_dir: Optional[Path]=None, exclude_active_write_guards: bool=False, deleted_ids: Optional[list]=None, **filters` → `int` | 11/16 | `gateway/session_prune.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/sessions.py` | `tests/gateway/test_bot_receipt_tombstone_expiry.py`, `tests/gateway/test_derived_generation_after_sweep.py`, `tests/gateway/test_secondary_route_fence_scope.py`, `tests/gateway/test_swept_bot_chat_fence.py` |
| [logical_size_bytes](../../hermes_state_maintenance.py#L423) `self` → `Optional[int]` | 11/16 | `hermes_cli/sessions_cmd.py` | 主题契约新增覆盖 |
| [vacuum](../../hermes_state_maintenance.py#L449) `self` → `int` | 16 | `hermes_cli/console_engine.py`, `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_prune_advisor.py`, `tests/hermes_state/test_clean_close_residual_poison.py`, `tests/hermes_state/test_deleted_wal_checkpoint_guard.py`, `tests/hermes_state/test_hermes_state.py` |
| [maybe_auto_prune_and_vacuum](../../hermes_state_maintenance.py#L478) `self, retention_days: int=90, min_interval_hours: int=24, vacuum: bool=True, sessions_dir: Optional[Path]=None, min_vacuum_interval_days: int=30, min_vacuum_freelist_ratio: float=AUTO_VACUUM_MIN_FREELIST_RATIO` → `dict[str, Any]` | 11/16 | `gateway/run.py` | `tests/hermes_cli/test_session_vacuum_config.py`, `tests/hermes_state/test_auto_vacuum_holder_gate.py`, `tests/hermes_state/test_auto_vacuum_in_process_holder_gate.py`, `tests/hermes_state/test_hermes_state.py` |
| [append_message](../../hermes_state_messages.py#L396) `self, session_id: str, role: str, content: str &#124; None=None, tool_name: str &#124; None=None, tool_calls: Any=None, tool_call_id: str &#124; None=None, token_count: int &#124; None=None, finish_reason: str &#124; None=None, reasoning: str &#124; None=None, reasoning_content: str &#124; None=None, reasoning_details: Any=None, codex_reasoning_items: Any=None, codex_message_items: Any=None, platform_message_id: str &#124; None=None, observed: bool=False, effect_disposition: Optional[str]=None, _compressed_summary: bool=False, timestamp: Any=None, api_content: Optional[str]=None, display_kind: Optional[str]=None, display_metadata: Optional[dict[str, Any]]=None, compression_lock_holder: Optional[str]=None, turn_lease_holder: Optional[str]=None, turn_lease_ttl_seconds: float=300.0, message_uid: Optional[str]=None` → `int` | 7 | `gateway/mirror.py`, `gateway/session_transcript.py`, `gateway/shutdown_flush.py`, `plugins/hermes-achievements/tests/test_achievement_engine.py`, `tui_gateway/server.py`, `tui_gateway/session_workdir.py` | `tests/acp_adapter/test_catalog_read_only.py`, `tests/acp_adapter/test_failed_turn_closure.py`, `tests/acp_adapter/test_gateway_catalog_cwd.py`, `tests/acp_adapter/test_gateway_catalog_local_rows.py` |
| [append_messages_batch](../../hermes_state_messages.py#L430) `self, session_id: str, messages: list[dict[str, Any]], compression_lock_holder: Optional[str]=None, turn_lease_holder: Optional[str]=None, chunk_rows: Optional[int]=None, turn_lease_ttl_seconds: float=300.0` → `int` | 7 | `agent/session_persistence.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_commands_mixin.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_workdir.py` | `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_cross_process_turn_lease.py`, `tests/agent/test_flush_uid_reinsert_guard.py`, `tests/agent/test_micro_compaction.py` |
| [set_latest_matching_message_display_kind](../../hermes_state_messages.py#L499) `self, session_id: str, *, role: str, content: str, display_kind: str, display_metadata: Optional[dict[str, Any]]=None` → `bool` | 7 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [set_message_reaction](../../hermes_state_messages.py#L523) `self, session_id: str, message_row_id: int, emoji: Optional[str], *, author: str='user'` → `Optional[list[dict[str, Any]]]` | 7 | `gateway/session_reactions.py`, `tools/react_to_message_tool.py`, `tui_gateway/methods_session.py` | `tests/agent/test_message_reactions.py`, `tests/agent/test_tool_call_incremental_persistence.py`, `tests/gateway/test_telegram_reactions.py`, `tests/hermes_state/test_compacted_message_reactions.py` |
| [get_message_reactions](../../hermes_state_messages.py#L549) `self, session_id: str, message_row_id: int` → `list[dict[str, Any]]` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_message_reactions.py`, `tests/gateway/fixtures/tui_desktop_routes_peer.py`, `tests/tools/test_reaction_session_identity.py` |
| [take_unseen_reactions](../../hermes_state_messages.py#L564) `self, session_id: str, *, author: str='user'` → `list[dict[str, Any]]` | 7 | `tui_gateway/methods_prompt.py` | `tests/agent/test_message_reactions.py`, `tests/hermes_state/test_compacted_message_reactions.py` |
| [latest_message_row_id](../../hermes_state_messages.py#L598) `self, session_id: str, *, role: str='user', offset: int=0, require_text: bool=True` → `Optional[int]` | 7 | `gateway/session_reactions.py`, `tools/react_to_message_tool.py`, `tui_gateway/methods_session.py` | `tests/agent/test_message_reactions.py`, `tests/gateway/fixtures/tui_desktop_routes_peer.py`, `tests/tools/test_react_to_message_tool.py`, `tests/tools/test_reaction_session_identity.py` |
| [latest_conversation_role](../../hermes_state_messages.py#L610) `self, session_id: str` → `Optional[str]` | 7 | `gateway/session_bot.py`, `gateway/session_transcript.py` | `tests/acp_adapter/test_failed_turn_closure.py`, `tests/agent/test_runtime_session_store_surface_parity.py`, `tests/gateway/test_api_session_compression_exhaustion.py`, `tests/gateway/test_authority_unknown_resolution.py` |
| [get_message_role](../../hermes_state_messages.py#L619) `self, session_id: str, row_id: int` → `Optional[str]` | 7 | `agent/conversation_compression.py`, `tools/react_to_message_tool.py` | `tests/agent/test_runtime_session_store_surface_parity.py` |
| [replace_messages](../../hermes_state_messages.py#L720) `self, session_id: str, messages: list[dict[str, Any]], active_only: bool=False, archive_dropped: bool=False, reject_active_turn_lease: bool=False` → `None` | 7 | `acp_adapter/session.py`, `gateway/platforms/api_server.py`, `gateway/session_transcript.py`, `tui_gateway/methods_prompt.py` | `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_turn_finalizer_final_response_persistence.py`, `tests/gateway/test_api_server_compaction_projection.py`, `tests/gateway/test_auto_reset_clean_context.py` |
| [replace_messages_in_transaction](../../hermes_state_messages.py#L746) `self, conn, session_id: str, messages: list[dict[str, Any]], *, active_only: bool=False, archive_dropped: bool=False, reject_active_turn_lease: bool=False, expected_active_ids: Optional[list[int]]=None` → `None` | 7 | `gateway/slash_commands_session.py` | 主题契约新增覆盖 |
| [has_archived_messages](../../hermes_state_messages.py#L814) `self, session_id: str` → `bool` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_retry_replacement.py` |
| [get_active_message_watermark](../../hermes_state_messages.py#L824) `self, session_id: str` → `int` | 7 | `agent/conversation_compression.py`, `gateway/session_transcript.py` | `tests/agent/test_micro_compaction.py`, `tests/gateway/fixtures/compression_persistence_worker.py`, `tests/gateway/test_api_server_compaction_projection.py`, `tests/gateway/test_compress_command.py` |
| [archive_and_compact](../../hermes_state_messages.py#L907) `self, session_id: str, compacted_messages: list[dict[str, Any]], model_config_patch: Optional[dict[str, Any]]=None, watermark: Optional[int]=None, lock_holder: Optional[str]=None, tail_count: int=0, carried_messages: Optional[list[dict[str, Any]]]=None, covered_ids: Optional[list[int]]=None, unresolved_held: Optional[list[dict[str, Any]]]=None, held_for_cas: Optional[list[dict[str, Any]]]=None` → `int` | 10 | `agent/context_compressor_prune.py`, `agent/conversation_compression.py`, `agent/micro_compaction.py`, `plugins/hermes-achievements/tests/test_achievement_engine.py` | `tests/agent/test_api_content_row_addressed_backfill.py`, `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_compression_persistence.py`, `tests/agent/test_compression_refusal_restores_transcript.py` |
| [set_user_message_content](../../hermes_state_messages.py#L1043) `self, session_id: str, row_id: int, content: Any, display_metadata: Optional[dict[str, Any]]=None` → `int` | 7 | `tui_gateway/session_auto_continue.py`, `tui_gateway/session_workdir.py` | `tests/agent/test_proactive_prune_restart_safety.py`, `tests/gateway/test_tui_session_reads.py`, `tests/hermes_state/test_compaction_carried_tail_not_cloned.py`, `tests/hermes_state/test_runtime_worker_metadata.py` |
| [deactivate_message](../../hermes_state_messages.py#L1061) `self, session_id: str, row_id: int` → `int` | 7 | `tui_gateway/session_auto_continue.py` | 主题契约新增覆盖 |
| [resolve_active_row_id](../../hermes_state_messages.py#L1073) `self, session_id: str, row_id: int` → `Optional[int]` | 7 | `tui_gateway/session_auto_continue.py` | 主题契约新增覆盖 |
| [deactivate_messages_by_display_kind](../../hermes_state_messages.py#L1093) `self, session_id: str, display_kind: str` → `int` | 7 | `tui_gateway/server.py` | 主题契约新增覆盖 |
| [display_message_count](../../hermes_state_messages.py#L1345) `self, session_id: str` → `int` | 7 | `tui_gateway/methods_profiles.py` | `tests/hermes_state/test_compacted_tool_result_paints_once.py` |
| [get_messages](../../hermes_state_messages.py#L1370) `self, session_id: str, include_inactive: bool=False, include_compacted: bool=False, limit: Optional[int]=None, offset: int=0, latest: bool=False, after_id: Optional[int]=None, include_ancestors: bool=False` → `list[dict[str, Any]]` | 7 | `gateway/platforms/api_server.py`, `gateway/run_topics.py`, `hermes_cli/goals.py`, `hermes_cli/web_routers/sessions.py`, `plugins/hermes-achievements/dashboard/plugin_api.py`, `tools/session_search_tool.py` | `tests/acp_adapter/test_failed_turn_closure.py`, `tests/acp_adapter/test_gateway_retry_command.py`, `tests/agent/test_860_dedup.py`, `tests/agent/test_api_content_row_addressed_backfill.py` |
| [find_pr_url_messages](../../hermes_state_messages.py#L1422) `self, session_ids: list[str]` → `list[dict[str, Any]]` | 7 | `hermes_cli/web_routers/profiles.py` | 主题契约新增覆盖 |
| [get_messages_around](../../hermes_state_messages.py#L1433) `self, session_id: str, around_message_id: int, window: int=5` → `dict[str, Any]` | 7 | `tools/session_search_tool.py` | `tests/hermes_state/test_get_messages_around.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_session_db_read_path_split.py` |
| [resolve_resume_session_id](../../hermes_state_messages.py#L1452) `self, session_id: str` → `str` | 7 | `agent/turn_facade_lease.py`, `gateway/platforms/api_server.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/oneshot.py`, `hermes_cli/web_routers/sessions.py`, `tools/kanban_tools.py`, `tui_gateway/methods_session.py` | `tests/gateway/test_api_server.py`, `tests/gateway/test_kanban_notifier_served_apiserver_wake.py`, `tests/gateway/test_matrix_project_context_isolation.py`, `tests/hermes_cli/test_cli_resume_command.py` |
| [get_messages_as_conversation](../../hermes_state_messages.py#L1517) `self, session_id: str, include_ancestors: bool=False, include_inactive: bool=False, repair_alternation: bool=False, include_row_ids: bool=False, include_compacted: bool=False` → `list[dict[str, Any]]` | 7 | `acp_adapter/session.py`, `agent/trace_upload.py`, `agent/turn_facade_lease.py`, `gateway/platforms/api_server.py`, `gateway/platforms/api_server_openai_routes.py`, `gateway/session_kanban.py`, `gateway/session_local_recovery.py`, `gateway/session_mutation_compress.py`, `gateway/session_mutation_model.py`, `gateway/session_transcript.py`, `gateway/session_tui_ops.py`, `gateway/session_tui_reads.py`, `gateway/session_tui_side.py`, `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_model_switch_mixin.py`, `hermes_cli/sessions_cmd.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_registry.py` | `tests/acp_adapter/test_empty_session_persistence.py`, `tests/acp_adapter/test_session.py`, `tests/agent/test_413_compression.py`, `tests/agent/test_api_content_row_addressed_backfill.py` |
| [conversation_revision](../../hermes_state_messages.py#L1536) `self, session_id: str, include_ancestors: bool=False` → `tuple` | 7 | `gateway/session_tui_reads.py` | 主题契约新增覆盖 |
| [get_resume_conversations](../../hermes_state_messages.py#L1667) `self, session_id: str` → `tuple[list[dict[str, Any]], list[dict[str, Any]]]` | 7 | `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/oneshot.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_registry.py` | `tests/agent/test_conversation_compression_manual.py`, `tests/agent/test_in_place_merged_user_rows.py`, `tests/agent/test_in_place_preflight_rewind.py`, `tests/agent/test_load_time_durability_stamp.py` |
| [get_resume_message_count](../../hermes_state_messages.py#L1727) `self, session_id: str, *, tip_only: bool=False` → `int` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_display_projection_parity.py`, `tests/hermes_state/test_hermes_state.py` |
| [assert_resume_safe](../../hermes_state_messages.py#L1734) `self, session_id: str, max_messages: Optional[int]=None, *, tip_only: bool=False` → `int` | 7 | `gateway/session_local_recovery.py`, `hermes_cli/oneshot.py` | `tests/hermes_cli/test_resume_display.py`, `tests/hermes_state/test_display_projection_parity.py`, `tests/hermes_state/test_hermes_state.py` |
| [get_ancestor_display_prefix](../../hermes_state_messages.py#L1754) `self, session_id: str` → `list[dict[str, Any]]` | 7 | `tui_gateway/methods_session.py`, `tui_gateway/session_registry.py` | `tests/hermes_state/test_composite_carrier_rewind.py`, `tests/hermes_state/test_compression_watermark_commit.py`, `tests/hermes_state/test_display_projection_parity.py`, `tests/hermes_state/test_hermes_state.py` |
| [get_conversation_root](../../hermes_state_messages.py#L1771) `self, session_id: str` → `str` | 7 | `agent/title_generator.py`, `run_agent.py` | `tests/hermes_state/test_conversation_root.py`, `tests/hermes_state/test_runtime_worker_history.py` |
| [get_active_message_ids](../../hermes_state_messages.py#L1821) `self, session_id: str` → `list[int]` | 7 | `gateway/slash_commands_session.py` | 主题契约新增覆盖 |
| [rewind_to_message](../../hermes_state_messages.py#L1850) `self, session_id: str, target_message_id: int, *, preserve_compaction_handoff: bool=False, expected_active_ids: Optional[list[int]]=None, expected_target_content: Any=None` → `dict[str, Any]` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_in_place_compaction.py`, `tests/gateway/test_resume_display_history.py`, `tests/gateway/test_retry_replacement.py`, `tests/gateway/test_undo_rewind_session.py` |
| [message_count](../../hermes_state_messages.py#L1879) `self, session_id: str &#124; None=None` → `int` | 7 | `hermes_cli/console_engine.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/sessions.py` | `tests/e2e/core/sqlite/_roles.py`, `tests/gateway/test_failure_writer_ownership.py`, `tests/hermes_state/test_append_messages_batch.py`, `tests/hermes_state/test_hermes_state.py` |
| [has_gateway_input_owner](../../hermes_state_messages.py#L1884) `self, session_id: str, owner: str` → `bool` | 7 | `gateway/session_transcript.py` | 主题契约新增覆盖 |
| [has_platform_message_id](../../hermes_state_messages.py#L1893) `self, session_id: str, platform_message_id: str` → `bool` | 7 | `gateway/run_turn_persistence.py`, `gateway/session_transcript.py` | `tests/gateway/test_dedupe_user_turns.py`, `tests/gateway/test_duplicate_user_message.py`, `tests/gateway/test_first_turn_session_meta_rebaseline.py`, `tests/gateway/test_incomplete_gateway_turns.py` |
| [is_explicit_fork_child](../../hermes_state_messages.py#L1925) `self, session_id: str` → `bool` | 7 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [latest_conversation_boundary](../../hermes_state_messages.py#L1931) `self, session_key: str, source: str` → `Optional[int]` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_declared_conversation_scope.py`, `tests/hermes_state/test_runtime_worker_history.py` |
| [clear_messages](../../hermes_state_messages.py#L1948) `self, session_id: str` → `None` | 7 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [purge_stale_tool_call_markers](../../hermes_state_messages.py#L1955) `self, *, dry_run: bool=False, backup: bool=True` → `dict[str, Any]` | 16 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_stale_tool_call_marker_session_repair.py` |
| [find_foreign_import](../../hermes_state_portability.py#L177) `self, origin` → `见实现` | 12 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [import_foreign_history](../../hermes_state_portability.py#L181) `self, origin, messages, *, title, cwd, profile` → `见实现` | 12 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_message_uid.py` |
| [distinct_session_cwds](../../hermes_state_portability.py#L234) `self, include_archived: bool=False` → `list[dict[str, Any]]` | 12 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [list_cron_job_runs](../../hermes_state_portability.py#L248) `self, job_id: str, limit: int=20, offset: int=0` → `list[dict[str, Any]]` | 12 | `hermes_cli/web_routers/cron.py`, `tools/cronjob_tools.py` | `tests/hermes_cli/test_web_server_cron_profiles.py`, `tests/hermes_state/test_cron_run_sessions.py`, `tests/hermes_state/test_hermes_state.py` |
| [cron_run_identity](../../hermes_state_portability.py#L273) `self, session_id: str` → `Optional[dict[str, Any]]` | 12 | `hermes_cli/web_routers/sessions.py` | `tests/hermes_state/test_cron_run_sessions.py` |
| [list_skill_scaffolded_sessions](../../hermes_state_portability.py#L320) `self, limit: int=200` → `list[dict[str, Any]]` | 12 | `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_session_skill_previews.py` |
| [export_session](../../hermes_state_portability.py#L347) `self, session_id: str, include_compacted: bool=False, include_inactive: bool=False` → `Optional[dict[str, Any]]` | 12 | `hermes_cli/console_engine.py`, `hermes_cli/session_export.py`, `hermes_cli/sessions_cmd.py` | `tests/gateway/test_managed_worker_client_env.py`, `tests/gateway/test_save_command_delivery.py`, `tests/gateway/test_watchdog_review.py`, `tests/hermes_cli/test_console_engine.py` |
| [export_session_lineage](../../hermes_state_portability.py#L357) `self, session_id: str, include_compacted: bool=False, include_inactive: bool=False` → `Optional[dict[str, Any]]` | 12 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_session_export_timings.py`, `tests/hermes_state/test_session_md_export.py`, `tests/tui_gateway/test_stranded_session_adoption.py` |
| [export_all](../../hermes_state_portability.py#L374) `self, source: str &#124; None=None, include_compacted: bool=False, include_inactive: bool=False` → `list[dict[str, Any]]` | 12 | `hermes_cli/console_engine.py`, `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_session_export_batch.py`, `tests/hermes_state/test_corrupt_row_robustness.py`, `tests/hermes_state/test_session_archived_round_trip.py`, `tests/hermes_state/test_session_import_keep_flags.py` |
| [adopt_session_lineage_from](../../hermes_state_portability.py#L401) `self, donor_db: Any, session_id: str, *, retire_donor: bool=True` → `dict[str, Any]` | 12 | `tui_gateway/methods_session.py` | `tests/hermes_state/test_session_import_keep_flags.py`, `tests/tui_gateway/test_stranded_session_adoption.py` |
| [import_sessions](../../hermes_state_portability.py#L789) `self, sessions: list[dict[str, Any]]` → `dict[str, Any]` | 12 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_session_tui_ops.py`, `tests/gateway/test_watchdog_review.py`, `tests/hermes_cli/test_save_transcript_history.py`, `tests/hermes_cli/test_session_system_prompt_dedup.py` |
| [find_crossed_profile_sessions](../../hermes_state_profile_repair.py#L77) `self, owner: str` → `dict[str, list[dict[str, Any]]]` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [list_gateway_routing_rows](../../hermes_state_profile_repair.py#L132) `self` → `list[dict[str, Any]]` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [find_profile_less_telegram_topic_rows](../../hermes_state_profile_repair.py#L137) `self` → `list[dict[str, Any]]` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [count_messages_all](../../hermes_state_profile_repair.py#L156) `self, session_id: str` → `int` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [relabel_sessions_to_key_profile](../../hermes_state_profile_repair.py#L162) `self, ids: Iterable[str]` → `int` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [sever_crossed_parents](../../hermes_state_profile_repair.py#L185) `self, ids: Iterable[str]` → `int` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [export_session_for_move](../../hermes_state_profile_repair.py#L210) `self, session_id: str` → `Optional[dict[str, Any]]` | 12 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [import_moved_session](../../hermes_state_profile_repair.py#L237) `self, payload: dict[str, Any], *, profile_name: str` → `str` | 12 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [delete_moved_session](../../hermes_state_profile_repair.py#L278) `self, session_id: str` → `bool` | 12 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [rekey_legacy_main_sessions](../../hermes_state_profile_repair.py#L298) `self, ids: Iterable[str], profile: str` → `int` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [delete_gateway_routing_rows](../../hermes_state_profile_repair.py#L318) `self, rows: Iterable[tuple[str, str]]` → `int` | 12 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [insert_gateway_routing_rows_if_absent](../../hermes_state_profile_repair.py#L329) `self, rows: Iterable[tuple[str, str, str, float]]` → `int` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [relabel_telegram_topic_rows](../../hermes_state_profile_repair.py#L344) `self, rows: Iterable[dict[str, Any]]` → `dict[str, int]` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [key_profiles_for_chat](../../hermes_state_profile_repair.py#L382) `self, platform: str, chat_id: str` → `set[str]` | 16 | `hermes_cli/sessions_repair_profiles.py` | 主题契约新增覆盖 |
| [request_prompt_refresh](../../hermes_state_prompt_refresh.py#L22) `self, session_id: Optional[str]=None` → `int` | 12 | `hermes_cli/sessions_cmd.py` | 主题契约新增覆盖 |
| [prompt_refresh_epoch](../../hermes_state_prompt_refresh.py#L41) `self, session_id: str` → `int` | 12 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [count_sessions_with_stored_prompt](../../hermes_state_prompt_refresh.py#L49) `self` → `int` | 12 | `hermes_cli/sessions_cmd.py` | 主题契约新增覆盖 |
| [rewritten_held_row_ids](../../hermes_state_prune_rewrite.py#L29) `self, session_id: str, held: list[dict[str, Any]]` → `list[int]` | 12 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_micro_compaction.py`, `tests/agent/test_proactive_prune_restart_safety.py` |
| [held_row_mismatches](../../hermes_state_prune_rewrite.py#L52) `self, conn, session_id: str, held: list[dict[str, Any]]` → `list[int]` | 12 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [rewrite_pruned_rows](../../hermes_state_prune_rewrite.py#L133) `self, session_id: str, changes: list[tuple[dict[str, Any], dict[str, Any]]], *, model_config_patch: Optional[dict[str, Any]]=None, turn_lease_holder: Optional[str]=None, turn_lease_ttl_seconds: float=300.0` → `int` | 12 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_micro_compaction.py`, `tests/agent/test_proactive_prune_restart_safety.py`, `tests/agent/test_turn_budget_durable_rows.py` |
| [rewind_user_turn](../../hermes_state_rewind.py#L59) `self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False, adopt_row_ids: bool=False` → `RewindOutcome` | 12 | `gateway/session_transcript.py`, `hermes_cli/cli_session_mixin.py`, `tui_gateway/session_workdir.py` | `tests/agent/test_pre_llm_block_hook.py`, `tests/hermes_cli/test_cli_retry.py`, `tests/hermes_cli/test_gateway_session_store.py`, `tests/hermes_cli/test_gateway_snapshot_restore_guards.py` |
| [plan_user_turn_rewind](../../hermes_state_rewind.py#L113) `self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False` → `RewindPlan` | 12 | `gateway/slash_commands_session.py` | 主题契约新增覆盖 |
| [retry_deferred_fts_recovery](../../hermes_state_schema.py#L596) `self` → `bool` | 16 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_deleted_wal_checkpoint_guard.py`, `tests/hermes_state/test_fts_rebuild_admission.py`, `tests/hermes_state/test_fts_runtime_rebuild.py` |
| [fts_rebuild_status](../../hermes_state_search.py#L325) `self` → `Optional[dict[str, Any]]` | 15 | `hermes_cli/web_routers/status.py`, `tools/session_search_tool.py` | `tests/hermes_state/test_fts_optimize_progress.py`, `tests/hermes_state/test_hermes_state.py` |
| [fts_cjk_rebuild_status](../../hermes_state_search.py#L330) `self` → `Optional[dict[str, Any]]` | 15 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_fts_cjk_bigram.py` |
| [fts_rebuild_step](../../hermes_state_search.py#L412) `self, progress: Optional[_BackfillProgress]=None` → `bool` | 15 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_fts_layout_drift.py`, `tests/hermes_state/test_fts_optimize_progress.py`, `tests/hermes_state/test_fts_tool_write_bounds.py`, `tests/hermes_state/test_fts_trigram_cron_exclusion.py` |
| [fts_cjk_rebuild_step](../../hermes_state_search.py#L425) `self, progress: Optional[_BackfillProgress]=None` → `bool` | 15 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [fts_optimize_available](../../hermes_state_search.py#L659) `self` → `bool` | 15 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_fts_cjk_bigram.py`, `tests/hermes_state/test_fts_layout_drift.py`, `tests/hermes_state/test_fts_optimize_progress.py`, `tests/hermes_state/test_fts_trigram_cron_exclusion.py` |
| [optimize_fts_storage](../../hermes_state_search.py#L851) `self, *, progress_cb: Optional[Callable[[dict[str, Any]], None]]=None, vacuum: bool=True` → `dict[str, Any]` | 15 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_fts_cjk_bigram.py`, `tests/hermes_state/test_fts_layout_drift.py`, `tests/hermes_state/test_fts_optimize_progress.py`, `tests/hermes_state/test_fts_trigram_cron_exclusion.py` |
| [get_anchored_view](../../hermes_state_search.py#L926) `self, session_id: str, around_message_id: int, window: int=5, bookend: int=3, keep_roles: Optional[tuple[str, ...]]=('user', 'assistant')` → `dict[str, Any]` | 15 | `tools/session_search_tool.py` | `tests/hermes_state/test_get_anchored_view.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_session_db_read_path_split.py` |
| [list_recent_user_messages](../../hermes_state_search.py#L972) `self, session_id: str, limit: int=20, include_inactive: bool=False` → `list[dict[str, Any]]` | 15 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_steer.py`, `tests/hermes_cli/test_list_recent_user_messages_handoffs.py`, `tests/hermes_cli/test_session_skill_previews.py` |
| [search_messages](../../hermes_state_search.py#L1257) `self, query: str, source_filter: list[str] &#124; None=None, exclude_sources: list[str] &#124; None=None, role_filter: list[str] &#124; None=None, limit: int=20, offset: int=0, sort: str &#124; None=None, include_inactive: bool=False, fields: Optional[Collection[str]]=None, after_ts: Optional[int]=None, before_ts: Optional[int]=None` → `list[dict[str, Any]]` | 15 | `hermes_cli/web_routers/sessions.py`, `tools/session_search_tool.py` | `tests/acp_adapter/test_session.py`, `tests/agent/test_codex_app_server_persist.py`, `tests/agent/test_conversation_compression_manual.py`, `tests/agent/test_in_place_compaction.py` |
| [search_sessions_by_id](../../hermes_state_search.py#L1432) `self, query: str, limit: int=20, include_archived: bool=True, source: str &#124; None=None, sources: list[str] &#124; None=None, exclude_sources: list[str] &#124; None=None` → `list[dict[str, Any]]` | 15 | `hermes_cli/web_routers/sessions.py` | `tests/hermes_state/test_hermes_state.py` |
| [optimize_fts](../../hermes_state_search.py#L1469) `self` → `int` | 15 | 无静态属性调用；保留至主题实施核对 | `tests/e2e/core/sqlite/_roles.py`, `tests/hermes_state/test_clean_close_residual_poison.py`, `tests/hermes_state/test_state_db_corrupt_quarantine.py` |
| [rebuild_fts](../../hermes_state_search.py#L1489) `self` → `int` | 16 | `gateway/session_transcript.py` | `tests/e2e/core/sqlite/_roles.py`, `tests/hermes_state/test_clean_close_residual_poison.py`, `tests/hermes_state/test_fts_rebuild_admission.py`, `tests/hermes_state/test_fts_rebuild_corruption_class.py` |
| [create_session](../../hermes_state_sessions.py#L416) `self, session_id: str, source: str, **kwargs` → `str` | 6 | `acp_adapter/session.py`, `agent/runtime_session_child.py`, `gateway/platforms/api_server.py`, `gateway/session_authority.py`, `gateway/session_automation.py`, `gateway/session_recovery.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/cli_session_mixin.py`, `plugins/hermes-achievements/tests/test_achievement_engine.py`, `run_agent.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_workdir.py` | `tests/acp_adapter/test_acp_commands.py`, `tests/acp_adapter/test_acp_mcp_discovery.py`, `tests/acp_adapter/test_catalog_read_only.py`, `tests/acp_adapter/test_empty_session_persistence.py` |
| [ensure_session](../../hermes_state_sessions.py#L421) `self, session_id: str, source: str='unknown', model: str &#124; None=None, **kwargs` → `str` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_delegation_switch_next_session.py`, `tests/agent/test_relay_llm.py`, `tests/agent/test_relay_runtime_plugins.py`, `tests/agent/test_relay_session_segments.py` |
| [set_expiry_finalized](../../hermes_state_sessions.py#L426) `self, session_id: str, finalized: bool=True` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [find_session_by_origin](../../hermes_state_sessions.py#L437) `self, *, platform: str, chat_id: str, thread_id: Optional[str]=None, user_id: Optional[str]=None` → `Optional[str]` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_mirror.py`, `tests/hermes_state/test_hermes_state.py` |
| [end_session](../../hermes_state_sessions.py#L477) `self, session_id: str, end_reason: str` → `None` | 6 | `acp_adapter/session.py`, `cron/scheduler.py`, `gateway/platforms/api_server.py`, `gateway/session_recovery.py`, `hermes_cli/cli_session_mixin.py`, `run_agent.py`, `tui_gateway/session_lifecycle.py` | `tests/acp_adapter/test_gateway_catalog_reset_owner.py`, `tests/acp_adapter/test_session.py`, `tests/acp_adapter/test_session_provenance.py`, `tests/agent/test_background_review_cache_parity.py` |
| [retire_undrained_queue_rows](../../hermes_state_sessions.py#L503) `self, session_id: str` → `int` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [reopen_session](../../hermes_state_sessions.py#L519) `self, session_id: str` → `None` | 6 | `acp_adapter/session.py`, `gateway/session_acp_lifecycle.py`, `gateway/session_api.py`, `gateway/session_local_recovery.py`, `gateway/session_recovery.py`, `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/oneshot.py`, `tui_gateway/methods_prompt.py` | `tests/gateway/test_session_end_delegations.py`, `tests/gateway/test_session_store_lock_io.py`, `tests/gateway/test_session_store_runtime_stale_guard.py`, `tests/gateway/test_session_store_stale_prune.py` |
| [promote_to_session_reset](../../hermes_state_sessions.py#L544) `self, session_id: str, reason: str='session_reset'` → `bool` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_declared_conversation_scope.py`, `tests/gateway/test_session_store_expiry_finalized.py`, `tests/gateway/test_session_store_lock_io.py`, `tests/gateway/test_session_store_runtime_stale_guard.py` |
| [update_session_cwd](../../hermes_state_sessions.py#L567) `self, session_id: str, cwd: str, git_branch: Optional[str]=None, git_repo_root: Optional[str]=None, replace_git_meta: bool=False` → `Optional[int]` | 6 | `acp_adapter/session.py`, `cron/scheduler.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_workdir.py` | `tests/agent/test_compression_rotation_state.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_session_git_metadata_generation.py` |
| [publish_session_git_metadata](../../hermes_state_sessions.py#L600) `self, session_id: str, cwd: str, generation: int, git_branch: Optional[str]=None, git_repo_root: Optional[str]=None` → `bool` | 6 | `acp_adapter/session.py`, `tui_gateway/session_workdir.py` | `tests/hermes_state/test_session_git_metadata_generation.py` |
| [backfill_repo_roots](../../hermes_state_sessions.py#L621) `self, cwd_to_root: dict[str, str]` → `None` | 16 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [touch_session_activity](../../hermes_state_sessions.py#L630) `self, session_id: str, ts: Optional[float]=None, *, description: Optional[str]=None, provenance: Optional[ActivityProvenance]=None` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_session_activity_persist.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/gateway/fixtures/rotation_persistence_worker.py`, `tests/gateway/test_watchdog_review.py` |
| [clear_session_activity_labels](../../hermes_state_sessions.py#L658) `self, session_id: str` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_activity_persist_off_relay_loop.py`, `tests/agent/test_session_activity_persist.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/gateway/test_watchdog_review.py` |
| [update_session_meta](../../hermes_state_sessions.py#L685) `self, session_id: str, model_config_json: str, model: Optional[str]=None` → `None` | 6 | `acp_adapter/session.py`, `tui_gateway/agent_factory.py` | `tests/acp_adapter/test_session_db_private_access.py`, `tests/tui_gateway/test_resume_switched_provider_endpoint.py` |
| [update_system_prompt](../../hermes_state_sessions.py#L695) `self, session_id: str, system_prompt: Optional[str]` → `None` | 6 | `agent/conversation_compression.py`, `agent/prompt_refresh.py`, `hermes_cli/sessions_cmd.py`, `tui_gateway/server.py` | `tests/agent/test_system_prompt_restore.py`, `tests/agent/test_system_prompt_switch_invalidation.py`, `tests/gateway/fixtures/compression_persistence_worker.py`, `tests/gateway/fixtures/rotation_persistence_worker.py` |
| [update_session_tool_names](../../hermes_state_sessions.py#L705) `self, session_id: str, pin: Any` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_bot_chat_toolset_refresh.py`, `tests/agent/test_runtime_session_store.py`, `tests/agent/test_system_prompt_restore.py`, `tests/gateway/test_session_mutation_compress_preview.py` |
| [update_session_model](../../hermes_state_sessions.py#L717) `self, session_id: str, model: str, provider: Optional[str]=None, *, base_url: Optional[str]=None, api_mode: Optional[str]=None` → `None` | 6 | `hermes_cli/cli_model_switch_mixin.py`, `tui_gateway/agent_factory.py` | `tests/agent/test_async_token_accounting.py`, `tests/agent/test_insights.py`, `tests/agent/test_system_prompt_switch_invalidation.py`, `tests/gateway/test_status_command.py` |
| [patch_session_model_config](../../hermes_state_sessions.py#L780) `self, session_id: str, patch: dict[str, Any]` → `None` | 6 | `agent/prompt_refresh.py`, `agent/runtime_session_store.py`, `hermes_cli/cli_model_switch_mixin.py` | `tests/agent/test_proactive_prune_restart_safety.py`, `tests/agent/test_would_grow_refusal_runway.py`, `tests/gateway/test_session_mutation_model.py`, `tests/gateway/test_session_mutation_model_busy.py` |
| [get_session_model_config_value](../../hermes_state_sessions.py#L787) `self, session_id: str, key: str, default: Any=None` → `Any` | 6 | `agent/runtime_session_store.py`, `gateway/session_automation.py` | `tests/agent/test_codex_app_server_thread_resume.py`, `tests/agent/test_would_grow_refusal_runway.py`, `tests/hermes_state/test_runtime_worker_compaction.py`, `tests/hermes_state/test_runtime_worker_context.py` |
| [update_conversation_model_config_value](../../hermes_state_sessions.py#L792) `self, session_id: str, key: str, update: Callable[[Any], Any]` → `Optional[str]` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [session_ids_with_model_config_key](../../hermes_state_sessions.py#L798) `self, key: str` → `list[str]` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [update_session_runtime_lock](../../hermes_state_sessions.py#L803) `self, session_id: str, *, model: Optional[str]=None, provider: Optional[str]=None, model_options: Optional[dict[str, Any]]=None, route_source: Optional[str]=None, confirmed: bool=False` → `None` | 6 | `gateway/platforms/api_server.py` | `tests/agent/test_system_prompt_switch_invalidation.py`, `tests/gateway/test_session_api.py`, `tests/hermes_cli/test_session_system_prompt_dedup.py` |
| [set_session_yolo](../../hermes_state_sessions.py#L823) `self, session_id: str, enabled: bool` → `None` | 6 | `gateway/session_busy_controls.py`, `gateway/slash_commands.py`, `hermes_cli/cli_init_mixin.py`, `hermes_cli/cli_session_mixin.py` | `tests/gateway/test_local_yolo_cold_restore.py`, `tests/gateway/test_yolo_launch_tristate.py`, `tests/gateway/test_yolo_restart_revocation.py`, `tests/hermes_cli/test_cli_yolo_resume_persistence.py` |
| [session_yolo_enabled](../../hermes_state_sessions.py#L830) `session_meta: Optional[dict[str, Any]]` → `bool` | 6 | `hermes_cli/cli_session_mixin.py`, `tui_gateway/methods_session.py` | `tests/hermes_cli/test_cli_yolo_resume_persistence.py`, `tests/tools/test_approval_yolo.py`, `tests/tui_gateway/test_resume_session_yolo.py` |
| [get_session](../../hermes_state_sessions.py#L834) `self, session_id: str` → `Optional[dict[str, Any]]` | 6 | `acp_adapter/session.py`, `agent/conversation_compression.py`, `agent/runtime_session_store.py`, `agent/session_persistence.py`, `agent/trace_upload.py`, `agent/turn_facade_lease.py`, `gateway/platforms/api_server.py`, `gateway/platforms/api_server_bot_chat.py`, `gateway/run_notifications_ownership.py`, `gateway/run_topics.py`, `gateway/run_turn_runner.py`, `gateway/session_a2a.py`, `gateway/session_api.py`, `gateway/session_api_turn.py`, `gateway/session_authority.py`, `gateway/session_automation.py`, `gateway/session_bot.py`, `gateway/session_controls.py`, `gateway/session_cron.py`, `gateway/session_deferred_pick.py`, `gateway/session_detached.py`, `gateway/session_history_mount.py`, `gateway/session_hosted_rpc.py`, `gateway/session_kanban.py`, `gateway/session_lifecycle.py`, `gateway/session_listing.py`, `gateway/session_local.py`, `gateway/session_local_mcp.py`, `gateway/session_local_migration.py`, `gateway/session_local_recovery.py`, `gateway/session_local_title.py`, `gateway/session_managed_worker.py`, `gateway/session_mutation_compress.py`, `gateway/session_mutations.py`, `gateway/session_onboarding.py`, `gateway/session_persistence.py`, `gateway/session_policy_refresh.py`, `gateway/session_route_recovery.py`, `gateway/session_setting_commands.py`, `gateway/session_transcript.py`, `gateway/session_tui_reads.py`, `gateway/session_usage.py`, `gateway/session_viewer_close.py`, `gateway/slash_commands_session.py`, `gateway/slash_commands_status.py`, `gateway/wake.py`, `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/cli_loops_mixin.py`, `hermes_cli/cli_session_mixin.py`, `hermes_cli/main.py`, `hermes_cli/main_resume_args.py`, `hermes_cli/main_tui_launch.py`, `hermes_cli/oneshot.py`, `hermes_cli/sessions_adopt.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/terminal_breadcrumbs.py`, `hermes_cli/web_routers/sessions.py`, `hermes_cli/web_server_sessions.py`, `tools/cronjob_tools.py`, `tools/kanban_tools.py`, `tools/session_search_tool.py`, `tui_gateway/agent_factory.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_prompt.py`, `tui_gateway/methods_session.py`, `tui_gateway/server.py`, `tui_gateway/session_lifecycle.py`, `tui_gateway/session_workdir.py` | `tests/acp_adapter/test_acp_dashboard_model_switch_validation.py`, `tests/acp_adapter/test_acp_unacked_identity_retry.py`, `tests/acp_adapter/test_empty_session_persistence.py`, `tests/acp_adapter/test_failed_turn_closure.py` |
| [get_session_list_row](../../hermes_state_sessions.py#L846) `self, session_id: str` → `Optional[dict[str, Any]]` | 6 | `gateway/session_local_close.py` | 主题契约新增覆盖 |
| [get_recent_session_model_route](../../hermes_state_sessions.py#L855) `self, session_id: str` → `Optional[dict[str, Any]]` | 6 | `gateway/slash_commands_status.py` | `tests/agent/test_voice_turn_route.py`, `tests/gateway/test_status_command.py`, `tests/gateway/test_usage_command.py`, `tests/hermes_state/test_recent_model_route.py` |
| [resolve_session_id](../../hermes_state_sessions.py#L877) `self, session_id_or_prefix: str` → `Optional[str]` | 6 | `agent/trace_upload.py`, `gateway/run_topics.py`, `gateway/session_controls.py`, `hermes_cli/console_engine.py`, `hermes_cli/main.py`, `hermes_cli/main_tui_launch.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/sessions.py`, `hermes_cli/web_server_sessions.py`, `tui_gateway/methods_session.py` | `tests/agent/test_trace_upload.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_session_delete_profile_isolation.py` |
| [backfill_null_session_profiles](../../hermes_state_sessions.py#L888) `self, profile_name: str` → `int` | 16 | `gateway/session_authority.py`, `hermes_cli/web_routers/sessions.py` | `tests/hermes_state/test_session_db_profile_stamp.py` |
| [backfill_acp_session_cwd](../../hermes_state_sessions.py#L907) `self` → `int` | 16 | `acp_adapter/session.py` | `tests/hermes_state/test_session_db_acp_cwd_backfill.py` |
| [set_session_archived](../../hermes_state_sessions.py#L953) `self, session_id: str, archived: bool, *, notify: bool=True` → `bool` | 6 | `gateway/platforms/api_server.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_workdir.py` | `tests/gateway/test_profiles_adopted_bot_chat.py`, `tests/gateway/test_session_api.py`, `tests/gateway/test_session_list_live_hidden.py`, `tests/gateway/test_stored_session_picker.py` |
| [unarchive_recoverable_session](../../hermes_state_sessions.py#L1004) `self, session_id: str` → `bool` | 6 | `gateway/platforms/api_server.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_session.py` | `tests/gateway/test_session_api.py`, `tests/tui_gateway/test_stranded_session_adoption.py` |
| [set_session_pinned](../../hermes_state_sessions.py#L1043) `self, session_id: str, pinned: bool` → `bool` | 6 | `gateway/platforms/api_server.py`, `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_profiles_session_archived_pages.py`, `tests/hermes_cli/test_profiles_sidebar_scope.py`, `tests/hermes_cli/test_prune_spares_pinned.py`, `tests/hermes_cli/test_sessions_export_retention.py` |
| [set_session_hidden](../../hermes_state_sessions.py#L1060) `self, session_id: str, hidden: bool` → `bool` | 6 | `gateway/platforms/api_server.py`, `gateway/session_controls.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_workdir.py` | `tests/gateway/test_legacy_stamped_bot_chat.py`, `tests/gateway/test_peer_dm_hidden_e2e.py`, `tests/gateway/test_profiles_adopted_bot_chat.py`, `tests/gateway/test_session_group_controls.py` |
| [set_session_read](../../hermes_state_sessions.py#L1064) `self, session_id: str, read: bool=True` → `bool` | 6 | `gateway/platforms/api_server.py` | `tests/hermes_cli/test_web_server.py`, `tests/hermes_state/test_session_read_state.py` |
| [session_unread](../../hermes_state_sessions.py#L1070) `session_row: dict[str, Any]` → `bool` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [list_recent_sessions_bounded](../../hermes_state_sessions.py#L1119) `self, *, limit: int=20, exclude_sources: list[str] &#124; None=None, timeout_seconds: float=3.0, candidate_limit: int &#124; None=None, lineage_limit: int &#124; None=None` → `list[dict[str, Any]]` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/hermes_state/test_bounded_recent_sessions.py`, `tests/hermes_state/test_session_list_index_choice.py` |
| [list_sessions_rich](../../hermes_state_sessions.py#L1303) `self, source: str &#124; None=None, sources: list[str] &#124; None=None, exclude_sources: list[str] &#124; None=None, cwd_prefix: str &#124; None=None, limit: int=20, offset: int=0, include_children: bool=False, min_message_count: int=0, project_compression_tips: bool=True, order_by_last_active: bool=False, include_archived: bool=False, archived_only: bool=False, id_query: str &#124; None=None, search_query: str &#124; None=None, compact_rows: bool=False, include_pinned: bool=False, session_key: str &#124; None=None, include_hidden: bool=False, include_subagents: bool=False, local_created_sources: Sequence[str] &#124; None=None` → `list[dict[str, Any]]` | 6 | `acp_adapter/catalog.py`, `gateway/platforms/api_server.py`, `gateway/session_listing.py`, `gateway/slash_commands_session.py`, `hermes_cli/console_engine.py`, `hermes_cli/gateway_session_store.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/profiles.py`, `hermes_cli/web_routers/sessions.py`, `hermes_cli/web_routers/status.py`, `hermes_cli/web_server_sessions.py`, `plugins/hermes-achievements/dashboard/plugin_api.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_session.py` | `tests/agent/test_token_guard_session_source.py`, `tests/agent/test_token_read_barrier_on_loop.py`, `tests/e2e/core/sqlite/_roles.py`, `tests/gateway/test_local_reset_lineage_one_conversation.py` |
| [session_lifecycle_statuses](../../hermes_state_sessions.py#L1461) `self, session_ids: list[str]` → `dict[str, str]` | 6 | `cron/scheduler.py`, `hermes_cli/sessions_cmd_browse.py` | `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/hermes_state/test_runtime_worker_lifecycle.py`, `tests/hermes_state/test_runtime_worker_read_fence.py`, `tests/hermes_state/test_session_lifecycle_status.py` |
| [assert_export_safe](../../hermes_state_sessions.py#L1487) `self, session_id: str, max_messages: Optional[int]=None` → `int` | 12 | `hermes_cli/session_export.py` | `tests/hermes_state/test_hermes_state.py` |
| [assert_exports_safe](../../hermes_state_sessions.py#L1508) `self, session_ids, max_messages: Optional[int]=None` → `None` | 12 | `hermes_cli/console_engine.py`, `hermes_cli/sessions_cmd.py` | 主题契约新增覆盖 |
| [search_sessions](../../hermes_state_sessions.py#L1542) `self, source: str &#124; Sequence[str] &#124; None=None, limit: int=20, offset: int=0, workspace_key: str &#124; None=None, local_created_sources: Sequence[str] &#124; None=None, skip_launch_stubs: bool=False` → `list[dict[str, Any]]` | 6 | `gateway/session_local_title.py`, `hermes_cli/console_engine.py`, `hermes_cli/gateway_session_store.py`, `hermes_cli/main.py`, `hermes_cli/sessions_cmd.py` | `tests/gateway/test_legacy_session_row_parity.py`, `tests/gateway/test_managed_worker_client_env.py`, `tests/gateway/test_onboarding_on_the_authority.py`, `tests/hermes_cli/test_cli_sessions_behind_newer_surfaces.py` |
| [session_count](../../hermes_state_sessions.py#L1571) `self, source: str &#124; None=None, sources: list[str] &#124; None=None, cwd_prefix: str &#124; None=None, min_message_count: int=0, include_archived: bool=False, archived_only: bool=False, exclude_children: bool=False, exclude_sources: list[str] &#124; None=None, include_subagents: bool=False, local_created_sources: Sequence[str] &#124; None=None` → `int` | 6 | `hermes_cli/console_engine.py`, `hermes_cli/gateway_session_store.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/web_routers/profiles.py`, `hermes_cli/web_routers/sessions.py` | `tests/gateway/test_local_session_recovery.py`, `tests/gateway/test_reset_lineage_session_count.py`, `tests/hermes_cli/test_sessions_repair_declarative.py`, `tests/hermes_cli/test_sessions_source_local.py` |
| [session_count_ge](../../hermes_state_sessions.py#L1589) `self, n: int=1` → `bool` | 6 | `gateway/session.py` | `tests/gateway/test_session.py`, `tests/hermes_state/test_hermes_state.py` |
| [session_count_by_source](../../hermes_state_sessions.py#L1593) `self, *, include_archived: bool=False, archived_only: bool=False, exclude_children: bool=False` → `dict[str, int]` | 6 | `hermes_cli/web_routers/sessions.py` | `tests/gateway/test_reset_lineage_session_count.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_local_lineage_cache.py` |
| [declared_scope_identity](../../hermes_state_sessions.py#L1615) `self, session_id: str` → `tuple[bool, str]` | 6 | `agent/runtime_session_compression.py` | `tests/hermes_state/test_runtime_worker_history.py` |
| [get_session_delete_targets](../../hermes_state_sessions.py#L1651) `self, session_id: str` → `list[str]` | 12 | `hermes_cli/sessions_cmd.py` | `tests/hermes_state/test_hermes_state.py` |
| [delete_session](../../hermes_state_sessions.py#L1702) `self, session_id: str, sessions_dir: Optional[Path]=None, expected_delete_ids: Optional[list[str]]=None, expected_display_messages: Optional[dict[str, list[dict[str, Any]]]]=None, exclude_active_write_guards: bool=False, include_compression_chain: bool=False` → `bool` | 12 | `gateway/platforms/api_server.py`, `gateway/session_onboarding.py`, `hermes_cli/gateway_session_store.py`, `hermes_cli/sessions_cmd.py`, `hermes_cli/sessions_cmd_browse.py`, `tui_gateway/methods_session.py` | `tests/agent/test_compression_concurrent_fork.py`, `tests/agent/test_declared_conversation_scope.py`, `tests/agent/test_session_row_under_live_agent_persist.py`, `tests/gateway/test_adversarial_responses_eviction.py` |
| [discard_unadmitted_session](../../hermes_state_sessions.py#L1773) `self, session_id: str` → `bool` | 12 | `tui_gateway/methods_session.py` | `tests/hermes_state/test_ledger_delete_consistency.py` |
| [delete_session_if_empty](../../hermes_state_sessions.py#L1791) `self, session_id: str, sessions_dir: Optional[Path]=None` → `bool` | 12 | `hermes_cli/cli_session_mixin.py` | `tests/hermes_cli/test_empty_session_hygiene.py`, `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_delete_session_write_guards.py`, `tests/hermes_state/test_ledger_delete_consistency.py` |
| [delete_sessions](../../hermes_state_sessions.py#L1835) `self, session_ids: list[str], sessions_dir: Optional[Path]=None, exclude_active_write_guards: bool=False, skipped_ids: Optional[list[str]]=None, include_compression_chain: bool=False` → `int` | 12 | `hermes_cli/web_routers/sessions.py` | `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_corrupt_row_robustness.py`, `tests/hermes_state/test_delete_compression_chain.py`, `tests/hermes_state/test_delete_session_write_guards.py` |
| [count_empty_sessions](../../hermes_state_sessions.py#L1934) `self` → `int` | 6 | `hermes_cli/web_routers/sessions.py` | `tests/hermes_cli/test_web_server.py`, `tests/hermes_state/test_empty_sweep_archived_transcript.py`, `tests/hermes_state/test_hermes_state.py` |
| [delete_empty_sessions](../../hermes_state_sessions.py#L1938) `self, sessions_dir: Optional[Path]=None` → `int` | 12 | `hermes_cli/web_routers/sessions.py` | `tests/hermes_cli/test_session_system_prompt_dedup.py`, `tests/hermes_state/test_empty_sweep_archived_transcript.py`, `tests/hermes_state/test_hermes_state.py`, `tests/hermes_state/test_ledger_delete_consistency.py` |
| [archive_sessions](../../hermes_state_sessions.py#L1969) `self, older_than_days: Optional[float]=None, source: str &#124; None=None, **filters` → `int` | 12 | `hermes_cli/sessions_cmd.py` | `tests/hermes_cli/test_prune_spares_pinned.py`, `tests/hermes_state/test_hermes_state_archive_open.py`, `tests/hermes_state/test_pinned_lineage.py`, `tests/hermes_state/test_session_archiving.py` |
| [apply_telegram_topic_migration](../../hermes_state_telegram.py#L119) `self` → `None` | 6 | `hermes_cli/session_recovery.py` | `tests/gateway/test_telegram_topic_mode.py`, `tests/gateway/test_telegram_topic_profile_isolation.py`, `tests/hermes_cli/test_session_recovery.py` |
| [enable_telegram_topic_mode](../../hermes_state_telegram.py#L164) `self, *, chat_id: str, user_id: str, profile_name: str='default', has_topics_enabled: Optional[bool]=None, allows_users_to_create_topics: Optional[bool]=None` → `None` | 6 | `gateway/slash_commands_session.py` | `tests/gateway/test_resume_command.py`, `tests/gateway/test_telegram_dm_topic_auto_transfer.py`, `tests/gateway/test_telegram_prune_stale_topic_binding.py`, `tests/gateway/test_telegram_topic_mode.py` |
| [disable_telegram_topic_mode](../../hermes_state_telegram.py#L198) `self, *, chat_id: str, profile_name: str='default', clear_bindings: bool=True` → `None` | 6 | `gateway/run_topics.py` | `tests/gateway/test_telegram_topic_profile_isolation.py` |
| [is_telegram_topic_mode_enabled](../../hermes_state_telegram.py#L220) `self, *, chat_id: str, user_id: str, profile_name: str='default'` → `bool` | 6 | `gateway/run_topics.py` | `tests/gateway/test_telegram_prune_stale_topic_binding.py`, `tests/gateway/test_telegram_topic_profile_isolation.py`, `tests/hermes_state/test_telegram_topic_selfheal.py` |
| [get_telegram_topic_binding](../../hermes_state_telegram.py#L229) `self, *, chat_id: str, thread_id: str, profile_name: str='default'` → `Optional[dict[str, Any]]` | 6 | `gateway/run_topics.py`, `gateway/slash_commands_session.py` | `tests/gateway/test_telegram_dm_topic_auto_transfer.py`, `tests/gateway/test_telegram_prune_stale_topic_binding.py`, `tests/gateway/test_telegram_topic_mode.py`, `tests/gateway/test_telegram_topic_profile_isolation.py` |
| [list_telegram_topic_bindings_for_chat](../../hermes_state_telegram.py#L240) `self, *, chat_id: str, profile_name: str='default'` → `list[dict[str, Any]]` | 6 | `gateway/run_topics.py` | `tests/gateway/test_telegram_topic_mode.py`, `tests/hermes_state/test_telegram_topic_selfheal.py` |
| [get_telegram_topic_binding_by_session](../../hermes_state_telegram.py#L251) `self, *, session_id: str` → `Optional[dict[str, Any]]` | 6 | `gateway/run_turn_runner.py` | `tests/gateway/test_compression_failure_session_sync.py`, `tests/gateway/test_telegram_topic_mode.py` |
| [delete_telegram_topic_binding](../../hermes_state_telegram.py#L259) `self, *, chat_id: str, thread_id: str, profile_name: str='default'` → `int` | 12 | 无静态属性调用；保留至主题实施核对 | `tests/gateway/test_telegram_prune_stale_topic_binding.py`, `tests/gateway/test_telegram_topic_profile_isolation.py` |
| [bind_telegram_topic](../../hermes_state_telegram.py#L304) `self, *, chat_id: str, thread_id: str, user_id: str, session_key: str, session_id: str, managed_mode: str='auto', profile_name: str='default'` → `None` | 6 | `gateway/run_topics.py` | `tests/gateway/test_resume_command.py`, `tests/gateway/test_telegram_dm_topic_auto_transfer.py`, `tests/gateway/test_telegram_prune_stale_topic_binding.py`, `tests/gateway/test_telegram_topic_mode.py` |
| [is_telegram_session_linked_to_topic](../../hermes_state_telegram.py#L341) `self, *, session_id: str` → `bool` | 6 | `gateway/run_topics.py` | 主题契约新增覆盖 |
| [list_unlinked_telegram_sessions_for_user](../../hermes_state_telegram.py#L350) `self, *, chat_id: str, user_id: str, profile_name: str='default', limit: int=10` → `list[dict[str, Any]]` | 6 | `gateway/run_topics.py` | `tests/hermes_state/test_session_list_index_choice.py` |
| [sanitize_title](../../hermes_state_titles.py#L49) `title: Optional[str]` → `Optional[str]` | 6 | `gateway/platforms/api_server.py`, `gateway/session_local_title.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_loops_mixin.py`, `hermes_cli/cli_session_mixin.py` | `tests/hermes_state/test_hermes_state.py` |
| [set_session_title](../../hermes_state_titles.py#L165) `self, session_id: str, title: str` → `bool` | 6 | `agent/conversation_compression.py`, `agent/title_generator.py`, `cron/scheduler.py`, `gateway/platforms/api_server.py`, `gateway/session_local_title.py`, `gateway/session_onboarding.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_agent_setup_mixin.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/cli_loops_mixin.py`, `hermes_cli/cli_session_mixin.py`, `hermes_cli/console_engine.py`, `hermes_cli/sessions_cmd.py`, `tui_gateway/methods_session.py` | `tests/agent/test_in_place_compaction.py`, `tests/agent/test_title_generator.py`, `tests/cron/test_scheduler_session_title_nudge.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py` |
| [set_auto_title](../../hermes_state_titles.py#L170) `self, session_id: str, title: str, *, source: str` → `bool` | 6 | `tui_gateway/methods_session.py` | `tests/agent/test_title_generator.py`, `tests/agent/test_turn_context.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/gateway/test_handoff_local_receipt.py` |
| [get_session_title](../../hermes_state_titles.py#L176) `self, session_id: str` → `Optional[str]` | 6 | `agent/agent_init.py`, `agent/conversation_compression.py`, `agent/title_generator.py`, `gateway/run_topics.py`, `gateway/slash_commands_session.py`, `gateway/slash_commands_status.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/cli_session_mixin.py`, `hermes_cli/main_tui_launch.py`, `hermes_cli/sessions_cmd.py`, `tui_gateway/methods_session.py`, `tui_gateway/session_registry.py` | `tests/agent/test_memory_user_id.py`, `tests/agent/test_title_generator.py`, `tests/gateway/test_branch_thread_command.py`, `tests/gateway/test_footer_command_mid_run.py` |
| [get_session_title_source](../../hermes_state_titles.py#L181) `self, session_id: str` → `Optional[str]` | 6 | `agent/agent_init.py`, `agent/conversation_compression.py` | `tests/agent/test_memory_user_id.py`, `tests/agent/test_title_generator.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py`, `tests/hermes_state/test_runtime_mutations.py` |
| [set_session_title_source](../../hermes_state_titles.py#L186) `self, session_id: str, source: str` → `bool` | 6 | `agent/conversation_compression.py` | `tests/hermes_state/test_runtime_worker_metadata.py`, `tests/hermes_state/test_runtime_worker_title_retry.py` |
| [get_session_by_title](../../hermes_state_titles.py#L195) `self, title: str` → `Optional[dict[str, Any]]` | 6 | `gateway/platforms/api_server.py`, `gateway/platforms/api_server_bot_chat.py`, `gateway/session_a2a.py`, `gateway/session_bot.py`, `gateway/session_local_migration.py`, `hermes_cli/cli_loops_mixin.py`, `tools/bot_live_delivery.py`, `tui_gateway/methods_profiles.py`, `tui_gateway/methods_session.py` | `tests/gateway/test_automation_notification_category.py`, `tests/gateway/test_bot_chat_follows_profile.py`, `tests/gateway/test_bot_chat_owner_adoption.py`, `tests/gateway/test_bot_chat_unadoptable_local_title.py` |
| [resolve_session_by_title](../../hermes_state_titles.py#L203) `self, title: str` → `Optional[str]` | 6 | `gateway/session_controls.py`, `gateway/session_local_title.py`, `gateway/slash_commands_session.py`, `hermes_cli/main.py`, `tools/session_search_tool.py` | `tests/gateway/test_matrix_project_context_isolation.py`, `tests/gateway/test_session_boundary_security_state.py`, `tests/hermes_cli/test_chat_c_fail_loudly.py`, `tests/hermes_cli/test_sessions_repair_profiles.py` |
| [get_next_title_in_lineage](../../hermes_state_titles.py#L222) `self, base_title: str` → `str` | 6 | `gateway/platforms/api_server.py`, `gateway/session_onboarding.py`, `gateway/slash_commands_session.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/sessions_cmd.py` | `tests/agent/test_title_generator.py`, `tests/cron/test_scheduler_session_title_nudge.py`, `tests/gateway/test_session_boundary_security_state.py`, `tests/hermes_state/test_hermes_state.py` |
| [get_latest_todo_result](../../hermes_state_todo.py#L16) `self, session_id: str, *, max_chars: Optional[int]=None` → `Optional[str]` | 7 | 无静态属性调用；保留至主题实施核对 | `tests/tui_gateway/test_todo_state_events.py` |
| [update_session_billing_route](../../hermes_state_usage.py#L86) `self, session_id: str, *, provider: str, base_url: str, billing_mode: Optional[str]=None` → `None` | 6 | `agent/agent_runtime_helpers.py` | `tests/agent/test_async_token_accounting.py`, `tests/agent/test_insights.py`, `tests/agent/test_system_prompt_switch_invalidation.py`, `tests/gateway/fixtures/lifecycle_persistence_worker.py` |
| [queue_token_counts](../../hermes_state_usage.py#L107) `self, session_id: str, **kwargs` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_async_token_accounting.py`, `tests/agent/test_runtime_session_store.py`, `tests/agent/test_token_persistence_non_cli.py`, `tests/agent/test_token_read_barrier_on_loop.py` |
| [flush_for_read](../../hermes_state_usage.py#L148) `self` → `bool` | 6 | 无静态属性调用；保留至主题实施核对 | 主题契约新增覆盖 |
| [flush_token_counts](../../hermes_state_usage.py#L159) `self, timeout: float=5.0` → `bool` | 6 | `agent/runtime_session_store.py`, `agent/session_persistence.py` | `tests/agent/test_async_token_accounting.py`, `tests/agent/test_token_guard_session_source.py`, `tests/agent/test_token_read_barrier_on_loop.py`, `tests/gateway/fixtures/agent_persistence_worker.py` |
| [update_token_counts](../../hermes_state_usage.py#L285) `self, session_id: str, input_tokens: int=0, output_tokens: int=0, model: str &#124; None=None, cache_read_tokens: int=0, cache_write_tokens: int=0, reasoning_tokens: int=0, estimated_cost_usd: Optional[float]=None, actual_cost_usd: Optional[float]=None, cost_status: Optional[str]=None, cost_source: Optional[str]=None, pricing_version: Optional[str]=None, billing_provider: Optional[str]=None, billing_base_url: Optional[str]=None, billing_mode: Optional[str]=None, api_call_count: int=0, absolute: bool=False, source: Optional[str]=None, task: str=''` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_async_token_accounting.py`, `tests/agent/test_insights.py`, `tests/agent/test_token_read_barrier_on_loop.py`, `tests/agent/test_voice_turn_route.py` |
| [record_auxiliary_usage](../../hermes_state_usage.py#L392) `self, session_id: str, task: str, *, model: Optional[str]=None, billing_provider: Optional[str]=None, billing_base_url: Optional[str]=None, input_tokens: int=0, output_tokens: int=0, cache_read_tokens: int=0, cache_write_tokens: int=0, reasoning_tokens: int=0, estimated_cost_usd: Optional[float]=None, api_call_count: int=1` → `None` | 6 | 无静态属性调用；保留至主题实施核对 | `tests/agent/test_worker_rpc_loop_diagnostic.py`, `tests/gateway/fixtures/persistence_worker.py`, `tests/gateway/test_resume_latest_local_cli.py`, `tests/hermes_cli/test_models_analytics_attribution.py` |
| [auxiliary_usage_by_task](../../hermes_state_usage.py#L427) `self, session_id: str` → `dict[str, dict[str, float]]` | 6 | `hermes_cli/oneshot.py` | `tests/agent/test_voice_turn_route.py`, `tests/hermes_state/test_runtime_worker_usage.py` |
| [usage_totals](../../hermes_state_usage.py#L456) `self, *, min_message_count: int=1, include_archived: bool=False` → `dict[str, float]` | 6 | `hermes_cli/web_routers/profiles.py` | 主题契约新增覆盖 |

## 门面外运行、Worker 与 API 函数

公开且以 db/conn 为参数的函数保留其源码返回/异常契约，按主题落位 Operation/Repository，不能继续执行 SQLite SQL。

| 源码函数 | Task |
| --- | --- |
| [is_reconnect_only](../../gateway/delivery_ledger.py#L96) | 14 |
| [is_flood_error](../../gateway/delivery_ledger.py#L101) | 14 |
| [flood_wait_seconds](../../gateway/delivery_ledger.py#L108) | 14 |
| [flood_retry_delay](../../gateway/delivery_ledger.py#L126) | 14 |
| [flood_not_before](../../gateway/delivery_ledger.py#L144) | 14 |
| [retry_not_before](../../gateway/delivery_ledger.py#L151) | 14 |
| [compute_obligation_id](../../gateway/delivery_ledger.py#L264) | 14 |
| [record_obligation](../../gateway/delivery_ledger.py#L270) | 14 |
| [record_crash_left_reply](../../gateway/delivery_ledger.py#L288) | 14 |
| [mark_attempting](../../gateway/delivery_ledger.py#L310) | 14 |
| [mark_delivered](../../gateway/delivery_ledger.py#L314) | 14 |
| [mark_failed](../../gateway/delivery_ledger.py#L318) | 14 |
| [release_runtime_claim](../../gateway/delivery_ledger.py#L322) | 14 |
| [sweep_recoverable](../../gateway/delivery_ledger.py#L368) | 14 |
| [sweep_failed_for_runtime](../../gateway/delivery_ledger.py#L449) | 14 |
| [pending_retries](../../gateway/delivery_ledger.py#L508) | 14 |
| [ledger_enabled](../../gateway/delivery_ledger.py#L555) | 14 |
| [atomically](../../gateway/platforms/api_server_response_store.py#L101) | 13 |
| [off_loop](../../gateway/platforms/api_server_response_store.py#L106) | 13 |
| [get](../../gateway/platforms/api_server_response_store.py#L125) | 13 |
| [put](../../gateway/platforms/api_server_response_store.py#L144) | 13 |
| [bind_request_key](../../gateway/platforms/api_server_response_store.py#L243) | 13 |
| [request_model](../../gateway/platforms/api_server_response_store.py#L253) | 13 |
| [output_index](../../gateway/platforms/api_server_response_store.py#L264) | 13 |
| [order_output](../../gateway/platforms/api_server_response_store.py#L279) | 13 |
| [request_created_at](../../gateway/platforms/api_server_response_store.py#L283) | 13 |
| [request_key_matches](../../gateway/platforms/api_server_response_store.py#L288) | 13 |
| [request_admission](../../gateway/platforms/api_server_response_store.py#L293) | 13 |
| [bind_request_admission](../../gateway/platforms/api_server_response_store.py#L298) | 13 |
| [forget_unadmitted_request](../../gateway/platforms/api_server_response_store.py#L306) | 13 |
| [delete](../../gateway/platforms/api_server_response_store.py#L312) | 13 |
| [get_conversation](../../gateway/platforms/api_server_response_store.py#L323) | 13 |
| [set_conversation](../../gateway/platforms/api_server_response_store.py#L329) | 13 |
| [close](../../gateway/platforms/api_server_response_store.py#L335) | 13 |
| [durable](../../gateway/platforms/api_server_run_idempotency.py#L62) | 13 |
| [reserve](../../gateway/platforms/api_server_run_idempotency.py#L133) | 13 |
| [lookup](../../gateway/platforms/api_server_run_idempotency.py#L157) | 13 |
| [status_for_run](../../gateway/platforms/api_server_run_idempotency.py#L189) | 13 |
| [extend_retention](../../gateway/platforms/api_server_run_idempotency.py#L204) | 13 |
| [owns_run](../../gateway/platforms/api_server_run_idempotency.py#L214) | 13 |
| [update_status](../../gateway/platforms/api_server_run_idempotency.py#L220) | 13 |
| [forget](../../gateway/platforms/api_server_run_idempotency.py#L227) | 13 |
| [close](../../gateway/platforms/api_server_run_idempotency.py#L233) | 13 |
| [binding_names](../../hermes_state_mutation_binding.py#L39) | 12 |
| [import_history_control](../../hermes_state_mutation_binding.py#L67) | 12 |
| [authorize_history](../../hermes_state_mutation_binding.py#L74) | 12 |
| [history_binding](../../hermes_state_mutation_binding.py#L101) | 12 |
| [same_history_owner](../../hermes_state_mutation_binding.py#L106) | 12 |
| [branch_in_transaction](../../hermes_state_mutation_branch.py#L52) | 12 |
| [chat_pick_key](../../hermes_state_mutation_chat_pick.py#L16) | 12 |
| [prepare_chat_pick](../../hermes_state_mutation_chat_pick.py#L41) | 12 |
| [commit_chat_pick](../../hermes_state_mutation_chat_pick.py#L52) | 12 |
| [compress_in_transaction](../../hermes_state_mutation_compress.py#L6) | 12 |
| [busy_refusal](../../hermes_state_mutation_guards.py#L12) | 12 |
| [require_not_executing](../../hermes_state_mutation_guards.py#L19) | 12 |
| [require_target_advanceable](../../hermes_state_mutation_guards.py#L43) | 12 |
| [require_idle](../../hermes_state_mutation_guards.py#L52) | 12 |
| [delete_targets](../../hermes_state_mutation_guards.py#L81) | 12 |
| [local_snapshot](../../hermes_state_mutation_prepared.py#L12) | 12 |
| [validate_prepared](../../hermes_state_mutation_prepared.py#L23) | 12 |
| [model_in_transaction](../../hermes_state_mutation_prepared.py#L44) | 12 |
| [reasoning_in_transaction](../../hermes_state_mutation_prepared.py#L69) | 12 |
| [workspace_in_transaction](../../hermes_state_mutation_prepared.py#L86) | 12 |
| [editor_mcp_in_transaction](../../hermes_state_mutation_prepared.py#L101) | 12 |
| [edit_policy_in_transaction](../../hermes_state_mutation_prepared.py#L107) | 12 |
| [picks_on](../../hermes_state_mutation_prepared.py#L121) | 12 |
| [policy_picks](../../hermes_state_mutation_prepared.py#L147) | 12 |
| [commit_refreshed_policy](../../hermes_state_mutation_prepared.py#L152) | 12 |
| [reset_in_transaction](../../hermes_state_mutation_reset.py#L12) | 12 |
| [retired_in](../../hermes_state_mutation_retirement.py#L19) | 12 |
| [retired_session](../../hermes_state_mutation_retirement.py#L23) | 12 |
| [create_conflict](../../hermes_state_mutation_retirement.py#L28) | 12 |
| [first_generation](../../hermes_state_mutation_retirement.py#L38) | 12 |
| [keep_passed_fences](../../hermes_state_mutation_retirement.py#L57) | 12 |
| [has_mutation_receipt](../../hermes_state_mutation_retirement.py#L73) | 12 |
| [retire_terminal_receipts](../../hermes_state_mutation_retirement.py#L100) | 12 |
| [retire_sessions](../../hermes_state_mutation_retirement.py#L148) | 12 |
| [retire_mutation_receipts](../../hermes_state_mutation_retirement.py#L176) | 12 |
| [retire_prunable](../../hermes_state_mutation_retirement.py#L236) | 12 |
| [delete_in_transaction](../../hermes_state_mutation_retirement.py#L261) | 12 |
| [entry_session_id](../../hermes_state_mutation_retirement.py#L275) | 12 |
| [retire_routes](../../hermes_state_mutation_retirement.py#L307) | 12 |
| [route_namespace](../../hermes_state_mutation_retirement.py#L320) | 12 |
| [route_fence_key](../../hermes_state_mutation_retirement.py#L327) | 12 |
| [route_retired_params](../../hermes_state_mutation_retirement.py#L358) | 12 |
| [route_retired](../../hermes_state_mutation_retirement.py#L364) | 12 |
| [expiring_retirements](../../hermes_state_mutation_retirement.py#L371) | 12 |
| [fence_shared_routes](../../hermes_state_mutation_retirement.py#L380) | 12 |
| [prune_retired_tombstones](../../hermes_state_mutation_retirement.py#L412) | 12 |
| [rewind_in_transaction](../../hermes_state_mutation_transcript.py#L5) | 12 |
| [validate_action](../../hermes_state_mutations.py#L8) | 12 |
| [apply_action](../../hermes_state_mutations.py#L89) | 12 |
| [begin_runtime_epoch](../../hermes_state_runtime.py#L116) | 8 |
| [admit_session_input](../../hermes_state_runtime.py#L130) | 8 |
| [get_session_admission](../../hermes_state_runtime.py#L180) | 8 |
| [find_session_admission](../../hermes_state_runtime.py#L187) | 8 |
| [list_session_admissions](../../hermes_state_runtime.py#L194) | 8 |
| [claim_session_input](../../hermes_state_runtime.py#L206) | 8 |
| [settle_session_input](../../hermes_state_runtime.py#L245) | 8 |
| [cancel_session_input](../../hermes_state_runtime.py#L280) | 8 |
| [steer_replayed](../../hermes_state_runtime.py#L302) | 8 |
| [steer_session_input](../../hermes_state_runtime.py#L315) | 8 |
| [settle_steer_transfers](../../hermes_state_runtime.py#L337) | 8 |
| [revert_steer_input](../../hermes_state_runtime.py#L350) | 8 |
| [replacement_binding](../../hermes_state_runtime.py#L362) | 8 |
| [retire_replaced_input](../../hermes_state_runtime.py#L368) | 8 |
| [check_replaced_input](../../hermes_state_runtime.py#L378) | 8 |
| [rehome_queued_inputs](../../hermes_state_runtime.py#L385) | 8 |
| [retarget_local_automation](../../hermes_state_runtime.py#L416) | 8 |
| [recover_session_inputs](../../hermes_state_runtime.py#L453) | 8 |
| [mutation_receipt_key](../../hermes_state_runtime.py#L467) | 8 |
| [replay_mutation_receipt](../../hermes_state_runtime.py#L478) | 8 |
| [mutate_runtime_session](../../hermes_state_runtime.py#L489) | 8 |
| [import_legacy_session_admissions](../../hermes_state_runtime.py#L611) | 8 |
| [resolve_unknown_session_input](../../hermes_state_runtime.py#L657) | 8 |
| [register_worker_execution](../../hermes_state_runtime.py#L734) | 8 |
| [adopt_worker_execution](../../hermes_state_runtime.py#L765) | 8 |
| [row_annotations](../../hermes_state_runtime.py#L821) | 8 |
| [mutate_worker_execution](../../hermes_state_runtime.py#L925) | 8 |
| [apply_worker_receipt](../../hermes_state_runtime.py#L953) | 8 |
| [runtime_lineage](../../hermes_state_runtime_workers.py#L5) | 9 |
| [worker_states](../../hermes_state_runtime_workers.py#L26) | 9 |
| [discard_orphan_workers_on_reset](../../hermes_state_runtime_workers.py#L33) | 9 |
| [retire_child_executions](../../hermes_state_runtime_workers.py#L53) | 9 |
| [descendant_range](../../hermes_state_runtime_workers.py#L62) | 9 |
| [retire_stale_children](../../hermes_state_runtime_workers.py#L68) | 9 |
| [compact_terminal_receipts](../../hermes_state_runtime_workers.py#L88) | 9 |
| [retired_receipt](../../hermes_state_runtime_workers.py#L111) | 9 |
| [worker_compression_lock](../../hermes_state_worker_compression.py#L26) | 10 |
| [worker_cooldown_record](../../hermes_state_worker_compression.py#L51) | 10 |
| [worker_cooldown_restore](../../hermes_state_worker_compression.py#L64) | 10 |
| [worker_cooldown_clear](../../hermes_state_worker_compression.py#L86) | 10 |
| [worker_compression_counter](../../hermes_state_worker_compression.py#L92) | 10 |
| [get_session](../../hermes_state_worker_compression.py#L139) | 10 |
| [authorize](../../hermes_state_worker_compression.py#L143) | 10 |
| [worker_lineage_context](../../hermes_state_worker_compression.py#L152) | 10 |
| [worker_lineage](../../hermes_state_worker_compression.py#L160) | 10 |
| [worker_boundary](../../hermes_state_worker_compression.py#L173) | 10 |
| [worker_history](../../hermes_state_worker_compression.py#L182) | 10 |
| [archive_on_connection](../../hermes_state_worker_compression.py#L208) | 10 |
| [publish_on_connection](../../hermes_state_worker_compression.py#L216) | 10 |
| [worker_watermark](../../hermes_state_worker_compression.py#L226) | 10 |
| [worker_archive](../../hermes_state_worker_compression.py#L251) | 10 |
| [worker_publish](../../hermes_state_worker_compression.py#L309) | 10 |
| [worker_receipt_assignment](../../hermes_state_worker_compression.py#L358) | 10 |
| [worker_claim_origin](../../hermes_state_worker_compression.py#L371) | 10 |
| [worker_retry_target](../../hermes_state_worker_compression.py#L380) | 10 |
| [reopen_on_connection](../../hermes_state_worker_compression.py#L395) | 10 |
| [worker_reopen](../../hermes_state_worker_compression.py#L414) | 10 |
| [worker_compression_cleanup](../../hermes_state_worker_compression.py#L419) | 10 |
| [worker_compression_append](../../hermes_state_worker_compression.py#L431) | 10 |
| [worker_turn_cleanup](../../hermes_state_worker_compression.py#L444) | 10 |
| [worker_context](../../hermes_state_worker_context.py#L16) | 9 |
| [worker_prompt](../../hermes_state_worker_context.py#L29) | 9 |
| [worker_sidecars](../../hermes_state_worker_context.py#L39) | 9 |
| [worker_tool_names](../../hermes_state_worker_context.py#L47) | 9 |
| [worker_tail_role](../../hermes_state_worker_context.py#L74) | 9 |
| [worker_row_role](../../hermes_state_worker_context.py#L83) | 9 |
| [worker_create](../../hermes_state_worker_lifecycle.py#L16) | 9 |
| [worker_end](../../hermes_state_worker_lifecycle.py#L42) | 9 |
| [worker_lifecycle](../../hermes_state_worker_lifecycle.py#L51) | 9 |
| [worker_title](../../hermes_state_worker_lifecycle.py#L62) | 9 |
| [worker_title_source](../../hermes_state_worker_lifecycle.py#L76) | 9 |
| [worker_next_title](../../hermes_state_worker_lifecycle.py#L84) | 9 |
| [worker_activity](../../hermes_state_worker_lifecycle.py#L110) | 9 |
| [worker_activity_clear](../../hermes_state_worker_lifecycle.py#L128) | 9 |
| [worker_billing_route](../../hermes_state_worker_lifecycle.py#L137) | 9 |
| [worker_api_content](../../hermes_state_worker_lifecycle.py#L148) | 9 |
| [worker_message_api_content](../../hermes_state_worker_lifecycle.py#L166) | 9 |
| [worker_user_content](../../hermes_state_worker_lifecycle.py#L177) | 9 |
| [insert_session_row_in_transaction](../../hermes_state_worker_lifecycle.py#L208) | 9 |

## 生产入口与消费归属

以下覆盖显式 import 的实际文件；工具/插件/cron/ACP 的主库调用同样纳入 Task 17，独立 SQLite 不因此迁移。模块内部的 _conn 不是外部消费者，不出现在此表。

| 消费者 | 实际依赖 | 接入/直接连接归属 |
| --- | --- | --- |
| `acp_adapter/catalog.py` | `hermes_state: SessionDB`<br>`hermes_state_local: POLICY_PREFIX` | 17 |
| `acp_adapter/gateway_session_meta.py` | `hermes_state: SessionDB` | 17 |
| `acp_adapter/session.py` | `hermes_state_registry: acquire` | 16/17；直接 db_path |
| `agent/agent_init.py` | `hermes_state_ids: new_session_id` | 17 |
| `agent/agent_runtime_helpers.py` | `hermes_state: SessionDB` | 17 |
| `agent/context_compressor_prune.py` | `hermes_state_errors: HeldRowRewrittenError`<br>`hermes_state_errors: PruneRowStaleError, PruneRowUnresolvedError` | 17 |
| `agent/conversation_compression.py` | `hermes_state: SessionDB`<br>`hermes_state_common: is_automatic_end_reason`<br>`hermes_state_ids: new_session_id`<br>`hermes_state_pidns: holder_namespace_token` | 17 |
| `agent/error_surface.py` | `hermes_state_errors: is_disk_full_error` | 17 |
| `agent/inline_tool_executors.py` | `hermes_state: format_session_db_unavailable` | 17 |
| `agent/micro_compaction.py` | `hermes_state_errors: HeldRowRewrittenError` | 17 |
| `agent/prompt_refresh.py` | `hermes_state_sessions: _parse_model_config` | 17 |
| `agent/runtime_session_child.py` | `hermes_state_worker_lifecycle: _CONSTRUCTOR_CONFIG` | 17 |
| `agent/runtime_session_compression.py` | `hermes_state_runtime: HANDOFF_MESSAGE_FIELDS` | 17 |
| `agent/runtime_session_store.py` | `hermes_state_compression: SessionCompressionMixin`<br>`hermes_state_sessions: _parse_model_config` | 17 |
| `agent/session_persistence.py` | `hermes_state: StateDbCorruptError, StateDbReplacedError, classify_persistence_error, divert_session_transcript_jsonl`<br>`hermes_state_errors: CompressionSessionClosedError`<br>`hermes_state_errors: PruneRowUnresolvedError, SessionTurnLeaseLostError` | 17 |
| `agent/title_generator.py` | `hermes_state: SessionDB` | 17 |
| `agent/tool_executor.py` | `hermes_state: classify_persistence_error` | 17 |
| `agent/trace_upload.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `agent/transcript_repair.py` | `hermes_state_common: _id_chunks, _placeholders`<br>`hermes_state_identity: _fill_missing_tool_call_uids, _restore_row_identity`<br>`hermes_state_messages: _MESSAGE_WRITE_COLUMNS, SessionMessagesMixin` | 17 |
| `agent/turn_explainers.py` | `hermes_state: _default_db_path`<br>`hermes_state_errors: STORAGE_RECOVERY_DOCS_URL` | 17 |
| `agent/turn_facade_lease.py` | `hermes_state_errors: is_sqlite_lock_error`<br>`hermes_state_pidns: holder_namespace_token` | 17 |
| `agent/turn_tool_round.py` | `hermes_state: classify_persistence_error` | 17 |
| `cron/scheduler.py` | `hermes_state_errors: PERSISTENCE_ERROR_CAUSES`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 16/17；直接 db_path |
| `cron/scheduler_delivery.py` | `gateway.delivery_ledger: compute_obligation_id, is_reconnect_only, ledger_enabled, mark_failed, record_obligation` | 14/17 |
| `cron/scheduler_detached_worker.py` | `hermes_state_registry: release_or_close` | 17 |
| `evals/api_delegation_http_probe.py` | `hermes_state: SessionDB` | 17 |
| `evals/api_delegation_sync_probe.py` | `hermes_state: SessionDB` | 17 |
| `evals/codex_echo/probe.py` | `hermes_state: SessionDB` | 17 |
| `evals/core_tool_deferral/worker.py` | `hermes_state: SessionDB` | 17 |
| `evals/desktop_bug_campaign/async-report-producer.py` | `hermes_state: SessionDB` | 17 |
| `evals/desktop_bug_campaign/history_live.py` | `hermes_state: SessionDB` | 17 |
| `evals/desktop_bug_campaign/markdown-producer.py` | `hermes_state: SessionDB` | 17 |
| `evals/fanout_resource_bench.py` | `hermes_state: SessionDB` | 17 |
| `evals/gateway_failure_ownership/foreign_writer.py` | `hermes_state: SessionDB` | 17 |
| `evals/gateway_failure_ownership/probe.py` | `hermes_state: SessionDB` | 17 |
| `evals/hosted_attachment_transfer/bench.py` | `hermes_state_runtime: list_session_admissions` | 16/17；直接 db_path |
| `evals/native_compaction/ab_checkpoint_preflight.py` | `hermes_state: SessionDB` | 17 |
| `evals/postmortem/review_probes/context_cap_probe.py` | `hermes_state: SessionDB` | 17 |
| `evals/prefix_rediet/worker.py` | `hermes_state: SessionDB` | 17 |
| `evals/provider_wire/issue_104359.py` | `hermes_state: SessionDB` | 17 |
| `evals/session_search_schema/fixtures.py` | `hermes_state: SessionDB` | 16/17；直接 _conn |
| `evals/session_search_schema/runner.py` | `hermes_state: SessionDB` | 17 |
| `evals/session_snapshot_removal.py` | `hermes_state: SessionDB` | 17 |
| `evals/shared_gateway/search_readonly_ab.py` | `hermes_state: SessionDB` | 17 |
| `evals/token_accounting/replay_gates.py` | `hermes_state: SessionDB` | 17 |
| `gateway/channel_directory.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `gateway/hosted_room_attachments.py` | `hermes_state_wal: apply_wal_with_fallback` | 16/17；直接 db_path |
| `gateway/hosted_rooms_gateway_import.py` | `hermes_state_runtime: RuntimeStoreError, _epoch` | 16/17；直接 db_path |
| `gateway/lifecycle_ledger.py` | `hermes_state_wal: _on_disk_journal_mode` | 17 |
| `gateway/mirror.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `gateway/owner_identity.py` | `hermes_state_mutation_binding: _login_label` | 17 |
| `gateway/parked_route_refusal.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/platforms/api_server.py` | `gateway.platforms.api_server_response_store: ResponseStore`<br>`gateway.platforms.api_server_run_idempotency: RunIdempotencyStore`<br>`hermes_state_errors: SessionActiveWriteGuardError`<br>`hermes_state_mutation_retirement: create_conflict`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 13/17；直接 db_path |
| `gateway/platforms/api_server_authority_runs.py` | `hermes_state_runtime: RuntimeStoreError, _row` | 13/17 |
| `gateway/platforms/api_server_bot_chat.py` | `hermes_state_local: local_receipt`<br>`hermes_state_local_migration: validate_legacy_row`<br>`hermes_state_runtime: RuntimeStoreError` | 13/17；直接 db_path |
| `gateway/platforms/api_server_memory_sessions.py` | `hermes_state_mutation_retirement: RETRY_HORIZON_S` | 13/17 |
| `gateway/platforms/api_server_openai_routes.py` | `hermes_state_runtime: RuntimeStoreError` | 13/17 |
| `gateway/platforms/api_server_response_admissions.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: get_session_admission, _row`<br>`hermes_state_terminal: terminal_api_admissions` | 13/17 |
| `gateway/platforms/api_server_response_store.py` | `hermes_state_holders: read_only_db_uri`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_terminal: ADMISSION_PREFIX`<br>`hermes_state_wal: apply_wal_with_fallback` | 13/17；直接 _conn |
| `gateway/platforms/api_server_run_idempotency.py` | `hermes_state_wal: apply_wal_with_fallback` | 13/17；直接 _conn |
| `gateway/platforms/api_server_runs.py` | `gateway.platforms.api_server_run_idempotency: TERMINAL_STATUSES`<br>`hermes_state_runtime: RuntimeStoreError` | 13/17 |
| `gateway/platforms/base.py` | `gateway.delivery_ledger: compute_obligation_id, ledger_enabled, mark_attempting, record_obligation`<br>`gateway.delivery_ledger: is_reconnect_only, mark_delivered, mark_failed` | 17 |
| `gateway/platforms/msgraph_webhook.py` | `hermes_state_runtime: admit_session_input, RuntimeStoreError` | 17 |
| `gateway/platforms/webhook.py` | `hermes_state_runtime: get_session_admission` | 17 |
| `gateway/platforms/webhook_delivery.py` | `hermes_state_runtime: RuntimeStoreError` | 14/17 |
| `gateway/platforms/webhook_ingress.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: RuntimeStoreError, get_session_admission`<br>`hermes_state_runtime: get_session_admission` | 17 |
| `gateway/plugin_keyless_inject.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/readiness.py` | `hermes_state_health: STORAGE_CORRUPT, note_storage_error, storage_state` | 17 |
| `gateway/relay/inbound_admission.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/run.py` | `hermes_state: AsyncSessionDB, _default_db_path`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: acquire, release_or_close`<br>`hermes_state_registry: borrow_live_shared_session_dbs`<br>`hermes_state_registry: release_or_close` | 17 |
| `gateway/run_bootstrap.py` | `hermes_state_reconcile: BROWSE_RECONCILE_BUDGET_S` | 17 |
| `gateway/run_heartbeat_acceptance.py` | `hermes_state_runtime: list_session_admissions` | 17 |
| `gateway/run_housekeeping_disk.py` | `hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/run_inbound.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: RuntimeStoreError, list_session_admissions` | 17 |
| `gateway/run_notifications.py` | `hermes_state: _default_db_path, classify_persistence_error`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_user_copy: describe_storage_failure` | 17 |
| `gateway/run_notifications_ownership.py` | `hermes_state_errors: StateDbReplacedError` | 17 |
| `gateway/run_plugin_injection.py` | `hermes_state_keys: profile_from_session_key`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/run_profile_reconcile.py` | `hermes_state_registry: acquire, release_or_close`<br>`hermes_state_registry: close_all_under` | 17 |
| `gateway/run_runtime.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release`<br>`hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/run_shutdown.py` | `hermes_state_registry: close_all` | 17 |
| `gateway/run_startup.py` | `gateway.delivery_ledger: RECOVERED_MARKER, mark_delivered, mark_failed`<br>`gateway.delivery_ledger: compute_obligation_id, ledger_enabled, record_crash_left_reply`<br>`gateway.delivery_ledger: flood_retry_delay, pending_retries`<br>`gateway.delivery_ledger: is_flood_error`<br>`gateway.delivery_ledger: ledger_enabled, sweep_failed_for_runtime`<br>`gateway.delivery_ledger: ledger_enabled, sweep_recoverable`<br>`gateway.delivery_ledger: pending_retries`<br>`gateway.delivery_ledger: release_runtime_claim` | 17 |
| `gateway/run_topics.py` | `hermes_state: format_session_db_unavailable` | 17 |
| `gateway/run_turn_persistence.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/run_turn_runner.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/runtime_ownership.py` | `hermes_state_reconcile: BROWSE_RECONCILE_PURPOSE` | 17 |
| `gateway/session.py` | `hermes_state_keys: profile_from_session_key_namespace` | 17 |
| `gateway/session_a2a.py` | `hermes_state_local: commit_local_session, local_receipt`<br>`hermes_state_local: local_receipt`<br>`hermes_state_local_migration: LEGACY_PREFIX`<br>`hermes_state_mutation_retirement: first_generation`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_terminal: identity_key` | 17 |
| `gateway/session_acp_lifecycle.py` | `hermes_state_local: POLICY_PREFIX, end_idle_local_session, local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_active_list.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 17 |
| `gateway/session_admission.py` | `hermes_state_keys: admission_fingerprint` | 17 |
| `gateway/session_ancillary.py` | `hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_api.py` | `hermes_state_local: API_BINDING_PREFIX, API_DECLARED_PREFIX`<br>`hermes_state_mutation_retirement: RETIRED_PREFIX, keep_passed_fences`<br>`hermes_state_mutation_retirement: first_generation`<br>`hermes_state_runtime: RuntimeStoreError, _epoch, _json`<br>`hermes_state_terminal: identity_key` | 17 |
| `gateway/session_api_media.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: _json` | 17 |
| `gateway/session_api_turn.py` | `hermes_state_runtime: RuntimeStoreError, admit_session_input, _json`<br>`hermes_state_runtime: get_session_admission`<br>`hermes_state_runtime: list_session_admissions`<br>`hermes_state_terminal: retry_terminal_admission`<br>`hermes_state_terminal: terminal_api_admissions` | 17 |
| `gateway/session_authorities.py` | `hermes_state_local: local_lineage_owner`<br>`hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_authority.py` | `hermes_state_local: POLICY_PREFIX`<br>`hermes_state_local_migration: LEGACY_PREFIX`<br>`hermes_state_media: collect_retired_media, retire_media`<br>`hermes_state_runtime: STEERING, RuntimeStoreError, admit_session_input, begin_runtime_epoch, cancel_session_input, claim_session_input, get_session_admission, list_session_admissions, recover_session_inputs, resolve_unknown_session_input`<br>`hermes_state_runtime: find_session_admission` | 16/17；直接 db_path |
| `gateway/session_automation.py` | `hermes_state_runtime: RuntimeStoreError, admit_session_input, list_session_admissions`<br>`hermes_state_runtime: find_session_admission`<br>`hermes_state_runtime: get_session_admission`<br>`hermes_state_runtime: list_session_admissions`<br>`hermes_state_runtime: rehome_queued_inputs`<br>`hermes_state_runtime: retarget_local_automation` | 17 |
| `gateway/session_bot.py` | `hermes_state_local: POLICY_PREFIX`<br>`hermes_state_local: commit_local_session`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES, legacy_account_label, validate_legacy_row`<br>`hermes_state_local_migration: LEGACY_PREFIX`<br>`hermes_state_mutation_retirement: RETIRED_PREFIX`<br>`hermes_state_mutation_retirement: first_generation`<br>`hermes_state_mutation_retirement: retired_session`<br>`hermes_state_runtime: RuntimeStoreError, get_session_admission` | 16/17；直接 db_path |
| `gateway/session_bot_cancel.py` | `hermes_state_runtime: RuntimeStoreError, get_session_admission` | 17 |
| `gateway/session_bot_mailbox.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_busy_controls.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_clarify_lock.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_cli_turn.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_commands.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_complete_path.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_config.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_connections.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_control_actions.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_controls.py` | `hermes_state_local: commit_local_session`<br>`hermes_state_local: local_receipt`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES`<br>`hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS, busy_refusal`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: get_session_admission`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 17 |
| `gateway/session_cron.py` | `hermes_state_keys: CRON_PRINCIPAL_ID, cron_request_id`<br>`hermes_state_local: commit_local_session`<br>`hermes_state_runtime: RuntimeStoreError, admit_session_input, get_session_admission`<br>`hermes_state_runtime: list_session_admissions` | 16/17；直接 db_path |
| `gateway/session_deferred_pick.py` | `hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS`<br>`hermes_state_mutation_prepared: DEFERRED_PICK_PREFIX`<br>`hermes_state_mutation_retirement: has_mutation_receipt`<br>`hermes_state_mutations: validate_action`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: _epoch, _json, mutation_receipt_key, replay_mutation_receipt`<br>`hermes_state_runtime: _json` | 17 |
| `gateway/session_detached.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: list_session_admissions` | 17 |
| `gateway/session_discovery.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_display.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_envelope.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: list_session_admissions` | 17 |
| `gateway/session_finite.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_group_controls.py` | `hermes_state_local_migration: LEGACY_PREFIX`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 16/17；直接 db_path |
| `gateway/session_history_mount.py` | `hermes_state_local: API_BINDING_PREFIX`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES`<br>`hermes_state_mutation_binding: binding_names, history_binding`<br>`hermes_state_mutation_guards: delete_targets`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_hosted_attachments.py` | `hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_hosted_controls.py` | `hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_hosted_members.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_hosted_rpc.py` | `hermes_state_local: commit_local_session`<br>`hermes_state_runtime: RuntimeStoreError, list_session_admissions`<br>`hermes_state_runtime: _epoch` | 17 |
| `gateway/session_hosted_service.py` | `hermes_state_runtime: RuntimeStoreError, _epoch` | 16/17；直接 db_path |
| `gateway/session_hosted_transport.py` | `hermes_state_runtime: RuntimeStoreError, _epoch` | 16/17；直接 db_path |
| `gateway/session_images.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_ingress.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: get_session_admission` | 17 |
| `gateway/session_ingress_context.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_ingress_media.py` | `hermes_state_runtime: ADMITTED_REQUEST_CONFLICT, RuntimeStoreError`<br>`hermes_state_runtime: get_session_admission` | 16/17；直接 db_path |
| `gateway/session_kanban.py` | `hermes_state_keys: profile_from_session_key`<br>`hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: find_session_admission` | 16/17；直接 db_path |
| `gateway/session_lifecycle.py` | `hermes_state_ids: new_session_id`<br>`hermes_state_local: API_BINDING_PREFIX`<br>`hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_listing.py` | `hermes_state_local: local_receipt`<br>`hermes_state_local_migration: client_history_row, validate_legacy_row`<br>`hermes_state_mutation_binding: authorize_history`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: list_session_admissions`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 17 |
| `gateway/session_live_listing.py` | `hermes_state_local: POLICY_PREFIX`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_llm_oneshot.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_local.py` | `hermes_state_local: commit_local_session`<br>`hermes_state_local: local_receipt`<br>`hermes_state_local: same_create_retry`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: list_session_admissions` | 17 |
| `gateway/session_local_adoption.py` | `hermes_state_local_lineage: adopt_untracked_compression`<br>`hermes_state_local_lineage: adoptable_compression`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_local_close.py` | `hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_local_editor.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_local_mcp.py` | `hermes_state_keys: local_identity`<br>`hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_local_migration.py` | `hermes_state_gateway: SessionGatewayMixin`<br>`hermes_state_local: POLICY_PREFIX`<br>`hermes_state_local: commit_local_session`<br>`hermes_state_local: local_conversation_ids`<br>`hermes_state_local: local_lineage_owner`<br>`hermes_state_local_migration: LEGACY_PREFIX`<br>`hermes_state_local_migration: client_history_row, validate_legacy_row`<br>`hermes_state_local_migration: legacy_creation_source, validate_legacy_row`<br>`hermes_state_mutation_binding: BINDING_PREFIX, _owner_user`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_sessions: _parse_model_config` | 16/17；直接 db_path |
| `gateway/session_local_recovery.py` | `hermes_state: SessionResumeTooLargeError`<br>`hermes_state_keys: local_identity`<br>`hermes_state_local: POLICY_PREFIX, local_receipt`<br>`hermes_state_local: hand_off_conversations, moved_receipts`<br>`hermes_state_local_lineage: adopt_untracked_compression, adoptable_compression`<br>`hermes_state_local_lineage: reset_local_target`<br>`hermes_state_local_lineage: validate_local_lineage`<br>`hermes_state_runtime: RuntimeStoreError, list_session_admissions`<br>`hermes_state_runtime: _epoch` | 16/17；直接 db_path |
| `gateway/session_local_title.py` | `hermes_state: SessionDB`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_managed_worker.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_messaging_picks.py` | `hermes_state_mutation_chat_pick: chat_pick_key, commit_chat_pick, prepare_chat_pick`<br>`hermes_state_mutations: validate_action`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_mutation_compress.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_mutation_model.py` | `hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_mutation_policy.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_mutations.py` | `hermes_state_local: local_lineage_owner`<br>`hermes_state_local: local_receipt`<br>`hermes_state_media: collect_retired_media`<br>`hermes_state_mutation_binding: authorize_history`<br>`hermes_state_mutation_binding: authorize_history, import_history_control`<br>`hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS`<br>`hermes_state_mutation_retirement: expiring_retirements`<br>`hermes_state_mutation_retirement: has_mutation_receipt`<br>`hermes_state_mutations: validate_action`<br>`hermes_state_runtime: RuntimeStoreError, mutate_runtime_session` | 16/17；直接 db_path |
| `gateway/session_onboarding.py` | `hermes_state_local: commit_local_session`<br>`hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_operator.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_pending_controls.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_persistence.py` | `hermes_state: _default_db_path`<br>`hermes_state_mutation_retirement: route_retired`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `gateway/session_policy.py` | `hermes_state_local: local_receipt`<br>`hermes_state_local: same_create_retry`<br>`hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_policy_credentials.py` | `hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_policy_refresh.py` | `hermes_state_local: local_receipt`<br>`hermes_state_mutation_prepared: commit_refreshed_policy`<br>`hermes_state_mutation_prepared: policy_picks`<br>`hermes_state_runtime: RuntimeStoreError` | 16/17；直接 db_path |
| `gateway/session_prune.py` | `hermes_state_maintenance: _PRUNE_FILTER_NAMES`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_queued_controls.py` | `hermes_state_runtime: STEERING, RuntimeStoreError, check_replaced_input, find_session_admission, get_session_admission, replacement_binding, retire_replaced_input, revert_steer_input, steer_replayed, steer_session_input` | 17 |
| `gateway/session_reactions.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_readiness.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_recovery.py` | `hermes_state_keys: profile_from_session_key` | 17 |
| `gateway/session_results.py` | `hermes_state_local_lineage: local_physical_target`<br>`hermes_state_runtime: RuntimeStoreError, _admission, _epoch, settle_session_input`<br>`hermes_state_runtime: _canonical_chain`<br>`hermes_state_terminal: RESULT_PREFIX, load_result`<br>`hermes_state_terminal: compact_result` | 17 |
| `gateway/session_retirement.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_retry_admission.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_route_recovery.py` | `hermes_state_local: handoff_head`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES, client_label` | 17 |
| `gateway/session_server_requests.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_setting_commands.py` | `hermes_state_local: local_receipt`<br>`hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_settlement_recovery.py` | `hermes_state_runtime: RuntimeStoreError, _admission, _epoch, get_session_admission, settle_steer_transfers` | 17 |
| `gateway/session_shell.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_surface.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_transcript.py` | `hermes_state: SessionDB`<br>`hermes_state: StateDbCorruptError, StateDbReplacedError`<br>`hermes_state: divert_session_transcript_jsonl`<br>`hermes_state_errors: CompressionSessionClosedError`<br>`hermes_state_rewind: RewindTargetUnavailableError` | 17 |
| `gateway/session_tui_config.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_tui_ops.py` | `hermes_state: SessionExportTooLargeError`<br>`hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_tui_reads.py` | `hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_tui_side.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_unattended_unknown.py` | `hermes_state_keys: CRON_PRINCIPAL_ID`<br>`hermes_state_runtime: RuntimeStoreError, _row, resolve_unknown_session_input`<br>`hermes_state_runtime: RuntimeStoreError, list_session_admissions` | 17 |
| `gateway/session_usage.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_viewer_automation.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `gateway/session_viewer_close.py` | `hermes_state_common: _sql_session_last_active`<br>`hermes_state_local: local_receipt`<br>`hermes_state_mutation_retirement: VIEWER_CLOSE_PREFIX`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: _epoch`<br>`hermes_state_runtime: list_session_admissions` | 16/17；直接 db_path |
| `gateway/session_worker.py` | `hermes_state_runtime: RuntimeStoreError, _secret_digest, adopt_worker_execution, mutate_worker_execution, register_worker_execution`<br>`hermes_state_worker_compression: worker_claim_origin`<br>`hermes_state_worker_compression: worker_retry_target` | 17 |
| `gateway/session_worker_child.py` | `hermes_state_ids: new_session_id`<br>`hermes_state_keys: admission_fingerprint`<br>`hermes_state_runtime: RuntimeStoreError, apply_worker_receipt`<br>`hermes_state_runtime: _secret_digest`<br>`hermes_state_runtime_workers: CHILD_SEPARATOR, descendant_range`<br>`hermes_state_worker_lifecycle: insert_session_row_in_transaction` | 17 |
| `gateway/session_worker_delegation.py` | `hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: apply_worker_receipt` | 17 |
| `gateway/session_worker_reservation.py` | `hermes_state_local_lineage: local_physical_target`<br>`hermes_state_runtime: RuntimeStoreError, _admission, _epoch, _secret_digest, _session`<br>`hermes_state_runtime_workers: compact_terminal_receipts` | 17 |
| `gateway/shutdown_flush.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `gateway/slash_commands.py` | `hermes_state: format_session_db_unavailable` | 17 |
| `gateway/slash_commands_session.py` | `hermes_state: SessionDB`<br>`hermes_state: SessionExportTooLargeError`<br>`hermes_state_mutation_transcript: rewind_in_transaction`<br>`hermes_state_rewind: RewindTargetUnavailableError`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: RuntimeStoreError, list_session_admissions` | 17 |
| `gateway/slash_commands_status.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `gateway/status_inline_source.py` | `hermes_state_holders: _PYTHON_LONG_OPTIONS_WITH_OPERANDS, _PYTHON_SHORT_OPTIONS_WITH_OPERANDS` | 17 |
| `gateway/wake.py` | `hermes_state: SessionDB`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `hermes_cli/backup.py` | `hermes_state_dbfile: RETIRED_GENERATION_DIR_SUFFIX`<br>`hermes_state_holders: read_only_db_uri` | 17 |
| `hermes_cli/backup_restore.py` | `hermes_state_holders: read_only_db_uri` | 17 |
| `hermes_cli/cli_agent_setup_mixin.py` | `hermes_state: SessionResumeTooLargeError`<br>`hermes_state_ids: new_session_id` | 17 |
| `hermes_cli/cli_commands_mixin.py` | `hermes_state: format_session_db_unavailable`<br>`hermes_state_ids: new_session_id`<br>`hermes_state_registry: acquire` | 17 |
| `hermes_cli/cli_init_mixin.py` | `hermes_state_ids: new_session_id`<br>`hermes_state_user_copy: describe_storage_failure, storage_failure_details` | 17 |
| `hermes_cli/cli_loops_mixin.py` | `hermes_state: SessionDB`<br>`hermes_state: format_session_db_unavailable` | 17 |
| `hermes_cli/cli_model_switch_mixin.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/cli_session_mixin.py` | `hermes_state: SessionDB`<br>`hermes_state: SessionExportTooLargeError`<br>`hermes_state_ids: new_session_id`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 17 |
| `hermes_cli/cli_snapshot.py` | `hermes_state_registry: close_all_under` | 17 |
| `hermes_cli/console_engine.py` | `hermes_state: DEFAULT_DB_PATH`<br>`hermes_state: SessionDB`<br>`hermes_state: SessionExportTooLargeError`<br>`hermes_state_holders: held_store_refusal`<br>`hermes_state_repair: _db_opens_cleanly, repair_state_db_schema`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 16/17；直接 db_path |
| `hermes_cli/doctor_platform.py` | `hermes_state_holders: describe_holder_pid, foreign_state_db_holders`<br>`hermes_state_wal: _path_on_cross_vm_fs, _wal_reset_repair_hint, is_sqlite_wal_reset_vulnerable, resolve_journal_mode`<br>`hermes_state_wal: is_sqlite_wal_reset_vulnerable, sqlite_source_id` | 17 |
| `hermes_cli/doctor_state.py` | `hermes_state: is_malformed_db_error`<br>`hermes_state_dbfile: collect_state_db_stats, count_db_holders`<br>`hermes_state_dbfile: iter_deleted_sqlite_sidecar_holders`<br>`hermes_state_holders: describe_holder_pid`<br>`hermes_state_holders: read_only_db_uri`<br>`hermes_state_repair: _db_opens_cleanly, _live_writer_holds_db`<br>`hermes_state_repair: _exclusive_repair_db_guard, _live_writer_holds_db`<br>`hermes_state_repair: repair_state_db_schema`<br>`hermes_state_repair: state_db_has_structural_damage` | 17 |
| `hermes_cli/foreign_sessions.py` | `hermes_state_ids: new_session_id` | 17 |
| `hermes_cli/gateway_session_store.py` | `hermes_state: SessionDB`<br>`hermes_state_rewind: _HISTORY_CHANGED, RewindOutcome, RewindTargetUnavailableError, _comparison_content, _user_indices` | 17 |
| `hermes_cli/goals.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `hermes_cli/kanban_db_connect.py` | `hermes_state: preflight_db_writability`<br>`hermes_state_wal: apply_wal_with_fallback` | 16/17；直接 db_path |
| `hermes_cli/kanban_db_dispatch.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `hermes_cli/main.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/main_agent_cmds.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/main_resume_args.py` | `hermes_state_local: local_receipt`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `hermes_cli/main_tui_launch.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/oneshot.py` | `hermes_state_registry: acquire` | 17 |
| `hermes_cli/profile_identity.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `hermes_cli/profiles.py` | `hermes_state_registry: close_all_under` | 17 |
| `hermes_cli/prune_advisor.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/session_export.py` | `hermes_state_portability: _export_timings` | 17 |
| `hermes_cli/session_lost_and_found.py` | `hermes_state_ids: is_known_session_id` | 17 |
| `hermes_cli/session_recovery.py` | `gateway.delivery_ledger: _initialize_schema`<br>`hermes_state: SessionDB`<br>`hermes_state_common: FTS_STORAGE_VERSION, SCHEMA_VERSION`<br>`hermes_state_repair: _db_opens_cleanly` | 17 |
| `hermes_cli/sessions_adopt.py` | `hermes_state: SessionDB`<br>`hermes_state_errors: is_sqlite_lock_error`<br>`hermes_state_local: POLICY_PREFIX`<br>`hermes_state_local_migration: LEGACY_LOCAL_SOURCES, LEGACY_PREFIX, not_client_labels, validate_legacy_row`<br>`hermes_state_repair: _schema_not_built`<br>`hermes_state_runtime: RuntimeStoreError` | 17 |
| `hermes_cli/sessions_cmd.py` | `hermes_state: DEFAULT_DB_PATH, SessionDB`<br>`hermes_state: SessionDB`<br>`hermes_state: SessionExportTooLargeError, resolved_max_export_messages`<br>`hermes_state_errors: SessionActiveWriteGuardError`<br>`hermes_state_holders: held_store_refusal`<br>`hermes_state_reconcile: repair_declarative_schema, schema_drift_reason`<br>`hermes_state_repair: _db_opens_cleanly, repair_state_db_schema`<br>`hermes_state_repair: _schema_not_built`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_sessions: workspace_key` | 16/17；直接 _conn, db_path |
| `hermes_cli/sessions_cmd_browse.py` | `hermes_state_errors: SessionActiveWriteGuardError` | 17 |
| `hermes_cli/sessions_cmd_journal_mode.py` | `hermes_state: _default_db_path`<br>`hermes_state_holders: describe_holder_pid, foreign_state_db_holders`<br>`hermes_state_wal: _path_on_cross_vm_fs, _set_journal_mode_no_wait, is_sqlite_wal_reset_vulnerable, resolve_journal_mode` | 17 |
| `hermes_cli/sessions_repair_profiles.py` | `hermes_state: SessionDB`<br>`hermes_state_profile_repair: SessionLedgeredError`<br>`hermes_state_profile_repair: session_key_profile`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 16/17；直接 db_path |
| `hermes_cli/sqlite_util.py` | `hermes_state_wal: apply_wal_with_fallback` | 17 |
| `hermes_cli/status.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/terminal_breadcrumbs.py` | `hermes_state: SessionDB` | 17 |
| `hermes_cli/update_cmd_maint.py` | `hermes_state: SessionDB`<br>`hermes_state_fts: fts_layout_drift` | 16/17；直接 _conn |
| `hermes_cli/update_downgrade_guard.py` | `hermes_state_holders: read_only_db_uri` | 17 |
| `hermes_cli/web_routers/_common.py` | `hermes_state_errors: StateDbReplacedError, classify_persistence_error, is_malformed_db_error`<br>`hermes_state_errors: classify_persistence_error` | 17 |
| `hermes_cli/web_routers/cron.py` | `hermes_state_keys: legacy_cron_run_job` | 17 |
| `hermes_cli/web_routers/profiles.py` | `hermes_state_health: STORAGE_CORRUPT, note_storage_error, storage_state` | 17 |
| `hermes_cli/web_routers/sessions.py` | `hermes_state: SessionDB`<br>`hermes_state: _default_db_path`<br>`hermes_state: is_malformed_db_error`<br>`hermes_state_errors: SessionActiveWriteGuardError, StateDbReplacedError, is_transient_sqlite_error`<br>`hermes_state_health: STORAGE_CORRUPT, note_storage_error, storage_state`<br>`hermes_state_timeline: get_session_messages_around`<br>`hermes_state_timeline: get_session_timeline` | 16/17；直接 db_path |
| `hermes_cli/web_routers/status.py` | `hermes_state: SessionDB`<br>`hermes_state: _default_db_path` | 17 |
| `hermes_cli/web_server_lifecycle.py` | `hermes_state_registry: release_or_close` | 17 |
| `hermes_cli/web_server_sessions.py` | `hermes_state: SessionDB`<br>`hermes_state: _default_db_path`<br>`hermes_state_common: _RESET_CHILD_SQL, _sql_json_extract`<br>`hermes_state_errors: is_malformed_db_error`<br>`hermes_state_errors: is_transient_sqlite_error`<br>`hermes_state_mutation_binding: import_history_control`<br>`hermes_state_mutation_guards: MUTATION_GUARD_REFUSALS`<br>`hermes_state_reconcile: DeclarativeDriftError, is_declarative_drift_error, reconcile_drift_for_browse`<br>`hermes_state_registry: acquire`<br>`hermes_state_runtime: RuntimeStoreError`<br>`hermes_state_runtime: begin_runtime_epoch, mutate_runtime_session`<br>`hermes_state_schema: schema_read_probe_statements` | 16/17；直接 db_path |
| `plugins/hermes-achievements/dashboard/plugin_api.py` | `hermes_state: SessionDB` | 17 |
| `plugins/hermes-achievements/tests/test_achievement_engine.py` | `hermes_state: SessionDB` | 17 |
| `plugins/platforms/discord/recovery.py` | `hermes_state_wal: apply_wal_with_fallback` | 17 |
| `run_agent.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `tools/async_delegation.py` | `hermes_state: _secure_state_db_files`<br>`hermes_state_repair: apply_durability_barriers`<br>`hermes_state_schema: reconcile_state_schema` | 17 |
| `tools/bot_live_delivery.py` | `hermes_state: SessionDB` | 14/17 |
| `tools/cronjob_tools.py` | `hermes_state: SessionDB` | 17 |
| `tools/delegate_tool.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `tools/kanban_tools.py` | `hermes_state: SessionDB`<br>`hermes_state_registry: acquire, release_or_close` | 17 |
| `tools/mcp_tool_registration.py` | `hermes_state_runtime: RuntimeStoreError` | 17 |
| `tools/process_registry_results.py` | `hermes_state: SessionDB` | 17 |
| `tools/react_to_message_tool.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `tools/session_search_tool.py` | `hermes_state: SessionDB`<br>`hermes_state: SessionDB, format_session_db_unavailable`<br>`hermes_state: _default_db_path`<br>`hermes_state_common: _BOUNDARY_END_REASONS`<br>`hermes_state_registry: release_or_close` | 16/17；直接 _conn |
| `tui_gateway/agent_callbacks.py` | `hermes_state_registry: acquire, release_or_close` | 17 |
| `tui_gateway/agent_factory.py` | `hermes_state: SessionDB` | 17 |
| `tui_gateway/change_watcher.py` | `hermes_state: _connect_tracked_db`<br>`hermes_state_holders: read_only_db_uri` | 17 |
| `tui_gateway/compute_host.py` | `hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |
| `tui_gateway/methods_groups.py` | `gateway.platforms.api_server_run_idempotency: RunIdempotencyStore` | 16/17；直接 db_path |
| `tui_gateway/methods_profiles.py` | `hermes_state: SessionDB`<br>`hermes_state_registry: acquire` | 16/17；直接 _conn |
| `tui_gateway/methods_prompt.py` | `hermes_state_user_copy: describe_storage_failure`<br>`hermes_state_user_copy: storage_failure_details` | 17 |
| `tui_gateway/methods_session.py` | `hermes_state: SessionDB`<br>`hermes_state: SessionExportTooLargeError`<br>`hermes_state: SessionResumeTooLargeError, resolved_max_resume_messages`<br>`hermes_state_errors: SessionActiveWriteGuardError`<br>`hermes_state_errors: is_disk_full_error`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close`<br>`hermes_state_sessions: INTERNAL_LISTING_SOURCES` | 16/17；直接 db_path |
| `tui_gateway/server.py` | `hermes_state: _BARE_BILLING_PROVIDERS`<br>`hermes_state_ids: new_session_id`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: acquire, release_or_close`<br>`hermes_state_user_copy: describe_storage_failure, storage_failure_details` | 17 |
| `tui_gateway/session_auto_continue.py` | `hermes_state_common: QUEUED_PROMPT_METADATA_KEY` | 17 |
| `tui_gateway/session_lifecycle.py` | `hermes_state_local: local_lineage_owner` | 17 |
| `tui_gateway/session_registry.py` | `hermes_state: SessionResumeTooLargeError` | 17 |
| `tui_gateway/session_workdir.py` | `hermes_state_errors: is_disk_full_error`<br>`hermes_state_registry: acquire`<br>`hermes_state_registry: release_or_close` | 17 |

## 本地专属与间接入口复核

- hermes_state_dbfile/readpool/wal/holders/guard/repair/schema/fts/profile_repair 与 registry 的文件代次、PRAGMA、WAL、inode、FTS 布局修复属于 SQLite 能力；PG 使用版本/连接健康接口，不伪造 db_path。
- stamp_legacy_compression_chains、import_legacy_session_admissions、SQLite 修复/backfill/旧格式 import 留在 SQLite，不加入 PG 无旧数据范围。现有 export/clone/branch/rewind 和新数据保真属于 Task 12。
- gateway.session_authority/runtime/mutations/deletions、agent.runtime_session_store、gateway.session_persistence 和 run.py 的异步/懒打开层不能只替换类型注解；必须接 db.runtime 并验证后台 Profile 归属。
- gateway.readiness、run_housekeeping_disk、run_runtime、API bot_chat、API response admissions，hermes_cli.web_server_sessions/profiles、web_routers.analytics/sessions、tui_gateway.methods_profiles、tools.session_search_tool/tool_result_storage/process_registry_results/kanban_tools 的路径/直连/只读入口由 Task 16/17 负责。
- backup_sqlite、doctor、update_cmd_maint、terminal_breadcrumbs 和离线恢复明确区分业务读取与 SQLite 文件维护；PG 模式不得按 state.db 缺失返回空状态或重建本地库。
- cron、kanban、hosted rooms、插件拥有的独立 DB 不迁移；扫描表中的同名方法不代表其独立 DB 需要实现 PG。其调用主会话库的部分继续走 Task 17。

## Task 1 验证记录

2026-11-06：Python 3.12.10 AST 读取当前源码，递归解析 SessionDB MRO 声明，扫描生产导入/属性使用与现有测试引用；手工核对门面外 runtime/worker、API 两存储、delivery ledger、直接 SQL 和路径依赖。未运行数据库，未更改业务行为。

本基线方法 250 个，显式主库/辅助存储依赖消费者文件 258 个。数量仅为审计结果，不作为测试断言；声明和静态匹配不等于运行证据。后续每主题实施须将新增动态消费记录补到本清单。


## 真实 PostgreSQL 测试配置（Task 4）

配置保存在仓库外的本地文件，不把 DSN 放进聊天、Git 或命令行。示意（将占位值替换到本地文件）：

```yaml
purpose: hermes-postgresql-tests
database: independent_hermes_tests
dsn: postgresql+psycopg://TEST_USER:TEST_PASSWORD@TEST_HOST/independent_hermes_tests?sslmode=require
```

仅接受声明的独立测试库，拒绝 postgres/template0/template1；连接后再次核对 current_database。采用 PostgreSQL >=15 的开发验收下限（实际可支持范围仍待真实实例验证），管理员预先准备 pg_trgm 和创建临时 Schema 的权限，测试不安装扩展或管理服务。池预算 2，连接/池等待 5 秒。

每轮在随机 hermes_test_<uuid> Schema 写入归属 COMMENT。已存在命名空间一律拒绝；清理前核对本轮 marker，不匹配时拒绝 DROP，即使测试本体失败也只清理本轮拥有的命名空间。正式业务 Schema 不作为测试目标。

runner 对自定义参数采用显式 `--` 透传（无需修改凭据环境变量白名单）：

```powershell
$env:HERMES_PYTHON = 'D:/AI/hermes-agent/.build/postgresql/test-env/Scripts/python.exe'
$testRunner = 'D:/Programs/Git/bin/bash.exe'
$pgTestConfig = Join-Path $env:LOCALAPPDATA 'HermesTests/postgresql.yaml'
& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config $pgTestConfig -s
```

测试参数只传文件路径。显式选择集成测试而缺配置/配置错误/连接失败时失败，普通运行按仓库默认 marker 排除 integration；不以 skip 充当真实 PG 通过。环境测试输出 server_version_num、psycopg 版本、pg_trgm 所在 schema 与当前连接 TLS 参数，不输出 DSN。

2026-11-06：默认示例位置不存在，用户尚未提供测试配置；真实版本、权限、扩展、TLS 和 Schema DDL 均未验证。


## 初始 Schema 与触发器落位（Task 5）

初始业务元数据共 24 表：原主库去除 SQLite schema_version，加上投递、6 个 API 表，以及 transcript_roots。Alembic 的版本表为共享 schema 级控制元数据，不是 store 业务行。所有业务主键/唯一键/外键/索引包含 store_id。消息 UID 是逻辑身份，可以有多个物理副本；messages 上使用 (store_id,session_id,message_uid) 普通索引，禁止额外施加 UID 唯一约束。

新增 transcript_roots 的理由：不存在或已删除的会话不能只靠 SELECT FOR UPDATE 串行化。每个稳定谱系根先创建持久控制行；sessions.lineage_root_id 引用它。压缩子段复用根，独立 fork/reset 的根分配由相应操作定义，正文清理不删除控制根。投递新增实例/claim token/到期字段，用于后续 Task 14 的跨节点领取栅栏。原文消息/提示使用 BYTEA，搜索投影单独存储。

| SQLite 业务触发器 | PG 保留位置 |
| --- | --- |
| sessions_runtime_ledger_delete_guard | 作用域 RESTRICT 外键阻止未退休账本的正文删除；Task 12 原子退休后删除 |
| messages_transcript_revision_update | Task 7 所有追加/替换/修订操作在同一事务维护 revision，Task 12 重写路径同样纳入 |
| messages_message_uid_insert | Task 7 当前写入者显式分配/携带 UID；不开发旧写入者格式补齐 |
| messages_display_order_insert/visibility_update/identity_update/identity_delete | Task 7 消息与 Task 12 重写操作在谱系锁内维护完整显示代表/顺序 |
| FTS 同步与引擎维护触发器 | Task 15 的 PG 搜索投影/索引；SQLite 专属保留 |

上述操作尚未完成，不因表已声明而认为这些业务不变量已实现。PG 工厂保持拒绝启用，直到 Tasks 6–17 完整接通。

初始 revision 冻结 PostgreSQL DDL，不在升级时导入当前 Table 元数据；显式 upgrade 取得 schema 级事务 advisory lock，以短锁等待/语句超时执行全事务 DDL。拒绝接管非空无版本 schema，未知版本明确失败。普通 status/check_schema 只读取，不自动建表。初始 downgrade 不对外提供，数据备份和回退由管理员管理，未宣称可迁回 SQLite。

## Task 6 落位与离线检查点

当前未发布初始 Schema 为 26 表/15 索引：补上原 SQLite 按需创建的 Telegram mode/binding 表、工具快照外键、标题唯一约束、用量 usage_order 和消息 preview_text。上述 24 表为 Task 5 当时的数量。更改均同步冻结 revision；Schema 尚未对生产发布，不提供旧 SQLite 导入或旧 PG 版本迁移。

会话门面分为 metadata/titles/topics/usage/queries；仓储接收 Connection 和不可变 scope，不提交；完整操作使用短事务。system_prompts 用原文 bytes 计算哈希，单独锁住引用发布以防与无引用清理竞争；消息正文/预览投影写入属于 Task 7。列表在数据库分页并批量水合，嵌套 JSON 路径、压缩 tip、标题转移、来源继承、计费 NULL 及并列顺序遵守 SQLite 参照契约。

谱系映射控制键 `hermes:lineage-map-lock` 在 state_meta 中持久保存。普通写入共享锁定映射后锁根行，父链补填/标题转移独占映射后按顺序锁根；Task 12 清理不得删控制键或 transcript_roots。真实 PG 的锁竞争仍待验收。读事务用 REPEATABLE READ；配置 write_lock_timeout_seconds/statement_timeout_seconds 作用于事务本地，不变更全局 search_path。

后台用量 writer 有序排队，绑定拥有者 Profile/秘密上下文，不因调用者 Profile 改变而串写。确认回滚的 40001/40P01 与未知提交分型；提交结果未知不自动重放。事务不包含模型、投递或线程等待。导出/删除安全探针 assert_export_safe/assert_exports_safe/get_session_delete_targets 的任务归属修正为 Task 12，其功能继续保留。

2026-11-06：标准 runner 离线回归 114 passed，包含 22 共享契约各在 SQLite/Core 执行及隔离/失败/后台上下文契约；Core 的隔离 SQLite 执行不充当 PostgreSQL 验证。真实 PG 28 项集成用例等待独立配置。PG 生产工厂仍拒绝启用。

## Task 7 消息写入与投影检查点

42 个消息主题接口已有 Core 实现。MessageCodec 显式复用当前纯序列化、身份、显示去重和回放规则，不继承 SQLite I/O。新正文 BYTEA 用 T/B 标签区分文本与任意字节，不读取历史格式。多模态 JSON、保留前缀的字面串、NUL、空 reasoning_content、API 原文和 UID 均有共享契约。预览按当前 SQLite 的 TEXT length/substr 规则在 NUL 截断，正文保持完整；搜索单独投影。

所有消息插入在根锁之后分配 ID；watermark 在同根锁内读取，不能以跨谱系 ID 或 sequence 分配顺序替代提交证据。PG 竞争测试使用两连接和 pg_blocking_pids 确认实际锁阻塞，未取得真实实例结果前不能声称此不变量已通过。显示 slot/identity 与计数、revision 原子维护，添加 store/session/display_order 与 display_identity 索引；当前未发布初始 revision 为 26 表/17 索引。

批量 flush 保留逻辑身份，提交确认后才发布物理行戳与 CAS digest；未知提交不重放。保留显式 chunk_rows 的分块提交业务契约，不承诺跨块全量回滚。替换、撤回、反应已读和异步结果去重在短事务内完成；回放只投影，不重组历史提示。archive_and_compact 的完整算法/验证归属 Task 10；该接口仍是必需功能。

2026-11-06：148 项离线回归与 14 项 staged 检查通过，47 项真实 PG 测试未执行。Core fixture 的 IDENTITY 模拟仅用于离线顺序契约，不是 PostgreSQL 验证。PG 工厂保持拒绝启用，等待完整接线和真实验收。

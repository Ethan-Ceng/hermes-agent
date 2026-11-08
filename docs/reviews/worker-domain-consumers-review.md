# compute-only worker 领域消费者独立补审

## 审查范围

2026-11-08，独立 Reviewer，按 `supercoder:code-review` 补查统一数据库 Task3/4/16/18 的实际 compute-only worker 边界：验证证据、Projects、维护插件持久化、context/memory store。指标由另一 Reviewer 负责，不重复计其问题。对照设计、实施计划与真实调用链，在现成冻结 `51b3e61c6c2c6338f84acc5965f32c078a58d520` 上运行实际 PostgreSQL ordinary daemon → `agent.managed_worker` → AIAgent → loopback 模型/工具执行。

只在 `.build` 写诊断与观测层，未改生产/仓库测试、未安装依赖、未提交。源文件及 probe SHA256 清单为 `.build/postgresql/review-worker-domains-source.json`。该冻结点与检查时当前 HEAD 一致；结论不自动外推到之后的整改。

## 问题列表

### [major] 验证证据的真实 worker 消费者直接打开 owner-only 域，编辑水位丢失且停止前验证失效

位置：`hermes_db/domains/verification.py:11`；调用者 `agent/verification_evidence.py:736`、`:800`，同入口另由 `:676` 的证据记录使用；守卫 `hermes_db/factory.py:28`。

问题：`postgres_resource()` 无 worker 分流，始终 `acquire_domain("verification", settings, scope)`。普通 PG managed worker 的文件工具和 verify-on-stop 确实执行这些消费者，因 `_owner_only()` 抛 `WorkerPersistenceError("owner_store_access_from_worker")`。文件编辑记录的外围 catch（`tools/file_tools_read_tracking.py:430`）继续返回；停止前验证的外围 catch（`agent/turn_stop_gates.py:48`）也继续返回 None。于是会话可以正常结束，而已启用的持久验证合同未生效。

实际证据：独立 clean verification-only probe 启动 owner PID **2862289** 与真实 managed child PID **2862443**，通过本机模型调用真正的 `write_file`，文件成功写入 **21 字节**。PG admission 与 worker 均 terminal、模型最终回复已持久化；owner 重查 `verification_state` 为 **空**。同一真实 worker 中捕获两条原始拒绝栈：

```text
tool_executor → model_tools → file_tools._handle_write_file
→ write_file_tool → _note_edited → _mark_verification_stale
→ verification_evidence.mark_workspace_edited → postgres_resource → acquire_domain

managed_worker.execute → AIAgent.run_conversation → turn_final_response
→ turn_stop_gates._verify_on_stop_nudge → build_verify_on_stop_nudge
→ verification_status → postgres_resource → acquire_domain
```

两条都由真实 guard 拒绝，未修改 is_worker_process 或模拟其标志。完整日志 `.build/postgresql/unified-review-pg-worker-verification-red.log`：**0 passed / 1 failed，exit 1，16.0 秒**；详细 JSON `.build/postgresql/review-pg-worker-domains-evidence.json` 的 `verification`。全进程 audit 记录实际 managed spawn/child guard，SQLite 尝试 **0**。

影响：PG managed 编码会话成功编辑后没有持久 stale 水位；启用的停止前验证因读取失败直接放行。终端证据记录也共享同一个不可达 opener，不能只修本次 file-edit 路径后声称整个域完成。

建议：保留 owner-only guard，为 worker 的编辑标记、终端/verify 证据记录与状态读取增加具名、受 assignment/session 校验的 owner 持久通道，绑定 owner 捕获的 Profile/backend/store 身份；写入须有可重放命令身份，不能以删除 guard、SQLite/内存回落或关掉 verify-on-stop 通过。保持原本跨会话 workspace verify 与保留策略。

### [major] 普通 managed worker 初始化 RetainDB 时无法取得 PG pending 队列，随后 sync_turn 不持久入队

位置：`hermes_db/domains/retain_queue.py:21`、`hermes_db/retain_queue.py:22`；实际入口 `plugins/memory/retaindb/initialization.py:26`。

问题：普通 managed worker 保留外部 memory provider，`agent/managed_worker.py:364` 构造 AIAgent；`agent/agent_init.py:1270` 经 MemoryManager 初始化 RetainDB。PG `_WriteQueue` 选中 `PostgresWriteQueue`，其构造函数 `capture_queue()` 直接 `acquire_profile_domain("retain_queue")`，再次被 owner-only guard 拒绝。此处失败发生在线程启动/持久入队前。MemoryManager 的初始化 best-effort 路径（`agent/memory_manager.py:934`）捕获异常后继续，provider 的 `_queue` 仍为 None；`plugins/memory/retaindb/__init__.py:402` 的 `sync_turn` 随即直接返回。

实际证据：原两项 probe 中 RetainDB case 使用真实临时 PG Profile、冻结配置选择 `memory.provider=retaindb`、现有秘密入口中的本机测试 key 与受控 loopback 服务，未调用付费/外部端点。owner PID **2861214**，真实 managed child PID **2861368**。该 child 捕获：

```text
managed_worker.execute → _construct_agent → AIAgent.__init__
→ _init_memory → initialize_for_agent → initialize_all → RetainDB.initialize
→ initialization.initialize → PostgresWriteQueue.__init__
→ capture_queue → acquire_profile_domain → acquire_domain
→ WorkerPersistenceError(owner_store_access_from_worker)
```

PG admission/worker terminal、模型最终回复持久化均为真；后续 provider 的 context/profile HTTP 读取仍实际发往本机服务，证明这不是 provider 被未配置/不可用检查跳过。SQLite audit 尝试 **0**。日志 `.build/postgresql/unified-review-pg-worker-domains-red.log`：两项合计 **0 passed / 2 failed，exit 1，29.4 秒**；RetainDB 详细证据在同 JSON 的 `retaindb`。这是实际 compute process 的完整 provider 构造，不是仅在 owner 中启动名为 writer 的后台线程。

影响：配置启用的 RetainDB 在 PG compute 会话中不能建立持久 pending 队列，会话却继续完成，后续 turn sync 因 `_queue is None` 不入队。现有 owner/后台线程/进程重开队列测试没有覆盖这一 compute-only 限制。

建议：让实际 worker provider 使用 owner 绑定的具名入队/生命周期通道或等价持久代理，保留队列确认、重试、未知提交、目标摘要及 shutdown 合同；owner 负责选定数据集的 PG 资源。不能允许 compute 直开 canonical 域，也不能禁用 RetainDB 或将 pending 变为进程内队列。

## 实际消费者边界与排除项

| 范围 | 已追踪的实际边界 | 本次判断 |
| --- | --- | --- |
| Projects | `gateway/session_local_inventory.py:64` 在 owner 解析 cwd；TUI/Desktop 的 `tui_gateway/agent_factory.py:658` 在 owner 构造 agent，`agent_callbacks.py:229` 接线工具回调 | 本次未证明 Projects 存在受支持 compute 路径，不报假 major |
| GUI managed | `gateway/session_managed_worker.py:55` 明确拒绝非 CLI 普通 managed policy；GUI 独立 probe 未产生 worker 行或模型请求，Projects 获取仅发生于 owner PID | 此诊断不满足 managed witness，保留日志但不作 PG 缺陷证据 |
| 通用 PluginStore | PG factory 本身 owner-only；Task16 实际 KV 消费者为 Discord recovery cursor，`operations/discord_recovery.py:90` 经 adapter owner 消费 | 未找到维护中的 compute 插件实际调用通用 plugin_store，不能只凭 API 类名报 major |
| 维护任务 | `hermes_db/maintenance.py:6` 的插件 TTL 清理由 owner 生命周期/CLI 启动入口调用；没有因本次 worker 链进入维护 factory | 未证明同类 compute 缺陷 |
| context engine | 本树只有插件发现器与框架契约，没有 bundled context SQL store 实现；内建压缩通过既有 session store | 不把 catalog 中未提供实现的 provider 假设为已验证，也不凭空报问题 |
| 内建 MemoryStore / ByteRover | 内建 MEMORY.md/USER.md 是既有文件能力；ByteRover 无本轮迁移的本地 SQL store | 不把这些文件/远端能力当作 PG→SQLite 回落；RetainDB 专用队列另列 major |

初版 combined probe 曾令 CLI 模型先请求 `desktop_project`，实际工具结果明确为 tool unavailable；随后有效 `write_file` 仍触发验证域红测。该 Projects 请求没有进入 factory，不能据此报告 Projects 域错误。随后已经移除无关调用，得到上面的 clean verification-only 红测。原 probe 留在 `.build/postgresql/review_worker_domains_red_v1.py`，GUI 诊断版本留在 `review_worker_domains_projects_v2.py`；GUI 日志 `.build/postgresql/unified-review-pg-worker-projects-red.log` 的失败是诊断要求 worker 行未满足，不计为第三个生产问题。

## 计划验收覆盖缺口

Task3（计划 `:170`）要求实际终端/停止提示消费者在 PG 工作；当前 `test_verification_store.py` 从 owner 作用域直接调用 facade，只证明持久域操作，没有完整 compute 执行。Task18（`:1036`）要求维护中的 provider 入口正常；现有 queue writer 线程、owner 子进程、故障/重开合同也没有证明 AIAgent 在真实 compute 进程初始化 provider。原 full-worker Kanban 流程未启用本次文件验证和 RetainDB，不能以其成功覆盖这两个域。

Task4 的 owner/UI 入口与 compute 支持边界须分开评价，不能把不存在的 Projects worker RPC 当作已经出现的生产缺陷。Task16 对无实际消费者的泛化 plugin SQL 路径也不能仅凭静态猜测扩项。

## 复现与证据限制

使用既有 PM Windows orchestrator 与 Linux PM test Python，随机 Schema 经既有 PG fixture 核对归属；仅访问 `.build/postgresql/private/acceptance-postgresql.yaml` 路径，不打印其内容或凭据。示例（私有 PG 参数由既有 orchestrator 追加）：

```text
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --state task24-selector-checkout-state.json --log unified-review-pg-worker-verification-red.log /mnt/d/AI/hermes-agent/.build/postgresql/test_review_pg_worker_domains.py -j 1 -k verification -s --tb=short -p tests.conftest -p tests.hermes_db.conftest -p tests.hermes_db.postgresql.conftest
```

当前 clean probe 参数为 `verification`、`retaindb`；原合批日志对应保存的 v1。实际业务等待为 90 秒、child exit 20 秒，没有缩短/放宽生产 deadline、替换 SQL/内存存储、伪造权限或直接设置 worker 标志。import hook 仅记录真实 factory 的成功/拒绝后原样返回/重抛，SQLite audit 原样拒绝全部连接。

本轮普通 worker 场景未尝试 SQLite；这不能外推为已验证 ignore-user-config 默认 snapshot 下的旧文件反例。该 storage 身份交界与指标 Reviewer 的实际反例需一起整改，不能只改某个 opener 使一个用例绿。owner-only、真实 PG 持久/重开/peer 隔离、失败/未知提交回放及原生后端同合同仍须在整改后复验。

## 门禁与结论

发现 **2 项实际复现的未处理 major**。本补审结论 **`CHANGES_REQUIRED`**。需要补齐 owner 持久通道和真实 compute 消费者合同后独立复审；原 owner 域测试与旧冻结完整回归不能替代。总体最新生产/发行载荷、其他原生失败与非 WSL 七项主机证据门禁继续保留。

## 后续整改复审

首步 verification owner 转发与 owner 保留策略的最新独立复审见 `docs/reviews/worker-domain-first-fix-review.md`。原验证域获取失败已由真实 ordinary/config-only managed 执行闭合；首版转发新增的 worker 自选 cutoff 跨 session 删除问题有独立破坏红及整改反向绿，原证据全部保留。RetainDB 的第二项 major 仍未实施，不能改写为两项均完成。

同名私有 probe 重跑会更新 `review-pg-worker-domains-evidence.json` 的 verification case，当前该 case 已是 green；原不可变 red 日志及本报告原 PID/调用栈仍保留，first-fix green 另存 `review-pg-worker-domains-first-fix-evidence.json`，以免把后续 JSON 状态误读为原红现场。

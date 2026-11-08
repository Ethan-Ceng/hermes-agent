# Managed worker metrics：有界协议复审

本报告第一阶段只审最小协议接缝，不重新设计全域指标、不修改生产或仓库测试、不重写实施计划。主要代码基点为 `ed0cdbe604cded73026f28f4b96937c6e204a5cf`；另只读核对 Root 当前 engagement Path(None) 窄修。末节追加当前未提交实现的独立复审及两项 ignored 真 PG 探针。普通 PG worker 指标缺失、PG bypass worker 打开遗留 metrics SQLite 的实证与 major 状态，沿用 `unified-database-metrics-worker-snapshot-followup-review.md`，本报告不关闭它们。

## 可直接复用的已有接缝

| 边界 | 实际代码 | 最小建议 |
| --- | --- | --- |
| 真实 worker 所属存储 | `gateway/session_worker_domains.py::storage_identity`；`agent/runtime_domain_store.py::owner_binding/worker_resource` | 复用已认证的 storage.identity，缓存 owner 的 backend/profile_home/store_id/target；metrics factory 与 consent 前置探测先识别这一绑定，不先依赖 agent snapshot 的默认 SQLite |
| 封闭域写入 | `worker_domains.write_handlers`→`worker_handlers.handlers`→`CoreEffect` | 增加封闭的 domain.metrics 命名操作；不开放 SQL、任意 state_key、Python callable 或调用者指定数据库/路径 |
| 当前 Profile 原子回执 | `RuntimeSessionStore._apply:339`、`retry_pending:357`；`operations/workers.py::apply_receipt:66` | 复用已有持久 journal、sequence/digest、epoch/generation 和 adoption 验证；指标 effect 与 worker_receipts 使用同一个 Connection 与 scope |
| 非事务维护 | `gateway/session_worker.py::worker_request` 在 mutate 返回以后已离开运行时 `_write` | 使用闭合的 `domain.metrics.flush` 空 Core effect；回执提交、连接释放后由 gateway 做 owner 维护。不增加任意维护 RPC，也不把有写入的操作塞进 worker.read |

`workers.apply_receipt` 已检查 epoch、执行归属、generation、顺序与 digest，并在同事务保存结果和 last_sequence；同序同摘要返回既有回执，异摘要冲突。当前 Profile 的 counter/latch/rollup 不需要另一套 metrics receipt 或新表。继承现有 4 MiB 上限之外，metrics 自身仍应限制批量条数和每字段长度，不传原始 Relay event、prompt、tool args 或配置/秘密内容。

## 真实身份、collection 与 send consent 必须分开

`SharedMetricsStore` 当前在构造时走 snapshot selector；PG 构造又经 capture_metrics/acquire_domain 被 `_owner_only` 拒绝。新 worker facade 应在 constructor 选择之前使用 owner_binding：PG owner 永远得到 PG owner 代理，默认/ignore snapshot 不得使它打开旧 metrics.sqlite3；查询失败不能退到本地 SQLite 或内存指标库。

collection 继续按 worker 已绑定的冻结配置决定；send consent 则由真正 owner 的当前 Profile 配置决定。客户端不能传一个 send_enabled 布尔值使 owner 授权。沿用 owner 现有 read-only/send-config 解析语义与 consent clocks，读取/准备放在短数据库事务之外，再把可信的解析结果用于同连接 consent 操作。发送前仍需 owner 原有的实时 consent 检查，不能将一次 worker 查询或旧回执当作永久发送许可。

`_reconcile_send_consent_once` 在 collection gate 前运行，这是撤回 consent 的必要路径；worker collection 关闭时也不能仅跳过它。可让代理提交没有 counter 的命名 consent 操作；不要重读 worker Profile 文件或关闭 config-only lifecycle。真实资源获取仍保留 owner-only，不能为了 metrics 去掉这一约束。

## 具名最小操作集与同连接约束

实际消费者是 `SharedMetricsSubscriber`：构造时读取 recorded_milestones/features；`_persist` 调 counter、每日 latch、client_active/install_snapshot；随后处理 milestone/feature adoption；`_record_engagement` 调 engagement.record。Runtime 还会读 install_snapshot_due、在 flush 后请求导出；install-age helpers 读取首会话时间。代理至少要覆盖这些真正消费的公共语义，而不是只补 model_route counter。

建议的闭合语义为 counter、daily counter、client active、install snapshot、milestone、feature adoption、engagement，以及对应只读 latch/install-age/due 查询。owner 以既有 `_validate_counter`/contract 再校验 metric/dimensions/resource/amount；各种 state_key、latch prefix 和时钟由 owner 从闭合 kind 推导，不能从 RPC 接收任意 key。install-age 应读 owner 对应 store 的首会话，不能继续拿默认 worker snapshot 去猜 state.db。

当前 PG operations 已提供 `record/once/rollup(conn, store, ...)`。复用 `ReceiptDomainResource` 或等价只借当前 conn 的 scoped facade；handler 内不得调用 `PostgresMetricsStore`→open_metrics→acquire_domain 再借连接，pool_size=1 会自阻。另必须在 receipt conn 上保留现有 `repositories.metrics.lock_store`：worker receipt 只拿 session store 锁，普通 owner metrics 则拿 metric_store_locks；只保留前者不能保护 once/rollup 与普通 metrics 的竞争。锁顺序固定为 session→metrics。

每个命名 store 调用保留其本来原子范围：counter+latch、engagement state+该次派生行与其回执同事务。不要额外宣称一个 Relay event 的全部 counter、feature、root 副作用都是单事务；现 subscriber 本来逐个调用这些操作。

## Engagement 的 callback 与 Profile 边界

`shared_metrics_engagement.record:110` 原来用 `Path(database_path)` 推 Profile，PG 的 database_path 为 None，不能工作。Root 当前窄修在 None 时用明确 profile_home，SQLite 自定义 database_path 仍保留原推导；此 diff 方向符合两种现有调用合同，本 Reviewer 未代跑 Root 报告的 PG/Native 绿测。

`update_rollup_state(state_key, lambda state: apply(...))` 不应直接成为 RPC。用具名 engagement observation 表达 surface/route/resource，owner 复用纯 `engagement.apply`。profile_home、root home、profile hash、owner 标志、时间以及 busy_peak 都由 owner 推导；worker 进程的 busy-memory 并不等于 gateway 真实 busy peak。不要接受任意 callback、clock、root 路径或 profile hash。

现有 record 先完成当前 store 的 update_rollup_state，再在 root collection 开启时独立更新 root；原本就不是跨 Profile 原子写。root 可能是另一个 PG target、另一个 store_id，或 SQLite；须按 root 自己的真实配置、资源身份和 collection/consent 执行，不能借源 Profile 的 backend、agent snapshot 或 source pool 来推断。

## Root intent：复用 metric_state 足够，但不是跨 Profile 原子事务

已采纳的候选方向可审：当前 engagement effect 需要 root 贡献时，在现有 metric_state 记录 owner 生成、版本化、非秘密的 root-observation intent，与当前指标及原 worker 回执同事务；原有 source transaction/connection 释放后，维护端独立处理 root。root 事务关闭后才重新打开 source 删除 intent，pool_size=1 时绝不嵌套借连接。

这需要遵守以下条件：

- root collection opt-in 在采纳时由真实 owner 读取，排空时再次核对；撤回则 retire，不把 collection 关闭时的旧贡献等将来 opt-in 再回填。send consent 独立于 collection。
- 保留原 intent 日/stamp。`engagement.apply:203–225` 在 state.day 已晚于传入日时仍会向现有 state 加 profile；因此不能直接喂一个旧 stamp。必须在 root 同一写事务中检查日序，已晚于 intent 日则明确 retire/drop，绝不把旧 Profile 计入新日。
- 当前 root 贡献只带 profile 集合，不带 surface/route，所以同 Profile/日重放是幂等集合加入；保留这一约束。若把 route/model 次数一并重放，纯集合幂等就不再成立。
- root commit 后、source intent 删除前崩溃，可重复应用同日集合；不宣称 root 与 source 一起提交。明确的晚到/withdraw retire 属于已有 best-effort 边界，须可观察且不能无限重试。
- intent 的字段/数量/处理批次与保留期要有界；只用闭合 owner 操作读写其专用 namespace，不开放任意 metric_state RPC。

无需为此新增 schema 或独立 outbox：现 metric_state（SQLite 对应 telemetry_state）可以承载这类有界待办。worker_receipts 只有 payload digest 和结果，没有完整原输入；其 replay ACK 是不可变的，不适合把待办完成状态反复写回 result_json。若强行改 ACK，会破坏原精确重放合同。新 schema 只有在需要超出现有有界 KV 能力的通用可索引队列或全局事务保证时才有额外理由，本轮没有这样的必要。

## flush 维护与 execution.finish 的顺序

`_Runtime._schedule_flush_and_export:742` 会启动异步 `_flush_thread`；`agent.managed_worker:405–417` 现先 retire agent、等 title、flush tokens，再发 result，等 owner finish 后提交 execution.finish。仅依赖 atexit 太晚：执行终态后新的指标 receipt 会被 stale_generation 拒绝。

因此在 finish 前需要显式关闭新 metrics 生产、等待 title/必要 callback、排空 Relay SDK/subscriber 并等待本 runtime 的 flush thread，确认 worker journal 没有 pending，再提交 `domain.metrics.flush` 维护回执，最后 execution.finish。若异步线程仍能在 finish 后写入，屏障并未完成。

已有 `shutdown_runtimes()` 可复用其关闭逻辑，但它用 `_safe` 吞异常，且本身没有明确 join `_flush_thread`；单独调用不能作为“已持久化”的证明。需要显式可检查的 quiesce/flush 结果和 journal 状态，失败不能静默变成 terminal-success。

等待 SDK/subscriber/flush thread 时不得持有 RuntimeSessionStore/RPC/metrics 锁或数据库连接：订阅线程可能正在等待同一 worker receipt，否则会把 drain 屏障变成互等。该屏障只作用于本 compute worker 的 runtime，不应为一个 worker 终态关闭 owner 的全 Profile Relay runtime。

`domain.metrics.flush` 的 Core 部分只保存空效果回执；gateway 在它提交并释放连接后排空本 Profile intents，并请求 owner 原有 export/异步 sender。精确缓存回执重放也必须重跑 post-commit 维护；维护失败不向 worker 确认该请求，保留原 journal 让它重试。维护成功时原回执 ACK 保持不变。owner 的文件导出和 HTTP sender 不在 receipt 事务内，也不由 compute worker 自己实例化 PG store 或发送。

## 本次结论

上述是基于实际调用者与现有协议的有界审查意见，不是实现验收。Root 已接受较小的 domain.metrics.flush、KV intent、晚到/withdraw retire 和显式 flush 屏障方向；未因此关闭任何 metrics major。后续必须由真实 PG managed worker、owner 关闭重开、peer 隔离、pool1、重放/故障及遗留 SQLite 反例给出证据。原 CLI safe-mode 通过只覆盖其既定合同，整体仍 **FAILED / CHANGES_REQUIRED**。

## 当前未提交实现的独立复审

范围为 Root 在 `ed0cdbe604` 之后工作区实现的 `worker_metrics_store.py`、`operations/worker_metrics{,_engagement}.py`、`domains/metrics_bound.py`、`runtime_workers.py`、gateway persist/post-maintenance、Relay factory/export、engagement 和 managed worker quiesce 全部实际 diff，并只读新增永久测试。原冻结 foundation 报告不变；本节只由 Foundation Reviewer 更新，不修改其他 Reviewer 的实现报告。

当前重点范围**未发现有实证的新增 blocking/major**。原 metrics major 的关键整改已有下述局部证据，最终状态仍由新冻结完整矩阵与独立终审决定。不能把“没有新发现”或部分绿测当作全局验收。

为区分审查中的工作区变化，最后读取的 Git blob 为：`worker_metrics_store.py`=`a70ba59560822ca69e1ada0aaf1e4707199a419f`、`worker_metrics.py`=`83a780a77af04b722228f01374f7c6686aff8670`、`worker_metrics_engagement.py`=`f00290b10ececb7424256dabf6e5dd9c3e648f9d`、`gateway/session_worker.py`=`fccacb9b133e480855aa6e842d400800f4f5c66c`、`session_worker_metrics.py`=`c622e0ca29617118c30021e12d7bac1e7e7b113d`、`worker_metrics_shutdown.py`=`cfc79419b49664ccb9fdacae837c54a86c09ac52`。这些是未提交文件内容的标识，不宣称为冻结 revision。

### 实际协议边界

| 合同 | 当前实现核对与限制 |
| --- | --- |
| PG 身份及旧 SQLite | `shared_metrics_storage.postgres_store` 在 snapshot selector 之前识别 `worker_resource('metrics')`；代理身份来自现有认证 storage.identity。`WorkerMetricsStore` 的 connection/write/callback 明确拒绝，本身不创建 PG engine 或 SQLite；collection 仍由 worker 已冻结 policy 决定。原 SQLite worker 早返路径保留。 |
| receipt 同连接与锁 | `RuntimeWorkers.mutate_worker:47–51` 在 `_write` 前准备可信 policy；`worker_metrics.invoke:43–62` exact fields、16 KiB 上限、`ReceiptDomainResource`、显式 `repo.lock_store`，bound store 仅借原 receipt Connection。没有拿第二连接规避 pool1，也没有将 lambda/任意 SQL/state key 变成 RPC。metric/rollup 与该次 receipt 原子提交，未额外声称整个 Relay event 原子。 |
| owner 配置与发送 | consent payload 为空，`prepare_policy:25–35` 在连接外读取真实 owner 配置；maintenance 在 owner scope 先解析真实配置、无条件 reconcile consent、drain，再依据 collection gate 决定 export，send gate 决定原 sender。代理忽略 worker 自带 send 布尔值。owner HTTP/文件工作没有保留 receipt 连接。 |
| root intent | owner 在本地 metrics 锁内推 home/root/hash/stamp；每日合并一个有版本 intent。root 配置采纳时及 drain 时分别核对；仅转发 Profile 集合，保留原日期，晚日退休。root 提交后 source key+原 value CAS 删除，保留跨 Profile 独立事务语义。 |
| 缓存回执与维护故障 | `gateway/session_worker:98–104` 在 mutate 返回后维护，缓存 receipt 同样进入该分支。维护异常不会返回成功 ACK；原 `RuntimeSessionStore.retry_pending` 保留 journal，并阻止新的 finish，直到显式原序号重放成功。下方实际 handler 探针覆盖这一局部链。 |
| 退出屏障 | `managed_worker:411–419` 在结果/finish 前 quiesce。`close_runtime` 复制 sessions/lineage/thread 时短暂持锁，释放后才 join 和 SDK flush；显式 store flush 与 journal 检查位于 finish 前，未复用吞异常的 atexit 作为成功依据。实际 SDK 故障证据见下表，未证明所有线程调度/断线组合。 |

quiesce 最初按 ambient `current_profile_key` 查 runtime；新永久故障夹具把调用放在未传播 Profile Context 的 ThreadPoolExecutor 中，首两批未通过，不能把它们改写成既有绿。Root 当前把入口按 `owner_binding(store)` 的 home/store_id 绑定后再查 runtime。`hermes_db.scope.bind_profile_home` 只 set/reset home ContextVar；不读取 `.env`、不构造秘密 scope、不修改 `os.environ`，符合后台入口显式 Profile 绑定规则。它继续只处理本 worker runtime。最新永久测试还要求后台 caller 原 scope 在成功/失败后恢复；本 Reviewer 已读完该断言和 2 pass 日志，没有另行声称该线程行为由自己执行。

### Foundation Reviewer 独立实际 PG 探针

两个 probe 均只在 ignored `.build/postgresql/review_foundation/`，用拥有者随机 Schema、真实 PM Windows 解释器、`scripts/run_tests.sh`、`-j 1`、retries=0、`-m integration`，显式加载 `tests.hermes_db.conftest` 与 `tests.hermes_db.postgresql.conftest` 的严格 SQLite guard。配置仅传私有文件路径，未输出凭据，未操作正式 Profile 或服务。

| 探针与实际结算 | 行为证据 |
| --- | --- |
| `test_metrics_maintenance_withdrawal_probe.py`，SHA256 `3BE8DF339CD56C5C71CDD7BFCF99DE495B44EBA20F4EB43B7A6A97BD7C97E51B`；`review-foundation-metrics-maintenance-withdrawal.log` **1 passed，exit 0，runner 6.0s** | 真 PG pool1，先开启 owner consent 并记一条 counter，再将 owner collection/send 同时撤回；ambient peer 仍两项开启。调用真实 maintain 后 owner window closed、package=0、outbox 空、counter=1/packaged=0，peer 没有窗口，foreground scope 恢复。脱敏 artifact 为 `review-foundation-metrics-maintenance-withdrawal.json`。 |
| `test_metrics_gateway_flush_replay_probe.py`，SHA256 `9FC43AEAABE74F92B64763347B2F5191B4269ADCC508CEAC9BC9FE196CABC9EF`；`review-foundation-metrics-gateway-flush-replay.log` **1 passed，exit 0，runner 7.3s** | 真 PG pool1，实际同用户存活 child PID/birth、SessionAuthority authorize、claim/register/adopt/verify；真实 gateway handler 提交 flush receipt 后先完成真实 maintain，再在 ACK 前注入 OSError。原 journal seq1 留存，PG execution 仍 running/last_sequence1，finish 被 sticky failure 拒绝；`retry_pending` 以同 seq 返回原缓存 receipt，同时第二次运行 maintain，journal 随后清空，receipt 仍只有原一条，恢复后 finish terminal。维护前后 checkedout=0。 |

第二项同步 dispatch 直接调用真实 async handler，不经过 WebSocket 序列化/连接层；child 仅作为本测拥有的实际身份，未运行完整 managed agent。它没有伪造 `_claim`、`_verify`、Core 结果或维护结果，但不能代称实际断线、worker 崩溃/新进程 adoption、长期离线恢复已通过。产物 `review-foundation-metrics-gateway-flush-replay.json` 同样明确这个边界。

第一次 withdrawal runner 曾 0 selected（遗漏 integration 选择），另一次 flush runner 参数未放在 `--` 后，runner 以 unrecognized argument 退出 2；分别保留 `review-foundation-metrics-maintenance-zero-selected.log` 与 `review-foundation-metrics-gateway-flush-replay-runner-args.log`，均不计为产品通过或产品红。上述 1+1 是随后真正执行的结算。

### 已读取的其他实证与剩余边界

| 产物 | 实际范围；非本 Reviewer 执行 |
| --- | --- |
| `unified-task24-worker-metrics-port-first.log` | 初版 Core/engagement/真实 ordinary+ignore managed 三文件 5 pass，尚未包含后来严格退出屏障。 |
| `unified-task24-worker-metrics-quiesce-first.log` | metrics、verification、Retain 三个真实 managed 文件 6 pass；只能证明这些消费者在当时源码的退出交界。 |
| `unified-task24-worker-metrics-root-http-first.log` | root 三项及实际 managed metrics 两项，共 5 pass；已读测试包含 config-only 场景真实 loopback receiver 收到已同意完整历史日的包，普通 send=false receiver 空。不能据此声称发送中的撤回与重启重试均完成。 |
| `unified-task24-worker-metrics-barrier-scoped.log` | 真实 Relay SDK subscriber + PG receipt 两项 2 pass。Event 暂停实际 active 写，屏障不能提前通过；真实 commit 后丢确认留 journal/阻止 finish，原序重试后计数恰一。它使用绑定的真实代理与 canonical Core，未启动完整 compute 子进程。 |
| `unified-task24-worker-metrics-mixed-barrier.log` | 上述两项与 PG satellite→明确 SQLite root 合同共 3 pass。已读 mixed test 的每次 SQLite audit 要求当前 home 为 SQLite root，source 不创建 metrics.sqlite3；不能将合法 root SQLite 记为 PG source 回落。 |
| Plugins Reviewer `unified-database-worker-metrics-implementation-review.md` | 独立 ignored 真 PG 三项报告：同 target pool1、root commit/source delete 前故障重放、更新 intent CAS、撤回时退休及不采纳、晚日不误计。已读报告，不冒称自己代跑。 |

本 Reviewer 在阅读中指出过两个候选，当前没有将它们登记为真实新缺陷：早版 maintain 的 collection gate 顺序在独立 withdrawal 探针之前已收紧，当前实际 green；早版 drain 单批 128 后可能 ACK 的问题，当前 `worker_metrics_engagement:87–90` 已检查残留并抛 `StorageNotReadyError`，保留原 journal 供 cached flush 再维护。未对旧候选跑出产品红，不能虚构为本 Reviewer 的红绿闭合。

仍须保留的验证边界：不同 PG target 的 root 新路径、真正 WebSocket post-commit 失联及 worker 新进程恢复、发送中 consent 撤回/失败包重放、超过 128 条/损坏 intent/长期失败的 backlog 保留策略、flush thread 达到其原 20 秒边界及所有实际 SDK 在途工作组合。本节没有把这些未覆盖项直接定为生产缺陷，也不因局部通过而删除它们。Root 独立发行载荷、当前最终 Linux/Windows 全矩阵和非 WSL POSIX 私有启动页缺口不在这两项窄探针内。

**结论仍为 CHANGES_REQUIRED；全局仍 FAILED。** 当前代码方向符合已审闭合协议，以上两项 Foundation 独立探针与所列永久证据支持局部整改，但本报告不关闭原 metrics major，不批准 Task24 完成、合并或发布。

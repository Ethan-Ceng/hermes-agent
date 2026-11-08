# RetainDB worker domain 方案边界独立复审

审查输入：Root 已提交的 `c0558e9c1365afb95406431b7a05c74c60525bf4` verification owner-domain 通道，以及拟沿此通道接入的 RetainDB 队列。只读核对实际 `_Client`、provider、PG 队列、worker journal / receipt / read-auth 源码和已有行为合同；本轮未实现、改测试、运行替代验收、安装或提交。

## Destination namespace 的结论

**同 Profile 的 destination 是合法业务 namespace，不需要额外强绑当前会话或当前最新 Profile 配置中的单一 endpoint/project 才能保持现有拥有者隔离。** 需要固定的是经过采用认证的 owner Profile / store_id / Schema / target 和 `plugin_id='retaindb'`，而不是把 destination 当成另一套 owner 数据集授权。

依据实际消费者：

- `plugins/memory/retaindb/__init__.py:94` 的 `_Client` 是实际使用的 REST client；没有另一个 RetainDB SDK 的隐式目的地解析。构造器仅去掉 base_url 的尾部 `/`，project 原值进入 `_scoped` 的请求正文。`initialization.py:17` 先对配置字符串 strip，再按 scoped secret > config > default 选择，不能用额外 URL 大小写、路径或 project 小写化规则改变已存在的目的地身份。
- `hermes_db/retain_queue.py:20` 当前按实际 client 的 `[client.base_url, client.project]` 紧凑 JSON 的 SHA256 分区，不含 API key。凭据轮换不应让原队列失去重放身份。
- 队列本来是每 Profile / plugin 共享，`operations.retain_queue.claim` 按 store/plugin/destination 取最早可用行，没有当前会话谓词。另一个新会话/client 可以重放旧会话的 pending。`user_id` / `session_id` 是远端 API 业务值，不等价于本地 PG session 外键，原合同故意包含 NUL/Unicode。
- `test_retain_queue_worker.py::test_changed_remote_project_never_receives_original_pending_data` 明确要求：切换项目只投递新项目的行，旧项目 pending 保留，恢复旧 client 后才重放；`test_two_real_writers_claim_distinct_rows_while_clients_wait` 允许同 Profile 的两个 client 同时工作。当前 owner direct API 也允许多个 `_Client` 目的地。

因此不能照搬 verification 的 `owned_session(payload, current_session)` 到 RetainDB claim/inspect/ack，否则会破坏实际跨会话恢复；也不能在每次 claim 时只允许最新 config 的 destination，否则旧冻结会话或恢复旧目的地会被误拒绝。worker 通道的 destination 值应保持严格 hash 形状/固定队列引用，所有 SQL 仍按 authority 的 store/plugin/destination 共同限定，返回的行不能悄悄切给另一个实际 `_Client`。这不代表 destination digest 本身是权限凭证，也不允许 payload 覆盖拥有者字段。

本结论不新增“同 Profile 的不同目的地互为不信任租户”的安全保证；现有 API 没有该授权合同。若以后要求会话级 destination capability，应单独设计跨会话恢复的授权模型，不能在这次移植中隐式改变。

## 拟接入通道需要保持的合同

1. **Owner 身份先于 agent snapshot。** 新资源首先读取 `owner_binding` 的已采用 authority 身份，不能因 ignore-user-config 默认 snapshot 而构造 SQLite 队列。固定 `plugin_id`，closed fields 拒绝 Profile / store / Schema / target / SQL / 权限 / 时间策略覆盖；每次 read/write 仍验证有效 execution、generation、owner epoch。
2. **写效果与 worker receipt 同 Connection 原子提交。** enqueue/claim/renew/ack/fail 调用实际队列原语时，应使用 owner 既有 receipt connection，不可内部另开 `open_queue` 单独提交。保留 rollback、真实提交确认丢失、同 seq 重放和 payload 冲突拒绝。inspect/counts/ready 只读通过同一采用认证，不隐式写或创建独立连接长期锁定。
3. **消息身份由 owner 重算。** owner 根据实际 destination、user_id、session_id、原 messages 重算 `operations.prepare` 的内容指纹，不相信 worker 提供的 fingerprint/status/attempts。请求 ID 稳定；已 acknowledged 的重复 enqueue 返回原终态、不重新投递。现有 request key 不含 destination，复用同 request ID 指向另一 destination 或内容必须继续冲突。
4. **Wire 转换限于 fingerprint。** `operations.decode` 已将消息/用户/会话/错误正文恢复为字符串，只有 fingerprint 仍是 bytes；明确把该字段转 hex、worker 恢复 bytes。不要通过全局 str()/hex/删空值转换损坏 NUL、Unicode、False、0、None 或消息列表。PG 时间、120 秒 lease、claim token、重试退避由 owner 的 PG 原语生成，不接受 worker 时钟/租期参数。
5. **HTTP 保持在线程及连接外。** 实际 `_Client.ingest_session` 仍由原队列 writer 发起；HTTP 等待中不能持有 PG connection、receipt transaction 或主 RuntimeSessionStore lock。client 与已捕获 destination 保持一致，换项目不捞旧项目正文。

## 时间敏感回执重放必须单独验证

`RuntimeSessionStore._apply` 将写入 durable journal；确认丢失后 `retry_pending` 会重放原 seq 并取得旧 receipt 的结果。这正是写幂等的需要，但 **旧 claim/renew receipt 的成功不等于当前 lease 仍有效**。

当前 direct `_send` 在 HTTP 前 fresh `renew`。迁移后如果 renew 本身已真实提交、确认丢失，worker 长时间断线，再以同 seq 得到缓存 True，而行已过期或被另一个 claimant 接管，就不能用缓存 True 继续发送。Root 拟增加的 authenticated `ready` read 适合在 HTTP 前检查 PG 当前 status/token/lease，并拒绝已知失效的 claim；它必须读取当下 PG 时间与状态，不复用旧 receipt 的布尔值。

最小真实反例：A claim/renew 提交后丢确认 → 只在拥有测试 Schema 中推进该行 lease 为过期 → B 实际 retake 得到新 token → A 恢复原 seq 回执 → A 的 fresh ready=False，不能据旧成功回执发 HTTP 或改掉 B 的 claim。另验证旧 token renew/ack/fail 均不能吞掉新 claim。

这不发明远端 exactly-once 保证：现有 `_Client.ingest_session(user_id, session_id, messages)` 没有可发送的本地 request/receipt 幂等参数；远端接收后本地 ack 丢失仍可能重放同一冻结内容。短读检查与网络之间也不是分布式原子区间。保持文档中的 at-least-once、稳定消息与 token fencing，避免把旧回执当新鲜许可。

## 线程、pending journal 与关闭边界

`WorkerDomainStore.command/query` 当前沿 RuntimeSessionStore 的同一 RLock / seq 通道，能序列化主 turn 和 writer。但实际 RPC/journal 故障会抛 `WorkerPersistenceError` / connection error，原 `PostgresWriteQueue._loop` 只捕获 `StorageError`。新桥接实现需要明确这些错误如何保留 journal、记录失败、停止或恢复，不能让 writer 线程无观察退出后仍报告工作已完成。`owner_read` 在 sticky failure / pending receipt 时本来就拒绝，不能为 ready 旁路这个规则。

原 HTTP timeout 15 秒，shutdown 的 join 是 10 秒；原代码允许关闭时警告仍有未确认工作保留。新 worker 通道必须在 `execution.finish` 前结算必要的 enqueue/write receipts，不靠 worker RPC 关闭后的 atexit ack。尚未确认的 HTTP 可以保留真实已提交 pending / claimed 行供下次重放，不能记为 acknowledged；必须测试 owner/worker 退出、lease 恢复及旧 token 失效。不得用延长 deadline、静默关闭 sync_turn 或移除 owner-only 来取绿。

## Root 后续实际证据应覆盖

- 真普通 PG daemon → 已采用 managed worker → 实际 RetainDB provider.initialize / sync_turn → loopback `_Client` HTTP → PG acknowledged（正文清除），owner 关闭/重开和 peer 隔离；SQLite 全拒绝。
- 同 Profile 同 destination 跨会话恢复、两个 client 并行；两个不同 destination 不错投，恢复旧 destination 后旧 pending 可投；API key 轮换不改变 namespace。
- 真实 enqueue effect/receipt rollback 与丢确认；claim/renew 时敏感旧 receipt + fresh ready、retake fencing；HTTP 成功但 ack 未提交/已提交确认丢失分别验证，无虚构远端幂等。
- NUL/Unicode 及非字符串 JSON 值保持；RPC 仅 fingerprint hex；未知时间/权限/owner/plugin 字段拒绝；HTTP 等待时连接归还，关闭/重启不丢 pending、不通过已关闭 RPC 假确认。

现有方案在 destination/owner 分层上合理；上述是实现和验收要求，不把未实现的设计预测冒充已经复现的新生产缺陷。RetainDB managed-worker 已有 owner-only 实际红测仍需 Root 真正整改闭合，metrics 两项 major 和全局门禁不变：**FAILED / CHANGES_REQUIRED**。

## Task24 bridge 实施后独立增量复审（2026-11-08）

范围：基于 `c0558e9c1365afb95406431b7a05c74c60525bf4` 的未提交工作区，读完 `hermes_cli/db_setup.py`、`hermes_db/domains/retain_queue.py`、`hermes_db/operations/{retain_queue,worker_retain_queue,worker_domains}.py`、`hermes_db/retain_queue.py` 的完整变更及实际调用链，并读完新增 `test_worker_retain_commands.py` 和 `test_managed_retain_queue.py`。本 Reviewer 仅写 ignored 诊断与本报告；未改生产/仓库测试、未安装、未提交。

### [major] WebSocket 读断线越过新 catch，writer 退出而 execution 仍可正常结束

位置：`hermes_db/retain_queue.py:84`（初版 bridge 的 `_loop` channel catch）；同一异常分类遗漏涉及 `:49` 的 enqueue 和 `:101` 的 shutdown count。实际传递点为 `agent/runtime_session_store.py:125` 的 `_OwnerLink.receive` 和 `:212` 的 `WorkerRPC.__call__` 原样重抛。

问题：真实 `websockets.exceptions.ConnectionClosedError` 的继承链为 `ConnectionClosed → WebSocketException → Exception`，既不是 `OSError`，也不是 `WorkerPersistenceError`。因此新增 `(WorkerPersistenceError, OSError)` 不能接住 owner socket 在已发送请求后关闭的正常传输失败。`ready` 是只读，失败不会进入 `retry_pending` 的 sticky 写失败规则；不能依靠全局 write journal guard 自动阻止正常结束。

独立复现：`.build/postgresql/test_review_retain_channel.py`，SHA256 `D01CC7AF168247D7179D4938A5E074792B5944386D88F4FA5BB0A2C717B2A38F`，通过既有 PM Linux Python、`scripts/run_tests.sh`、retries=0、拥有者校验随机 PG Schema 与全 SQLite 拒绝 fixture。先使用真实 PG runtime/receipt 和 `RuntimeSessionStore` 入队，再在 captured WorkerRetainQueueRef 的 dispatch seam 将一次 `ready` 交给真实 loopback WebSocket；对端收到请求后 close(1011)，异常沿真实 `_OwnerLink → WorkerRPC` 返回。只替换了 reference/dispatch 接缝，未伪造 is_worker_process，亦未把无认证的局部故障端点说成完整 owner 认证或 managed daemon 验收。probe 名称中的 authenticated 不构成该项额外证据。

日志 `.build/postgresql/review-retain-channel-red.log`：**1 failed、exit 1**，测试 8.48s、文件 runner 9.1s。脱敏红测观测已保留为 `.build/postgresql/review-retain-channel-red-observed.json`（原输出路径后由绿测更新）：

| 观察值 | 实测 |
| --- | --- |
| 线程未处理异常 | `ConnectionClosedError` |
| writer 存活 / HTTP 调用 | `false` / `0` |
| PG canonical 行 | `pending` |
| protected journal pending / sticky failure | `0` / `false` |
| `flush_token_counts()` | `true` |
| 随后真实 PG `execution.finish` | `{"status":"terminal"}` |

影响：一次瞬时读断线便终止当前消费者的持续恢复，无该 consumer 的重试；当前 worker 仍可成功 finish。PG pending 未丢，后续新消费者仍能恢复；本证据不支持“消息丢失”或远端 exactly-once 的说法。enqueue 的同类 socket 确认丢失也不会按当前 catch 附上稳定 request_id，shutdown 的 counts 亦可能越过局部错误报告。

最小建议：在 RetainDB owner-channel 边界处理 SDK 的 `WebSocketException`（至少包含 ConnectionClosed）；enqueue 同时处理实际会原样冒出的 `OSError` / TimeoutError，使原异常携带稳定 request_id。保留 sticky journal 与原异常，不修改 WorkerRPC 的未知提交后禁止自动重发规则，不禁用队列。增加一次真实断线后同 writer 再取 pending 的永久行为回归。Root 已收到本证据并负责实施；本节记录的是初版 bridge 红测，后续修正必须单独列新证据。

### 已落实且未发现新增问题的边界

- `storage_backend` 对真实已采用 worker 优先读取 owner identity，验证显式 home 后返回 owner backend；普通 owner 的配置/secret 路径及冻结 snapshot 选择仍分别保留。Retain queue 先走 `worker_resource`，不会在 PG worker 中绕过 `_owner_only` 自开 PG 或回落 SQLite。
- owner handler 只接受关闭的具名操作与 exact fields；Profile/store/target/Schema/plugin/time/lease 不可由 payload 覆盖。destination 限 64 位小写 hex，是 owner store 内业务分区；远端 session_id 继续合法跨会话，与本报告前述结论一致。
- effects 使用传入的 receipt Connection；同一事务内的 owner `prepare` 重算指纹，PG 生成时间/token/lease/backoff，wire 仅转 fingerprint，worker 恢复 bytes。未引入 HTTP 内持连接或写事务。
- `_send` 在 renew 后新增独立 `owns_claim` 读，真实 PG status/token/lease 和当前 PG 时钟均须匹配。新第三项永久测试实际提交 renew 后丢确认，再在本测试 Schema 使 lease 到期，以另一个合法会话 retake；旧 seq 仍返回历史 True，而 fresh owns_claim=False，旧 token renew/fail/ack 均 False，新 token 不变。初次以同一会话注册两个活 worker 被现有 guard 正确拒绝；改合法跨会话 fixture 没有放宽实现护栏。
- `RuntimeSessionStore` 原有 `_apply/retry_pending/_read_rpc/flush_token_counts/finish` 仍拒绝 sticky failure 或未确认 journal；新队列未清空 journal 或把本地接收当 canonical commit。下面独立 probe 验证了这个窄合同，不等于完整关闭路径已验证。

### 已有证据的准确范围

Root 日志已逐项读取：`unified-task24-worker-retain-port-first.log` 是 Windows canonical runner **6 文件、22 passed、0 failed**，覆盖初版两项 owner command 与原 direct-owner queue/selection 合同；不能代称新增 managed 端到端已通过。`unified-task24-managed-retain-first.log` 后来的真实 managed 文件本身 **1 passed / 47.7s**，该合批总体仍 **3 passed / 1 failed**（旧接管 fixture）；修正后的独立 `unified-task24-worker-retain-lease-green.log` 为 **3 passed / 0 failed**，9.8s。以上是 Reviewer 核对过的 Root 实际日志，不伪称 Reviewer 自己执行。

新 `test_managed_retain_queue.py` 使用普通 `gateway.run` daemon、真正 worker adopt、loopback 模型与实际 RetainDB provider / `_Client`。它在 HTTP 挂起时读到已提交 claimed 行，owner 配置 budget=1 且同 owner 的公开 session.resume 成功，证明该条真实执行没有在 HTTP 等待中占住唯一连接；503 后 pending，原 owner 退出、新 owner 和新会话重放相同正文，最后两行 acknowledged 且正文清除，peer 空、子进程 SQLite audit 无连接。未以改 worker 标志、内存队列或假 `_Client.ingest_session` 替代。这为原 managed owner-only 缺口提供了关键整改证据。

该测试在收到 held HTTP 后即主动 release，未等待超过原 shutdown join=10 秒；它不证明 HTTP 持续到 join 超时后、worker finish/RPC close 与迟到 ack 交界，也没有注入真正 managed 进程的 enqueue/ack 确认丢失。当前设计允许 durable pending 留给下一消费者，不能因有限 join 本身虚构数据损坏；仍需明确观测必要 receipt 在 execution.finish 前结算，未确认时不假 finish。

独立 journal 实证：`.build/postgresql/test_review_retain_pending.py`，SHA256 `110D844D146816646F077D1CDF8B41E857F76579C6A7ADD40C4B04675CBB8919`；相同 PM Linux/canonical runner、retries=0、真实随机 PG Schema、全 SQLite guard。reference/dispatch seam 将 enqueue 实际 PG effect+receipt 提交，再由真实 loopback WebSocket close(1011) 丢确认；observed journal 在磁盘保留原 seq=1、原 NUL/Unicode/False/0/None 消息，canonical 行真实 pending，peer 无行。`flush_token_counts`、`finish`、worker counts read 三者均抛 `WorkerPersistenceError`；显式 `retry_pending` 以原 seq 得到已提交 receipt 后，仅剩一条 pending、sticky 清除，随后才可 finish。日志 `.build/postgresql/review-retain-pending.log` 为 **1 passed / 0 failed、exit 0**，10.6s；脱敏 JSON 为 `.build/postgresql/review-retain-pending-observed.json`。这是 Reviewer 自己运行的写失败合同窄证据，无真实 managed 生命周期/HTTP 关闭观测，不据此关闭上段未验证项。

### 本轮门禁

新增 channel major 已有独立红测，尚待 Root 修正与绿色恢复证据；完整 managed 未确认写入/关闭交界尚未验证。RetainDB 局部结果不外推 metrics：真实 PG managed worker 指标持久化缺失与 config-only 旧 metrics.sqlite3 打开两项原 major 继续保留。Task24 与总体审查结论仍为 **FAILED / CHANGES_REQUIRED**。

## Channel catch 整改后的独立复验

Root 随后只在 RetainDB enqueue、writer loop、shutdown count 的 channel 边界纳入 `WebSocketException`，enqueue 同时纳入 `OSError` 并保留原异常和 request_id；WorkerRPC、protected journal、finish 与 owner-only 规则未放宽。逐行复审该增量未发现新的问题。

Reviewer 用**完全未修改**的原红 probe（上述 SHA256 不变）重新通过 canonical Linux runner 执行，`.build/postgresql/review-retain-channel-fixed.log`：**1 passed / 0 failed、exit 0**，15.0s。实际相同 WebSocket 1011 断线后，没有未处理线程异常，writer 保持存活，原 pending 继续投递一次，PG 最终 acknowledged，flush 和 finish 可成功。绿观测为 `.build/postgresql/review-retain-channel-observed.json`；其中 pending_entries 是无锁获取的较早瞬时值（本次为 1），后续 flush/PG read/finish 均有自己的同步时点，不能将该字段拼成“flush 放行了未确认写入”的原子快照。

新增永久 `test_worker_retain_transport.py` 已读完：read 分支等待真正 PG acknowledged 及 journal 空后再验证；committed_acknowledgement 分支先实际提交 ack，再真实 socket 丢确认，要求 writer 存活、sticky journal 阻止 flush/finish、shutdown 不清空 journal、同 receipt 恢复不再发 HTTP。它使用 fake Client 观察传输次数，只能作为通道窄合同，与实际 provider `_Client` 的 managed 测试分别陈述。Root 首轮新增批次的 read 分支曾以 sent 先出现且 journal 暂为空作为完成条件，因 ack 尚未入 journal 得到 claimed；最新改等 PG acknowledged 是正确修复观察竞态，未降低持久化断言。

另核对 Root `unified-task24-managed-retain-linux-first.log`：实际 Linux **2 文件、4 passed / 0 failed**，76.4s，含三个 owner command 与原 managed HTTP/restart 一项。这仍是加入 abandon_http 参数之前的四项范围，不能代称新关闭分支已过。

最新 `test_managed_retain_queue.py` 增加 `abandon_http=True`：保持 HTTP 未释放，通过真实 admission/worker terminal 与实际 worker exit audit 后才结束原 owner，要求 PG 原行仍 claimed；在拥有测试 Schema 中使该行 lease 过期，再由新 owner / 新会话恢复。保留原 join=10 秒及真实 HTTP，没有关闭队列、伪造 worker 标志或延长生产期限。移除的是错误从 daemon stdout 寻找 worker 私有日志警告的断言，当前仍保留实际 HTTP 未释放、旧 worker 已退出及 PG claimed 状态，因此没有用删业务结果断言绕过关闭合同。新批日志 `unified-task24-retain-lifecycle-green.log` 在本次复审时只结算了 transport 两项，managed 两参数仍运行；不能因日志名含 green 计为已完成。

上节 channel major 的**局部修正已获独立红→绿**；必要写入 sticky guard 已有独立真 PG 正例。完整新增 managed 关闭分支及这轮 Root 全文件门禁仍需按最终日志另行结算；metrics 两项 major 保留，总体仍 **FAILED / CHANGES_REQUIRED**。

## 最终 enqueue 分支与局部门禁复核

继续只读核对 `c0558e9c13..工作区` 的全部六个生产文件最终 diff（包含已暂存的新 `worker_retain_queue.py`；使用 `git diff HEAD` 避免漏读已暂存内容）。相比前次独立绿色复验，没有新增生产语义改动；未发现新的生产问题。Root 新增永久 transport 第三项 `committed_enqueue` 的合同成立：先用真实 PG 提交 enqueue effect 与同序号 receipt，再通过真实 WebSocket close(1011) 丢确认；`queue.enqueue` 必须抛 SDK 原异常并携带稳定 request_id，protected journal 的原 payload 必须同 ID。后台 worker 因 sticky 不得发 HTTP，flush/finish 均拒绝，shutdown 不清 journal；显式同 receipt 恢复后 canonical 行仍 pending 且正文保留，不得误记 acknowledged。最终生产实现使用 bare raise 保留原异常，未增加 WorkerRPC 自动重发、清空 journal 或 owner-only 豁免。测试只使用窄 transport seam，未自称完整 managed RPC 认证验收。

已重新逐项读取以下 Root 日志，区分最新结算和仍运行的批次；这些是核对 Root 运行产物，不冒充本 Reviewer 新执行：

| 日志 | 已结算范围与结果 |
| --- | --- |
| `unified-task24-retain-lifecycle-green.log` | Windows 2 文件 **4 passed / 0 failed**，107.4s：read/ack 通道两项、实际 managed HTTP 返回失败 / HTTP 一直未 release 而原 worker 退出两项 |
| `unified-task24-retain-request-id-green.log` | Windows 2 文件 **6 passed / 0 failed**，19.2s：Core 三项、transport read/ack/enqueue 三项 |
| `unified-task24-retain-sqlite-contracts.log` | Windows 6 文件 **44 passed / 0 failed**，8.6s：无 PG 驱动 SQLite、owner wiring/冻结选择/统一选择、原 RetainDB provider/plugin |
| `unified-task24-managed-retain-linux-first.log` | Linux 原 2 文件 **4 passed / 0 failed**，76.4s：加入 abandon_http 前的 Core 三项及实际 managed 一项 |
| `unified-task24-retain-owner-linux-final.log` | 最终 Linux 七个 PG 文件已完整结算：**19 passed / 0 failed**，206.1s；包含最新 Core/transport/managed 两参数及原队列/并发/事务/进程合同。曾观察到的六文件 17 passed 是中途状态，已由此最终 summary 取代 |
| `unified-task24-retain-owner-checks-final.log` | 最终局部静态检查 **14 checks ok**；9 个 Python 文件相对 c0558e9c1365 的 health 为 **0 blocking / 0 advisory**，不外推为完整分支全部文件复查 |

最新真实 managed 两参数均通过，补足前节“HTTP 超过原 join=10 秒、未释放情况下原 worker 已退出、持久 claimed 由下一 owner/会话恢复”的局部未知项。初版 owner-only 缺少实际 RetainDB 消费者及本轮发现的 channel major 在上述范围内已有整改证据；未发现通过停用 sync_turn/HTTP、替代内存队列、放宽 SQLite guard 或改生产期限取绿。更广并发/目的地/事务/进程合同须与七文件最终批结果一同保留，不能按单个 managed 测试泛称所有故障已经穷尽。

RetainDB 本轮结果不关闭全域指标门禁：owner identity selector 的变化须在原普通 PG opt-in 指标持久化/重开/peer，以及 config-only 保留旧 metrics.sqlite3 的真实反例中重新证明；既有两项 metrics major 尚未获得完整实际整改闭环。当前最新源码还需要统一冻结后完成全域 PG/原生/故障复验、重新构建并测试最终独立发行载荷、补齐适用平台证据及独立最终复审。本报告只确认列出的 RetainDB 局部证据，总体仍 **FAILED / CHANGES_REQUIRED**。

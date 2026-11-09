# Unified database：develop 合并协作领域独立审查

审查状态：**CHANGES_REQUIRED**。本轮仅检查合并影响，不实施、stage、commit、运行测试或操作数据/Schema。

## 范围与输入

- 三方：ours `264dc20077`，incoming `781dc1e05fc7e781b714790d6ea2ab459835b3bb`，base `ff09cead02`；检查对象为文本冲突解决后、语义适配仍进行的实际工作区。因此下述行号和遗漏以本轮读取时为准，不能当作之后修复已复审。
- 读取 root/gateway/cron/TUI 规则、统一数据库既有设计与计划约束、原三方 conflict 清单和本轮相关实际 diff。追踪 `gateway/hosted_room*`、`session_group*`、`session_hosted*`，以及 TUI service/driver/peer HTTP、新 Kanban 通知消费者和所选 PG 操作/表。
- 本轮读取的 `pg-merge-initial-contracts.log` 确为五项通过。其五项覆盖 snapshot、transcript cursor、room deferred reopen、binding owner、metadata patch；不覆盖下述 peer 撤销债务、member homes、policy race、Kanban reclaim 或 run close。旧生产 689 项也不能外推到本次合并。
- 下列问题为源码和实际调用参数可以确定的缺口；本 Reviewer 未执行红测，不把静态演算写成实际 PG 失败日志。

## 确证问题

### [major] Peer 路由与持久撤销债务尚无完整 PG 生命周期

位置：`gateway/hosted_room_links.py:130`；`hermes_db/operations/room_links.py:17`；`gateway/hosted_rooms.py:654`、`:677`、`:783` 至 `:883`；`hermes_db/operations/room_authority.py:51`。

直接失败链：新的 `save_room_link` **总是**传 `expiry=room_grant_hard_expiry`，`@room_operation("room_links")` 选出的 PG `upsert_room_link_record(store, *, record, max_links)` 不接受该参数。真实 peer 注册、重新注册、自动续期走 `_save_link → save_room_link`，会 TypeError；不是只有手工调用新 API 才触发。

更完整的遗漏如下，不能仅吞掉 expiry 参数来“修复”：

- 新 `room_has_peer_obligations` 已有 PG dispatcher 装饰器，PG room_links 模块没有同名操作；metadata-only `groups.disband` 在 `session_group_controls.py:282` 直接消费。
- `retire_room_link_records`、`owe_room_grant_revoke`、`owes_room_grant_revokes`、`hold_room_grant_revoke`、`due_room_grant_revokes`、`held_room_grant_revokes`、`settle_room_grant_revoke` 没有 PG 分流，仍直达 Native `_transaction` / `_read_connection`。所选 PG 下现有 guard 会拒绝私有 SQLite；不得通过回退 SQLite 绕过。
- Native 新增 `hosted_room_owed_revokes`（`:154`）；读取到的 PG tables/migrations 没有这张表及其 held/expiry/attempts 等字段。`HostedRoomService` 在 `:392`、`:406`、`:423`、`:473`、`:485`、`:490`、`:494` 真实读取/写入这些操作，涉及 Disband、拒绝注册后债务、后台重试、重启恢复。
- PG `disband_room` 尚未移植 Native `:1399` 的未过期 held 拒绝、过期 held 清理，也未移植 member home 的同事务清除。只让上层先检查仍不足：held 可以在 peer I/O 后、tombstone 之前到达，必须由提交 tombstone 的事务再次检查。

影响：PG peer 注册/续期/删除及撤销恢复不可用；若只补形参或在 purge 时级联丢弃债务，则会遗忘仍有效的长期 grant，违背 incoming 明确增加的 Disband 合同。

历史意图已核对：`78f10d04dc` 不允许 unsigned claim 使真实 grant 的 revoke 变成“已覆盖”；`2bca97130a` 要保留 Disband 期间收到的 grant；`8d588310e9` 要在 Disband 前撤销 retained grant；`5f56c5f674` 要一直重试至 grant 到期。它们不是可省略的新维护功能。

最小建议：给整个族增加具名 Core 操作及显式前向 migration，保留现有 store/room scope 和 fail-closed；按下节的原生语义移植，并通过真实 PG 生命周期、故障和隔离合同再关闭该项。

### [major] 新 member/attempt home 直接使用 Native 私有 SQL，PG 本地 member 提交与 Stop 归属缺失

位置：`gateway/session_hosted_member_homes.py:45`、`:68`、`:81`、`:94`、`:106`、`:113`、`:120`；实际消费者 `gateway/session_hosted_service.py:128`、`:210`、`:219`、`:288` 至 `:308`。

`record_attempt_home` 用 `db._execute_write`，读操作用 `db._read_ctx`、SQLite `?` / `INSERT OR IGNORE`；`_attempt_homes` 又直接联读 Native driver task 表。`PostgresSessionStore` 没有这些私有入口，SessionResource 只把属性转发给它，不能提供兼容。新 source submit attestation 无条件调用 `record_attempt_home`；跨 Profile transport resolve 调用 `record_member_home`。因此不仅历史移动 Profile 才失败，正常 PG hosted submit 也能在新写入处失败。

这些记录不能简单丢弃：incoming `ada04cbd6a` 的目的，是把 stopping/deferred attempt 的 Stop 送回**实际 admitting home**，而不是已移动 Profile 的新 home。新 home 的“无 session”不能证明旧 home 已排空；未记录旧 home 会重新引入提前 Disband/错误 Retry 的问题。

最小建议：提供 scoped 的 member home、attempt home 具名读写，保持 `(room,member,task,execution_generation)` 首次归属胜出、旧活 attempt 保留、结束 attempt 在下一次 submit 剔除、旧版本无记录时 unknown/fail-closed，以及 tombstone 的同事务删除。使用已有 runtime/store scope 和 Core connection；不要公开任意 SQL callback，不能给 PG 加模拟 `_read_ctx`。

必要见证：双真实 Profile/同 room ID 的隔离；admit 于 A 后映射移至 B，B 的空 session 不得确认 A 已 Stop；A 活且不答复须保留，A 确认或确实 absent 后才可结算；generation 重试与重启后记录仍正确。可沿 incoming `test_hosted_room_attempt_home_moves.py` / `test_hosted_room_member_homes_retire.py` 的真实消费者增加 PG 对应合同。

### [major] Native 讨论代次修复没有进入 PG policy 投影，升至 schema 5 后仍会丢新讨论

位置：`hermes_db/operations/room_policy_projection.py:55`、`:61`；对照 Native `gateway/hosted_room_policy_checkpoint.py:263`、`:273`；版本重建 `hermes_db/operations/room_policy.py:18`。

Native 新逻辑只在 discussion ID 仍匹配时删除 thread，并拒绝恢复已被同 thread 更新 user message 超越的旧 Continue。PG `room_activity` 仍按 `(room,thread)` 无条件删线程；PG `continued` 仍直接 `_thread` 回旧 discussion，没有中间新 message 检查。

确定反例：同一 thread 的 D1 user → D2 user → D1 room.activity，PG 会删除 D2 的 thread 投影，Native 保留 D2；旧 D1 Continue 的重放还会把 thread 重新指向 D1。真实 service `prepare_room → _policy_snapshot → plan_next_task` 消费该投影，会漏答 D2 或重规划旧讨论并阻塞其他 thread。

incoming `dc29ecd4c9` 的提交说明明确描述这个 race，并把 `_TRANSCRIPT_SCHEMA_VERSION` 提至 5 来重建旧错误投影。PG `ensure_cursor` 引用了新常量，确会重建，但使用的仍是旧 PG apply_event，故重建本身不能纠正问题。

最小建议：移植两个 scoped Core 谓词，按提交事件 seq 和 policy_thread_key 检查同 thread 后续 user message；保留 room/store scope。用真实 PG 逆序 activity、旧 Continue、已有 v4 投影升级后重放验证最终讨论归属，并保留 Native 原 `test_hosted_room_policy_settle_race.py` 合同。

### [major] Kanban stray delegate 订阅回收在两层都缺 PG 实现

位置：`tui_gateway/session_notifications.py:470`、`:491`；`hermes_state_delegate_children.py:13`；`hermes_cli/kanban_db_notify.py:284`；`hermes_db/operations/kanban_notify.py`。

新 poller 先调用 `delegate_descendant_ids(db, session_key)`，该函数使用 `_session_lineage_root_to_tip`、`_read_one`、`_read_ctx` 和 Native `_collect_delegate_child_ids`，PG facade 不提供这些私有 API，先发生 AttributeError。即使只补前置查询，新的 `retarget_notify_subs` 已经 `@domain_operation("notify")`，PG kanban_notify 模块仍没有同名操作，再次 AttributeError。消费者只捕获 sqlite3.Error，不能变成可重试的旧 Native busy 分支。

已正向核对 `_kbc.connect`：`kanban_db_connect.py:731` 至 `:734` 会在 PG 下返回 `domains.kanban.connect` 创建的 BoardResource，随后由 domain_operation 分流；**connect 本身没有落回 SQLite**。该问题是分流后缺少具名 PG 操作，以及前面的 SessionDB 私有读未迁移。

影响：本应由父会话接收的卡片完成通知仍停留在 delegate ID；新 PG 通知轮询不能完成此业务。incoming `f483ce2667` 的目的，是修复 reserved child 丢 `_delegate_from` 引发的错误订阅归属，不应通过禁用回收或返回空 descendants 保绿。

最小建议：给 descendants 增加所选后端的具名 lineage 读取，保留 compression continuation、delegate/branch 截断边界；给 retarget 增加 scoped Board Core 写操作。保持原 cursor/metadata，目标 key 已存在时目标订阅胜出；所有源移除/目标搬迁同事务，遵守既有 files→Board 写锁和命令结果协议。验证不同 store/Board 的同 chat ID 不被迁移。可用 incoming `tests/tui_gateway/test_kanban_stray_delegate_subs.py` 的完整父会话消费者建立 PG 合同，不只测试数据库 helper。

### [major] Peer Discard 的“查找或关闭未用 admission key”仅 Native 可用

位置：`gateway/platforms/api_server_room_grants.py:291`；`hermes_db/run_idempotency_store.py:15`；Native 新操作 `gateway/platforms/api_server_run_idempotency.py:173`。

`PeerRunsHTTPClient.close_admission`（`:424`）在没有本地 receipt 时请求 `/v1/room-members/runs/close`。实际 HTTP handler 调用所选 `_run_idempotency_store.find_or_close`；PG 类缺该方法，产生 AttributeError/500。新 peer Discard 因此无法得到“从未 admission 且将来也不能 admission”的证明。

最小建议：在 PG 现有 `_transaction` 的 scoped store lock 下与 reserve 竞争，原子 find-or-close；无 run 时持久 closed fingerprint/terminal cancelled 墓碑，重复 close 延长其 MAX_STATUS_GRANT_TTL_SECONDS 保留期，已有 run 时返回原 receipt。不能改成 lookup 后异步 forget，也不能在内存记录 closed。真实 PG 合同须含 reserve/close 竞争、后续相同 key 必须冲突、既有 run 返回、实际 COMMIT 丢 ACK 后重放及同 key 不同 store/scope 隔离。incoming `test_session_group_closed_admission.py` 的完整 Discard 消费链也须验证。

### [major] “目标确认 run 不存在”后的远端 receipt 删除缺 PG 操作

位置：`gateway/hosted_rooms.py:1046`；`tui_gateway/hosted_room_peer_http.py:681`、`:696`；`hermes_db/operations/room_links.py`。

新 Native `drop_remote_run_receipt` 已被 `@room_operation("room_links")` 包装，但 PG 模块没有该函数。显式 Retry 的 `refresh_receipt` 收到目标真实 404/run_not_found 时，调用 `forget_receipt → drop_remote_run_receipt`，确定会在 PG getattr 失败。service `_close_missing_peer_run` 也消费这条删除链，故 receipt 丢 ACK / admission 被拒后留下的旧 run handle 无法正常清理恢复。

最小建议：在 scoped Core 事务内按完整 REMOTE_IDENTITY **和旧 run_id** 条件删除，禁止删掉并发替换的新 receipt；只有实际删除时在同一连接 capture_transition_locked。保留 False 的幂等返回和 COMMIT 不明后的重放语义，验证同 room/task/generation 但不同 store/member/authority 的行不受影响。不能只清客户端 `_runs` 内存缓存。

## Held / owed PG 移植的必要合同

这是第一项整改的最小语义边界，不是新增功能提案：

| 层 | 必须保留的 incoming 行为 |
| --- | --- |
| schema | store_id 隔离；`(room,member,grant_digest)` 唯一；target_url/grant/expires_at/attempts/next_attempt_at/created_at/held。债务越过 room purge，不能使用 room 级删除级联；store 退役仍服从既有全 store 生命周期。旧 PG 显式前向升级，不改历史 migration。 |
| token 与 expiry | 精确 token digest 区分债务；unsigned payload 只调度该 token 的 status horizon，最多 now+30 天。它不能证明同 scope 另一个真 grant 已无效；重复 token 保持幂等，不以伪造更长期限挤掉原债务。 |
| 替换路由 | 较长期旧 grant 被较短新 grant 替换时，同事务保存 held 旧 token；成功发布的新 token 若本有同 digest hold，要按原语义移除该 hold。稳定 cancellation_scope_id/trace_id 不因重新注册改变。 |
| Disband | peer revoke I/O 在事务和 policy/publication 锁之外；完成后只清本轮确认 revoked 的 held digest；并发新到 held 必须让 tombstone 事务拒绝/重试。route 删除和 debt 转换必须原子；member homes 清理与 tombstone 同事务。 |
| retry / expiry | held 不进入普通 due；未确认 revoke 留存并以结束时点退避；仅确认已撤销/未知或 token 已过期才清。无债务的 idle cycle 保持只读，不能每 tick 取写锁。 |
| 容量 / 并发 | 每 member 4、每 store 512；满额不抛弃 live grant，caller 走原已确认 revoke 或明确失败。遵守现有 scoped store quota lock→room row→具体记录的顺序，避免 capacity/Disband/替换竞态。 |
| 故障 / 重启 | 事务回滚不丢旧 route/debt；真实 COMMIT 后丢 ACK 重放不增殖债务、不误删新 token；重启实际 loader/supervisor 可读回并继续付债，不用只读 helper 的绿代替后台消费。 |

## 已检查的局部适配与限制

- 当前新增 PG `mark_attempt_indeterminate` 使用既有 scoped store lock、active lease、精确 execution/cancel generation 和同连接 work capture；`defer_unconfirmed_stop`、`reopen_deferred_task` 复用同一 fence/change 管道，字段在既有 task schema 中。此轮源码检查未发现该三项新增阻塞缺陷；五项日志中的 room case只证明其特定 reopen 成功链及 peer store 反向读取，不代表全部停止/竞争/丢 ACK 消费链。
- 新 route_identity 从已有 scoped route 读取稳定 pair，再按 home installation/room/member 派生，未在该新入口发现强制 Path 或 SQLite 回落。endpoint/Profile attestation 的新 read/stop 限制不能借 PG 适配放宽。
- 维护/通知异常传播和 API StorageError 映射也须随真正 PG 消费合同核对，不能把 AttributeError 改为空列表、把 storage outage 当“无旧 home / 无 owed / 无订阅 / run 不存在”。

## 门禁与结论

当前六项均为未处理 **major**，足以要求继续合并语义整改；未报告无依据的 blocking。没有运行新红测，故后续必须为每项取得当前真实 PG 消费、scope 反向、必要竞争/故障/恢复证据，并保留对应 Native 行为合同。

19 个文本冲突解完和当前五项绿都不足以关闭这些无冲突文件带来的漏迁。旧 PG 689、旧 Native 补测及旧独立发行证据不覆盖新语义。完整合并验证、最终独立审查和既有适用平台限制仍单列。

**本次合并不批准：CHANGES_REQUIRED。** 仅本审查报告可由本 Reviewer 修改；实现和测试整改由父任务负责。

## 六项端口补齐后的独立增量复审

本节更新前述初审的“当前六项未实现”状态，保留原始缺口证据。复审仍只读生产/测试、日志和新 migration，没有代跑、连库、stage 或 commit。

### 已补齐的实现与正向证据

本 Reviewer 逐项读取了新 `room_revoke_debts`、`room_member_homes`、0030 migration、room_links/authority/policy_projection、retarget、find_or_close、lineage 及原消费入口的分流，确认初审六个缺方法/错投影问题均已有对应实现：

| 初审项 | 实际补齐及本轮检查结果 |
| --- | --- |
| 撤销债务 | 全族经 room_operation 分到 Core；表为 store+room+member+digest 键，无 room 级联 FK；room retention 不删该表。所有债务写操作和路由替换共用 scoped store quota lock，Disband 在同锁/room row lock 下检查 held，再同事务写 tombstone、清 home。retire 只删本轮 revoked digest 或同事务释放 held；idle due 查询无过期记录时不取写锁。**下述非有限期限边界仍有 major，不能把该项整体关闭。** |
| Member/attempt home | 真实 SessionResource/PG facade 分流到具名操作；每个 key/read、driver task join 和删除都有 store scope，prefix 使用 autoescape；写用同一 room store lock，attempt 首次值 on-conflict 保留，结束 attempt 按当前 generation/status 剔除，tombstone 的同连接 forget 不会删其他 room/store。没有新增任意 SQL callback。 |
| Policy | room_activity 删除含 discussion ID；continued 按 source/event seq、同 store/room/thread 的 user message 拒绝旧重开；未把其他 thread/room 的消息算入 fence。 |
| Kanban | 前置 descendants 已有 PG session lineage 读分流，retarget 已按 scoped Board 选择、ASCII platform_key 比较、目标冲突保留原 owner 行、原 cursor/metadata 搬迁后删旧 key，并在现有 BoardResource 写锁/receipt 管道内返回结果。未见新的 SQLite 回落。 |
| Admission close | find_or_close 与 reserve 共用 PG `_transaction` 的 sessions 独占 store lock；closed fingerprint/随机 closed run ID/terminal cancelled 持久化，重复关闭延长 30 天 horizon，存在 run 则返回原记录；store 与 API scope 同时过滤。 |
| Remote receipt | 删除使用完整 REMOTE_IDENTITY **及旧 run_id**；只在 rowcount=1 时同连接 capture work，不误删同 task 的新 run 或其他 store。 |

已独立读取 `pg-merge-current.log` 的 3 文件 **18 passed / 0 failed / 50.0 秒 / exit 0**：其中 collaboration 当时 6 项、data upgrade 2 项、storage 10 项。随后当前 `pg-merge-collaboration-final-candidate.log` 为原 collaboration 完整文件 **7 passed / 0 failed / 45.0 秒 / exit 0**，新增 receipt CAS/store 反向合同与 policy v4→v5 snapshot 重建段已经包含在这份后续终态。

重建测试初次写到无 schema_version 的 cursors 表时，本 Reviewer 已指出；当前实际代码改为 transcript_state 种 v4，另种旧 thread 错投影，再调用真实 snapshot 并要求等于正确状态。本节引用的是修正后的 7 项终态，不用前一份 6 项日志证明这段新代码。

测试准确范围：债务含长 grant 替短后的 hold、Disband 拒绝、held→due、关闭再 acquire、退避和空 peer store；home 含首次归属胜出、关闭再读、Disband 清理；policy 含旧 activity/Continue 逆序及 v4 重建；close 含 reserve 竞争和 store/API scope；retarget 含 owner 胜出和 cursor；receipt 含旧 run ID 拒绝、成功/重复删除和同 ID peer store 保留。它们尚不是完整 service/RPC/HTTP/poller E2E，也没有在本轮加入真实 COMMIT 丢 ACK 注入。

### [major] NaN 期限可绕过 PG 撤销债务的 30 天上界

位置：`hermes_db/operations/room_revoke_debts.py:11`；输入来源 `gateway/hosted_room_peer.py:532`；持久列 `hermes_db/migrations/versions/0030_room_revoke_debts.py:17`；消费 `hermes_db/operations/room_authority.py:66`。

新 `owe_locked` 用 `min(float(expires_at), now + MAX_OWED_REVOKE_SECONDS)`，没有拒绝/归一化 NaN。实际 `room_grant_hard_expiry` 对未认证 payload 的 `status_expires_at` 做 float 转换；合法 JSON 字符串 `"NaN"` 可得到 NaN，且不走“不可读期限使用有限最长 horizon”的 except。`session_group_peers.register` 在 Disband fence/已 tombstone 的分支特意不进行远端 probe，仅核对 token 所读 scope 后 hold/owe，因此没有签名验证替这个持久边界过滤非有限数。

静态确定的最小输入：沿既有 `_grant` 样式构造可 base64 解码的 payload，含当前匹配的 room/member/home/authority scope、`expires_at` 和 `status_expires_at: "NaN"`，交给真实 hold；或直接在现有 PG hold 合同中使用 `expires_at=float('nan')`，随后检查存储值及 horizon 之后的 pending/expiry 行为。本 Reviewer 没有执行该输入，不冒称已有红测。

Python 这里的 min 保留第一项 NaN。PG DOUBLE PRECISION 可存 NaN，且 PG 将 NaN 排在全部有限数之上，因此 `expires_at > timestamp` 一直为真、`expires_at <= timestamp` 一直为假；这与假设 NaN 会自然比较失败或被列 NOT NULL 拒绝不同。[PostgreSQL 浮点类型文档](https://www.postgresql.org/docs/current/datatype-numeric.html#DATATYPE-FLOAT)明确规定该排序语义。

影响的准确边界：该 token 的债务不再受 30 天 horizon 约束。**当 member 持续不可达时**，held 永远阻止 tombstone，普通 owed 也永久占用 per-member/store 配额；超过 30 天仍不会自动清理。若 member 在线并明确回答 grant 无效，既有 terminal-revoke 路径仍可能清掉它，不能把本问题写成所有情形下一定永久无法 Disband。

建议：先用真实 PG 和原 SQLite guard 建立非有限期限合同，再在共享期限读取/持久边界把非有限期限视作不可读，保守采用**有限**的 now+最大 status horizon。不能把它当作已过期立即遗忘可能仍有效的 grant；考虑阻止新 NaN 持久值及已存在候选 NaN 行的安全恢复。覆盖 NaN、正负无穷/畸形 payload 的有界行为，并保留精确 token 和真 grant 互不覆盖的旧合同。父任务已收到该发现并正在取证/整改，当前不能据 7 项绿关闭此 major。

### 当前剩余门禁

本轮未发现上述六个补齐实现的其他确定生产 major；NaN 是新增、可定位的 major。现有操作的事务/锁与精确 key 在源码上有界，但未知 COMMIT 的实际业务恢复仍需证据：不能仅用某操作可重复调用推定 HTTP/RPC caller 收到不明结果后也正确恢复。

下一验证应覆盖真正的新增消费 seams：PG CanonicalHostedRoomService 的 submit/home move/Stop；peer grant 注册、撤销债务后台重启恢复与 Discard HTTP close；父会话 poller 的 descendants→retarget；对应关键主事务实际 COMMIT 后丢 ACK 与反向 scope。可复用已经存在的真实 PG ordinary daemon/authority 场景，选择能证明这些业务结果的最小合同，无需用一串 helper 绿代替，也不要求无依据重复全部测试。

待 NaN 整改和对应证据、当前更广合并回归、最终独立复审及既有适用平台缺口结算后，再按实际 ref 更新状态。本节仍为 **CHANGES_REQUIRED，不批准当前合并**；外部七项主机证据缺口没有消失。

## 非有限期限修复与未执行 consumer 合同的只读复审

本轮读取共享 helper、两个持久入口、0030 CHECK、新 consumer 文件及实际红/绿日志，没有运行任何测试、连接数据库或操作服务。PG 当前恢复/不可用情况仅按现有日志和父任务报告记录，不把它解释为业务已执行。

期限修复源码已覆盖原 NaN 缺口：`hosted_rooms_common.bounded_grant_expiry` 对非有限值返回有限 now+horizon，正常值保留原上限；hard-expiry parser 同样对非有限结果使用最大有限 status horizon；SQLite `_owe_revoke_locked` 和 PG `owe_locked` 均走该持久边界。0030 新表 CHECK 要求 expires_at 严格在负无穷与正无穷之间；根据已核对的 PG NaN 排序，NaN 也不能通过。它没有把不可读 token 当已过期立即遗忘。

证据边界：`pg-expiry-and-oneshot-red.log` 保存 nonfinite parser 的 **3 个真实断言失败**（另有不属本缺口的 surface-flow 失败）；不能把这些 parser 断言称为 PG 已存入 NaN 的证据。后续 `pg-expiry-storage-red.log` 为 **0 passed / 3 fixture errors**，在连接获取阶段 StorageUnavailable，未运行存储业务。`native-expiry-and-entrypoints.log` 为 **3 文件 / 14 passed / 0 failed / 17.9 秒**，其中期限三参数全部通过。结论是原 major 的源码整改与 Native 正向见证已有，**真实 PG 持久、CHECK 和到期恢复尚未验证**，不能关闭 PG 门禁。

### [major] 正常 API 的 ProfileRunStores 缺 find_or_close 转发

位置：`hermes_db/run_resources.py:15`；实际创建 `gateway/platforms/api_server_runs.py:261` 至 `:262`；调用 `gateway/platforms/api_server_room_grants.py:291` 至 `:292`。

前节底层 PostgresRunIdempotencyStore 已有 find_or_close，但正常 APIServerAdapter 使用的是 **ProfileRunStores**。当前读取该类只有 reserve/lookup/status_for_run/extend_retention/owns_run 等转发，没有 find_or_close。真实 close HTTP handler 对这个正常对象取方法，必然 AttributeError/500，尚未进入底层事务。初审 admission close 的业务缺口因此仍未完全接通；仅底层七项绿不能关闭它。

新增 `test_merge_collaboration_consumers.py:36` 的首段保留正常 adapter，通过真实 operator Discard → peer close HTTP 进入此处，能够暴露这个接口遗漏；本 Reviewer 未执行，不声称已有该测试红日志。后半段 `:96` 才把 adapter store 替换为直接 PostgresRunIdempotencyStore(db)，不会修复首段入口。

最小建议：在 ProfileRunStores 经现有 `_for_scope(scope)` 进行可信当前请求 home 绑定后转发，保持其同 scope 不得改投其他 Profile 的策略。不能仅透传到 launch store。DB 恢复后运行原完整 consumer 合同，并验证 foreign request scope/同 key 不影响 owner tombstone；已有 run 返回与延迟 POST 冲突仍须真实 HTTP 结果。

### [minor] 新 HTTP 测试的 setup 异常未被资源清理覆盖

位置：`tests/hermes_db/postgresql/test_merge_collaboration_consumers.py:52` 至 `:65`、`:101`。

adapter、CanonicalHostedRoomService、AuthorityConnection 的创建及 `await peers.serve` 都发生在 try 之前。若任一步失败，当前 finally 不会关闭已经创建的 run/response stores；外层 closing 只释放显式打开的 db，不替代 adapter 自有资源。serve 内若 server 已启动后 setup 出错，也不在此 finally 的保护范围。该路径与当前存储恢复状态尤其相关，但本轮未执行失败注入，不能把它写成已观察泄漏。

建议将每份资源从成功创建开始纳入同一异常安全生命周期，正常/断言失败/setup 失败都依次关闭 HTTP、run 与 response 资源。测试没有启动 HostedRoomRuntime worker，未凭空要求停止一个不存在的后台服务。

### 新 consumer 测试的准确覆盖边界

- Kanban case 调用真实 `_collect_kanban_notifications`，不是 mock descendants 或数据库 helper：确实串联 parent/child lineage → stray reclaim → retarget → claim cursor，并以再次采集为空及 peer Profile 为空校验。它验证的是生产 poller 的 collector seam，没有启动后台通知循环或 notification turn，不能如此表述。
- HTTP case 使用真实 loopback TestServer、原 authority control、peer invite/register/Discard 和 PG persistence；仅把 `_execute_run` 设为 inert，以防延迟 POST 真正执行模型。关闭 key 后要求 delayed POST 发生 idempotency conflict，目标 `_run_statuses` 为空。该正向场景有意义，但尚未运行。
- 后半段只重建 RunStore facade，底层仍是同一个 SessionStore/transaction pool；不能称进程重启或完整独立资源重开。建议按正常 ProfileRunStores 工厂重新 acquire 后继续 HTTP 检查，避免绕过此次遗漏所在的真实路由层；保留同 owner scope 的持久结果与 peer 反向合同。

当前新的确定生产 major 是正常 API 的转发接口遗漏；NaN PG 存储整改待验证，test cleanup 为 minor。consumer 合同、未知 COMMIT 恢复、更广合并回归与外部七项平台证据仍未结算，继续 **CHANGES_REQUIRED，不批准合并**。

## PG 恢复后：typed ref / router / 真实消费者的有界结算

本轮仍只读，无测试、DB、实现、stage 或 commit 操作；仅更新本报告。HEAD 仍为 ours `264dc200772a`，合并适配在工作区进行，后续全局审查须核对最终冻结 ref。

### 实际日志及不能改写的原失败

| 证据 | 独立核对结果与边界 |
| --- | --- |
| `pg-merge-restored-contracts.log` | 原四文件总批 **29 passed / 1 failed / 108.4 秒**，不能称整批绿。其中 storage **16 pass**、collaboration **10 pass**（含 NaN/±Inf 的真实 PG 持久保留及上界后清理）、data upgrade **2 pass**；consumer 当时 **1 pass / 1 fail**。 |
| `pg-http-type-diagnostic.log` 等中间记录 | 原 HTTP 注册失败经捕获异常定位到 Path 强转；后续 owner/fixture 与请求 Profile 诊断失败也保留，不用最终绿改造这些现场的原因。 |
| `pg-http-owner-profile.log` | 当前完整 consumer 文件 **2 passed / 0 failed / 14.9 秒 / exit 0**，含真实 operator Discard→HTTP close、正常 ProfileRunStores 工厂资源重取、延迟 POST 冲突以及实际 Kanban collector。 |
| `run-wrapper-scoped-contract.log` | 完整资源选择文件 **5 passed / 0 failed / 9.3 秒 / exit 0**。实际 fixture 是声明为 offline Core 的 SQLite harness；证明 router 选择/拒绝/重取行为，**不是五项真实 PG 证明**。真实 PG HTTP 另由上一份支持。 |
| `pg-linux-sdk-restored.log` | Linux **11 文件 / 32 passed / 0 failed / 160.4 秒 / exit 0**，含实际 SDK/crypto/faults 与完整单后端子进程。`test_single_backend` 分别新进程 write/read、PID 不同、业务 SQLite 连接尝试为 0。该证明不自动扩展成新增 HTTP Discard 跨进程恢复或后台 poller turn。 |

SDK 的 candidate-source 记录为 tree `4533da2a336d8763dab4e38fc6caaf52442f281e`；在本轮限定文件中，它与当前仍有 peer_http 及 consumer 测试差异。因此 SDK 32 项不冒称覆盖随后 typed-ref 修正；该修正的当前真实正向证据是 Windows consumer 两项。最终发行/全域结算仍须使用最终实际来源。

### 可以关闭的局部缺陷

- **NaN major 局部关闭。** 共享 parser/helper、两个持久边界和 PG 有限 CHECK 已审；collaboration 10 项现在包含真实 PG NaN/正负无穷保留至有限 horizon、之后清理为空的成功断言。旧 parser 红与 DB 不可用的零业务错误仍保留，但不再把当前 PG 非有限期限列为未修复。
- **ProfileRunStores 缺转发 major 局部关闭。** 当前 `run_resources.py:95` 经 `_for_scope` 转发 find_or_close，保留原 home/store/API scope 的拒绝规则；offline routed owner/foreign refusal/resource reacquisition 和实际 PG HTTP consumer 均有正向结果。未改成 launch store 直取。
- **Peer receipt typed-ref 缺口局部关闭。** `PeerRunsHTTPClient.__init__` 与 `bind_receipt_store` 现使用 normalize_location，DbPath 包含 RoomStoreRef；不会对 PG ref 强制 Path。ref 的 profile_home/store_id/target 等值比较仍保护“不可换绑定”，真实注册、服务重建 loader、Discard 和延迟提交路径已经经过当前生产入口。没有用清空 receipt store 绕过。
- **原 adapter setup 清理 minor 已整改。** 当前 consumer 从 adapter 成功创建后即注册 ExitStack 回调，后续真实 owner 初始化或 serve 抛错时也能释放其 run/response acquisition；HTTP 建立后由 finally 关闭。先前“try 前创建 adapter 导致其资源无清理”不再是当前事实。下述新增真实 runner 的自有资源仍须另行处理。
- 初审六个缺方法/投影差异均已有对应实现和前文指定的局部合同；本轮未发现另一处确定生产 blocking/major。这里关闭的是具体缺陷，不是批准整个合并或宣称所有新增 lifecycle 已完整验收。

### [minor] 新真实 runner 的自有 acquisition / cron owner 尚未清理

位置：初读 `test_merge_collaboration_consumers.py:67` 至 `:70`；真实初始化 `gateway/run_runtime_init.py:37`、`:164`，`gateway/session.py:793`，`gateway/session_authority.py:1493`。

当前 fixture 为修正真实 owner 语义而创建 GatewayRunner。其 SessionStore 构造会打开并持有自己的 `_db_handles`，runner 又持有 `_session_db_handles`；initialize_session_authority 还通过 session_cron.bind_owner 将 authority 放进模块 `_owners`。现有退出回调只释放 API adapter 和显式 with 打开的 db，没有释放 runner/SessionStore 各自 acquisition，也没有 unbind。进程结束可掩盖它，单文件绿不证明引用已按拥有者释放；本 Reviewer 未执行故障或泄漏探针。

最小建议已反馈父任务：使用生产既有顺序 `runner.session_store.close_all_db_handles()`，再 `runner.close_all_session_db_handles()`（生产 shutdown `:2091` 至 `:2095`；会跳过 borrowed 并按 refcount 释放），并对本 authority 调用 session_cron.unbind_owner；如保留 owner connection，则 await 其 close。应从成功创建开始注册清理，不调用全局 registry close_all、不裸关他人共享底层句柄、不启动/停止本用例未启动的 worker。本项是测试 fixture 的 minor，不重新上升为生产 major。

### 仍未证明的范围与当前结论

当前 HTTP case 后半已改为正常 **ProfileRunStores 工厂**资源重取，真实 owner 来自 initialize_session_authority，DEFAULT_DB_PATH 修正恢复 runtime Profile 选择，没有换成别的业务后端。它仍运行于同一测试进程；没有宣称 HTTP Discard 的跨进程重启。Kanban 验证仍精确到真实 collector seam，不能称后台通知循环/turn 全链路。

新 peer debt/close/typed-ref 的真实 COMMIT 丢 ACK 后 caller 恢复、Profile 移动后的实际 member Stop、后台 owed retry 重启等，仍须由匹配这些语义的合同或实际更广场景结算；Matrix fault 与旧 689 项不能自动替代。总体合并回归/最终来源/独立终审和七项非 WSL 适用主机证据也继续单列。

结论：已证实局部缺陷按上文关闭；当前未发现未修复的本范围生产 blocking/major，仍有 fixture minor 与明确验证边界。**全局继续 CHANGES_REQUIRED，不批准当前合并。**

本轮落文后的只读增量核对：父任务已在 consumer `:68`、`:69` 依次注册 runner handle sweep 与 SessionStore sweep，ExitStack 的 LIFO 执行正好先 Store 后 Runner；`:72` 注册本 authority 的 unbind_owner。该 minor 的源码整改已补齐，未触及全局 registry 或其他 Profile 资源。本轮已读的 HTTP 两项绿早于这次 cleanup 增量，不能借旧日志声称新 callback 已执行通过；后续针对该完整文件的正常复验即可结算，不另要求无依据的全域重跑。当前剩余为所列验证边界与全局门禁。

## V2 runtime 最终限定复审：本地合并整改结算

范围保持 develop `781dc1e05fc7` → feature ours `264dc200772a` 的协作/Kanban 合并影响。本 Reviewer 对 runtime tree `95242301fef57260b46accb5adf65387d816699a` 与当前工作区执行了只读来源比较，排除 tests/docs 后 **diff=[]**；没有把树对象误称为已创建的 merge commit。新 v2 四套载荷的 candidate-source 也指向该 tree。本轮只读、只更新报告，未测试、连库、实施、stage 或 commit。

### 新增合同的实际含义

- **真实后台付债与清理**：当前 consumer 在 Disband 后收到 late registration，先断言真实持久 debt 存在，再 `service.start()` 启动原 supervisor；没有直接调用 retry helper、没有替换 HTTP revoke。原后台维护走 actual peer HTTP 清掉债务，10 秒业务窗口不变，finally 真实 `service.stop(timeout=5)` 必须返回 True。测试未把恒定 status 回答当作“线程已运行”证据；运行和排空由真实 start/stop 和持久结果证明。其 ExitStack 同时覆盖 adapter 资源、Store→Runner 的 refcount sweep 与本 authority unbind。
- **新进程恢复**：`test_merge_process_recovery.py` 的两个参数均分别启动 write/read 两个 Python 子进程，比较实际 PID 不同；两个子进程在导入业务代码之前安装 sqlite3.connect audit 拒绝。关闭键使用正常 ProfileRunStores；第二进程 delayed reserve 冲突且仍读到 closed。债务由第一进程写，第二进程从 PG 读回 exact token/room、attempts=0；另一个 store 的同 key 可独立创建、债务为空。该合同证明闭键和债务的跨进程持久恢复，债务的“重新读取”不能单独表述为后台付债，后者由上一项独立覆盖。
- **真实 COMMIT 丢 ACK**：`test_merge_commit_recovery.py` 在 engine dialect do_commit 中先执行原 COMMIT，再首次抛 psycopg.OperationalError，调用方必须收到 UnknownCommitError，且 fired 有断言。关闭键的 router 预先创建；路由域的 schema 探测只读，未见会在这两个待测主写之前消费注入的预检 COMMIT。随后重取正常 router 仍 closed，迟到 reserve 冲突；短 grant 替换的重放仍保留旧长 token 恰好一条、路由为 short。没有在 COMMIT 前抛错冒充确认丢失，也没有仅期待异常而省掉持久结果。
- **Collector 的旧边界保持**：Kanban 新消费合同依然是真实 parent lineage→retarget→cursor claim；不把它改称后台 notification loop/模型 turn 全链路。新增进程合同也不被扩大成完整 daemon/gateway 重启验收。

### 最终已读终态

| 日志 | 终态 |
| --- | --- |
| `pg-http-supervisor-final.log` | consumer 完整文件 **2 pass / 0 fail / 16.2 秒**，含最新资源清理及真实 supervisor 付债 |
| `pg-merge-process-recovery-corrected.log` | **2 pass / 0 fail / 15.9 秒** |
| `pg-merge-commit-ack-recovery.log` | **2 pass / 0 fail / 9.2 秒** |
| `pg-merge-final-contracts.log` | 6 个完整文件跨文件 **-j1** 同批 **34 pass / 0 fail / 162.0 秒**；16 storage、10 collaboration、2 consumer、2 process、2 upgrade、2 COMMIT；文件内原竞争/期限/guard 保留 |
| `pg-interrupted-files-restored.log` | 原四个中断 PG 文件 **75 pass / 0 fail / 371.9 秒**；原失败历史仍留账 |
| `native-peer-http-regressions.log` | Native peer HTTP/transport/admission/recovery/Discard 六文件 **75 pass / 0 fail / 45.8 秒** |
| v2 独立发行 | Windows 两文件 **4 pass / 0 fail / 2 Linux 平台 skip / 28.4 秒**；Linux SQLite 发行/SDK **4 pass / 0 fail / 14.2 秒**；Linux PG 初始化 **2 pass / 0 fail / 19.7 秒**。不把 Windows skips 算为当地执行。 |

前节 Linux SDK 11 文件/32 项的正向证据继续保留；v2 发行已覆盖此前 tree4533 后的 runtime 差异。旧 restored 29/1、parser 红、DB fixture error、typed-ref 及 owner/profile 诊断记录均不改写成绿色。

### 问题处置与本地合并门禁

本范围已报告的六个合并遗漏、NaN expiry、ProfileRunStores 转发、typed-ref 输入和两个 fixture cleanup 问题，均已有对应源码整改与匹配的当前正向合同，**局部关闭**。本 Reviewer 未发现未处理的生产 blocking/major 或剩余 cleanup minor。上述跨进程/COMMIT/supervisor 补充填补了本报告明确要求的关键新语义见证；未要求所有可能排列穷举。

最终静态日志本轮已返回：`checks-staged-final-candidate.log` 为 **15 checks，FAILED: ruff**；health **1045 文件 / 0 blocking / 0 advisory**。唯一 ruff finding 为新 `test_merge_process_recovery.py:67` 的 PLW1510（subprocess.run 未显式传 check）。已通知父任务补显式 check=False，保留后续 returncode 断言；这是 test-only 修正，不改变上述 runtime tree 或业务合同。**在其最新静态终态转绿之前，本地合并门禁仍为 CHANGES_REQUIRED**，不能写成全部检查通过。

就协作语义和已读验证而言，本轮 develop→feature 的本地合并整改已达到本 Reviewer 可接受范围；待这个明确的静态门禁闭合后，可接受该有界整改，不需要为 test-only 显式参数改动重跑 34 项业务。该局部判断不替代其他分域独立审查，也不是推送/发布/合并远端授权。

**整体 Task24 仍有七项非 WSL 适用主机证据缺口，不能宣称全系统统一 PG 已完成、全域 APPROVED 或 READY_TO_MERGE。**

## V3 增量核对（全目录终态待结算）

V3 runtime tree 为 `bb811be4a8132bcdb52190ab730ae1ab329b8512`。相对 v2，唯一生产差异是 `repositories/messages.py` 补 NULL display_identity 的有界 backfill；本协作/Kanban/peer 范围没有新增生产 diff，v3 至当前排除 tests/docs 后仍 diff=[]。新增两项旧格式 PG 升级分别验证 oldest/latest 实际分页；本 Reviewer 未替代 foundation Reviewer 的该领域结论。

已读 `pg-merge-final-contracts-v3.log`：六个完整文件 **36 pass / 0 fail / 246.0 秒 / -j1**；原 34 项保留，data upgrade 由 2 项增加为 4 项。PLW1510 的 check=False 已明确添加，`checks-staged-v3.log` **15 checks ok、health1045 0/0**。之后仅发行 probe 的 tests-only receipt 修正，新的 `checks-staged-v3-receipt.log` 尚待终态，不能引用旧绿替它预记结果。

发行原始 v3 现场：Windows 首轮漏选 PG integration（3 pass/1 skip）不算 PG 验收；完整选择重跑 `distribution-source-windows-v3-complete.log` 为 **3 pass / 1 fail / 2 skip / 81.4 秒**，PG 初始化测试在 stdout 空时 IndexError。Linux PG 原轮也有 **1 pass / 1 fail** 的同处失败；其 wrapper 同名后被重跑覆写，父任务已承认，不能引用当前同名绿声称旧红不存在。

已读后续诊断：子进程 stderr 中保留了完整成功 receipt 和到达 receipt 前的阶段标记；实际 `tui_gateway/server.py:218` 至 `:221` 在 projector 导入时将 sys.stdout 改为 sys.stderr。当前 probe 只在导入前保存原 stdout，并将成功/失败 receipt 显式写回该 stream；父进程还新增非空断言，原 PID/epoch/持久化/scope/业务断言、180 秒期限未放宽。这是 probe 回执通道修正，不是生产绕过。

当前 corrected 发行终态已读：Windows `distribution-source-windows-v3-receipt.log` **4 pass / 0 fail / 2 Linux 平台 skip / 45.7 秒**；Linux Native v3 **4 pass / 0 fail / 87.4 秒**；Linux PG v3 receipt **2 pass / 0 fail / 43.4 秒**。载荷源码指向 v3 runtime tree，生产内容没有因 receipt 修改改变。

131 文件 PG 全目录 `pg-suite-v3.log` 仍运行，本段不预记其绿或最终接受结论。待该批和最新静态自然终态后，才更新本轮有限合并接受判断；七项非 WSL 适用主机证据限制继续保留。

## V3 全部指定终态后的最终限定结论

本节取代前节“等待全目录/最新静态”的中间状态，原失败和中断记录保留。只读核对对象为 runtime tree `bb811be4a8132bcdb52190ab730ae1ab329b8512` 加 tests/docs 修正；最终检查排除 tests/docs 后 runtime diff=[]。本 Reviewer 没有实施、测试、连库、stage 或 commit。

已读取完整终态：

- `pg-suite-v3.log`：Windows **131 文件 / 686 passed / 0 failed / 34 skipped，2024.6 秒，-j3**，100% 完成。没有用早期进度代替总汇总；本协作 rooms/Kanban/maintenance、actual consumer、process 与 COMMIT 恢复文件均包含在内。
- 34 个 skip 的原逐文件行已核对：11 个 Matrix/SDK/单后端 Linux 文件合计 32 项，加 distribution_initialization 的 2 项。前者有前述 Linux SDK 11 文件/32 项成功结果（来源边界仍按前节记录），后者有 **v3** Linux PG 发行 2 项成功结果；不能把这些 skip 写成在 Windows 执行，也不能因对齐数量就擦除各自来源/时间边界。
- `checks-staged-v3-receipt.log`：**15 checks ok**；health **1045 文件，0 blocking / 0 advisory，327.6 秒**。因此本报告曾阻塞本地结算的 PLW1510 已整改且实际静态通过，没有沿用 failed 的 final-candidate 日志作绿证据。
- 四份 v3 PM source bundles 的验收为 Windows **4 pass / 0 fail / 2 Linux skip / 45.7 秒**、Linux Native **4 pass / 0 fail / 87.4 秒**、Linux PG **2 pass / 0 fail / 43.4 秒**；真实源码 tree 对应 v3。probe 保存原 stdout 的 tests-only 改动已独立审阅，原业务结果、重开 epoch/PID 和 scope 断言仍成立。
- 定向最终六文件 **36 pass / 0 fail / 246.0 秒 / -j1**、真实 supervisor 付债与清理、两新进程恢复、实际 COMMIT 后丢 ACK 的证据已在前节逐项审查；不再列为“缺少匹配见证”。旧 29/1、发行空 stdout、DB recovery/unavailable、typed-ref、NULL identity 与 ruff 原红都继续保留。

**问题处置：** 本范围初审六项合并缺口及后续 NaN、ProfileRunStores 转发、typed-ref、adapter/runner cleanup 问题均局部关闭；当前未发现未处理 blocking/major/minor。本范围 code-review 的源码、迁移、归属、锁、关键恢复及必要 Native/PG 正向验证已达到本轮合并影响审查要求。

**有限接受：可以接受本轮 develop `781dc1e05fc7` → feature 的本地合并整改。** 此判断限于本报告负责的协作/Kanban/rooms 范围和上述冻结实现，不替代其他分域 Reviewer 的判断，也不授权远端推送、发布或合并。新测试证明的是具体闭键/债务跨进程恢复、真实 HTTP/supervisor/collector 路径；没有扩大成所有 daemon 生命周期排列或后台 notification turn 的穷举证明。

**全局结论仍为 CHANGES_REQUIRED / Task24 未完成。** 七项非 WSL 私有启动页适用主机证据仍缺，本地合并整改接受不等于全系统统一 PG 已完成、全域 APPROVED 或 READY_TO_MERGE。最后合并提交若改变 runtime 内容，必须按实际 diff 重新判断证据是否仍适用。

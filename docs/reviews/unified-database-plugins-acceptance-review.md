# Unified database：插件、指标与强验收独立审查

## 审查范围

- 日期：2026-11-08；独立 Reviewer，未参与被审生产实现。
- 基准：`a875342384`；受审 HEAD：`3febe6fc31`。本报告的首次结论仅针对这一版本；后续整改须另记复审结果。
- 输入：root、plugins、gateway、hermes_cli、tests 的 AGENTS.md，`supercoder:code-review`，统一设计/计划、Matrix 协议核对文档及真实 diff/source。
- 生产范围：metrics/consent/packages/sender；portable plugin KV/CAS/TTL/配额；Discord recovery；RetainDB 持久队列/线程；Matrix CryptoStore/SyncStore、适配器、同步/错误传播、身份与异步边界；这些域的迁移、对应合同、Task22/23 业务探针及发行文档。
- 与其他 Reviewer 的边界：基础设施/运维、Kanban/Rooms 深入业务由其他独立审查覆盖；本报告追踪联合验收与插件消费交界，不替代其结论。
- 实际 SDK：现有 Linux PM 环境中的 mautrix 0.21.1、真实 libolm；核对 `CryptoStore`、`SyncStore`、`PgCryptoStore`、OlmMachine MRO、Syncer 与真实发送/密钥处理消费者。未凭类名推断后端。

## 问题列表

### [major] SDK 内部吞掉真实密钥请求的 PG 失败，仍推进持久同步游标

位置：`plugins/platforms/matrix/adapter_pg_client.py:13`；游标提交点 `plugins/platforms/matrix/adapter_sync.py:53`。

问题：PG Client 的 `_catch_errors` 只能重新抛出已经离开 handler 的 `StorageError`。mautrix 0.21.1 的 `KeySharingMachine.handle_room_key_request` 默认 `raise_exceptions=False`，在内部获取请求方设备以及处理/发送密钥时有 `except Exception`。真实 `m.room_key_request` 处理中的 PG 读取/写入失败可以先被 SDK 吞掉；外层 gather 看到 handler 成功，随后保存 `next_batch`。已有 `test_sdk_swallowed_storage_error_cannot_advance_durable_sync_cursor` 注册的是自定义 ROOM_MESSAGE handler，覆盖不到这个真实 SDK 内层异常边界。

可复现证据：独立诊断使用实际 PG adapter 启动、实际 SDK `handle_sync` 分发 `m.room_key_request`，仅在 PG `matrix_accounts.get_device` 注入 `StorageUnavailableError`。初始持久游标为 `before-real-key-request`；实际 SDK 到达该 PG 读取一次，但返回后没有异常，数据库游标成为 `after-lost-key-request`。标准 runner 输出：

```text
REVIEW_EVIDENCE read_calls=1 raised=False cursor=after-lost-key-request
```

SDK 真实栈为 `key_share.py:114` → `device_lists.py:250` → `PostgresCryptoStore.get_device`；吞错位于 SDK `key_share.py:115`，仅当 `raise_exceptions` 为真才重抛。初始分支的诊断失败，不是 SDK/数据库依赖缺失或 SQLite guard 失败。

影响：数据库短暂失败被确认成该同步批次已经成功，原始密钥请求可能不再由游标恢复，违反设计及 Matrix 协议文档承诺的“存储失败阻止游标推进”。

建议：在 PG 的窄 SDK 适配边界处理实际内部吞错路径，保证批次内任一持久化失败可被同步提交点观察；同时追踪 `handle_room_key_request` 的读取和写入分支、SDK `resolve_trust` 等同类吞错消费者。保留普通协议错误的原隔离语义；不得通过禁用 handler 或把网络处理纳入长数据库事务解决。补真实 SDK handler 的回归，失败时游标保持旧值、解除失败后重放成功。

### [major] 每次反 pickle 新 Olm Session 破坏 SDK 锁前预读的并发发送合同

位置：`hermes_db/matrix_crypto.py:97`（`get_latest_session`）；同类快照入口 `hermes_db/matrix_crypto.py:94`。

问题：本实现每次读取同一持久 Olm 会话都生成新的 Session 对象。真实 SDK `OlmEncryptionMachine.send_encrypted_to_device` 先 `get_latest_session`，再进入 `_olm_lock` 加密和保存；上游 `PgCryptoStore` 的 `_olm_cache` 让同一代 Session 复用同一可变对象。此处两个并发发送可在获得锁之前各读到相同 ratchet 状态的独立快照。后续即使按 SDK 锁串行执行，也会从同一旧状态分别加密，并互相覆盖数据库 pickle。

可复现证据：真实双端 Olm 先完成一次初始加解密；通过 PG 保存发送方账户和会话；使用真实 OlmMachine 同时调用两次 `send_encrypted_to_device`。仅在实际 `get_latest_session` 返回后用 Event 对齐“两次读取均先完成”的合法交错，不替换会话/加密算法/PG 存储。网络 transport 是本地受控回调。发送方报告两条已发送，接收方真实 libolm 只能解开一条：

```text
REVIEW_RATCHET sent=2 decoded=1 errors=['OlmSessionError: BAD_MESSAGE_MAC'] same_session_object=False
```

SDK 真实源码发送入口为 `crypto/encrypt_olm.py:114`，读取在第125行、锁在第126行。另一个消费者 `encrypt_megolm._share_group_session` 也会经 `_find_olm_sessions` 先捕获会话，之后才进入 `_olm_lock` 做群密钥发送，不能只修单一入口。

影响：正常并发密钥/加密事件在发送端被视为成功，接收端却无法解密；串行 round-trip 与 Megolm message_count 测试无法发现该问题。这里按实际错误消息与协议兼容性列为 major，不从此推导未验证的攻击或保密性结论。

建议：为真实 SDK 消费者提供统一、受会话代次保护的协调方案，使同一 Olm 会话的读取、ratchet 更新和持久化不能操作陈旧的独立副本。可在窄 SDK 适配器中把所有相关读取纳入既有 Olm 协调区，或采用明确生命周期/失效语义的兼容会话对象缓存；同时追踪群密钥发送及收取/发送交界。HTTP 与等待仍在数据库事务外。回归须用真实 SDK 并发发送和对端 libolm 逐条解密，并检查重开后的后续消息。

## 实际执行与证据

Reviewer 只创建本报告和被忽略目录内的诊断；未改生产代码、仓库测试或提交。

独立诊断：`.build/postgresql/test_review_matrix_key_request.py`。通过已有 PM Windows 包装器调用实际 Linux PM 环境及 `scripts/run_tests.sh`：

```text
.build/postgresql/full-test-env/Scripts/python.exe .build/postgresql/run_matrix_linux.py --log review-matrix-key-request.log --state task24-linux-state.json .build/postgresql/test_review_matrix_key_request.py -j 1 -s -p tests.conftest -p tests.hermes_db.conftest -p tests.hermes_db.postgresql.conftest
```

结果：退出1，`2 failed, 1 warning in 22.25s`，无重试。完整日志在 `.build/postgresql/review-matrix-key-request.log`，第66–67行包含上述简短见证。沿用实际 PostgreSQL fixture：私有配置只传路径，核对测试数据库及随机 Schema 归属，业务过程 autouse 拒绝全部 SQLite。未打印 DSN/密码、触碰正式 Profile/服务或业务表。最初沙箱无法执行 PM 的账户目录基础 Python；在已授权隔离测试范围内提升后正常运行，这一环境失败不计作业务红测。

其他受审域未发现需要单列的确定问题。静态核对及已有执行日志支持下列具体结论，但不替代尚未完成的 Task24 最新完整回归：

- Metrics 具备 store 锁、原子计数/包水位、持久 consent 窗口与 obs/data 高水位；发送使用冻结身份与精确 claim token，网络/文件操作在借用连接外。合同含真实 loopback HTTP、确认丢失后相同字节重发、opt-out、时钟回拨及双进程聚合。
- Portable KV 按 Profile/plugin/namespace 隔离，单调 namespace revision 防删除/过期 ABA，写锁内执行 TTL/键数/字节配额；SQLite 无 PG 依赖合同与 PG 双进程 CAS/配额合同存在。旧 `plugin_db` 在 PG 先明确拒绝；Discord 游标是真实通用 KV 消费者。
- Discord 具名操作保持终态、attempt 预算、原子 reply+cursor；PG 失败传播而非返回空恢复记录。Retain 使用数据库 pending/claim/ack、拥有者上下文线程和目标摘要；有失败保留、unknown ACK、新进程重放及205条积压证据，不以 Event/内存队列替代持久数据。远端 at-least-once 限制已明示。
- Matrix 其余已审部分包括39协议方法、pickle 外元数据、身份冲突、代次护栏、明确 PG 失败、实际事务/savepoint/取消回滚、旧文件/远端设备保留及共享池异步桥接。上述两个发现说明单方法覆盖和现有 SDK happy path 仍未闭合消费者并发/异常合同。

## Task22/23 与文档证据核对

- Task22 的 `.build/postgresql/unified-task22-pg-accepted.log` 实际为15文件49 passed；随后联合进程与 Matrix 恢复2 passed。联合探针实际写入/重读10领域、两个 Profile、反序新解释器恢复；SQLite audit 包括 URI、内存、别名及直接构造，并有正向拒绝控制。没有发现以禁用指标/插件、内存读取替代或 SQLite 回落通过这一探针。
- 普通 SQLite 验收拒绝 PG 核心依赖；实际 SQLite Matrix SDK 因上游导入 asyncpg 异常类型而保留真实类型依赖，同时明确拒绝 PG connect/create_pool。这是已记录的真实 SDK 依赖边界，不是 PG 连接豁免。Linux 最终4 passed，Windows SDK 平台 skip 有对应 Linux 执行证据。
- Task23 为 `2219b69afd` 的独立 git-archive source-bundle，经 PM 构建 Windows/Linux 的 SQLite/PG 四环境；探针以 `-I` 从载荷/checkout 外启动，业务合同断言原 checkout 不在导入路径，包来自独立 source。Linux 最终6 passed、Windows4 passed/2 SDK平台skip，另有旧0004合法历史向0028升级的新进程补验。无PG包确认 psycopg 不存在。源码发行形态与文档一致，未冒称 wheel/Electron 全发行矩阵。
- 文档站实际 build:fast 成功；日志保留 llms 资产链接及两处其他页面锚点告警，未据此声称无告警发布。
- 这些证据只证明各探针覆盖的路径，不能冲销本次真实消费者红测。整改后的生产版本也不在旧 `2219b69afd` 独立载荷中，必须按新提交重新验证相应发行证据。

## 无法验证项

- 本次独立审查未执行所有 Task24 宽回归；父任务正在进行，其最新结果另行审计，不能使用旧阶段通过数代替。
- 已知7项非 WSL POSIX 私有启动页合同缺适用主机；Windows/WSL 不补齐该覆盖，不得标已通过。
- 未进行公网 Matrix/RetainDB/Discord 服务联调；这里使用真实 SDK/密码学/数据库及本地受控 transport，未声称远端 exactly-once。
- 初始两项 major 的整改和独立复审尚未完成。

## 合并门禁

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 本范围无已证实 blocking | 通过 | 未发现需列为 blocking 的确定问题 |
| 无未处理 major | 失败 | 两项真实 SDK + PG 红测 |
| 设计/验收满足 | 失败 | 失败批次游标推进与并发 Olm 消息不可解密 |
| 相关测试通过 | 失败 | Reviewer 新诊断2 failed；现有绿日志未覆盖这两条路径 |
| Task22/23 既有证据真实 | 通过其所列范围 | 已核对探针源码、执行账本及最终日志；不能外推整改后的载荷 |
| 本范围迁移及可选依赖 | 有既有证据 | 0023–0027、旧0004前向升级、独立无PG安装；最新总体门禁另待 Task24 |
| 全部原生适用平台验证 | 无法验证 | 已声明的7项主机缺口与当前 Task24 状态 |

## 审查结论

`CHANGES_REQUIRED`。两项 major 需要生产整改、真实消费者回归及独立复审；Task24 总体门禁仍须结合其他 Reviewer 和适用主机证据判断。未发现问题的受审域不等于整个分支获准合并。

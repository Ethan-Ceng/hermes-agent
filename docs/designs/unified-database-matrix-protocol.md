# Matrix 统一数据库：实际 SDK 协议核对与验收矩阵

- 关联：[统一设计](unified-database-backends.md)、[Task 19](../plans/unified-database-backends-plan.md#task-19适配-matrix-加密存储完整-sdk-协议)。
- 状态：Task19协议局部验证已通过；系统整体仍须Task20–24验收。
- PM锁定并实际安装：mautrix 0.21.1、python-olm 3.2.16；Python 3.14.9，现有Ubuntu-26.04 WSL真实Linux主机。
- Windows当前未装SDK；项目matrix extra原本仅Linux。新建SDK环境的home/runtime独立，不改正式Profile或数据库服务。
- 实际源码核对：`mautrix.crypto.store.abstract.CryptoStore`、`mautrix.client.state_store.SyncStore`、`mautrix.crypto.store.asyncpg.store.PgCryptoStore`、`sessions`、`account`及OlmMachine MRO各消费者。SDK源码副本/签名清单只在被忽略的`.build/postgresql/matrix-sdk/`，不作为业务测试的source-reading断言。

## 持久化边界

PG实现继承真实CryptoStore/SyncStore，提供39个实际协议方法（CryptoStore 37，SyncStore 2）。每张表、约束、查询和锁包含store_id、稳定Matrix账号身份与本设备scope；账号身份由homeserver/user_id构成，不由文件路径产生。客户端只能访问自己捕获的scope/数据库目标；每次操作校验。namespace代次在首次open持久分配，删除/替换后旧句柄拒绝重建数据。

SDK的PgCryptoStore同时支持SQLite，类名不能作为后端证据。新实现只使用hermes_db Core/同步psycopg共享连接池和显式Alembic迁移，不创建mautrix Database/asyncpg池，不打开aiosqlite或sqlite3。

| 实际SDK方法 | 数据及事务合同 | 必需验证 |
| --- | --- | --- |
| open、close、flush、transaction | 短资源/关闭护栏；SDK设备更新事务原子提交/回滚 | 生命周期、回滚、取消、代次/目标改变拒绝 |
| get/put_device_id、get/put_next_batch | 本设备身份与同步水位，空值/NUL保真 | 重开、跨Profile/设备/账号隔离 |
| get/put_account | 真实OlmAccount pickle及shared布尔 | 真libolm identity/one-time keys重开；错误key不回落 |
| has/get/get_latest/add/update_session | 真实Olm Session pickle与创建/加解密时间 | 双端实际加解密、更新重开、排序、隔离 |
| put/get/has_group_session | inbound Megolm pickle、签名/发送者、forwarding chain、RatchetSafety、收到时间、过期/计数、scheduled | 真Megolm解密、全元数据重开、隔离 |
| redact_group_session(s)、redact_expired_group_sessions、redact_outdated_group_sessions | 删除密钥但保留withheld tombstone；过期按两倍max_age，scheduled/缺metadata依协议处理 | 真密钥删除、GroupSessionWithheldError、范围/时间谓词 |
| add/update/get/remove_outbound_group_session、remove_outbound_group_sessions | outbound pickle、共享状态、次数/期限、创建及使用时间；update只修改精确session代次 | 真密钥加密、恢复计数、旧代次不能覆盖新会话 |
| validate_message_index | scope内(sender,session,index)首次事件/时间身份不可更改 | 同事件幂等、重放拒绝、竞争、重开和隔离 |
| get_devices、get_device、find_device_by_key、put_devices、filter_tracked_users | SDK DeviceIdentity及tracked空设备列表，替换同一用户的设备需原子 | 真实SDK DTO、trust/deleted/name、空列表与未跟踪区别 |
| get_cross_signing_keys、put_cross_signing_key | 当前key可更新、first_seen_key不可替换 | 真实TOFUSigningKey/usage、TOFU换key后first不变 |
| put_signature、is_key_signed_by、drop_signatures_by_key | CrossSigner二元身份及签名，精确范围删除 | 真实CrossSigner、行数、重开及隔离 |
| delete | 沿实际0.21.1实现清理account/Olm/outbound，保留inbound历史密钥等 | 不越过其他账号/设备/Profile，不由PG启动自动调用 |

对应真实合同（均通过标准runner，PG业务过程拒绝所有SQLite连接）：

- `test_matrix_crypto_store.py`：账户/shared/私有one-time keys真实重开、建立实际inbound Olm会话并保存已消耗密钥，设备/同步值NUL、跨Profile隔离、并发重放索引单一胜者。
- `test_matrix_sessions.py`：真实双向Olm、最近解密排序/更新、Megolm完整metadata/ratchet/计数/时长重开、withheld墓碑、全部redaction谓词和outbound移除。
- `test_matrix_devices.py`：SDK DeviceIdentity/trust、tracked空列表、TOFU换key保留first、CrossSigner签名及删除计数、真实事务回滚/savepoint、子任务拒绝、delete保留历史的实际SDK语义、账号/设备/homeserver隔离。
- `test_matrix_faults.py`：取消事务回滚/连接归还、真实COMMIT后丢失确认仍可观察、账号身份冲突、错误pickle key明确失败、dataset退休后旧句柄拒绝重建、outbound旧session不能覆盖新代次、环境切换仍访问拥有者且store变更拒绝。
- `test_matrix_sdk_flows.py`：实际OlmMachine签名设备查询与写事务、request_room_key/forwarded-key接收与剩余目标取消、重开后SDK解密与重放拒绝、SDK outbound加密和计数恢复。网络transport回调核对共享pool.checkedout()==0。
- `test_matrix_adapter_storage.py`：实际Client/OlmMachine连接、重开、真实远端公钥DTO比较、旧crypto文件保留、optional模式PG故障/缺旧设备私钥均中止、实际SDK吞异常红后修复游标合同。
- `test_matrix_recovery.py`及新进程scenario：禁止import asyncpg/aiosqlite、禁止全部SQLite连接、禁止因缺SDK SQL驱动触发PM安装，普通ensure_matrix_deps实际通过，恢复账号/group/sync并由真实SDK重新加密，父进程观察计数持久化。
- 原生Linux `test_sqlite_crypto.py`及新进程scenario：禁止SQLAlchemy/psycopg/Alembic导入，真实SQLite SDK adapter连接、密钥写入及重开解密；不要求PG实例。

具体命令、各阶段失败/整改与最终结果保留在计划Task19。SDK transport使用本地受控回调，未连接公网Matrix服务；密码学对象、SDK消费者与PostgreSQL读写均真实执行。没有借方法存在、类名或.db文件缺失代替业务证据。

## 关键实际值与调用顺序

OlmAccount.from_pickle需要额外shared参数；libolm原生pickle本身不携带这个SDK字段。Session需要creation_time/last_encrypted/last_decrypted；InboundGroupSession另需RatchetSafety、forwarding_chain和过期元数据；OutboundGroupSession需要shared、message_count、期限及两个时间。均保存独立字段，不能只保存pickle后丢掉状态。时间以无损ISO值保存，并为SDK过期/排序建立派生投影，不改变业务值。

SDK的transaction实际出现在DeviceListMachine._fetch_keys：网络query_keys在事务前，事务内为设备签名验证、设备/交叉签名存储及本地find_shared_rooms。适配器state shim的find_shared_rooms只读本机joined_rooms。实现用受控单线程持有该SDK事务的同步Connection，所有方法仍在该线程执行，禁止把Connection跨线程使用；普通方法转到线程并即借即还。SDK网络/模型/投递调用不放进事务，测试需要证明网络边界checkedout=0，不能用默认no-op事务假装原子性。

SDK 0.21.1没有独立持久key-request表/方法。请求等待者是OlmMachine内的Future；真正收到forwarded room key时调用has_group_session/put_group_session持久保存。必须用实际request_room_key及_receive_forwarded_room_key验证真实密钥接收、PG持久化和重开后解密；不凭空新增无人消费的request表，也不把已有持久数据改成内存。

实际Syncer._catch_errors默认记录并吞掉handler异常，且设备/加密handler默认wait_sync=False。PG客户端因此使用实际Client的窄子类：保留普通handler错误隔离，将StorageError传播给adapter，等待本批处理器完成后再持久化next_batch。所有handler重新绑定捕获的Profile。SDK handle_sync本身不写游标，adapter负责提交；启动同步带持久since，首次同步存储失败使连接中止。此差异来自真实SDK可复现行为（sync-cursor-red），不修改SDK、不禁用handler、不把整个网络事件放入持有PG连接的事务。SDK多步处理的远端事件不因此获得端到端exactly-once承诺；重试/重新请求密钥仍服从原Matrix协议。

## PG新数据集与设备安全

PG不读取旧crypto.db或crypto_store.pickle，不迁移旧pickle key，不调用旧设备自动reset/delete。认证后使用真实homeserver/user/device身份；新PG数据集若没有原设备私钥而服务器已有该设备公钥，明确拒绝并要求管理员配置新的Matrix设备/token。不同本地/服务端密钥也拒绝，不删除远端设备或重置旧密钥。任何PG持久化故障都不能被optional E2EE分支吞掉后声称加密可用。

PG依赖入口只把SDK的asyncpg/aiosqlite作为SQLite路径要求；普通PM matrix安装仍提供完整原生extra。PG加密连接实际检查libolm/SDK及共享Core依赖，缺失时明确失败。依赖安装提示统一使用Hermes PM；明确关闭加密的配置仍可使用普通Matrix客户端。完整系统可用性不由本项协议证据外推。

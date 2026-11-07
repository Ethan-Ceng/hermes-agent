# Hermes 系统统一数据库后端设计

## 状态与目标

- 日期：2026-11-07。
- 状态：IMPLEMENTING；统一配置已进入实施，各领域以执行账本中的独立证据验收。
- 用户已明确：SQLite 可选是 `hermes_db` 的后端选择能力；选择 PostgreSQL 后，系统不能仍依赖其他自有 SQLite 数据库才能工作。
- 承接现有 [会话后端设计](postgresql-session-storage.md)、[代码分层设计](postgresql-storage-code-layout.md) 与 [会话阶段实施记录](../plans/postgresql-session-storage-plan.md)。已有会话后端继续复用，不重做技术选型。
- 执行账本：[统一数据库后端实施计划](../plans/unified-database-backends-plan.md)。

最终目标是一个 Profile 的系统自有数据库数据统一使用选定后端。SQLite 模式仍可独立运行；PostgreSQL 模式可独立运行，常规功能不创建、读取或写入应用自有 SQLite 数据库。保留两种实现不等于运行时必须同时启用两种数据库。

配置、Markdown、工作区、附件二进制、既有 JSON 配置/文件格式继续按原职责保留为文件；本设计不把“数据库后端统一”扩大为所有文件都入库。

## 范围与不变量

1. 延续 `hermes_db`、SQLAlchemy Core、同步 psycopg、Alembic；不引入通用 SQLite SQL 到 PG SQL 的字符串翻译器。
2. PostgreSQL 使用新数据集。不导入旧 SQLite 数据，不双写，不回迁；现有 SQLite 模式的数据与行为保留。
3. 撤销此前把 Cron、Kanban、房间协调、插件独立数据库排除在外的范围边界。所有自有数据库都必须有选定后端的实现。
4. 不新增账号系统、对象存储迁移、Kubernetes 或 active-active 网关。原单 owner、epoch、租约、消息前缀与提示缓存语义保留。
5. PG 实例与扩展由管理员管理；应用只提供配置、显式建表/升级及可读诊断。普通启动不执行 DDL。
6. 所有 PG 查询、唯一键、外键、幂等键、CAS、计数和删除都包含服务端确定的 `store_id`。Board、插件、房间和 Matrix 账号是域内键，不能替代 Profile 隔离。
7. 一个 Profile 只选择一种自有数据库后端；组件不单独覆盖 backend。多 Profile 的作用域仍独立，后台任务/线程显式绑定拥有者。
8. 第三方服务的远端存储由该服务管理。本仓库维护的插件本地数据库需要适配；任意外部插件的私有 SQL 不能凭空获得跨方言兼容性，必须接入统一存储协议并声明支持能力，不能隐式创建 SQLite 绕过选择。

## 已有能力与源码核对

会话阶段基准提交为 `a875342384`。已实现稳定作用域、连接池、未知提交分类、0001–0004 迁移、完整会话/运行/API/投递后端。该阶段完整后端测试 835 passed，含 285 项实库；这些证据只覆盖其原范围，不能用来证明下列独立数据库已支持 PG。

| 数据域 | 主要源码入口 | 现状与本次要求 |
| --- | --- | --- |
| 主会话、消息、提示、用量、运行队列、Worker、API、投递 | `hermes_db/`、`hermes_state*.py`、`gateway/platforms/api_server_*` | PG 已实现；统一全局配置后持续回归，审计遗留旁路 |
| Agent 验证证据 | `agent/verification_evidence.py` | `verification_evidence.db`：事件、变更状态和保留策略需适配 |
| Projects | `hermes_cli/projects_db.py` | `projects.db`：项目、目录、元数据、发现缓存需适配 |
| Cron 执行与事件 | `cron/executions.py`、`cron/incidents.py` | 共用 `cron/executions.db`；保留终态不可变、未知结果和状态通知 |
| Cron 待投递 | `cron/delivery_queue.py` | 独立投递数据库；保留 claim、unknown、终态墓碑及精确请求身份 |
| Cron notepad | `cron/notepad.py` | `cron/notepad.db`；保留每值/每任务字节上限和跨 Profile 隔离 |
| Kanban | `hermes_cli/kanban_db*.py`、`kanban_transfer.py`、`kanban_owner_recovery.py` | Board、任务图、run、订阅、工作区、派发与跨 Board 操作；大量消费者持有原生连接 |
| 房间元数据和事件 | `gateway/hosted_rooms.py`、`hosted_room_replicas.py` | 本地协调数据库；权限代次、顺序事件、复制游标和墓碑需适配 |
| 房间任务与调度 | `gateway/hosted_room_driver.py`、`hosted_room_work_records.py` | 租约、执行代次、停止、接管及终态回执需适配 |
| 房间策略和路由 | `gateway/hosted_room_policy_checkpoint.py`、`tui_gateway/hosted_room_router_call.py` | 事件水位、checkpoint、路由结果 CAS 需适配 |
| 房间附件元数据 | `gateway/hosted_room_attachments.py` | 元数据/配额/幂等进数据库；附件 blob 文件保持原存储方式 |
| 本地指标与发送 outbox | `hermes_cli/observability/shared_metrics*.py` | `metrics.sqlite3`；计数、consent、去重、打包和保留窗口需适配，不能因 opt-out 漏测本地写入 |
| 插件通用存储 | `plugins/plugin_storage.py` | 公开 `plugin_db()` 返回 SQLite Connection；需要可移植协议及明确的旧 API 边界 |
| Discord 恢复账本 | `plugins/platforms/discord/recovery.py` | 消息、扫描及游标需适配，不能把 PG 故障当作空恢复记录 |
| RetainDB 本地队列 | `plugins/memory/retaindb/__init__.py` | `retaindb_queue.db`；本地 pending 队列、线程和关闭行为需适配，远端服务不替换 |
| Matrix 加密存储 | `plugins/platforms/matrix/adapter.py`、`adapter_crypto*.py` | 目前显式传 `sqlite:///crypto.db`；SDK 类名 `PgCryptoStore` 不代表当前使用 PG，需单独协议适配 |
| 旁路和运维 | `agent/kanban_turn_recovery.py`、`gateway/session_kanban.py`、`tools/async_delegation.py`、备份/诊断/安装探测、Desktop updater | 逐项证明已分流或补齐，不能只搜索连接创建点后忽略原生 SQL 消费者 |

`gateway/lifecycle_ledger.py` 的 SQLite 使用主要是旧 `state.db` 的取证/完整性检查，不应误判为另一份业务数据库；PG 路径仍须禁止调用 SQLite 物理检查。`tools/read_extract.py` 读取用户提供的 SQLite 文档、`hermes_cli/browser_connect.py` 处理浏览器自有数据属于外部文件格式能力，不能被改写成应用数据库，也不能给应用自有 SQLite 库提供豁免。

这是一份所有者/消费者清单，不把含有 `sqlite3` 注释、异常类型或测试代码的文件数量当作待迁移数据库数量。实施时遇到清单遗漏必须登记并补任务，不能默认为范围外。

## 方案比较与推荐

| 方案 | 实现和维护成本 | 正确性与测试风险 | 结论 |
| --- | --- | --- | --- |
| 每个组件各加 PG DSN 和独立连接池 | 初期改动局部，后续配置/连接预算/迁移重复 | 容易出现一部分 PG、一部分 SQLite，无法兑现统一选择 | 不采用 |
| `hermes_db` 统一选择、资源与迁移，各领域提供业务存储接口 | 复用已有连接/作用域设施，逐域改造 | 能用同一行为契约和禁 SQLite 的真实 PG 流程验证 | 推荐 |
| 用 SQLite Connection 兼容包装层转换所有 SQL | 表面上改动少，实际需要复制两种方言和连接语义 | `PRAGMA`、FTS、行锁、时间函数、SDK SQL、rowcount 和事务边界不可透明等价 | 不采用 |

采用第二种方案。SQLite 的现有实现可继续存在于明确的 SQLite 后端；PG 的 SQL、表和事务只放入 `hermes_db`。业务层处理普通记录、领域错误和完整操作，不能要求调用者识别 SQLAlchemy/psycopg 异常。

## 配置与选择

统一配置如下；Task 1 接通配置选择，各领域 PG 能力按计划逐项实现：

```yaml
storage:
  backend: postgresql
  postgresql:
    dsn_env: HERMES_POSTGRES_DSN
    schema: hermes
    store_id: personal-main
    pool_size: 5
    max_overflow: 5
    connection_budget: 10
```

后端选择提升为 `storage.backend`，覆盖同一 Profile 全部自有数据库。`storage.postgresql` 统一提供连接、Schema、稳定身份与连接预算；DSN 仍只在已有 Profile secret scope 中读取。未配置时为 SQLite，不增加每组件 backend 配置。

会话阶段的 `storage.session.*` 属于旧开发分支配置。解析器、默认值、示例、测试和调用者统一采用新键；旧嵌套配置明确报配置错误并给出修改位置，不能被忽略后静默回落 SQLite，也不新增永久双配置模式。

切换后端选择的是独立数据集，不读取旧 SQLite 作为 PG 的备用数据源。PG 缺配置、驱动、权限、扩展、版本或模块表时明确失败；不以自动创建本地库、禁用功能或只存在内存中的队列来继续报告成功。

## 代码布局与调用边界

```text
hermes_db/
  settings.py / scope.py / engine.py / factory.py
  domains/                 # 按实际消费者定义的资源入口与协议
  tables/                  # projects、cron、kanban、rooms、metrics、plugins 等 Core 表
  repositories/            # 接收 Connection + scope，无隐式 commit
  operations/              # 完整短事务、锁、CAS、幂等和终态
  migrations/versions/     # 新增域的显式 PG Schema 演进
  sqlite/                  # 新整理的 SQLite 域实现；原稳定实现可先保留原模块
```

1. 复用 `resolve_db_configuration` 的 Profile 绑定、`DatabaseSettings`、`DatabaseScope` 和 `get_engine`。会话 `DatabaseHandle` 不是通用 SQL 连接；新领域通过按需获取、调用者持有并释放的领域资源接入，不强行给它堆积全部服务对象。
   领域协议及SQLite入口保持无PG驱动依赖；仅在选定PG后延迟导入SQLAlchemy/psycopg实现，避免可选依赖变成SQLite模式的启动前提。
2. 组件获取领域存储时完成一次配置/作用域解析；每个完整操作借用短连接。模型、工具、网络和投递等待不占用连接或事务。
3. 复用按 PID/连接目标/池配置划分的现有 PG 池，不按 Board、插件或每次调用新增 Engine。进程关闭/回收行为统一。
4. 现有返回原生 SQLite Connection 的公开内部入口必须逐步替换其生产消费者。PG 入口提供具名领域操作或 Unit of Work，不提供伪 SQLite `.execute(sql, params)` 对象。
5. 现有 SQLite 专用维护能力保留在 SQLite 路径；PG 调用返回明确的能力不适用结果或执行对应 PG 管理能力。
6. Worker 继续使用 owner RPC。领域适配不能成为 Worker 直接打开 owner 会话/业务数据库的后门。

领域资源显式接收拥有者Profile/scope；原`db_path`、`EXECUTIONS_FILE`等只属于SQLite分支，不能把`cron/`、Board目录或附件目录的父路径当成Profile重新解析配置。这类路径推断会把已选PG静默变成另一个目录的默认SQLite。跨线程持有的是不可变scope，不能依赖调用时的进程全局环境。

复用会话阶段已经验证的无损值编码策略。用户文本、JSON、Unicode/NUL、布尔/数字/字符串、空值和时区语义必须逐域保真；需要服务器查询的内容建立明确派生投影，不直接把所有任意文本改成PG Text/JSONB后丢失合法值。派生列不进入业务身份、导出摘要或幂等指纹，索引和排序使用与原合同一致的规范值。

## Schema、隔离与迁移

- 保持共享 Schema，新增域使用稳定表名前缀，如 `cron_*`、`kanban_*`、`room_*`、`project_*`、`metric_*`。全部包含 `store_id`。
- Kanban 的 `board_id`、插件的 `plugin_id/namespace`、房间 `room_id`、Matrix `account_id/device_id` 作为域内作用域进入复合键及查询；不能用本机绝对文件路径生成跨节点身份。
- 现有 Board/Profile 的逻辑身份已有稳定 ID 时复用；确需新增 ID 时经拥有者配置/元数据写入接口分配，不在每次启动重新随机生成。
- 保留原 PG revision 0001–0004，不修改已执行的 revision。各域增加新 revision、索引、唯一约束和必要的范围锁；不将所有未知业务塞进一个 JSON 文档表。
- 显式 `hermes db upgrade` 初始化完整模块集合，重复安全；status/readiness 报告整个所选后端及缺失模块。插件启用时不能自行执行 PG DDL。
- SQLite 的现有版本演进不被本轮重写；所有后端的配置选择与数据集相互独立。

## 各领域的关键合同

### Cron 与 Kanban

Cron 保留 owner 指纹、claimed/running/terminal、unknown、错过发生时刻、终态不可变及恢复判据。执行与 incident 仍可在同一业务事务下观察一致状态。Notepad 用 UTF-8 字节限制，行锁保护并发写入的总配额。

Kanban 保留任务图、可派发条件、精确 run identity、租约、认领与回执、订阅和工作区引用。跨 Board 转移在同一 PG 事务中完成，排序获取多个 Board/任务锁；本地文件/工作树清理在提交后的受控阶段执行。不能用进程内锁替代跨进程 claim，也不能把旧 SQLite 的全库写锁当作 PG 已提供的保证。

Task 8 代码核对补充：SQLite Board 的 slug 是目录身份，归档后重建同 slug 会产生新数据库；PG 不能把 slug 永久直接用作数据代次。复用 slug 作为稳定查找键，由拥有者的显式 Board 初始化/元数据操作在 PG 注册表中分配稳定 `board_id`；归档保留旧代次，同名重建分配新代次，不从绝对路径生成身份。默认 Board 不可删除，可使用固定默认身份。Task 8–10 分别报告 `kanban_tasks`、`kanban_runs`、`kanban_workspace` 能力，未完成部分仍明确未就绪，不能把基础任务可读写标成完整 Kanban 已支持。原跨 Profile 共享目录的 Worker 路径不能直接转换为执行 Profile 的 store_id；Task 9 必须从可信 owner/派发上下文解析 Board 作用域，继续遵守 owner RPC 边界。

`board.json` 继续是文件配置，保存显示信息、默认工作目录和项目配置；PG 注册表只保存 Board 身份、slug 查找与生命周期，不复制该 JSON 配置进数据库。PG 文件根绑定拥有者 Profile，SQLite 继续保留原共享目录规则。身份事务先提交，文件配置随后写入；文件失败显式上报，重试创建复用已提交的活动代次。工作区/附件目录的归档、清理与跨 Board 转移在 Task 10 闭合，不把 DB 提交假称为文件操作已经成功。

Task 9 依赖细化：现有 `complete_task` / `request_review` 在终态事务中登记保存的附件行，`_spawn_candidate` 同步写入解析后的 workspace/branch，完成后查询父子与跨 Board 的共享工作区引用再清理。因此 Task 9 的真实终态/派发闭合依赖原排在 Task 10 的底层附件元数据、workspace 字段/引用读取和清理接口。将这些必要底层适配提前随 Task 9 实施，Task 10 保留订阅、跨 Board 原子转移、Board 目录生命周期以及剩余工具/dashboard/watchers消费者；任务总数、后端选型和验收范围不变。不得用省略附件保存或跳过清理/共享引用判据使 Task 9 通过；文件准备/回滚与提交确认丢失仍须分别处理。

Task 9 调度协调细化：SQLite 原文件锁覆盖整个 tick（包括工作区/进程等待），PG 不用持有连接的 advisory lock 替代。PG 使用 store 内持久调度租约、随机 owner token 和短事务续租；同 store 的 Board tick 串行，以原子认领及所有 Board 的 running 计数共同保护预算。等待期间连接归还池；租约失效后不再开始新 spawn，已认领任务仍由精确 run/claim 和 owner 回执保护。租约 TTL/续租属于内部实现常量，不增加用户配置或环境变量；进程消失后可按数据库时钟接管。跨 store 的计数不越过 Profile 隔离，机器资源压力仍由已有主机探测约束。

工作区清理并发细化：仅查询现有共享引用后删除文件存在跨Board新增引用的窗口。PG增加store内规范路径注册表与任务引用，路径在连接外解析，业务事务通过同一路径行锁登记引用；恢复非终态、分解继承和新增依赖也核对仍需使用的父工作区。清理事务核对终态、活动子任务与所有Board引用后先提交随机cleanup token，再在连接外清理目录/工作树，最后以token CAS释放。pending token拒绝新引用，不依赖进程内锁或长数据库事务；进程中断后由Task 20维护对账，不能自动过期并冒险删除新引用。路径是本机文件资源定位，业务Board身份仍使用稳定board_id。

Task 10文件布局细化：PG数据库已用board_id区分同slug重建代次，若本地附件/工作区/日志仍只按slug定位，新Board会继续接管旧文件树。因此PG内容根使用拥有者Profile下 `kanban/data/<board_id>/`，文件根覆盖也按board_id分代；资源/RPC捕获的Board引用绑定该代次，目录路径不成为业务身份。`boards/<slug>/board.json`继续是当前显示配置，归档只移动配置并保留可定位旧代次内容的文件指针，复用slug不会搬动或重用旧内容根。SQLite文件布局保持现状。硬删除的文件回收必须使用持久目录栅栏，保护其他Board仍引用的附件/工作区，不能直接rmtree一个可能共享的代次树；中断后的待清理状态由Task 20对账。该PG布局在最终启用新数据集前确定，不迁移旧SQLite文件。

实际 `kanban_transfer.py` 是整Board归档export/import，现有系统没有单任务move_board命令。Task 10保留该CLI/API语义，以一致快照导出、原子创建目标Board和域内ID映射实现PG转移；不新增无消费者的任务移动工具。PG归档使用明确的无SQLite载荷版本，支持其完整导入导出并保留文件，旧SQLite数据库归档继续只走SQLite分支；PG不打开旧SQLite档案来实施被排除的数据迁移。

Board文件退休的锁顺序为短事务内store文件栅栏→注册表/Board→路径锁，引用登记与目录删除意图共用该栅栏；目录删除在事务外，持久退休根拒绝新引用。配置目录的rename/delete/create另用已有PM跨进程文件锁协调同一台机器的实际文件，等待文件锁时不占数据库连接；这不承载数据库状态或代替PG业务锁。硬删除先持久确认配置目录已清理，再允许复用slug；旧内容仍被其他Board引用时明确保留待清理状态，重建使用新board_id内容根，不影响旧引用。所有源/目标路径在本机操作前核对归属与解析后的边界。

PG导入先在私有文件stage校验归档与附件SHA-256，单个短事务创建目标Board、全部任务/图/history和持久import文件job，按新目标域映射run/event等本地行ID。Board在文件发布前保持不可打开的pending状态；发布文件/配置均在连接外，最后以同一短事务激活Board并结算job。提交结果不明保留原stage/job供恢复，不自动重做为另一个Board；已知业务事务回滚只补偿本次独占stage。用户未请求双写/数据回迁，PG只导入PG v2逻辑归档。导出为一致读快照，复制快照登记的附件并记录内容校验；并发删除导致文件不可读时明确失败，不能悄悄省略附件后声称完整导出。

回收先在一致读快照中捕获 task、当前 run、owner/worker 事件及水位；事务外执行进程、文件和 admission 探测，短写事务在 Board 锁内重新核对整个快照与事件水位后才结束 run、释放 claim、记事件和失败预算。这些写入一次提交，避免 run 已释放但预算未登记时另一个 dispatcher 重派发。等待期间新绑定的 interpreter、心跳或回执都会使旧快照失效；未知提交保持错误，不自动重试。

Worker 命令协议细化：实际 `worker.persist` 的连续序号与回执属于执行会话owner，Board却可能属于另一个Profile甚至另一个连接目标，不能把Board写入混进该会话事务或假称二者原子。复用Worker已有受保护JSON outbox，增加一个互斥的待确认Kanban命令槽，使用独立随机command_id，不消耗会话persist序号。命令经已采用worker的同一认证RPC连接交给会话owner；owner只从其持久化、冻结的kanban policy解析Board owner ref，不接收Worker自选DSN/Schema/Profile路径。关闭的具名读操作不写入；mutation在Board主业务事务内登记scoped command回执，提交确认丢失后只以同ID/同payload恢复原回执。文件/PR准备和提交后清理仍在事务外，不能为了通用回执包住整段编排而持有连接。明确业务拒绝可登记无副作用回执；存储故障/未知提交保留pending，禁止静默重发为新命令或让后续写入越过它。Worker工厂owner-only护栏保持原样。

Task 9 实库探针已发现真实整机依赖：普通 `gateway.run` 启动会经 `recover_gateway_native_sessions → ensure_hosted_service → RoomCoordination._prepare → hosted_rooms._connect` 无条件打开尚属Task 11–12的房间SQLite。这不是Kanban功能通过，也不是环境缺SDK。保留普通daemon探针作为Task 22必须转绿的全系统场景；在房间实现前，Task 9另用生产SessionAuthority/runtime API/control listener的嵌入式拥有者合同验证真实dispatcher、采用Worker、具名RPC与业务持久化，不改生产启动逻辑、不加“关闭房间以运行PG”的开关。该合同只能证明Kanban/session协议；全系统PG可启动、真实普通daemon及重启仍须Task 22完成，不能用范围较窄的证据替代。

### 房间与附件

房间事件序号、权限 epoch、幂等身份和退役墓碑用范围约束及行锁保护。Driver、work records、policy checkpoint 和 router claim 对应同一房间事件谱系；提交时重新核对代次与水位。

Task11接口核对：现有房间函数的db_path是SQLite位置参数，不能从shared-state.db或会话state.db的目录推断PG拥有者。PG延迟调用者捕获明确的Profile/store_id房间引用；旧位置参数在已绑定Profile的PG入口只选当前Profile，不能指定另一个store。所有原生SQLite私有连接在PG下拒绝。原会话阶段`hosted-pg-<digest>.db`独立协调壳须移除；其admission/driver原生SQL消费者在Task12–13逐项端口化，不能用PG连接模拟SQLite执行器。可信事务回调复用已有CoreEffect，权限写入与房间写入使用同一短事务；普通SQLite回调不能被直接拿到PG执行。房间内容配额使用store级短锁和现有统计，控制事件保留原有紧急余量；房间/副本序号使用明确行锁，不把Python锁当多进程租约。

Task12依赖细化：driver终态清理与被动work-record快照需要policy_publications作为已出版判据，其scoped底层表提前进入0020；策略checkpoint和实际出版事务仍由Task13完成。Canonical owner创建及FIFO准入使用同一连接上的具名CoreEffect，锁序为runtime epoch、room store、room/lease/task，文件/配置/peer/模型等待均在借用连接前结束。被动证据与事实在同事务保存，但损坏证据保留原字节并分类invalid，容量失败只回滚证据savepoint，不能阻止Stop；权威切换以scoped数据库触发器冻结旧producer/epoch证据。Task12的transport-free driver调度与准入合同不等于整服务可用：Canonical服务构造仍依赖Task13策略/路由及Task14附件，完整daemon在Task22强验收，不能禁用这些功能绕过依赖。

附件只统一元数据、配额、引用和删除状态。文件写入与 DB 不是同一事务，保留准备/提交/清理协议及重启对账；不因换后端移动附件内容或声称多节点共享文件完成。

### 指标与插件

指标保留当前安装/拥有者语义与 consent 状态，不能以换库扩大遥测发送范围。聚合、打包水位与 outbox 去重在一个短事务完成，导出文件及网络发送仍在事务外。

插件增加有真实消费者的可移植持久化协议；通用键值/CAS 与领域队列分别按其需求定义。原 `plugin_db()` 任意 SQLite SQL 接口在 SQLite 模式保留，PG 模式不得打开 SQLite；本仓库插件必须完成协议迁移，不能通过禁用插件功能算通过。外部插件须显式采用协议，遇到不兼容使用给出插件名和具体能力原因，不能吞错后伪装已持久化。

### Matrix SDK

Matrix 单独实现 SDK CryptoStore 协议适配，PG SQL/表/事务由 `hermes_db` 管理，异步 SDK 接口在明确边界调用同步存储并保留 Profile scope。不得只把 SDK URL 从 sqlite 改成 PG 后另起不受管的异步池或失去 `store_id` 隔离。

需覆盖账号/设备、identity/Olm 会话、群组会话、设备列表、密钥请求和 SDK 版本要求的完整协议；必须核对实际安装版本的协议并运行真实密钥 round-trip。PG 模式不读取/删除旧 SQLite 或 pickle 来补数据，不自动删除远端设备或重置密钥。旧设备在新库中缺少原密钥时明确提示管理员使用新设备身份，不能承诺解密未迁移的旧历史。

## 初始化、切换与运维

新增各领域全部接通、实库验收后才切正式 Profile。执行顺序：PM 准备依赖 → 校验秘密与统一配置 → 显式升级新 Schema → 全模块状态检查 → 排空并重启网关 → 核对运行中的 backend、revision、代码版本与域健康 → 受控读写及再次重启恢复。

此前正式实例仍为 SQLite、最近一次重启已加载 `a875342384`。本轮规划不改运行配置、不操作网关、不安装或管理 PG 服务，也不把历史会话阶段测试结果外推到全系统。

备份/恢复、健康、诊断、安装使用状态探测、Desktop updater 和数据库路径存在性判断都必须使用选定后端的能力；PG 的本地文件备份不能假装包含数据库数据。

## 验收与证据

1. 两种模式各自通过同一业务合同；无 PG extra 的 SQLite 安装仍可启动并执行既有功能。
2. PG 模式在新数据库和空 Profile 文件树中完整启动，全部域实际读写、关闭、进程重启及恢复通过。
3. 在PG完整业务测试子进程拒绝所有SQLite连接尝试，包括内存库和URI；覆盖启动、消息/工具、项目、Cron、Kanban、房间、指标、已维护插件和所有入口。用户SQLite文档/浏览器文件格式读取在另一个明确的文件输入测试进程验证，不给业务运行进程开豁免。不能仅凭“没有生成 .db 文件”或静态搜索判定无混用。
4. 跨 store、Board、插件及同业务 ID 测试不串数据；并发 claim、事件序号、总配额、CAS 和终态用真实 PG 验证。
5. 断连、池超时、SQL 错误和提交确认丢失保持原错误/unknown 语义；没有 SQLite/内存回落。
6. 全新 Schema/重复升级/现有 PG 版本前向升级与独立发行环境均通过；管理员准备扩展，应用不自动安装服务/扩展。
7. Matrix 使用实际支持版本 SDK 的加密对象读写/重开验证；需要的系统依赖或实库条件缺失时明确保留未验收任务。
8. 全部测试经 `scripts/run_tests.sh`，依赖经 PM；最终执行 verification-before-completion 和独立 code-review，整改后复验。
9. 原会话阶段的非 WSL 私有启动页验证缺口及波动历史继续单列；不伪装 OS，不以不相关基线覆盖当前功能缺陷。

Task 10普通Worker细化：交互会话通过同一采用连接的具名`board.resolve`只读请求，由owner在自身Profile解析slug和board_id；后续请求仅携带该slug/代次选择器，不能携带Profile路径/DSN/Schema。派发Worker仍只能使用冻结kanban policy指向的Board；delegated child继承根policy的可读Board、owner拒绝其全部mutation。新数据集默认Board使用固定`default`代次，可在真实PG表上零行读取；第一次写入将默认Board登记与业务写入置于同一事务，保证只读RPC不会隐式创建Board。已存在默认Board保持原board_id。

Worker附件沿用25MiB上限，不能塞入4MiB JSON outbox或8MiB RPC。采用私有分块文件handoff：小块认证RPC、owner检查执行claim、总量/摘要/块顺序，文件准备在事务外，终态附件登记和command回执仍共用Board事务；未知提交保留同一command/stage恢复。handoff位置由owner决定，Worker不得传任意读取路径；child只读且不能上传。实际实现和恢复合同在Task10记录，自动回收对账归Task20。

## 风险与处置

| 风险 | 处置 |
| --- | --- |
| 原生连接在消费者之间穿透 | 每域先固定业务接口与调用清单，连生产消费者一并适配，不做 SQL 兼容壳 |
| 从全库锁换为行锁后出现竞态 | 固定锁顺序、范围唯一约束和原子状态转换；真实多连接并发合同 |
| 模块遗漏仍偷偷打开 SQLite | 所有者矩阵、调用者核对、真实流程 SQLite 连接审计三者共同验收 |
| SDK/第三方插件自带 SQLite | 协议适配和实际版本验证；明确发现不支持，不能跳过该域后宣称全部完成 |
| 文件与 DB 的跨资源一致性 | 保留附件/工作树现有准备、回执、对账与清理顺序；不假称数据库事务覆盖文件 |
| 全局配置误读旧嵌套配置 | 旧配置显式报错、统一更新示例/默认值/测试，不静默选择 SQLite |
| 连接预算与线程/进程资源泄漏 | 复用已有池，显式 scope 与释放，领域等待不持有事务，独立进程验证 |

目前没有需要重新选择数据库技术的未决事项。Matrix SDK 的完整协议和外部插件能力是指定任务内必须核实的实现输入；未验证前不能把该任务或整个统一后端标为完成。

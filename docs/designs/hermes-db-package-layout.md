# hermes_db 按业务域分包与模块收敛设计

## 文档状态

- 状态：`READY_TO_MERGE`（仅本次分包重构）；2026-11-10在独立检出完成18/18任务，完整验证与独立APPROVED见实施计划及审查报告。
- 日期：2026-11-09；负责人：Codex / 项目维护者。
- 源码基准：`cbfc773dd7`；运行实现基准为`0d69702244`，两者仅文档不同。
- 文档分支：`docs/hermes-db-package-layout`；实施分支：`refactor/hermes-db-packages`，隔离检出`D:/AI/hermes-db-packages`。
- 关联：[统一后端设计](unified-database-backends.md)、[独立实施计划](../plans/hermes-db-package-layout-plan.md)、[全量模块归属清单](hermes-db-package-map.json)。原统一后端24项账本保持独立，不重写其历史或解除Task24门禁。

## 背景与现有实现分析

当前`hermes_db`有398个Python文件、约28,484行：根目录113个，operations144个，repositories51个，domains20个，tables29个，migrations35个，postgresql4个，sqlite2个。
剔除迁移包和`__init__`后，356个模块中268个不足100行。文件短并不直接构成问题；这里还同时存在以下维护成本：

1. 同一功能分散在根门面、domains桥接、operations及repositories四处；operations中有48个`kanban_`和26个`room_`前缀文件，根目录有40个`session_`文件。
2. `PostgresSessionStore`组合36个Mixin，`PostgresRuntimeStore`组合10个Mixin，方法间通过`self`隐含共享事务、Profile和其他能力。
3. PG操作借用CLI门面的私有规范化、DTO和异常，例如`operations/projects.py`引用`hermes_cli.projects_db`。纯规则复用、接口转换和SQL操作尚未形成明确边界。
4. SQLite继续复用既有Native实现，PG另有Core持久化实现；当前并非两套完全共用SQL的薄ORM包装。存储还承担锁、CAS、回执、重放、SDK加密状态和文件引用事务，不能用通用CRUD取代。
5. `domains`当前主要放后端分流桥接，名称与“业务域内聚包”的预期不一致；`native_registry`实际组合具体Store，不能因为文件名像基础设施就下沉到不应依赖领域的core。

本次复用现有工厂、资源生命周期、短事务、稳定作用域、表定义、SDK实现和业务合同；不重新调研数据库技术栈。

## 目标与范围

- 业务域成为主要导航边界；同一域的协议、后端实现和事务查询就近组织。
- 根目录从113个文件收敛到明确列出的11个入口/公共定义，领域实现前缀转为包命名空间。
- 完成两阶段后，Python文件总数须净减少，另报告排除迁移、表和包初始化后的业务模块变化；不通过堆入巨型文件达成数字。预计主要收益来自48个Kanban、26个Room操作和36/10个Mixin的工作流归组，具体数量以验证后的清单为准。
- 保持消费者实际使用的存储方法、参数、返回、错误身份、事务、回执及作用域语义；让SQLite模式继续不需要PG依赖。
- 每项修改有原生/PG消费者验证，可独立提交和恢复。

本次不更换SQLAlchemy Core、psycopg或Alembic，不改数据库结构/配置键，不迁移数据，不重写Native SQLite SQL，不增加通用DAO/Service框架或每表一套接口。模型提示、工作区和附件内容的既有文件职责保持不变。

## 可选方案与比较

| 方案 | 方式 | 复杂度/维护 | 兼容性与测试成本 | 结论 |
| --- | --- | --- | --- | --- |
| A：现有技术层内分子包 | operations/kanban、repositories/kanban、stores/sessions分别归组 | 改动较小；一次业务修改仍穿过多棵目录树，Mixin和反向依赖保留 | 主要是导入/patch点回归，风险较低 | 可作机械中间步骤，不作最终结构 |
| B：业务域内聚，域内按需拆分 | domains/kanban等统一归属，基础设施/组合/迁移单独组织 | 中等；能同时减少导航跳转和碎片，允许简单域少文件 | 分开机械移动与结构调整，逐域使用现有合同，迁移/发行单独验证 | 推荐 |
| C：同时重写双后端共享ORM | 将Native SQLite和PG业务都改为新模型、通用Repository和Service | 高；组织变化叠加SQL、事务、FTS和SDK重写 | 回归面和数据兼容风险最高，交付成本显著增加 | 不纳入本次 |

选择B。先取得可运行的一对一分包检查点，再收敛组件与工作流。阶段一临时保留域内operations/queries/capabilities目录，以便审查“只移动与改import”；它们不构成必须永久存在的三层模板。

## 目标目录与职责

```text
hermes_db/
  __init__.py              # 保持轻量；不批量导出具体实现
  access.py                # 现有Profile获取/释放入口
  factory.py               # 后端与具体实现的组合入口
  handle.py                # 实际DatabaseHandle定义
  contracts.py             # 现有跨后端能力契约
  errors.py                # 实际公共错误定义，迁移锚点
  settings.py / scope.py   # 配置值/稳定作用域定义
  health.py / maintenance.py
  schema.py                # 现有显式升级/版本入口
  core/                    # 资源、纯值编码、目录能力描述等低层能力
  backends/
    sqlite/                # Native获取/注册桥接
    postgresql/            # Engine/池、事务、方言表达式与通知
  integration/             # Profile绑定、组合注册、跨域维护及DTO/RPC适配
  domains/
    sessions/              # 会话、消息、转录、压缩、检索、保留
    runtime/               # 准入、投递、Worker、终态、运行恢复
    projects/
    verification/
    cron/
    kanban/
    rooms/attachments/
    metrics/
    plugin_storage/
      records/             # 通用插件KV协议的持久化实现
      discord/
      retain/
      matrix/
  tables/                  # 保持现有29个模块路径和表/metadata身份
  migrations/              # 保持Alembic资源位置
    versions/              # 0001–0031原内容及revision图保持不变
```

11个根文件是实际定义/组合入口，不是为旧内部路径保留的re-export壳。`integration`只承载已经存在的上层接线与跨域工作；不得成为无归属的utils堆。新增文件须能说明其具体拥有者、调用者和事务/生命周期边界。

### 域内形态

简单域例如Projects：`api.py`放既有分流入口，`rules.py`放确实由两后端复用的纯规则，`postgres.py`可同时包含紧密关联的SQL与短事务。没有独立职责时，不单独建立Repository文件。

复杂域例如Kanban：以catalog、claims、completion、dispatch、files、workspace、notify、transfer、owners、maintenance、effects等工作流组织PG实现。确有复杂查询时在同一工作流旁拆查询模块。`postgres/`明确其后端属性，公共api/rules模块不提前加载驱动。

已有SQLite入口继续调用Native实现；桥接归入`backends/sqlite`，但不在本次搬迁整个`hermes_state`/CLI业务树。共用纯规则由两者反向调用共享模块，不让PG操作回头依赖CLI私有实现。

## 模块迁移清单

[JSON清单](hermes-db-package-map.json)覆盖基准全部398个Python文件，每项记录源路径、第一阶段目标、归属任务、行数和基准Git blob的SHA256；使用Git规范内容核对，避免Windows/Linux检出的换行差异被误判为代码变化：

- 320个移动，76个保持，2个空的旧技术层`__init__`在最后消费者迁移后删除。
- 目标路径无冲突；root keep精确为11项。
- 表和迁移包64项保留现有位置；其余保持项为根入口与domains命名空间。
- source清单按基准冻结；实施前发现新增/改动模块必须先更新归属及计划，不按通配符漏掉或移入杂项包。
- 新父包只补必要的空`__init__`；它们不导入全部领域、SDK或Engine。
- Task10实施修正：`kanban_import.py`目标使用`postgres/operations/imports.py`，避免Python关键字`import`；其源hash与业务归属保持，全部move目标已补验合法模块标识符。
- stage1_target是机械落位，不能把临时capabilities目录当作阶段二最终组件设计；阶段二以下表收敛，并在任务完成时更新最终落位记录。

## 分层与依赖规则

1. 根factory/access和integration组合具体实现；core不导入domain Store/业务操作。`native_registry`因构造Session/Runtime实现归入integration。
2. backend提供连接、事务、方言及Native桥接，不读取运行时默认Profile、不知道Kanban/Rooms状态机。Native SQLite桥接对原SQLite门面的导入单列允许。
3. PG域操作只使用捕获的scope、同一次Connection及明确能力；不自行重新解析Profile，不把网络/文件等待放入数据库事务。
4. 查询辅助接收Connection和scope，不commit或创建Engine。简单查询可以直接调用本域辅助，不额外穿过空操作层。
5. 运行时PG域实现不依赖CLI/Gateway/插件门面的私有helper、完整Service或Native存储Mixin。已有独立、无I/O的共享纯模块可以复用，须在Task1按模块+符号登记；不因目录纯洁性把Agent业务搬进数据库层。
6. CLI DTO/异常身份、owner RPC和适配器结果转换放在明确的integration边界。可通过实际需要的构造器/转换函数注入，保留现有公共错误类型；不复制一套同名异常，不靠扩大plugin_api.json掩盖依赖。
7. 跨域查询只能走登记的窄查询能力，且复用调用者Connection/scope；跨域Profile迁移/引用维护由integration协调。低层域不导入上层工厂/服务，所需能力由组合入口注入。
8. 活跃文档、skills、AGENTS和生产消费者的导入/动态路径在同一任务更新；不留旧内部模块re-export shim。历史执行命令和冻结证据标明原基准，不伪改成当时并未执行的新路径。

## 两阶段实施与组件收敛

### 第一阶段：机械落位

Task1冻结接口、动态引用与活动回归基线；Task2处理基础设施；Task3–10逐域按清单移动。一次移动任务仅修改模块落位、导入、patch点、必要资源路径与对应文档，不捆绑SQL或状态规则调整。原Mixin可作为短期可运行检查点。

动态入口必须专项处理：Kanban现有`import_module(f"hermes_db.operations.kanban_{topic}")`、room_operation分发、方法名getattr、Worker handler登记、plugin boundary baseline、SDK延迟导入、测试patch字符串及发行资源。物理模块位置不能继续由旧全局前缀字符串拼接；使用明确模块表或已归属的域内路由，同时保持逻辑命令/回执名称不变。

### 第二阶段：按职责合并与显式组合

以下是初始合并单元；每组要在既有事务与消费者合同下完成，不能把文件简单拼接后保留新的巨大隐式Mixin集合。

| 范围 | 收敛单元 | 约束 |
| --- | --- | --- |
| Sessions catalog | metadata、titles、topics、queries及picker能力 | 明确目录读写职责，必要时拆reader/writer；保留先筛选再limit和canonical归档语义 |
| Sessions messages | messages、reads、lookup、edits、reactions、results | 按实际读写/结果职责组合；同Connection回执、metadata merge-patch、BYTEA/NUL及显示身份保持 |
| Sessions history | transcript pages、read snapshot、lineage、handoff、compression/rewrites | 快照与编辑revision规则保持；snapshot pin是整个Store上下文共享，不按组件实例分裂 |
| Sessions usage/lifecycle | analytics、bookkeeping、usage/usage_writer；leases、retirement/housekeeping | 队列关闭、线程Profile捕获、root锁和归档条件保持；独立生命周期可以保留独立模块 |
| Profile portability | portability、profile moves/repair、file grants与home引用 | integration协调，由Store委托已注入能力；目标摘要和旧home授权身份不随包名变化 |
| Runtime policy/local | policy/bot/viewer；local/history/terminal/recovery | 明确组件输入；保留owner权限、epoch、receipt序号、未知终态和重启恢复 |
| Runtime workers | reservation、lifecycle、compression、metrics/retain、children/delegations | 按Worker生命周期归组；compute进程仍经owner RPC，不获得数据库直连能力 |
| Kanban | catalog；claims；review；completion；dispatch；runs；files/workspaces；notify；transfer；owners；maintenance；effects/swarm | 把48个前缀操作按工作流归组。若单组逼近2000行，按真实生命周期/锁边界继续拆分，不混合文件IO与持锁SQL |
| Rooms | lifecycle/reads；ownership/leases；grants/links/debts；tasks；work；policy；replication；attachments | 保留exact-grant、CAS、generation、held债务、purge后存活和后台付债，不跨组开启独立事务 |
| 小型域 | Projects/verification、Cron、metrics、records/Discord/Retain | 合并同域薄操作/查询；共享纯规则先以Projects试点。Matrix codec/cache/failure通道可因独立SDK职责保持分离 |

Task11实际收敛：Projects与verification各为单一`postgres.py`；Cron execution/incident/query合并，delivery与notepad按独立持久化生命周期保留；metrics counter/query合并为records、consent/package/claim合并为outbox；插件records的协议实现与具体CAS/配额SQL同置。纯Projects规则由两个后端共用。移除11个临时空namespace，462→444个Python文件；后续大域继续净收敛。最终落位与源模块沿革记录在映射的`final_target`、`consolidations`及`new_files.final_status`。

Task12实际归属：Session的catalog/messages/history/lifecycle/usage五个域内组件与一个integration/transfer组件共享SessionContext；仅注入真实跨组件回调，构造器由integration/session_composition组合。Worker复用显式Connection/scope查询，不借用组件方法。消息codec、覆盖及校验纯规则为Native/PG共享。当前444→419文件；本Task的Native560、PG160、288方法签名及15静态核验通过；最终跨域/发行/SDK验收仍待后续，证据见Task12账本。

Task13实际归属：Runtime的admissions/local/policy/workers/media五组件由integration/runtime_composition组合，RuntimeContext借用已有SessionContext；委托账本同用该Context并保持其额外fence。读沿用Session pin，写保留Profile激活顺序，不另设close状态或池；当前419→415文件；Native504、PG43及15静态通过，最终全域验证仍待Task17，详见Task13账本。

Task14实际归属：52个Kanban操作/查询收敛到17个工作流/共享能力，完整表见Task14账本与映射consolidations。基础repository与依赖run的evidence分开；父/后代撤回与Catalog/DAG同置，消除聚合引入的eager环。无lazy循环或旧路径shim；当前415→378，根11；Native536、Linux core24、PG104及15静态通过，最终跨域/发行验证待Task17。

Task15实际归属：Room的23操作/4查询与附件5metadata模块归为九组，内容I/O保持独立。两个内部读取helper按真实局部遮蔽证据具名调整，184函数/类与常量等价、17-topic/67入口已核对。当前378→351，根11；Native529、Linux附件24、PG109及15静态通过，最终全域/发行验收仍待Task17，详见Task15。

Task16局部实施完成记录（最终验收待Task17）：根保持11个入口/公共定义；398项原始源均有最终归属或删除理由，当前365个Python模块，较原始净减33；非namespace模块389→315；再排除tables/与migrations/后，业务模块328→254。两个旧全局技术namespace已删除。跨域时钟、DTO、所有权、事件/媒体、Worker自动化/指标及Cron运行能力由integration注入；真实纯规则由两个后端共用。Retain HTTP/线程协调与PG队列SQL各归实际职责。现有插件边界仅精确迁移一条Retain类路径，公共API不扩张。依赖检查登记到consumer+symbol，并纳入scripts/check；最终发行、Schema恢复、实SDK和全域验证仍由Task17完成，当前数量不等于验收结果。

Task17–18最终验收完成：完整PG720、Linux Native584、Windows Native579/5平台skip及两端CLI/TUI各49通过；静态16项、契约、独立载荷/SDK/迁移恢复通过，独立审查APPROVED。统计口径minor已修正，代码未因审查改变；原统一后端Task24及七项非WSL缺证仍独立保留。前述各Task“待Task17”为历史实施检查点，最终状态以本段和计划末节为准。

Session/Runtime最终使用少量明确组件和显式门面方法委托，去除36/10基类组合。组件共享一个带scope、事务、snapshot pin及关闭状态的上下文；不各自创建连接池，不互相保存整个Facade作为万能self，也不使用万能`__getattr__`/运行时反射自动导出全部方法。
上下文的缓存/pin身份沿用原Store实例及完整资源身份，不能只按store_id合并不同目标。共享上下文不意味着所有read自动切换活动Profile；原活动绑定的生命周期点须逐项保持。导入/组件初始化不新增配置、秘密、模型或数据库I/O，既有按需行为仍在原操作位置执行。
公共存储方法保留既有签名/返回与权限语义；内部构造方式可以随组合重构同步更新所有消费者。接口只服务真实消费者，不为每张表新建Protocol、DTO或基类。

## 调用流程

1. 调用方通过现有access/factory捕获Profile、settings与scope。
2. 组合入口选择Native SQLite桥接或PG资源，并注入Profile活动绑定、跨域查询/转换等实际能力。
3. 域内读写/工作流借用短事务；辅助查询复用当前Connection。
4. 提交后由原拥有者处理hook、投递和文件副作用；主业务回执、outbox和unknown恢复边界不变。
5. 调用方释放Handle；组件不会提前关闭共享池。后台线程、SDK事务和关闭失败继续按既有协议处理。

## 数据结构、接口及迁移约束

- 无业务表、列、约束、索引、数据、配置键或新数据库revision变化；REQUIRED_REVISION保持0031，稳定store_id/Board/插件/房间/Matrix账号键不变。
- 表模块及metadata/SCHEMA身份保留；31个已部署versions文件及revision/down_revision逐字节不改，Alembic目录和package-data资源仍原位。
- `migrations/merge_data_repair.py`等非revision帮助代码仅在必要处同步import，保留原算法/SQL与历史依赖例外；从0004、0030、0031的真实前向/重复升级必须验证。不通过旧路径空壳维持迁移。
- 实体返回值、DTO/异常身份、JSON字段、Worker/RPC命令名、回执operation值、目标摘要、编码字节和SDKpickle格式均不因Python路径变化改名。Task1核对是否持久化过模块全名；若发现，先记录兼容影响并修订方案，不能盲目换字符串。
- 现有公共入口/接口无能力扩张；内部导入路径明确随任务迁移，公开插件API保持现有承诺。当前plugin_api.json未发布hermes_db模块，不能把26个旧边界例外整体升级成公共API。

## 错误、可观测性与边界检查

保留StorageError/UnknownCommitError分类和显式失败；日志不输出DSN、密码、加密材料。原pool超时、断连、SDK内部吞异常后的故障传播和关闭语义保持。
使用现有lint机制验证导入边界，必要新增规则也归入scripts检查；不写读取.py源码的pytest“形状测试”。依赖台账须区分正常依赖、明确的纯模块复用、SQLite兼容桥接、历史迁移例外和待移除的运行时反向依赖，不用更新全量baseline掩盖新耦合。

## 实施隔离、恢复与回滚

正在运行的正式Hermes从`D:/AI/hermes-agent`加载源码。单独切Git分支不能阻止Python后续lazy import读到改动。方案文档在当前目录的独立文档分支准备；实施必须在不被正式进程引用的独立checkout，使用普通refactor分支。可使用worktree或本地clone，不强制特定工具。
实施前把测试HERMES_HOME/HERMES_RUNTIME_DIR绑定隔离目录，再初始化PM/导入应用；依赖仅由PM准备。PG仅用已有秘密文件和核对归属的随机Schema，不操作正式Schema、服务、扩展或角色，不输出连接信息。
每完成一个任务更新计划、真实命令/结果/未验证项/恢复点并创建本地commit。失败时回到最后已验证的代码检查点，不reset用户修改，不用自动DB降级、数据复制或SQLite回落恢复。
本次没有数据迁移，因此回滚对象是隔离分支的代码和imports；需要在实际独立载荷中验证新旧代码均识别已有0031。正式部署/重启属于代码可审查后的独立运行步骤，不在本轮准备方案时进行。

## 风险与验证

| 风险 | 可能性/影响 | 缓解与直接验证 |
| --- | --- | --- |
| 动态模块/patch点遗漏 | 高/高 | 全量映射与动态入口台账；真实CLI/Worker/房间路由和测试patch生产读取点 |
| MRO改组合后self依赖、快照pin或close分裂 | 高/高 | 两阶段、单上下文、真实并发读快照、关闭、元数据回执和unknown恢复合同 |
| SQLite间接加载PG/SDK依赖 | 中/高 | 公开入口driver-free；独立无PG依赖载荷实际读写/新进程重开 |
| 同名类双份、DTO或持久命令改名 | 中/高 | 不保留内部shim；实际类型身份、RPC/回执重放、既有0031数据重开 |
| 迁移、表或发行资源丢失 | 中/高 | 固定锚点、revision哈希、独立source payload及0004/0030升级 |
| 为减少文件改变事务/锁/文件IO边界 | 中/高 | 真实PG竞争/CAS/COMMIT丢ACK、文件token及实际supervisor/collector |
| 重构工作区干扰正式运行 | 高/高 | 独立检出与隔离Profile；方案阶段仅文档，不停止正在验收的服务 |
| 异常基线/SDK/PG环境不完整 | 中/高 | 记录阻塞并继续独立任务；必需实SDK/PG证据缺失时不完成对应任务 |

## 验收标准

以下仅为本次分包范围，最新完整批次与限制见[实施计划](../plans/hermes-db-package-layout-plan.md)，独立结论见[审查报告](../reviews/hermes-db-package-layout-review.md)。

- [x] 398项基准各有唯一处置，新增模块也有归属；根目录只剩列出的11个实际入口/定义。
- [x] 阶段二后文件总数与业务模块数净减少；给出合并/保留理由，不遗留全局operations/repositories及临时Mixin碎片作为最终结果。
- [x] Session/Runtime的36/10 Mixin组合已收敛为显式组件，公共业务能力无缺失，无万能动态转发。
- [x] 依赖方向明确，运行时私有门面反向依赖关闭，纯共享模块/Native桥接/历史迁移例外逐项可审议；插件API和边界baseline不扩大。
- [x] SQLite无PG extra能真实工作；PG完整业务进程拒绝全部SQLite连接，证明业务、持久化、scope隔离和新进程恢复。
- [x] 当前Matrix SDK真实加密对象和PG读写/重开/并发通过；不是仅类名或导入检查。
- [x] 0001–0031 revision哈希/图不变；现有0031数据可重开，旧版本真实前向/重复升级及独立发行资源通过。
- [x] 每项使用标准runner完成适用消费者验证；最终verification-before-completion、独立code-review及整改后复验有最新证据。
- [x] 正式Profile、PG数据、SQLite数据、运行进程未被开发测试或工作区改动影响；部署另行记录。

## 重要假设与待决策项

用户已认可按域分包方向并授权实施；18项已在不被正式进程引用的独立检出完成，正式源码与运行实例保持原状。内部模块路径可更新，真实公共存储能力需保持。使用现有技术栈和Schema，故无新数据库选型或核心设计待决策。
原统一后端Task24七项非WSL平台缺证及当前未重跑的全仓/前端范围继续独立记录；新分包验证不能倒写其完成。任何新增外部兼容需求或持久模块名发现，先记录影响并修订设计。

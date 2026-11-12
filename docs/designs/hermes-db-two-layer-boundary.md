# hermes_db 基础设施与业务持久化分层设计

## 文档状态

- 状态：`READY_TO_MERGE`；2026-11-12。20/20完成，独立最终复审APPROVED；R1最小修正、真实红绿灯与v2全组复验通过。5freshPM载荷、10批159passed/3真实平台skip、24019文件hash及固定资源核对通过；初版CHANGES_REQUIRED/158结果单独保留。结论仅限本轮两层分层，不外推全系统验收。
- 日期：2026-11-10；设计基准：`0d8782ba8adb168a86abb6a8e338591d70d03428`。
- 隔离目录：D:/AI/hermes-db-packages；实施分支refactor/hermes-db-two-layer-boundary。实施期间正式D:/AI/hermes-agent保持90a2987e8c；2026-11-12用户后续授权本地快进合入47e2317fa03f供运行验收，详见[实施计划的本地合入记录](../plans/hermes-db-two-layer-boundary-plan.md)。
- 依据：[持久层精简设计](hermes-db-persistence-scope.md)、[已完成实施账本](../plans/hermes-db-persistence-scope-plan.md)、[逐项映射及固定锚点](hermes-db-persistence-scope-map.json)、[统一后端设计](unified-database-backends.md)。本设计不改写这些工作的历史验收。

## 背景与目标

本节描述0d8782ba8a基准的设计背景；当前落地状态见文档开头与实施账本。

当前目录主要按领域归组，基础设施、领域持久化和应用协调仍有交叉。factory既选后端又创建业务资源；core.catalog列出业务能力和表；SQLite backend获取代码适配Session/Runtime；integration装配Profile、CLI DTO、Worker和文件能力。需要建立可检查的职责边界。

hermes_db承担两类职责：基础设施管理数据源及其生命周期，业务持久化管理业务数据模型和具名存储操作。Profile解析、Worker进程调度、文件系统副作用及应用事件归应用调用方。业务持久化使用基础设施；基础设施不内置Session、Kanban、Room等业务名单，也不读取当前Profile或Worker状态。

目标是在保留业务合同、SQL及并发语义的前提下，使两类职责可分别定位、导入和验证。SQLite可在无PG依赖的独立载荷中运行，PG完整业务继续拒绝全部SQLite连接。

## 功能范围与非功能范围

范围包括后端选择、资源/连接/事务与迁移执行的归属；业务API、查询、数据约束、回执及Schema声明的归属；现有integration逐函数归属；应用所有者解析和装配外移；所有直接/动态消费者、patch点、发行资源及边界检查同步。

保留SQLAlchemy Core、psycopg、Alembic和原生SQLite SQL。业务方法、DTO、异常身份及对外CLI/RPC行为保持。内部获取与装配接口允许调整，但须同步全部真实消费者；不保留旧内部路径re-export shim。

不增加第三种后端、动态后端注册框架、统一CRUD/SQL翻译框架、通用事件/Outbox框架、兼容flag或外置数据搬迁工具。不恢复已退役的repair-profiles、stranded adoption和搬移授权生成。不执行数据迁移、Schema降级、正式启用、服务管理或部署。

## 可选方案与比较

| 方案 | 结构与流程 | 复杂度与维护 | 兼容性与测试风险 | 决定 |
| --- | --- | --- | --- | --- |
| A 维持目录并补依赖规则 | core/backends/domains/integration原位，逐项清理反向依赖 | 实施成本较低；目录仍不能直接说明所有权，integration容易继续扩张 | 消费者移动较少，纯基础设施边界较难核实 | 可作中间检查点 |
| B 两类职责与应用装配外移 | 独立infra，业务domains及Schema资源有明确所有权，应用协调回到现有应用拥有者 | 实施成本中高；长期依赖和变更范围明确 | 逐领域验证真实消费者、生命周期和SDK，机械移动与职责调整分别验收 | 推荐 |
| C 拆成独立发行包 | 基础设施作为独立分发，业务存储另一个包 | 增加打包、版本和安装维护，当前没有独立外部消费者 | 多一层发行/版本兼容测试，收益尚不足 | 暂不采用 |

选择B。目录服务于依赖边界；不能只改包名后保留反向业务调用。保留固定资源的原路径约束，不以目录整齐为理由重写历史链。

## 推荐分层和目录

```text
Hermes应用层（hermes_db之外，按现有应用所有者组织）
  Profile配置解析、可信owner解析、业务流程
  Worker进程/RPC、文件操作、事件通知、对象装配
                         |
                         v
hermes_db业务持久化层
  业务合同、表映射、查询、写入规则、回执和持久化意图
                         |
                         v
hermes_db基础设施层
  数据源选择、连接/池、事务、资源释放、版本检查和迁移执行
                         |
                         v
                 SQLite / PostgreSQL
```

当前目录落位（2026-11-12用户确认简化，见[后续实施计划](../plans/hermes-db-infra-layout-plan.md)）：

```text
hermes_db/
  根部11个实际入口/定义          按下文明确所属职责
  infra/                       基础设施执行区域
    resource.py                通用连接/事务资源，不含sessions/runtime成员
    sqlite/                    SQLite连接、并发和生命周期执行
    postgresql/                PG池、短事务、超时和生命周期执行
  domains/                     业务持久化区域
    sessions/                  业务API、规则及各后端存储实现
    runtime/
    kanban/
    cron/
    rooms/
    projects/
    verification/
    metrics/
    plugin_storage/
  tables/                      业务表定义；固定29模块原位保持
  migrations/                  PG业务Schema资源；既有31 revision及配套资源原位保持
  core/                        固定资源仍引用的实际共享定义，按模块归属，禁止继续充当混合入口
```

本轮后续简化的实际新路径及消费者见[infra目录映射](hermes-db-infra-layout-map.json)；原两层映射与冻结记录继续描述其对应历史源码。

这两类职责不要求只有两个物理目录。tables/migrations属于业务模型的资源；core残留定义受固定导入约束。基础设施以明确模块集合检查，不能因为旧目录叫core就把其中的业务清单视为基础设施。

### 固定路径与core清单

已核对tables/__init__.py直接导入hermes_db.core.catalog.POSTGRES_DOMAINS。该文件属于既有固定锚点，禁止为移动catalog而改写它，也不将catalog改成旧路径转发壳。因此core/catalog.py保留真实业务Schema/能力清单定义，归业务持久化所有。受历史资源直接依赖的其他实际共享定义也按逐项映射处理。

infra不得依赖core.catalog、tables或具体领域。其事务Schema翻译配置由业务Schema描述传入，消除当前transactions.py直接引用tables.metadata.SCHEMA的依赖。业务查询投影/身份编码与驱动通用能力分别判定，不把所有PG表达式辅助都自动归底层。

### 根部入口

根部继续保留11个实际入口/定义。settings/errors/scope和纯后端选择属于基础设施；包含Session/Runtime成员的DatabaseHandle、SessionStore合同和会话入口属于业务持久化。根schema入口执行显式生命周期，业务Schema及能力描述由调用方提供。health保留真实业务存储身份纯助手；Profile配置解析/探测协调外移db_diagnostics，连接技术探测由infra提供。maintenance中的DB数据维护归业务层，文件/Profile周期协调归应用。

factory去掉业务领域构造和Profile解析，提供已解析配置下的实际后端获取。应用装配解析Profile后选择后端、构造具名Store，再交给业务调用者。内部acquire_db/acquire_domain/acquire_profile_domain和access获取签名的最终处置必须在实施映射列出；不能承诺旧内部路径永久兼容，也不能静默改变正常业务方法。

## 两层职责合同

### 基础设施

- 输入已解析的DatabaseSettings、稳定scope及显式生命周期参数；不自行导入hermes_cli/gateway/agent寻找Profile。
- 管理连接、PG池复用、SQLite原有并发语义、PID边界、借用/释放、超时、事务提交/回滚和底层错误分类。
- SQLite按既有单写者/线程及连接策略实现；不强制与PG使用相同池模型。
- 事务资源不带session_store、Kanban对象、Worker注册等业务成员。现有DatabaseHandle仍可作为业务聚合句柄使用。
- 只支持当前实际实现的两种后端；资源获取失败明确报错，不回落、不双写、不自动复制数据。
- 普通获取/read/write不DDL；初始化、状态检查及升级是显式生命周期调用。SessionDB原公开创建构造如保留，属于真实创建/升级入口；普通生产获取统一走open_existing，不增兼容flag或隐式exists初始化分支。

### 业务持久化

- 持有业务表、查询、约束、编码规则、状态写入、CAS、领域锁顺序及回执身份。
- 操作使用捕获的scope和同一次Connection；Repository不创建Engine、不重新选择Profile、不自行commit。
- 事务原子性的决定由完整业务操作所有者作出，基础设施执行事务。跨领域同连接操作保留明确所有者；跨数据库目标的流程不假称全局原子。
- SQL、锁、receipt和unknown恢复条件与现有算法保持，公共值和异常身份保留；SQLite及PG实现可继续采用不同SQL组织方式。
- 模型、进程、网络和文件等待由应用协调；原有必须同一锁范围的短本地回收临界区由包外应用持原短事务完成，不在本次架构移动中改变原子顺序。确需持久化意图时复用现有file jobs、receipt和恢复记录，不引入无消费者的新框架。

## migrations的归属

每个后端的连接、升级锁、版本读取、执行及失败分类属于基础设施执行器；创建哪些业务表、列、约束及版本顺序属于业务Schema资源。

PG保持一条既有31 revision链，资源及61固定Python锚点/4项迁移资源保持原路径和字节，不按领域拆散或压平。实际SQL表模块及metadata身份不变。核心执行器接收业务Schema的资源位置、目标版本及技术校验要求，业务层汇总各领域能力和缺失表；核心不硬编码业务名字。

SQLite保留各原生存储的真实版本演进。实施必须将连接获取与已有Schema初始化/升级责任分开，覆盖首次Profile/领域创建的显式初始化入口及已有库普通重开；不能通过删除首次创建能力获得“无DDL”结果，也不把初始化藏进普通open。

## integration的具体处置

| 现有代码 | 新职责归属 | 必须保持 |
| --- | --- | --- |
| session/domain/runtime_composition | 应用装配，按Session/Runtime/各业务实际拥有者落位 | DTO/异常身份、参数、scope、资源关闭 |
| registry | 通用生命周期机制归基础设施；Session/Runtime构造及聚合注册归业务/应用 | PID/配置/scope键、并发构造、引用计数、最后释放 |
| kanban_application/worker/owner/wire | Profile、进程、RPC及文件适配归现有应用拥有者；DB代次/claim/receipt规则留领域 | 可信owner、冻结Board代次、认证RPC、outbox命令身份 |
| media_grants | 数据库授权读取、验证、引用和多scope锁规则归业务持久化 | 既有授权pin、token/recipient/owner核验、安全释放 |
| media_retirement | DB候选/引用/回执查询留业务；文件身份、租约、实际回收归应用 | 最后引用、文件替换保护、提交后副作用和中断恢复 |
| profile_lifecycle | 正常Profile数据清理归具名存储操作，触发及目录生命周期归Profile应用 | 历史保留、路由/心跳/投递/topic隔离及顺序 |
| session_portability / transfer/kanban | 逻辑业务快照/导入原子写留领域，归档文件和发布协调归应用 | 正常导入导出、stage/job、hash校验、unknown恢复 |
| backends/sqlite/acquire中的业务代理 | Session/Runtime适配归业务层，连接/释放机制归SQLite基础设施 | 不重写Native SQL，不制造PG的伪SQLite接口 |

配套文档：[实施计划](../plans/hermes-db-two-layer-boundary-plan.md)、[逐项映射](hermes-db-two-layer-map.json)。

最终不保留一个包内通用integration收纳所有应用工作。需要共享的应用装配按真实消费者归属现有agent/hermes_cli/gateway等区域；跨入口共用时必须在逐项映射中确定唯一拥有者，不能复制多份或堆入通用utils。逐函数及候选读取点已列入配套映射；实现前Task1仍核对动态运行读点，目录建议不代表代码已移动。

## 正常流程与错误处理

1. 应用在新会话/服务资源创建时解析可信Profile、配置和owner权限；Worker继续走owner RPC，不获得直接打开owner存储的新入口。
2. 选择一处数据源，取得基础设施资源；显式校验Schema，由应用组合实际业务Store/DTO/窄能力。
3. 领域执行具名业务操作，按原有同连接、scope、锁、回执语义提交；网络/文件/进程等待释放连接。
4. 应用执行已有提交后效果，使用现有持久意图/令牌恢复。提交结果未知时保留原命令和stage，恢复原receipt，不盲目重放或创建新身份。
5. 调用者关闭业务资源，基础设施按原有引用与进程池生命周期释放；一个资源关闭不影响仍活动的其他资源。

后端切换继续只选择独立数据集，在新进程/新会话生效；不热换运行会话或提示缓存。错误类型复用现有Storage*和业务异常，不复制新的同名异常，也不输出DSN、密码或原始失败堆栈。

## 数据结构与接口

无业务表、列、索引、业务DTO、配置键或持久化数据格式变化。SQLite Schema诊断可增加就绪/版本字段和明确失败退出，原诊断字段保持；业务RPC/Worker形状不变。复用现有DatabaseSettings、DatabaseScope、DomainSpec及真实Schema资源信息；根据实际生命周期消费者确定最小输入字段，不增加反射代理或开放插件注册层。

业务Store具名方法与返回保持。内部获取、装配、资源构造及patch读点随落位同步调整。基础设施接口覆盖实际借用、事务、状态、显式初始化/升级和关闭；业务API覆盖实际领域能力。尚未指定最终函数签名的内部入口必须在实施计划前完成逐项映射，禁止在编码中临时发明通用CRUD。

## 推进顺序

1. 从0d8782ba8a冻结模块/符号/消费者、SQLite Schema入口、事务与外部效果边界，建立两类职责及应用拥有者映射。
2. 先提纯基础设施：解除业务catalog/metadata/Session/Runtime依赖，沿用真实驱动及生命周期；不同时重写SQL。
3. 从小领域到Sessions/Runtime，再到Kanban/Rooms，逐域同步迁出应用装配与副作用，保留操作原子性和恢复材料。
4. 完成SQLite业务适配与底层连接/Schema责任拆分；未完成该项不能声称两后端都完成分层。
5. 更新边界规则、活动文档/skills/AGENTS、动态表和patch点，删除空的旧内部路径；冻结当前载荷重新完整验收与独立审查。

这五项是设计推进顺序。实际Task状态、命令和本地恢复提交以实施计划为准；当前20/20已完成，Task20 R1整改源完成新冻结/全批次复验并独立APPROVED，保留0d8782ba8a的既有精简基准；当前验收按用户精简策略及冻结清单执行。

## 风险与验证

| 风险 | 影响 | 控制与可观察验证 |
| --- | --- | --- |
| 移动锁或事务边界 | 重复执行、丢回执或跨scope写入 | 保留Connection和锁顺序；真实并发与COMMIT后丢ACK/新PID恢复 |
| 固定资源间接导入失效 | 旧版本升级/发行失败 | 保留61+4及直接依赖可解析，独立安装载荷前向/重复升级及0031重开 |
| 应用外移丢Profile绑定 | 默用默认Profile或错误文件回收 | 多scope/跨线程/新PID合同、文件owner与最后引用合同 |
| SQLite抽取改变Native行为 | 初始化、WAL/线程/关闭退化 | 无PG依赖载荷真实读写恢复、首次显式初始化及普通打开无DDL |
| 缩小API破坏正常消费者 | CLI/Gateway/Worker恢复失败 | 同步所有实际读取点，混合测试保留正常断言，完整业务命令exit0 |

测试仍只用scripts/run_tests.sh，依赖只由项目PM管理；先绑定隔离HERMES_HOME/HERMES_RUNTIME_DIR。PG仅fixture核对归属的随机Schema，完整PG业务拒绝全部SQLite连接。正式Profile、配置、秘密、业务数据及服务不改，测试日志不泄密。原Task24、七项非WSL缺证及Windows Profile8项基准问题独立保留。

## 验收标准

- [x] 基础设施不导入业务catalog、业务表、CLI/Gateway/Agent装配或业务Store；不存在绕过边界的动态路径。
- [x] 每个模块/函数有基础设施、业务持久化或应用拥有者；历史固定路径有真实定义和明确归属，无shim/代理/兼容flag。
- [x] SQLite业务适配与底层生命周期完成分离，PG保留真实SQLAlchemy Core/SDK及连接池语义；两端业务合同保持。
- [x] 各后端显式Schema生命周期可用，普通open/acquire/read/write不DDL；31 revision/29表模块/61+4内容和路径保持。
- [x] 既有授权、正常Profile生命周期、导入导出、Session/Worker恢复、原子写和unknown commit恢复通过。
- [x] 当前冻结源的双主机Native、消费者、计划精简PG完整批次、发行及真实SDK批次实际exit0；skip与未验证范围具名；独立APPROVED。
- [x] 默认保持DB Python不超过359、根11；改名不算净减少，新拆分须以同职责收敛抵消且满足复杂度上限，不删除正常覆盖。

## 重要假设与待决策项

采用单repo、现有技术栈、两种已实现后端和固定Schema资源；内部调用路径可调整，业务合同及原锚点约束继续有效。新namespace infra用于明确执行基础设施，domains及固定资源构成业务持久化；root按实际职责分类。

推荐方案无需要立即解除固定锚点、放宽文件预算或引入新技术的核心决策。用户已要求准备实施方案；逐符号归属、应用目标、内部接口和路径预算见配套映射/计划。实施从Task1核对实际基准与完整调用点开始，不把本轮规划当作实现或业务验收。

## 回滚与设计阶段验证

实施回滚只恢复代码检查点，不回迁/降级数据。历史资源、SQL和算法保持，应用外移分步验证；每个实施Task实际证据和本地提交由后续计划记录。

以下为2026-11-10规划阶段的历史记录，不作为当前执行状态：当时准备此设计、20项实施计划及逐项映射，没有修改生产/测试、旧计划/映射/审查记录或正式实例。设计自检核对本地链接、基准HEAD、现有路径和固定资源直接导入；当时业务测试未运行，验收复选框未完成；当前验收以本文件开头及Task20最终证据为准；规划结构/资源/接口自检结果见实施计划准备记录。

2026-11-11 Task2预算核算修订：同职责PG查询路径/投影助手合并为domains/sql/postgresql.py，原空expressions包移除，抵消infra与domains/sql两个新初始化文件；中间Task也遵守359上限，规划路径并集350→348，不宣称移动或合并减少业务算法。

## 应用实现读点

Session/Runtime装配由hermes_cli/db_sessions.py、db_runtime.py和db_session_lifecycle.py拥有，
延迟accounting线程由db_usage_writer.py拥有。业务registry接收实际owner的build回调；
构造读取点与测试patch位于hermes_cli.db_sessions._construct_store。Native装配不加载PG依赖。

archive/media文件协调由db_archive_files.py和db_media_retirement.py拥有，文件身份由
db_file_identity.py拥有，Profile维护协调由db_maintenance.py拥有。业务maintenance接收已有
Connection/scope；引用检查与本地unlink保持原短事务及锁顺序，长file-job准备/发布保持连接外。

Gateway的session_storage_authority.py拥有claim检查和owner-memory commit协调，
session_worker_process_proof.py在数据库访问前捕获PID/birth证明。保留原same-Connection历史授权、
publication顺序，以及Session map fence到session_ingress_media capture lease lock的原顺序和最后pin保护。

Task11小领域拥有者：cron/storage_application.py绑定具体Cron runtime；agent/runtime_metrics_snapshot.py
负责Snapshot获取/Worker路由，agent/runtime_metrics_store.py负责现有Metrics RPC facade。
Metrics的Profile/ref打开与具体PG store/sender组合在shared_metrics_postgres.py，HTTP transport在
shared_metrics_transport.py，本地package导出在shared_metrics_export.py；以上均归hermes_cli/observability。
worker_metrics_bridge.py拥有root/consent/owner-clock准备及提交后Root replay，业务worker_metrics仅作原子SQL/CAS。
共享队列常量/parser是metrics.policy真实定义；bound metrics仍借用原receipt Connection，普通打开验证捕获的target。

Task12 Kanban拥有者：kanban_storage_application.py拥有具体capabilities、Worker/Profile选择装饰器、
闭合dispatch表和connect；kanban_storage_owner.py拥有捕获Profile/代次后的文件scope与实际acquire。
纯board_reference/validate_reference及已给Connection的board_generations查询在domains/kanban/owner.py。
RPC codec在kanban_storage_wire.py，Worker proxy在agent/runtime_kanban_storage.py；原DTO/命令/回执形状不变。
dashboard通过既有kanban_db模块读取实际已消费的decorator，不增加facade定义、私有API白名单或旧路径shim。

2026-11-11用户验证范围修订：本轮是分层拆分，既有PG改造已深度验收，因此后续采用与分层直接相关的关键合同和新载荷冒烟，取消目录级全量/重复旧业务深测；不把旧成功算成本轮结果。实现范围、固定资源、数据隔离和最终独立审查不变。实际验收范围以计划“验证策略修订”和Task16冻结清单为准，不宣称全系统重新验收。

Kanban事务/文件边界：`hermes_cli/kanban_storage_<workflow>.py`拥有Profile策略、Worker/租约线程、文件准备/发布/清理和post-commit通知。领域`postgres`模块保留具体SQL、快照、CAS、约束、回执及原短事务文件栅栏；应用仍在原连接/锁位置调用。动态读取点位于`kanban_storage_application._KANBAN_MODULES[(topic, operation)]`；测试patch按真实定义迁移。逻辑归档文件入口是`hermes_cli.kanban_storage_transfer`，业务快照/图写入是`hermes_db.domains.kanban.postgres.transfer`。

Rooms应用读取点：`gateway.hosted_room_storage`捕获Profile/target及选择后端；`gateway.hosted_room_attachment_store/files/reads`持有原文件gate、内容发布/回收和读取两侧授权重核，`gateway.hosted_room_policy_store`协调日志cursor。TUI的`hosted_room_router_storage`保留原RouterCallLifecycle，具体同连接CAS/TTL与release SQL位于`domains/rooms/postgres/router_claims.py`。RoomStoreRef/RoomResource/metadata业务合同原位保留。

插件获取读取点：已发布 `plugins.plugin_storage` 持有 Profile/Worker、具体 Matrix/Discord wrapper 及 portable provider；SQL 和记录合同留在业务域。Matrix actor/executor 在 `hermes_cli.db_matrix_runtime`，业务 Store 接收捕获 reference 和真实 provider。API 获取在 `hermes_cli.db_api`，Profile Run 生命周期在 Gateway；OwnedApiStore 留在业务域。Native API、portable、Discord、Retain、Matrix 普通打开只检查既有 Schema；创建/升级由 Profile 生命周期、插件启用/setup 或各插件显式 db upgrade 执行。Matrix 原 SDK 升级表只用于显式升级；缺失/旧 Schema 拒绝普通打开并保留旧 pickle。

Task16实际API收口：Cron `domain_operation`及闭合后端表归现有 `cron.storage_application`；Verification真实 Profile/Worker分支归 `agent.verification_storage`。业务 `api.py` 不再有装配例外；纯规则复用仍按符号审查。退役integration五个空Python包入口删除，不保留shim。

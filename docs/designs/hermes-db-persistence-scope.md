# hermes_db 持久层职责精简设计

## 文档状态

- 状态：`IMPLEMENTING`；用户已授权按本方案逐Task实施并本地提交，Tasks1–6已完成；最终完整验收与独立审查待Task8–9。
- 日期：2026-11-10；源码基准：`90a2987e8c`，运行时代码等价`9a8093841b`。
- 分支：`refactor/hermes-db-persistence-scope`；隔离检出：`D:/AI/hermes-db-packages`。
- 关联：[实施计划](../plans/hermes-db-persistence-scope-plan.md)、[逐文件处置映射](hermes-db-persistence-scope-map.json)、[统一后端设计](unified-database-backends.md)、[已交付分包设计](hermes-db-package-layout.md)。
- 准备历史：`7f151a3299`保存了首轮职责核对。规划阶段将旧的A/B待选草案收敛为推荐A的单一路线；后续用户明确授权本轮整体退役实施。准备记录不计为实施证据，部署仍未授权。

## 背景与目标

`hermes_db`是可替换的持久层。顶层选择`storage.backend`，业务通过同一组具名操作使用所选后端。当前已实现SQLite/PostgreSQL；增加其他后端必须有真实实现和合同验证，不把任意配置字符串当作已经支持。

后端切换选择独立数据集，不代表应用负责把旧数据搬过去。普通打开、启动、恢复不自动复制另一后端或另一Profile的数据，不双写、不回迁，后端故障不回落SQLite。

上一轮分包保留了现有方法，包括历史修复。本轮按职责缩减接口：保留业务持久化、完整事务、锁、scope、回执、unknown结果恢复与资源生命周期；退役旧版本错Profile数据修复及自动承接分支。有消费者意味着要处理调用链，不意味着必须保留这个功能。

## 推荐范围与兼容性决定

采用**整体退役**方案：删除`hermes sessions repair-profiles`及双后端专用实现；删除TUI普通resume时的stranded-session自动承接。不给它们换目录、兼容空壳、开关或外置工具继续维护。

这是本实施方案的明确产品取舍：旧命令将按标准未知子命令拒绝，不会再扫描或修复历史数据；曾写错Profile的数据留在原数据集中，不再由恢复流程自动复制。已有正常会话和文件引用保持可读，用户不需要为此次代码精简执行数据搬迁。

保留：正常业务导入导出、其他工具的会话导入、Kanban归档、Profile删除/重命名及其失败重试、当前会话恢复/分支/压缩、Worker和调度恢复。`profile_paths`及正常rename的`migrate-identity`属于用户发起的Profile生命周期，不是更换数据库后端的数据转换，不能仅按名称删除。

Schema初始化、校验和显式升级属于后端生命周期。本轮不压平Alembic，不改`0031_merge_data_repair`要求、31个revision、29个表模块及历史SQL/算法。保留0031必要辅助代码，不在普通启动执行它。保留版本链不等于提供SQLite↔PG数据迁移。

## 方案比较

| 方案 | 复杂度/维护成本 | 兼容性与验证风险 | 结论 |
| --- | --- | --- | --- |
| A：整体退役历史修复 | 删除命令、双后端方法和专用模块，成本最低 | 明确取消旧修复与自动承接；需保护正常resume和生命周期 | 本方案采用 |
| B：外置可选维护工具 | DB合同可缩小，但仍须维护两套SQL/锁/版本协议及安装 | 容易把原耦合改成工具对私有连接的依赖，继续承担迁移职责 | 不纳入本轮；若将来另有真实需求独立设计 |
| C：仅改名称或目录 | 实施量小，维护面不减少 | 旧行为和合同仍存在 | 不满足精简目标 |

## 调用流程与前后行为

1. 顶层捕获Profile配置及稳定scope，工厂选一种后端；领域操作不重选Profile或backend。
2. 后端执行自己的SQL/事务。缺配置、未初始化、不支持或不可用时明确失败；不会扫描另一数据集补齐。
3. `session.resume`在拥有者store中查找。已有行正常恢复；真实live-lazy与server-minted-key恢复保留；普通不存在目标维持既有4007结果，不打开default store尝试收养。
4. 删除Profile继续清理其路由、心跳、待投递及topic身份，保留原历史与其他Profile状态。
5. 媒体/溢出文件的已有有效授权继续参与pin、可见性和安全回收；停止生成新的跨store搬移授权。代码精简不清理持久化票据、重写历史文本或删除文件。

## 逐项处置与职责归属

完整路径、基准Git blob SHA256、任务、消费者和测试处置见映射JSON。主要变化如下：

| 代码 | 处置 | 正常行为保护 |
| --- | --- | --- |
| `integration/postgres/operations/profile_move.py`、`queries/profile_move.py` | 删除 | 先移除历史adoption消费者，不留snapshot空壳 |
| `integration/postgres/operations/profile_repair.py`、`queries/profile_repair.py` | 删除 | 先把实际共享的`delete_routes`归到现有`domains/sessions/postgres/queries/gateway.py`，同步所有调用和patch点 |
| `integration/postgres/operations/adoption.py`、`integration/transfer/move_values.py` | 删除 | 与SQLite adoption及TUI调用同任务退役；move_values在其最后消费者移除后删除 |
| `hermes_state_profile_repair.py` | 删除 | 移除SessionDB Mixin/import；维护专用helper/异常无剩余消费者才删除，不修改正常错误身份 |
| `hermes_cli/sessions_repair_profiles.py`、`sessions_cmd_repair_profiles.py` | 删除 | 同时清理parser、dispatch、活动文档和专用测试 |
| PG store及SessionTransfer中的16项维护/兼容方法 | 删除 | 逐方法比对，其他业务方法签名、DTO及返回保持；16项含私有`_ledgered_session_ids` |
| `integration/postgres/operations/profile_purge.py` | 保留行为，收敛为`integration/profile_lifecycle.py` | 只改所有者/导入，不改scope、锁、删除顺序及终态投递 |
| `integration/postgres/operations/file_grants.py` | 去除跨store生成部分，收敛为`integration/media_grants.py` | 保留received/origin/lock/release及已有授权读侧 |
| `integration/transfer/session_store.py` | 收敛为`integration/session_portability.py`与SessionPortability | 保留真正业务导入导出、外来会话导入及现有业务读取；无完整Facade反向依赖 |
| `migrations/versions`、`tables`及必要迁移资源 | 原位保持 | 61固定锚点与4项迁移资源按本轮基准逐字节保持 |

预计DB Python模块从365减至不超过359，根目录仍11；另删除3个维护生产文件。3个现有模块改名不计作净减少，新增行为测试不与生产模块混算。若实际依赖导致新生产模块或额外保留，先修订映射和理由，不能用新目录掩盖职责未退役。

## 数据结构与接口

无表、列、索引、配置键或业务DTO变化，不清理旧数据。现有业务方法及Runtime合同保持；维护方法的取消属于本轮明确兼容性变化。精确16项列表在映射的`retired_postgres_store_methods`。

删除`adopt_session_lineage_from`及SQLite专用`_retire_donor_segment`，删除`_resume_adopt_stranded`定义/调用。内部组合构造可同步重命名`transfer`为`portability`，必须修改生产读取点与直接消费者，不保留旧路径re-export或反射代理。

文件授权中仅由搬移/adoption消费的`transfer`、`_grant`、`_texts`、`_mentioned`、`_known_media`、`_subset`在调用链清空后删除。读侧与release不能依赖已删的创建函数；测试直接构造临时库中的既有有效授权记录，再执行真实普通读取/回收，而不是为保住旧测试继续调用搬移功能。

## 测试处置

- 明确退役repair/move/adoption专用测试，记录每个被取消用例的功能理由，不冒称它们改成通过。
- 混合文件逐用例拆分。`test_review_data_safety.py`保留prepared compression晚到写入冲突；`test_file_consumers.py`保留roster/stats/resource release/backup；`test_health_archive_refs.py`保留health/archive backfill/retention/purge/concurrency，清理其导入与参数表。
- `test_profile_file_scope.py`验证正常Profile目录重命名和恢复，必须保留。普通import的inactive/checkpoint标记、deleted-parent、真实minted/lazy恢复也保留。
- 新增有行为价值的边界：错误Profile中存在同ID时，普通resume不复制/归档/删除源数据；不支持的旧命令在存储打开/写入前拒绝；切换backend只选择各自数据集；已有授权仍防误删。
- 不新增源码文本匹配、方法存在性快照或方法数量pytest。接口/文件/锚点清单属于独立操作审计，不代替行为测试。

## 配置切换与验证设计

在独立临时Profile中，用项目配置写入接口选择backend，每次启动新子进程/新会话观察结果；不在一个运行会话中热切后端或重建缓存提示。

SQLite子进程来自无SQLAlchemy/psycopg/Alembic等PG依赖的独立PM载荷，写入其标记；PG子进程来自另一个载荷，仅连接fixture核对归属的随机Schema，读取不到SQLite标记并写入PG标记；切回SQLite仅看到原SQLite数据；再开新PG进程只看到PG数据。控制进程不冒充PG完整业务进程；后者拒绝全部SQLite连接（内存、URI、别名与直接构造），不能通过同进程混跑两后端豁免规则。

已有参数化业务合同继续覆盖两个后端，不引入统一CRUD框架或SQL字符串翻译。真实Matrix SDK协议/PG读写与新PID恢复继续执行；旧720/31等结果只作历史参考，精简后的用例数按实际收集/退役清单报告。

## 风险、隔离与恢复

| 风险 | 直接控制与验证 |
| --- | --- |
| 删除共享路由清理破坏Profile删除 | 先移动唯一实际定义，保留相同Connection/scope/锁，运行双后端purge合同与真实PG组 |
| 删除授权创建顺带破坏旧文件读侧 | 先建立既有授权普通行为合同，保留pin/release，并验证最后引用前不能删除 |
| resume退役补偿误删真实恢复 | 同步测试owned-store、minted/live-lazy、压缩tip、handle释放、错scope/未知目标 |
| 删除旧测试掩盖正常功能回归 | 逐文件/用例处置台账，混合文件拆分，完整DB Native/PG与消费者组重新执行 |
| Schema或数据被改写 | 不连接正式数据；61+4资源hash和0031不变；所有PG测试验证随机Schema归属 |
| 后端切换误读另一库或故障静默回落 | 独立载荷多进程数据集隔离+全部SQLite拒绝，显式故障证据 |

正式Hermes当前从`D:/AI/hermes-agent`运行。本轮在独立checkout实施；PM/应用导入前绑定隔离HOME/RUNTIME，依赖只由项目PM管理，测试只用`scripts/run_tests.sh`。不改正式配置/秘密/业务数据，不管理PG服务/角色/扩展，不输出秘密或原始失败堆栈。

回滚只恢复隔离分支代码检查点；不降级Schema、回迁或清理用户数据。已有文件授权的兼容读取不等于继续提供跨后端搬移服务。发布、合并及正式进程切换是最终代码可审查后的独立步骤，本次准备方案不执行。

## 验收标准

- [ ] 已实现后端通过统一配置选择；业务流程不按数据库类型分叉，缺配置/故障不回落。
- [ ] 16项维护/兼容方法和9个专用生产文件按映射处置；无旧CLI、自动stranded adoption、搬移票据生成或内部shim。
- [ ] DB模块不超过359、根11，所有其他业务合同及正常Profile生命周期保持。
- [ ] 既有文件授权可安全读/回收，历史数据不搬、不删；正常导入导出与恢复通过。
- [ ] 独立SQLite与真实PG多进程数据集选择/持久化/隔离、实际SDK均有当前证据，PG完整业务0 SQLite尝试。
- [ ] 0031、61锚点和4迁移资源不变，无新Schema/配置键/核心工具/通用框架。
- [ ] 活动文档、动态入口、patch与边界台账同步，完整命令exit0、最终审查APPROVED；所有skip具名。
- [ ] 正式实例/数据未受开发影响；原统一后端Task24及七项非WSL缺证独立保留。

## 重要假设与待决策项

本轮按用户已确认的“持久层不承担迁移”定位实施整体退役，不新增外置维护产品。不存在阻止形成可执行计划的技术待决策；开始实施按本方案执行。若用户改为要求保留旧修复入口，须先修订为另一份外置工具方案，不能实施中静默改回兼容模式。截至Task7，退役与正常组件收敛已实施并完成局部合同验证，独立载荷证实后端仅选择各自数据集；完整发行/双后端最终验收与独立审查仍待执行。未部署、重启正式实例或操作正式业务数据。

## 当前实施核对

Tasks1–6本地提交已完成，DB实际365→359、根11、16项Store维护方法取消，3模块改名不计净减少；61固定锚点与4迁移资源保持。映射新增第23个相关混合测试test_insert_counts.py，保留正常Worker change tracking。Task7进一步保留默认store中的title碰撞无读取/无复制合同，审计边界registry无涉及被删/改名integration路径的consumer+symbol条目，因此不为凑改动重刷权限。

Windows Profile八项在独立90a基准上同ID复现，当前未解决，单独保留；原统一后端Task24及七项非WSL缺证也仍独立。局部通过不构成全系统或正式运行验收。

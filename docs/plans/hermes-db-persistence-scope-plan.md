# hermes_db 持久层职责精简实施计划

## 关联设计与当前进度

- 设计：[职责精简设计](../designs/hermes-db-persistence-scope.md)。
- 分支：refactor/hermes-db-persistence-scope；隔离检出D:/AI/hermes-db-packages；基准90a2987e8c。
- 整体状态：NEEDS_USER_DECISION；当前阶段：完成职责/消费者核对，等待旧修复功能处置选择；完成1/7。
- 当前任务：无；Task2等待A整体退役或B外置工具的产品选择，不把等待计作功能完成。
- 日期：2026-11-10。原18项分包与正式重启已完成，本计划是新增职责精简，不改写旧记录。

## 全局约束

统一storage.backend、正常业务合同、Profile隔离、事务/锁/回执/unknown恢复不变。维护能力退役不能变成迁移服务或兼容flag。0031/31revision/29表模块与历史SQL/算法保持。仅独立checkout编辑；先绑定隔离HOME/RUNTIME再PM或应用导入；依赖仅PM，测试仅scripts/run_tests.sh。正式Profile/秘密/数据不变，PG仅归属随机Schema，禁止输出秘密和原始失败堆栈。不自动合并、推送、部署或重启正式服务；逐Task核对、记录证据并本地提交的策略沿用。

## Task 1：冻结定位与真实消费者台账

状态：completed

### 目标

把维护能力与持久层业务能力按真实消费者分开，确定精简边界。

### 涉及文件

本设计/计划；只读核对factory/contracts、transfer/session_store、profile_move/repair/purge/adoption及CLI/TUI消费者。

### 实施步骤

核对正式/隔离HEAD和工作区；逐符号追踪调用方；识别共享生命周期与历史自动补偿；列出A/B处置决策。

### 验证方式

Git status/log与rg直接/动态符号搜索、实际函数体阅读；不导入应用或运行正式修复命令。

### 完成条件

真实调用链及共享依赖进入设计，正式运行源码未变，没有用“仍有调用”代替职责判断。

### 执行结果

完成设计台账，识别15项维护接口、Profile删除对repair.delete_routes的实际依赖，以及TUI adoption是旧错路由补偿。新普通分支从正式90a2987e8c建立；两checkout起始clean。未编辑运行时代码。

### 验证证据

2026-11-10，Git status/log与rg export_session_for_move/import_moved_session/delete_moved_session、adopt_session_lineage_from、profile_purge/purge_profile_state，逐函数核对CLI repair-profiles与TUI _resume_adopt_stranded，及31revision的0031 repair调用；仅源码阅读，无业务测试通过声明。详细处置表见设计。文档结构检查7项/1completed/6pending及4个本地链接通过，暂存区空白检查exit0；本Task只提交职责核对与设计/计划，不包含运行时代码。

## Task 2：落实历史修复CLI退役或外置边界

状态：pending

### 目标

依据用户A/B选择完整处置入口，避免持久层接口移除后留下悬空消费者。

### 涉及文件

hermes_cli/subcommands/sessions.py、sessions_cmd.py、sessions_cmd_repair_profiles.py、sessions_repair_profiles.py；hermes_state_profile_repair.py及SessionDB实际组合点；CLI文档与对应测试。

### 实施步骤

A删除整个历史repair-profiles入口与专用实现；B将其置于独立显式工具，DB不暴露维护合同。逐项记录兼容退出行为，禁止只让PG AttributeError、添加万能SQL代理或仅隐藏help。

### 验证方式

按所选语义以标准runner运行相关CLI parser/正常sessions与Profile合同；既有维护测试删除或迁到外置工具范围，不能把测试搬走当成业务回归通过。

### 完成条件

A/B入口处置自洽，普通业务和SQLite独立启动仍可用，无悬空动态调用。

### 执行结果

待用户功能处置选择。

### 验证证据

未执行。

## Task 3：去除自动承接历史错归属数据

状态：pending

### 目标

普通resume不再执行历史跨Profile复制/退休补偿。

### 涉及文件

tui_gateway/methods_session.py、hermes_state_portability.py、hermes_db/integration/postgres/operations/adoption.py、transfer/move_values.py、queries/profile_move.py及store委托；对应TUI/DB合同。

### 实施步骤

追踪_resume_adopt_stranded的入口；删除自动修复分支，保留真实lazy/minted/正常存在与scope拒绝分支。A移除无消费者实现；B仅在显式外置工具可达，正常持久层不反向导入工具。

### 验证方式

scripts/run_tests.sh选择TUI session resume及DB会话/隔离合同；验证错scope/缺失会话不读取另一store、正常恢复和新PID重开继续有效。

### 完成条件

不存在普通resume触发的跨数据集修复；未误删正常业务恢复。

### 执行结果

未执行。

### 验证证据

未执行。

## Task 4：缩减DB维护方法并解开共享生命周期耦合

状态：pending

### 目标

从store/SessionTransfer移除维护方法和专用PG模块，正常Profile生命周期保留。

### 涉及文件

设计所列15项方法、operations/queries/profile_move与profile_repair、profile_purge、session_composition及Shared DTO/error定义。

### 实施步骤

依赖Task2/3，逐项核对所有剩余消费者；把purge实际使用的delete_routes放回正常路由所有者，保留同Connection/scope/回执语义；移除专用模块/无用注入/导入，收敛剩余SessionTransfer；不留内部shim。

### 验证方式

scripts/run_tests.sh运行Profile删除/身份/文件归属、正常Session/Runtime/网关路由合同及对应真实PG组；核对61锚点、DTO/error身份及动态引用。

### 完成条件

DB维护合同实际减少，正常Profile删除、读写及scope/事务仍一致，无私有门面反向依赖。

### 执行结果

未执行。

### 验证证据

未执行。

## Task 5：同步消费者、文档与边界合同

状态：pending

### 目标

让配置/文档/SDK与真实后端选择语义一致，明确独立数据集与不自动搬移。

### 涉及文件

实际受影响的CLI/TUI文档、skills/AGENTS、hermes_db边界台账与合同测试；不改历史基准证据。

### 实施步骤

全仓查找已删除接口、动态表和patch读取点；同步活动说明；保留真实业务导入导出/生命周期，分清Schema版本管理；不为未来第三后端新增无消费者扩展点。

### 验证方式

标准runner运行配置/工厂选择、真实消费者及边界lint合同；PM解释器scripts/check --staged --base 90a2987e8c、boundary_lint.py --check、必要生成契约检查和git diff --check。

### 完成条件

活跃文档和代码一致，无新边界豁免、无SQL/Schema演进或新配置key。

### 执行结果

未执行。

### 验证证据

未执行。

## Task 6：当前源码的双后端实际验收

状态：pending

### 目标

证明精简后顶层选择各后端仍可实际持久化，且不承担数据迁移。

### 涉及文件

当前DB合同/PG/发行/配置组及需要的真正业务测试，不改正式Profile。

### 实施步骤

冻结当前源码；PM建立无PG依赖SQLite与具实际SDK的PG独立载荷；标准runner全DB Native与PG，CLI/TUI受影响组单独运行。PG仅归属随机Schema，完整业务进程拒绝所有SQLite连接；覆盖多scope与新PID恢复，检查切换后端不自动搬入另一数据集；矩阵按真实SDK协议执行。

### 验证方式

scripts/run_tests.sh tests/hermes_db -j 4 --file-timeout 1200 -- --tb=short与独立CLI/TUI命令；真实PG目录加-m integration与私有配置路径；发行组绑定新的source/driver和PM解释器。实际参数在启动前展开记录，禁止复用前一轮720等结果为新证据。

### 完成条件

完整命令exit0，所有skip/环境差异具名，源/载荷一致；61锚点/0031不变，普通启动无DDL/搬移。

### 执行结果

未执行。

### 验证证据

未执行。

## Task 7：最终验证、独立审查与交付

状态：pending

### 目标

以新的精简边界判定本轮可交付性，不外推旧分包或全系统验收。

### 涉及文件

本设计/计划与本轮审查记录及实际整改文件。

### 实施步骤

执行verification-before-completion，对完整diff做独立code-review；整改后跑受影响验证，关闭blocking/major，给出READY_TO_MERGE/BLOCKED/FAILED；只按明确授权执行后续切换。

### 验证方式

读取实际完整输出、退出码/skip、源码hash/完整diff；无口头批准替代证据。

### 完成条件

功能处置、正常业务及后端选择合同均有当前证据，审查APPROVED；原Task24/七平台缺证独立保留。

### 执行结果

未执行。

### 验证证据

未执行。

## 最终验证与当前恢复点

本轮尚未改运行代码或运行测试。当前仅1/7职责核对完成，不能宣称精简已实现或READY_TO_MERGE。核心待决策为A整体退役旧修复功能或B外置工具；正式实例仍运行已发布的分包源码，开发恢复点为90a2987e8c及本设计/计划。后续逐Task记录实际命令、退出状态、通过/失败/skip和本地commit，不复用旧结果。

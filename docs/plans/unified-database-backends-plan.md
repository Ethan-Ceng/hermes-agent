# Hermes 统一数据库后端实施计划

## 关联设计与恢复位置

- 设计：[系统统一数据库后端](../designs/unified-database-backends.md)。
- 前置成果：[会话阶段计划](postgresql-session-storage-plan.md)，基准提交 `a875342384`。
- 分支：`feat/postgresql-session-storage`；沿用独立普通分支，不重建、不覆盖已有成果。
- 用户最新要求：SQLite/PGSQL是`hermes_db`的可选实现；选择PG后系统自有数据库不能仍依赖SQLite。按已有规划直接实施并逐项创建本地commit，不重新规划。

## 当前进度

- 整体状态：`VERIFYING`。
- 当前阶段：等待适用平台实机验收及验收major解除。
- 当前验证判定：`BLOCKED`；当前非平台必需范围及全分支检查通过，三分域未发现未处理的产品blocking/major。独立总体复核已完成、结论`CHANGES_REQUIRED`；非WSL七项缺证为仍未满足的验收major。
- 当前任务：Task24（in_progress）；最终代码`6c9e28665b1766c295023018a03e390dd264c230`，生产实现/四套发行载荷仍为`120bf8c9d6`，代码来源等价及五测试hash已冻结。历史恢复提交详见恢复记录。
- 已完成：23 / 24；会话阶段的17/18和原验证限制另行保留，不混入本计划计数。
- 阻塞：非WSL POSIX私有启动页七项仍缺适用主机，已准备冻结源码验收包和PM隔离脚本并询问现有入口/执行日志。PG完整689、双宿主DB、发行、Native分批及独立总体复核已结算；历史未定因风险保留，最后文档14检查已过，当前无其他不依赖该主机的必需项可推进，不绕过平台验收。
- 当前实际安装：2026-11-09用户明确授权默认和“股票大师”两个Profile都切换本机PG并重启。PM已安装postgresql extra，独立新Schema已显式升级，旧网关14412排空停止、新网关26656运行，两个Profile均PG就绪；旧SQLite保留，不导入。本机试运行记录见下文，不解除Task24的平台验收阻塞。
- 更新时间：2026-11-09（Asia/Shanghai）。

## 目标、约束与范围变化

1. 用统一的`storage.backend`/`storage.postgresql`选择整个Profile的自有数据库；旧`storage.session`开发配置已显式拒绝，不静默回落。
2. 复用SQLAlchemy Core、同步psycopg、Alembic、共享Schema和稳定store_id。SQLite模式无需PG extra；PG模式不创建/打开应用自有SQLite。
3. 不迁移旧SQLite数据、不双写、不回迁；不新增账号/K8s，不安装管理PG服务。
4. 配置、Markdown、工作区、附件blob和既有JSON文件格式不因本计划迁入数据库。附件元数据等数据库数据属于本计划。
5. 全部SQL/约束/计数/锁/幂等都遵守store_id及Board/插件/房间域内scope；线程、后台任务和Worker保留原拥有者边界。
6. 所有新PG表只由显式升级创建；不改0001–0004，不在应用启动或插件启用时偷偷DDL。
7. 不提供通用SQLite SQL翻译壳，不用关闭功能/内存替代/容错回落通过验收；PG错误必须明确传播。
8. 测试一律 `scripts/run_tests.sh`，依赖由项目PM管理；PG秘密只经私有文件路径，测试只操作验证归属的随机Schema。
9. 用户授权每个完成task创建本地commit；每个task立即写实际修改、验证、状态和恢复点，不推送、发布或合并。
10. 保留会话阶段原始失败/平台/波动证据；不能把835后端测试或285实库测试外推成新领域已经支持PG。
11. 新行为放主题模块，原生SQL消费者逐项收口；不扩张超长facade，不用SQL兼容壳或与实现镜像的测试替代业务合同。

## 阶段和依赖

| 阶段 | 任务 | 可验收结果 |
| --- | --- | --- |
| 统一基础 | 1–2 | 一个配置入口、领域资源、统一迁移与作用域 |
| 小型域及Cron | 3–7 | 证据、项目、执行/incident、投递、notepad |
| Kanban | 8–10 | 任务图、run/派发、订阅/工作区/转移 |
| 房间 | 11–14 | 元数据/事件、driver、策略/路由、附件元数据 |
| 指标和插件 | 15–19 | metrics、通用存储、Discord、RetainDB、Matrix E2EE |
| 闭合接入 | 20–22 | 运维/全入口、真实PG禁止自有SQLite的端到端证明 |
| 发行和最终门禁 | 23–24 | 独立安装、原生重启、完整验证和独立审查 |

依赖为执行约束，编号为推荐顺序；不因为基础资源已就位而把尚未端口化的域标为完成。

## 验证命令约定

所有任务下的命令均经标准runner；新测试文件由对应任务创建。PowerShell准备：

```powershell
$testRunner = 'D:/Programs/Git/bin/bash.exe'
$pgTestConfig = Join-Path $PWD '.build/postgresql/private/acceptance-postgresql.yaml'
# HERMES_PYTHON 由PM构建的对应测试解释器提供；不使用裸pytest/pip/uv。
```

任务中的 `scripts/run_tests.sh ...` 在PowerShell以 `& $testRunner scripts/run_tests.sh ...` 执行。PG参数仅传给加载 `tests/hermes_db` conftest 的文件；其他目录分开运行，避免将usage error误当测试结果。

## 状态变更记录

| 日期 | 状态 | 记录 |
| --- | --- | --- |
| 2026-11-07 | PLAN_READY | 用户澄清统一选择语义；已完成新增数据库所有者/消费者核对及24任务计划，未改业务代码 |

## 规划自检

- 已运行PM解释器下的`.build/postgresql/validate_unified_plan.py`，exit0：24项均pending、依赖均指向前置任务且无环、8类必需章节齐全、已有源码入口有效、本地Markdown链接存在、目标YAML可解析且池上限不超过预算。
- `git diff --check`通过。本轮只修改设计/计划及当前范围说明；没有执行新领域业务测试、DDL、配置切换或服务操作。
- 标准`PM Python scripts/check --staged --base a8753423841362c6c8d76e2dca094c95d690ba27`退出0、14项通过，health报告无业务代码变更；日志`.build/postgresql/unified-plan-checks.log`。新文件末尾空行已整改，最终暂存区`git diff --cached --check`退出0。
- 该自检只证明规划结构与引用有效，不是代码审查或业务验收；正式任务证据逐项填写。

## Task 1：统一 Profile 数据库配置与后端选择

状态：completed

### 目标

用一个 storage.backend 选择 Profile 全部自有数据库；取消仅会话选择造成的混合运行语义。

### 涉及文件

- `hermes_cli/db_setup.py`
- `hermes_db/settings.py`
- `hermes_cli/config_defaults.py`
- `hermes_cli/config_defaults_storage.py`
- `hermes_cli/config.py`（核对已有storage根键登记及配置校验）
- `tests/hermes_cli/test_db_setup.py`
- `tests/hermes_db/contracts/test_unified_selection.py`

### 依赖与接口

- 前置：无；以本设计和a875342384会话成果为输入。
- 输出：全域只有一个配置选择入口；未实现组件不能伪报已支持 PG，当前正式 Profile 配置保持不动。

### 实施步骤

1. 将配置提升为 storage.backend / storage.postgresql；秘密仍走 Profile secret scope，默认仍是 sqlite。
2. 更新配置注册/默认值/错误文本和所有已实现会话入口；旧 storage.session 嵌套配置明确报错，不忽略或静默回落。
3. 验证同一 Profile 的领域选择一致、跨 Profile/线程不串配置，SQLite 缺 PG extra 仍可导入。

### 验证方式

- `scripts/run_tests.sh tests/hermes_cli/test_db_setup.py tests/hermes_db/contracts/test_unified_selection.py`
- 覆盖缺 DSN、无效后端、冲突/旧配置、Profile 绑定和 SQLite 独立安装。

### 完成条件

全域只有一个配置选择入口；未实现组件不能伪报已支持 PG，当前正式 Profile 配置保持不动。

### 执行结果

统一 storage.backend/storage.postgresql 解析、默认值、作用域错误文本和克隆身份写入；旧 storage.session（含空配置及新旧冲突）明确拒绝。内部选择器改名为 storage_backend，全部生产调用者与既有配置测试同步，无兼容 shim；更新 .env.example 和用户配置示例。正式 Profile、服务及数据未改。提交标题：feat(storage): unify profile database backend selection。恢复点：Task 2；新领域尚未接通，不宣称系统 PG 可用。

### 验证证据

原生 Windows，现有 PM full-test-env（Python 3.14.9）。`scripts/run_tests.sh tests/hermes_cli/test_db_setup.py tests/hermes_db/contracts/test_unified_selection.py -j 2` exit0，15 passed/0 failed，无 skip；日志 `.build/postgresql/unified-task1-selection.log`。新合同在修改前 exit1、5 failed（新顶层配置读为 SQLite、旧配置未拒绝；含尚无新选择器的用例），日志 unified-task1-red.log。独立子进程阻止三个 PG 依赖导入并实际 SQLite 写入/关闭/重开成功；双线程两 Profile 配置及秘密隔离通过。`PM Python scripts/check --staged --base d9984f73af` 最终 exit0、14 checks ok（unified-task1-checks-final.log），初次 ruff 缺显式 check 参数已修正。git diff --check 通过。扩展回归 `scripts/run_tests.sh tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_db_commands.py tests/hermes_cli/test_profile_storage_identity.py tests/hermes_cli/test_backup_storage.py tests/hermes_db/contracts -j 4` 最终 exit0，81文件505 passed/0 failed，无 skip/重试波动（unified-task1-contracts.log）；本任务未运行实库及新领域验收，后续任务负责。

## Task 2：建立领域存储资源与统一 PG Schema 演进

状态：completed

### 目标

让新领域复用现有 scope、池、短事务、错误分类和显式升级机制。

### 涉及文件

- `hermes_db/domains/`
- `hermes_db/factory.py`
- `hermes_db/engine.py`
- `hermes_db/tables/__init__.py`
- `hermes_db/schema.py`
- `hermes_db/migrations/versions/`
- `tests/hermes_db/contracts/test_domain_resources.py`
- `tests/hermes_db/postgresql/test_domain_schema.py`

### 依赖与接口

- 前置：Task 1。
- 输出：新领域可在同一受管 PG 目标与作用域上运行，未声明/未初始化模块明确失败。

### 实施步骤

1. 定义按需领域资源/Unit of Work，协议导入不依赖 PG 驱动；明确 close、fork、线程绑定与连接预算。
2. 使用现有 scoped_table/scoped_fk 和 Schema 翻译机制；增加模块支持/版本清单，不改已执行的0001–0004。
3. 扩展显式 upgrade/status，逐域报告支持与 Schema 状态；普通启动不 DDL，不按 Board/插件另建池。
4. 领域资源显式接收Profile/scope，SQLite路径覆盖不参与PG配置/身份推断；增加嵌套cron/Board路径不能让PG回落的合同。
5. 固定各域值编码/查询投影合同，复用会话阶段无损策略；覆盖Unicode/NUL、JSON类型、字节配额、时区、摘要不含派生列。

### 验证方式

- `scripts/run_tests.sh tests/hermes_db/contracts/test_domain_resources.py`
- `scripts/run_tests.sh tests/hermes_db/postgresql/test_domain_schema.py -- -m integration --postgres-test-config=$pgTestConfig`
- 实测空 Schema、重复升级、旧PG revision 前向升级、无权限和同Schema多store；检查连接关闭。

### 完成条件

新领域可在同一受管 PG 目标与作用域上运行，未声明/未初始化模块明确失败。

### 执行结果

新增 driver-free 领域目录、显式拥有者资源、按需短事务、关闭与跨PID拒绝；复用现有池/预算/Transactions及错误分类，Worker拒绝直接取owner资源。SQLite路径只在SQLite分支保存，不推断Profile。Schema/status报告各域支持、所需revision、缺表及full_system_ready；未实现和未初始化域明确拒绝，普通打开无DDL。load_metadata从已实现域清单加载。0001–0004保持原样；本任务无新业务表，新增revision随各域任务提供，不创建占位迁移。值保真、配额/投影/时区合同写入 domains/README.md 并以现有编码真实PG写读验证。提交标题：feat(storage): add scoped domain resources and schema capabilities。恢复点：Task 3。

### 验证证据

原生Windows/现有PM解释器：`scripts/run_tests.sh tests/hermes_db/contracts/test_domain_resources.py tests/hermes_db/test_engine_lifecycle.py tests/hermes_cli/test_db_commands.py -j 3` exit0，24 passed、0 failed、1 skipped（原生POSIX fork合同不适用于Windows，待适用主机复验）；unified-task2-contracts-final.log。`scripts/run_tests.sh tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig` exit0，9 passed/0 failed/0 skipped；unified-task2-pg-final.log。使用已有私有配置和归属校验的随机Schema，实测空库/重复升级/0003前向升级、缺表拒绝、同Schema双store、Unicode/NUL/JSON类型、重开及连接归还。权限测试初次1 failed/3 passed：测试用户为superuser，REVOKE不能约束它；改为事务内SET LOCAL ROLE pg_monitor后真实拒绝读，不改账号或全局授权，复验通过。`PM Python scripts/check --staged --base 41f4258e91` exit0、14 checks ok；unified-task2-checks.log。未验证：原生POSIX fork执行及后续各业务域，不能据此宣称全系统PG完成。

## Task 3：统一 Agent 验证证据数据库

状态：completed

### 目标

验证证据事件和状态在 PG 模式持久化，不再创建 verification_evidence.db。

### 涉及文件

- `agent/verification_evidence.py`
- `hermes_db/tables/verification.py`
- `hermes_db/repositories/verification.py`
- `hermes_db/operations/verification.py`
- `tests/agent/test_verification_evidence.py`
- `tests/agent/test_verification_evidence_fd_leak.py`
- `tests/hermes_db/postgresql/test_verification_store.py`

### 依赖与接口

- 前置：Task 2。
- 输出：两后端证据合同一致，PG 真实消费者流程不打开自有 SQLite。

### 实施步骤

1. 固定记录、查询、编辑水位、保留上限和被动证据语义；提取后端无关分类逻辑。
2. 实现 store/session/root 范围的 PG 查询、并发写入与清理，SQLite 接口行为保留。
3. 接入实际终端/停止提示消费者，保留只记录实际证明、不自行执行测试的行为。

### 验证方式

- `scripts/run_tests.sh tests/agent/test_verification_evidence.py tests/agent/test_verification_evidence_fd_leak.py`
- 对应 PG 文件实库验证并发状态、保留策略、重开和隔离。

### 完成条件

两后端证据合同一致，PG 真实消费者流程不打开自有 SQLite。

### 执行结果

新增0005_verification（冻结DDL）及scoped Core事件/状态/锁表，精确文本用BYTEA；状态引用包含store_id外键。复用现有分类器，记录/编辑/状态入口按统一配置分流；PG以短事务、每store行锁合并编辑、共享完整证明及保留清理，SQLite原生接口继续独立使用。进程内未归因记录增加Profile键。终端消费者明确返回unavailable、编辑消费者记录存储警告，停止读取错误传播；不伪造成功证据。核对fcbdf3c356历史意图并用失败合同发现SQLite单会话上限误删其他会话仍引用的完整证明，已补引用保护，与PG保留规则一致。提交标题：feat(storage): persist verification evidence on selected backend。恢复点：Task 4。

### 验证证据

现有PM解释器/原生Windows：修改前实际PG证据入口测试exit1、1 failed，禁止所有SQLite连接时捕获verification_evidence.db连接（unified-task3-red.log）。`scripts/run_tests.sh tests/agent/test_verification_evidence.py tests/agent/test_verification_evidence_fd_leak.py tests/agent/test_verification_evidence_retention.py -j 3` exit0，66 passed/0 failed，无skip（unified-task3-sqlite-final.log）；共享证明保留新合同修正前1 failed（unified-task3-retention-red.log）。`scripts/run_tests.sh tests/hermes_db/postgresql/test_verification_store.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0，12 passed/0 failed/0 skipped（unified-task3-pg-final.log）。独立子进程恢复新增后再运行test_verification_store.py相同PG参数，exit0、3 passed（unified-task3-process.log）：父/子均拒绝所有SQLite连接，子进程恢复证明并写回编辑，父进程读到stale。实测12并发编辑、NUL/Unicode、跨store、引用/上限/过期、终端/停止/编辑入口和缺表错误，无外部模型/网络请求。停止提示及领域合同另有18 passed、2项POSIX平台skip；一次附带marker_schema文件未选中integration，不计实库证据。`PM Python scripts/check --staged --base 4d9d0c0430` 最终exit0、14 checks ok（unified-task3-checks-final.log），diff --check通过。未验证：POSIX适用测试、全系统业务单后端流程和最终审查，留至后续门禁。

## Task 4：统一 Projects 与发现缓存数据库

状态：completed

### 目标

项目、目录、当前项目和仓库发现记录全部支持选定后端。

### 涉及文件

- `hermes_cli/projects_db.py`
- `hermes_db/tables/projects.py`
- `hermes_db/repositories/projects.py`
- `hermes_db/operations/projects.py`
- `tests/tui_gateway/test_projects_rpc.py`
- `tests/tui_gateway/test_project_tree.py`
- `tests/hermes_db/postgresql/test_projects_store.py`

### 依赖与接口

- 前置：Task 2。
- 输出：PG 项目操作无需 projects.db，实际项目入口通过。

### 实施步骤

1. 替换原生连接穿透为项目存储操作，保留 slug 唯一性、目录主次和归档语义。
2. 实现范围唯一约束、主目录并发更新及发现缓存清理。
3. 一并适配 CLI/TUI/Web/项目关联的生产消费者，不改工作区文件存放方式。

### 验证方式

- `scripts/run_tests.sh tests/tui_gateway/test_projects_rpc.py tests/tui_gateway/test_project_tree.py`
- PG 实测同slug跨store隔离、同store冲突、主目录竞争、归档和重启恢复。

### 完成条件

PG 项目操作无需 projects.db，实际项目入口通过。

### 执行结果

新增0006_projects冻结迁移、Core项目/目录/元数据/发现缓存及store锁表；精确文本用BYTEA，slug唯一键、外键均带store_id。19个已有具名项目操作统一分流到PG完整短事务，保留SQLite接口；PG资源不提供execute或SQL翻译。创建/slug分配/主目录/策略缓存变更以store行锁序列化。connect显式拥有者，db_path覆盖仅用于SQLite。CLI/TUI/Web/tools既有具名调用接通；发现缓存、库存和看板关联查询不再吞PG错误为空结果。修正两个已在基线复现的Windows工具测试路径fixture，无OS伪装。提交标题：feat(storage): support Projects on the unified backend。恢复点：Task 5。

### 验证证据

原生Windows/PM full-test-env。`scripts/run_tests.sh tests/hermes_cli/test_projects_db.py tests/hermes_cli/test_projects_cli.py tests/tui_gateway/test_projects_rpc.py tests/tui_gateway/test_project_tree.py tests/tools/test_project_tools.py tests/hermes_cli/test_kanban_project_link.py tests/hermes_cli/test_kanban_board_project.py tests/hermes_db/contracts/test_unified_selection.py -j 4` exit0、97 passed/0 failed/0 skipped（unified-task4-sqlite-final.log），含禁止PG依赖导入的SQLite项目写入/重开。初轮2项工具Unix路径断言失败；用44df595f2a原版projects_db模块跑同测试仍2 failed/8 passed（unified-task4-tools-base.log），改原生tmp_path后通过。`scripts/run_tests.sh tests/hermes_db/postgresql/test_projects_store.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、13 passed/0 failed/0 skipped（unified-task4-pg-final.log）。扩展CLI/Web/TUI创建流程后再跑test_projects_store.py相同PG参数，exit0、4 passed（unified-task4-surfaces-final.log）：整个业务进程及独立子进程拒绝所有SQLite连接，验证真实工具注册dispatch、CLI list、TUI list/create、Web工作区、重启读写、同ID跨store、同slug竞争、主目录竞争、归档删除/缓存和故障传播。TUI首轮因测试仅绑定秘密而缺Profile秘密文件失败，fixture改为隔离Profile的.env（从已有私有测试源读取、不输出/提交秘密）；宿主将CLI输出重定向stderr的断言已按实际协议修正。`PM Python scripts/check --staged --base 44df595f2a` 最终exit0、14 checks ok（unified-task4-checks-final.log），diff --check通过。未验证：metrics启用链路须Task15后单后端全流程再验；本次用默认授权策略，未禁用/替代指标以绕过测试，也不把项目证据外推到指标、完整Kanban或全系统。

## Task 5：统一 Cron 执行与 incident 账本

状态：completed

### 目标

执行状态和故障事件使用同一选定数据库并保持原恢复语义。

### 涉及文件

- `cron/executions.py`
- `cron/incidents.py`
- `cron/scheduler_*.py（实际调用者）`
- `hermes_db/tables/cron.py`
- `hermes_db/operations/cron_executions.py`
- `hermes_db/operations/cron_incidents.py`
- `tests/cron/test_execution_ledger.py`
- `tests/cron/test_cron_incidents.py`
- `tests/hermes_db/postgresql/test_cron_executions.py`

### 依赖与接口

- 前置：Task 2。
- 输出：执行与故障事件不依赖 cron/executions.db，既有恢复判据保留。

### 实施步骤

1. 端口化 claimed/running/终态、handoff、progress、occurrence 和 incident 操作，不用进程锁替代 PG 原子性。
2. 保留 owner 指纹、未知结果、终态不可变、incident 重开/关闭和通知的提交后顺序。
3. 跨 Profile 的 scheduler scope 在开库前绑定，后台线程/外部 worker 使用拥有者配置。

### 验证方式

- `scripts/run_tests.sh tests/cron/test_execution_ledger.py tests/cron/test_cron_incidents.py tests/cron/test_cron_incidents_resolve.py`
- PG 多连接执行采用/恢复/终态竞争、同job_id隔离及断连测试。

### 完成条件

执行与故障事件不依赖 cron/executions.db，既有恢复判据保留。

### 执行结果

新增0007_cron_executions冻结迁移及同域执行/incident/锁表，复用统一scope、池与Transactions。具名执行/incident入口分流，无SQL翻译；claimed/running/终态、handoff、progress、unknown/receipt恢复、occurrence及保留策略用scoped Core/CAS，事件/metrics回调在提交后。保留原UTC/本地offset文本，以不进入业务记录的毫秒投影排序。存活探测在读连接归还后执行，更新重核快照，避免扫描覆盖接管/进度。Cron occurrence消费者原来直接导入SQLite事务，已改具名completed_occurrence_rows，PG错误不被吞为未完成。SQLite私有连接在PG下明确拒绝，EXECUTIONS_FILE只作用于SQLite。实际scheduler Profile scope和外部worker拥有者经实库验证。提交标题：feat(storage): support Cron execution and incident ledgers。恢复点：Task 6。

### 验证证据

原生Windows/PM full-test-env。修改前新PG业务合同exit1、1 failed，捕获cron/executions.db连接（unified-task5-red.log）。指定执行/incident/resolve测试初轮43 passed；扩展命令 `scripts/run_tests.sh tests/cron/test_execution_ledger.py tests/cron/test_cron_incidents.py tests/cron/test_cron_incidents_resolve.py tests/cron/test_scheduled_occurrence.py tests/cron/test_stale_running_recovery.py tests/cron/test_live_firer_receipt_recovery.py tests/cron/test_idle_tick_config_skip.py tests/hermes_db/contracts/test_unified_selection.py -j 4` exit0、62 passed/0 failed/0 skipped（unified-task5-sqlite-final.log），含无PG依赖的SQLite Cron读写。`scripts/run_tests.sh tests/hermes_db/postgresql/test_cron_executions.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、14 passed/0 failed/0 skipped（unified-task5-pg-final.log）；新增调度scope/路径合同后test_cron_executions.py相同PG参数exit0、6 passed（unified-task5-scope.log）。业务父/子进程拒绝所有SQLite连接；实测双真实进程唯一采用、父进程晚到终态拒绝、真实退出owner恢复unknown与receipt结算、恢复探测期间并发采用CAS、跨store同job隔离、incident重开/ack及8并发去重、offset时间排序/游标、物理关闭PG连接报错后持久记录仍可读取、实际scheduler scope及嵌套路径不回落。`PM Python scripts/check --staged --base e7612bcf80` 最终exit0、14 checks ok（unified-task5-checks-reviewed.log）；初次ruff UTC别名问题已修正，diff --check通过。未验证：投递/notepad/指标启用等独立领域及完整scheduler→模型→投递流程，依赖后续任务；不外推当前证据。

## Task 6：统一 Cron 待投递队列

状态：completed

### 目标

外部 Cron worker 到网关的持久化投递不再依赖独立 SQLite。

### 涉及文件

- `cron/delivery_queue.py`
- `cron/scheduler_delivery*.py`
- `hermes_db/operations/cron_delivery.py`
- `tests/hermes_db/contracts/test_cron_delivery_store.py`
- `tests/hermes_db/postgresql/test_cron_delivery_store.py`

### 依赖与接口

- 前置：Task 5。
- 输出：PG Cron 投递完整流程不创建本地队列库，不扩大 exactly-once 承诺。

### 实施步骤

1. 实现原子 enqueue、claim、终态、等待超时和墓碑清理；沿用 execution identity。
2. 网关在事务外投递，崩溃后保留 unknown/不重复外部效果的原策略。
3. 适配实际 enqueue_and_wait/drain 与关闭路径，不能吞 PG 错误后返回空队列。

### 验证方式

- `scripts/run_tests.sh tests/hermes_db/contracts/test_cron_delivery_store.py`
- PG 实测双消费者 claim、提交确认丢失、投递中断、终态重试和重启恢复。

### 完成条件

PG Cron 投递完整流程不创建本地队列库，不扩大 exactly-once 承诺。

### 执行结果

新增0008_cron_delivery冻结迁移、scoped队列/终态墓碑/锁表；以完整短事务实现enqueue、claim、finish、unknown恢复、等待超时与payload清理。保留execution身份幂等：重放返回原请求或墓碑，不覆盖已持久化请求、不重发终态。read/claim/prune都包含store_id；进程活动发送标记增加Profile键，防止同execution_id跨Profile恢复串扰。发送/等待在事务外，继续复用旧drain及outcome回写流程。网关watch显式捕获拥有者，对PG使用原有1秒节奏poll drain，不依赖本地文件/WAL。原生SQLite连接在PG下明确拒绝，无SQL翻译/内存替代/重试扩张。提交标题：feat(storage): persist Cron delivery queues on selected backend。恢复点：Task 7。

### 验证证据

原生Windows/现有PM解释器。PG合同修改前exit1、1 failed，捕获deliveries.db连接（unified-task6-red.log）。`scripts/run_tests.sh tests/hermes_db/contracts/test_cron_delivery_store.py tests/cron/test_delivery_queue.py tests/cron/test_delivery_queue_retention_race.py tests/cron/test_queued_delivery_fencing.py tests/gateway/test_cron_delivery_housekeeping.py -j 4` exit0、22 passed/0 failed/0 skipped（unified-task6-sqlite.log）。SQLite禁止导入sqlalchemy/psycopg/alembic子进程补充真实enqueue/drain后，test_unified_selection.py exit0、5 passed（unified-task6-sqlite-independent.log）。`scripts/run_tests.sh tests/hermes_db/postgresql/test_cron_delivery_store.py tests/hermes_db/postgresql/test_schema.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig` exit0、9 passed/0 failed/0 skipped（unified-task6-pg-concurrency.log）；补跨Profile活动隔离后单文件相同PG参数exit0、5 passed（unified-task6-pg-final.log）。PG业务父/子进程拒绝所有SQLite连接，证明JSON类型/NUL/Unicode、持久化/重开、作用域隔离、双真实进程唯一claim、owner退出unknown且不重发、终态墓碑重放、pending超时仍排队、无本地文件watch及发送期间checkedout=0。提交确认丢失通过真实PG commit后在dialect do_commit注入OperationalError验证：UnknownCommitError明确抛出，数据库已保存delivered，外部fixture发送计数仍为1，重开drain不重复。该证据是客户侧确认丢失注入，不声称网络代理丢包实测。`PM Python scripts/check --staged --base 895e13cd6e` exit0、14 checks ok（unified-task6-checks-final.log）；最终追加子进程断言后检查仍exit0、14 checks ok（unified-task6-checks-commit.log），diff --check通过。未验证：notepad/指标启用、完整所有域端到端和最终门禁仍在后续任务。

## Task 7：统一 Cron notepad

状态：completed

### 目标

任务游标/水位等 notepad 数据跟随全局后端并守住并发配额。

### 涉及文件

- `cron/notepad.py`
- `cron/jobs.py（清理调用）`
- `hermes_db/operations/cron_notepad.py`
- `tests/cron/test_notepad.py`
- `tests/hermes_db/postgresql/test_cron_notepad.py`

### 依赖与接口

- 前置：Task 5。
- 输出：PG notepad 无 SQLite 依赖，超过配额原数据保持不变。

### 实施步骤

1. 实现 get/set/delete/list/clear，保留键上限、UTF-8字节上限和渲染行为。
2. 在 PG 对任务范围加锁后核算总配额，防止两个写入分别通过检查后超限。
3. 删除任务清理使用同一 Profile/store 的 notepad，不触碰其他 Profile 同名任务。

### 验证方式

- `scripts/run_tests.sh tests/cron/test_notepad.py`
- PG 实测 Unicode字节、双连接超额竞争、重开及同job_id隔离。

### 完成条件

PG notepad 无 SQLite 依赖，超过配额原数据保持不变。

### 执行结果

新增0009_cron_notepad及scoped per-job锁/笔记表，BYTEA保留Unicode/NUL，写入前按真实UTF-8字节核算单值/任务总配额，任务行锁保护并发写/delete/clear。get/set/list/delete/clear统一配置分流，PG不依赖notepad.db存在性。保留空notepad返回空字符串及既有CLI/提示行为；PG读取失败明确传播而非渲染为空。将已删除任务的best-effort清理收口notepad主题模块，正常删除只清理所属store/job，PG故障有明确warning且不假称清理成功；不回滚已持久化的任务文件删除。新增可复用真实Profile PG测试fixture，业务过程全拒绝SQLite。提交标题：feat(storage): support scoped Cron notepads on PostgreSQL。恢复点：Task 8。

### 验证证据

原生Windows/PM full-test-env。新PG合同修改前exit1、2 failed，均捕获notepad.db连接（unified-task7-red.log）。`scripts/run_tests.sh tests/cron/test_notepad.py tests/hermes_db/contracts/test_domain_resources.py tests/hermes_db/contracts/test_unified_selection.py -j 3` exit0、35 passed/0 failed、1 POSIX fork平台skip（unified-task7-sqlite-final.log）；26项既有notepad/CLI/提示/删除合同全过，另以禁止PG依赖导入的子进程实际读写SQLite notepad。`scripts/run_tests.sh tests/hermes_db/postgresql/test_cron_notepad.py tests/hermes_db/postgresql/test_schema.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig` exit0、8 passed/0 failed/0 skipped（unified-task7-pg-final.log）。PG父/子业务进程拒绝全部SQLite，实测Unicode/NUL、关闭/新进程恢复与写回、真实jobs.remove_job的跨store清理、双连接竞争总字节配额只有一写成功且失败后原值不变、缺表读取不渲染空内容、best-effort删除清理故障明确warning。`PM Python scripts/check --staged --base f519a4b6ac` exit0、14 checks ok（unified-task7-checks.log），diff --check通过。未验证：POSIX平台合同、全域PG单后端矩阵及最终审查仍待后续，不将当前证据外推到Kanban/rooms/metrics/plugins。

## Task 8：统一 Kanban Board、任务与依赖图

状态：completed

### 目标

任务与图操作从 SQLite Connection 改为领域事务并支持 PG。

### 涉及文件

- `hermes_cli/kanban_db.py`
- `hermes_cli/kanban_db_context.py`
- `hermes_cli/kanban_db_graph.py`
- `hermes_cli/kanban_db_connect.py`
- `hermes_db/tables/kanban.py`
- `hermes_db/operations/kanban_tasks.py`
- `tests/hermes_db/postgresql/test_kanban_tasks.py`

### 依赖与接口

- 前置：Task 2、Task 4。
- 输出：Kanban 基本任务与图在 PG 可独立读写，公共消费者不执行 SQLite SQL。

### 实施步骤

1. 固定 Board 身份和默认/命名 Board 作用域，复用稳定逻辑ID，不从绝对路径派生跨节点身份。
2. 适配任务CRUD、父子/依赖图、事件、元数据和项目关联；保留图约束及原错误。
3. 隔离 SQLite 初始化/损坏修复/WAL路径；PG显式迁移，不伪装原生连接。

### 验证方式

- Kanban 既有任务/图行为测试，经 scripts/run_tests.sh 执行。
- PG 实测同任务ID跨Board/store隔离、图约束、排序和并发状态修改。

### 完成条件

Kanban 基本任务与图在 PG 可独立读写，公共消费者不执行 SQLite SQL。

### 执行结果

新增 `0010_kanban_tasks` 及 Core Board 注册表、任务/依赖边/评论/事件表；所有键、FK、查询、锁和删除均带 `store_id + board_id`。Board slug 查找当前稳定代次，归档后重建分配新代次，旧资源写入被 Board 行锁和生命周期检查拒绝；不从本地路径推断 Profile/Board。命名 Board 必须显式创建，默认 Board 只做幂等业务 DML，不在连接时运行 DDL。

`BoardResource` 使用捕获的拥有者作用域和短事务，无 `.execute`/SQLite SQL 翻译接口。任务创建、幂等、字段修改/分配、Projects 关联、技能/goal/model/reasoning字段、任务删除、依赖图/环检测、ready 重算、triage 规格化/原子分解、评论/事件/统计/保留期均有命名 Core 操作；基础 CLI 创建/列表/编辑/统计直接使用这些接口。分解的后续 child 约束失败会回滚此前 child/边/事件；并发创建键和反向图边由真实 PG Board 锁串行化。Worker context 的 parent 查询改用命名图接口，run history 归 Task 9。

`board.json` 保留文件配置，不存入 PG；PG 只登记身份与生命周期。PG 文件根绑定拥有者 Profile，SQLite 原共享路径与路径覆盖继续保留。身份事务提交后写配置文件；文件错误明确上报，重试创建复用已提交活动代次。已将这项事务边界、Board 代次、跨 Profile Worker 必须继承可信 owner 的要求补入设计。`kanban_tasks`、`kanban_runs`、`kanban_workspace` 分别报告能力；后两者仍不支持，不伪报整个 Kanban 就绪。

原 `SCHEMA_SQL` 原样移到 `kanban_sqlite_schema.py`，修正内部引用而不加 re-export shim，facade 净缩减。SQLite 初始化、WAL/损坏修复和 PG 获取路径在最早的连接边界分离。原生基线四个失败（systemd 主机标记、Git/可执行路径断言、FakePopen 跨用例泄漏）已在 Task 7 原始源码复现；仅修测试主机边界和假进程注册表隔离。扩大回归另发现同类 FakeProc 泄漏，也只修测试隔离。

### 验证证据

Windows 原生；PM 测试解释器沿用 `.build/postgresql/full-test-env/Scripts/python.exe`，秘密只通过私有测试配置路径读取。PG fixture 在核对归属的随机 Schema 显式升级；父/子业务进程拒绝所有 `sqlite3.connect`，包括内存/URI，不给业务路径豁免。

- 初始 `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_tasks.py -- -m integration --postgres-test-config=$pgTestConfig`：2 failed，按预期在旧 SQLite 连接处拒绝。后续测试修正了实际 connect_closing 所在模块、CLI positional title 与输出词、故障注入前提；不把测试编写错误当作产品缺陷。
- 原始 Task 7 源码的 `scripts/run_tests.sh tests/hermes_cli/test_kanban_db.py -j 2`：50 passed、4 failed、1平台skip，日志 `unified-task8-native-baseline.log`。之前动态导入基线插件的两次尝试为 harness 54 setup errors，不是产品证据；已删除临时插件并换成原源码覆盖、finally 精确恢复当前文件。
- 最终 `scripts/run_tests.sh tests/hermes_cli/test_kanban_db.py tests/hermes_cli/test_kanban_db_init.py tests/hermes_cli/test_kanban_decompose_db.py tests/hermes_cli/test_kanban_graph_identity.py tests/hermes_cli/test_kanban_project_link.py tests/hermes_cli/test_kanban_boards.py tests/hermes_cli/test_kanban_board_project.py tests/hermes_cli/test_kanban_creator_origin.py tests/hermes_cli/test_kanban_specify_db.py tests/hermes_cli/test_kanban_gc_retention.py tests/hermes_cli/test_kanban_core_functionality.py tests/hermes_cli/test_kanban_cli.py tests/hermes_db/contracts/test_unified_selection.py tests/hermes_db/contracts/test_domain_resources.py -j 3`：退出0，153 passed、5适用平台skip（Linux/systemd、POSIX）。日志 `unified-task8-regression-final.log`。之前扩展回归为151 passed、2 failed、5 skip，同类 FakeProc 泄漏修正后完整复验。包含真实 SQLite 业务子进程拒绝 SQLAlchemy/psycopg/Alembic 导入。
- 最终 `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_tasks.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_cron_notepad.py tests/hermes_db/postgresql/test_cron_delivery_store.py tests/hermes_db/postgresql/test_cron_executions.py tests/hermes_db/postgresql/test_projects_store.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，32 passed，其中当前 Kanban 9项、Schema 5项；日志 `unified-task8-pg-final-all.log`。曾以两个不存在的文件名调用 runner，退出2且未执行测试；上述已改为真实路径。
- Kanban 实证包含：NUL/Unicode 精确保真、相同任务ID跨Board/store隔离、旧Board资源与同名重建隔离、并发幂等与互斥图边、原子分解约束回滚、Projects继承/显式scratch覆盖、真实 CLI、池归还、调用上下文变更仍绑定拥有者、SQL失败不回落、真实子进程关闭/重开后读写持久数据、文件配置写入失败后的代次恢复。
- `PM Python scripts/check --staged --base 38a120b287` 最新退出0，14项通过，0 blocking/advisory；日志 `unified-task8-checks-final.log`。首次检查只报测试文件行数增长，清理两处多余空行后通过。`git diff --cached --check` 通过。本地提交标题 `feat(storage): support scoped Kanban tasks and graphs`，父提交 `38a120b287`；提交后可用该唯一标题定位SHA。

未验证/恢复点：Task 9 的 run/claim/派发/Worker/owner恢复/旧回执和完成态 result 编辑仍未实现；Task 10 的订阅继承、工作区/附件生命周期、Board 文件目录归档/删除、跨 Board 转移仍待闭合。当前仅验收基础任务/图，不宣称完整 Kanban/全系统 PG；Task 11–24 与最终审查仍 pending。Task 8 本地提交后立即进入 Task 9。

## Task 9：统一 Kanban run、派发与 Worker 回执

状态：completed

### 目标

派发认领、运行身份、租约与终态在 PG 多进程下保持准确。

### 涉及文件

- `hermes_cli/kanban_db_dispatch.py`
- `hermes_cli/kanban.py`
- `hermes_cli/kanban_owner_recovery.py`
- `hermes_cli/kanban_swarm.py`
- `hermes_cli/kanban_db_workspace.py`、终态所需附件元数据/文件保护接口（从Task 10前移的基础依赖）
- `agent/kanban_turn_recovery.py`
- `gateway/session_kanban.py`
- `hermes_db/operations/kanban_runs.py`
- `tests/hermes_db/postgresql/test_kanban_runs.py`

### 依赖与接口

- 前置：Task 8、Task 5。
- 输出：同一任务不被重复派发，旧代次不提交，PG运行无SQLite协调锁。

### 实施步骤

1. 端口化资格判断、claim、run ID、心跳、owner恢复、取消、完成及代次护栏。
2. 明确 Board/任务/run 锁顺序，用受影响行/CAS判定结果，保留未知提交和旧回执拒绝。
3. 接入真实dispatcher/worker/cron调用链，Worker不直接打开owner会话库。
4. 端口化终态/派发直接调用的底层附件元数据与 workspace 字段/引用/清理接口；附件内容仍为文件，不跳过保存/共享引用判断。订阅、跨Board转移及剩余消费者仍在Task 10闭合。

### 验证方式

- 既有派发/Worker/恢复测试，经标准 runner 运行。
- PG 双进程认领、晚到回执、租约过期、owner重启与失败结算测试。

### 完成条件

同一任务不被重复派发，旧代次不提交，PG运行无SQLite协调锁。

### 执行结果

已完成。前置 Task 8 本地提交 `94efe69e4e`。新增 `0011_kanban_runs` 至 `0015_kanban_workspaces` 显式迁移，端口化run/claim/心跳/恢复/派发/终态/审阅、精确进程代次和失败预算。复用原生调度/策略与文件准备，PG使用Board锁及store内持久租约，不占连接等待文件或进程。真实采用Worker使用可信Board owner ref、闭合RPC和独立outbox命令回执，effect+receipt同Board事务。Swarm拓扑/黑板/root激活同事务，CLI diagnostics读取命名快照。必要的附件元数据、工作区引用与cleanup token已接入；SQLite原生路径继续可用。`kanban_runs`能力现已登记；完整workspace/订阅/转移及普通daemon全系统能力仍待后续任务。提交标题：feat(storage): persist Kanban runs dispatch and worker receipts。

以下保留子阶段实施与失败修正记录。初始run实现新增Core run表与Board/store/task复合FK，当前任务指针和事件run引用都不能跨任务或作用域。已有run读取API抽入 `kanban_db_runs.py` 主题模块，facade保持公共补丁入口并净缩减；claim用Board行锁+受影响行CAS；手动reclaim在释放读连接后做进程探测，并以run/lock/PID/指纹快照重查。

初始调用链核对发现：`gateway/session_kanban.py`、`kanban_worker_client.py`、`kanban_owner_recovery.py` 等持有SQLite path/Connection；assigned Profile的会话owner与Board owner可能不同，不能让assignee的store_id覆盖Board身份。随后沿可信派发与已采用Worker frame/RPC传递/核对Board owner ref，保持Worker不直接获得owner store，factory的owner-only防线未放宽。

实施前依赖调整已记录至设计：实际 `complete_task` / `request_review` 事务内登记附件、`_spawn_candidate` 写 workspace/branch、提交后清理查父子/跨Board引用，原Task 9→10顺序缺少这些终态前置。将必要底层附件元数据与workspace适配前移到Task 9；Task 10仍负责订阅、跨Board原子转移、Board目录生命周期及剩余消费者。无功能削减、不改变24项总数；相关实测必须在Task 9完成前提供。

### 验证证据

- 初始 `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_runs.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig`：2 failed，明确在 Task 8 保留的未实现 PG 原生事务保护处失败，日志 `unified-task9-red.log`。
- 首轮 `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_runs.py tests/hermes_db/postgresql/test_schema.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，7 passed（2 run/5 Schema），包含真实双子进程同时起跑，只有一个 claim 成功且退出后可读取持久 run；日志 `unified-task9-claims.log`。
- 新增 reclaim 代次测试后 `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_runs.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，3 passed，日志 `unified-task9-reclaim.log`。各 fixture 仍使用核对归属的随机 Schema，父/子拒绝全部 SQLite，未访问正式 Profile/数据或管理 PG 服务。
- 继续复用/抽出 `kanban_block_policy.py` 的纯状态策略，已接入 PG block/unblock 与 run 结束。对应实库同命令：退出0，4 passed，日志 `unified-task9-blocks.log`，覆盖依赖等待、粘性阻塞、unblock 继承计数与循环进入 triage；并非整个终态/完成/审阅都已实现。
- `scripts/run_tests.sh tests/hermes_cli/test_kanban_db.py -j 2`：退出0，53 passed、2原生主机平台skip，日志 `unified-task9-native-runs.log`；`scripts/run_tests.sh tests/hermes_cli/test_kanban_block_kinds.py tests/hermes_cli/test_kanban_blocked_sticky.py tests/hermes_cli/test_kanban_resume_guard.py -j 3`：退出0，21 passed，日志 `unified-task9-native-blocks.log`。run schema 新 FK 后 Task 8 实库基础任务合同复验：退出0，9 passed，日志 `unified-task9-task8-regression.log`。
- 当前部分实现 `PM Python scripts/check --staged --base 94efe69e4e`：退出0，14项通过、0 blocking/advisory，日志 `unified-task9-checks-partial.log`。这不是Task 9最终门禁，后续变更继续复验。
- 底层附件前置：新增 `0012_kanban_artifacts`，附件行/跨Board路径护栏保存在PG，内容保留文件；新上传使用唯一文件代次，已知回滚删除未登记文件，UnknownCommit保留文件。最后一个引用的删除先提交cleanup token，文件删除在连接归还后执行，新引用遇到待清理token显式失败；跨Board共享引用保留内容。进程在cleanup中途丢失的token需由Task 20维护/对账闭合，当前未宣称完整生命周期恢复。
- `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_artifacts.py tests/hermes_db/postgresql/test_schema.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，7 passed（2附件/5Schema），初始对应2项按预期NotReady失败。增加真实COMMIT后客户端确认丢失与跨Board并发引用测试后单文件4 passed；日志 `unified-task9-artifacts-faults.log`。确认丢失为真实服务器COMMIT之后在客户端注入异常，未声称做过网络代理丢包。
- workspace字段与引用读取已改为命名Core接口，共用文件编排通过持有资源绑定owner Profile，原生/PG不再在这些编排中直接读取tasks原生SQL。`scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_workspaces.py tests/hermes_db/postgresql/test_kanban_artifacts.py tests/hermes_db/postgresql/test_kanban_runs.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，10 passed；日志 `unified-task9-workspace-base.log`。workspace当前证明现存共享引用保护与字段/拥有者绑定；并发新增workspace引用与清理的最终协调护栏尚待闭合，不能把这2项adapter合同外推为完整workspace生命周期验收。
- 完成态已开始：`test_kanban_completion.py` 最初3项在原生SQL未适配处失败；接入 Core 完成/证据/PR接受快照和事务外文件准备后，3项通过，扩展客户端COMMIT确认丢失与PR接受身份/连接断言后5项通过（`unified-task9-completion-faults.log`）。PR收据使用既有 `collect_acceptance` seam 测试，未声称真实GitHub网络验收。完成后副本/附件行持久化、旧run回执拒绝、失败时保持running和继任者不受影响均实测；审阅/dispatcher/owner链及workspace并发清理护栏仍未完成。
- 复用文件helper时定位出既有回滚补偿缺陷：`_persist_scratch_completion_artifacts` 用附件目录前缀而非本次创建集合生成补偿列表，导致 review 回滚删除已有附件。`git log -p -S 'staged_copies = _stage_completion_artifacts'` 核对 `ba65ce668ab9` 原意为只清理本次副本；在 `94efe69e4e` 原始 facade/workspace 源码覆盖并finally恢复的基线上，新增行为合同确实1 failed（`unified-task9-file-ownership-base.log`）。已改为有序的实际创建集合；调用者传入内部暂存marker的第二场景也先复现1 failed/1 passed（`unified-task9-file-marker-red.log`），随后清除输入marker再生成补偿权限。两种后端共享该helper，修正整个类而非只补PG。
- 原生workspace扩展回归最初73 passed、1 failed、2平台skip，其中 teardown 用例在测试准备阶段 `scratch.rmdir()` 即触发 Windows“当前目录被占用”，未运行产品清理。该“已删除 cwd”前提仅POSIX可构造，已用 `platforms("posix")` 标记，无OS伪装。修正后 staging/teardown 两文件19 passed、1平台skip（尚未加入第二marker场景时，`unified-task9-file-ownership-green.log`）；最新两场景复验继续记录。
- 两种暂存所有权场景及无PG导入SQLite合同最新共7 passed（`unified-task9-file-marker-green.log`）。完成态 result/summary/任意JSON回填已接入，先复现显式NotReady，再单文件6 passed（`unified-task9-result-edit.log`），更新原completed run而不生成重复handoff。
- 审阅原生SQL与Worker上下文role查询原先3 failed；接入Core request_review/request_changes/reopen与recent_profile_completions后3 passed，扩展真实COMMIT阶段延迟FK回滚后4 passed（`unified-task9-review-faults.log`）。Body失败/COMMIT明确回滚只补偿新副本，UnknownCommit保留内容；实现者/审阅者在changes→重做→再审阅中保持原来源。
- 本轮原生7文件命令（`test_kanban_db.py`、`test_kanban_review_lifecycle.py`、`test_kanban_review_lifecycle_complete.py`、`test_kanban_empty_completion.py`、`test_kanban_task_updated_hook.py`、`test_kanban_complete_live_claim_guard.py`、`test_kanban_artifact_staging_ownership.py`，均在`tests/hermes_cli/`，`scripts/run_tests.sh ... -j 3`）：退出0，116 passed、2平台skip，日志 `unified-task9-native-terminal.log`。
- 本轮实库7文件命令（`test_kanban_tasks.py`、`test_kanban_runs.py`、`test_kanban_artifacts.py`、`test_kanban_workspaces.py`、`test_kanban_completion.py`、`test_kanban_review.py`、`test_schema.py`，均在`tests/hermes_db/postgresql/`，`scripts/run_tests.sh ... -j 3 -- -m integration --postgres-test-config=$pgTestConfig`）：退出0，34 passed，日志 `unified-task9-domain-partial.log`。不包含尚未适配的dispatcher/owner链。
- 人工promotion与reassign合同先2 failed，其中实际SQL错误被旧 `except RuntimeError` 吞成False，违背该函数只处理“仍在running”的原意。新增窄 `TaskAlreadyClaimedError(RuntimeError)` 用于分配业务拒绝，两种后端一致；PG promotion与reassign接入后2 passed（`unified-task9-routing.log`），存储故障明确传播。
- 完成态基础阶段静态复验 `PM Python scripts/check --staged --base 94efe69e4e`：退出0，14项通过（`unified-task9-checks-terminal-partial.log`）；该次尚未含最后review/result/promotion变更，Task 9最终静态门禁仍待继续执行。
- 失败结算从过长dispatch主题抽入 `kanban_db_failure.py`，公开补丁入口统一为facade的 `_record_task_failure`，agent finalizer和原测试同步改用此入口，无旧内部路径shim。共享failure预算策略；PG在同一短事务处理run/claim/预算，旧run不能计入继任者，基础设施拒绝不计失败。`scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_failures.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig`：退出0，2 passed（先按预期失败，`unified-task9-failures.log`）。原生4文件（db/review_lifecycle_complete/worker_exit_trailer/agent iteration_limit_exit）94 passed、2平台skip（`unified-task9-native-failures.log`）；`test_run_agent.py -k 'kanban_block or no_kanban_block'`仅选择改动的2项，2 passed（`unified-task9-agent-seam.log`），不外推为完整agent回归。
- PID发布/采用已接入Core，进程指纹在事务外取得，任务和run记录同一个PID/出生指纹，并用run/claim锁拒绝旧发布。`test_kanban_runs.py`最新6 passed（先2 failed/4 passed，`unified-task9-pid.log`），用实际测试进程指纹验证；未终止当前测试进程。
- owner恢复的具名证据读取接入Core，实测真实PG admission从queued→running→terminal；相同task ID在另一Board/store无回执串读，旧run的worker_result不能成为新run依据。`test_kanban_owner_recovery.py`初始2 failed于原生SQL，修正测试keyword调用后2 passed（`unified-task9-owner.log`）；所有SQLite连接仍拒绝，远程owner不以PID推断状态。
- 过期租约、孤儿与陈旧心跳扫描使用脱离连接的task/run/event水位快照；写入前Board锁内重查，run结束、claim释放、事件与失败预算原子提交。首轮3项红后，两文件5 passed（`unified-task9-sweeps.log`）。加入真实独立子进程的超时终止、死亡/clean-exit分类、终态回收和结算注入回滚后先3 failed/5 passed（未适配crash/reaper，`unified-task9-crash-red.log`），随后8 passed（`unified-task9-crash.log`）。信号hook实测池checkedout=0；等待期新owner回执使旧快照失效；注入失败使run与预算一起回滚。未操作正式进程/服务。
- 派发租约设计已在编码前细化至设计：PG不以持续占连接的advisory lock包住spawn等待；store内持久token租约+续租、短事务认领与预算协调。实现和跨进程/接管证据仍待提供，不能据此声明dispatcher完成。
- 随后新增 `0013_kanban_dispatch` 和store内持久token租约；后台续租用捕获resource的显式scope，不持有等待连接，不运行SQLite文件锁或WAL checkpoint。共享原生lane/budget编排，PG在claim事务内再核对租约与跨Board running预算；共享respawn纯策略，PG存储错误不吞成0/False。`test_kanban_dispatch.py`与`test_schema.py`首轮8 passed（`unified-task9-dispatch-first.log`），含真实子进程tick与另一Board竞争，子进程退出后仍从PG读取running预算。spawn仍为测试回调，尚未验证真实owner/Worker执行链。
- 新增“工作区准备期间operator reclaim”合同先1 failed/4 passed（`unified-task9-spawn-fence-red.log`），证明旧run会继续spawn；启动前加入Board事务内精确run/claim+租约核对与claim续期后5 passed（`unified-task9-dispatch-fences.log`）。其中续租合同越过初始TTL仍保持唯一owner，旧owner释放不会删除继任者token。
- 共享respawn/dispatch改动后原生5文件（db、host_cap、list_undecodable_text、review_lifecycle、dispatch_tick_hook）98 passed、2平台skip（`unified-task9-native-dispatch.log`）。owner回收原生3文件（owner_receipt_reclaim、managed_worker_loss、dispatch_lock）31 passed、2平台skip（`unified-task9-native-owner.log`）。本阶段静态检查14项通过、health56文件0 blocking（`unified-task9-checks-sweeps-partial.log`），该次还未包含后续dispatch/schema13/owner-policy变更。
- 已接入gateway真实policy构建与admission marker入口的PG分支，Board owner引用显式携带Profile home、store_id和稳定Board代次，不接受DSN/SQL/额外字段，也不从assigned Profile重解释Board身份。`test_kanban_owner_policy.py`最初1 failed/1 passed为测试误把Event DTO的dict payload再次json.loads，修正后随owner-recovery/dispatch合同复验；实际结果记录在下一条。原生gateway两个文件排除真实dispatcher lifecycle的选择性回归4 passed（`unified-task9-native-policy.log`）；不外推为完整原生或PG Worker回归。
- 该轮owner-policy/recovery/dispatch实库3文件9 passed（`unified-task9-owner-policy.log`）。补充不完整PG owner receipt后先按SQLite连接拒绝策略1 failed/2 passed（`unified-task9-owner-untyped-red.log`）；PG新数据集不接受历史裸db路径作为owner身份。新回执显式带backend/Profile home/principal，通过配置选择会话SDK；SQLite旧历史裸路径只留在原生Board兼容路径。两文件5 passed（`unified-task9-owner-typed.log`）。
- 原生真实dispatcher argv、普通owner进程、loopback模型/tool round与complete/timeout/rate-limit/billing/crash生命周期随 `test_session_kanban.py` 全文件重跑，与owner_receipt_reclaim共24 passed、2平台skip（`unified-task9-native-owner-typed.log`）。该证据仅SQLite；PG实际Worker/RPC/outbox路径仍未接通。
- 崩溃分类增加protocol连续预算、rate-limit不计失败、真实死亡dispatcher租约按数据库时钟过期并由继任者接管，实库sweeps/dispatch两文件15 passed（`unified-task9-crash-and-lease.log`）。后续静态检查发现3 blocking（两处通用异常缺traceback、续租测试固定sleep）和1 advisory（原始Thread未继承ContextVars），已按规则加诊断、改为轮询数据库时钟，并使用 `spawn_context_thread`；最新复验待记录，未以waiver跳过。
- SDK协议核对后记录Worker命令实现细化：现有 `worker.persist` 必须保持会话owner连续序号，Board可以属于不同Profile/连接目标，不能在会话receipt事务内调用独立Board事务后宣称原子。复用已有受保护JSON outbox增加互斥Kanban pending槽，独立command_id；owner从持久冻结policy获得Board ref，具名mutation在Board主事务登记effect+receipt，未知提交保留同命令待确认。读请求不承载写入，不放宽factory owner-only。该细化已在对应编码前写入设计，尚待实现、真实RPC/故障/重启验收。
- Worker JSON outbox增加互斥 `kanban_pending`，复用原私有目录、独占文件锁、原子落盘、大小限制和已验证adoption规则，不消耗 `worker.persist` 的next_sequence。新增2项合同最初AttributeError红，随后outbox新旧两文件8 passed、1 POSIX平台skip（`unified-task9-command-outbox.log`）。这是本地journal/RPC模拟证据；真实owner RPC和端到端尚未接通。
- 新增 `0014_kanban_commands`，Board主事务可登记无损DTO/tuple/文本结果与request digest；重放只返回同一命令结果，变更payload冲突。comment首个实际消费者的实库回执/Schema合同8 passed（`unified-task9-command-receipts.log`），包含真实COMMIT后客户端确认丢失仍只有1条comment、回执插入失败使comment/event一并回滚、同command ID跨Board/store不串。关键生命周期已逐项插入主事务result登记，后续复验进行中；未将部分hook覆盖外推为全部命令已可远程执行。
- 关键command result hook后8个PG领域文件38 passed（`unified-task9-command-hooks.log`）；该阶段完整静态14项通过、health79文件0 blocking/advisory（`unified-task9-checks-command-partial.log`），不含后续RPC桥接。具名RPC合同实库1 passed（`unified-task9-worker-rpc-first.log`）：真实会话SDK的execution/adoption/generation/epoch与跨store Board effect/receipt均实际读写，PID认证在此项使用既有verified-claim seam，不能算真实子进程认证。canonical覆盖/生成4 passed（`unified-task9-worker-contracts.log`）；之后加入载体/结果桥接，恢复/等待/契约四文件63 passed（`unified-task9-worker-bridge-native.log`）。
- 普通daemon强探针先失败，诊断 `unified-task9-worker-e2e-diagnostic.log` 指向尚未实施的房间启动依赖：`recover_gateway_native_sessions → CanonicalHostedRoomService → RoomCoordination._prepare → hosted_rooms._connect` 实际触发被拒绝的SQLite连接。未关闭房间、未放行SQLite、未把失败改成成功。该全系统场景保留为Task 22必须转绿的显式场景；Task 9改用生产原语组成的嵌入式session owner合同继续验证Kanban/采用Worker/RPC真实链。范围与影响已先写入设计，普通daemon启动/重启仍未通过、整体full_system_ready仍false。
- 真实嵌入式Owner/dispatcher argv/submitter/已采用Worker/RPC/tool实测发现用量结算 `_compression_ancestors` 调用SQLite私有 `_is_compression_child_row`，导致成功Worker被错误结算unknown。核对引入历史 `fcaddb248d` 的压缩祖先用量意图后，新PG合同2项先按AttributeError红（`unified-task9-worker-usage-red.log`），改用已有portable `is_compression_child`；原生用量8 passed（`unified-task9-native-worker-usage.log`）。
- PG真实Worker+用量+命令回执3文件7 passed（`unified-task9-worker-embedded-green.log`）：loopback模型实际调用comment/complete、PG持久化、submitter退出0、所有业务Python进程由sitecustomize拒绝全部SQLite，实际interpreter PID有独立guard见证。关闭重开与Owner重启后epoch增长、重复kanban.run均恢复同一terminal admission，kanban.result退出0、comment仍1条、worker_bound仍1次且没有新增推理。测试服务器修正Ollama `/api/show` 元数据探测应404，推理计数仅计真实 `/v1/chat/completions`；未用停功能回避数据库。该证据仍限嵌入式session runtime，普通daemon待Task 22。
- RPC/Worker桥接阶段静态 `PM Python scripts/check --staged --base 94efe69e4e` 14项通过、health99文件0 blocking/advisory（`unified-task9-checks-worker-partial.log`）；不含后续workspace fence等变更。工作区新增引用竞态合同先2 failed（`unified-task9-workspace-fence-red.log`），实现0015规范路径引用+持久cleanup token后，与完成/Schema3文件15 passed（`unified-task9-workspace-fence-first.log`）。连接外删除期间，另一Board create/set同路径均明确Busy并回滚，清理后可重新引用；父子引用/中断恢复仍继续验证。
- Swarm合同先2 failed（`unified-task9-swarm-red-workspace.log`，原生write_txn明确拒绝PG）；抽出共同卡片计划并以命名Core整图事务实现。随后修正测试误把argv list传给Namespace入口、诊断年龄需同时包含ready事件的fixture问题，Swarm/slash diagnostics与workspace父子/中断2文件7 passed（`unified-task9-swarm-diagnostics-green.log`）。另一Board新增引用、同Board新增live child在目录删除回调期间均Busy且无连接占用；中断token关闭重开仍拒绝新引用，未冒称Task 20对账已完成。
- 新增调度清理故障合同先1 failed/1 passed（`unified-task9-lease-error-red.log`），修正release失败掩盖原UnknownCommitError，原错误对象和unknown语义保留，清理错误加note；正常tick只有release失败仍传播StorageError。该修正已包含下列整批PG回归。
- PG整批实际命令：`$pgFiles = @(Get-ChildItem tests/hermes_db/postgresql/test_kanban*.py | ForEach-Object { $_.FullName }); & $testRunner scripts/run_tests.sh @pgFiles tests/hermes_db/postgresql/test_managed_worker_usage.py tests/hermes_db/postgresql/test_schema.py -j 4 -- -m integration --postgres-test-config=$pgTestConfig`，退出0，18文件75 passed（`unified-task9-pg-regression.log`）。配置fixture限定已核对归属的随机Schema，全业务测试过程拒绝所有SQLite连接。
- 后续真实Worker E2E增加独立命名执行Profile/store_id，与默认Profile两个模式2 passed（`unified-task9-worker-cross-profile.log`）；不是PID或SDK mock。Board effect留在store one，session admission标记实际执行store worker-two与Profile，执行Profile自己的Board仍无任务；重启后同terminal admission、同run、同一comment、无重复推理，实际owner/interpreter/submitter链的SQLite guard均有见证。普通daemon仍保留Task 22失败场景，未替换整系统验收。
- SQLite原生整批实际命令：`$nativeFiles = @(Get-ChildItem tests/hermes_cli/test_kanban*.py | ForEach-Object { $_.FullName }); & $testRunner scripts/run_tests.sh @nativeFiles tests/agent/test_kanban_turn_recovery.py tests/agent/test_kanban_command_outbox.py tests/agent/test_runtime_session_store.py tests/agent/test_runtime_session_store_proxy.py tests/agent/test_turn_finalizer_iteration_limit_exit.py tests/gateway/test_session_kanban.py tests/gateway/test_managed_worker_result_usage.py tests/cron/test_cron_kanban_env_isolation.py -j 4`：90文件首轮680 passed、1 failed、20平台skip（`unified-task9-native-regression.log`）。唯一失败为配置故障测试fixture时机/错误预期；产品原有allowlist失败仍跳过全部card。调整为连接和任务就绪后注入故障、兼容显式配置路径参数，保留skipped_nonspawnable与无claim/run断言，单文件9 passed（`unified-task9-config-fault-green.log`）。其余89个文件通过后实现未再改变，未额外重复运行；没有未整改失败或pass-on-retry。
- 收尾配置/Schema能力两文件9 passed（`unified-task9-capability.log`）；root agent预算seam两项2 passed（`unified-task9-agent-finalizer.log`，`scripts/run_tests.sh tests/agent/test_run_agent.py -j 1 -- -k kanban_block`）；RPC生成/无驱动资源/Board ref四文件9 passed、1 POSIX平台skip（`unified-task9-final-contracts.log`）。最终 `PM Python scripts/check --staged --base 94efe69e4e` 退出0，14检查通过、health112文件0 blocking/advisory（`unified-task9-checks-final.log`）；后续仅更新本执行账本。

未验证/恢复点：Task 10继续订阅、跨Board转移、Board目录生命周期、dashboard/watchers/CLI tail及通用Worker工具消费者；当前PG RPC只绑定真实Kanban采用Worker，普通chat与delegated child工具能力需在Task 10闭合。附件25MB文件传递不能被4MB Worker outbox缩限，需专用文件handoff。附件/workspace中断token与命令提交后工作对账待Task 20。普通daemon仍被后续房间域SQLite依赖阻止，强场景须Task 22转绿。20项跨平台skip没有在本机验证，不伪装OS；Task 24最终验证与独立审查仍未执行。仅Task 9已验收，不宣称完整Kanban或全系统PG。

## Task 10：统一 Kanban 订阅、工作区引用与跨 Board 转移

状态：completed

### 目标

Kanban剩余持久化与所有原生 SQL 消费者完成接入。

### 涉及文件

- `hermes_cli/kanban_db_notify.py`
- `hermes_cli/kanban_db_workspace.py`
- `hermes_cli/kanban_transfer.py`
- `gateway/kanban_watchers_dispatcher.py`
- `tools/kanban_tools.py`
- `plugins/kanban/dashboard/plugin_api.py`
- `hermes_db/operations/kanban_transfer.py`
- `tests/hermes_db/postgresql/test_kanban_integration.py`

### 依赖与接口

- 前置：Task 9。
- 输出：完整Kanban功能在选定PG下不需要任何Board SQLite文件。

### 实施步骤

1. 实现订阅游标、去重、工作区引用及跨Board转移的明确事务；固定多Board锁顺序。
2. 文件/worktree/tmux清理放在提交后受控阶段，保留共享引用和转移的保全证明。
3. 更新dashboard、tools、scheduler和恢复消费者的私有SQL，禁止用临时SQLite连接补查询。

### 验证方式

- `scripts/run_tests.sh tests/tools/test_kanban_tools.py tests/plugins/test_kanban_board_project_api.py`
- PG实测跨Board并发/回滚、订阅恢复、工作区引用不误删及原生入口。

### 完成条件

完整Kanban功能在选定PG下不需要任何Board SQLite文件。

### 执行结果

已完成：订阅/游标/继承、具名dashboard/CLI/watch/GC和网关消费者、按board_id分代的真实文件生命周期、带校验的v2整Board导入导出及原子图写入、普通/派发Worker与child owner RPC、25MiB分块附件handoff。新增0016–0018显式迁移并登记kanban_workspace能力；SQLite仍无需PG依赖。提交标题：feat(storage): complete scoped Kanban storage consumers。恢复点Task11。自动文件job/upload-stage/token维护及全daemon房间依赖按Task20/22闭合，不能把当前业务合同外推为全系统PG完成。以下保留实施过程和失败证据；最终完成依据见本任务末尾。

部分进展：新增0016通知订阅与精确文本/ASCII平台匹配投影，命名订阅操作、owner过滤、原子claim/rewind、独立ping水位、保留清理及create/link/decompose订阅继承。订阅沿原生语义不强制task外键（可预订未来任务），删除任务显式清理订阅；Board FK带store/board，删除Board级联。count在只读PG资源中查询，不以.db存在性跳过，不创建默认Board。尚未完成Task 10其他消费者和完整验收。

实施前布局/转移核对已写入设计：PG本地内容必须跟随board_id代次而非复用slug，采用Profile `kanban/data/<board_id>`，归档显示配置与内容指针，目录清理由持久栅栏保护共享引用。实际kanban_transfer为整Board export/import，没有单任务跨Board移动API；PG保留现有入口，提供无SQLite载荷的归档版本与原子目标导入，不借归档打开旧SQLite迁移。两点属于当前任务实际接口细化，不改变目标和任务总数。

### 验证证据

- `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_notify.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` 首轮2 failed，原生write_txn拒绝PG（`unified-task10-notify-red.log`）。实现后同文件+test_kanban_tasks.py+test_kanban_swarm.py，`-j 3`、相同PG参数，退出0，13 passed（`unified-task10-notify-first.log`）。持久订阅、creator/parent/link继承、NUL/Unicode/0/False元数据、跨store/Board过滤、两个连接竞争claim以及旧rewind不能覆盖新游标均实库验证。
- Task 10完整回归、剩余具名消费者、归档/转移/通用Worker合同与静态门禁尚未执行，不创建commit，不标完成。
- dashboard经真实bundled插件发现/信任挂载+HTTP与线程tail初轮2 failed（`unified-task10-dashboard-red.log`），暴露原生SQL及线程丢失Profile实际打开SQLite；改具名聚合/事件接口、捕获thread Context后2 passed（`unified-task10-dashboard-reads-first.log`）。状态写入新增重开合同先1 failed（`unified-task10-dashboard-write-red.log`），命名Core实现parent/descendant/run/event同事务、归档postcommit终止与清理后3 passed（`unified-task10-dashboard-write-first.log`）。加入审计故障整图回滚后，与notify两文件6 passed（`unified-task10-dashboard-rollback.log`）。
- 原生通知/计数/dashboard/tail/parent-reopen五文件77 passed（`unified-task10-native-dashboard-notify.log`）。CLI watch/GC收口命名接口，PG使用已有cleanup token，真实CLI两阶段读取和持久清理1 passed（`unified-task10-cli-watch-gc.log`）；原生watch/GC两文件13 passed（`unified-task10-native-watch-gc.log`）。这些不是Task 10最终门禁。
- 部分消费者静态 `PM Python scripts/check --staged --base 4bd7861dfc` 退出0，14项通过、health24文件0 blocking/advisory（`unified-task10-checks-consumers-partial.log`）；后续仅增加执行账本和新布局/转移细化，后续实现继续验证。
- 文件代次合同先1 failed，证明同slug新Board仍解析旧附件根（`unified-task10-file-generation-red.log`）。PG本地内容改为绑定board_id，资源/Worker引用捕获同一代次；SQLite布局不变。与完成/工作区/真实Worker四文件14 passed（`unified-task10-file-generation-first.log`）。
- 新增0017持久Board文件任务与短store文件栅栏；归档提交后移动配置、保存旧内容指针和tombstone；同slug配置未结算前拒绝复用。硬删除先提交逻辑退休，配置删除确认后可创建新代次，旧内容被其他Board引用时明确files_pending并保留。附件增加独立规范路径投影，workspace/attachment新引用与退休意图共用短锁，目录删除期间无连接占用。源/目标解析归属和重定向路径均核对，PM文件锁只协调本机文件操作，不替代PG业务状态。Task 20仍须接通维护入口和未知路径投影回填。
- 归档初轮误导入atomic_json_write所在模块，形成3失败（`unified-task10-archive-first.log`）；修正后Board文件/任务/附件/完成/审阅/Schema六文件29 passed（`unified-task10-file-retirement-first.log`）。故障合同初轮3 passed/1 fixture失败：patch了已持有资源的Transactions实例，而生产入口另取资源；改patch实际Transactions类后4 passed（`unified-task10-file-jobs-faults-green.log`），真实COMMIT后抛UnknownCommitError、文件中断均保留持久意图并可重试归档。硬删除保留其他Board工作区/附件，移除引用后退休根回收；回收期间新增引用Busy、重复job不误删同slug新代次配置。

当前恢复点：通知、具名dashboard/CLI读写、父级重开/归档、内容根代次和基础文件job已有局部证据。继续完整export/import PG归档、gateway dispatcher/notifier scope/identity、普通chat/delegated Worker工具与25MB文件handoff；之后整批回归、最终静态门禁才能完成Task 10。没有Task 10 commit。

导入实施前细化：一致读快照导出v2逻辑数据和登记附件SHA-256；不可读/越出管理根附件明确报错，不静默省略。导入私有stage先验证，目标Board+全部rows+import job一次事务提交，文件在事务外发布，激活Board+结算job再一次事务提交；pending Board不能被业务打开，未知提交保留原stage/job而不自动生成新Board。stage/文件job的自动维护入口仍属Task 20，不把手动恢复合同外推为已闭合维护功能。

追加局部证据：PG export公共入口业务合同先失败（`unified-task10-export-business-red.log`），v2逻辑归档实现后1 passed（`unified-task10-export-first.log`）。import公共入口先拒绝v2（`unified-task10-import-business-red.log`）；初版误向safe_extract_targz传str、修正Path后全图导入/事务回滚3 passed（`unified-task10-import-graph-green.log`）。新增0018 import stage持久定位，实际COMMIT确认丢失、文件发布中断、损坏附件校验6 passed（`unified-task10-import-faults.log`）；原stage/job可恢复，pending Board不可打开，没有另建Board重做。

实际scratch完成附件导入后run/event链接仍指源绝对路径，PG和SQLite分别红测（`unified-task10-import-artifact-links-red.log`、`unified-task10-native-artifact-links-red.log`）。核对历史重定位意图后加入共同纯值映射，PG合同6 passed（`unified-task10-import-artifact-links-green.log`），原生transfer20 passed（`unified-task10-native-transfer-green.log`）。禁止三个PG依赖导入的实际SQLite完成/附件/关闭重开子进程1 passed（`unified-task10-sqlite-driver-free.log`）。

真实HTTP并发导入先因run_in_executor丢失Profile选择SQLite v1而失败（`unified-task10-http-transfer-scope-red.log`）；改asyncio.to_thread继承ContextVars，dashboard+transfer两文件11 passed（`unified-task10-transfer-http-green.log`），同名并发导入分配两个独立代次且落到目标Profile。原生Board HTTP生命周期4 passed（`unified-task10-native-transfer-http.log`）。以上PG命令均标准runner、`-m integration --postgres-test-config=$pgTestConfig`，业务进程拒绝所有SQLite连接；SQLite合同不传PG参数。静态partial14项中health46文件无阻塞，ruff发现新子进程测试缺显式check参数（`unified-task10-checks-transfer-partial.log`），已补check=False，待下一批复验。当前恢复点推进为gateway notifier/dispatcher身份及普通chat/delegated Worker/25MB附件handoff，Task10仍in_progress、无commit。

Task10网关/Worker追加进展：dispatcher/notifier按PG store_id+board_id去重/识别代次，PG metadata不再声称有.db路径；通知回写捕获可信Board ref，拒绝归档/复用slug的新代次。后台fresh Context保留捕获的Profile，仅清除请求/child标记。网关合同先3 failed（`unified-task10-watchers-red.log`），初版2 passed/1 fixture缺完整Runner失败（`unified-task10-watchers-first.log`），改真实GatewayRunner后3 passed（包含于`unified-task10-watchers-counts.log`，同批CLI计数仍红）。CLI Board计数原以.db存在性返回空，红测后改具名聚合；合同首次期望triage而实际默认ready，已按业务真实状态修正。原生网关/Board CLI三文件41 passed（`unified-task10-native-watchers.log`）。

普通compute新增owner解析的board.resolve与slug/代次选择器，worker不可自选Profile/DSN；新默认Board只读零行不登记，首次写入在主事务登记稳定default代次，已有默认代次保持不变。真正预留child使用自身claim，继承根policy读权限，owner拒绝所有child mutation；本机delegate运行/重试显式绑定child store。实际PG runtime预留/子claim/首写回执/重开隔离合同1 passed，加原有真实默认/跨Profile专用Worker两例合计3 passed（`unified-task10-interactive-worker-first.log`）。该局部owner协议合同绕过了同进程PID核验，不能替代独立进程认证，独立场景仍在推进。

25MiB附件原直接编码使4MiB outbox_full，红测`unified-task10-upload-red.log`。现用256KiB认证块、owner决定私有stage、准确执行身份/目标/摘要/块长度验证，最终附件与command receipt同主事务；原outbox/transport预算不放宽。实际最大尺寸+真实COMMIT后UnknownCommitError+同命令恢复+文件重开合同1 passed（`unified-task10-upload-first.log`），帧小于1MiB、pending JSON小于64KiB，最终仅一条附件。stage自动回收入口仍须Task20，当前保留恢复材料，不隐藏孤儿清理义务。

独立普通Worker探针未通过，不计完成：初版隔离env缺HOME（`unified-task10-interactive-process-first.log`），补齐后session.create20秒探测超时（second/fourth/diagnostic日志）；third到达实际工具但fixture漏assignee，已补正确assignee和kanban_show。faulthandler证据定位`session_inventory → get_tool_definitions → get_model_context_length → model_metadata_http`，当前明确配置测试模型context_length，不关闭功能。context日志随后证实已进入真实Worker，但fixture仅register未adopt导致stale_generation，已补完整register→adopt；最新`unified-task10-interactive-process-adopt.log`待核结果。原生完整Kanban126文件回归正在运行（`unified-task10-native-regression.log`）。

归档边界补充：循环依赖导入先fixture猜错created_at列，修正按真实row复制后实际未拒绝循环（`unified-task10-import-cycle-business-red.log`）；已加入发布前线性DAG/引用/status/workspace校验，transfer7项已在diagnostic批次通过。静态首次GBK输出编码失败；UTF-8重跑health67文件0 blocking/advisory，footguns发现一个UTF-8读/BOM规则、ruff发现无效noqa和未使用解包，均已修正（`unified-task10-checks-worker-utf8.log`），还需最新全门禁。当前仍9/24、Task10 in_progress，无Task10 commit。

最新追加：完整register→adopt后，独立Worker已实际完成创建/评论/25MiB上传，child的kanban_show返回完整对象而非ok包装；修正fixture按真实协议取task.id后，独立进程/owner重启/数据隔离合同1 passed（`unified-task10-interactive-process-complete.log`，36.9s），所有owner/Worker均有SQLite拒绝guard见证。此前context/adopt日志的失败分别是未采用状态和show响应断言，不隐去。移除临时faulthandler诊断模块，保留堆栈证据。

完整原生126文件首轮934 passed/1 failed/21平台skip（`unified-task10-native-regression.log`，422.7s）。唯一失败是既有fixture直接open('/dev/null')在Windows越出受控目录；历史284d220ba4确认其意图只提供无用的日志句柄，已改隔离Profile下worker.log，不改生产派发语义。相同两项跨Profile合同与SQLite repair/outbox/无PG依赖四文件9 passed（`unified-task10-native-followup.log`）；其余125文件首轮通过。

PG26文件首轮报告105 passed，但运行过程中新增repair守卫合同导致该文件首轮红、代码修正后自动重试绿，属于本次编辑与测试并发造成的污染，不能当稳定最终门禁（`unified-task10-pg-regression.log`保留原始重试输出）。repair独立红测捕获旧SQLite文件连接（`unified-task10-repair-red.log`），已明确拒绝PG下的SQLite索引修复，不触碰旧数据；PG消费者3项+SQLite无驱动1项合计4 passed（`unified-task10-repair-independent.log`）。已冻结业务源码重新运行包含所有真实Worker的PG27文件最终批次（`unified-task10-pg-final.log`），还在等待结果。静态current14项通过、health67文件0 blocking/advisory（`unified-task10-checks-current.log`），最终源码静态与delegate执行回归亦在运行。Task10业务已局部闭合并登记kanban_workspace能力，但仍须这批最终证据通过才标completed并commit。

Task10最终验证：原生Windows/同一PM full-test-env，冻结业务源码后 `scripts/run_tests.sh <tests/hermes_db/postgresql/test_kanban*.py全部25文件> tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、27文件106 passed/0 failed/0 skipped/无重试或flaky（`unified-task10-pg-final.log`，144.3s）。包括真实采用的普通Worker/预留child/25MiB附件/owner重启，以及默认与跨Profile专用Worker；PG父/子业务进程拒绝所有SQLite连接，实际工作、持久化、隔离和恢复均有正向断言。目录I/O/实际COMMIT后确认丢失、共享引用/代次竞争、导入全图回滚及损坏/循环档案拒绝合同同批通过。

SQLite最终证据是前述126文件934 passed、1个/dev/null fixture失败、21个原生平台skip，加修正后4文件9 passed（含该文件全部2项）；其余125文件已通过，未伪造POSIX。`scripts/run_tests.sh tests/tools/test_delegate.py tests/tools/test_delegate_child_transcript_release.py tests/tools/test_async_delegation_worker.py tests/tools/test_delegate_capability_inheritance.py -j 3` exit0、81 passed/0 failed/0 skipped（`unified-task10-child-regression.log`）。无PG依赖的SQLite真实完成/附件/重开也通过。`PM Python scripts/check --staged --base 4bd7861dfc` exit0、14 checks ok，health69文件0 blocking/advisory（`unified-task10-checks-final-source.log`）；之后只更新领域README与本执行账本，diff --cached --check及diff --check均通过。本任务不安装/运维PG、不动正式Profile、未推送。未验证项：POSIX专有合同、自动维护入口(Task20)、全系统普通daemon(Task22)、Matrix实际SDK(Task19)和最终独立审查/复验(Task24)仍未完成。恢复点：Task11，前10项均有本地commit。

## Task 11：统一房间元数据、事件与 replica

状态：completed

### 目标

房间协调数据与会话使用同一选定后端，保留权限/事件谱系。

### 涉及文件

- `gateway/hosted_rooms.py`
- `gateway/hosted_rooms_common.py`
- `gateway/hosted_room_replicas.py`
- `gateway/hosted_rooms_gateway_import.py`
- `hermes_db/tables/rooms.py`
- `hermes_db/operations/rooms.py`
- `tests/hermes_db/postgresql/test_rooms_store.py`

### 依赖与接口

- 前置：Task 2。
- 输出：PG房间协调无需local rooms SQLite，旧数据不被隐式导入。

### 实施步骤

1. 迁移房间、成员、事件、游标、退役及幂等操作到scoped Core事务。
2. 固定 room/epoch/seq 锁及唯一约束，保证事件顺序与权限代次；保留副本检查点语义。
3. PG不执行旧SQLite/legacy import；移除原会话阶段固定本地协调资源的选择逻辑。

### 验证方式

- 房间元数据/事件/replica既有合同，经标准runner执行。
- PG实测双写者事件seq、权限转移、同room_id跨store、退役后重放和重启恢复。

### 完成条件

PG房间协调无需local rooms SQLite，旧数据不被隐式导入。

### 执行结果

已完成房间元数据/事件/副本、私有links/grants/reservations/remote receipts及永久退役的scoped Core实现；新增0019显式迁移，捕获Profile/store/数据库目标引用。已移除原会话阶段独立hosted-pg摘要.db的选择和启动DDL，PG不导入旧SQLite房间；SQLite仍独立可用。提交标题：feat(storage): support scoped room metadata events and replicas。恢复点Task12：将driver/owner/admission/work-record消费者改为typed Core事务；Task13策略/路由、Task14附件和Task22完整daemon仍未完成，不能将本任务元数据合同外推为完整房间或系统PG可用。

### 验证证据

下方保留实施过程、初始失败与局部验证；最终完成证据在本任务末尾。

Task11实施中（前置Task10 commit `297bd9069e`）：新增明确Profile/store引用和具名操作分流、0019房间/事件/永久退役/replica表、scoped Core仓储。普通打开不DDL、不读旧SQLite；私有SQLite连接在PG下明确拒绝。基础创建、只读列表/回放/探测、rename/append、authority CAS、disband/prune均以短store配额锁→房间锁串行化。复用原生验证和DTO，Unicode/NUL名字与JSON以BYTEA保存；回放使用原窗口字节预算和共享纯分页序列化，读取保持现有Transactions的REPEATABLE READ。

`scripts/run_tests.sh tests/hermes_db/postgresql/test_rooms_store.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` 先2 failed捕获shared-state.db（`unified-task11-rooms-red.log`），基础实现后2 passed（`unified-task11-rooms-first.log`）。不同store同room_id、捕获引用在另一个Profile仍读取原owner、值保真/关闭重开、两个连接seq唯一、authority更新拒绝旧epoch、永久退役重放通过。副本实际业务先因原生连接guard拒绝而1 failed（`unified-task11-replica-red.log`）；适配ingest/checkpoint/promote/demote后，与Schema前向升级两文件8 passed（`unified-task11-replica-first.log`）。原生events/只读路径两文件49 passed（`unified-task11-native-events-first.log`），不伪造平台。

当前恢复点：Task11仍in_progress、无commit。继续房间links/grants/reservations/remote receipts等facade公共API、移除原会话阶段hosted-pg摘要.db协调资源和PG legacy import旁路，补实际子进程重启、配额/确认丢失/副本并发/回滚合同与静态检查。Task12 driver、Task13策略和Task14附件仍未实现；当前非空附件出版明确未就绪，没有跳过登记或用内存持久化。新0019尚未提交，可在同一任务内补齐表与冻结迁移；不能修改已提交0001–0018迁移。

追加进展：links/grants/reservations/remote receipts具名Core已接通，字符串/JSON和远端run/session标识保真，不以绝对路径选store；退休payload清理也删除对应scoped元数据。新0019首版新增grant字段漏引号导致PG保留字语法失败（`unified-task11-metadata-red.log`），修正后业务红测明确到原生接口guard（`unified-task11-metadata-business-red.log`），接通后与Schema两文件9 passed（`unified-task11-metadata-first.log`）。协调壳红测定位hosted-pg摘要.db（`unified-task11-coordination-red.log`）；已改为含非秘密目标指纹的RoomStoreRef、验证canonical PG目标，移除启动SQLite/DDL。房间业务+旧SQLite不导入+协调资源6 passed（`unified-task11-coordination-first.log`）；read/write/admission等driver消费者仍归Task12–13，不声称普通daemon已可启动。

PG事务回调CoreEffect拒绝普通SQLite callback；真实提交后丢确认同event_id只一条、配额控制余量、create/admit同事务回滚、独立真实进程拒绝全部SQLite并读取/追加恢复合计3项通过，与主合同两文件9 passed（`unified-task11-faults-first.log`）。副本降级额外核对原始e730deedd1意图：旧authority即使历史配额耗尽也必须能自我围栏；PG初版重用普通事件配额造成红测（`unified-task11-demotion-red.log`），已恢复该既有降级语义并计入实际字节，正在复验`unified-task11-faults-green.log`。

原生五文件rooms/read/replica/links/gateway-import为70 passed/0 failed、1 POSIX平台skip（`unified-task11-native-metadata-green.log`）。此前命令猜错test_hosted_rooms_legacy_import.py不存在而exit2（`unified-task11-native-metadata.log`），不计通过；实际legacy迁移覆盖在已有test_hosted_rooms.py。部分静态14检查通过、health21文件0 blocking/advisory（`unified-task11-checks-partial.log`），之后新改动仍须全门禁。当前恢复：继续PG元数据consumer/副本并发边界、SQLite无PG依赖安装、所有相关入口与源码检查，完善下一Task12的typed transaction边界；Task11仍未完成、不commit。

最终批次前补充：CPython sqlite3审计事件guard覆盖预存connect别名/直接Connection构造，fixture同时记录被业务捕获的连接尝试并在teardown失败；实际Worker sitecustomize和房间重启子进程同步增强，没有给内存库或URI豁免。增强guard后房间+真实普通/专用/跨Profile Worker四文件14 passed（`unified-task11-audit-guard.log`），无尝试见证文件。SQLite阻止全部PG extra导入的独立事件/replica/private metadata实际读写1 passed（`unified-task11-sqlite-independent.log`）。副本双连接同页竞争只有一方ingest、gap失败检查点不变；retention删除links/reservations且永久保留room_id；存储身份变化拒绝旧引用。PG rooms/faults/Schema/domain Schema四文件最终22 passed/0 failed/0 skipped/无重试（`unified-task11-pg-final.log`，23.0s）。静态progress14 checks ok、health27文件0 blocking/advisory（`unified-task11-checks-progress.log`），之后纯文档和补充边界合同仍需最后静态检查。

Task11最终验证与恢复：原生Windows/PM full-test-env，`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_faults.py tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、22 passed/0 failed/0 skipped/无重试（`unified-task11-pg-final.log`）；上一批增强审计后的真实采用Worker/跨Profile Worker/普通Worker/child及房间四文件14 passed（`unified-task11-audit-guard.log`）。既有SQLite五文件70 passed/1 POSIX平台skip（`unified-task11-native-metadata-green.log`），无PG extra的SQLite实际数据读写与预存别名/直接Connection/内存库/URI审计拒绝独立合同两文件2 passed（`unified-task11-standalone-final.log`）。`PM Python scripts/check --staged --base 297bd9069e`最后exit0、14 checks ok、health28文件0 blocking/advisory（`unified-task11-checks-commit.log`）；之后仅更新账本，diff检查通过。本任务没有推送或触及正式Profile/旧SQLite数据。未验证：POSIX限定合同、driver/admission/work-record整机链路(Task12)、策略/附件(Task13–14)、维护(Task20)、全系统daemon(Task22)与最终独立审查(Task24)。恢复点Task12，前11项均有本地commit。

## Task 12：统一房间 driver、任务与 work records

状态：completed

### 目标

房间执行租约、任务代次和回执在 PG 保持原子性。

### 涉及文件

- `gateway/hosted_room_driver.py`
- `gateway/hosted_room_work_records.py`
- `tui_gateway/hosted_room_driver.py`
- `tui_gateway/hosted_room_prepare_stall.py`
- `hermes_db/operations/room_runs.py`
- `gateway/session_hosted_storage.py`、`gateway/session_hosted_service.py`（Task11已移除PG SQLite壳；其typed read/write、owner/admission与driver消费者在本任务闭合）
- `tests/hermes_db/postgresql/test_room_runs.py`

### 依赖与接口

- 前置：Task 11。
- 输出：房间调度完整工作，无SQLite协调锁或备用账本。

### 实施步骤

1. 适配admit/start/renew/stop/settle/recover及work record引用，复用房间权限护栏。
2. 保留单owner、执行代次、未知结果、取消竞争与晚到回执规则。
3. 调度等待、模型、外部peer访问均在短事务外，不用Python锁充当跨进程租约。
4. 将CanonicalHostedRoomService/HostedAdmissionFence的旧SQLite事务回调逐项改为具名Core/CoreEffect，并在remote run receipt事务中接通work-record capture；不得用PG连接执行旧SQL字符串或遗留独立SQLite围栏。Task11只完成其元数据原语，不将该消费者接入标为已完成。
5. 依赖细化：driver保留清理与work-record快照均读取policy_publications。为在Task12闭合真实消费者，将该底层scoped publication表随0020提前建立；Task13仍负责策略checkpoint及实际出版事务，不能用空publication集合宣称策略完成。Canonical服务构造仍依赖Task13策略/路由和Task14附件；本任务先完成typed协调/准入及transport-free driver完整调度合同，整服务验收在后续依赖接通后执行，Task22保留完整daemon强验收。

### 验证方式

- `scripts/run_tests.sh tests/tui_gateway/test_hosted_room_driver_runtime.py tests/tui_gateway/test_hosted_room_worker_capacity.py`
- PG多连接/进程租约、停止竞争、接管、旧回执及故障恢复。

### 完成条件

房间调度完整工作，无SQLite协调锁或备用账本。

### 执行结果

已完成scoped Core租约、准入、启动、Stop/settlement、recover与读取，复用原DTO/验证和代次/幂等规则；0020冻结DDL建立实际driver/work-record及publication基础表。旧driver私有SQLite连接显式拒绝PG。所有room/task/lease围栏含store/room，跨房间member capability反例先红后修复，数值相同的外房间lease不能结算任务。提交标题：feat(storage): persist scoped room driver and work records。恢复点Task13策略checkpoint/router；Task14附件及Task22完整daemon仍待实施，本任务不能外推为完整Canonical房间服务或系统PG已可用。

同事务work-record快照、remote receipt即时捕获、精确pending/ACK与v2 lineage、损坏字节invalid分类/冻结、容量savepoint及已出版终态清理已接通；Canonical owner创建CoreEffect与FIFO member授权使用同一PG连接，移除独立SQLite admission围栏。生产线程driver保存显式RoomStoreRef，容量释放及Stop/重启收获合同通过。PG证据保存原字节，scoped触发器在权威切换时冻结旧producer，不以证据代替执行权限；不导入SQLite旧证据或创建迁移孤儿占位表。

原生回归定位：5文件批次16 passed/1 failed（unified-task12-native-owner.log），唯一失败是既有Profile roster缓存测试，单独复现同样失败（native-cache-repro）。临时诊断仅观察隔离Profile签名（native-cache-diagnosis），确认Windows DirEntry.stat()首次返回子目录内config/profile文件关闭前的旧mtime，后续调用才刷新；marker字节/身份没有变化。已核对c2846b54bb的缓存意图及未修改缓存逻辑的baseline代码。最小改为os.stat(entry.path)读取当前目录状态，保留所有身份/墓碑/粗时钟判据；临时诊断测试已移除，沿用原生失败合同复验。

### 验证证据

原生Windows/PM full-test-env，测试均经scripts/run_tests.sh、独立随机且核对归属的PG Schema。租约先红5 failed（unified-task12-leases-red.log，原路径转换拒绝RoomStoreRef），首轮实现4 passed/1 failed（unified-task12-leases-partial.log，未适配admit_task被SQLite旁路护栏拒绝），继续具名Core状态机后，`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_runs.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit0、24 passed/0 failed/0 skipped/无重试（unified-task12-state-contracts.log）。涵盖实际竞争连接、租约接管/过期/释放、权限转移、准入冲突、取消竞争、未知任务恢复、显式重试和晚到回执；仍未验证work-record原子捕获、完整runtime/跨进程重启、publication清理及最终静态检查，需后续新鲜证据。

最终证据覆盖并取代上述实施中未验证项：`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_runs.py tests/hermes_db/postgresql/test_room_work.py tests/hermes_db/postgresql/test_room_coordination.py tests/hermes_db/postgresql/test_room_driver_runtime.py tests/hermes_db/postgresql/test_room_run_faults.py tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/test_room_faults.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_runtime.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、10文件78 passed/0 failed/0 skipped/无重试（unified-task12-pg-complete.log）。上一轮76 passed的pg-final之后新增跨房间反例确实1 failed（member-scope-red），整改后本轮78全部通过。包括两个真实子进程无SQLite接管、持久未知恢复/旧回执拒绝、Profile隔离、真实COMMIT确认丢失一次结算、Stop并发、snapshot/remote receipt同事务、坏字节保留、容量savepoint、v2 lineage与精确ACK、publication清理、真实FIFO准入及生产线程driver/容量调度；外部session/model RPC为合同stub，完整Canonical模型Worker/daemon仍由Task22验证。

SQLite命令：`scripts/run_tests.sh tests/gateway/test_hosted_room_driver.py tests/gateway/test_room_work_transition_capture.py tests/gateway/test_room_work_evidence.py tests/gateway/test_room_work_receipt_capture.py tests/gateway/test_room_work_service_capture.py tests/tui_gateway/test_hosted_room_driver_runtime.py tests/tui_gateway/test_hosted_room_worker_capacity.py -j 3` exit0、7文件91 passed/无skip（native-first）。owner/group/无PG SDK五文件批次16 passed/1 failed已按上文定位，修复后`... tests/gateway/test_session_group_controls.py tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py -j 2` exit0、2文件8 passed（native-cache-green）；另外四文件10项原已通过。独立SQLite子进程实际屏蔽sqlalchemy/psycopg/alembic导入，仍完成事件/副本/links/driver/证据及ACK真实读写。

`PM Python scripts/check --staged --base 8e1b3c2cc0` exit0、14 checks ok、health35文件0 blocking/advisory（unified-task12-checks-final.log），diff检查通过；之后只更新账本。未验证/未完成范围：POSIX限定、完整Canonical服务构造(Task13–14)、实际模型/peer跨进程链路(Task22)、维护(Task20)、插件与Matrix(Task15–19)、发行及最终独立审查(Task23–24)。PG业务进程维持全SQLite连接审计拒绝，没有新增豁免、回落、双写、服务管理、推送或正式Profile改动。

## Task 13：统一房间策略 checkpoint 与路由调用

状态：completed

### 目标

房间策略、路由和事件水位通过同一数据库的精确CAS提交。

### 涉及文件

- `gateway/hosted_room_policy_checkpoint.py`
- `tui_gateway/hosted_room_router_call.py`
- `gateway/hosted_room_router.py`
- `hermes_db/operations/room_policy.py`
- `tests/hermes_db/postgresql/test_room_policy.py`

### 依赖与接口

- 前置：Task 12。
- 输出：PG策略与路由路径不创建SQLite，旧准备结果不能覆盖新谱系。

### 实施步骤

1. 适配checkpoint、cursor、router claim和结果提交，事务内重新检查epoch和目标事件。
2. 模型路由调用不持锁；Stop/新消息/另一worker获胜后丢弃旧准备结果。
3. 保留room.routed事件幂等和策略快照，不改已建立的提示前缀。
4. 实际值合同核对：policy的thread/member/discussion/task字段来自任意JSON文本，须BYTEA保真。0020提前建立的publication.task_id在0021显式转BYTEA（不修改已提交0020）；事件增加非身份的thread/discussion字符串派生键并建立索引，避免用PG JSONB解析含NUL的合法JSON。显式迁移按scoped键回填已有PG事件；普通打开不DDL，事件内容/摘要/幂等身份不变。room_context读写和CoreEffect一并闭合，因路由规划真实调用它们。

### 验证方式

- 既有路由与policy checkpoint测试，经标准runner执行。
- PG实测两个router竞争、Stop与新消息插入、重开及旧水位提交拒绝。

### 完成条件

PG策略与路由路径不创建SQLite，旧准备结果不能覆盖新谱系。

### 执行结果

已完成scoped Core增量投影、bounded transcript、Continue重开、late receipt、终态publication、冻结输入重建和router claim；0021显式迁移建立策略表并将opaque publication.task_id转BYTEA、回填事件thread/discussion查询键，未修改已提交0020或事件原字节/身份。普通打开无DDL，容量持久保留，重复/竞争同步以store/room锁及cursor CAS提交。room_context保存使用同事务CoreEffect，捕获RoomStoreRef贯穿延迟线程与ServerRPC。提交标题：feat(storage): persist scoped room policy and router claims。恢复点Task14附件元数据；全系统PG验收仍未完成。

真实Canonical服务实例化/owner绑定/策略和路由结果持久化通过，外部模型仅为等待/结果合同stub。实测旧_record_route会在准备期间权威切换后以新权威写入旧结果，核对57c6a9e44b的路由意图及b2680034ba源码后添加捕获gateway/epoch检查；实际PG先红、整改后PG及SQLite均拒绝旧答案，Stop/新消息/另一worker获胜仍保持原CAS/幂等规则。没有通过禁用路由或跳过必要附件初始化声称整服务完成：常规groups.send即使empty manifest仍会进入旧HostedRoomAttachmentStore构造，Task14必须完整闭合该路径和非空附件，Task22再执行完整daemon业务。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_policy.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit1、2 failed（unified-task13-policy-red.log），确实执行到既有Path转换拒绝；未借用Task12或会话测试作为新域完成证据。后续需真实PG投影/claim竞争、Stop/新消息/authority CAS、重启和原生回归。

后续证据覆盖上述未验证项：初版policy/work两文件8 passed（policy-first）；扩展四文件11 passed/1 failed（policy-expanded，测试message.member误用gateway actor，已修正合法member actor）。authority反例初次因测试member_id缺失失败（route-authority-red），修正fixture后明确复现旧准备结果越过权威切换、1 failed（route-authority-red-actual），该日志才作为围栏先红证据。修复后专用五文件15 passed（policy-expanded-green），涵盖真正新Python进程恢复/推进游标、opaque Unicode/NUL水位及publication、两连接claim/重放竞争、Continue/late settled message、冻结输入、容量上限与当前cursor、上下文first-write幂等，以及实际0020已有两store同room事件向0021升级且字节不变。

最终原生Windows/PM环境命令：`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_policy.py tests/hermes_db/postgresql/test_room_policy_schema.py tests/hermes_db/postgresql/test_room_policy_process.py tests/hermes_db/postgresql/test_room_policy_bounds.py tests/hermes_db/postgresql/test_room_route_fences.py tests/hermes_db/postgresql/test_room_runs.py tests/hermes_db/postgresql/test_room_work.py tests/hermes_db/postgresql/test_room_coordination.py tests/hermes_db/postgresql/test_room_driver_runtime.py tests/hermes_db/postgresql/test_room_run_faults.py tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/test_room_faults.py tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、14文件81 passed/0 failed/0 skipped/无重试（unified-task13-pg-final.log）。仅使用核对归属的独立随机Schema，业务Profile和重启子进程严格审计拒绝SQLite；模型等待中实际连接池checkedout=0且另一连接Stop成功。

SQLite：`scripts/run_tests.sh tests/tui_gateway/test_hosted_room_router_authority.py tests/tui_gateway/test_hosted_room_router.py tests/tui_gateway/test_hosted_room_policy_upgrade.py tests/gateway/test_room_work_service_capture.py -j 3` exit0、4文件34 passed（native-first）；`scripts/run_tests.sh tests/gateway/test_hosted_room_context.py tests/tui_gateway/test_hosted_room_service.py tests/tui_gateway/test_hosted_room_settled_retry.py tests/tui_gateway/test_hosted_room_frozen_publication.py tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py -j 3` exit0、5文件55 passed（native-rest），均无skip/重试。无PG SDK子进程实际完成SQLite driver/work/policy/claim读写。`PM Python scripts/check --staged --base b2680034ba` exit0、14 checks ok、health29文件0 blocking/advisory（unified-task13-checks-final.log），diff检查通过；之后只更新领域说明和执行账本。

未完成/未验证：附件构造、非空附件/真实Send端到端(Task14)，指标/插件/Matrix(Task15–19)、维护(Task20)、全系统入口与普通daemon强验收(Task21–22)、发行/独立审查(Task23–24)。正式Profile/SQLite数据/数据库服务保持原状，无推送、发布、PR或合并。

## Task 14：统一房间附件元数据与配额

状态：completed

### 目标

附件元数据、引用及配额入PG，附件二进制维持文件存储。

### 涉及文件

- `gateway/hosted_room_attachments.py`
- `gateway/session_ingress_media.py`
- `hermes_db/operations/room_attachments.py`
- `tests/hermes_db/postgresql/test_room_attachments.py`

### 依赖与接口

- 前置：Task 11、Task 12。
- 输出：附件元数据无SQLite，文件与DB的失败窗口有明确恢复证据。

### 实施步骤

1. 实现scoped元数据、幂等、引用和配额，使用范围锁保护并发上限。
2. 保留blob准备/提交/清理和重启对账，DB失败不能误删唯一附件内容。
3. 关联房间事件和退役护栏，保持路径/ACL/内容去重边界。
4. 实际协议细化：Native put/commit/sweep在SQLite事务内执行文件IO，PG不能照搬。持久namespace区分同Profile的不同数据集；复用PM文件门闩保护候选/清扫的本地竞争，配额/引用仍为scoped SQL事务，文件校验全部移到连接外。cleanup job与最后引用删除同事务；未知COMMIT不删除候选文件。不存在的quarantine/disband_fences仅是旧SDK可选读取协议，当前仓库没有写入者，不创建占位业务表；已有权威/退役护栏在实际Core消费者验证。

### 验证方式

- 附件既有安全/限额/对账测试经标准runner执行。
- PG实测配额竞争、文件成功DB失败、DB成功清理失败、重复请求和重启。

### 完成条件

附件元数据无SQLite，文件与DB的失败窗口有明确恢复证据。

### 执行结果

已完成0022显式namespace/blob/attachment/cleanup迁移及具名Core操作，保留原纯验证、ACL、内容文件、上传幂等、逻辑/物理配额、引用计数、commit/abort/retain和member/viewer/range协议。非空manifest的严格retention在实际room append同一事务中执行，出版失败完整回滚。实际CanonicalService的普通Send和非空附件Send、任务冻结manifest、member materialization、viewer下载及服务重开均已实测；原SQLite连接在PG明确拒绝。

所有文件准备、校验、删除和文件锁等待在数据库连接外。持久namespace区分同Profile的不同数据集；捕获资源逐操作核对namespace，旧句柄拒绝新数据集，已删除内容根不被清扫回调重建。复用PM本地跨进程文件门闩，配额/引用仍由scoped SQL短事务保护；清扫先等待未决store写事务结束，再开新读快照核对live blobs。最后引用删除和持久cleanup job同事务；未知COMMIT保留候选，文件删除失败保留job供真实新进程重放。PG不读取旧SQLite内容树。恢复点：本项提交后进入Task15；Task20维护入口和Task22普通daemon/Worker全流程仍须单独闭合。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_attachments.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit1、1 failed（unified-task14-attachments-red.log），实库Schema已初始化、失败为现有Path(RoomStoreRef)拒绝；未把此前房间领域的证据当作附件完成证据。后续必须覆盖真实文件与PG持久化、Scope、跨进程配额、故障窗口、重启和常规Send/非空文件。

首轮实现1 passed（attachments-first）；非空事件出版先红1 failed/1 deselected（publication-red，真实执行到Task11未就绪adapter），接通同事务严格retention后2 passed（publication-first）。当前`... test_room_attachment_faults.py test_room_attachments.py -j 2 -- -m integration --postgres-test-config=$pgTestConfig` exit0、2文件6 passed/无skip/无重试（unified-task14-faults-first.log），包括真实文件成功SQL拒绝后的安全孤儿清扫、实际business COMMIT后确认丢失不删除唯一内容、数据库成功文件删除失败的持久job及真实新进程重放、另一个真实进程读取/提交/恢复同一PNG，以及文件写入/commit校验/读取时连接池checkedout=0。其余上述范围未验证，Task14仍未完成。

最终验证（以上为保留的中间记录）：`scripts/run_tests.sh tests/hermes_db/postgresql/test_room_attachments.py tests/hermes_db/postgresql/test_room_attachment_{faults,guards,service,concurrency,values,limits}.py <其余test_room*.py> tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig`（PowerShell数组展开实际21文件，日志unified-task14-pg-final.log），exit0、104 passed、0 failed/skip/retry。新增7文件23项，包括两个真实进程争同一配额、PG实际blocking_pids证据证明清扫等未决COMMIT后保留文件、独立Profile去重/配额/清理隔离、64未提交项限制、NUL二进制/PNG/PDF/zip/Unicode名称字节保真、篡改/范围/权限/退役竞态、代次替换和删除根护栏。所有业务PG fixture/子进程拒绝包括内存/URI/别名在内的SQLite连接。

`scripts/run_tests.sh tests/gateway/test_hosted_room_attachments.py tests/gateway/test_hosted_room_attachment_publication.py tests/gateway/test_hosted_attachment_bridge.py tests/gateway/test_hosted_room_runtime_attachments.py tests/tui_gateway/test_hosted_room_attachment_routes.py -j 3` exit0、46 passed/1 skipped（unified-task14-native-first.log）；skip为当前Windows无权限创建符号链接，篡改检测已执行，不能声称该symlink分支通过。`scripts/run_tests.sh tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py -j 1` exit0、1 passed（unified-task14-sqlite-no-pg.log），子进程阻止SQLAlchemy/psycopg/Alembic导入，实际SQLite附件put/commit/read及既有房间业务继续可用。最后PG-only资源护栏补充后专测12 passed（namespace-guards）、限额3 passed（limits）。实际service初轮因fixture仅1个member被原生双成员规则拒绝，修正为ops/review后1 passed（service-followup），不是产品缺陷或有效业务红证据。

`PM Python scripts/check --staged --base abb9f65e5a` exit0、14 checks、health24文件0 blocking/advisory（unified-task14-checks-final.log）。完成提交标题`feat(storage): persist scoped room attachment metadata and quotas`；正式Profile/服务/SQLite数据未触碰，无新依赖。未验证项仍为上述Windows symlink分支、Task20系统维护及Task22全系统强验收，不能据本项宣称全系统PG后端完成。

## Task 15：统一指标、consent 与 outbox

状态：completed

### 目标

本地指标持久化使用所选后端，保留发送授权与去重语义。

### 涉及文件

- `hermes_cli/observability/shared_metrics.py`
- `hermes_cli/observability/shared_metrics_snapshot.py`
- `hermes_cli/observability/shared_metrics_sender.py`
- `hermes_cli/observability/shared_metrics_install_run.py`
- `hermes_db/operations/metrics.py`
- `tests/hermes_db/postgresql/test_metrics_store.py`

### 依赖与接口

- 前置：Task 2。
- 输出：指标路径不依赖metrics.sqlite3，授权与去重规则保持一致。

### 实施步骤

1. 保留安装/拥有者范围，适配aggregate、packaged水位、consent窗口、标记与outbox。
2. 同一短事务生成包和推进水位；导出文件、发送与等待不占DB事务。
3. 使用既有opt-in，不增加遥测内容/发送范围；覆盖opt-out时仍发生的本地操作。

### 验证方式

- 现有shared_metrics/consent/sender tests经标准runner执行。
- PG实测聚合竞争、同窗口去重、打包重试/重开与发送后回执丢失。

### 完成条件

指标路径不依赖metrics.sqlite3，授权与去重规则保持一致。

### 执行结果

已完成0023迁移、领域表/具名Core操作、SharedMetricsStore与sender工厂分流；聚合、rollup、interval/day/首次使用标记、安装身份、包水位、consent obs/data、outbox claim/续租/token CAS及保留清理使用PG。PG保留Profile内安装身份，以独立metrics范围锁序列化原SQLite写事务语义，不使用连接SQL翻译壳；opaque版本/JSON/state键值按BYTEA保真。指标PG故障直接传播到既有显式best-effort调用边界，不把未落库数据当作持久化成功。文件/POST/重试等待不占连接。恢复点：本项提交后进入Task16；Task20维护、Task21全入口审计、Task22完整daemon单后端及Task23发行/完整用户文档仍待验收。

核对修正：旧启动consent对账为进程全局bool，多个Profile会只对账首个（intent提交5e380d95ba为opt-out仍对账）；改为按拥有者Profile的集合，实库逐Profile关闭窗口。安装年龄PG先查实际scoped sessions，不访问或改写旧state.db。新增接口后SQLite测试RealBackedStore替身补具名reconcile委托，保留真实SQLite窗口断言。现有Windows退出测试在任何产品代码前无条件patch不存在signal.alarm；核对生产逻辑本就按hasattr选择deadman，测试同样只在主机支持alarm时patch，Windows实际指标flush业务继续执行，不增加skip或伪造平台。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_metrics_store.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit1、2 failed/2 teardown errors（unified-task15-metrics-red.log）：真实PG已初始化，业务构造器尝试SQLite连接，fixture同时记录即使调用方吞错也不可接受的连接尝试；这是Task15独立红证据。尚无完成验证或本地任务commit。

中间记录：metrics-first 2 passed；pg-first 3文件10 passed（窗口on/off/on拒绝期、时钟钳制、opt-out逐Profile、事务回滚/导出失败/未知commit、claim过期及旧token/身份轮换）；process-first 2 passed，真实双进程40增量+1 latch和另一新进程打包、文件失败后新进程恢复。consumers-first 2文件5 passed/1 failed/1 teardown error，失败为测试直接构造原生SQLite SessionDB，修正为已有生产open_session_store工厂；HTTP2项已通过，包括真实202后本地回执丢失、字节相同的再发、持久429退避且POST时池checkedout=0。native-first 196 passed/3 failed/4 skipped（旧接口替身），更新后native-full 631 passed/1 failed/7 skipped（alarm测试），修正后sqlite-followup 8 passed/1 POSIX skip，含阻止所有PG驱动导入的真实SQLite聚合/consent/打包/发送子进程。checks-first报2处新异常边界检查，已改为仅捕获StorageError，最终检查尚未运行。

最终验证（保留以上中间失败）：`scripts/run_tests.sh <PowerShell数组展开test_metrics*.py的6文件> tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、8文件27 passed/无skip/retry（unified-task15-pg-final.log）。consumer修正先因测试传入create_session不支持的started_at失败1项（consumers-followup），改为实际公开create/get API读取真实时间后已包含在最终4项通过中；旧SQLite取证文件逐字节保留。追加必需的保留窗口/首次使用/时钟修正/导出无连接合同后`... test_metrics_store.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit0、4 passed（retention-latches），PG合计29个独立合同，均在拥有者核验的随机Schema和严格SQLite拒绝下执行。

SQLite完整29文件回归中28文件通过（native-full保留631 passed/1 failed/7 skipped原记录）；修正唯一alarm测试后`... tests/hermes_db/contracts/test_metrics_sqlite_optional_drivers.py tests/hermes_cli/test_shared_metrics_exit_flush.py -j 2` exit0、8 passed/1 POSIX skip（sqlite-followup），其中退出文件7 passed，无新增skip；其余6个原跳过项为原POSIX权限/进程/安装脚本等主机限制，本轮不声称它们在Windows通过。`PM Python scripts/check --staged --base 8eb11259b6`最终exit0、14 checks/health31文件0 blocking/advisory（unified-task15-checks-pass.log）；先前checks-final仅1个未使用测试变量失败，已修正。暂存区diff检查通过。

完成提交标题`feat(storage): persist scoped metrics consent and send outbox`；无新依赖、无遥测内容/授权扩张、无正式Profile/服务变更。未验证项保留上述7个平台skip与后续任务全系统证据，不能由此宣称全系统PG完成。

## Task 16：提供插件可移植持久化协议

状态：completed

### 目标

为维护中的插件提供统一选择和范围隔离，停止把原生SQLite连接当作通用后端API。

### 涉及文件

- `plugins/plugin_storage.py`
- `hermes_db/domains/plugins.py`
- `hermes_db/tables/plugins.py`
- `hermes_db/operations/plugin_storage.py`
- `tests/plugins/test_plugin_storage.py`
- `tests/hermes_db/postgresql/test_plugin_storage.py`

### 依赖与接口

- 前置：Task 2。
- 输出：插件存储能力可由PG独立提供，并有真实消费者合同；外部插件适配要求明确。

### 实施步骤

1. 定义有明确插件消费者的键值/CAS/分页及领域队列边界，绑定store_id、plugin_id、namespace。
2. SQLite模式保留原plugin_db语义；PG调用旧SQLite专用API明确报能力错误，不生成SQLite文件。
3. 迁移后续Discord/RetainDB实际消费者并提供插件指南；不做任意SQLite SQL翻译，不以禁用功能验收。
4. 依赖细化：当前plugin_db无生产调用者，将Task17已有Discord恢复游标的get/advance提前作为真实KV消费者；SQLite保留已有cursor表，PG接入插件namespace。Task17仍负责完整消息/扫描/恢复故障合同，Task18负责专用队列；不能把仅游标支持外推为Discord已完成。

### 验证方式

- `scripts/run_tests.sh tests/plugins/test_plugin_storage.py`
- PG实测插件同key/namespace隔离、CAS、配额/保留、重开与不兼容API明确失败。

### 完成条件

插件存储能力可由PG独立提供，并有真实消费者合同；外部插件适配要求明确。

### 执行结果

已完成公开plugin_store及driver-free PluginRecord/冲突/配额/Protocol类型；0024显式PG plugin_namespaces/records，SQLite独立portable.db，不导入旧plugin_db数据或迁移JSON文件。namespace持久revision避免delete/TTL后的ABA，PG真实namespace行锁保护CAS/配额，keyset扫描无offset，JSON/NUL/Unicode保真，逐操作捕获Profile/store/target。旧plugin_db在PG创建目录/连接前明确报插件名与替代API。实际Discord cursor get/advance已接协议，SQLite仍用原表，Task17全账本未完成。公开插件指南已更新，包含CAS/TTL/分页/配额、Profile捕获、未知提交后观察而非盲重试和SQLite专用API边界。恢复点：本项提交后进入Task17完整Discord消息/扫描账本与所有实际消费者；RetainDB专有队列仍为Task18，不用KV冒充队列完成。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_plugin_storage.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig`首轮exit1、2 failed/1 teardown error（unified-task16-red.log）：缺新协议且旧入口实际尝试SQLite；初实现2 passed（first），扩展后5 passed（consumer-first），包括实际DiscordAdapter游标写/重开/更新/Profile隔离、共享公开契约、TTL和CAS/ABA。`scripts/run_tests.sh tests/plugins/test_plugin_storage.py tests/plugins/test_portable_storage.py tests/gateway/test_discord_missed_message_backfill.py -j 3` exit0、3文件32 passed/无skip/retry（native-first）。当前尚无最终门禁或本项本地commit。

最终验证（以上为中间记录）：`scripts/run_tests.sh tests/hermes_db/postgresql/test_plugin_storage.py tests/hermes_db/postgresql/test_plugin_storage_process.py tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、4文件18 passed/无skip/retry（unified-task16-pg-pass.log）。含实际4,096个存量key拒绝第4,097并删除后释放、真实16 MiB namespace的最后1 MiB跨两个进程竞争仅一成功、每值1 MiB拒绝、namespace/Profile独立配额、真实进程CAS单一胜者/新解释器读取、实际COMMIT后确认丢失可读且CAS0重试拒绝、UTF8/NUL前缀keyset扫描、非JSON值拒绝和SQLite旧API明确失败。PG业务fixture/子进程拒绝所有SQLite连接，无内存/URI/别名豁免。

`scripts/run_tests.sh tests/plugins/test_plugin_storage.py tests/plugins/test_portable_storage.py tests/gateway/test_discord_missed_message_backfill.py tests/hermes_db/contracts/test_plugins_sqlite_optional_drivers.py -j 3` exit0、4文件34 passed/无skip/retry（unified-task16-native-final.log）。其中子进程实际阻止SQLAlchemy/psycopg/Alembic导入并执行SQLite持久化、CAS、delete/rebuild及scan。第一次进程测试2 failed（process-first与pg-final保留）：探针命名plugins.py遮蔽顶层plugins包，改名portable_plugins.py后真实进程通过；不是产品缺陷或有效业务红。`PM Python scripts/check --staged --base b74b53b114`最终exit0、14 checks/health19文件0 blocking/advisory（checks-final），首次仅__all__排序失败已修正。暂存区diff检查通过。

完成提交标题`feat(storage): provide portable scoped plugin records`；无新依赖、无正式实例/配置/旧SQLite变更。未验证范围：Task17消息/扫描完整恢复、Task18远端pending队列、Task19 Matrix实际SDK、Task20–24维护/全入口/整体验证，不能以游标接入代替这些功能。

## Task 17：统一 Discord 恢复账本

状态：completed

### 目标

Discord已完成消息、扫描及游标恢复完整使用选定后端。

### 涉及文件

- `plugins/platforms/discord/recovery.py`
- `plugins/platforms/discord/adapter*.py（实际消费者）`
- `hermes_db/operations/discord_recovery.py`
- `tests/hermes_db/postgresql/test_discord_recovery.py`

### 依赖与接口

- 前置：Task 16。
- 输出：Discord恢复不需要discord_message_recovery.db且既有功能保留。

### 实施步骤

1. 适配message、scan、cursor、尝试次数和保留窗口，严格限制到插件/store scope。
2. 保持恢复去重、回执及错误脱敏；PG不可用不能伪装空记录成功。
3. 使用实际恢复入口测试重启，所有外部消息通过本机fixture模拟，不向用户频道发送测试消息。

### 验证方式

- Discord既有恢复合同，经标准runner运行。
- PG实测重复消息、游标竞争、扫描重放、重启及数据库故障。

### 完成条件

Discord恢复不需要discord_message_recovery.db且既有功能保留。

### 执行结果

已完成全部message/scan/cursor及启动探测消费者的具名协议、0025显式迁移和PG完整账本。SQLite保留原表/数据；PG不提供lambda(SQLite Connection)回调，旧private call明确拒绝，故障明确传播而非空记录。response与Task16 cursor在同一事务。已复现并修复旧attempt在seen保留responded后仍无条件UPDATE覆盖终态的问题；intent提交8c6881231a要求已投递不再重派，两个后端加终态保护并合并seen/attempt事务。scan_id改为每次扫描UUID避免毫秒/PID碰撞覆盖。错误在连接外复用已有强制redaction。恢复点：本项提交后进入Task18 RetainDB实际provider/pending队列；Task20–24系统维护、全入口和最终门禁仍待完成。

当前实现：0025及message/scan/locks表、捕获Profile/store/target的资源、具名store/操作/SQLite协议已接通。adapter消费者已从facade抽至recovery_events；旧Task16 recovery_cursors内部模块删除并更新唯一消费者，不留重导出。SQLite schema初始化先提交，再对具名操作使用IMMEDIATE，防止跨实例SELECT后终态被覆盖；PG store/plugin行锁保护状态，回复与plugin namespace cursor同事务。首轮PG/原生流程已通过，最后检查两处COALESCE空值语义并补值/清理隔离证据，尚未完成本项。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_discord_recovery.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit1、2 failed/2 teardown errors（unified-task17-pg-red.log），实际消息/回复入口尝试SQLite。`scripts/run_tests.sh tests/gateway/test_discord_recovery_completion_race.py -j 1` exit1、1 failed（completion-race-red），真实SQLite已完成消息被迟到queued撤销，非推测问题。尚无实现通过证据或本地任务commit。

中间证据：pg-first 2文件9 passed（Discord2+插件7）；backfill-first 2 passed，真实候选迭代/授权/派发入口在本地Discord消息fixture运行，两次实际扫描仅首次派发、持久scan成功回执与PG故障不作为空记录；faults-first 3 passed（回复/cursor同事务回滚、实际COMMIT后确认丢失+新进程读取、真实retention/错误强制脱敏）；native-first 21 passed，native-followup 3文件41 passed（含既有journal合同）；sqlite-no-pg 1 passed，真实Native ledger在阻止PG三依赖导入的子进程仍可完成attempt/complete/response/cursor。pg-final首轮8文件28 passed/无skip/retry；checks-first 14 checks通过、health20文件无发现。最后两处COALESCE空字符串语义修正后复验尚未结束。

最终验证（以上为中间记录）：`scripts/run_tests.sh <PowerShell数组展开test_discord*.py的4文件> tests/hermes_db/postgresql/test_plugin_storage.py tests/hermes_db/postgresql/test_plugin_storage_process.py tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、8文件30 passed/无skip/retry（unified-task17-pg-pass.log）。新增Discord12项：实际backfill两次扫描去重、startup/read故障传播、回复/cursor原子回滚与实际COMMIT确认丢失后的新进程恢复、两个进程终态竞争、attempt预算/claim过期不被discovered续期、scope限定retention、NUL/Unicode SDK IDs及空字符串/None精确保真、旧SQLite回调拒绝。真实外部频道/模型没有被调用，只有本机消息/client fixture；PG进程和子进程严格拒绝全部SQLite入口。

`scripts/run_tests.sh tests/gateway/test_discord_missed_message_backfill.py tests/gateway/test_discord_recovery_completion_race.py tests/hermes_state/test_journal_mode_config.py -j 3` exit0、3文件41 passed/无skip/retry（native-followup）；`... tests/hermes_db/contracts/test_discord_sqlite_optional_drivers.py -j 1` exit0、1 passed（sqlite-no-pg）。`PM Python scripts/check --staged --base 8145fcafab`最终exit0、14 checks/health20文件0 blocking/advisory（checks-final）；暂存区diff检查通过。初次用于更新facade的PM解释器在默认sandbox启动被拒绝，授权范围内提升后成功，无业务数据影响或自动审批拒绝；不把该环境执行失败当作业务测试红证据。

完成提交标题`feat(storage): persist scoped Discord recovery ledgers`；无新依赖、无正式Profile/服务/旧SQLite变更。未验证项仍为后续Task18–24，不能将本领域证据外推为全系统PG已经完成。

## Task 18：统一 RetainDB 本地 pending 队列

状态：completed

### 目标

RetainDB插件本地队列不再要求SQLite，同时保留远端服务协议。

### 涉及文件

- `plugins/memory/retaindb/__init__.py`
- `hermes_db/operations/retain_queue.py`
- `tests/hermes_db/postgresql/test_retain_queue.py`

### 依赖与接口

- 前置：Task 16。
- 输出：维护中的RetainDB功能可在PG模式工作，不创建retaindb_queue.db。

### 实施步骤

1. 端口化pending入队、取批、确认和失败保留，明确队列幂等身份与关闭顺序。
2. 队列线程显式绑定拥有者scope，远端请求在DB事务外；不修改远端产品数据存储。
3. 测试实际provider队列入口，用受控本机客户端代替外部付费/真实请求。

### 验证方式

- RetainDB既有队列/provider合同，经标准runner运行。
- PG实测线程并发、发送失败、确认丢失、进程重开和跨store隔离。

### 完成条件

维护中的RetainDB功能可在PG模式工作，不创建retaindb_queue.db。

### 执行结果

已完成0026领域表/资源/具名操作与PG队列、原生factory分流和provider拥有者初始化。已核对_Client.ingest_session实际三参数协议；PG用持久request_id/指纹/claim token和紧凑确认，消息正文确认后清除，终态同request不重发。远端at-least-once不虚构幂等header或exactly-once。目标摘要绑定endpoint/project，API key不进入摘要；旧目标pending明确告知并保留，不能改投新目标，恢复原配置后可继续投递。初始化先在拥有者scope读配置/秘密并启动上下文线程，重初始化先关闭原队列，SOUL后台seed捕获原client/agent身份。

worker按短事务/SKIP LOCKED/持久token claim，POST前续租CAS，确认/失败均精确token结算；HTTP、等待、退避、join不借PG连接。未知入队错误携带安全request_id且仍唤醒数据库重查，未知claim无发送权，未知确认不猜测回滚。关闭拒新、限时等待并报告保留pending。SQLite实现及旧数据保留，不导入PG；PG持续一条一批从数据库取工作，已实测205条启动积压完整恢复。恢复点：本项提交后进入Task19，必须核对实际Matrix SDK并做真实密钥/PG协议验证，不借本项证据外推。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_retain_queue.py -j 1 -- -m integration --postgres-test-config=$pgTestConfig` exit1、1 failed/1 teardown error（unified-task18-provider-red.log），实际provider initialize通过旧_WriteQueue尝试SQLite。尚无实现通过证据或本地任务commit。

中间证据：provider-first 1 passed；provider-persistence 1 passed，真实sync_turn在外部client阻塞时查到claimed/payload持久行，池checkedout=0、另一Profile pending=0，结束后紧凑ACK清除user/session/messages。provider-owner 2 passed，指定owner在另一个ambient Profile中初始化并sync，实际工作线程读取拥有者的config/secret。native-first 29 passed/1 failed，为旧fixture只mock get_hermes_home但未同步HERMES_HOME导致新拥有者绑定正确拒借另一Profile环境；将fixture实际launch home与mock一致、scope标记拥有者后native-followup 2文件30 passed。transactions-first 3 passed（request幂等、目标scope、终态、到期接管token CAS、真实失败延期/消息冻结）；worker-process-first 5 passed（双writer、实际ACK提交确认丢失不重发、远端成功但本地无ACK的真实新进程重放、205条积压全恢复）。

最终验证：`scripts/run_tests.sh <PowerShell数组展开test_retain_queue*.py的4文件> tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=$pgTestConfig` exit0、6文件20 passed/无skip/retry（unified-task18-pg-final.log）。RetainDB独立11项另含改变project不接管旧pending、恢复原project实际成功、实际enqueue COMMIT确认丢失仍有request_id且不丢投递。所有PG fixture和新进程拒绝全部SQLite入口；只用本机受控client，未请求实际RetainDB服务。崩溃lease重放以拥有者Schema内设置lease过期代表已过TTL，不声称实际等待了生产120秒TTL。

`scripts/run_tests.sh tests/plugins/memory/test_retaindb_provider.py tests/plugins/test_retaindb_plugin.py -j 2` exit0、30 passed/无skip/retry（native-followup）；`... tests/hermes_db/contracts/test_retain_sqlite_optional_drivers.py -j 1` exit0、1 passed（sqlite-no-pg），实际provider/SQLite队列在SQLAlchemy/psycopg/Alembic导入全拒绝的独立进程完成sync_turn/落库/发送/确认。`PM Python scripts/check --staged --base 8ebb3e5691`最终exit0、14 checks/health16文件0 blocking/advisory（checks-final），暂存区diff检查通过。

完成提交标题`feat(storage): persist scoped RetainDB pending queue`；无新依赖、无正式Profile/服务/旧SQLite修改。未验证项为Task19 Matrix实际SDK及Task20–24系统闭合/最终门禁；远端原生协议的at-least-once限制明确保留，不宣称远端去重保证。

## Task 19：适配 Matrix 加密存储完整 SDK 协议

状态：completed

### 目标

Matrix E2EE本地持久化在PG模式独立运行，纳入统一schema、scope、迁移和连接预算。

### 涉及文件

- `plugins/platforms/matrix/adapter.py`
- `plugins/platforms/matrix/adapter_crypto*.py`
- `hermes_db/domains/matrix_crypto.py`
- `hermes_db/operations/matrix_crypto.py`
- `hermes_db/tables/matrix_crypto.py`
- `tests/gateway/test_matrix_crypto_store_per_profile.py`
- `tests/hermes_db/postgresql/test_matrix_crypto_store.py`

### 依赖与接口

- 前置：Task 2、Task 16。
- 输出：完整协议有覆盖矩阵和真实PG证据，Matrix功能不被禁用；依赖/平台未满足时任务保持未完成。

### 实施步骤

1. 读取PM锁定的实际mautrix版本协议，列出完整方法/表/初始化要求和支持平台；先写可执行合同再实施。
2. 用hermes_db Core/同步psycopg实现SDK CryptoStore适配，异步边界受控转线程，不另起绕过预算/隔离的PG池。
3. 覆盖账号设备、Olm/群组会话、设备列表、密钥请求等实际协议；PG依赖探测不强制SQLite驱动。
4. 使用真实SDK对象和测试密钥完成加密对象写读/重开/隔离；PG不读取旧crypto.db或pickle、不重置远端设备。

### 验证方式

- `scripts/run_tests.sh tests/gateway/test_matrix_crypto_store_per_profile.py`
- PM安装真实支持版本SDK后运行PG协议及密钥round-trip；缺libolm/SDK/适用平台则记录未验收，不算通过。

### 完成条件

完整协议有覆盖矩阵和真实PG证据，Matrix功能不被禁用；依赖/平台未满足时任务保持未完成。

### 执行结果

实施中：已核对现有adapter连接/迁移/依赖检查路径，当前显式SQLite URL、强依赖asyncpg+aiosqlite、旧pickle迁移与远端设备删除分支均不能照搬PG。项目锁定mautrix[encryption]==0.21.1，matrix extra明确仅Linux，Windows正式测试环境没有SDK/libolm；只读确认现有Ubuntu-26.04 WSL Running，旧独立Linux测试解释器同样无SDK。正在已有Linux主机通过PM/no-install-project创建全新matrix+postgresql+messaging/dev/test隔离环境，home/runtime均随机/tmp根，未改正式Profile、未安装/启动/运维数据库服务。状态文件`.build/postgresql/matrix-linux-state.json`只含非秘密路径，构建日志unified-task19-linux-pm-build.log；后续必须读取真实安装协议并运行真实密钥PG往返，当前未完成。

SDK环境已实际构建成功exit0；状态root为/tmp/hermes-unified-matrix-5bb7b10a96b1，实际mautrix0.21.1/python-olm3.2.16，真实OlmAccount identity pickle往返通过。初次前置探针漏传SDK shared参数而TypeError，按实际from_pickle签名补齐后通过，属于SDK核对而非产品业务红。已读取实际CryptoStore37方法+SyncStore2方法和Session/GroupSession/Device/TOFU/CrossSigner构造及OlmMachine消费者，形成[协议覆盖矩阵](../designs/unified-database-matrix-protocol.md)。SDK事务网络query在外，内部设备验证/本地状态调用在受控同步线程执行真实事务；key-request没有独立DB协议，必须用实际SDK请求/forwarded-key路径验证group持久化，不能发明占位表。恢复点：实现共享Schema/完整Core store及adapter安全分流，仍未完成。

### 验证证据

尚无业务验收结果。已用PM解释器importlib.metadata读取实际Windows/已有Linux环境：mautrix/python-olm/aiosqlite/asyncpg均未安装；pyproject/uv.lock限定Linux及0.21.1；hermes_platform.resolver解析wsl后只读list确认现有Ubuntu与docker-desktop均Running。这是SDK/主机前置核对，不是Matrix协议或PG功能通过证据。依赖缺失不能静默禁用E2EE或把类名PgCryptoStore当作支持PG。

`HERMES_PYTHON=<上述PM Linux python> scripts/run_tests.sh tests/hermes_db/postgresql/test_matrix_crypto_store.py -j 1 -- -m integration --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml` exit1、1 failed（unified-task19-linux-pg-red.log）：真实SDK已导入、独立PG Schema归属/初始化已完成，失败为尚无hermes_db.matrix_crypto。没有DB网络阻塞、没有SQLite豁免、未读旧加密文件或操作远端设备。尚无本项完成commit。

Task19实施续记：新增0027共享迁移、按Profile/store+homeserver/user+device分区的9张Core表和generation护栏；完整39方法使用同步共享池，普通调用即借即还，SDK设备更新transaction由单线程执行真实事务/嵌套savepoint，取消后排队回滚并归还连接。时间及timedelta保留完整值；pickle之外的shared、ratchet、forwarding、TOFU及计数均持久。账号身份冲突拒绝覆盖，旧outbound session更新精确代次。adapter的旧SQLite启动移动到独立sibling，PG分支不创建SDK Database、不读取/删除旧crypto文件、不重置远端设备；新PG数据集遇到已有设备密钥拒绝，PG持久化失败在optional下同样中止。设备认证前后比较ed25519与curve25519。普通正式实例及配置数据保持原样。

阶段证据：真实Linux `scripts/run_tests.sh` 3个Matrix PG文件7 passed、0 failed/skip/retry（unified-task19-linux-pg-core.log）；真实SDK OlmMachine设备查询/发送与adapter启动两文件先5 passed/1 failed（unified-task19-linux-sdk-flows.log），失败为测试发送端群会话未设shared，收到forwarded key/请求取消此前已执行；已修正夹具，完整批次复验中。Windows标准runner 22个Matrix文件215 passed/1 skipped（unified-task19-native.log），唯一skip为既有test_matrix_voice因Windows未装mautrix；将到实际Linux SDK环境补验。首次Windows包装WSL argv把Resolution对象当字符串而TypeError，改用resolver.command后正常，属于启动包装错误而非业务测试结果。Task19仍in_progress，未创建本项commit；当前恢复点为新增进程恢复/无SDK SQL驱动合同、故障/取消/代次测试和全静态门禁。

Task19最终结果：已实现实际mautrix0.21.1 CryptoStore37方法和SyncStore2方法，共享Core/同步psycopg/池/预算/显式迁移0027；Profile/store、homeserver/user、device复合范围及dataset代次检查，全部领域操作命名化。PG adapter使用实际Client窄子类等待SDK handler，传播存储错误，业务成功后再持久游标，启动恢复使用已保存since；既有SQLite SDK流程独立保留。普通ensure_matrix_deps入口现按PG选择排除SDK asyncpg/aiosqlite依赖，不因二者缺失触发PM安装；实际连接仍检查加密SDK/libolm，不以optional降级。安装指导统一PM。正式实例、Profile配置、SQLite数据和旧Matrix文件均未修改；未管理数据库服务。

最新验证（全部标准runner，retry=0）：

- PM Linux SDK环境执行 `scripts/run_tests.sh tests/hermes_db/postgresql/test_matrix_crypto_store.py tests/hermes_db/postgresql/test_matrix_sessions.py tests/hermes_db/postgresql/test_matrix_devices.py tests/hermes_db/postgresql/test_matrix_sdk_flows.py tests/hermes_db/postgresql/test_matrix_adapter_storage.py tests/hermes_db/postgresql/test_matrix_recovery.py tests/hermes_db/postgresql/test_matrix_faults.py tests/hermes_db/postgresql/test_schema.py -j 3 -- -m integration --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml` exit0，8文件27 passed/0 failed/skip/retry（unified-task19-pg-final-clean.log）。每个业务过程拒绝全部SQLite，包括audit捕获别名/直接Connection；随机独立Schema归属校验后使用/清理。实际账号私有one-time keys从PG恢复并建立Olm会话、消耗后再持久；群组加解密、信任/TOFU/签名、重放竞争、真实事务/savepoint/取消/unknown COMMIT、重启及范围均通过，方法对应见协议矩阵。
- 实际新解释器禁止import asyncpg/aiosqlite、禁止所有SQLite连接、禁止因缺两驱动触发PM安装；普通依赖入口通过，恢复账号/同步/group并由实际OlmMachine加密，父进程重读确认次数增加。网络transport为本地受控回调，实际SDK各网络边界checkedout=0；未做公网Matrix服务联调，不声称端到端exactly-once。
- 同一PM Linux环境 `scripts/run_tests.sh <rg --files tests/gateway -g test_matrix*.py> tests/plugins/platforms/matrix -j 3` exit0，23文件219 passed/0 failed/skip/retry（unified-task19-linux-native-clean.log）。含实际SDK voice、SQLite adapter连接/加密重开；独立SQLite进程禁止SQLAlchemy/psycopg/Alembic导入，不要求PG实例。
- Windows原生标准runner最新4文件112 passed/0 failed/skip/retry（unified-task19-native-latest-source.log）；此前23文件215 passed/2 skipped，skip为Windows缺mautrix voice及Linux专有SQLite SDK合同，两者均已在上述实际Linux主机通过，不伪装OS。
- `PM Windows Python scripts/check --staged --base a0a5ffea8c` exit0，14 checks ok，health29文件0 blocking/advisory（unified-task19-checks-accepted.log）。PG SDK启动异常边界仅留一条具因health allow，捕获后关闭资源并仅记安全错误类型，避免密码学traceback泄密；最后独立review仍须复核。暂存差异检查后仅更新本执行账本、协议文档及EOF空行。

补充失败/修复记录：完整PG先22passed/1failed，子进程在no-install-project环境未显式PYTHONPATH；补传仓库路径后新进程恢复通过，Windows包装打印先GBK错误但实际恢复exit0（recovery-fixed.log），包装改UTF-8。真实SDK默认吞StorageError且不等加密handler已由sync-cursor-red实测失败，修复后adapter/recovery两文件5passed。普通依赖入口仍强制SDK SQL驱动的实测红（pg-sdk-dependency-red.log）后已按后端分流，最终禁止安装合同通过。扩大Linux原生回归先217passed/2failed：fresh-install fixture未模拟PM missing接口，实际SDK已安装时无法进入预期分支；ensure_matrix_deps在基线a0a5ffea8c及f5784617e8已有同一PM条件，已修fixture，3passed。指导改PM后旧pip文字断言1failed，按正确可执行命令更新后3passed。新增scope测试直接import yaml失败，改用项目hermes_yaml后5passed，无增依赖。最终27/219完整批次均通过。早期静态发现unused noqa、UTC别名、async阻塞subprocess、gather BaseException与sibling logger识别问题，已整改至14项全通过；未用规则豁免掩盖业务失败。Windows到Linux文件路径包装错误单列日志final.log，规范路径后最终批次执行正确。

未验证/恢复点：仅Task19协议/业务领域完成，Task20维护入口（包括此前Kanban/附件中断文件job和提交后投影）、Task21全入口审计、Task22完整系统普通daemon/Worker单后端、Task23发行/完整文档和Task24最终验证/独立审查仍未完成。不能以本项Schema ready或原会话测试推断全系统PG就绪。本项提交后立即进入Task20；不推送、不发布、不创建PR或合并。

## Task 20：消除生命周期、健康与运维旁路

状态：completed

### 目标

启动、诊断、备份、恢复与维护入口遵守同一选择，不再隐式打开自有SQLite。

### 涉及文件

- `gateway/lifecycle_ledger.py`
- `gateway/readiness.py`
- `hermes_cli/backup*.py`
- `hermes_cli/install_state.py`
- `hermes_cli/doctor*.py`
- `hermes_cli/approvals_suggest.py`
- `hermes_cli/session_recovery.py`
- `hermes_cli/worktree_ops.py`
- `apps/desktop/electron/updater/state-db-preflight.ts`

### 依赖与接口

- 前置：Task 3、Task 4、Task 7、Task 10、Task 14、Task 15、Task 17、Task 18、Task 19。
- 输出：所有系统管理路径已分流，缺文件不被当作PG无数据或应创建SQLite。

### 实施步骤

1. 按所有者矩阵逐项审计直连/文件存在性/SQLite物理修复；保留必要的SQLite模式工具。
2. PG启动和readiness检查完整域的版本/支持能力，明确显示后端；普通启动不建表。
3. 备份只承诺实际覆盖范围；安装状态/旧state.db取证等不能把PG读取失败降级为SQLite或空数据。
4. Desktop更新/导出/恢复进入后端能力接口；外部浏览器/用户SQLite文档与应用自有库严格区分。

### 验证方式

- 相关backup/doctor/readiness/安装探测及Desktop updater原生主机测试。
- PG在缺少本地state.db及所有独立DB文件时启动/诊断；故障明确上报，SQLite专用维护不触发PG模式本地写入。

### 完成条件

所有系统管理路径已分流，缺文件不被当作PG无数据或应创建SQLite。

### 执行结果

实施中，基线Task19提交90f82575b0。已按所有者矩阵核对lifecycle/readiness、install_state、approvals_suggest、worktree、backup/restore、doctor与Desktop preflight；会话阶段backup仅声明排除session，尚不足覆盖新的全部领域。已明确发现脏退出会探测遗留state.db/journal、安装证据和审批历史以state.db存在性判断无数据、worktree仍使用SQLite SQL/文件路径定位、Desktop直接-S运行SQLite snapshot。Kanban文件job/import/upload stage、中断token和提交后副作用及房间附件cleanup仍需实际维护入口闭合；未宣称这些已完成。

首批修改：增加driver-free导入的具名PG只读observations，消息存在性和审批历史按拥有Profile/store_id查询；安装探测PG故障按UNREADABLE处理，不伪造无使用数据；审批矿取复用真实危险分类/拒绝标记过滤，PG不因无本地文件返回空结果，--db异Profile文件明确SQLite-only。脏退出/deferred检查先选择后端，PG读真实Schema/会话状态，不对旧SQLite运行quick_check/journal；既有SQLite检查移到主题sibling，原patch seam保留。readiness故障仍报告选中backend和安全错误类别，不回落。

### 验证证据

`scripts/run_tests.sh tests/hermes_db/postgresql/test_profile_observations.py -j 1 -- -m integration --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml` 首次3 failed/1 teardown error：真实SQLite guard捕获legacy连接、缺文件造成消息/审批假空（unified-task20-observations-red.log）。实施后先2passed/1failed，修复新查询对既有tool_calls Text字段误作BYTEA解码；下一次2passed/1failed是测试用了普通git push而非实际危险命令，按既有classifier使用--force后exit0、3passed/0skip/retry（unified-task20-observations-classified.log），包括真实PG持久数据/跨Profile隔离和旧文件原样保留。

Windows原生4文件首次41passed/6failed/2skipped（unified-task20-native-observations.log）：approvals15和lifecycle10通过，install_state5项因主机无symlink特权失败（WinError1314），readiness健康fixture依赖宿主磁盘<90%而实际_probe_disk为93.3% degraded。未改宿主权限/文件/正式Profile；健康fixture改为明确给定健康磁盘观测，将在真实Linux补验symlink合同。Task20继续in_progress，尚无本项commit；下一恢复点是剩余运维/备份/工作树/维护job和补充故障合同。

Task20后续实施恢复点：工作树锁采用不含秘密的Profile/store/目标标记，旧db=字段在PG配置下拒绝SQLite探测并保守保留；TUI创建/恢复/退出均捕获拥有者。真实PG工作树2项通过（unified-task20-worktree-green.log）。原生GC13项曾失败，systematic-debugging证明机器Git autocrlf=true使fixture工作树在隔离Git配置下显脏；只固定测试仓库local autocrlf=false，GC27项全通过（unified-task20-native-gc-fixture-fixed.log），未放松生产Git安全隔离。quit/resume/retained-cwd/readiness另外26项通过。

Linux原生install/lifecycle/approvals/readiness共49项全通过（unified-task20-linux-observations.log），实际覆盖Windows缺权限的symlink和POSIX合同。备份增加所选后端策略、全Profile ZIP范围标记、quick覆盖清单及恢复前校验；PG历史库/sidecar不打开不导入，opaque用户db文件仍可恢复。初步6项PG备份恢复全通过（unified-task20-backup-restore.log），扩展自动ZIP/旧档案拒绝后8项通过（unified-task20-management-expanded.log）。Windows原生备份首轮91pass/6fail/1error/11skip：未关闭测试reader句柄妨碍Windows备份轮换、有限全局monotonic mock污染teardown、POSIX wrapper/路径/换行/权限假设。按原生路径API、实际源字节、独立topic时钟和显式close修正测试后97pass/0fail/11平台skip（unified-task20-native-backup-fixed.log）；真实Linux108pass/0skip（unified-task20-linux-backup.log）。

PM已在隔离task20-js-home/runtime供应Node26.12.1/npm12.0.2，并用canonical scripts/build/node-deps.mjs准备Desktop workspace（ignore_scripts、不安装Electron二进制、不启动桌面实例、无manifest变化）。Desktop6项首次5pass/1fail因原超时测试truncate100GiB触发ENOSPC；改为受控stat大小观测，实际新preflight下SQLite WAL、managed launcher协议和PG排除范围共6项全通过（unified-task20-desktop-preflight-fixed.log）。

维护第一轮4项红测记录unified-task20-maintenance-red.log；补齐owner-scoped maintain_profile、退休/import重放和workspace token续作后9项通过（unified-task20-maintenance-green.log）。扩展含真实新解释器的SQLite审计、跨ambient Profile、退休slug重建、25MiB upload实际回执恢复；4文件17pass/1fail（unified-task20-maintenance-expanded.log），唯一失败是新增档案测试调用内部签名错误，已修正。补充0028 outbox与数据删除后5文件26pass/1fail（unified-task20-management-expanded.log）：completion/回执恢复/备份均通过，数据删除3pass，Cron新fixture遗漏source参数1fail已修正；Core表删除顺序曾有kanban循环FK warning，已改按deferrable边排序。后续operations-final实测5文件24pass/0skip（含Schema0028、备份10、删除/doctor4、观察3和worktree2），无该warning。尚未将Task20标为完成，尚无commit。

后续补齐：附件删除只有unlink成功才释放token；PG准备文件使用带Profile/store/目标标记的独立generation，normal准备/SQL确认与维护共用文件门，未知COMMIT在新快照中对账。workspace token保存完整清理snapshot，任务行后来删除也能续作；import stage和worker chunk同样保留目标身份，切换数据集不清理旧文件。plugin TTL回收不删除namespace revision，room附件重放复用持久cleanup表。完成后的outbox保存冻结board/assignee/run，支持Board随后归档；活动图投影在归档后已过期，文件清理和observer仍以原代次处理。

首次扩展9文件40pass/4fail（unified-task20-lifecycle-complete.log）：已确认回滚后残留owner marker两项；新的全局文件门让并发metadata引用先等待OS锁而非立即命中SQL退休/删除栅栏两项。整改为准备代次补偿、门前只读快速拒绝+门内权威写栅栏后，cleanup-retest 5文件28pass/0skip，含真实PG未知COMMIT、下游ready、删除任务后的workspace恢复、房间blob中断、插件TTL revision及旧dataset文件保留。原生management 7文件61pass/1平台skip（unified-task20-native-management-fixed.log），此前一轮命令误用不存在的test文件名exit2已纠正，未将usage error计为验证。

元数据/配置矛盾ZIP与quick两个红测（unified-task20-backup-metadata-red.log）确认会把PG配置恢复成SQLite；已在写入前核对实际YAML，并延迟读取无关Native配置以保持逐文件原子失败合同。PG根下Native子Profile仍拥有旧shared-state.db的情况通过真实SQLite ZIP回环证明：该文件按Native子Profile归属保存/恢复，PG根旧state.db保持不打开不导入；元数据按各Profile选择登记。Windows最终backup/bytecode 3文件85pass/11平台skip（unified-task20-native-backup-accepted.log）。

Linux原生运维首轮8文件103pass/1fail/4skip（unified-task20-linux-management.log）：SQLite恢复CLI超时，独立faulthandler进程确认堵在启动bytecode sweep遍历.build中的PM SDK环境（unified-task20-linux-cli-probe.log），并非恢复SQL。已核对原意提交c4cf20f564：原本就排除venv/node_modules；新回归在未修复前证明工具runtime缓存被误删（unified-task20-bytecode-red.log），最小增加.build排除，Linux恢复12+范围回归1全通过（unified-task20-linux-recovery-green.log）。4skip是可选sqlite3 shell缺少sqlite_dbpage/.recover能力，核心损坏页range salvage与CLI已真实通过。未放大超时或禁用业务。

Desktop PM Node26原生Vitest6pass；tsc --build tsconfig.electron.json exit0（unified-task20-desktop-typecheck.log）。第一次静态63文件失败于BOM读取/超长facade净增/分派梯；逐项整改后14checks全部通过、0health阻断/建议（unified-task20-checks-refined.log）；新补充修改后还需最终重跑。当前待验证：最终14文件PG组合、真实Matrix SDK在0028下重启回归、Native Profile/serve归档，以及最终暂存区静态检查。恢复基线仍90f82575b0，未提交修改均为Task20；不得将局部通过当成全系统PG完成。

Task20最终结果：所列生命周期/安装/审批/工作树/doctor/备份/恢复/Desktop入口已遵守统一后端，PG不以本地库文件存在性判断数据，不进行SQLite物理取证/修复。维护与session retention开关独立；Kanban退休/import/workspace/附件/chunk和提交后outbox已有持久恢复协议；Profile数据删除先捕获身份，PG仅删除该store的系统表行，故障或未知提交保留本地文件。迁移head为0028，0001–0027未修改。正式实例/配置/数据保持原样，没有操作数据库服务或扩展，没有推送/发布/PR/合并。

最终PG命令（沿用前述PM解释器、私有配置和标准runner）：

```powershell
$task20PgFiles = @(
  'tests/hermes_db/postgresql/test_domain_maintenance.py',
  'tests/hermes_db/postgresql/test_management_storage.py',
  'tests/hermes_db/postgresql/test_backup_backend.py',
  'tests/hermes_db/postgresql/test_profile_observations.py',
  'tests/hermes_db/postgresql/test_worktree_storage.py',
  'tests/hermes_db/postgresql/test_schema.py',
  'tests/hermes_db/postgresql/test_kanban_workspaces.py',
  'tests/hermes_db/postgresql/test_kanban_board_files.py',
  'tests/hermes_db/postgresql/test_kanban_transfer.py',
  'tests/hermes_db/postgresql/test_kanban_artifacts.py',
  'tests/hermes_db/postgresql/test_kanban_worker_upload.py',
  'tests/hermes_db/postgresql/test_kanban_review.py',
  'tests/hermes_db/postgresql/test_kanban_completion.py',
  'tests/hermes_db/postgresql/test_kanban_command_receipts.py'
)
& $testRunner scripts/run_tests.sh @task20PgFiles -j 3 -- -m integration --postgres-test-config=$pgTestConfig
```

结果exit0、14文件71passed/0skip/retry（unified-task20-pg-final.log）。全部PG业务测试进程拒绝SQLite，包括真实新解释器恢复；实际SQL持久数据、同ID跨store、真实文件/25MiB chunk、丢失确认/回滚、中断恢复及配置retarget均有断言。删除retarget新增合同证明两store数据和本地文件均未被清除。

实际mautrix/Linux SDK环境的`scripts/run_tests.sh tests/hermes_db/postgresql/test_matrix_crypto_store.py tests/hermes_db/postgresql/test_matrix_recovery.py -j 2 -- -m integration --postgres-test-config=<同一私有配置>` exit0、3passed/0skip/retry（unified-task20-matrix-schema-regression.log），验证0028显式升级下真实CryptoStore私钥与新进程恢复，未借Windows缺SDK的skip代替实测。

原生Profile/serve命令`scripts/run_tests.sh tests/hermes_cli/test_profiles.py tests/hermes_cli/test_web_server_auto_archive_profile_config.py tests/hermes_cli/test_web_server_auto_archive_gateway_lock.py tests/hermes_cli/test_backup_storage.py -j 3`在真实Linux exit0、113passed/3 Windows平台skip（unified-task20-linux-profile-maintenance.log）。此前Windows管理61pass/1 POSIX skip、backup/bytecode85pass/11平台skip、Linux backup108pass、SQLite恢复补验13pass及Desktop6pass/tsc exit0均保留各自实际范围，不相加冒充完整系统计数。

最新`PM Python scripts/check --staged --base 90f82575b0` exit0、14 checks全部通过，health66文件0blocking/0advisory（unified-task20-checks-final.log）；最后文档状态更新另以git diff --cached --check核对。未验证项：本任务未运行完整daemon/全入口/独立发行验收，未完成最终独立code-review；对应Task21–24仍pending。可选sqlite3 shell的sqlite_dbpage/.recover及各原生主机平台skip照实保留，不据此扩大声明。恢复点：立即提交本Task20状态与代码，随后从Task21消费者调用图与旧test_surface_flow配置、普通kanban_full_gateway场景继续；实际Task20提交号在Task21起始记录。

## Task 21：闭合全部入口与直接 SQL 消费者

状态：completed

### 目标

CLI/Gateway/Web/TUI/Desktop/ACP/Agent及后台任务统一接入领域能力。

### 涉及文件

- `hermes_cli/web_routers/`
- `hermes_cli/main*.py`
- `gateway/session*.py`
- `tui_gateway/`
- `apps/desktop/`
- `acp_adapter/`
- `tools/`
- `tests/hermes_db/postgresql/test_unified_surfaces.py`
- `tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py`（Task 9提前建立、必须转绿的普通daemon场景）

### 依赖与接口

- 前置：Task 20。
- 输出：所有入口使用统一选择，PG错误没有本地/内存成功回落。

### 实施步骤

1. 按调用图清零未适配原生SQLite Connection/私有SQL消费者，不把仅数据库文件已替换当作完成。
2. 核对后台/线程/多Profile/外部worker的scope绑定、关闭和错误传播。
3. 保留恢复先于业务导入、提示前缀、表面协议和UI业务行为；不暴露数据库实现细节给普通用户流程。

### 验证方式

- 各入口原生主机回归与真实PG→Gateway/HTTP→Agent本机模型fixture流程。
- 跨Profile同ID、消息/工具/压缩/删除/重试、项目/Cron/Kanban/房间调用链及关闭重开。

### 完成条件

所有入口使用统一选择，PG错误没有本地/内存成功回落。

### 执行结果

Task21启动恢复点：Task20已在f0c6a6bcb6本地提交，开始时工作区干净。先核对旧test_surface_flow的storage.session fixture、普通kanban_full_gateway场景及已知直接SQL调用图；继续保留正式Profile/服务/SQLite数据，PG只使用私有配置下核对归属的随机Schema。不以部分入口或旧会话测试代替完整闭合。

首批结果：旧surface_flow基线2文件5pass/7fail（unified-task21-entry-baseline.log），embedded worker两Profile2项已通过，7失败是旧配置和旧房间SQLite边界。将surface fixture统一为storage.backend，并抽出可复用pg_sqlite_guard（connect/alias/direct Connection审计且捕获被吞错误）；配置改后9pass/1fail（unified-task21-surface-guarded.log），剩余旧合同明确要求独立SQLite，已按撤销边界替换为同PG/backend、持久owner、同ID隔离、epoch/服务重开合同。新测试曾误用不存在的get_room并已改用实际probe_hosted_room/room_state；最终surface+offturn 12pass/0skip/retry（unified-task21-offturn-surface-green.log）。实际普通gateway.run daemon场景已在不关闭房间/指标/插件下转绿1项（unified-task21-daemon-first.log），业务模型/worker argv、工具写入与重启使用原真实实现；Task22仍要扩展为全域完整验收。

实际代码缺口一：Board owner只比较store/board，两个归属已核对的独立随机Schema构造同store_id/default Board/同task ID，旧引用会跟随配置改指另一个数据集。红测unified-task21-board-retarget-red.log确认，修复为内部v2冻结target哈希、统一所有producer并将目标纳入claim请求ID；现owner_policy3项通过。进一步发现owner admission回执同样缺目标，且配置改回SQLite时先open_session_store再比较会触发SQLite；双Schema红测确认错误采用另一个终态，第二fixture起先因config写入遗漏字段被项目保护拦住，改为write_config_key后补验。生产回执增加target，typed PG evidence缺字段保留unknown；恢复先判断所选backend再打开，并核对target。owner recovery+policy现8passed/0skip（unified-task21-admission-retarget-green.log），保留原pending而不把另一个数据集的completed当作结束。

实际代码缺口二：idle-exit仍按kanban.db是否存在判断忙碌，更新回退检测会直连旧state.db。红测2fail/1teardown error被SQLite guard实际捕获（unified-task21-offturn-red.log）。已增加具名PG due Board观察，逐服务Profile绑定完整拥有者Scope；PG自动回退不走Native ledger/snapshot，forward保持通过。更新成功校验按PG Schema健康分流，未就绪明确返回未完成，不运行SQLite :memory:能力probe。PG offturn/owner/rpc/upload扩展4文件9pass/0skip（unified-task21-owner-offturn-expanded.log），原生idle-exit/downgrade4文件23pass/0skip（unified-task21-native-offturn.log）。设计已记录v2/unknown和PG回退边界，未改变正式SQLite协议/实例。

当前恢复点：Task21仍in_progress，无本task提交，基线f0c6a6bcb6；源码连接/SQL消费者清单存于忽略目录task21-sql-consumers.txt和task21-direct-connections.txt，不把ACP transport的_conn或Native实现SQL当作未适配数据库。已核对insights、analytics、session_search、spillover、update维护等已有PG具名分流；Profile初始化已由profile_storage.fork_storage_identity分配新ID，复用而非重写。待核对Profile rename下PG本机Kanban绝对文件路径/持久intent是否重定位（尚需实际复现，不凭搜索宣称缺陷），继续剩余Web/TUI/ACP/后台调用图、完整Schema下daemon及v2 worker回归；本task尚未做最新静态门禁，不得标完成。

后续实际复现：新增test_profile_file_scope.py通过真实profiles.rename_profile移动独立Profile（所有宿主服务适配器被测试边界替换，不操作正式实例），PG guard下确实完成目录/alias/现有identity流程，但task.workspace_path仍是before旧home，附件也存旧绝对路径；红测1fail（unified-task21-profile-rename-red.log）。已将本机文件引用重定位/中断日志/发布顺序写入设计，尚未实施。下一恢复点是此缺口，不能用跳过rename或仅改测试期望完成Task21。当前其余最新owner policy+admission恢复8pass、offturn/surface12pass、原生offturn23pass；待路径重定位后再做整组回归和static，最后按本task提交。

路径重定位已实施：profile_file_moves在同一profiles目录的文件锁内记录无秘密的home/store/target操作日志，PG目录改名前标记新Profile不可发布，短Core事务重定位明确列、workspace主键/引用/cleanup snapshot、owner policy和文件job，离开SQL后原子重写自身数据集的私有文件标记，成功后才发布并删除日志；旧SQLite直接目录rename保持原协议。基础实库改名1passed（unified-task21-profile-rename-gated.log）；数据库不可用/确认丢失/文件中断重试及cleanup重放首轮5pass/1fixture失败（unified-task21-profile-rename-recovery.log），失败来自未发布Profile正常配置写入被tombstone保护拦住，测试已改为模拟管理员直接编辑现有文件，未绕开生产保护。后续整组入口7项路径合同已通过，尚待最新fixture整理后复验。

当前未解决：最新10文件入口回归中普通daemon1项、embedded worker2项超时（unified-task21-entry-final.log），其余入口/投影/owner/RPC/路径测试通过；不能使用早先daemon通过覆盖本次失败。已为超时追加脱敏worker/owner日志（不扩大timeout、不停功能），由systematic-debugging定位。静态首轮发现测试fixture导入shadow及无效noqa，修正后14检查通过、health20文件0blocking/advisory（unified-task21-checks-final.log）；诊断测试新增后须重跑。原生Windows Profile套件8项为POSIX权限、symlink特权或shell文件名假设失败，另pwd导入失败；正在真实Linux环境运行对应4文件，未伪装OS或改宿主策略。Task21保持in_progress，无本task commit。

最终闭合：脱敏诊断日志unified-task21-daemon-diagnostic.log显示submitter被owner以invalid_params拒绝，实际wire contract的KanbanBoardOwner仍Literal[1]且不允许target；不是模型慢或PG池问题。将契约同步v2+必需target并重新生成TypeScript/OpenRPC后，真实普通daemon、embedded同/不同执行Profile、交互worker和改名恢复4文件11passed。补充owner admission同ID但target改变的不可变红测1fail/2pass（unified-task21-admission-identity-red.log），实际Core admit_claim原比较遗漏target，现同时比较backend/store/target/principal/session/request/home；修复后owner policy/recovery+普通daemon3文件9passed。没有扩大timeout或停用功能。Profile路径7合同同时验证真实PG持久化、同Schema不同store不改写、三种中断恢复、配置改指拒绝、cleanup fence保留与重放。

最终恢复点：Task21完成，按本task创建本地commit，随后开始Task22完整域单进程/子进程业务矩阵。Task22必须补足全域同时运行、跨进程重启和SQLite无PG依赖证明；本task入口证据及此前各域证据不能替代它。Task23发行/文档和Task24最终独立审查尚未实施。正式Profile、配置、SQLite数据和PG业务表未改。

### 验证证据

- PM Windows解释器统一经`scripts/run_tests.sh`，PG参数均`-m integration --postgres-test-config=<私有文件路径>`、retries=0，独立随机归属Schema且PG业务进程SQLite全拒绝。
- 10文件全入口首轮38pass/3fail（unified-task21-entry-final.log）；失败为上文已复现修复的wire v1/v2。其余8文件覆盖surface_flow、surface_projections、unified_surfaces、owner policy/recovery、worker RPC/interactive及profile_file_scope。
- `scripts/run_tests.sh tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py tests/hermes_db/postgresql/test_kanban_worker_e2e.py tests/hermes_db/postgresql/test_kanban_interactive_worker.py tests/hermes_db/postgresql/test_profile_file_scope.py -j 2 -- <PG参数>`：11passed/0skip，退出0，unified-task21-workers-wire-green.log。
- `scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_owner_policy.py tests/hermes_db/postgresql/test_kanban_owner_recovery.py tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py -j 2 -- <PG参数>`：9passed/0skip，退出0，unified-task21-owner-daemon-final.log。
- 原生Windows生成契约、canonical wire和适用Profile回归3文件76passed/2平台skip，退出0，unified-task21-native-wire-rename.log；过滤完整POSIX专属测试类的同一原生全量Profile合同在真实Linux4文件127passed/3Windows skip，退出0，unified-task21-linux-profile.log。首轮Windows误选POSIX全量测试的8失败及pwd导入失败保留在unified-task21-native-profile.log，Linux实机通过不伪装Windows支持symlink特权；Windows新增PG改名7项无skip。
- 更新/idle-exit原生4文件23passed（unified-task21-native-offturn.log）。使用已由PM准备的Node/TypeScript对生成契约`--noEmit --strict --skipLibCheck --target ES2023 --module ESNext --moduleResolution Bundler`退出0（unified-task21-contract-tsc.log）。
- PM解释器`scripts/check --staged --base f0c6a6bcb6`：14检查通过，health23文件0blocking/advisory（unified-task21-checks-accepted.log）；`git diff --cached --check`退出0。最终仅补写本账本，随后创建本地commit。

## Task 22：建立单后端运行强验收

状态：completed

### 目标

用运行证据证明PG模式不依赖任何应用自有SQLite数据库。

### 涉及文件

- `tests/hermes_db/contracts/test_single_backend.py`
- `tests/hermes_db/postgresql/test_single_backend.py`
- `tests/hermes_db/postgresql/conftest.py`
- `tests/hermes_db/postgresql/test_unified_surfaces.py`

### 依赖与接口

- 前置：Task 21。
- 输出：不是通过禁用功能/伪装OS/内存替代达到零SQLite；每个域都有业务与隔离证据。

### 实施步骤

1. 在PG业务隔离子进程拒绝所有SQLite连接，包含内存库与URI；不能只检查.db文件、只按Profile路径过滤或读源码。
2. 从空Profile与新PG Schema运行完整功能矩阵，包含指标/插件及后台操作；外部SQLite文档/浏览器读取在另一个明确的文件输入测试进程验证，不给业务运行进程开豁免。
3. 双store、双Board、双插件、双进程竞争和故障注入；同样验证SQLite模式不需要PG驱动或实例。

### 验证方式

- `scripts/run_tests.sh tests/hermes_db/contracts/test_single_backend.py`
- `scripts/run_tests.sh tests/hermes_db/postgresql/test_single_backend.py -- -m integration --postgres-test-config=$pgTestConfig`
- `scripts/run_tests.sh tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py -- -m integration --postgres-test-config=$pgTestConfig`；房间端口化后必须转绿并扩大为普通daemon重启恢复，禁止以嵌入式owner合同替代。
- 预期所有自有SQLite连接尝试为0，且各功能的真实业务结果、持久化和重启恢复全部成立。

### 完成条件

不是通过禁用功能/伪装OS/内存替代达到零SQLite；每个域都有业务与隔离证据。

### 执行结果

从Task21提交17078105be的干净工作区恢复，新增共享业务探针和Native/PG验收入口：同一解释器依次运行会话/Projects/验证证据/Cron执行、incident、notepad、delivery/双Board任务、run、comment、附件/房间事件和附件授权/指标/双插件KV与Discord；PG同进程另运行真实RetainDB writer的失败持久待发与实际mautrix/Olm SDK加解密，再运行各域维护。两个Profile使用同Schema不同store与相同会话/房间/插件键，写入后退出解释器，新的解释器以反向Profile顺序重读，RetainDB实际重放同一冻结消息，Matrix恢复原身份、同步游标、群组密钥并再次通过SDK加解密。测试文件只记录随机业务ID和公共加密见证，不存读取替代；断言均来自实际领域API和PG。

SQLite业务探针主动拒绝sqlalchemy/psycopg/alembic/asyncpg导入，真实各域数据库写入后由新解释器恢复，RetainDB同样走真实SQLite队列重放。PG审计用sys.addaudithook捕获别名、URI、内存库和直接Connection构造；独立正向控制实际尝试4种入口全部被拒绝。PG目录fixture升级为autouse，吞错或后台线程尝试仍使测试失败；整个联合业务进程不提供SQLite豁免。用户SQLite文档读取在另一个独立文件输入子进程验证只读内容与文件hash，不给PG业务进程开例外。

首轮Native1pass/1fail、PG1fail均是测试指标resource使用无效taxonomy，实际_validate_counter正常拒绝；改为项目client_resource映射，不改变生产校验。修正后Native2passed（unified-task22-sqlite-second.log）、真实SDK Linux全域双Profile重启1passed（unified-task22-pg-second.log），均退出0。正在运行包含新文件输入合同的Native完整3项，以及PG15文件联合/故障/并发/普通daemon矩阵和静态门禁；尚未结项，不外推为全系统最终ready。

最终结果：PG15文件首轮41pass/8fail，8项都是文件启动的旧fixture在no-install-project环境缺少明确源码路径（ModuleNotFoundError分别为gateway/hermes_cli/plugins/hermes_db，unified-task22-pg-acceptance.log），不是业务SQL失败。共享child_env保留系统白名单且显式pin当前checkout，不继承任意PYTHONPATH；全矩阵重跑49pass/0skip/retry（unified-task22-pg-accepted.log）。最新报告按真正完成的调用登记10领域及Profile数量，PG新进程SQLite连接数均0、无吞错见证；更新后的联合进程+原Matrix恢复2pass（unified-task22-pg-final-process.log）。

SQLite SDK细化与真实证据：上游mautrix SQLite类确实从asyncpg导入UniqueViolationError，直接禁止该类型依赖的首轮SDK补验1fail/3pass（unified-task22-native-sdk.log）；未伪造SDK类或改生产依赖。SDK专项允许真实asyncpg异常类型，但禁止其connect/create_pool，继续禁止SQLAlchemy/psycopg/Alembic；普通SQLite核心专项仍禁止全部四类导入。SDK实际创建SQLite数据库、保存Olm账号/群组密钥/同步游标，退出后新解释器恢复并通过实际OlmMachine再次加解密；Linux最终4pass/0skip（unified-task22-native-sdk-final.log）。没有PG实例或PG连接。Windows共同合同与普通启动4pass/2明确Linux专属skip（unified-task22-windows-final.log），未伪装OS；实际SDK全域PG/SQLite证据来自已核对的Linux环境。

恢复点：Task22验收完成并立即按任务创建本地commit。后续Task23必须从本地提交导出独立载荷、PM环境离开开发源码导入路径验证全部域和迁移；Task24仍须完整原生回归、最终verification-before-completion及独立code-review，不能据本task声明READY_TO_MERGE。正式实例/配置/数据库服务未动。

### 验证证据

- 全部Python验证经`scripts/run_tests.sh`，PG仅私有配置路径和核对归属的随机Schema，retries=0。
- Linux PM：`scripts/run_tests.sh tests/hermes_db/postgresql/test_single_backend.py tests/hermes_db/postgresql/test_transaction_failures.py tests/hermes_db/postgresql/test_cron_executions.py tests/hermes_db/postgresql/test_plugin_storage_process.py tests/hermes_db/postgresql/test_metrics_process.py tests/hermes_db/postgresql/test_room_attachment_concurrency.py tests/hermes_db/postgresql/test_retain_queue_process.py tests/hermes_db/postgresql/test_retain_queue_transactions.py tests/hermes_db/postgresql/test_matrix_faults.py tests/hermes_db/postgresql/test_matrix_recovery.py tests/hermes_db/postgresql/test_discord_recovery_process.py tests/hermes_db/postgresql/test_kanban_command_receipts.py tests/hermes_db/postgresql/test_kanban_tasks.py tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py -j 3 -- -m integration --postgres-test-config=<私有配置>`：49passed，退出0，unified-task22-pg-accepted.log。覆盖池耗尽、实际断连/语句取消、COMMIT确认丢失、精确回执、双进程CAS/配额/计数器/终态、205条Retain重启及完整daemon模型工具和重启。
- 同Linux环境最新`test_single_backend.py test_matrix_recovery.py -j 2 -- <PG参数>`：2passed，退出0，unified-task22-pg-final-process.log。所有PG测试进程自动SQLite全拒绝；完整业务子进程包含双Profile与10领域。
- Linux PM：`scripts/run_tests.sh tests/hermes_db/contracts/test_single_backend.py -j 1`：4passed/0skip，退出0，unified-task22-native-sdk-final.log，包含实际SQLite Matrix SDK、完整共同业务、拒绝PG服务连接、四类SQLite审计正向控制、独立用户SQLite文件只读hash。
- Windows PM：`scripts/run_tests.sh tests/hermes_db/contracts/test_single_backend.py tests/gateway/test_normal_runtime_boot.py -j 2`：4passed/2Linux专属skip，退出0，unified-task22-windows-final.log；SDK专属项在上述Linux真实执行。
- PM解释器`scripts/check --staged --base 17078105be`：14检查通过、health10文件0blocking/advisory，退出0，unified-task22-checks-final.log；`git diff --cached --check`退出0。仅本账本完成记录随后补写，立即本地commit。

## Task 23：完善统一配置文档与独立发行验证

状态：completed

### 目标

用户通过一种配置选择完整后端，安装载荷和迁移资源能独立工作。

### 涉及文件

- `website/docs/user-guide/postgresql-session-storage.md`
- `website/docs/developer-guide/`
- `docs/designs/postgresql-storage-code-layout.md`
- `tests/hermes_db/test_distribution.py`
- `tests/hermes_db/postgresql/test_distribution_initialization.py`

### 依赖与接口

- 前置：Task 22。
- 输出：文档与实现一致，两种独立安装模式可用，完整域迁移资源和真实初始化通过。

### 实施步骤

1. 更新全局config.yaml示例、.env秘密边界、模块范围、初始化、池预算和新数据集规则。
2. 从实际代码提交导出独立source-bundle，PM构建有PG和无PG两套环境，离开开发源码导入路径验证。
3. 独立载荷显式初始化所有域、重复升级、实际写读、跨OS进程重启和store隔离；不伪装非支持的发行构建。

### 验证方式

- `scripts/run_tests.sh tests/hermes_db/test_distribution.py（显式传两套PM解释器和独立载荷参数）`
- 独立PG初始化测试使用私有配置文件路径，执行全部域/版本/资源验证；不把密码放进argv或日志。

### 完成条件

文档与实现一致，两种独立安装模式可用，完整域迁移资源和真实初始化通过。

### 执行结果

从Task22本地提交2219b69afd的干净工作区开始。文档已改为Profile统一后端范围，补全所有领域、插件portable边界、Matrix实际SDK/Linux限制、PG文件备份与数据库备份区别、故障/未知提交、pool预算、稳定store_id及新数据集/不双写规则。CLI示例加入全局storage块，.env.example只保留秘密引用说明；新增开发指南并更新架构、所有权和会话入口，旧代码布局文档明确归为历史、链接当前实际实现，不重写旧研究或旧计划。

从实际提交2219b69afd经git archive导出无.git/秘密的独立载荷，通过pm.build_environment(frozen=True, explicit=True)分别构建Windows和Linux的SQLite/PG共4个新环境。Windows载荷位于.build独立目录，Linux另解包到/tmp/hermes-unified-matrix-5bb7b10a96b1/task23-source-2219b69afd，两个Linux环境均包含项目锁定Matrix extra，SQLite环境没有postgreSQL extra。没有原环境覆盖、裸pip/uv或数据库服务操作。构建状态路径仅保存在忽略目录task23-{windows,linux}-bundle-state.json；源码恢复依据是已提交ref，秘密不在载荷或argv。

安装探针用-I、在载荷/checkout之外的临时目录启动，先验证installed hermes_db位于独立source且原checkout不在sys.path，再加载该提交内导出的业务测试驱动。PG初始化及业务全程SQLite拒绝；显式核对目标数据库及随机Schema归属标记后，升级新Schema、重复升级、全部域真实写读、双Profile反序新进程恢复以及真实Matrix SDK加解密均通过。通用PG资源探针去掉旧版无条件SQLite写入，验证完整领域注册表与迁移资源；SQLite安装确认无psycopg并在禁止PG依赖/连接下恢复真实业务。

已修复两个验收fixture问题：Linux旧安装测试将venv解释器resolve为基础Python而丢失安装，首轮5pass/1fail（unified-task23-linux-distribution-first.log），改为保留解释器绝对入口后6pass；补充旧PG 0004有历史数据的前向升级时，首轮手工插入普通UTF-8字节被消息envelope校验正确拒绝（unified-task23-upgrade-diagnostic.log，previous-history-read/Invalid message content envelope），现用实际PostgresSessionStore API在0004保存合法提示/历史，再升级0028并在新进程验证保真。Windows该补验已1pass/1Linux skip（unified-task23-windows-forward-upgrade-final.log），最新Linux全组及最终静态复验运行中。

文档站是独立npm项目，初次误当根workspace的依赖准备被边界校验拒绝，未改根node_modules。改用PM install_node_sidecar按website自身package-lock准备，再用PM Node26.12.1/npm12.0.2执行build:fast，英文生产站构建退出0（unified-task23-website-build-final.log）。保留输出中的llms.txt/llms-full.txt索引资产缺失及其他页面两处锚点告警，不将其说成无告警全站发布；新数据库用户/开发页面实际生成HTML，已读取确认标题与内容。没有发布网站。

最终结果：最新Linux6项全部通过、0skip/retry，包含有效旧PG历史前向升级、新Schema重复升级、双Profile/完整SDK重启；Windows独立双安装通用4项通过/2Linux SDK skip，最新旧PG前向升级补验另1pass/1Linux SDK skip。静态14检查通过。两处其他页面锚点已用git diff a875342384 --quiet核对，与会话基准内容相同；保留为站点既有告警，不掩盖或修改它们。Task23完成后立即本地提交；Task24最终原生回归、verification-before-completion、独立审查及整改复验仍未执行，不据此声称READY_TO_MERGE。

### 验证证据

- 构建：从ref2219b69afd git archive的独立载荷，通过PM build_environment构建4个全新环境；Windows两环境输出unified-task23-windows-pm-build.log，Linux两环境输出unified-task23-linux-pm-build.log，均退出0。SQLite无postgreSQL extra，Linux两环境有实际锁定Matrix SDK。
- 两主机统一`scripts/run_tests.sh tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/test_distribution_initialization.py -j 2 -- -m 'integration or not integration' --postgres-test-config=<私有路径> --hermes-distribution-source=<独立载荷> --hermes-sqlite-python=<PM独立SQLite解释器> --hermes-postgresql-python=<PM独立PG解释器>`：Windows4passed/2Linux SDK skip、退出0（unified-task23-windows-distribution-first.log）；Linux最新6passed/0skip、退出0（unified-task23-linux-distribution-accepted.log）。每次-I子进程的CWD在载荷及checkout之外，断言原checkout不在sys.path，实际包位于独立source。
- Windows最新同参数仅test_distribution_initialization.py：1passed/1Linux SDK skip、退出0（unified-task23-windows-forward-upgrade-final.log）；该版本先在真实0004创建合法提示和NUL历史，前向升级0028后重开仍保真，不导入SQLite。Linux最新六项包含同一版本该合同。PG全部SQLite拒绝；10领域业务与Matrix SDK均实际读写及重启。
- PM Node/npm、website自身锁文件，`npm run build:fast`（cwd website）退出0，unified-task23-website-build-final.log；源码目录之外未部署/发布。实际HTML用户与开发两页存在并包含新标题；初次沙箱中PM Python基解释器访问被限制，改用PowerShell原生只读核对成功。站点保留两条索引资源链接和两个不相关历史锚点告警（上述基准diff退出0），本次数据库页面链接无错误。
- PM解释器`scripts/check --staged --base 2219b69afd`：14检查通过、health4代码文件0blocking/advisory，退出0，unified-task23-checks-final.log；`git diff --cached --check`退出0。随后仅补写本账本完成记录并立即本地commit。

## Task 24：原生启动复验、最终验证与独立审查

状态：in_progress

### 目标

按统一目标判定交付状态，留下可审计结果和本地恢复点。

### 涉及文件

- `docs/plans/unified-database-backends-plan.md`
- `docs/reviews/unified-database-backends-review.md`
- `tests/hermes_db/`
- `受审查整改影响的实际源码/测试`

### 依赖与接口

- 前置：Task 23。
- 输出：全部必需域和单后端验收通过、无未处理blocking/major且独立审查APPROVED才READY_TO_MERGE；其他情况保留真实失败与未验证任务。

### 实施步骤

1. 在隔离PG测试Profile完成原生启动、全模块健康、受控业务写读和排空重启；当前正式Profile不在开发阶段被切换。
2. 执行verification-before-completion：记录真实PG/SQLite/入口/构建/静态/安装/故障及所有跳过、失败。
3. 使用code-review做高风险独立审查，整改后复验；每个完成任务本地commit，不推送/发布/合并。
4. 承接会话阶段剩余适用平台验证和波动记录；缺证据时标BLOCKED/FAILED，不把新计划创建或会话835项通过当作全系统完成。

### 验证方式

- `scripts/run_tests.sh tests/hermes_db`
- `scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config=$pgTestConfig`
- `scripts/run_tests.sh tests/cron tests/hermes_cli tests/gateway tests/tui_gateway tests/acp_adapter tests/plugins tests/agent tests/tools（按依赖/原生平台分批并读取完整汇总）`
- PM解释器运行 scripts/check；适用的生成契约/TypeScript/发行检查；原生重启前后核对backend、revision、代码版本。

### 完成条件

全部必需域和单后端验收通过、无未处理blocking/major且独立审查APPROVED才READY_TO_MERGE；其他情况保留真实失败与未验证任务。

### 执行结果

已启动最终验证和三份独立代码审查（见docs/reviews/unified-database-{foundation-operations,collaboration,plugins-acceptance}-review.md）。独立审查复现：Profile删除确认后重新解析配置可误删peer store（blocking）；PG Bot Chat/定向Cron房间/原生及Desktop群聊入口残留SQLite路径假设；Kanban附件别名误删、完成file_job阻断后续生命周期、拒绝claim缺少原事务回执；实际Matrix SDK吞掉存储异常后推进游标及并发Olm快照导致消息无法解密（major）。全部保持未整改/待复验，不用已有绿测抵消。

整改决定：删除流程在确认前冻结target与root路由数据集（包括SQLite），实际写入从冻结settings/scope取得并核对handle；live mux核对已持有routing_db身份并回传匹配token，旧handler忽略token不能计成功；target本地身份由随后整store删除覆盖。该改动收紧原设计的删除确认合同，不扩大功能或改数据迁移边界。其余整改继续沿用类型化资源、原子回执与真实SDK协议，不重新规划。

当前整改实现（尚待最终门禁）：受约束删除使用新的purge-profile-identity-checked verb，旧网关unknown verb拒绝发生在任何写之前；PG与SQLite的root/target均冻结，实际资源按冻结settings/scope打开。Bot Chat按所选session_store存在性而非文件探测；定向Cron从解析至发布绑定目标完整scope；native groups使用location_root，Desktop本地handler按目标完整scope读取并核对服务ref。附件使用规范path_key计数/锁，全store活引用和null引用保护cleanup，旧raw alias和pending token继续可对账；Board已完成import/archive允许后续退休，待清stage仍阻止切换。claim、heartbeat、failure、block/schedule及request_changes事务内拒绝均有原子回执，completion audit同时记录CommandRefusal。另新发现phantom prose审计遗漏PG分流会卡住outbox，现补具名Core审计和同run/payload幂等，需永久复验。

Matrix整改按实际mautrix 0.21.1协议：get_sessions/get_latest_session仍每次真实PG读取核对generation，但共享同一可变Olm Session对象；异步gate和显式SDK transaction采用同一顺序，保存失败/取消包括等待gate时使旧ratchet明确不可继续，不能更换已被排队SDK捕获的对象。handler checkpoint保留SDK内部吞掉的StorageError，包含SDK transaction的COMMIT错误；sync batch等待所有解密后派生handler完成再推进游标。PG存储失败通过已有adapter fatal/retry supervisor请求完整重连、重建SDK对象并读取持久游标，不在同一poisoned store中每5秒无限重试或保持虚假connected。没有修改远端设备、添加数据库服务或扩大外部exactly-once声明。

### 验证证据

所有Python测试仍经scripts/run_tests.sh、retries=0；真实PG仅核对归属的随机Schema并全拒绝SQLite。最新红测：test_review_foundation_profile_delete.py 1failed；test_review_foundation_room_routing.py 1failed；test_cron_bot_delivery.py 2failed（unified-task24-bot-chat-red.log）；Reviewer群聊/附件/生命周期/回执共7个实际PG场景失败；真实Linux Matrix SDK两例失败（review-matrix-key-request.log）。命令、边界和原始见证详见三份review。

第一轮全PG目录结束：test_domain_schema.py 1fail、test_health_archive_refs.py 2fail、test_startup_requirements.py 1fail，另test_retirement_rewrites.py未收集完成，日志unified-task24-full-pg-first.log；旧session配置/旧Matrix unsupported断言及PG进程直接开SQLite输入与新合同不符，须修为有意义的当前合同再重跑。Windows contracts批次3个文件4fail，另private_launch文件未执行测试，日志unified-task24-windows-contracts-first.log。Linux原生宽回归仍运行；ACP fixture setup有超时，独立取栈显示Git/文件复制/Path.resolve冷启动接近40秒边界，同fixture单进程34.27秒ready，尚无基准A/B，不能据此归为既有问题或增加timeout。非WSL POSIX私有启动页7项仍缺适用主机，已向用户询问现有执行入口；没有收到主机信息。

补充精确汇总：首轮全PG为103文件569passed/4failed/1error、退出1，1625.5秒；retirement_rewrites已执行17个case后触及runner默认300秒文件cap，非零测试收集。后续显式--file-timeout1200仅为完整多case实库文件提供总预算，不增加业务deadline/重试。Windows修复后删除/Bot Chat2文件3pass（unified-task24-delete-bot-first-fix.log）、房间/协作原始红测2文件8pass（unified-task24-collaboration-first-fix.log）；Matrix真实Linux3文件11pass（unified-task24-matrix-first-fix.log）。独立foundation追加11pass、Matrix原两例加四项补查均pass，分别见新增foundation-operations-followup-review与matrix-followup-review；它们保留全局CHANGES_REQUIRED，不替代本任务全回归。

永久化复验：第一次foundation-kanban批次缺显式-m，只有Native14pass且实库case被默认marker排除，不能计为PG证据（unified-task24-foundation-kanban-regressions.log）。修正显式-m 'not live'的8文件实际72pass/1fail、退出1（unified-task24-foundation-kanban-selected.log）；唯一失败为新SQLite输入子进程未设置独立USERPROFILE/HOME，现已补隔离home，待回归。其余通过包括永久11项删除/混合路由、实际PG房间授权与FIFO同连接及确认丢失恢复、schema完整能力与真实缺Matrix表拒绝/零startup DDL、5项扩展要求、Kanban任务/回执/审查。旧“PG+独立SQLite房间”合同已改为纯身份合同，实际业务改由test_hosted_submission_receipt.py及已有真实test_surface_flow/test_room_coordination证明，未放宽SQLite guard。

静态首轮14检查失败于两处未用测试变量、两个新增SDK边界的BLE001；变量已更正，边界说明按项目health规则记录任务排空/秘密安全原因，尚待最新重跑（unified-task24-checks-first-fix.log）。当前正跑unified-task24-collaboration-recovery-regressions.log和unified-task24-matrix-recovery-final.log；不得提前计成功。宽原生回归仍有ACP setup和若干业务deadline失败，必须读取完整汇总、按相同原生条件复现/核对基准，不能用旧阶段835项或局部绿色覆盖。

整改恢复点验证：上述协作7文件69pass/0fail/退出0，包含修正独立输入home后health全部35项与既有附件/Board退休/主完成事务真实COMMIT丢ACK文件保留；closure-edges五文件14pass/0fail/退出0，包含真实server capabilities通过所选open_run_store短期acquire/close、零SQLite和两类completion audit+CommandRefusal原子重放。Matrix最新Linux6文件17pass/0fail/退出0（Native single_backend被integration marker排除，不计新Native证据），包含永久真实SDK并发/派生handler/取消/重开/受控supervisor回调；独立新增实测真实Gateway重连队列、取消carrier及has_session读中poison两项pass，正常tests曾因混用-p重复注册零收集，不计业务失败，正在单独补验。

Native最新：Linux10文件145pass/0fail/5平台skip、退出0（unified-task24-native-profile-delete.log）；Windows群聊8文件初次58pass/3fail，修正后60pass/1fail（unified-task24-native-groups-accepted.log），剩余为附件路由测试0.4秒lease因文件/CPU耗时自然过期。该合同只验证文件传递，现使用已有注入clock固定测试时间，不增加production或业务deadline；连同独立租约失效套件和Windows持文件句柄删除七文件复跑53pass/0fail/2平台skip、退出0（unified-task24-native-files-leases.log）。两个原FakeService已提供真实选择的db_path；Native允许同home显式state.db/shared-state.db，PG服务仍精确匹配捕获ref。

最新静态：scripts/check --staged --base 3febe6fc31全部14检查通过，55个Python文件health 0blocking/0advisory（unified-task24-checks-accepted.log）。前两次静态的ruff未用探针变量及重构后BLE001已整改，四个保留的异常边界有明确health原因。三份独立follow-up均记录所列blocking/major关闭及本范围绿测，但总体保留CHANGES_REQUIRED；宽回归目前仍运行且有失败，非WSL POSIX七项主机仍缺。为重建包含整改的新发行载荷，将创建明确标注Task24仍in_progress的本地恢复commit；不是Task24完成提交，不能据此将24/24或全系统PG标完成。

恢复提交前追加两项独立发现并已红绿整改：真实gateway→scheduler的投递wrapper先按SQLite文件存在性返回，PG持久队列从不排空（unified-task24-cron-gateway-red.log）；坏YAML在执行账本backend解析时抛出ParserError，绕过run_job失败tuple（unified-task24-cron-config-red.log）。投递行为已抽至scheduler_delivery_queue sibling，保留facade transport/通知补丁缝，只对Native无文件快返；配置读取将YAMLError/OSError转为仅含拥有者路径的StorageConfigurationError，执行身份准备失败明确返回失败tuple，不启动模型、不读SQLite。最新PG队列全文件7pass/0fail（unified-task24-cron-delivery-accepted.log），同ID peer保持pending、目标实际送达并重开读取、send不持连接；坏配置原生窄测1pass/0fail（unified-task24-cron-config-accepted.log）。中间名为green的混合命令因状态术语queued/pending及给非hermes_db文件传PG自定义参数而失败/零收集，保留原日志，不计通过。独立配置边界3pass及源码复审记录在cron-consumers-followup-review，Matrix永久7pass+监督器实证2pass记录在matrix-supervisor-followup-review，均不扩大总体门禁结论。

恢复提交静态终验：scripts/check --staged --base a875342384退出0，全部14检查通过、完整分支547个Python文件health 0blocking/0advisory（unified-task24-all-branch-checks.log）；git diff --cached --check通过。局部整改恢复提交标题为`fix(storage): close unified backend review gaps`，Task24仍in_progress、整体FAILED，剩余全域/发行/平台任务照旧。原生宽回归跨整改版本运行，结果仅作为缺陷发现依据，不能当作某个固定新提交的最终验收；接下来在已有Linux的独立本机文件系统checkout中按冻结恢复提交重跑，避免/mnt/d源代码I/O争用，继续保留所有初轮失败和未验证项，不调大业务deadline、不伪装OS。

冻结验证恢复点为实际本地提交`58d0003f83d1c99505e1173508ea7e2934d89411`。已从该ref重新导出Windows/Linux无.git及秘密的独立source-bundle，经PM构建SQLite/PG四个全新环境，构建日志unified-task24-{windows,linux}-pm-bundles.log均退出0；新载荷的Windows独立安装/升级2文件4pass/2Linux SDK skip（unified-task24-windows-distribution-final.log），Linux同两文件实际6pass/0skip，包含在下面冻结PG总批次内。继续使用-I、载荷外CWD、installed源码归属及双Profile新进程逆序读回；SQLite环境不含PG extra，Linux两个环境均有锁定实际Matrix SDK，PG进程全拒绝SQLite。四套状态只存忽略目录task24-{windows,linux}-bundle-state.json。后续目前只有测试/诊断及账本变化，未改该冻结提交的生产实现，不将旧2219载荷当作本轮代码。

Windows最终核心普通合同：`scripts/run_tests.sh tests/hermes_db -j 3 --file-timeout 1200 -- -m 'not integration and not live'`并传新独立安装参数，212文件573passed/0failed/3平台skip，退出0、907.9秒（unified-task24-windows-core-final.log）。PG目录在该批次按integration排除，进度估算不是实库执行数量。Windows真实PG文件范围补验3文件19pass/0skip（unified-task24-windows-pg-file-scope.log），覆盖Profile改名、附件规范路径及file_job，仍归属校验随机Schema、SQLite guard。PM Node运行生成契约strict/noEmit TypeScript及Desktop Electron noEmit检查均退出0，PM Python `scripts/gen_gateway_contracts.py --check`退出0；Desktop预更新备份Vitest实际22pass/0fail，退出0（unified-task24-{contract-tsc,desktop-typecheck,generated-contracts,desktop-preflight}.log）。无构建部署或正式服务变更。

冻结58d的Linux全PG+独立发行批次已完整结束：`scripts/run_tests.sh tests/hermes_db/postgresql tests/hermes_db/test_distribution.py -j 3 --file-timeout 1200 -- -m 'not live' --postgres-test-config=<私有文件> --hermes-distribution-source=<58d独立载荷> --hermes-postgresql-python=<新PM解释器> --hermes-sqlite-python=<新PM解释器>`，113文件654passed/4failed/0skip，退出1、1945.9秒（unified-task24-frozen-pg-and-distribution.log）。失败为maintenance两项故障注入、Matrix sessions一项及跨Profile embedded Worker结果回执30秒超时。其余全部通过不抵消这四项；普通daemon场景不符合自动test_文件名，仍须显式执行。

maintenance旧夹具无条件在首个write的真实COMMIT后丢ACK；整改引入的completion前置写使其尚未命中声称的主完成事务。现捕获真实repo.event(kind='completed')对应同一Connection，仅在该事务真实COMMIT并归还连接后注入UnknownCommitError，回滚不会注入；父done/子todo→ready、另一Profile触发维护、hook恰一次及归档workspace清理断言全部保留。Windows全文件10pass/0fail（unified-task24-maintenance-confirmation-final.log），独立Reviewer窄复验2pass/0fail（unified-review-maintenance-ack-independent.log），均退出0；复核及原失败保留在collaboration-followup-review。本次只修正测试，不改变生产事务。

Matrix sessions失败来自测试在store重开并读取loaded_inbound后，继续提交旧store的独立inbound对象；新的真实SDK并发整改正确拒绝替换活动ratchet。测试现让两端均使用重开的对象完成真实加解密、保存，再第二次重开验证加密时间和双向消息。实际Linux SDK/PG全文件4pass/0fail、退出0（unified-task24-matrix-sessions-corrected.log）；独立Reviewer同一项1pass/0fail、退出0（review-matrix-sessions-corrected-single.log），已记录matrix-followup-review，未放松合同。Worker超时只补测试所有者与worker脱敏日志，不提高业务deadline、不放松回执/clean-exit/重启断言；相同实际Linux环境独立全文件2pass/0fail、退出0（unified-task24-worker-result-diagnostic.log），但未稳定复现原失败，不能将其写成根因已解决。

冻结58d的独立本机文件系统checkout正在执行八个原生目录完整宽回归，日志unified-task24-frozen-native-areas.log，尚未有完整汇总。compression deterministic fallback出现一项时序失败；相同环境依次在a875与58d checkout独立窄跑各6pass/0fail（unified-task24-compression-{baseline,head}.log），不能据此将完整批次失败隐藏或宣称根因已确认。原/mnt/d宽回归跨多次整改版本、还有大量ACP/时序失败，不再是最终证据；核对其runner cwd/确切脚本及父子进程归属后，只停止该runner及11个测试子进程（unified-task24-superseded-run-stop.log），保留原始partial日志，不记完整退出或成功，未影响正式实例或冻结新批次。

仅测试合同及脱敏诊断修正的静态门禁：PM解释器`scripts/check --staged --base 58d0003f83`全部14检查通过，3个Python文件health 0blocking/0advisory，退出0（unified-task24-test-contract-checks.log）；git diff --cached --check通过。随后只补账本与独立复审记录并保存本地恢复commit；Task24仍in_progress。生产代码及58d四套发行载荷未变，新冻结测试快照将重跑完整PG与显式普通daemon联合合同，不以局部pass替代完整结果。

上述测试恢复commit为`d402ff3a06b15c45a150eb2459191bfc5a4a7e22`，新独立checkout状态记录于忽略目录task24-pg-corrected-state.json，没有更换仍运行中的58d Native checkout。新冻结PG命令在前述完整目录/新安装参数基础上显式加入`tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py`，共114文件、retries0、-j3/--file-timeout1200，日志unified-task24-corrected-pg-and-daemon.log，仍运行，当前结果不得计完整通过。相同新checkout的`contracts/test_single_backend.py -j1`已实际4pass/0skip/退出0、11.5秒（unified-task24-sqlite-sdk-final.log），包含真实SQLite Matrix SDK、全域双Profile及新解释器恢复、禁止PG服务、SQLite guard正控制和单独输入进程。

原生Windows最新显式`scenarios/kanban_full_gateway.py test_kanban_worker_e2e.py test_kanban_interactive_worker.py -j2 --file-timeout1200 -- <PG参数>`：3文件4pass/0skip/退出0、111.9秒（unified-task24-windows-daemon-workers.log），普通gateway.run daemon、同/跨执行Profile worker、交互入口、实际工具写入、持久回执及重启均通过，进程SQLite全拒绝。不据此删除前次Linux全量的Worker超时记录。

冻结Native宽回归随后新增shutdown_interrupt两项失败，当前共3fail、尚无完整汇总。独立Reviewer确认第二项多余mark来自前一barrier失败测试的same-job/old-owner线程，前一测试在barrier.wait(2)失败前没有finally release/join，存在跨测试污染；第一barrier为何超时仍缺线程栈。以原deadline顺序在a875/58d执行同文件各25pass/0fail（review-foundation-shutdown-{baseline,head}-ab.log），不能将窄跑绿写成失败已解决或归为既有问题。新增观察和未验证边界已补foundation-operations-followup-review，未改Agent核心、业务deadline或全局门禁。

新d402完整PG/独立发行/显式daemon批次现已真实结束：114文件336passed/0failed/325errors，49文件非零、退出1、681.9秒。maintenance全部10项、Matrix sessions全部4项、同/跨Profile embedded worker两项及普通daemon均已在此批次通过；约58%开始的metrics_store、messages准备/清理首先报FATAL database system is in recovery mode，后续49文件大量连接失败，不能宣称完整PG通过。随后在Windows和Linux分别以已有私有测试配置，只读SELECT current_database/pg_is_in_recovery核对；两边都在建立连接时OperationalError/recovery_mode、退出2（unified-task24-pg-readiness-{windows,linux}.log）。不打印连接秘密、不操作服务；已异步请求用户在其管理的服务恢复后告知，当前原因未查明，不擅自归因。只提取本日志的两个随机Schema候选至忽略目录task24-interrupted-schema-candidates.json，归属标记未能核对、未清理；恢复后仅能在核对测试数据库与该候选拥有者标记后清理，不能枚举删除其他Schema。

不依赖PG的整改继续：仅观测探针在d402独立checkout导入原compression/shutdown合同，保留原deadline并在超时记录无局部变量的线程栈，31pass/0fail（unified-task24-timing-stack-probe.log）、退出0，未复现原失败，导入探针不计为原文件完整隔离验收。已给原shutdown barrier测试增加finally release Event/abort Barrier/join全部实际启动线程，保留2秒rendezvous/join、全部owner及registry断言；只在原BrokenBarrierError输出无局部变量的faulthandler栈并重抛。Windows原文件25pass/0fail、退出0（unified-task24-shutdown-cleanup-windows.log）；独立Reviewer确定性barrier失败/owner断言失败两项证明原异常仍抛、线程退出及清理全执行（review-foundation-shutdown-cleanup-default-stack.log），复审接受此测试修正，但不能据此宣称首个barrier超时根因解决。生产实现未变。

冻结Native宽回归另新增command_discovery一项：daemon比legacy多出/sdlc-review bundled skill（原delta tuple为daemon值/legacy值，先前账本将方向记反，现按真实断言纠正），当前已有4fail。独立同条件A/B正在核对，未提前归为既有问题或backend缺陷，未改技能/缓存/提示前缀。新增总审查汇总docs/reviews/unified-database-backends-review.md把三份原独立发现及增量复审、当前范围/命令/结果、PG恢复模式和平台缺口逐项关联；明确该文件由实施Agent汇总，不冒充尚未执行的独立全局终审，保持FAILED/CHANGES_REQUIRED。

线程清理与汇总恢复前静态：PM解释器`scripts/check --staged --base d402ff3a06`全部14检查通过、1个Python文件health 0blocking/0advisory，退出0（unified-task24-shutdown-cleanup-checks.log）；git diff --cached --check通过。之后只补写实际依赖中断、复审与执行结果，不改变已检查的测试代码。本地恢复提交后需在新的独立Linux checkout复验原shutdown文件，仍保留58d Native宽回归失败和原deadline，不改变生产实现。

线程清理/审查汇总恢复commit为`66a987c9ea2a0e7914c77526e6792b79c72e72b0`。新独立Linux checkout实际运行原`tests/cron/test_shutdown_interrupt.py -j1 --file-timeout1200 -- --tb=long`，25pass/0fail/退出0、3.7秒（unified-task24-shutdown-cleanup-linux.log），与Windows25项及独立两条确定性失败清理见证对应，不解释首个原超时。58d八目录Native宽回归没有被更换或重启。

用户通知PG服务已恢复后，第一次双主机探测仍不可连接，脱敏服务端明细为not yet accepting connections/Consistent recovery state has not been yet reached（unified-task24-pg-restored-diagnostic.log）；未立即重启宽回归。随后只读探测在Windows/Linux均验证current_database匹配独立测试配置、pg_is_in_recovery=false（unified-task24-pg-readiness-after-recovery-wait.log、unified-task24-pg-ready-linux-confirmed.log），退出0。对日志中两个随机Schema候选，在单事务先核对数据库、当前角色owner及hermes-pg-tests唯一标记，全部核对后只删除其中仍存在的一项，另一项已经不存在，退出0（unified-task24-interrupted-schema-cleanup.log）；忽略目录manifest已记checked/dropped/absent，没有删除其他Schema或既有业务表，没有管理数据库服务。

已在冻结66a独立checkout重新启动同一114文件完整PG/发行/普通daemon批次，retries0、-j3、--file-timeout1200、-m 'not live'，其余私有配置及58d生产载荷/双PM解释器参数与d402批次一致，日志unified-task24-pg-after-service-recovery.log。66a仅多测试清理与文档，生产代码仍为58d；完整结果尚未返回，不计通过。原d402的336pass/325errors及恢复前失败全部保留，服务可连接不等于这批业务已验收完成。

新增Native证据与整改决定：冻结宽回归新增arrival-order paused的原3秒both-kept超时，以及hot-profile原control结果没有parked键，两项使当前观察到的失败达6。arrival-order仅观测原用例1pass/0fail（unified-review-native-arrival-observation.log），未复现/未取到失败时栈，不归因资源或既有问题。hot-profile独立原用例head/baseline各1pass；随后只对本测实际持有的daemon注入invalid-hot首个真实serve的文件门闩，保持handler原5秒等待，a875/58d均取得真实pending回复，释放后真实park/unserve完成，但原测试仍精确KeyError红（review-foundation-hot-profile-pending-{baseline,head}-red.log）。历史ae601a7632/2919595040已明确允许慢刷新后台继续、返回pending；不能把正常pending当handler错误，亦不能声称已取得冻结当次reply。

据此只修测试的异步合同：rescan请求仅发送一次；立即完成仍校验原parked列表；明确pending=true时按本文件已有的20秒eventual publication窗口轮询真实identify，要求精确parked集合及所有目标实际withdraw后才继续。无pending且无parked仍失败，不合成预期reply，不增加生产5秒等待或业务deadline、不停功能，保留真实park/unserve及gateway_state断言。生产实现保持58d。新增docs/debug/unified-database-final-regressions.md关联原失败、反证、未验证因果及下一观测；总门禁仍FAILED，不以fixture修正盖过其他失败。

恢复后的完整PG结果已读取：冻结66a同一114文件批次659passed/0failed/0errors/0skipped、退出0、1276.2秒（unified-task24-pg-after-service-recovery.log），包括完整PG目录、独立发行/显式升级及实际普通gateway.run daemon；实际Matrix SDK、原维护确认丢失/重开ratchet/跨Profile Worker四项全过。自动SQLite guard和业务子进程guard全程开启，池/并发/故障/双store/真实持久化/新进程逆序恢复均按各文件原合同执行，没有功能禁用、重试或SQLite豁免。58d生产source-bundle双PM解释器参数不变，生产代码经diff核对仍相同；后续变化仅测试/诊断/文档。旧58d四失败及d402服务恢复325errors完整记录仍保留。该完整绿色PG门禁不替代仍运行且已有失败的Native宽回归或非WSL七项主机证据，也不提前改变FAILED/23项计数。

独立cache反证已写foundation followup：a875/58d均在真实CLI inventory临时发布窗口令普通find_all_skills看到Kanban-only条目，但同窗口scan_skill_commands及恢复后的get_skill_commands都再次正确过滤；不能解释原daemon多出/sdlc-review。该底层列表既有minor保留两版本red及历史意图证据，本轮延后单独修复，不扩大数据库后端生产范围，不关闭原command discovery差异/RPC超时。arrival-order原paused单用例观测1pass，成功stdout未保留原始JSON，根因仍未知，详见native-admission-arrival-order-observation.md，不把缺失字段写成已观察事实。

hot-profile新helper独立真实正向门闩1pass/退出0（review-foundation-hot-profile-pending-positive.log及旁置observation.json），两原场景各仅1次rescan；第一请求原5秒返回pending后，新helper先见真实空parked，再自行轮询到实际park/withdraw；第二终态也实际完成，全部原业务/状态文件断言保留。整7文件在Root/mnt/d窄验为6pass/1fail、退出1、489.5秒（unified-task24-hot-profile-async-contract.log），原invalid-hot用例已过，失败为另一create-profile场景的start_daemon原90秒仍starting、尚未调用新helper；该非零记录保留，不调大期限。当前新静态首轮因Windows GBK无法编码检查输出而退出1（unified-task24-hot-profile-contract-checks.log），改用PYTHONUTF8=1及PM Python -X utf8重跑完整14检查，日志unified-task24-hot-profile-contract-checks-utf8.log仍运行，不计通过。为在实际Linux文件系统完整复验，将保存明确Task24仍in_progress的测试/调试恢复commit再创建新native checkout；不是完成提交。

冻结Native宽回归另出现managed-compress[False]在HISTORY_9普通turn terminal原30秒超时，尚未到实际compress操作，当前已观察7fail。独立只读诊断将捕获本测真实worker/admission及拥有者日志，不凭文件名或低并行绿测猜根因。除正在改的测试合同外，生产代码仍保持58d，不以完整PG659绿测抵消这些Native失败。

上述测试/调试恢复commit为`dcb0e7df59df0e644e6def1157332a2bda2b7394`，不是Task24完成提交。首次快照参数误填为不足10位引用，被工具在创建前拒绝；随后直接从git rev-parse HEAD读取完整ref，新独立Linux checkout（task24-hot-profile-checkout-state.json）保持该ref的实际测试源码。原`test_multiplex_hot_serve_live.py -j1 --file-timeout1200 -- --tb=long`完整7pass/0fail/退出0、222.1秒（unified-task24-hot-profile-native-filesystem.log）；原启动90秒、控制5秒未变。Root/mnt/d此前6pass/1个启动失败的日志保留，不把切换文件系统本身当作原启动延迟已定因；当前受影响文件复验全过。

UTF-8完整静态输出已读：14项中13项通过，唯一no-tmp失败是新调试文档写死Linux临时根；health该测试文件0blocking/0advisory（unified-task24-hot-profile-contract-checks-utf8.log）。现文档改为引用实际task24状态文件，未添加规则豁免；只重跑受影响`check --staged --only no-tmp --base 66a987c9ea`为1check ok/退出0（unified-task24-debug-path-check.log）。原测试代码与完整14项执行时的blob c4c46a7bf2bafcab33a782036dee1fd302ca6d22一致；不冒称第一轮14项命令退出0。全分支最终统一检查留待总验收收敛时复核。

managed普通turn独立单次带观测原False用例1pass/退出0、106.3秒（review-native-managed-compress-observed.log），原17次terminal等待均保留30秒、实际两个daemon周期及后续压缩/配置冻结/owner/worker排空/重启断言全部执行。原故障点HISTORY_9此次4.1002秒，最长HISTORY_15为24.9360秒；实际没有触发timeout现场采样，不能归因CPU/模型/锁/启动/结算或称已修复。独立报告unified-database-native-managed-compress-observation.md及原失败一并保留，不重复轰跑争取绿色。当前只剩58d八目录Native宽回归仍在执行；其7个失败信号并未因局部通过全部闭合。

宽回归继续揭示实际新问题及工具前提：config_read_guard明确命中backup_database_policy.validate_config的归档字节yaml.safe_load，未通过配置owner。此处必须验证归档自身的原始backend，不能换成当前Profile的defaults/overlay/ENV或把归档写入临时config再读。整改决定：在现有config_backend增加纯raw document解析入口，FileBackend与归档均复用同一既有fast-safe loader；不访问live backend、不增加存储后端或恢复路径、不改变矛盾metadata/坏内容的fail-closed规则。补原始BOM/环境字面值/坏内容秘密安全合同；原架构guard红及真实PG/Native备份合同均须复验。此为Task24原owner边界整改，未扩展统一数据库设计。生产代码将不再与58d字节一致，旧659全绿只对应此前冻结版本；新生产恢复commit后须重建独立载荷并复验相关当前代码，不能自动继承旧结果。

其他新增CLI准备错误已由独立工具审计区分：Node/npm未在Linux准备，既有PM uv0.13.5已验证但不在测试PATH；desktop/setup/plugin相关错误不是业务已通过。Root将仅通过PM在新的隔离store准备锁定Linux Node26.12.1/npm12.0.2，明确加入已verified工具PATH后复跑受影响文件，不修改仍运行的58d环境。MiniMax loopback Connection reset及safe_mode request_failed分别保留，不能归入缺工具。当前Native仍未完整结算，新增失败/错误以最终汇总为准。

新增已确认major：safe-mode原完整合同在a875通过、58d失败，独立实际owner栈定位session.create/resume展示信息在owner_scope之外调用Projects，重新解析被明确忽略的损坏live YAML；尚未进入worker。新增真实PG双Profile红测也实际取得foreground project而非owner project。整改仅把普通可选Project查询放到既有owner_scope内；ignore_user_config策略不查询该附加标签，实际会话仍使用已持有的持久store，不改storage fail-closed、不以冻结agent默认值改选SQLite。原PG bypass新测在创建时更早触及routing重新解析坏配置，尚未命中inventory，不能计为目标红测；调整为先真实创建持久会话，再损坏配置并调用真实snapshot_info，单独保留新建routing需要有效storage配置的边界。完整safe-mode原合同及普通PG隔离/持久化/重开均须复验。

Linux隔离PM工具准备已实际结束：uv0.13.5、Node26.12.1、npm12.0.2版本核对通过，状态task24-linux-tools-state.json；下载SSL失败重试及最终成功保留在unified-task24-native-tools-pm-preparation.log。原58d宽回归环境未被修改，当前仍运行，已观察44 failed，最终setup错误及失败分类必须读取完整汇总；先前7fail为当时进度而非最终数量。

另一当前major已按原真实remote plane合同复现：fresh Profile仍在隐藏staging目录时，fork_storage_identity无条件向配置backend解析该临时home，remote backend正确拒绝非法Profile home，导致创建失败（unified-task24-remote-profile-red.log，1fail）。后续独立同条件A/B及git show证明a875会话基础已有此问题，f874e6be49为其祖先，不归为本24项计划新增；因它直接阻断当前Profile身份创建仍在本轮收敛。既有远端配置明确不允许文件clone，fresh没有复制的storage身份或本地config需要fork；远端最终Profile配置继续由其backend管理。整改沿用既有profiles_config的supports_file_tooling边界，只有实际拥有本地配置文件的backend执行复制身份拆分，不为staging伪造远端Profile、写远端配置或回落SQLite；本地PG clone的独立store_id及file owner合同仍须复验。此处不改变运行时统一后端选择。

当前PG inventory永久合同已实际3fail→3pass，退出0（unified-task24-inventory-target-red.log / unified-task24-inventory-owner-green.log）。独立foundation复审未发现新增blocking/major，明确两项bypass只证明既有持久会话的snapshot、再次取得handle及peer隔离，不声称关闭owner后的跨进程恢复或损坏storage配置下新PG session.create成功；原完整CLI/worker safe-mode合同待新快照。归档原始配置合同Windows48pass、实际PG备份10pass，独立同合同48pass及真实ZIP/quick拒绝发布11pass；局部复审archive-config-document-review通过，整体仍CHANGES_REQUIRED。remote Windows全文件99pass/6fail，fresh已过；其他六项为dotenv/plane-home合同，尚未核对主机前提或基线，完整日志unified-task24-remote-profile-green.log保留，不能把该名称当全绿结果。

Linux实际PM工具补齐后29文件完整复验424pass/0fail/0error、退出0、251.9秒（unified-task24-native-tools-recheck.log），仍58d冻结源码、原deadline、retries0；覆盖原缺工具的Desktop/source/TUI/web构建及plugin install/update/consent/guard等，具体完整文件列表保留在runner日志。没有改原宽回归环境或给生产增加工具特判。test_update_finish两项后经独立追栈也属缺Node，另由Reviewer在相同已验证工具环境单独复验，不将原failed吞掉。

冻结58d的八目录原生宽回归已真实结束：6412文件62870passed/44failed/220errors/726skipped，49文件非零（1个import/collection），退出1、10578.9秒（unified-task24-frozen-native-areas.log）。只读runtime observer在核对原runner身份后自动记录terminal并退出0，没有管理/重启/终止该runner；全量失败保留。除了已实际424项工具补验，Photon三文件还需已核验Node环境，FAL collection缺锁定fal extra需通过PM新环境补验；不能把220errors当成业务已执行。独立后段报告unified-database-native-late-failures-review记录7项A/B在a875/58d均红的归属，不将既有问题自动抵消当前失败。

Achievements三个失败已由独立保留原断言的观测定位为替身缺实际SessionDB必有的db_path；当前只在测试factory按实际打开参数填充db_path，不动生产storage_identity或统计/partial持久化合同，须复验原文件。Windows本地Profile identity+profiles两文件批次为101pass/8fail/4skip（两个store/file身份clone用例通过）；其余包括symlink权限及POSIX壳/环境合同失败，unified-task24-profile-identity-fork.log保留，拟在新Native冻结快照完整复验，不假称Windows完整通过。最新完整静态首轮14项仅ruff冗余fixture alias失败、health552文件0问题；删除冗余alias后单独ruff退出0，最终完整检查将再次执行。

独立MiniMax诊断已给出实际原socket及单变量TCP反事实：测试Handler未消费95字节POST即关闭，客户端仍open且只收到13032<16384字节便RST；仅读完请求体则完整响应+EOF。生产OAuth和原测试在a875/58d均无diff，不修改生产吞ReadError。当前仅补测试Handler按Content-Length消费body，保留真实socket、15秒HTTP边界、16KB截断及全部错误文本断言；原红、基线/窄绿和诊断首版自身失误均保留在native-oauth-update-finish-observation.md。update_finish补工具实际14pass/2skip，缺esbuild/TypeScript/Vite的两个真实构建仍未验证，不能记16pass。

当前Achievements原全文件Windows6pass/0fail/退出0（unified-task24-achievements-fixture-final.log），只修测试factory身份属性。新PG测试fixture改为pytest_plugins复用实际既有fixture，以消除冗余alias/参数遮蔽，不更改业务断言；完整静态第二轮因该遮蔽及独立报告临时根字面值而失败，均按规则修正，未加豁免，须最新复验。

当前整改恢复提交前最新验证：`scripts/check --staged --base a875342384`全部14检查通过，554个Python文件health0blocking/0advisory、退出0（unified-task24-owner-checks-accepted.log）；保留此前两轮真实失败。Windows配置/归档/本地PG身份clone/MiniMax真实HTTP/Achievements五文件72pass/0fail、退出0（unified-task24-owner-contracts-final.log）；pytest_plugins复用fixture后实际PG inventory仍3pass/0fail、退出0（unified-task24-inventory-plugin-fixture.log）。Linux补PM Node的Photon三文件16pass/0fail/0skip、退出0（unified-task24-photon-tools-recheck.log）。另通过PM新建单独含锁定fal extra的测试环境成功，未修改原full环境，业务测试尚待。将保存本地恢复commit以建立新冻结验证点，Task24继续in_progress，不是完成提交；完整原safe-mode/remote/备份与新发行载荷门禁仍待。

新生产恢复点为`8d6f7bdaebf8fc1749d155a455bbb2730d492ae3`（fix(storage): preserve configuration owner boundaries），Task24仍in_progress。新独立Native快照task24-owner-checkout-state.json已核对完整ref；Root22个受影响配置/Profile/remote/备份/恢复文件正运行unified-task24-owner-native-regressions.log，独立Reviewer另跑原完整safe-mode合同，尚无完整汇总，不计通过。Linux新PM fal环境的原真实SDK文件38pass/0fail/退出0（unified-task24-fal-sdk-recheck.log），实际SDK及HTTP叶子合同已执行，补齐原collection缺项。

同一8d6生产提交的Windows/Linux SQLite/PG四套全新PM独立发行环境均已构建成功、退出0，日志unified-task24-{windows,linux}-pm-bundles-8d6f7bdaebf8.log，状态task24-{windows,linux}-bundle-8d6f7bdaebf8-state.json；旧58d载荷/环境保留。构建成功尚不等于新安装/全域业务通过，待当前Native受影响文件完整结算后，使用这套新参数复验完整PG/显式daemon及安装合同。

新8d6快照受影响Native回归已真实结束：22文件415pass/0fail/3个Windows平台skip、退出0、115.6秒（unified-task24-owner-native-regressions.log），包括原配置guard2项、remote实际plane全部105项、本地Profile全部108项/身份拆分2项、完整备份/恢复、MiniMax16项及Achievements6项。另独立原完整safe-mode合同仍1fail/退出1、89.63秒（review-foundation-safe-mode-owner-accepted.log）：前面的普通sentinel、safe one、坏YAML safe two及文件保持均通过，最后ignore-user-config仍保留插件发现的阶段发现worker打开测试Profile的.env（原line252审计断言失败）。原Projects/inventory原因局部闭合不等于完整合同通过；该新增现场正在独立捕获实际.env读取栈，未归为既有/时序、未改原断言或放宽秘密边界。最新生产全域PG复验暂不重启，先收敛这一真实失败，避免用即将过时的发行载荷反复验证。四套8d6载荷已保留且尚未宣称业务通过。

8d6完整safe-mode末阶段的新major已有实际owned worker审计栈（review-foundation-safe-mode-owner-env-observed.log，1fail/16.49秒）：conversation_loop→lifecycle→relay_shared_metrics.observe_lifecycle→consent reconcile→storage_backend→_owning_profile→build_profile_secret_scope→load_env_file。a875原完整合同此前已通过末阶段；本轮不是靠重试猜时序。原因是新PG consent guard在原disabled/no-file短路前探测backend，而selector在读取冻结worker快照之前先hydrate .env。整改仅让已绑定的worker快照选择直接走现有effective loader与_backend校验，避免附加secret scope构建；正常owner有效配置/真实PG acquire/秘密/稳定scope全部保留，不关闭config-only插件或指标、不让agent默认配置重选owner既有store。补真实新解释器、两种backend/三种冻结策略的文件audit与禁PG driver导入合同，先红后绿，再原完整CLI及实际PG指标复验。

冻结backend探测永久新解释器合同已实际6fail→6pass（unified-task24-frozen-selector-red.log / unified-task24-frozen-selector-green.log），覆盖SQLite/PG与普通/ignore/safe三个真实绑定策略；audit拒绝Profile config/.env打开，import hook拒绝PG驱动。后者与原选择/指标/备份共5文件171pass/0fail/1个POSIX平台skip、退出0、23秒。真实owner PG指标六文件20pass/0fail、退出0、45.6秒（unified-task24-frozen-selector-pg-metrics.log），包含新进程、HTTP、故障、双Profile及disabled lifecycle consent；不外推为managed worker指标通过。

独立metrics-worker-snapshot-followup-review确认窄修保留同一冻结loader结果和正常owner MetricsRef/PG acquire；同时发现此前未覆盖的两个关键静态交界：默认bypass worker快照缺storage、PG Profile保留旧metrics.sqlite3时可能进入SQLite分支；普通PG managed worker的指标域获取会被owner-only拒绝，尚未找到转发消费者。这些不是已执行红测，已请求独立实际PG daemon/managed worker+模型+启用指标的持久/重开/peer隔离与遗留SQLite反例，不能用owner20项证明它们完成。真实复现后必须沿明确owner持久通道解决，并将原因/影响写回设计与Task24，不放宽guard、不取消指标/生命周期、不以agent默认快照替代持有store身份。

冻结selector窄修本地恢复门禁：`scripts/check --staged --base 8d6f7bdaeb`全部14检查通过，2个Python文件health0blocking/0advisory、退出0（unified-task24-frozen-selector-checks.log）；不把局部health2文件写成完整分支555文件已检查。随后保存明确Task24未完成的本地恢复commit，下一步新快照执行原完整CLI合同；新发现的managed PG指标范围仍等实际反例，未标完成，不重建最终发行载荷。

51b3新冻结原完整safe-mode CLI独立复验已1pass/0fail、退出0、96.1秒（review-foundation-safe-mode-selector-accepted.log），原test blob及期限/断言未变；关闭此前Projects inventory与selector额外.env读取两个局部major，不能外推PG managed指标。

新的实际PG联合证据确认必要功能缺口，当前全局仍FAILED：普通启用指标的真实worker模型已完成、scope/peer正确且SDK真实加载，但采集开启后的_get_runtime→capture_metrics被owner-only拒绝，PG模型指标为0；config-only同Profile保留旧指标SQLite时实际尝试连接该文件，被严格guard拒绝。独立最终负例准确在SQLite-attempt断言红，早先业务/aux计数观测误差全部保留在metrics-worker-snapshot-followup-review。另一实际write_file→turn-stop链两次verification领域获取受同一guard拒绝，PG状态空；RetainDB正常初始化的PG队列也被拒绝，最终模型成功不能当作记忆工作。Projects经真实GUI/CLI可达性核对目前是owner消费者，不据不可达CLI工具泛报。

设计补充及整改决定已写入unified-database-backends.md“指标与插件”：保留owner-only，先补闭合的owner数据集身份/领域读通道，再以现有worker.persist受保护outbox和同Connection Core回执承接相同Profile领域短操作，首项修verification，再接RetainDB与指标。数据集身份独立于agent默认快照；不接受Worker自选DSN/Schema/Profile/store_id，不添加任意SQL RPC。外部HTTP、文件导出及发送保持事务外，必要回执在execution.finish前排空。该补充纠正原Task2/3/15/18局部owner验证未覆盖的实际消费者，不新增任务数、不撤销功能或放宽SQLite验收；Task24持续整改，旧659/owner20项均不代表这些新路径通过。

verification首步实际结果：新Core合同第一次因测试表名导入失误为collection error（unified-task24-worker-domain-core-red.log），修正后真正2fail（worker-domain-core-target-red），再与原workers/verification合批3文件21pass/0fail/退出0（worker-domain-core-first）。独立复审随后用未来cutoff真实删除同store foreign state/events，作为新增major保留red；现已移除worker时钟/清理/配额参数，owner在同一回执事务生成，普通owner API自定义参数保留。永久Core2项与独立反向1项分别通过（worker-domain-policy-green、unified-review-worker-domain-retention-green），含真实业务SQL后回滚、实际COMMIT丢ACK、原序号重放、同ID peer隔离、拒绝跨会话/任意SQL/保留策略伪造。

真实消费永久化：Windows原普通daemon→采用worker→模型write_file→PG证据→退出→新owner恢复→peer空已1pass（managed-verification-first）。扩为普通/ignore-user-config的首批1pass/1fail是默认关闭验证功能后没有证据的测试前提错误，保留managed-verification-accepted.log；config-only现通过已有公开HERMES_VERIFY_ON_STOP启动override显式opt-in，不改生产开关/断言/guard。最新永久两项2pass/0fail/0skip、退出0、106.3秒（unified-task24-managed-verification-opt-in.log），每个owner进程连接预算1。独立Linux普通1pass46秒、config-only1pass62.3秒（worker-domain-first-fix-review），实测默认snapshot_backend=sqlite而实际证据在owner PG；此前“默认snapshot字面缺storage”的额外观测误判已纠正并留原日志，未计生产失败。

原生证据/停止/保留/FD/缓存及worker读线程8文件90pass/0fail/3平台skip、退出0（unified-task24-worker-domain-native-evidence.log）；SQLite独立全域/新进程恢复+统一选择2文件8pass/0fail/1 Linux SDK skip（worker-domain-sqlite-independent），PG导入/服务拒绝保持。当前暂存首步`scripts/check --staged --base 51b3e61c6c`全部14检查通过、11个Python文件health0blocking/0advisory（unified-task24-worker-domain-checks.log），准备保存明确Task24未完成的本地恢复commit；独立worker-domain-first-fix-review关闭本通道及retention问题，RetainDB和metrics已实证的worker major仍保留，整体CHANGES_REQUIRED。

最新恢复提交为`c0558e9c1365afb95406431b7a05c74c60525bf4`，verification owner receipt通道已提交；其全新Linux冻结快照三个文件实际8pass/0fail/0skip、退出0、41.4秒（unified-task24-domain-frozen-linux.log），包含真实普通/ignore managed验证和SQLite全域实际SDK合同。没有将Task24标完成。

RetainDB整改进行中：真实owner-only红测与独立boundary review确认缺少worker消费者。沿既有采用身份/领域回执接入闭合enqueue/claim/renew/ack/fail及fresh reads；store/plugin/Schema由authority固定，destination保留同Profile合法业务namespace，owner重算消息指纹。队列SQL复用同一receipt Connection，HTTP仍在worker原线程与事务外。实际注册worker的backend从owner identity读取，不能用agent默认快照重选SQLite。旧renew回执仅是历史，HTTP前增加当下token/lease读；通道失败保留sticky journal，不自动绕过恢复。首轮Core红测2fail，接入后4pass；最新6文件22pass/0fail、退出0、30.6秒（unified-task24-worker-retain-port-first.log），含队列多进程、事务故障及冻结selector。尚未完成实际managed sync_turn/HTTP/重启恢复、旧租约丢确认反例及独立实现复审，不以构造成功或局部22项关闭major；metrics实际worker缺口仍未修复。

RetainDB最新局部收敛：原先首轮managed+Core合批3pass/1fail，失败为非法同会话双活worker夹具；改合法跨会话接管后Core3pass。其真实managed文件先Windows1pass/47.7秒、Linux与Core合批4pass/76.4秒。新增真实WebSocket断线永久合同先2fail，根因SDK的ConnectionClosed不属于OSError；队列在enqueue/loop/shutdown处理WebSocketException及OSError，保留原异常/request_id与sticky journal，不改变WorkerRPC未知提交重试。独立原红probe不变复验1pass，另独立实际enqueue提交丢确认/journal/peer/flush/finish1pass。

最新Windows `unified-task24-retain-lifecycle-green.log`两文件4pass/0fail/107.4秒，包含实际provider sync_turn、PG budget1下HTTP挂起仍由同owner读取会话、503失败与HTTP未结束worker退出两种持久恢复、新owner/新会话重放原body、peer隔离及所有进程SQLite尝试0。此前生命周期批次5pass/2fail保留：read测试在HTTP调用与ack开始间隙提前观察，现等PG acknowledged及空journal；另一项误查daemon的worker警告，现核对实际worker退出、HTTP仍未release及PG claimed，不放宽join10或业务断言。`unified-task24-retain-request-id-green.log`两文件6pass/0fail/19.2秒，包括新增enqueue实际commit/丢确认原异常携request_id、必要回执阻止finish、显式重放后仅一行和旧renew回执/新租约反例；JSON False/0/None/NUL/Unicode均保留。

最终Linux同一生产实现7文件19pass/0fail/0skip、退出0、206.1秒（unified-task24-retain-owner-linux-final.log），包括全部Retain PG原合同及三个新永久文件的实际业务、线程/通道故障、重启/peer。Windows SQLite/插件6文件44pass/0fail、退出0、8.6秒（retain-sqlite-contracts）；`scripts/check --staged --base c0558e9c13`14检查通过、health9个Python文件0blocking/0advisory（retain-owner-checks-final）。独立retaindb-worker-boundary-review已读取最终日志及diff，关闭本通道major，保持全局FAILED。当前保存标题`fix(storage): persist retained memory through owner receipts`的本地恢复commit，Task24仍in_progress，后续先整改metrics托管major，再新冻结完整PG/发行/Native/平台复验与独立终审；不将以上19项当全系统矩阵。

ed0冻结Native六文件19pass/0fail/0skip、退出0、16.5秒（unified-task24-retain-frozen-native.log），包括原完整safe-mode（原断言未改）与实际SQLite SDK独立合同，真实checkout ref为ed0cdbe604cded73026f28f4b96937c6e204a5cf。metrics永久真实消费者已在该生产版本实际1fail/1pass、退出1、47.98秒（managed-metrics-permanent-red）：普通opt-in模型成功/重开但PG模型调用数0；ignore默认不采集、owner同意窗口及遗留文件保持通过。另新增PG owner engagement合同实际1fail Path(None)（metrics-owner-engagement-red）；直接一律改profile_home会破坏SQLite仅给自定义数据库路径的两项旧合同（14pass2fail），现只对无文件PG使用明确home，SQLite保持原路径合同。PG两文件5pass（metrics-owner-engagement-green），SQLite原全文件16pass（metrics-engagement-native-preserved）；不据此关闭worker major。

metrics下一步闭合方案已做有界独立协议复审并补设计：公开具名短写/owner同意、metric_state root待办与本地receipt共事务、domain.metrics.flush提交后连接外维护与重放、root独立后端/opt-in/晚到退休、finish前显式quiesce。没有新任务或整轮重规划，尚未实现通道，未声称通过。最新源码只增加上述PG engagement窄修和两份永久测试，未重建最终发行载荷。

metrics通道实施进展：已复用实际owner identity、封闭worker.persist CoreEffect与同Connection指标锁，覆盖counter/day/interval/feature/milestone/install snapshot/age/engagement/consent及只读查询。source/root分事务待办沿metric_state，不新增Schema；domain.metrics.flush先提交空回执再在owner连接外维护，缓存回执也重跑维护，失败保留原journal；有界128批次若仍有待办明确拒绝ACK。owner实际当前collection/send决定导出/发送及撤回；worker默认send=false不能撤销owner窗口。严格quiesce在必要title完成后、execution.finish前停止新指标生产、等待异步flush、实际SDK订阅flush与所需回执；入口仅用owner绑定的纯Profile ContextVar scope，不读取worker.env。

首步Core真实红为1fail/1pass（worker-metrics-core-red）；第一次接入因把facade当scope resource出现AttributeError，改用既有ReceiptDomainResource后通过。Windows最初三文件5pass（worker-metrics-port-first），随后strict barrier与三个真实managed领域合批3文件6pass/0fail（worker-metrics-quiesce-first），包含verification普通/ignore与Retain两种关闭恢复。扩大owner发送实测后root+HTTP两文件5pass/0fail/77.7秒（worker-metrics-root-http-first）：普通模型持久重开、ignore默认不采集且保留owner窗口、已存在合格日期包由owner真实HTTP发送，普通send-off零HTTP。Core named interval/feature/day latches补验3pass（worker-metrics-named-operations）。

SDK barrier窄测最初两批各2fail：首批夹具绕过正常factory的identity缓存，第二批后台ThreadPoolExecutor不传播Profile而查错runtime；未把这些算成真实adopted主线程失败。现在quiesce从owner_binding显式绑定纯路径scope，实际Relay SDK订阅事件被gate时不提前返回，PG实际提交丢确认后保留journal并拒绝finish，原回执恢复后可结束；线程caller scope恢复。scoped两项2pass，增加明确混合Profile测试后两文件3pass（worker-metrics-mixed-barrier），PG子Profile无SQLite连接、root只在自己的SQLite scope真实提交，单独归类为混合配置，不充当全PG零SQLite证明。

真实gateway handler持久化窄测3文件6pass（worker-metrics-maintenance-first）：实际存活同用户child PID/birth、register/adopt/claim/verify不跳过，flush回执commit后实际维护故障，受保护journal原seq保留、finish拒绝、同receipt重放再次维护并仅一条回执，恢复后可结束；明确未走WebSocket线路。root用另一已核对归属随机Schema的不同PG target新合同正在Linux合批复验。独立foundation另真实撤回1pass、实际claim/postmaint replay1pass；plugins独立pool1/root实际commit/source CAS故障/withdraw/晚日3pass，报告保留当前范围与未验证项。

最新Windows指标原生30文件688pass/0fail/7个POSIX平台skip、退出0、69.2秒（worker-metrics-native-regressions）；这些7项后续在Linux验证，与尚缺的非WSL私有启动页七项不是同组。当前暂存14静态检查通过，health23个Python文件0blocking/0advisory（worker-metrics-checks-first）；补测后的最后统一检查尚待。Linux首批误把scenarios/metrics.py普通子进程驱动当测试文件，产生collection error；实际测试尚运行，不计该整批全绿，将按明确test_*.py清单重新结算。后续仍需当前生产冻结、完整PG/发行/Native宽回归未决项整改及全局独立终审，Task24保持FAILED/in_progress。

metrics最新完整局部结算：校正清单后的Linux13文件34pass/0fail/0error/0skip、退出0、182.7秒（unified-task24-worker-metrics-linux-accepted.log），包含真实ordinary/config-only daemon/采用worker/模型/SDK/PG计数与engagement、新owner恢复、peer、发送同意及真实HTTP，Core锁/回执故障/具名latch、实际SDK关闭屏障、实际存活child claim/register/adopt的维护失败缓存重放、独立SQLite root及第二owned Schema的不同PG ResourceKey。后两种handler/跨backend窄合同不冒充WebSocket失联后新worker恢复；第二Schema不是第二数据库服务。此前错误清单整批确为14文件33pass/1个collection error/退出1，不抹除；scenarios驱动仍由原process测试以正确配置/参数实跑。

补测后静态`PM Python scripts/check --staged --base ed0cdbe604`全部14检查通过、health23个Python文件0blocking/0advisory、退出0（worker-metrics-checks-final）。当前生产候选将保存标题`fix(storage): persist worker metrics through owner receipts`的本地恢复提交；Task24仍23/24、FAILED/in_progress。下一步在该ref新冻结Native验证原指标30文件、原完整CLI安全启动与SQLite实际SDK独立合同，并继续宽回归未决项；所有必需生产整改收敛后才重建最终四套PM发行载荷和完整PG/故障/平台复验，避免用即将过时的载荷反复声明完成。全局独立终审仍待，非WSL私有启动页七项主机仍缺。

metrics恢复点实际为`2a2684390016a1bfadc4c759bf2151945425f077`，独立Native checkout已核对完整ref。该冻结版本36文件714pass/0fail/0skip、退出0、49.2秒（unified-task24-metrics-frozen-native.log），覆盖原指标30文件、原完整safe-mode及SQLite实际SDK/禁止PG驱动独立合同，补齐Windows所跳过的该组7个POSIX用例；不外推为另一组非WSL私有启动页已通过。四套最终发行载荷及全系统PG矩阵仍待生产整改收敛后重建。

Native Telegram基线major继续整改：2a冻结的原error_before_entry-cancel确实1fail/93deselected（telegram-preentry-current-red），与a875同条件旧红一致。实际PTB22.8的stop先running=False，随后派生error callback未进SDK自己的task set，导致stop返回时claim owners=1。第一版直接跟踪Task并循环gather候选被独立3秒观察及Root180.1秒超时/stop栈否定：Python3.14对全done Task的gather可同步完成，饿死清理callback。该失败候选日志名虽含green仍不计通过；旧全文件候选执行已中断，另按完整argv、PM解释器、cwd、出生时间及专有pytest temp marker核对归属后终止其独立进程组，未操作其他进程/服务。

当前改为私有settlement Future，只在coroutine关闭及原claim释放完成后才完成该信号；stop在SDK stop之后用asyncio.wait等待这些清理信号，取消stop不取消marker。原单项1pass/2.4秒，原94项断言未改；完整原文件与平台三文件共4文件119pass/0fail/退出0/15.0秒（telegram-settlement-full）。独立真实SDK三项3pass/4.9秒，还覆盖stopping状态派生后继task及取消stop后真实释放；native-late-failures-review已记录局部闭合，未批准全局。静态首轮只发现slots排序，已修正排序待最终检查，功能/测试期限未放宽。当前修改准备另存标题`fix(telegram): settle admitted callbacks before shutdown`的恢复commit，Task24仍FAILED/in_progress，继续剩余Native fixture/生命周期问题。

Telegram恢复提交已实际保存为`692382575fc9...`（完整ref由git记录），随后只整改Native宿主fixture。冻结2a原两文件实际24pass/2fail（native-host-fixtures-red），危险审批的/tmp目标包含真实解释器所以正确硬拒，Termux的成功fallback与真实WSL警告同时存在。现审批改用隔离子目标并保留原deny/callback/allow_permanent断言，另加真实sys.executable父目录即使请求session批准仍在callback前硬拒；Termux只要求其成功notice和不误报app缺失，保留其他宿主要求、clean no-match阻断与真实OS事实。生产guard/audio代码未改。Windows两文件27pass/4.2秒，Linux两文件27pass/7.0秒，均0fail/0skip/退出0；14静态检查/health2文件0blocking0advisory（host-fixtures-checks）通过。独立foundation复核接受并记录旧意图/当前范围，整体仍FAILED。将以标题`test: isolate approval targets and Termux capability checks`另存恢复commit。

下一步按原完整失败输出生成逐文件复验清单；用已有PM管理的Linux工具链，依项目package-management说明在新隔离Native checkout准备锁定npm workspaces依赖，补原update_finish两项真实esbuild/TypeScript/Vite acceptance，不能把缺编译器的skip当通过。再以该冻结ref复验原失败文件及独立FAL PM环境；非WSL私有启动页七项继续保留主机缺口。未重写24任务范围，也未重建将过时的最终发行载荷。

Native原失败清单最新完整复验已结算：冻结`29796fc67d3580adbea66ce83306ded4ee7007c0`的新隔离Linux checkout，使用已有PM Node26.12.1/npm12.0.2，依项目workspace说明实际npm ci安装567包且esbuild/TypeScript/Vite均可解析（native-node-prepare），未修改其tracked源码。原49个失败文件中48个在全PM环境复验为761pass/10fail、3文件非零、退出1/180.1秒（unified-task24-native-failed-files-final.log）；FAL在单独已有PM环境、同一297源码另1文件38pass/0fail、退出0/1.6秒（fal-frozen-regression）。首次FAL编排早于state生成而FileNotFound，未开始测试，不计通过或业务红；生成后才顺序实跑。

十项红为非WSL私有启动页7项、真实更新编译2项、managed压缩1项（30秒等待HISTORY_8终态）。另在原冻结checkout安装未跟踪只读观测插件，实际2项编译均失败并记录原child输出（update-compiler-observed）；esbuild已真实编译197B，但TUI打包cpSync找不到夹具的ui-tui/scripts/gateway_bootstrap.py。生产builder从c1f19acb7f起要求连同clipboard_image.py打包，测试的微型workspace尚未提供这两项输入。当前只补实际辅助脚本输入及输出存在合同；在独立candidate checkout测试，不改原297冻结证据、不放松编译/回执/锁/退出断言。压缩保留原30秒期限，先在失败退出前采集拥有者日志和admission/execution行；未证明其根因，不将其他45文件通过替代本项。

当前实际最终候选为`69d455ccd377085b15dbb49f789bc9a3d5e8b8aa`。`task24_build_bundles.py snapshot/windows 69d455ccd377`及`task24_linux_bundles.py 69d455ccd377`均退出0，从该ref新导出不含.git/秘密的独立源载荷；PM frozen build构建Windows/Linux各SQLite/PG两个新环境，Linux含实际Matrix SDK（相应69d455ccd377命名日志及state）。Linux新native checkout亦核对完整HEAD且tracked diff为空；按锁npm ci再次567包/退出0，实际解析esbuild/TypeScript/Vite均在该checkout。FAL同ref单独已有PM SDK环境完整1文件38pass/0fail/0skip、退出0/1.9秒（unified-task24-69d455-fal-native.log），没有从完整回归中遗漏该域。

最终全分支首次直接working-tree检查把忽略目录中的PM第三方cache及独立源载荷作为待检树，no-tmp和profile-archives失败；保留unified-task24-69d455-all-branch-checks.log，不删除测试依赖或改guard。按scripts/check支持的CI受版本管理artifact方式，`scripts/check --staged --base a875342384`实际14检查全过、health587个Python文件0blocking/0advisory、退出0（unified-task24-69d455-tracked-branch-checks.log）。当前源码另实跑生成契约check、generated contract strict/noEmit TypeScript及完整TUI真实esbuild产品，全部退出0，两个运行时辅助脚本实际随产品发布（69d455-contracts-and-tui-build）。产物位于核对归属的隔离根下，不写正式实例。

本候选完整验证运行中：Linux `scripts/run_tests.sh tests/hermes_db/postgresql tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py -j3 --file-timeout1200 -- -m 'not live'`并传私有PG路径及新载荷参数，共126文件（69d455-full-pg-linux）；Windows `tests/hermes_db -j4 --file-timeout1200 -- -m 'not integration and not live'`并传新载荷参数（69d455-db-native-windows）；Linux原计划八个Native目录`-j4 --file-timeout1200 -- -m 'not live'`，FAL仅因独立SDK环境分跑并以上述38项合并结算（69d455-full-native）。全部retries=0，原压缩30秒业务期限不变且保留只读失败观测。三个Reviewer开始当前ref分域独立复审，均待完整日志；当前尚无最终汇总，不宣称全绿或关闭Task24。

69d完整PG批次已实际终态失败：126文件157pass/0fail/533errors，103文件非零、退出1/328.2秒（69d455-full-pg-linux）。最先可见test_kanban_board_files有4pass及teardown错误：服务返回could not write pg_wal/xlogtemp: Interrupted system call；相邻事务连接随后异常关闭，之后recovery mode。Windows/Linux只读复核均not yet accepting connections/Consistent recovery state has not been yet reached（69d455-disconnect-ready-{windows,linux}）。已异步告知用户处理其服务；不运维服务、不推断具体服务端根因、先不重跑完整PG。中断可能遗留的本批次标记Schema待服务恢复后逐个核对数据库、owner、唯一标记再清理，不借机操作既有业务表。

69d Windows数据库原生/新独立发行参数完整226文件579pass/0fail/3平台skip、退出0/565.8秒（69d455-db-native-windows），PG integration仅按marker排除，不能把进度显示的PG文件当实库执行。当前八目录Native仍运行。

独立终审又复现MatrixRuntime.close正常adapter.disconnect关闭链的新major：pending driver Task已done但_finished排队时，Python3.14的gather同步完成可使while热循环；取消close又会取消to_thread Task并遗失仍运行的同步线程追踪。独立真实SDK/关闭协议probe1fail且未访问PG；永久双合同首版1pass1fail，首项deadline误用AssertionError被adapter普通异常边界捕获，已改专用BaseException硬期限，未改变生产关闭语义，校正后原代码2fail。当前最小生产修正仅将等待pending的gather改asyncio.wait，保留shield、异常观察及事务退出顺序；实库关闭/commit补验因服务不可用待验证，不用线程返回值替代PG证据。报告plugins-final-candidate-review保留major待整改复验。

独立审查同时定位五个managed执行unit fixture缺少storage.identity；原冻结5文件实际10pass/21fail，均AttributeError owner_read，原资源释放/凭证/策略/路由断言未改。当前仅让五个Store double共用按真实构造scope返回SQLite身份的小fixture，不改生产quiesce/owner校验、不伪装PG或跳过关闭。两类整改均继续Task24内红绿验证，不完成任务。

本轮关闭整改局部验证已结算：独立候选7文件37pass/0fail/0skip、退出0/40.3秒（runtime-close-candidate）：Matrix关闭2、SQLite单后端4（含实际SDK）、五managed单位夹具31；独立原关闭probe未改另1pass/5.4秒（review-matrix-close-candidate-fixed）。Linux网关Matrix文件名合同/Relay/authority另25文件288pass/0fail、1原expected failure、退出0/64.9秒（matrix-and-relay-native-candidate），并非288项都是真SDK；Windows相应7文件48pass/0fail/1个Linux平台skip、退出0/70.7秒（worker-fixtures-relay-windows）。Relay只在原测试加entered Event和20秒入场阶段，修正EYES早于实际模型的夹具竞态；原顺序/ACK及各既有20秒期限均保留，整体wall-clock可增加该语义阶段。foundation独立复核已接受源码，待追加窄验结算。

另新增真实PG关闭双参数永久合同，直接真实_unit/Core提交、正常SDK store/adapter关闭链、取消关闭后保留driver、新store持久读回/peer隔离/连接归还；当前服务不可用，尚未运行，不把其Ruff通过当实库证据。下一步新静态/独立报告后保存明确未完成Task24的本地恢复点。69d正在运行的Native批次仍绑定原ref用于完整缺陷发现；生产关闭改动仅影响Matrix，必须在新ref补其适用实库/发行验证，不把旧载荷当新生产版本。

PG再次只读核对Windows/Linux均身份匹配、in_recovery=false且可连接（matrix-fix-ready-{windows,linux}）；先对上批日志唯一随机Schema核对current_database/namespace当前role owner/唯一测试marker后清理1项（69d455-interrupted-cleanup），未触及其他Schema或运维服务。新的真实关闭合同实际2pass/0fail/0skip、退出0/7.6秒（matrix-close-real-pg-first），并在当前10文件hash候选中完整Matrix PG目录组10文件31pass/0fail/0error/0skip、退出0/72.5秒（matrix-sdk-pg-after-close-fix），含真实SDK密码学、会话/并发、故障、恢复及关闭两参数。相同新PG test/同一SDK与数据库、仅恢复69d旧runtime的独立对照确实2fail/退出1/14.0秒（matrix-close-real-pg-baseline-red）：已完成回调热循环5秒硬期限，以及取消close删除真实driver追踪均重现。独立plugins Reviewer已逐项核对，关闭该major的调度/真实PG局部缺口，整体仍FAILED。

测试环境新增约束已实证：旧隔离Linux根所在tmpfs仍有约1GB可用却available_inodes=0，而独立测试tmp目录所在文件系统约992GB/6664万inode可用（linux-filesystem-inventory）。此前候选clone准备两次因No space失败且未开始测试；首个谨慎清理脚本因同UID系统进程cwd不可读而在删除前停止，未伪称完成。随后仅对本轮失败、从未执行的确切partial clone核对解析绝对路径/当前owner/Git origin/未到node_modules准备阶段/无state引用后回收，释放19031inode（partial-checkout-cleanup）；其余已验证目录及所有运行路径保留。后续新候选与PM发行/冻结树改用已核对空间充足的独立文件系统，不清理正式实例。

运行中的69d Native批次因此出现一批明确的control socket No space错误，原失败日志与计数保留，不将所有失败概括成环境问题。原冻结test_normal_runtime_boot.py在释放inode后、源码/期限未改的同环境2pass/0fail、退出0/54.7秒（native-control-after-inode-recovery），只关闭本文件对应环境反例，其他失败待逐文件复验。该宽回归尚未终态，不作最新全绿证据。新真实PG test的失败清理又经独立检查修正：未完成closing显式取消，COMMIT等待有10秒异步边界且只有真实成功后才启5秒关闭硬观察，不伪造成功信号。最后统一静态待补；下一本地恢复提交仍不是Task24完成提交。

最新实际恢复提交`120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b`已保存，四套全新PM载荷构建退出0，Linux产物/最新冻结树均位于已核对容量和owner的大容量隔离根。相同ref生成契约check、strict TypeScript及完整TUI产品退出0。Linux数据库非集成完整228文件584pass/0fail/0skip、退出0/563.9秒（120bf8c9d6c9-db-native-linux）；Windows新载荷真实初始化/资源/SQLite独立业务两文件4pass/0fail/2个Linux SDK平台skip、退出0/31.7秒（distribution-windows）。这两个SDK分支已由Linux相应批次实际执行，不将Windows跳过当通过。

本ref完整PG127文件再次未通过：240pass/1fail/451errors，87文件非零、退出1/423.7秒（120bf8c9d6c9-full-pg-linux）。首故障是kanban_sweeps正常COMMIT的UnknownCommitError，后续全为recovery mode；当时本地IPC tmpfs仍有7292 inode，不把本次服务故障归因到先前inode耗尽。核对测试信号仅作用其明确Popen child，无PG服务管理。随后只读Linux确认恢复，核对日志唯一Schema的数据库/owner/marker后清理1项（120bf8-interrupted-cleanup）。现以同一冻结源码/新载荷、全部127文件、`-j1 --file-timeout1200 -- -m 'not live'`串行跨文件复验（full-pg-linux-serial），保留文件内真实并发、所有原业务期限及retries=0；仅减少跨文件DDL叠加，不将改变调度称作已确认服务根因。

69d完整八目录Native已终态：6412文件63024pass/140fail/726skip，63文件非零、退出1/7788.5秒（69d455-full-native）。旧临时盘约束修复后，在120bf8冻结树先复验已完成的59个失败文件，实际315pass/4fail/7skip、退出1/868.8秒（120bf8-partial-native-replay）；最终新增四个失败文件中，三个已在安静串行同ref复验239pass/0fail/1个macOS平台skip、退出0/66.9秒（native-final-additional-files），另一个为非WSL私有启动页七项，适用主机仍未提供。以上是不同批次、部分合同重叠，不合计成一次全绿或抹掉原失败。

重放余下四个文件中两份CLI夹具根因已由源码/历史独立审查确认。relaunch按95f2802/parser合同继承CLI model，旧test误带pytest的`-m not live`；现固定实际Hermes argv，POSIX execvp标记并新增受控model继承参数，保留精确exec断言。Windows复验又发现原绝对路径fixture使用Unix字面路径，改为宿主tmp_path绝对路径；不伪装OS。service unit夹具按9248d847d0的account home安全来源补模拟account默认目录，与其已有platform默认目录一致，并先断言确实选裸unit，再保留真实sync/env/name断言；不改变生产逻辑。首轮Linux两文件125pass/0fail/7平台skip，最终path调整后relaunch Linux12pass/4Windows skip、Windows12pass/4平台skip，均退出0；Windows首轮原Unix路径1fail真实保留。最后静态/独立候选复核仍待。

另外两个未闭合文件是managed_worker_launch的history与plugin_keyless_inject的host路径超时。增加忽略目录只读观测，保留真实ordinary daemon/原SQLite审计/30秒期限：一次两文件观测2pass/1fail，压缩True在HISTORY5失败；采样显示worker主线程在真实journal fsync或RPC，owner主循环可运行，不能据采样断定单次fsync持续多久或排除产品问题。随后宽批结束的安静串行、同原业务期限复验3pass/0fail、退出0/135.1秒（worker-history-fsync-observed）；实际调用原fsync并测量，history372次总1.225秒/max0.132，压缩两参数2676/2703次总8.228/8.670秒、max0.348/0.095。保留间歇失败，仍待根因及host注入边界审查，不用这次绿直接声称修复。为保障IPC inode，另把两份已结束候选源码逐项校验复制到大容量根、保留旧路径链接后释放tmpfs副本（retired-candidates-relocation），原内容和日志均保留，空闲inode由7029升至79635。

CLI两份fixture最后静态首轮13/14通过，health指出原service test超长文件2929>2927；仅减少已修改函数内两处空行抵消增长，行为与所有断言不变。最终`PM Python scripts/check --staged --base 120bf8c9d6c9`14检查全过、health2文件0blocking/0advisory、退出0（cli-fixture-checks-final）。foundation已独立核对真实历史、完整diff、两阶段候选hash和Linux/Windows结果；将以`test: isolate relaunch and system unit fixtures`保存本地恢复提交，仅含测试/账本/审查，不改变120bf8生产实现或宣称Task24完成。Host注入取证插件首轮嵌套引号错误零收集，已编译校验修正后重跑（host-injection-observed-corrected），不是业务红绿证据；该验收与原生间歇仍未闭合。

20a478本地恢复提交已核对存在，工作区没有生产改动。完整分支CI artifact `PM Python scripts/check --staged --base a875342384`最新14检查全过，health598个Python文件0blocking/0advisory、退出0（unified-task24-20a478-full-branch-checks.log）；不是仅两文件的局部检查。Host原单项在120bf8冻结增加只读phase/ledger/model/watchdog观察后1pass/15.4秒（host-injection-observed-corrected），原20/30秒和精确一次/目标断言保留，5条terminal与5个真实模型输入及同会话FIFO均成立；该串行绿测没有解释原并发缺note，独立Host报告亦保留FAILED。原观察插件首轮引号错误零测试的日志仍保留，不计业务红/绿。

继续从120bf8实际生产冻结运行原三个未决文件的`-j3 --file-timeout1200 -- -m 'not live'`，只添加各自独立命名的诊断插件，不覆盖已有失败/安静证据（unified-task24-worker-host-loaded-observed.log）。完整PG127文件本次仅改跨文件`-j1`调度，文件内并发与故障/业务期限均不变（unified-task24-120bf8c9d6c9-full-pg-linux-serial.log）；Windows同生产ref数据库完整回归也在执行（db-native-windows）。这些命令尚未终止时不记通过，不关闭Task24。

上述三个文件现已终止：13pass/1fail/0skip、退出1、369.7秒，Host5项和managed压缩2项均通过，launch6pass/1fail；新红是`[controls]`原20秒等待无approval prompt，已保存当时started admission/running execution及owner线程栈。实际worker启动较晚、已有agent初始化日志但尚未看到模型/审批记录；该轮20秒watchdog未能在worker退出前采样，不据owner fsync采样猜完整因果。失败home随后按原runner清理，精确路径的只读timing恢复未找到，没有扫描/操作别的进程/Profile。安静压缩两项2676/2703次真实fsync总8.228/8.670秒，本次并发同类2653/2657次总107.774/91.614秒，最大1.768/1.800秒；这些属于通过用例的累计调用时长，不能证明controls具体哪步耗时或关闭其失败。后续观察已补5秒watchdog及失败时timing采集，但未运行新批次，先结算现有PG/Windows任务。

独立foundation按69d最终非零清单做集合差：63−59−额外3恰好剩private_launch一个文件，没有多余或漏记的失败文件；可以说最终62/63非零文件已复验，不能说62文件均绿或20a478完整6412已执行通过。69d→120唯一生产差异是MatrixRuntime.close，20a478只改CLI测试/文档；旧成功路径与当前受影响Matrix组可作为有界组合支持，不能自动替换本计划的当前完整Native门禁。问题收敛后才安排一次最终不可变生产ref的八目录宽复验，不在已知红未收敛时新增数小时runner。

当前完整实库批次已真实终止退出0：120bf8新冻结/新载荷，127文件689pass/0fail/0error/0skip、2474.4秒（unified-task24-120bf8c9d6c9-full-pg-linux-serial.log）。范围为整个PG目录、独立distribution及明确显式收集的ordinary Kanban daemon/采用worker/真实模型业务场景，包含最新managed verification/RetainDB/metrics与Matrix SDK关闭/加解密/并发/重启。只将跨文件调度改为-j1，文件内并发/故障、真实PG与作用域/恢复/SQLite audit和原期限均保持；不据该结果解释之前WAL中断的服务原因。Windows同生产ref完整数据库228文件579pass/0fail/5平台skip、退出0、520.0秒；Linux同ref数据库228文件584pass/0fail/0skip、退出0、563.9秒，五项差异为宿主真实SDK/协议合同。SQLite独立发行子进程与PG禁止SQLite业务进程范围各自核对，不把前者伪称全PG零SQLite。

四份证据文档相对20a478的CI artifact检查14项通过（final-evidence-docs-checks），无Python measured改动；以上两个完整批次终止后补入本结算，再次核对文档检查后保存本地恢复点。三域Reviewer已收到实际最新日志进行只读增量结算，尚不预判全局APPROVED。原三文件13pass/1fail的controls失败仍未解释；现有宽批次全部结束后才开始同一三文件-j3的下一次取证（worker-host-timed-observed），增加早至5秒watchdog、失败timing和单次started时间，保持真实fsync/原期限/所有业务断言，独立输出名保留此前失败现场。

新增timed观察已终态：同三个文件14pass/0fail/0skip、退出0、112.6秒，launch7项包含controls及history、压缩2项、Host5项全部原期限通过。PG/Windows批次在该次开始前均已终止；增加的5秒watchdog及单次timing只属于这次绿色运行，不能替代前次controls失败缺失的关键worker时间线，也不能把此前并发红删掉或称根因已修。没有生产修改，不为单次绿重建载荷或重复PG689；后续应利用保留观察在一次最终宽复验中核对压力下实际表现，平台主机缺口仍独立保留。

三域独立Reviewer现均已只读核对127/689、双宿主数据库/发行/静态与当前生产blob，现有领域未发现新增未处理blocking/major；全局仍FAILED/CHANGES_REQUIRED。plugins特别区分本轮没有重跑contracts下integration标记的mixed-root合同，先前局部证据保留，不计入689/584/579；维护handler不是WS失联全链，第二owned Schema不是第二数据库服务。本次七份证据文档检查14项通过、无Python measured变化（pg-final-ledger-checks）；新增本段仅记录检查后执行状态，另运行diff-check保存。

已开始一次最终当前代码宽复验：冻结`20a4789b35d4b38eec098c5a1203699200833474`（与120bf8生产相同，包含最终CLI测试修正），独立native-filesystem checkout及锁定Node真实compilers已准备。开跑前核对owner、完整ref/无tracked修改、专有根空闲inode66,253,099及tmp78,008，不再使用原inode耗尽的源副本。通过`scripts/run_tests.sh tests/cron tests/hermes_cli tests/gateway tests/tui_gateway tests/acp_adapter tests/plugins tests/agent tests/tools -j4 --file-timeout1200 -- -m 'not live' --ignore=tests/tools/test_fal_sdk.py`，仅添加现有worker/Host只读观察插件，retries=0，原6412文件/原期限/平台行为全部保留（unified-task24-20a478-full-native-observed.log）。此批用于结算当前宽回归及保留压力现场，不代表历史偶发已定因；七个缺适用主机的私有页测试没有被删除或改OS。FAL同ref用既有独立PM环境另行38pass/0fail/0skip、退出0、1.9秒（20a478-fal-native），不与正在运行的6412文件混报整批全绿。最新宽批次尚运行，Task24保持in_progress。

补齐最终选择范围的两处实库证据：独立审查指出contracts下的mixed-root带integration标记，被Native的not-integration排除，也不在PG目录127文件中。Root在当前20a478独立冻结中通过标准runner显式执行`tests/hermes_db/contracts/test_worker_metrics_mixed_root.py -j1 --file-timeout1200 -- -m integration --postgres-test-config=<既有私密验收路径>`，实际1pass/0fail/0skip、退出0、4.5秒（unified-task24-20a478-mixed-profile-backends.log）。PG子Profile真实effect/receipt和待办排空、SQLite根Profile实际指标持久结果、源scope恢复及所有SQLite连接只属于明确SQLite根scope断言保留；该合同明确允许另一个Profile选择SQLite，不计作全PG进程零SQLite的689项。

进一步核对PG目录外使用integration/实际PG fixture的现有合同，另有`tests/hermes_db/test_profile_deletion_storage.py`的七项集成参数，亦不在689和Native584/579中。Root按相同命令前提单独执行该文件`-m integration`，实际7pass/0fail/0skip、退出0、24.4秒（unified-task24-20a478-profile-deletion-integration.log），包括PG source→显式SQLite房间target、确认后root/target retarget拒绝、check/open间改配置仍只写冻结store，以及SQLite→PG切换拒绝和peer保留。原非integration的四项由前述NativeDB批负责，不重复。两份新结果与689分别留账，不改称一次697项全PG；本轮没有源码/测试变更、服务运维、正式Profile操作或现有表操作，真实Schema仍由原fixture核对归属后创建/清理。后续最终独立终审应同时读取这两份补证日志，旧报告“本轮尚未重跑mixed-root”仅保留为其检查点的历史状态。

独立foundation已读取上述两份补证的真实日志、原测试和实际删除/投递/指标调用链，并追加followup；没有代跑或连库。明确其中是6项删除身份参数+1项跨后端Cron room，和既有4项非integration共同给该原文件11个参数留下分批证据；mixed metrics每个SQLite连接都必须在明确root scope，source PG pool budget1及scope恢复保留。没有将8项归入689零SQLite或把分批说成同次11项。本次审查也读到timed14绿并保留前次13/1未定因，全局仍FAILED/CHANGES_REQUIRED。宽复验进程经原session 64460重新核对仍在运行，中途无新失败只作进度，不登记Task24完成。

最终交付物核对发现`docs/reviews/unified-database-backends-review.md`的“当前”仍停在58d/d402/66a，落后于本账本与三域独立follow-up。现已更新汇总的当前生产120bf8/测试冻结20a478、689/双宿主DB/四套发行/静态构建、目录外integration8项、owner消费者与Matrix关闭/Telegram局部整改及仍在运行的6412文件宽批；旧批次结果明确标为历史保留。原不再存活的旧进程不继续写成当前运行，Native间歇/服务故障因果及非WSL主机缺口不降级。该文件明确由实施Agent汇总，不代替尚待宽批终态后的独立全局终审。此次只改证据文档，未改生产、测试、依赖或验收范围。

审查汇总文档增量已执行`PM Python scripts/check --staged --base 8a3c2f39d8`，14检查全部通过、无Python measured修改、退出0（unified-task24-review-summary-checks.log）；diff-check亦通过。以标题`docs(storage): align final review with current evidence`保存本地证据恢复点。当前原生宽批仍经原session核对运行中，已进入Gateway文件、尚无新失败，不将该中途状态改成最终通过。

20a478当前宽批首红已产生：启动锁probe文件6pass/1fail、8.5秒，原持久probe用例先满足elapsed>=0.3，再因gaps=[]失败。源码及历史核对表明原测试/共享reserve helper相对a875未变；原固定deadline允许首轮真实reserve/复核耗尽预算后立即拒绝，测试却要求一定出现第二次尝试。保持真实flock、直接调用未改原test，受控模块时钟在一次真实复核后推进0.31秒，标准runner确定1fail、退出1、1.0秒，同gaps断言（probe-budget-original-red）；没有把原红归为单个fsync延迟或PG产品缺陷。

当前仅修原测试前提：原wait_s=0.3/真实文件锁与PID记录/真实fsync/release保留，通过已有cancel.wait与模块私有clock接缝明确测试预算内退避和首轮预算耗尽两种合法路径；其余六个真实boot/跨进程probe/foreign owner/取消case不改。独立新候选state为task24-probe-budget-candidate-state.json、基础8c75a83c35、单测试overlay SHA92182b8c...1c1b0c；整文件8pass/0fail、退出0、1.5秒（probe-budget-candidate），不是延长生产或测试期限取绿。独立foundation与静态待结算，Task24保持FAILED/in_progress。当前完整6412文件原冻结继续执行，不能将后续候选8绿记成原宽批已绿；详见debug的新日期章节。

启动锁probe夹具整改已由独立foundation逐行核对真实I/O、模块clock隔离、两个预算分支和原六项接线合同，局部可接受、无新增blocking/major；未要求或执行生产改动。`PM Python scripts/check --staged --base 8c75a83c35`14检查通过、health1个Python文件0blocking/0advisory、退出0（unified-task24-probe-budget-checks.log），后续只补入审查结论/结果文字，diff-check通过。以唯一标题`test: make probe deadline coverage deterministic`保存父提交8c75上的本地测试恢复点；PG/发行不因测试修改重跑，仍以120bf8真实生产689/四载荷为准。原20a478宽批仍在运行，现进入managed相关文件，已记录旧probe单红，不能改称当前整批全绿或Task24完成。

当前原20a478宽批内，managed launch7pass/64.5秒（含controls/history）、Host injection5pass/37.9秒和managed压缩2pass/170.8秒已真正原期限通过；它们属于该宽批子范围，不与先前timed14相加、不反推旧失败因果。第二个非零文件为hygiene turnhold adoption，2pass/1fail、28.4秒，inline尚缺原具体断言；整批仍live。Root受控阶段观测原文件3pass/4.3秒，仅测得该次whole1.0396/wait0.300855秒。核对完整runner身份后Python调试只读请求被OS EPERM拒绝，未取得原failure，未改内核/服务或重启原批次。

该hygiene首case的失败前release缺finally已由独立foundation确认minor，Root先对这一独立问题做精确红绿：原函数/真实Events/强制result断言失败的probe实际close0而红，1fail/9.7秒；只给原断言段加try/finally release+await原deferred drain，原5/15/commit5秒和全部业务断言不动，probe现1pass/10.5秒且原AssertionError正文保留、close1和任务空。candidate state task24-hygiene-cleanup-candidate-state.json、单hygiene文件SHA ffac74a5...badd59f，源候选另外持有已提交probe测试overlay；未修改运行中的20a478。独立foundation已接受这项局部cleanup整改，静态待结算。

新candidate原adoption整文件仍2pass/1fail，真正完整复现whole elapsed11.010960637<5失败；合批2文件3pass/1fail/退出1/34.6秒（hygiene-cleanup-candidate）。后来method观察另3pass/5.1秒、call-only原首case另1pass/2.6秒只属于成功时序，不能记根因已修。慢阶段继续调查，未改生产或期限。详见debug和foundation followup，Task24仍FAILED/in_progress，非WSL平台缺口保留。

后续hygiene call-only失败profile已取得真实慢阶段：whole8.811243883秒中post-turn hooks7.3143秒，首次真实goal store warm7.29866秒；summary等待仍约0.3秒。skeleton未准备真实post-turn库，故当前保留实际goal/loop/SQLite初始化但移到原计时起点前，另保留失败finally release/drain。原期限/业务断言全保留，生产无修改。第一次bootstrap顺序probe监视错接缝、结果[]，不计有效红；更正包装真实_acquire_session_db后旧cleanup-only候选明确in_handler=True而1fail/13.7秒。新99bd候选state task24-hygiene-warm-overlay-state.json、源SHA da3e7ec2...c7b943e，原3项+cleanup错误路径+真实acquire计时边界共3文件5pass/0fail/退出0/45.9秒（hygiene-real-warm-accepted）。首次WSL服务启动错误零测试单独保留，不算业务失败/通过。独立复审及最新静态待结算，详见debug；Task24仍FAILED/in_progress。

当前20a478宽批仍经原session64460运行，不重启；截至96.7%已有6个非零文件、12个失败参数（probe、hygiene、pause-record、private-launch七项、async-delegation、groups-route-parity），只作中途快照。probe已提交局部闭环，hygiene最终候选5绿待独立复审；pause-record身份/marker分叉及groups真实断言待取证，async-age错误墙钟上限待最小验证。七项非WSL适用主机仍缺；旧managed/Host因果不能由本批局部14绿倒推。未创建Task24完成提交，PG689/四套载荷不因测试/文档变化重复运行。

hygiene最终独立foundation复审已接受该fixture小修：正确acquire红/5绿、真实hooks/库及全部原期限均核对，无新增blocking/major。最新`PM Python scripts/check --staged --base 99bd92d5ecdf63c93a01561d58769fd51360cbdf`14检查全过、health1文件0blocking/0advisory、退出0（hygiene-real-warm-checks）；随后仅补入本结果及独立结论并diff-check。以唯一标题`test: prepare real hygiene state before timing`保存本地恢复提交；Task24仍23/24、FAILED/in_progress。下一步继续原宽批终态和pause-record完整文件只读分叉观察，不延长TTL/改权限/重置身份缓存。

原20a478宽批已自然退出1：6412文件63150pass/15fail/726skip、7722.3秒、4workers/retries0（20a478-full-native-observed）。8个非零文件精确为probe1、hygiene1、pause-record1、private-launch7、async-delegation1、groups-route-parity1、notification-poller1、tui-gateway-server2；原hygiene此次实际12.006945064秒违反5秒，不能把新profile代充原现场。probe99bd、hygiene261f已有局部闭环；PG/发行未发生生产变化，不重复执行。新server两项分别15秒未make_agent、下一项scopes多None，须查失败工作线程/清理，不加期限。

async-age测试原固定20上限已按独立plugins核对的合同整改：真实dispatch/ledger/monitor/worker保留，monitor实际Event替代sleep，list前后真实时钟包围同base_ts的一位小数age。原gate10/.03与全部业务/隐私/finally断言不变；不修改生产。相同原函数反例只推进两个模块本地proxy的逻辑时钟10.1秒、全局stdlib不改，原1fail26.1秒（age46.9>20，含模拟推进，不是实际延迟），新261f候选原完整文件+同probe36pass/0fail/1个macOS平台skip/退出0/113.9秒（activity-age-verified-candidate）。overlay单文件SHA641d0ac7...dc21c74，准备时WinError206及缺state零测试保留；独立终态审查/静态待结算。

pause-record原完整文件只读分叉观察43pass/40.1秒，false实际asked/unknown空、live含本PID、fresh/cached ct相同；notification原单项1pass/1.9秒且两个真实join约.006/.709秒。它们只是未复现原红，根因不关闭。剩余当前原宽红的三项有局部整改，另4文件5个Native失败参数与7个非WSL平台参数尚未闭合，最终独立全局审查仍待；Task24继续FAILED/in_progress。详见debug和各独立followup。

async-age最终独立plugins复审已接受源码/原函数红/新36绿1skip，原固定上限minor按局部闭合。最新`PM Python scripts/check --staged --base 261f3fcc04f6f25965e1e78ae5fc7e324fa35aa2`14检查通过、health1个Python文件0blocking/0advisory、退出0（activity-age-checks）；后续仅补实际结果、独立结论和pause/groups只读报告，diff-check通过。以唯一标题`test: compare delegation activity age at sampling time`保存本地测试恢复点；Task24仍FAILED/in_progress，不把补测从原宽批15红中扣成全绿。

server两个profile build测试失败清理已单独验证并最小整改：原finally只pop，确切自有thread可越过patch生命周期。原函数故障probe保留真实scope/线程/store acquire，只迫使原built断言失败；旧1fail/2.3秒（原异常已捕获后thread仍alive），新同probe1pass/3.0秒。两case各join自身handle15秒再pop/assert退出，原业务built15/ready5及scope/home断言不改；新增15秒明确为cleanup独立上限，超限仍红，不宣称完全相同时序或原15秒慢因已修。当前fb483 overlay SHA f85b555d...64b388d，原完整637项+probe共638pass/0fail/退出0/110.4秒（profile-build-cleanup-candidate），独立foundation接受cleanup minor局部闭合，静态待。observer本次只见成功的自有sid/home/scope，旧额外None归属及旧超时仍未关闭。

groups原完整4项在只读phase observer下4pass/0fail/退出0/33.9秒；document/image真实room_once约.136秒、两read/submit/settle均有返回，44events/dropped0、无失败快照，只记未复现。观察保留原10/5/.4及固定业务clock，在原timeout/stop前仅保存实际调用状态和自有线程栈，不额外连库探测。下一步按四个原失败完整文件的联合现场继续取证，未闭合仍4文件5参数及非WSL7项，全局FAILED/in_progress。

server cleanup最新`PM Python scripts/check --staged --base fb48321d7d06997b787b0ec8e855a74527179ec4`14检查通过、health1文件0blocking/0advisory、退出0（profile-build-cleanup-checks），独立foundation已接受故障probe红绿与完整637项结算；collaboration已接受groups未复现的准确边界。之后仅补本结果/审查/恢复文字并diff-check。本地恢复标题`test: join profile build threads before releasing mocks`，Task24仍23/24、FAILED/in_progress。当前同一fb+f85b overlay正以-j4跑四个剩余完整文件联合观察（remaining-native-joint-observed/session41931），全部原期限/真实存储/文件内顺序保持，joint产物单独命名，尚无完整终态，不重启/覆盖。

四文件joint已终态682pass/3fail/退出1/574.6秒；pause43及groups4只记本次通过，notification原第二join3红真实捕获loop→goals→registry首次SessionDB/WAL路径；server635pass/2fail分别secret built15及新增queued notification nested_started5。原MCPhome built15本次已过但不反推旧因果，新增5秒缺线程现场，不泛归DB。server secret真实open23.438762秒，15秒现场最后在schema DDL（不同于notification WAL）；随后owned scope/sid/home正确且cleanup线程确实退出，不能再声称额外None是产品泄漏。

notification raw fake-agent夹具现仅补真实goals store/nonNone准备，保留完整poller/loop/goal/SQLite及两条join3/原唯一线程断言。正确真实_acquire相位probe旧1fail/31.8秒，明确after_services=True/同一隔离home；先前WSL准备失败及缺文件退出2零测试不计红绿，已记录依赖启动错误并修正编排。新d010候选state task24-poller-warm-overlay-state.json、SHA09ac2921...5c11928，Linux原1+同probe1共2pass/0fail/退出0/15.3秒，Windows同源原1pass/0fail/退出0/10.8秒。原实际join约.014/.509秒，独立最终复审/静态待；不声明通用cold-init stop或WAL内部性能已修。

下一步先结算通知fixture局部小修，然后用真实profile store ref覆盖server scope测试的timed build/join并验证同一handle与实际worker open；两个相位probe的原红正在非运行旧候选执行（profile-store-preparation-original-red/session51770），尚未计结果。新增nested_started5先取所属线程实际phase，不加期限/不禁用tick；当前仍Task24 FAILED/in_progress及非WSL7项缺口。

notification最终独立foundation已接受局部红绿和准确边界，最新`PM Python scripts/check --staged --base d0101fe64df16b4db716af9ea55b66d8bd05b5d2`14检查通过、health1个Python文件0blocking/0advisory、退出0（poller-real-store-checks）。随后只补实际结果/恢复文字并diff-check，以唯一标题`test: prepare real store before polling lifecycle`保存本地恢复点，Task24仍FAILED/in_progress。工作区server另有closing真实ref准备增量、未纳入此提交；旧两profile相位probe现已2fail/28.8秒（实际first open after_start=True；此前28.7误记已更正），本段当时候选仍待。新nested5待原失败窗口线程现场。

server实际closing准备已有局部证据：原15/5/cleanup15及全业务断言保持，worker仍真实open同target；旧phase2红28.8秒→当前两参数绿5.2秒，验证初始化在start之前、第二次实际worker open复用同home/同真实SQLite handle。当前源SHA0e05b83d...5659cf8（state task24-profile-store-candidate-state.json，基础d010+已提交notif overlay），Windows原两项2pass/0fail/退出0/10.4秒。清理适配probe曾旧1fail16.4秒且自身15秒未排空，另存不计干净排空；新ignored probe仅自身finally real_join60，原fixture15/5/15不改，旧唯一alive红1fail7.6秒/实际排空成功（非工具外层8.3），当前同probe1pass9.6秒。独立foundation已接受局部准备边界，不外推PG对象identity或底层23秒性能修复。

六文件-j4联合观察仍在session22923（profile-prepared-native-joint），当前五文件51pass、原server637项未返回，不预记688绿；扩展observer已准备新nested5原失败窗口的owned-thread栈。下一步读取完整终态，分别处理新红与窄绿，不重启或重复已结算PG/发行；该源码的静态/本地提交待完成，Task24仍FAILED/in_progress。

六文件联合现已自然退出0：688pass/0fail/0skip、485.9秒、4workers（profile-prepared-native-joint），其中原server637pass/476.3秒、pause43/groups4/notif1/profile相位2/cleanup1；旧四文件682/3和原20a全宽15红都不改写。新nested5本次Event约.524秒True，observer触及20000事件cap、无失败线程快照，不声称原因已定位。最新`PM Python scripts/check --staged --base c1dffcc317`14检查通过、health1文件0blocking/0advisory、退出0（profile-held-store-checks）；独立最终局部结算待补，后续仅结果/恢复文字并diff-check，本地提交待创建。

只读native provenance manifest逐一对应原6412唯一文件行及Git blob：完整原统计63150/15/726、8非零文件；到当前worktree生产diff=[]，仅5个selected测试变更且全部在原8个非零文件中。该manifest不是新的业务测试或全绿判定，不取代补测和独立审查；Task24原验证方式允许按依赖/原生平台分批，但当前非平台必需范围/并发合同和历史未定因风险的实际分级仍由独立review核对。非WSL7项主机及最终全局门禁未闭合，保持FAILED/in_progress、不宣称全系统完成。

独立foundation最终已按原分批要求核对688/0/0、14静态、五hash及原6412 provenance：本范围未发现需要再跑全6412或另加新并发组合的具体非平台blocking/major；原七非平台非零文件都有当前完整文件补证，最后四为-j4联合，历史未定因风险和原红都保留。最终本地ref/hash/分批集合冻结、相对a875全分支静态/verification、各分域独立总审仍待；非WSL7仍缺真实主机。以唯一标题`test: hold real profile stores during scoped builds`保存本地恢复，父c1dffcc317，非Task24完成提交。

## 计划变更

| 日期 | 变更 | 原因与影响 |
| --- | --- | --- |
| 2026-11-07 | 撤销独立Cron/Kanban/rooms/插件SQLite排除，建立统一后端计划 | 用户明确可选意味着系统单后端可用；原会话成果复用，新域全部待实施 |
| 2026-11-07 | 统一选择提升至storage.backend | 避免组件配置造成运行时必须混用数据库；旧开发配置显式报错，不静默回退 |
| 2026-11-07 | Matrix单列完整SDK协议任务 | 源码实际传sqlite URL；不能凭PgCryptoStore类名或替换DSN判定已经统一 |
| 2026-11-07 | Task 9提前包含终态/派发直接依赖的底层附件元数据与workspace适配 | complete/review/spawn实调用链依赖原Task 10接口；避免通过跳过保存/清理完成Task 9，订阅/转移/剩余消费者仍归Task 10，24项总数与验收不变 |

## 最终验证

### 冻结输入与执行命令

最终代码：`6c9e28665b1766c295023018a03e390dd264c230`，分支`feat/postgresql-session-storage`，a875为祖先。PG/发行真实运行使用生产120bf8；到最终代码的生产diff为空，未因tests/docs变更重复已结算PG/发行。

- 最终全分支：`PM Python -X utf8 scripts/check --commit 6c9e28665b1766c295023018a03e390dd264c230 --base a875342384`。
- 最新Native：PM解释器运行`run_matrix_linux.py --state task24-profile-store-candidate-state.json --tools-state task24-linux-tools-state.json --native --log unified-task24-profile-prepared-native-joint.log tests/hermes_cli/test_update_pause_record.py tests/tui_gateway/test_groups_route_parity.py tests/tui_gateway/test_tui_gateway_notification_poller.py tests/tui_gateway/test_tui_gateway_server.py tests/tui_gateway/test_task24_profile_store_preparation.py tests/tui_gateway/test_task24_profile_build_failure_cleanup_held_store_drained.py -j4 --file-timeout1200 -- -m 'not live' -p _task24_pause_prepared -p _task24_groups_prepared -p _task24_notification_prepared -p _task24_server_build_profile`；实际测试仍由`scripts/run_tests.sh`执行，retries=0。
- 输入绑定：PM解释器运行`task24_reconcile_native_provenance.py`及`task24_freeze_final_reference.py`，均exit0；后者冻结代码、五个测试SHA、14日志摘要/hash及23/24状态到`task24-final-code-reference-6c9e286.json`。
- PG/双宿主/发行/构建的实际完整命令与当时输入保留在Task24执行账本和对应原始日志，不将新提交号冒充其原运行版本。

### 执行结果

- 当前完整PG：127文件689pass/0fail/0skip、exit0、2474.4秒，生产120bf8；含完整PG目录、独立发行和显式ordinary Kanban daemon场景。PG业务子进程严格拒绝全部SQLite连接，包括内存/URI/别名/直接Connection及吞掉的尝试；实际业务/持久化/作用域/重启与SDK均验证。独立SQLite发行子进程和不同Profile的mixed合同分别标明，不把整个联合runner进程树说成零SQLite。
- DB Native：Linux228文件584pass/0fail/0skip，Windows228文件579pass/0fail/5平台skip，均exit0；SQLite独立PM载荷无需PG驱动/实例，实际SDK业务和新进程恢复通过。
- 发行/升级：120bf8四套Windows/Linux、SQLite/PG PM载荷已真实执行；Linux发行4项与PG初始化发行2项包含于689，Windows发行4pass/2 Linux SDK skip。fresh Schema、重复/前向升级、历史PG数据及十域/双Profile新进程恢复按各自合同执行；没有旧SQLite数据迁移/双写/回迁。
- PG目录外：mixed-root1pass/4.5秒、Profile删除/跨后端房间integration7pass/24.4秒，均exit0；不并入689的严格全PG业务范围。
- Native来源与补验：原20a478完整6412文件63150pass/15fail/726skip、exit1，原始结果保留。6412唯一逐文件行/原与当前Git blob已逐项核对，仅5个测试变化、全属于原8个非零文件，生产diff空。原七个非平台非零文件都有当前完整文件补证：probe8、hygiene原3加诊断2、async原35/1macOS skip加诊断1；其余四原完整文件在新六文件-j4联合688pass/0fail/0skip、exit0/485.9秒中覆盖（原server637+pause43+groups4+notification1+profile相位2+cleanup1）。FAL独立PM环境另38pass，未在原6412中，不混计。
- 原生夹具局部补证：notification Linux原+真实acquire probe2pass、Windows原1pass；profile真实持有ref/实际worker同handle参数、故障清理及Windows原2pass均通过。原业务0.3/3/5/15等各自期限保留；新增cleanup15仅明确清理上限，ignored诊断自身排空60不作业务期限。历史未知原因与诊断自身失败分别保留，不以当前绿补造根因。
- 最终静态：冻结代码相对a875全部14检查通过，603 Python文件health0blocking/0advisory、exit0（6c9e286-final-branch-checks）。当前生产生成契约、strict TypeScript与实际TUI build exit0；Electron旧noEmit/预检22项只按源码未变历史范围保留。
- 独立审查：foundation、collaboration、plugins/acceptance已分别读取真实diff/日志/hash/来源，当前范围未发现未处理的产品blocking/major。最后独立总体门禁复核也已完成：冻结ref/日志/hash/603文件检查及设计九项/原八非零处置准确，按原Task24分批合同无需没有具体依据的整轮重跑。非WSL七项缺证为验收major，结论BLOCKED/CHANGES_REQUIRED；没有全局APPROVED。追加总体结论后的最后文档14检查通过、无Python measured变化、exit0（final-gate-docs-checks）；随后仅补结果/恢复文字并diff-check。

### 验收标准检查

- [x] 单个Profile所有自有数据库服从同一个后端选择，依据完整PG各域及跨Profile/mixed补证。
- [x] PG完整业务矩阵实际工作，自有SQLite连接尝试为0；发行的SQLite独立子进程不混称PG业务。
- [x] SQLite独立运行，不要求PG驱动/实例。
- [x] 各域声明的作用域、幂等、锁、配额、重启及错误语义有真实合同证据；不保证一切可能的负载组合。
- [x] Matrix及维护插件有实际SDK/PG协议和持久化证据，未关闭功能或用内存替代持久化。
- [ ] 全部适用平台验证完成；数据库/发行/启动关闭指定范围已过，非WSL私有启动页七项未完成。
- [ ] 最终全域独立审查APPROVED；缺失平台证据继续阻止全局批准。

### 未通过与未验证

七项非WSL POSIX私有启动页为必需条件，当前没有适用主机。已准备本地`private-launch-host-6c9e286/`：仅冻结Git源码archive、PM隔离runner、README及校验和；archive为91,102,713字节，SHA256 `891705faa5344a5e34593ba49a22a38419f4e5d597ee240eeec729c75910f33d`。runner的`bash -n`通过，但没有在适用主机执行；不计验收，也未把用例删除或伪装OS。已异步询问现有入口/执行日志，继续完成不依赖该主机的证据收尾。

历史pause/groups/managed/Host/nested等待及PG服务恢复实例的完整原因仍未明，保留为可靠性残余风险/无法验证项。原Native全宽非零、服务中断批次及诊断自身失败保留。当前独立审查没有将未知原因臆断为新增生产major，也未宣称其已经根因修复；如再现，应按新现场处理。

### 最终状态

`BLOCKED`：当前代码与已声明的非平台验证范围通过，独立总体审查已完成但因适用主机缺证给出CHANGES_REQUIRED；Task24仍in_progress、23/24。最后文档14检查已过，以本地标题docs(storage): preserve final blocked acceptance gate保存证据恢复，非Task24完成提交。不批准合并，不将目标标complete。

## 恢复点

### 当前恢复点

最终代码本地提交`6c9e28665b1766c295023018a03e390dd264c230`（test: hold real profile stores during scoped builds），生产120bf8内容等价；notification c1dffcc317、server cleanup d010、async fb483、hygiene261f、probe99bd均已局部验证。代码后的修改仅为证据文档。Task1–23 completed，Task24 in_progress/验证BLOCKED、23/24，非完成提交。

所有本轮测试进程均已终态：原full20a exit1；旧joint41931为682/3 exit1；新joint22923为688/0/0 exit0；最终全分支88541为14checks/603Python health0/0 exit0。源/hash/日志冻结在`task24-final-code-reference-6c9e286.json`；原6412逐行来源在`task24-native-provenance-reconciliation.json`。不因tests/docs变化重做PG/发行或重启这些终态批次。

独立总体复核和最后文档14检查已完成，证据恢复按唯一标题docs(storage): preserve final blocked acceptance gate定位，源码仍冻结6c9e286。直接Git核对d998..3febe6fc31恰23个按Task1–23领域顺序的本地提交，Task24没有完成提交。当前唯一必需外部缺口是七项适用主机结果；入口缺失已连续多轮记录，截至该检查点没有其他不依赖主机的必需项可自主推进，现有工具也无远程执行入口。下一步取得真实非WSL Linux/macOS入口或完整实机日志，运行准备的原完整12项（含缺失7项）；新失败按原合同整改后复验，平台通过后再解除总体CHANGES_REQUIRED。用户随后新增授权的正式Profile本机PG试运行已执行，详见下一节；不推送、发布、PR、合并或操作数据库服务。

### 2026-11-09：用户授权两个正式Profile本机PG试运行

用户先请求配置本地PG并重启Hermes，再明确回复“两个Profile都切换到PG”。已说明并确认此次使用新数据集，旧SQLite会话/项目/看板等不自动导入；配置、Markdown记忆、工作区和附件内容继续为文件。这是新增的运行切换授权，取代此前“本轮不切换正式Profile”的操作限制，不改变功能设计或Task24完成条件。

实际检查纠正了旧安装记录：切换前网关PID14412已经加载`9b292893eb`，并非仍运行a875；两Profile仍SQLite、active_agents=0。现有秘密来源指向本机loopback端口55432、数据库hermes_agent；只在进程内读取，不打印DSN/密码。只读连接确认PG17.11、非recovery、已有pg_trgm和建Schema权限；没有安装、启动、重启或管理PG服务/扩展/角色。

实际操作与结果：

1. `hermes pm install --extra postgresql`：exit0，保留现有extra，由PM发布正式依赖代次`ca8aa89c2a8149528de46dcd935326d9`。正式解释器实际导入SQLAlchemy2.1.6、psycopg3.3.7、Alembic1.20.1；未使用验收环境代替正式运行环境。
2. 正式PM解释器经`runpy.run_path`执行`.build/postgresql/prepare_local_pg_rollout.py`：核对随机新名称不存在，显式`upgrade_schema`仅创建独立持久Schema`hermes_local_20261109_e6d5e1b8fb5b`；归属核对通过，110表、revision0028_kanban_effects、16领域及full_system_ready=true，exit0。该Schema与可清理的验收随机Schema分开，不修改已有业务表；此阶段Profile未改动。
3. `hermes gateway stop`：exit0，旧网关排空停止。正式PM解释器执行`configure_local_pg_profiles.py`：先备份两Profile完整config.yaml及.env，核对旧文件hash；通过官方秘密保存及原子配置写入接口设置storage.backend=postgresql。默认store_id=`profile-2053304a95b242e491f57c8886fc575a`，股票大师store_id=`profile-d4558d7645cc4fe4942f2b11a120b303`，各自稳定且不同。配置/.env不进入Git，无DSN写入YAML。
4. `hermes gateway start`：exit0，官方direct spawn启动PID26656；`hermes gateway status`：exit0，确认运行。`hermes db status`及`hermes --profile u80a1-u7968-u5927-u5e08 db status`各自返回全部16领域ready、full_system_ready=true及相应独立store_id。
5. 正式PM解释器执行`verify_local_pg_rollout.py`：exit0。独立进程核对真实网关running/session_store.status=ok、心跳未陈旧、served_profiles包含两者、新PM site-packages实际注入、运行代码9b292893eb。只读查询本次新Schema发现两store分别持久化runtime_epoch、state_meta、Cron/room/Kanban锁等启动行，默认另有实际Kanban默认board。切换前停机后记录的根部SQLite主文件SHA256仍一致；进程根部.db打开句柄为空。句柄/文件检查只是补充，不能替代业务读写验收。

本地运行证据为`.build/postgresql/local-pg-rollout-state.json`与`local-pg-live-readiness.json`；状态live_pg_ready。完整原配置及.env备份在`C:/Users/Ethan/AppData/Local/hermes/backups/local-pg-rollout-20261109-07fcdaa335/`按Profile分目录，秘密不提交。首次诊断误用未安装的PyYAML已改用项目hermes_yaml；初次运行检查脚本错误地期待session_store.status=ready，实际协议只允许ok/unavailable/retrying，核对协议后改为ok并通过。两者均为操作检查脚本问题，无产品代码修改，不计业务测试红绿。

恢复方式：需要停止试运行时，先用`hermes gateway stop`排空；将两个Profile各自的storage.backend通过官方config接口改回sqlite，再启动网关，即读取独立保留的旧SQLite数据。必要时参照上述配置备份恢复原设置；不要覆盖试运行后其他配置变更。PG试运行期间的新记录仍留在PG，不向SQLite回迁；保留新Schema和两个store_id以便再次选择原PG数据集。不要把PM依赖切换或配置恢复当作PG数据回滚，也不要自动降级生产代码。

验证边界：本次是用户授权的运行配置、显式迁移、真实启动持久行及重启就绪核对；没有向外部平台发送测试消息，也没有在正式Profile写入测试会话。完整PG业务689及Matrix实SDK证据仍按冻结生产等价范围引用，不因运行切换重命名为本次测试。七项非WSL POSIX验收仍未验证，Task24保持in_progress、23/24、总体BLOCKED/CHANGES_REQUIRED。本次仅文档进入本地commit；`PM Python -X utf8 scripts/check --staged --base 9b292893eb`实际14检查通过、no measured files changed、exit0，日志`local-pg-rollout-docs-checks.log`。独立foundation已逐项只读核对脚本/JSON/计划/Git，在其followup报告第919行起确认本次运维范围未发现blocking/major，明确不扩大业务验收结论；此后仅补检查结果及独立复核文字，diff-check通过。以本地标题`docs(storage): record local PostgreSQL trial restart`保存运行与恢复记录，不是Task24完成提交。

### 历史恢复记录

以下保留当时结果与恢复位置；其中“下一步/仍在运行”是历史状态，不替代上述当前恢复点。

metrics恢复`2a2684390016a1bfadc4c759bf2151945425f077`已实际Linux13文件34项及新冻结Native36文件714项全过；先前ed0真实worker模型PG计数0的红已由owner通道局部整改，不用旧owner20项替代。RetainDB `ed0cdbe604`与verification `c0558e9c13`证据继续保留，三个真实managed领域在加入quiesce后另6项通过。

Telegram原基线pre-entry取消major的实际恢复提交为`692382575f`，宿主两项夹具恢复为`29796fc67d3580adbea66ce83306ded4ee7007c0`。在297新冻结且实际准备Node compilers后，原失败48文件761pass/10fail，另同ref的FAL38pass；十项集中非WSL私有页7、真实更新编译2、managed压缩1。两份旧tools失败已局部闭合，不再列为下一步。

更新编译candidate仅补微型workspace必需的真实运行时辅助脚本及打包输出断言，原完整文件16pass/0fail/0skip、退出0/40.4秒（unified-task24-update-compiler-candidate.log），不修改生产builder、不跳过真实编译。独立foundation复核接受该局部修正；首轮静态13/14通过，旧审查历史故障字面路径缺标注导致no-tmp红，补历史证据注释后最终14检查全过、health1文件0blocking/0advisory、退出0（update-fixture-checks-final）。以标题`test: include runtime helpers in update build fixture`保存本地恢复commit，不是Task24完成提交。Windows/Linux另只读核对验收数据库身份且均in_recovery=false/available=true（current-ready-{windows,linux}），不操作服务。

压缩原冻结单文件2pass/102.5秒、原清单并发组6文件52pass/107.8秒（compress-observed/compress-load-observed），均0fail/退出0，未修改源码或原30秒期限；尚未再现HISTORY_8超时，不据此声称根因修复。下一步从新恢复ref统一重建最终四套PM载荷与新冻结全PG/Native门禁，保留压缩故障观测和原红证据。

当前Matrix关闭/生命周期恢复候选最后静态`PM Python scripts/check --staged --base 69d455ccd377`已14检查通过、health10个Python文件0blocking/0advisory、退出0（matrix-close-fixture-checks-final），包含最终PG测试清理调整和更新审查报告。独立plugins已核对实际PG旧runtime双红、新runtime双绿及Matrix10文件31绿后关闭该major的局部状态；foundation接受identity/Relay夹具和真实窄验结算。将以标题`fix(storage): drain Matrix work and restore lifecycle tests`保存本地恢复提交，父提交69d455ccd3；本次不是Task24完成提交。后续冻结与载荷使用核对owner/容量/inode充足的隔离根，继续保留当前69d Native完整批次原失败再按最终清单整改复验。

所有必需生产整改收敛后统一重建四套发行载荷，执行当前完整PG/Native/故障/适用平台复验及独立终审。旧58d生产的完整PG659绿及Native62870pass44fail220errors726skip不外推到当前代码；后续工具424、Photon16、FAL38及局部整改证据见本账本。非WSL私有启动页七项仍待现成主机，不伪装OS；正式实例仍SQLite a875342384，未写正式Profile/秘密/既有业务表，不管理数据库服务，不推送/发布/PR/合并。

规划检查点提交标题：`docs(storage): plan unified database backends`，父提交`a875342384`；该本地提交包含本计划与范围修正，具体SHA通过该唯一标题定位。

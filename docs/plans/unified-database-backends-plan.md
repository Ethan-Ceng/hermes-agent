# Hermes 统一数据库后端实施计划

## 关联设计与恢复位置

- 设计：[系统统一数据库后端](../designs/unified-database-backends.md)。
- 前置成果：[会话阶段计划](postgresql-session-storage-plan.md)，基准提交 `a875342384`。
- 分支：`feat/postgresql-session-storage`；沿用独立普通分支，不重建、不覆盖已有成果。
- 用户最新要求：SQLite/PGSQL 是 `hermes_db` 的可选实现；选择 PG 后系统自有数据库不能仍依赖 SQLite。先完成计划，再实施。

## 当前进度

- 整体状态：`IN_PROGRESS`。
- 当前阶段：RetainDB持久pending队列实施。
- 当前任务：Task 18（completed；正在创建本地任务提交，随后进入Task19）。
- 已完成：18 / 24；会话阶段的17/18和原验证限制另行保留，不混入本计划计数。
- 阻塞：无待用户重新选择的技术方案；Matrix SDK/原生依赖和外部插件能力按对应任务核验，缺证据不得完成。
- 当前实际安装：正式Profile仍SQLite，已重启加载 `a875342384`；本轮不切换数据库或重启服务。
- 更新时间：2026-11-08（Asia/Shanghai）。

## 目标、约束与范围变化

1. 用统一的 `storage.backend` / `storage.postgresql` 选择整个Profile的自有数据库；这是目标配置，实施前旧会话配置仍是当前实现。
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

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 20：消除生命周期、健康与运维旁路

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 21：闭合全部入口与直接 SQL 消费者

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 22：建立单后端运行强验收

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 23：完善统一配置文档与独立发行验证

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 24：原生启动复验、最终验证与独立审查

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## 计划变更

| 日期 | 变更 | 原因与影响 |
| --- | --- | --- |
| 2026-11-07 | 撤销独立Cron/Kanban/rooms/插件SQLite排除，建立统一后端计划 | 用户明确可选意味着系统单后端可用；原会话成果复用，新域全部待实施 |
| 2026-11-07 | 统一选择提升至storage.backend | 避免组件配置造成运行时必须混用数据库；旧开发配置显式报错，不静默回退 |
| 2026-11-07 | Matrix单列完整SDK协议任务 | 源码实际传sqlite URL；不能凭PgCryptoStore类名或替换DSN判定已经统一 |
| 2026-11-07 | Task 9提前包含终态/派发直接依赖的底层附件元数据与workspace适配 | complete/review/spawn实调用链依赖原Task 10接口；避免通过跳过保存/清理完成Task 9，订阅/转移/剩余消费者仍归Task 10，24项总数与验收不变 |

## 最终验证

### 执行结果

- 单元/SQLite回归：未执行本计划验证。
- 真实PG各域/并发/故障/单后端审计：未执行。
- 独立安装/显式迁移/原生重启：未执行本计划全域验证。
- 静态/生成契约/适用构建：业务实现后按实际变化运行。
- 独立审查：未执行本计划代码审查；会话阶段报告保留为前置证据。

### 验收标准检查

- [ ] 单个Profile的所有自有数据库均服从一个后端选择。
- [ ] PG下完整业务矩阵实际工作且自有SQLite连接尝试为0。
- [ ] SQLite模式独立运行，不要求PG驱动/实例。
- [ ] 所有域作用域、幂等、锁、配额、重启和错误语义通过真实验证。
- [ ] 包括Matrix在内的维护插件有真实协议/存储证据，未用禁用功能通过。
- [ ] 显式迁移、独立发行及原生启动/关闭通过，数据库服务仍由用户管理。
- [ ] 最终验证与独立审查通过；无未处理blocking/major。

### 未通过与未验证

Task 1–9 已完成，Task 10–24 尚未完成；不得宣称全系统PG已完成。会话阶段已知的非WSL私有启动页适用平台缺口和波动记录继续保留，最终门禁需说明实际范围。

### 最终状态

尚未进入最终验证。当前为PLAN_READY；实施后的最终判定只用READY_TO_MERGE / BLOCKED / FAILED。

## 恢复点

Task 1–18已验收并各自创建本地commit（Task16 `8145fcafab`，Task17 `8ebb3e5691`，Task18标题 `feat(storage): persist scoped RetainDB pending queue`）。下一项Task19实际Matrix SDK协议及真实PG密钥往返；Task18 PG20 passed、SQLite30 passed、无PG依赖1 passed及14静态checks通过，无skip/retry。Task20维护及Task22普通daemon强验收尚未完成。分支仍为 `feat/postgresql-session-storage`，正式实例保持SQLite，未写正式Profile、秘密或业务表；不能由此宣称全系统PG已完成。

规划检查点提交标题：`docs(storage): plan unified database backends`，父提交`a875342384`；该本地提交包含本计划与范围修正，具体SHA通过该唯一标题定位。

# Hermes 统一数据库后端实施计划

## 关联设计与恢复位置

- 设计：[系统统一数据库后端](../designs/unified-database-backends.md)。
- 前置成果：[会话阶段计划](postgresql-session-storage-plan.md)，基准提交 `a875342384`。
- 分支：`feat/postgresql-session-storage`；沿用独立普通分支，不重建、不覆盖已有成果。
- 用户最新要求：SQLite/PGSQL 是 `hermes_db` 的可选实现；选择 PG 后系统自有数据库不能仍依赖 SQLite。先完成计划，再实施。

## 当前进度

- 整体状态：`IN_PROGRESS`。
- 当前阶段：统一配置与基础资源实施。
- 当前任务：Task 7（pending；Task 5 提交 `895e13cd6e`）。
- 已完成：6 / 24；会话阶段的17/18和原验证限制另行保留，不混入本计划计数。
- 阻塞：无待用户重新选择的技术方案；Matrix SDK/原生依赖和外部插件能力按对应任务核验，缺证据不得完成。
- 当前实际安装：正式Profile仍SQLite，已重启加载 `a875342384`；本轮不切换数据库或重启服务。
- 更新时间：2026-11-07（Asia/Shanghai）。

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

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 8：统一 Kanban Board、任务与依赖图

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 9：统一 Kanban run、派发与 Worker 回执

状态：pending

### 目标

派发认领、运行身份、租约与终态在 PG 多进程下保持准确。

### 涉及文件

- `hermes_cli/kanban_db_dispatch.py`
- `hermes_cli/kanban.py`
- `hermes_cli/kanban_owner_recovery.py`
- `hermes_cli/kanban_swarm.py`
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

### 验证方式

- 既有派发/Worker/恢复测试，经标准 runner 运行。
- PG 双进程认领、晚到回执、租约过期、owner重启与失败结算测试。

### 完成条件

同一任务不被重复派发，旧代次不提交，PG运行无SQLite协调锁。

### 执行结果

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 10：统一 Kanban 订阅、工作区引用与跨 Board 转移

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 11：统一房间元数据、事件与 replica

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 12：统一房间 driver、任务与 work records

状态：pending

### 目标

房间执行租约、任务代次和回执在 PG 保持原子性。

### 涉及文件

- `gateway/hosted_room_driver.py`
- `gateway/hosted_room_work_records.py`
- `tui_gateway/hosted_room_driver.py`
- `tui_gateway/hosted_room_prepare_stall.py`
- `hermes_db/operations/room_runs.py`
- `tests/hermes_db/postgresql/test_room_runs.py`

### 依赖与接口

- 前置：Task 11。
- 输出：房间调度完整工作，无SQLite协调锁或备用账本。

### 实施步骤

1. 适配admit/start/renew/stop/settle/recover及work record引用，复用房间权限护栏。
2. 保留单owner、执行代次、未知结果、取消竞争与晚到回执规则。
3. 调度等待、模型、外部peer访问均在短事务外，不用Python锁充当跨进程租约。

### 验证方式

- `scripts/run_tests.sh tests/tui_gateway/test_hosted_room_driver_runtime.py tests/tui_gateway/test_hosted_room_worker_capacity.py`
- PG多连接/进程租约、停止竞争、接管、旧回执及故障恢复。

### 完成条件

房间调度完整工作，无SQLite协调锁或备用账本。

### 执行结果

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 13：统一房间策略 checkpoint 与路由调用

状态：pending

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

### 验证方式

- 既有路由与policy checkpoint测试，经标准runner执行。
- PG实测两个router竞争、Stop与新消息插入、重开及旧水位提交拒绝。

### 完成条件

PG策略与路由路径不创建SQLite，旧准备结果不能覆盖新谱系。

### 执行结果

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 14：统一房间附件元数据与配额

状态：pending

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

### 验证方式

- 附件既有安全/限额/对账测试经标准runner执行。
- PG实测配额竞争、文件成功DB失败、DB成功清理失败、重复请求和重启。

### 完成条件

附件元数据无SQLite，文件与DB的失败窗口有明确恢复证据。

### 执行结果

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 15：统一指标、consent 与 outbox

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 16：提供插件可移植持久化协议

状态：pending

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

### 验证方式

- `scripts/run_tests.sh tests/plugins/test_plugin_storage.py`
- PG实测插件同key/namespace隔离、CAS、配额/保留、重开与不兼容API明确失败。

### 完成条件

插件存储能力可由PG独立提供，并有真实消费者合同；外部插件适配要求明确。

### 执行结果

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 17：统一 Discord 恢复账本

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

## Task 18：统一 RetainDB 本地 pending 队列

状态：pending

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

本任务尚未实施；实施后记录实际修改、偏差、提交与恢复点。

### 验证证据

验证命令尚未执行；不借用会话阶段测试将其标为通过。实施后记录实际命令、退出码、数量、环境和失败/跳过项目。

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

Task 1–6 已完成，Task 7–24 尚未完成；不得宣称全系统PG已完成。会话阶段已知的非WSL私有启动页适用平台缺口和波动记录继续保留，最终门禁需说明实际范围。

### 最终状态

尚未进入最终验证。当前为PLAN_READY；实施后的最终判定只用READY_TO_MERGE / BLOCKED / FAILED。

## 恢复点

Task 1–6 配置/领域基础、验证证据、Projects及Cron执行/incident/投递已验收；本地提交后从 Task 7 继续。分支与初始干净工作区已核对，正式实例仍保持 SQLite；开发未写正式 Profile、秘密或业务数据库。

规划检查点提交标题：`docs(storage): plan unified database backends`，父提交`a875342384`；该本地提交包含本计划与范围修正，具体SHA通过该唯一标题定位。

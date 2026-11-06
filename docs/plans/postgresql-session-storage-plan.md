# PostgreSQL 完整会话后端实施计划

## 关联设计

- [会话存储设计](../designs/postgresql-session-storage.md)
- [数据库层代码组织](../designs/postgresql-storage-code-layout.md)
- [SQLite 源码调研](../designs/sqlite-postgresql-research.md)
- 开发分支：`feat/postgresql-session-storage`（从 `develop` 创建，2026-11-06）。
- 用户授权范围：实施全部任务；每个 task 验证完成后创建本地 commit，不推送、发布或合并。

## 当前进度

- 整体状态：`IN_PROGRESS`，不表示完整后端已通过验证。
- 当前阶段：M3 完整接入（离线实现）；M1/M2 的真实 PG 验证尚未完成。
- 当前任务：Task 18（配置文档、最终验证与审查）；Tasks 4–17 为 verification_pending，真实 PG 与完整回归未通过。
- 已完成：3 / 18。
- 产品范围阻塞：无。用户已确认使用新库，不迁移旧数据。
- 执行前置条件：真实 PG 验证时需用户提供本地测试配置，实际版本、权限和扩展由 Task 4 检查；当前没有连接数据库。
- 最近更新时间：2026-11-07（Asia/Shanghai）。

## 已确定的实施边界

1. 数据库包命名 `hermes_db`，使用 SQLAlchemy Core + 同步 psycopg；表定义、数据仓储、完整操作、事务与连接资源分别组织。
2. 新 PostgreSQL Schema 从空库开始；不开发 SQLite → PG 整库导入、旧 Schema 升级、旧格式数据兼容、跨后端双写或数据回迁。Alembic 仍用于新库初始化及今后 PG Schema 的版本演进。
3. 保留 SQLite 可选运行模式及其已有测试；“无旧数据迁移”不等于删除当前业务字段、消息保真或本地功能。
4. 本轮覆盖主库会话/提示/消息/用量、运行账本/队列/Worker/租约/压缩/墓碑/路由/代次/心跳/委派、投递义务，以及 API 响应与 Run 幂等辅助存储。旧 SQLite schema_version 机制由 PG 的 Alembic 版本替代。
5. 不新增账号/登录系统；PG 采用共享 Schema + 稳定 store_id，所有键和查询遵守作用域，供后续服务端用户授权映射接入。当前 Profile 岛屿语义继续保留，不将 Profile、租户、用户混为同一实体。
6. 不迁移配置文件、Markdown、工作区、附件，也不替换 Cron/kanban/hosted rooms/插件的独立数据库。它们若依赖主会话存储，其主库调用仍须适配；独立持久化及多副本部署不能因此被宣称已完成。
7. 不设计 K8s 部署或直接改成 active-active 网关；现有 epoch/单一所有者和受管 Worker RPC 边界保留。数据库共享不是多副本执行安全的完成证据。
8. PostgreSQL 实例由用户管理。计划不安装、启动或运维数据库；配置、Schema 和独立测试命名空间属于接入实现。扩展由管理员准备，应用只检查并明确报错。

## 全局约束

- 每次模型调用的历史前缀、提示词与工具快照遵守现有缓存不变量；只有既有受控压缩流程可以改写上下文。
- Repository 接收当前 Connection 与作用域，不自行提交；Operation 拥有完整短事务。LLM、终端、浏览器与投递等待不占用事务。
- PG 连接、权限、Schema、扩展或版本不满足要求要明确失败；不能静默切回 SQLite、JSONL 或内存。
- 连接池按进程/连接目标复用；配置预算覆盖多进程与副本总连接数。后台任务、线程跳转、关闭和回调显式绑定拥有者 Profile。
- DSN 通过现有 Profile 秘密机制解析并脱敏；普通配置在 config.yaml。不得通过每请求修改 os.environ 或全局 search_path 切换用户。
- 使用 PM 管理依赖及锁；新增依赖必须有上下界，执行 hermes pm lock。禁止 raw pip/uv 修改 Hermes 环境。
- 测试一律 scripts/run_tests.sh；新包测试按仓库镜像规则放在 tests/hermes_db/，不是 tests/db/。测试使用隔离 HERMES_HOME，不操作用户业务数据。
- 并发测试用事件/屏障，不加依赖时间猜测的 sleep；SQLite 内部测试与后端业务契约分开。
- 现有 .gitignore 和 docs/ 有用户会话内修改。已核对并保留它们，普通分支已创建；用户已明确授权逐 task 本地提交，不 stash、清空、推送或合并。
- 新行为放主题模块，门面保持简短；不加入未使用的抽象、通用 SQL 字符串替换或永久双写。
- 测试/静态检查结果必须对应当时实际代码。任务完成后立即更新本计划，失败记录原因、已尝试内容和解除条件。

## 阶段与关键依赖

| 阶段 | 任务 | 可验证输出 |
| --- | --- | --- |
| M1 基础 | 1–5 | 稳定作用域、配置工厂、测试入口、新库 Schema |
| M2 业务语义 | 6–12 | 完整消息、运行账本、Worker、压缩、路由与删除 |
| M3 完整接入 | 13–17 | API 辅助存储、投递、搜索、文件依赖与所有入口 |
| M4 验证 | 18 | 真实 PG、SQLite 回归、静态检查、审查证据 |

所有普通接口接通前只在开发分支验证，不交付一份可部分写 PG、部分写 SQLite 的生产模式。

## 公共验证命令与环境

下列命令是未来实施时执行的 PowerShell 命令，本次没有运行。postgresql extra、测试文件和测试配置选项由对应任务创建后才可使用。

```powershell
hermes pm lock
. .\activate.ps1 -TestExtras 'all,postgresql'
$testRunner = 'D:\Programs\Git\bin\bash.exe'
$pgTestConfig = Join-Path $env:LOCALAPPDATA 'HermesTests\postgresql.yaml'
```

测试配置文件由用户在本地提供，包含独立测试数据库的连接秘密，不进入 Git。通过文件路径选项传递给 pytest，不把密码放在命令行，也不把应用凭据转发进标准测试环境。

```powershell
& $testRunner scripts/run_tests.sh tests/hermes_db
& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config $pgTestConfig
python scripts/check
```

没有真实 PG 配置时可完成部分纯单元测试，但不能把 PG 集成验证记录为通过。PG 主版本与扩展可用性在 Task 4 留下证据，发布只声明实际验证范围。

## 状态变更记录

| 日期 | 整体状态 | 当前任务 | 原因 |
| --- | --- | --- | --- |
| 2026-11-06 | IN_PROGRESS | Task 2 | Task 1 契约及源码链接校验完成；开始可选依赖 |
| 2026-11-06 | PLAN_READY | 无 | 用户确认新库、不迁移旧数据，完成任务拆分；尚未开始编码 |

## Task 1：固定作用域和当前业务契约

状态：completed

### 目标

为后续实现确定可检查的接口、作用域键和原子操作清单。

### 涉及文件

- docs/designs/postgresql-session-storage.md
- docs/designs/postgresql-storage-code-layout.md
- docs/plans/postgresql-session-storage-contracts.md（新增）

### 依赖与接口

- 前置：无；编码前先建立拟定普通分支并核对用户已有修改。
- 输出：没有无人负责的普通存储调用；跨作用域键与高风险原子操作都有明确约束。

### 实施步骤

1. 逐个登记 SessionDB 的实际消费者、门面外 runtime 函数、API 辅助存储和直接连接调用，区分业务接口与 SQLite 本地修复接口。
2. 固定共享 Schema + store_id：Profile 在服务端解析稳定 store_id；数据库行、唯一约束、外键、墓碑、幂等键和 epoch 都带完整作用域。不能从本机路径推导跨 Pod 身份。
3. 为每个实际业务方法标注所属任务、输入/返回结构、异常、事务边界和现有行为测试；当前使用的字段与功能不因“无旧数据”被删去。
4. 列明新 PG 数据允许的类型、原文/摘要字段的编码边界，以及全局消息 ID 与会话水位线的锁定契约。

### 验证方式

- 手工逐条检查契约清单：每个实际消费者都有后端实现归属；SQLite 文件维护方法明确列为后端专属。
- 手工核对相同 session_id、request_id、message_uid 在不同 store_id 下的唯一性与引用规则；不得仅给 sessions 加作用域。

### 完成条件

没有无人负责的普通存储调用；跨作用域键与高风险原子操作都有明确约束。

### 执行结果

已新增 postgresql-session-storage-contracts.md：250 个公开方法、258 个显式依赖消费者（保守静态扫描）、运行/Worker/API/投递清单、逐主题任务归属、作用域键/外键、完整事务与锁顺序、watermark 和编码边界。创建独立普通分支，保留原 .gitignore 和其他 docs。未更改业务代码。

### 验证证据

2026-11-06，Python 3.12.10：执行 .build/postgresql/inventory.py（exit 0），解析 10,732 个 Python 文件；手工复核 SessionDB MRO、runtime/worker、API 两存储、delivery、直接连接与路径耦合。执行源码链接/行号锚点校验（exit 0），所有索引有实现任务归属。未连接数据库；本任务为契约文档核对，不声称运行验证。

## Task 2：声明 PostgreSQL 运行依赖并锁定

状态：completed

### 目标

用项目 PM 提供可选 PostgreSQL 依赖，保留无需 PG 驱动的 SQLite 安装。

### 涉及文件

- pyproject.toml
- uv.lock
- tests/hermes_db/test_optional_dependencies.py（新增）

### 依赖与接口

- 前置：Task 1。
- 输出：依赖与锁一致；SQLite 最小路径无需 PG extra，PG extra 可由 PM 选择安装且驱动可导入。

### 实施步骤

1. 声明 postgresql 可选依赖，包含兼容项目 Python 范围的 SQLAlchemy、psycopg 与 Alembic，并按 PM 规范设置上下界；实际版本在实施时核查官方兼容说明。
2. 运行 hermes pm lock；使用 PM 激活带 postgresql extra 的测试环境，不通过 raw pip/uv 修改环境。
3. 验证 SQLite 最小安装不会因声明可选依赖而强制安装或导入 PG 驱动，PG extra 可以由 PM 选择安装；工厂的缺驱动错误路径由 Task 3 实现和验证。
4. 在 pyproject.toml 的 setuptools 包发现中登记 hermes_db 与子包，并为 Alembic 配置/版本资源设置发布规则；不能只在源码目录可导入。安装制品验证在 Task 18 完成。

### 验证方式

- `hermes pm lock`
- 按照下方公共准备命令激活测试环境。
- `& $testRunner scripts/run_tests.sh tests/hermes_db/test_optional_dependencies.py`

### 完成条件

依赖与锁一致；SQLite 最小路径无需 PG extra，PG extra 可由 PM 选择安装且驱动可导入。

### 执行结果

声明 postgresql opt-in extra（SQLAlchemy>=2.0.44,<3、psycopg>=3.3,<4、Alembic>=1.17,<2），binary 按支持平台启用；登记 PM anchors、包发现与迁移资源。新增 hermes_db 无驱动导入入口和 SQLite 隔离启动/同步 PG dialect 测试。

### 验证证据

2026-11-06：项目 `python -m pm.cli lock`（hermes pm lock 同一入口）初次 exit 1：Android 无 psycopg-binary wheel；修正 binary 平台标记后 exit 0，二次检查锁已 current（exit 0）。官方兼容性：[SQLAlchemy](https://docs.sqlalchemy.org/en/20/intro.html)、[psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html)、[Alembic](https://alembic.sqlalchemy.org/en/latest/front.html)。PM `python -m pm.build_env --source . --out .build/postgresql/test-env --extra postgresql --group dev --group test` exit 0。Python 3.14.9，SQLAlchemy 2.1.6、psycopg 3.3.7、Alembic 1.20.1 实际导入通过，无网络连接。标准 runner `tests/pm/test_extras.py` 19 passed；新 optional_dependencies 首次 1 passed/1 failed（测试误传 str 给原 SessionDB），改为 Path 后重跑 2 passed/0 skipped（exit 0）。SQLite 测试子进程主动屏蔽三种 PG 模块后完成真实临时库写读。制品内容在 Task 18 验证；未连接真实 PG。

## Task 3：实现配置解析、工厂和资源生命周期

状态：completed

### 目标

让服务端按明确配置创建数据库作用域句柄并复用连接池。

### 涉及文件

- hermes_db/__init__.py、contracts.py、scope.py、settings.py、errors.py、factory.py、handle.py、engine.py（新增）
- hermes_db/legacy_sqlite.py（新增）
- hermes_cli/db_setup.py（新增）
- hermes_cli/config_defaults.py 及现有配置根键、秘密登记的实际所属模块
- tests/hermes_db/test_factory.py、test_scope.py、test_engine_lifecycle.py（新增）
- tests/hermes_cli/test_db_setup.py（新增）

### 依赖与接口

- 前置：Tasks 1–2。
- 输出：配置确有消费入口；资源所有权、Profile 绑定和秘密脱敏通过行为测试。

### 实施步骤

1. 实现 acquire_db(settings, scope) 与 DatabaseHandle；注入不可变作用域，明确 sessions/runtime 等接口持有和释放的责任。
2. 登记 storage.session 配置、postgresql.dsn_env/schema/store_id/池预算与超时；通过当前 Profile 的秘密解析获取 DSN，所有日志及诊断脱敏。
3. SQLite 分支复用现有 registry；PG Engine 按进程及连接配置复用，连接/事务按操作获取，禁止按用户或每次请求建池。
4. PG 缺凭据、无 store_id、连接失败或模式不兼容明确报错；开发分支内可逐步接通实现，但任何未实现功能都不得回落 SQLite/JSONL/内存。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/test_factory.py tests/hermes_db/test_scope.py tests/hermes_db/test_engine_lifecycle.py tests/hermes_cli/test_db_setup.py`
- `& $testRunner scripts/run_tests.sh tests/gateway/test_config_secret_scope.py tests/hermes_state/test_shared_session_db_registry.py`

### 完成条件

配置确有消费入口；资源所有权、Profile 绑定和秘密脱敏通过行为测试。

### 执行结果

已实现 driver-free contracts/scope/settings/errors、acquire_db/DatabaseHandle、SQLite registry/运行接口适配、延迟调用拥有者 Profile 绑定、进程与连接配置维度 Engine 复用和关闭、配置/秘密组合入口。storage.session 默认 SQLite，PG 显式 schema/store_id/DSN 秘密名称，池与连接等待/总预算校验；DSN 不出现在设置和池键 repr。DEFAULT_CONFIG 自动登记根键，OPTIONAL_ENV_VARS 登记 DSN。PG 完整实现之前工厂明确 StorageNotReadyError，绝不部分写 PG/SQLite。

### 验证证据

2026-11-06，PM Python 3.14.9：标准 runner `tests/hermes_db tests/hermes_cli/test_db_setup.py` 最新 37 passed/0 skipped（exit 0）。包括真实临时 SQLite 读写/共享释放、持有句柄在异 Profile 调用的 resume 限额、秘密上下文恢复、同步驱动缺失和假连接异常脱敏、Barrier 竞争的实际 SQLAlchemy Engine 复用。首次 Task 3 测试 32 passed/2 failed 是测试引用不存在的 scope seam 和错误的配置路由 seam，已修正并通过。计划回归 `tests/gateway/test_config_secret_scope.py` 31 passed；`tests/hermes_state/test_shared_session_db_registry.py` 13 passed/2 failed/3 posix skipped。两失败均为现有 TestMultiGenerationTeardownBarrier 删除打开文件的 WinError 32，在 bb221ec7d8 隔离源码基线（.build/postgresql/task3-base）用同一 runner/解释器 `-k TestMultiGenerationTeardownBarrier` 复现相同 2 failed/1 passed（exit 1），不是新工厂的回归，保留最终验收限制。`scripts/check --only ruff,health --base HEAD` exit 0，0 blocking/0 advisory。全工作区检查受忽略目录中的 PM cache/venv 归档和 Windows 默认 GBK 解码影响，改用 UTF-8 `scripts/check --staged --base HEAD` 验证拟提交内容；exit 0，14 checks 全部通过。未连接真实 PG，schema 检查在 Task 5 接通，PG 仍拒绝启用。

## Task 4：接通真实 PostgreSQL 测试配置与环境检查

状态：verification_pending（测试入口已实现；真实 PG 配置未提供，不能标 completed）

### 目标

通过标准测试入口对用户提供的独立测试数据库开展可重复验证。

### 涉及文件

- tests/hermes_db/conftest.py（新增）
- tests/hermes_db/postgresql/test_environment.py（新增）
- tests/hermes_db/test_test_config.py（新增）
- docs/plans/postgresql-session-storage-contracts.md

### 依赖与接口

- 前置：Tasks 2–3；执行真实测试前由用户在本地提供测试配置。
- 输出：真实 PG 版本与能力有证据；无配置、坏配置和归属保护均有测试，未接入数据库时本任务不能标 completed。

### 实施步骤

1. 实现 --postgres-test-config 文件参数，由测试 fixture 读取 DSN 与允许使用的测试数据库；不通过命令参数或日志传递密码，也不扩大 run_tests.sh 的环境变量白名单。
2. 真实 PG 测试使用 integration 标记与现有网络 opt-in 机制；普通测试不连接数据库。显式选中集成测试但缺配置或不可达时应失败，不能跳过后报告通过。
3. 记录实际 PG 主版本、客户端版本、TLS、权限和 pg_trgm 可用性；测试不得自动安装或管理数据库实例，扩展缺失时给管理员明确准备说明。
4. 仅创建本轮唯一命名并标记归属的测试 Schema；拒绝复用/删除已有业务 Schema；退出时只清理本轮持有的测试对象。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/test_test_config.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_environment.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

真实 PG 版本与能力有证据；无配置、坏配置和归属保护均有测试，未接入数据库时本任务不能标 completed。

### 执行结果

已实现 --postgres-test-config 路径参数、安全 YAML 读取与目的/独立数据库核对、显式集成 opt-in 和网络 marker、版本/权限/扩展/TLS 探针、唯一临时 Schema 创建和 marker 归属清理。管理员准备 pg_trgm；测试不安装数据库或扩展。配置示例与正确 runner 自定义参数透传已写入 contracts。

### 验证证据

2026-11-06，PM Python 3.14.9：`scripts/run_tests.sh tests/hermes_db/test_test_config.py` 初次 10 passed（exit 0），新增非法 DSN 情况后最新 11 passed/0 skipped（exit 0）；UTF-8 `scripts/check --staged --base HEAD` 全部 14 checks 通过（0 blocking/0 advisory）。显式 `scripts/run_tests.sh tests/hermes_db/postgresql/test_environment.py -- -m integration` exit 1，0 passed/1 fixture error，清楚要求 --postgres-test-config，证明缺配置没有被 skip 当作通过；无真实连接尝试。默认示例文件 LOCALAPPDATA/HermesTests/postgresql.yaml 不存在。真实 PG 版本/权限/扩展/TLS/DDL 未验证，任务保持 verification_pending。

## Task 5：创建新库 Schema 与显式版本管理

状态：verification_pending（Schema/迁移/命令实现已完成离线验证；真实 PG DDL 等待 Task 4）

### 目标

把全部本阶段业务表和约束建到空 PostgreSQL Schema，并提供版本检查。

### 涉及文件

- hermes_db/tables/metadata.py、conversations.py、runtime.py、gateway.py、api.py（新增）
- hermes_db/migrations/env.py、versions/、alembic.ini（新增）
- hermes_cli/db_cmd.py、db_parser.py（新增）及现有 CLI 注册入口
- tests/hermes_db/postgresql/test_schema.py（新增）
- tests/hermes_cli/test_db_commands.py（新增）

### 依赖与接口

- 前置：Tasks 1–4。
- 输出：空库可以重复初始化，全部业务表、作用域约束和版本行为经真实 PG 验证。

### 实施步骤

1. 按契约建立 sessions/messages/prompts/usage、运行账本、路由/代次/租约/委派、delivery_obligations 与 API 6 表；PG 使用 Alembic 版本，不复制 SQLite SCHEMA_VERSION=32 或其 schema_version 升级流程。
2. 设置完整作用域的主键/唯一键/外键/索引；当前浮点值按 DOUBLE PRECISION 评估，消息旁路和原文保真字段按契约存储；逐项登记业务触发器由何处保留。
3. 提供拟定 hermes db status 与 hermes db upgrade；普通启动只检查连接及版本，迁移命令串行执行 Schema 变更。
4. 验证空库初始化、重复 upgrade、并发初始化拒绝/串行化、Schema 版本不匹配及权限不足；不开发 SQLite 数据导入器。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_cli/test_db_commands.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_schema.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

空库可以重复初始化，全部业务表、作用域约束和版本行为经真实 PG 验证。

### 执行结果

已声明 24 个 Core 业务表（含稳定谱系 transcript_roots）、完整 store_id 复合键/引用、Double/Bytea 保真字段及索引；现有新 SQLite 主库字段覆盖检查通过。声明 Alembic 初始冻结 revision（不导入可变当前 metadata）、显式 schema 事务锁、非空无版本拒绝、未知版本和连接/池超时错误，以及 hermes db status/upgrade 的顶层 CLI 接线。SQLite 业务触发器与后续 Operation 落位已登记 contracts。PG 工厂仍拒绝完整启用。

### 验证证据

2026-11-06，PM Python 3.14.9：标准 runner `tests/hermes_db/test_table_contracts.py tests/hermes_cli/test_db_commands.py` 初次 8 passed；`tests/hermes_db tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_db_commands.py` 57 passed（exit 0），6 个 PG integration 测试按默认 marker deselected，不计通过。新增池超时/真实配置消费检查后受影响两文件重跑 8 passed。迁移资源由真实 Alembic ScriptDirectory 找到 required head。DDL 只编译/冻结，未在 PG 执行。静态检查首次 14 项中仅 Ruff 的三个 RUF015 测试迭代写法不合规，已修正，最新 UTF-8 `scripts/check --staged --base HEAD` 全部 14 项通过，health 0 blocking/0 advisory。最终完整离线局部回归同上命令 59 passed/0 failed（exit 0）；PG 集成 6 项 deselected，不计通过。真实空库 upgrade、重复升级、并发锁、跨 store FK 和权限场景均待 Task 4 配置，不能标 completed。

## Task 6：实现会话生命周期、提示快照、用量与查询

状态：verification_pending（离线实现与契约已通过；真实 PG 行锁/事务/隔离验收待配置）

### 目标

覆盖新 PG 会话的创建、读取、展示与元数据操作。

### 涉及文件

- hermes_db/session_store.py（新增）
- hermes_db/repositories/sessions.py、usage.py、prompts.py（新增）
- hermes_db/operations/sessions.py（新增）
- tests/hermes_db/contracts/test_sessions.py、test_prompts_usage.py（新增）
- tests/hermes_db/postgresql/test_sessions.py（新增）

### 依赖与接口

- 前置：Tasks 3–5。
- 输出：契约清单中本主题方法与全部当前字段有实现；提示原文、归属和用量一致。

### 实施步骤

1. 按 Task 1 清单实现创建/ensure、读取、列表、标题、模型配置、归档/隐藏/置顶、Telegram topic 等当前使用的方法与返回结构。
2. 保持系统提示和工具快照的精确内容及哈希；不在会话中途重新组装提示或改变工具前缀。
3. 实现按当前全部维度累计用量和费用状态；普通记录在连接结束前取出，不向上返回连接或 ORM 实体。
4. 以现有 SQLite 实现和新 PG 实现执行业务契约；旧 SQLite 文件修复语义继续留在原模块。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_sessions.py tests/hermes_db/contracts/test_prompts_usage.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_sessions.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

契约清单中本主题方法与全部当前字段有实现；提示原文、归属和用量一致。

### 执行结果

离线实现检查点：新增会话/提示/用量与有界列表仓储、短事务、构造/生命周期操作、元数据/标题/Topic 门面及有序后台用量 writer。22 项共享契约分别在原 SQLite 和隔离 Core 路径执行，覆盖首次结束、父链/分支继承、标题优先级/唯一性/转移、模型与原文快照、全部计费维度、NULL 计数、Topic 和列表过滤。补充跨 store 与事务回滚、拥有者 Profile/秘密上下文、未知提交不重放测试。契约清单逐方法核对；三项导出/删除保护的归属纠正为 Task 12，未删除功能。

初始未发布 revision 同步为 26 表/15 索引：补齐 SQLite 按需创建的两张 Telegram 表、工具快照归属外键、标题唯一约束、用量同时间排序、消息预览投影列（写入在 Task 7）。普通写入持谱系映射共享锁，父链归并持独占锁；控制键不可被后续清理。读取使用短 REPEATABLE READ 快照，写入使用同根行锁；配置入口与实际事务均应用 lock/statement timeout。PG 工厂仍禁止生产启用，待完整能力接线。

### 验证证据

2026-11-06：首次共享契约执行 11 SQLite passed / 11 Core fixture error（实现缺失，exit 1）；实现后两文件 22 passed。列表共享契约首次 11 passed/1 failed（测试误把 JSON 路径当字面键），按原 SQLite 路径语义修正后 12 passed。均用 scripts/run_tests.sh，PM Python 3.14.9。未连接真实 PG；Core 使用隔离 SQLite 的离线 SQLAlchemy 执行，不计 PG 验证。

最新离线回归：`HERMES_PYTHON=.build/postgresql/test-env/Scripts/python.exe`，`bash scripts/run_tests.sh tests/hermes_db tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_db_commands.py`：exit 0，18 文件、114 passed、0 failed，15.2 秒；日志 `.build/postgresql/task6-tests.log`。真实 PG 28 项用例由默认 integration 过滤排除，不计通过。默认独立 PG 配置文件仍不存在。`PYTHONUTF8=1`，PM Python 执行 `scripts/check --staged --base HEAD`：exit 0，14 checks ok，health 39 文件、0 blocking/0 advisory（日志 `.build/postgresql/task6-checks.log`）。

## Task 7：实现完整消息写入与历史读取

状态：verification_pending（离线实现/共享契约通过；真实 PG 竞争与驱动验收待配置）

### 目标

在一个完整事务内维护消息正文、旁路字段、身份和计数。

### 涉及文件

- hermes_db/repositories/messages.py（新增）
- hermes_db/operations/messages.py（新增）
- hermes_db/postgresql/transactions.py（新增）
- tests/hermes_db/contracts/test_messages.py（新增）
- tests/hermes_db/postgresql/test_messages.py（新增）

### 依赖与接口

- 前置：Tasks 5–6。
- 输出：消息所有当前业务字段保真，失败回滚，历史读取不改变模型上下文及显示顺序。

### 实施步骤

1. 实现 append_message、批量追加、活动/压缩消息读取及 API conversation 投影，覆盖工具调用、推理、多模态 api_content、UID、显示身份及显示顺序。
2. 在统一锁定与事务内执行写入保护、消息变更和计数/修订维护；Repository 不自行提交。
3. 保持当前消息边界与编解码行为，验证批量失败无部分写入；新库不实现旧格式脏数据兼容。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_messages.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_messages.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

消息所有当前业务字段保真，失败回滚，历史读取不改变模型上下文及显示顺序。

### 执行结果

从 Task 6 检查点 7fd192bb81 继续。先建立共享消息契约，再实现原文编解码、事务写入/修订、稳定身份与回放。真实 PG 验证仍未具备配置。

已实现消息仓储、完整操作与 reads/edits/lookup/reactions/results 主题门面。纯编解码、显示去重及 conversation 投影复用既有业务规则，不执行 SQLite SQL。新 BYTEA 正文带明确文本/二进制标签，原文中的 NUL/Unicode 与结构化内容、API/推理旁路保真；预览/搜索是分离投影。批次全部写入或回滚；与当前 SQLite 相同，显式 chunk_rows 允许逐块提交，跨块工具 UID 先分配，不能把整个分块导入视为单事务。

消息追加、替换、重写、watermark 共享谱系根锁；显示身份/顺序、计数、revision 与正文同事务维护。调用者的物理行戳只在提交确认后发布，逻辑 UID 在事务前分配并在未知提交时保留；不自动重放。实现 CAS winner 采用、可恢复撤回、反应已读、结果通知幂等和有界 Todo 恢复。新增两条显示索引并同步冻结 revision，当前 26 表/17 索引。

审计清单 Task 7 的 42 方法均有实现。archive_and_compact 的归属修正为 Task 10，与完整压缩发布/尾部合并算法一并实施，不以接口空壳提前满足 Task 7。该功能未被移除；消息读取已支持 compacted 历史。普通 PG 工厂仍保持关闭门禁。

### 验证证据

2026-11-06：首次 6 共享消息契约为 SQLite 6 passed/Core 6 failed（缺接口，exit 1）；实现后 12 passed。扩展后全部 contracts 一轮 79 passed。最新标准 runner：`HERMES_PYTHON=.build/postgresql/test-env/Scripts/python.exe`，`bash scripts/run_tests.sh tests/hermes_db tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_db_commands.py`：exit 0，22 文件、148 passed、0 failed，18.6 秒；日志 `.build/postgresql/task7-tests.log`。`PYTHONUTF8=1`，PM Python 执行 `scripts/check --staged --base HEAD`：exit 0，14 checks ok，health 22 文件、0 blocking/0 advisory；日志 `.build/postgresql/task7-checks.log`。

Core 离线 fixture 在测试中模拟 SQLite 缺少的复合键 IDENTITY，仅用于顺序契约；不能证明 PG sequence/提交顺序。新增 PG 消息共享契约 16 项、同 schema 隔离 1 项、两项根锁阻塞实测（pg_blocking_pids）；均未执行。目前全部真实 PG 47 用例按默认 integration marker 排除，不能计 passed。原 SQLite 共享路径、未知提交确认丢失的受控离线注入、所有权/CAS/回滚/显示边界已有测试；实际 PG DDL、锁/连接故障待配置。

## Task 8：实现准入队列、epoch 与终态事务

状态：verification_pending（离线准入/终态实现与契约通过；真实 PG 竞争/故障待配置）

### 目标

在 PG 多连接竞争下保持每会话准入、FIFO 和代次栅栏。

### 涉及文件

- hermes_db/operations/runtime.py（新增）
- hermes_db/repositories/runtime.py（新增）
- hermes_db/postgresql/transactions.py
- tests/hermes_db/contracts/test_runtime.py（新增）
- tests/hermes_db/postgresql/test_runtime.py（新增）
- tests/hermes_state/test_runtime_admission.py（行为依据，按需提取共用用例）

### 依赖与接口

- 前置：Tasks 6–7。
- 输出：同时准入、领取、旧代次、崩溃恢复和水位线测试通过；失败不产生部分状态或重复执行。

### 实施步骤

1. 实现 scoped epoch、准入去重/摘要冲突、队列容量、严格同会话 FIFO、领取、取消、终态及重启 unknown 状态。
2. 按稳定会话记录和统一顺序加锁；不存在记录时由父记录/约束保证竞争安全；不能用 SKIP LOCKED 绕过同会话队头。
3. 用事件/屏障构造交错提交，验证消息 sequence 与 transcript mark 的关系；若当前主键水位线不足，先更新设计，再引入有明确用途的会话内顺序字段。
4. 分类可重试事务冲突与未知提交；没有提交结果证据时以请求身份查询，不重新执行外部效果。
5. 清点 _authorize_write/_guard/_terminal_write 等连接级回调中的 SQLite SQL，在数据操作内通过 Repository 实现等价检查；不能把必须同事务的授权、所有者门禁或退休检查提前到事务外，也不能原样把 SQLite 回调交给 PG Connection。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_runtime.py tests/hermes_state/test_runtime_admission.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_runtime.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

同时准入、领取、旧代次、崩溃恢复和水位线测试通过；失败不产生部分状态或重复执行。

### 执行结果

从 Task 7 commit 22c6fb7924 开始。先固定 epoch/去重/FIFO/代次/unknown 共享契约；连接级旧 SQLite 回调不能原样交给 PG，必须转为显式 Core 事务效果并在锁内执行。

已实现 PostgresRuntimeStore、scoped epoch 与准入仓储、FIFO/容量/摘要冲突、领取/generation、取消/steer/revert、重定向、恢复 unknown、显式解除 unknown、终态结果与 Worker 收尾。私有回调必须是显式 CoreEffect，在拥有者 Profile/秘密上下文和同一事务内执行；失败回滚，已接受请求重放绕过新准入授权。读取/约束均带 store_id。

epoch 行共享锁先于映射和根锁，启动更新 epoch 等待旧写入结束；普通账本事务按序锁运行范围内全部根（包含 Local reset 后物理目标），不使用 SKIP LOCKED 跳过队头。终态/unknown 收尾及启动恢复使用短映射独占栅栏，先等子 Worker 写入完成，再退休跨根子任务；不跨外部效果持锁。transcript_mark 改为当前逻辑执行及其物理谱系范围的 MAX(id)，不受其他 store/谱系 sequence 干扰；根锁先于分配/领取，保留“本轮行位于 mark 之后”的业务用途。

清单的 Worker 接口改归 Task 9，完整 revision-fenced mutate/receipt runner 改归 Task 12（覆盖其中的删除/重写/准备发布动作），消除清单粗归属造成的反向依赖。Task 8 保留准入/领取/终态回调边界。import_legacy_session_admissions 明确 SQLite 专属，PG 新库不实现旧队列导入；Task 17 接线须禁止调用。业务范围没有删减。

### 验证证据

2026-11-06，PM Python 3.14.9 + scripts/run_tests.sh：首次基础共享契约 SQLite 3 passed/Core 3 fixture error（缺模块，exit 1）；实现后 6 passed。扩展后 Runtime 两文件 16 passed，覆盖 FIFO/容量/去重、unknown、steer、rehome、跨 store、压缩子段互斥、reset 后 mark 和授权/终态回滚。新增测试曾因插入位置造成 NameError，已修正并复验；lint 的 pairwise/unused/next 建议已整改。

一轮 `bash scripts/run_tests.sh tests/hermes_db tests/hermes_state/test_runtime_admission.py tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_db_commands.py`：exit 0，26 文件、166 passed/0 failed，18.7 秒（`.build/postgresql/task8-tests.log`）。终态锁顺序/generation 整改后受影响三文件 18 passed，exit 0，7.8 秒（task8-affected.log）；SQLite fixture 可选依赖隔离补测两文件 14 passed，exit 0，26.9 秒；增加提交确认丢失/同请求查询及精确重放测试 1 passed，exit 0，10.9 秒，无事务效果重放。

`PYTHONUTF8=1`、PM Python 执行 `scripts/check --staged --base HEAD`：exit 0，14 checks ok、0 blocking/0 advisory（task8-checks.log）；后增确认丢失测试及 fixture 调整的最新 ruff/health 两项也通过。真实 PG 新增 12 用例（6 共享/4 隔离与效果/2 多连接竞争），均未执行；合计 59 PG 用例默认 integration 排除，不计通过。Core fixture 的序号模拟不能验证 PG 锁或提交顺序。

## Task 9：实现 Worker 回执与异步委派存储

状态：verification_pending（离线主题实现/契约与检查通过；真实 PG 回执/竞争待配置）

### 目标

保持子执行结果的幂等、序列和所有者代次检查。

### 涉及文件

- hermes_db/operations/workers.py（新增）
- hermes_db/repositories/workers.py（新增）
- tests/hermes_db/contracts/test_workers.py（新增）
- tests/hermes_db/postgresql/test_workers.py（新增）

### 依赖与接口

- 前置：Tasks 7–8。
- 输出：重复、乱序和旧代次结果均有行为证据；Worker 持久化边界不被绕过。

### 实施步骤

1. 实现 worker_executions、worker_receipts、async_delegations 的实际消费操作，保留请求摘要、序列、generation 和旧结果拒绝规则。
2. 验证重复回执不会重复追加消息或累计用量，失效 Worker 不覆盖新一轮结果。
3. 保持 compute Worker 通过已有所有者 RPC 提交；不在此任务给 Worker 增加主库直连能力。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_workers.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_workers.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

重复、乱序和旧代次结果均有行为证据；Worker 持久化边界不被绕过。

### 执行结果

从 Task 8 commit 5b68f4ebd6 继续。先固定 Worker assignment/sequence/adoption 与重复回执契约；复用已实现的短事务、消息操作和 worker_retirement。保持所有者 RPC，不给 Worker 增加主库直连能力。

离线主题实现覆盖 Worker 登记/采用、assignment/epoch/generation/sequence/摘要、同事务操作与回执、重复重放、父子执行退休、构造/元数据/提示/工具快照/用量/消息/turn lease 的闭合集合。连接级 DML 观察只覆盖 handler，回执自身写入不会推进只读业务 revision；事务失败不发布注释或部分写入。所有 Worker 回执先取得短映射独占栅栏，避免创建子根/全局标题操作在持根锁后升级。

补齐 Worker 委派闭合操作与 Owner 委派存储：dispatch/partial child/complete/read/claim/ack/drop/defer/release、pending/orphan/failure 查询、恢复 CAS、再投递预算和有界清理。PID/birth 验证与恢复提示的文件/进程 I/O 在数据事务外；恢复比较 owner/state/时间及 JSON 快照，不覆盖后续真实完成。PG 缺少应有的委派记录时明确拒绝领取，不走旧“未持久化事件可直接投递”的许可分支；SQLite 行为保留。普通消费入口接线仍归 Task 17。

初始未发布 Schema 同步为 26 表/18 索引。worker_receipts 增 read_snapshot/title_candidate 投影，前者收尾时不解析包含 NUL 的完整提示 JSON，后者为候选标题保存精确回执授权；子执行改用转义前缀与 pattern 索引，不依赖 PG 文本语言环境的范围排序。抽出标题与追加的连接内操作；构造时回收被 keep-existing 忽略的新提示快照。压缩专用 Worker handlers 在 Task 10 随完整压缩事务接入，不提供空壳。

### 验证证据

2026-11-06，PM Python 3.14.9 + scripts/run_tests.sh：首批共享契约 SQLite 3 passed/Core 3 failed（缺接口，exit 1）；实现后 6 passed。扩展元数据和标题回归三文件 34 passed；委派共享 4 passed；子预留/回执故障/跨 store 3 passed；Owner 恢复/预算/清理与构造回归三文件 31 passed。

整轮 `bash scripts/run_tests.sh tests/hermes_db tests/hermes_state/test_runtime_worker.py tests/hermes_state/test_runtime_worker_metadata.py tests/hermes_state/test_worker_lineage_exclusion.py tests/hermes_state/test_runtime_worker_children.py`：exit 0，34 文件、186 passed/0 failed，45.6 秒（`.build/postgresql/task9-tests.log`）。随后补 Worker 租约、重复用量及新代次拒绝旧回执，受影响两文件 14 passed/0 failed，exit 0，4.6 秒。

`PYTHONUTF8=1`、PM Python 执行 `scripts/check --staged --base HEAD`：exit 0，14 checks ok，health 28 文件、0 blocking/0 advisory（task9-checks.log）。未执行真实 PG；新增 Worker/委派 16 个 PG 用例，合计 75 个 PG 用例按默认 integration marker 排除，不能计通过。独立 PG 配置仍不存在；不存在真实驱动、锁竞争或吞吐验证证据。普通入口与 Worker RPC 消费接线在 Task 17，当前不能把此开发检查点当作可用 PG 生产模式。

## Task 10：实现租约、压缩与谱系提交

状态：verification_pending

### 目标

避免租约竞争造成并发压缩分叉，并保留压缩期间新增消息。

### 涉及文件

- hermes_db/operations/compression.py、leases.py（新增）
- hermes_db/repositories/compression.py、leases.py（新增）
- tests/hermes_db/contracts/test_compression_leases.py（新增）
- tests/hermes_db/postgresql/test_compression_leases.py（新增）
- tests/hermes_state/test_compression_watermark_commit.py、test_compression_lease_refresh_before_publish.py、test_session_turn_lease.py（依据）

### 依赖与接口

- 前置：Tasks 7–9。
- 输出：接管/续租交错、发布前续租、晚到消息和重启后谱系均通过真实 PG 验证。

### 实施步骤

1. 用稳定谱系根锁定压缩/回合租约；以 holder 条件续租，保留过期但未被他人接管时允许续租的现有语义。
2. 实现过期回收、领取、刷新、释放及发布检查，显式区分本地主机 PID namespace 证据与跨节点实例身份。
3. 原子提交压缩结果，保留并发尾部、归档标志、所有旁路字段和 UID；不重新激活旧上下文。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_compression_leases.py tests/hermes_state/test_compression_watermark_commit.py tests/hermes_state/test_compression_lease_refresh_before_publish.py tests/hermes_state/test_session_turn_lease.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_compression_leases.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

接管/续租交错、发布前续租、晚到消息和重启后谱系均通过真实 PG 验证。

### 执行结果

已实现公开回合/压缩租约、归档压缩、原子子会话发布、冷却/anti-thrash 状态和保守孤立恢复，以及全部 Worker compression/cleanup/history/lineage handlers。所有操作复用当前 Connection 和 store_id；LLM、等待与回调在事务外，回调绑定拥有者 Profile。PG 的 holder 是共享命名空间中的不透明身份，统一按租约到期回收，不调用当前主机 PID 探测去回收远端 holder；过期未接管仍可条件续租。55P03 仅在事务体确认回滚后分类为 StorageBusyError，提交阶段仍是 UnknownCommitError。

Coverage 仅复用现有无 I/O 的身份/版本证明函数；Core 仓储提供本 store 的 detached active rows，不继承 SQLite SQL。归档在同一根锁事务内完成 held CAS、named/merged/retired coverage、尾部识别、归档标记、BYTEA/UID/所有列的 INSERT SELECT 克隆、显示去重、计数/config/revision。发布同事务检查/续租、关闭父会话、继承路由/提示/工具 pin/归档状态、插入完整子会话及晚到尾部，并原子推进 Local route/receipt；路由冲突回滚全部内容。

Worker 发布将 execution 的物理目标和 admission lineage 同事务推进，FIFO/idempotency 逻辑键不变；丢失回复按原 assignment/sequence/digest 精确重放。Worker receipt 新增 assignment_parent/assignment_session 投影，原始 assignment 查询不把可能含 NUL 的整段 result_json 转成 JSONB；26 表/18 索引的未发布初始 revision 已同步。旧只读快照退休规则保留。

新增根回填租约契约复现了租约遗留旧根的问题；构造器在已有映射栅栏和两个根锁下原子转移租约，两个不同有效 holder 拒绝合并，失败不改变 parent 字段。SQLite 原实现未改。Task 16 的旧压缩链维护仍仅适用 SQLite，不为 PG 增加旧数据兼容。

### 验证证据

- PM Python 3.14.9；全部通过标准 scripts/run_tests.sh。最初租约 4 passed/5 missing-interface failed、归档 4 passed/4 missing-interface failed、metadata 3 passed/3 missing-interface failed，建立红灯依据。实现后租约/事务错误 17 passed，归档/发布 16 passed；Worker RPC 丢回复/连续旋转/guard/谱系授权 4 passed。
- 整轮：tests/hermes_db + watermark/lease refresh/turn lease + 5 个 Worker compression SQLite 回归文件，45 files / 270 passed / 0 failed，29.1s，exit 0，日志 .build/postgresql/task10-tests.log。随后新增老子会话终结和 Local 路由冲突/回滚契约；受影响 metadata/atomicity 16 passed / 0 failed，exit 0。
- 根回填修复红灯：Core competitor 错误取得租约；修复后 atomicity + sessions 29 passed。Local route 冲突错误类型被 ValueError 外层覆盖，专门测试发现并修正；最新 16 项受影响测试通过。
- ruff/health 当前通过（35 files、0 blocking/0 advisory）；全量 staged scripts/check --staged --base HEAD 14 checks / 0 blocking / 0 advisory 通过，exit 0，日志 .build/postgresql/task10-checks.log。
- 新增 27 项真实 PG 压缩/租约/Worker/故障/并发用例，尚未执行；与前序合计 102 项 PG 用例未验证。仅 collect-only 尝试被 runner 按 0 实际测试返回 exit 1，不记为通过。默认本地 PostgreSQL 测试配置路径仍不存在；未连接 PG、未管理数据库服务/扩展。

## Task 11：实现路由、会话代次与整理状态

状态：verification_pending

### 目标

让路由与代次等会话关联状态使用同一选定后端和作用域。

### 涉及文件

- hermes_db/repositories/gateway.py（新增）
- hermes_db/operations/gateway.py（新增）
- tests/hermes_db/contracts/test_routing.py（新增）
- tests/hermes_db/postgresql/test_routing.py（新增）

### 依赖与接口

- 前置：Tasks 6–10。
- 输出：同名路由跨 store 不串数据，代次不回退，后台整理不调用 SQLite 文件维护。

### 实施步骤

1. 覆盖 gateway_routing、gateway_hygiene_state、conversation_generations、gateway_heartbeats 的实际方法，区分路由所属 store 和当前会话所属 store。
2. 保持 reset/压缩的代次差异和单调世代，不能因删除重用缓存身份；sessions.json 只作为现有可选镜像，不成为 PG 失败后的写入权威。
3. 整理和保留操作保留业务语义；VACUUM、WAL、FTS 修复等本地操作仅属于 SQLite 后端。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_routing.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_routing.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

同名路由跨 store 不串数据，代次不回退，后台整理不调用 SQLite 文件维护。

### 执行结果

从 Task 10 commit 0b0ea642f4 继续。已完成路由 scope/退休栅栏、心跳、hygiene 原子计数、交接状态 CAS、peer 自愈/重定向、reset 边界恢复、孤立会话报告/采用、从 Local 当前目标转到 messaging lane 的谱系/标题/receipt 结算、profile 精确重命名和候选整理选择。首批 routing 3 passed/4 missing-interface failed、peers 4 passed/4 missing-interface failed、rekey 2 passed/3 missing-interface failed 建立红灯依据，随后分组测试 15 与 13 项通过。新增代次契约发现 Task 6 的 source/key 缺少既有 strip 语义，已补齐并验证。所有查询、相关子查询和冲突检测带 store_id；profile 重命名不改 stable store_id。

依赖核对：prune_never_active_keyed_sessions 会调用删除/账本退休，本接口归属修正到 Task 12，复用完整墓碑事务；Task 11 已提供候选选择。功能保留，不添加占位删除。PG 固定完整 Schema，不移植 SQLite 可选列/旧表探测、旧 sessions.json 导入或数据库文件维护。

### 验证证据

- PM Python 3.14.9、scripts/run_tests.sh：整轮 tests/hermes_db + SQLite rekey/orphan/compression/turn-lease/Worker regressions，51 files / 321 passed / 0 failed，34.5s，exit 0，日志 .build/postgresql/task11-tests.log。随后当前 topic 身份与冲突、投递行归属契约补充验证：test_gateway_rekey.py 10 passed / 0 failed，exit 0。
- Task 11 审计清单 27 个公开接口均存在；prune_never_active_keyed_sessions 明确归 Task 12。当前无 SQLite 文件维护调用；未改 SQLite 实现。source/key strip 代次红灯 19 passed/1 failed 已修复，routing + sessions 31 passed。
- ruff/health 已通过；全量 staged scripts/check --staged --base HEAD 14 checks 通过，0 blocking/0 advisory，exit 0，日志 .build/postgresql/task11-checks.log。
- 新增 21 项真实 PG 路由/交接竞争/hygiene 并发累加/陈旧路由快照竞争用例未执行；累计 123 项真实 PG 验证待配置，不能计入通过。Schema 仍为 26 表/18 索引，无新依赖。

## Task 12：实现删除、退休墓碑与会话重写

状态：verification_pending（离线实现与检查已通过；真实 PG 未执行）

### 目标

保证删除后旧请求不复活，同时保留当前分支、回退和重写功能。

### 涉及文件

- hermes_db/operations/retirement.py、rewrites.py（新增）
- hermes_db/repositories/retirement.py（新增）
- tests/hermes_db/contracts/test_retirement_rewrites.py（新增）
- tests/hermes_db/postgresql/test_retirement_rewrites.py（新增）
- tests/hermes_state/test_terminal_retirement.py、test_retired_fence_outlives_horizon.py（依据）

### 依赖与接口

- 前置：Tasks 8–11。
- 输出：删除、重试、清理、重写交错后仍不复活旧会话；当前普通会话功能在新数据上成立。

### 实施步骤

补充责任：prune_never_active_keyed_sessions 从 Task 11 转入，在完整退休/删除事务建立后接入；profile rekey 的 namespace 退休栅栏也在墓碑主题审计，防止改名后旧路由恢复。

依赖审计补正：archive_sessions 与其 list_prune_candidates 选择器统一在 Task 16；跨 Profile adopt/move 及 delete_gateway_routing_rows 与该调用方的文件引用、维护/修复命令和其余 profile_repair 接口统一在 Task 16。Task 12 保留同会话分支复制、当前 JSON 导入导出和完整删除/重写。这里调整的是落位顺序，未减少接口或业务范围；Task 16 必须核对共享文件指针的持有者，不能搬移正文后清理仍被目标引用的文件，也不增加 SQLite 旧数据自动迁移。

1. 覆盖谱系删除、墓碑、终态回执、路由退休、分支/回退/重写及当前消息显示代表更新。
2. 区分业务删除与可清理缓存；必要的 state_meta 栅栏和回执不随会话正文清空。
3. 在新库中验证现有导出、复制等普通功能；不增加 SQLite 整库导入、旧 Schema 升级或旧导出格式兼容任务。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_retirement_rewrites.py tests/hermes_state/test_terminal_retirement.py tests/hermes_state/test_retired_fence_outlives_horizon.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_retirement_rewrites.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

删除、重试、清理、重写交错后仍不复活旧会话；当前普通会话功能在新数据上成立。

### 执行结果

从 Task 11 commit fa346a033c 继续。已建立并实现 assert_export_safe/assert_exports_safe/get_session_delete_targets：导出限额包括归档物理行；默认删除探针包含 Local receipt 谱系和递归 delegate marker，普通 branch/compression 子会话不由默认探针串入；所有选择按 store_id 隔离。tests/hermes_db/contracts/test_retirement_guards.py 首轮有效红灯为 2 passed/3 missing-interface failed，实现后 5 passed，exit 0。Task 12 仍 in_progress，尚未提交。

Native delete_session/delete_sessions 已接入同一完整短事务：映射/根锁 → queued/running/unknown 拒绝 → terminal admission/worker 身份退休 → mutation 内容裁剪 → 路由/Local policy/API binding/永久墓碑 → 正文/旁表删除及提示 GC；默认物理删除保留独立分支，显式 chain 删除支持整链租约跳过和请求计数；expected ids/display snapshot 在事务内复核。提交后才发事件并清理当前会话缓存文件，路径限制在明确 sessions_dir 内，支持字面特殊字符。

契约复现并整改两个物理父删除边界：显示谱系不能把永久锁根当作存在的会话行；失去物理父连接后的兄弟会话不能共用 pinned/archive/turn lease 域。现在在原映射栅栏内把存活组件重新绑定到各自根，旧根行/控制键/代次行仍保留。这个重绑定只发生在显式拓扑断开后，不把旧 holder 延续到已经独立的会话；正常压缩的稳定根语义不变。Native root/frame/回执跨 store 契约通过。

canonical mutation 已提供作用域内 epoch/revision/generation 护栏、确定性 request/digest 回执及重放优先、删除 owner 闭包和 metadata 动作。跨 owner 压缩边界红灯发现遍历不能越过外域节点后再进入同域，已改为逐边检查。预备 model/reasoning/workspace/editor_mcp/edit_policy 在同一事务复核 Local receipt、物理目标 revision 和运行/租约状态后提交；模型变更保持提示、工具快照及消息原文不变。新增 policy picks/配置刷新入口，分支显式继承 picks，不实现旧 receipt 格式回退。

新增 canonical branch/reset/rewind/compress，复用同连接的压缩发布、归档与消息回退；分支复制精确列、独立 Local 路由/策略/锁根和 picks。reset 可带 queued follower 发布新目标，unknown/running 护栏保持；预备动作会复核当前物理目标的 revision。调用者 prepared 数据在事务前复制，不暴露未提交的物理 stamp。逐行 prune 在写入前复核全部行的 CAS，仅变更行归档一份旧正文、保留原行和显示槽；公共 rewind 规划复用只依赖公开读写接口的纯算法。

新增 housekeeping：空会话及未准入 seed 补偿、never-active 带租约跳过/路由计数、terminal 身份/结果/worker 墓碑到期；派生 Bot Chat/A2A/API id 和走过的代次栅栏永久保留。私有 terminal retry 校验原始 digest/epoch，worker tombstone 额外验证 adoption proof，删除后的结果只留回复与用量。profile rekey 审计补齐 namespace 栅栏：复制到新 namespace，与现有栅栏合并时永久优先，旧键继续拒绝迟到路由；保持 store_id 不变。

退休文件现已记录持久候选后再清除正文，在提交后的拥有者 Profile 中复核生存 transcript/已准入输入、本地 capture lease 和文件身份再清理；共享 branch 指针仍保留。清理失败保留候选供重试。普通当前 JSON 导出/导入已保留 prompt、消息 UID/归档状态，并重置运行路由/活动；整批验证、墓碑拒绝和无环父图重建已覆盖，未添加 SQLite 整库或旧格式迁移。

chat picks、canonical import、prompt refresh 和当前 Cron/外部快照/skill/工作区投影已实现。Cron 新库路径只读当前 scheduler 准入及其 policy 身份，不实现旧 timestamp id 扫描。其余跨 Profile 修复/搬移、archive_sessions 与选择器按依赖归 Task 16，见上方责任补正。

最终接口核对：归属调整后的 28 个公开 SessionDB 方法均存在。Task 12 离线实现已落位，真实 PG 并发、故障和重启验证尚未执行；PG 工厂仍不启用。

### 验证证据

- scripts/run_tests.sh（PM Python 3.14.9）：retirement_guards 5 passed；Native retirement 初始红灯 4 passed/5 missing-interface failed。实现后 8 passed/1 lineage failed，修正实际存活祖先后与 compression_metadata/worker_compression 21 passed。
- 补充 verified-delete CAS、故障回滚和缓存路径约束后，retirement_rewrites 13 passed。新增孤立兄弟隔离用例先 1 passed/1 failed（pinned 串入）；在同一根/映射事务内重绑定组件后，retirement_rewrites + compression_leases + gateway_peers 35 passed / 0 failed，15.0s，exit 0。
- mutation_receipts 外域节点边界先 1 passed/1 failed，逐边整改后与 retirement_rewrites 共 22 passed。prepared_mutations 首轮 SQLite 2 passed/Core 2 failed（prepare 未实现），实现后与 mutation_receipts 共 11 passed / 0 failed，10.6s，exit 0。prompt/tool/message 中 NUL 原文及策略准备后 revision 改变拒绝已覆盖。
- mutation_transcript 初始实现缺口及两处测试误用（私有 lineage、append 非 runtime revision）已整改，14 passed，包含压缩原位/轮换、后继目标 revision 复核及精确重试。prune_rewrites 首轮缺接口及测试 snapshot/原文断言修正后 6 passed；与 messages、compression_archive 共 44 passed / 0 failed，10.5s，exit 0。追加 append 后显示槽保持测试也已通过。ruff 一处 UTC 测试写法已修正；health 24 files / 0 blocking / 0 advisory。
- terminal_retries 先 2 passed / 2 missing-interface failed，实现后 4 passed，4.5s。housekeeping 先 3 passed / 3 missing-interface failed，实现后与 terminal_retries、gateway_peers 21 passed；补 never-active 和 generation walk 后 housekeeping 9 passed，8.6s。rekey 栅栏测试修正 save 的 None 返回值误用后有效红灯：新 namespace 未拒绝旧 id；整改后 rekey 11 passed。
- retired_files 2 failed（最后持有者删除后文件未清理），实现后与 retirement_rewrites/mutation_receipts 共 24 passed，36.8s。当前 portability 修正测试 API/timing 字段误用后 6 passed。整轮 contracts：34 files / 271 passed / 0 failed，31.2s，exit 0，日志 `.build/postgresql/task12-contracts.log`。
- 新增 PG retirement/rewrites 入口：41 项定义（共享契约、故障、作用域和 3 项 barrier 并发），均未执行；加前序 123 项为 164 项待真实 PG 验证。这里的定义数量不是验证通过数量。
- session_controls 初轮 4 passed / 2 missing-interface failed，补齐 chat pick 和 refresh 后与 portability 12 passed；补当前 Cron/外部快照/skill/cwd 后 16 passed / 0 failed，6.3s。最新 ruff/health：46 files / 0 blocking / 0 advisory。新增这 8 项 PG 共享契约后，Task 12 PG 定义 49 项、总计 172 项，仍均未执行。
- Task 12 整轮离线检查点：全部 hermes_db 加 SQLite runtime_mutations/terminal_retirement/retired_fence_outlives_horizon/export_timings/import_keep_flags，58 files / 372 passed / 0 failed，46.6s，exit 0；日志 `.build/postgresql/task12-tests.log`。PG 文件由默认 marker 排除，没有连接数据库；不能把其发现项算作 PG passed。14 staged 检查通过，日志 `.build/postgresql/task12-checks.log`。
- 后续审计新增空压缩祖先与后继保护红灯 1 failed：sweep 会删除仍承载后继租约的根。现在按实际存活压缩组件检查 turn/compression guard 和 executing/unknown ledger；受影响 housekeeping/retirement/leases/peers 45 passed，14.1s，exit 0，日志 `.build/postgresql/task12-sweep-lease.log`；补 Worker 存活/终态释放断言后 1 passed，2.7s。新增对应 PG 用例后 Task 12 定义 50 项、总计 173 项，均待真实 PG 配置。整改后完整 14 staged 检查再次通过（47 code files，0 blocking / 0 advisory，exit 0），日志 `.build/postgresql/task12-final-checks.log`。本提交为 Task 12 离线恢复点；不等于真实后端验证完成。
- 前次 ruff/health 局部检查通过；最新预备策略修改后的检查、完整 Task 12 验证与 commit 尚未到达。未连接 PG，123 项前序真实 PG 用例仍待配置，新 retirement 用例尚未接到 PG 入口。

## Task 13：实现 API 响应续接与 Run 幂等存储

状态：verification_pending（离线实现与检查已通过；真实 PG 未执行）

### 目标

把完整 API 会话身份和重放记录接入所选后端。

### 涉及文件

- hermes_db/repositories/api.py、operations/api.py（新增）
- gateway/platforms/api_server_response_store.py、api_server_run_idempotency.py、api_server.py
- tests/hermes_db/postgresql/test_api_stores.py（新增）
- tests/gateway/test_api_idempotency_after_delete.py、test_api_server_response_store_profile_scope.py、test_api_idempotency_namespace.py

### 依赖与接口

- 前置：Tasks 8–12。
- 输出：API 续接和重放可跨服务重启恢复，作用域完整且故障不会降级成进程内身份。

### 实施步骤

1. 覆盖 response_store 的 5 表和 run_idempotency 表，保持指纹、输出顺序、previous_response_id 续接、保留期与已接受请求身份。
2. 通过运行存储接口获取准入终态/墓碑，移除在 PG 路径寻找相邻 state.db 的逻辑。
3. PG 故障不切回内存，跨作用域重复 key 不共享结果；删除后重复请求返回原终态而不再次执行。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/gateway/test_api_idempotency_after_delete.py tests/gateway/test_api_server_response_store_profile_scope.py tests/gateway/test_api_idempotency_namespace.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_api_stores.py -- -m integration --postgres-test-config $pgTestConfig`

### 完成条件

API 续接和重放可跨服务重启恢复，作用域完整且故障不会降级成进程内身份。

### 执行结果

从 Task 12 本地 commit dfd78f3515 继续。已核对现有 ResponseStore 的 5 表和 RunIdempotencyStore 事务/保留语义；PG 固定 Schema 已包含这些表。新增 repositories/api.py、operations/api.py 与 PostgresResponseStore：双作用域限定、正文 LRU/命名会话、不可变回执、模型标签、准入绑定、输出索引及同库终态结算；close 不关闭共享 SessionStore，短事务不回落内存。atomically/off_loop 在当前线程复用本次事务 Connection，调用方只能组合本存储的同步数据库动作。生产接线统一留 Task 17，工厂仍不启用半成品 PG。

新增 PostgresRunIdempotencyStore 及 api_runs 仓储的首批预留/查询/保留期实现；未决状态不按年龄清除，授权保留期限只延长。PG update_status 要求显式 scope，避免同 store 的同名 run 跨 API 作用域更新；Task 17 接线须从现有 _run_owners 传入。后续还须避免在持有 Response 事务时另取 Session/Runtime Connection（尤其 pool_size=1），并将 PG Run 恢复接 canonical/epoch 证据，不能依本地 PID 推断远端执行已结束。

结算改为同库窄列联结，只读 admission status/terminal meta key，不水合大请求或转为 JSONB。先结算身份再淘汰正文，零正文容量也受 settled 身份上限约束。resolve_request_admission 在 Responses 当前 Connection 上修复丢失导数指针，校验原始 principal/request，过期或冲突身份不重新准入；Task 17 的 _lookup_admission 必须使用此入口，不能绕回 SQLite helper 或另借连接。Run scope、同库原始身份、未知提交后原 key 查询和后台拥有者 Profile 已有离线契约；未增加账号系统。

### 验证证据

scripts/run_tests.sh（PM Python 3.14.9）test_api_responses.py：首轮 SQLite 2 passed/Core 2 missing-module failed；首批实现后 4 passed / 0 failed，2.5s，exit 0。只验证初始 LRU/回执/标签/输出顺序和重开；终态结算边界、作用域/故障/并发、全部 Run 语义和真实 PG 仍未验证。Task 13 未提交，保持 in_progress。

Run 首轮 2 passed/Core 2 missing-module failed，首批实现后与 Responses 10 passed。零正文容量结算顺序先 1 passed/1 failed，整改后两文件 12 passed。补同库退休结算/指针修复后 17 passed；后续 off-loop Profile/父子生命周期及断线不回落内存覆盖，scope_faults 8 passed，4.1s，exit 0。PG 入口新增 17 项定义（含 3 项 barrier 并发），尚未执行；与前序合计 190 项待真实 PG。整轮离线回归进行中，最新完整静态检查未执行；此前 ruff/health 9 files / 0 blocking / 0 advisory。

整轮首次结果：61 files / 356 passed / 2 failed / 3 collection errors，45.2s，exit 1；全部失败来自四个既有 gateway API 文件缺 aiohttp，日志 `.build/postgresql/task13-tests.log`，不能记作整轮通过。正在用 PM 新建 `.build/postgresql/api-test-env`（postgresql + messaging extras、dev/test groups），保留原环境，不用 raw pip/uv；完成后重跑受影响 API 回归。Task 13 仍 in_progress，未提交。

PM 新环境构建成功（`.build/postgresql/task13-env.log`）；四个受影响 gateway API 文件重跑 12 passed / 0 failed，5.7s，exit 0，日志 `.build/postgresql/task13-api-tests.log`。原轮 356 项通过与这次重跑分别记证据，没有把缺依赖轮写成完整通过。接下来运行 Task 13 暂存快照完整静态检查；真实 PG 190 项仍未执行。

Task 13 离线检查点：整改后 14 staged 检查通过（9 code files，0 blocking / 0 advisory，exit 0），日志 `.build/postgresql/task13-checks.log`。数据层接口全部落位；API 路由/authority 接线和 PG Run 恢复的 epoch 证据按总计划在 Task 17 完成。50+123+17 共 190 项真实 PG 定义未执行，不能宣称 API PG 后端已通过。下一任务为 Task 14。

## Task 14：实现对外投递义务账本

状态：verification_pending

### 目标

让同在主库范围的投递义务使用 PG，维持外部效果恢复规则。

### 涉及文件

- gateway/delivery_ledger.py
- hermes_db/repositories/deliveries.py、operations/deliveries.py（新增）
- tests/hermes_db/postgresql/test_deliveries.py（新增）
- tests/gateway/test_delivery_ledger.py、test_delivery_ledger_producer.py、test_delivery_ledger_process_home.py

### 依赖与接口

- 前置：Tasks 8、11–13。
- 输出：所有普通账本调用已按后端接入，领取和恢复有真实 PG 行为证据。

### 实施步骤

1. 接入 delivery_obligations 的记录、领取、尝试、终态、重试与清理；保留已有回执和投递恢复语义。
2. 主机 PID 证据仅在正确命名空间使用；共享 PG 中领取依赖实例身份和原子条件，旧持有者不得覆盖新领取。
3. 网络投递不置于数据库事务内；发送后未知结果按现有义务状态恢复，不能以数据库重试保证“恰好一次外部投递”。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_deliveries.py -- -m integration --postgres-test-config $pgTestConfig`
- `& $testRunner scripts/run_tests.sh tests/gateway/test_delivery_ledger.py tests/gateway/test_delivery_ledger_producer.py tests/gateway/test_delivery_ledger_process_home.py`
- 手工故障注入：领取后退出、发送后回执未提交、重启恢复；记录发送次数与持久状态，不产生额外自动重放。

### 完成条件

所有普通账本调用已按后端接入，领取和恢复有真实 PG 行为证据。

### 执行结果

从 Task 13 本地 commit ad0750dc13 继续。已读取现有 ledger 的创建、领取、重试/限流、清理及普通生产调用：账本属于 launch/process home，adapter_profile 区分被服务 bot，不能改为当前 turn 的 home。PG 表已有 owner_instance_id/claim_token/claim_expires_at；将用实例和原子 token 条件替代跨主机 PID 推断。先建立内容/限流预算共享契约及过期接管拒绝旧 owner 的 Core 契约；尚未实现 PG ledger 或改普通调用。

首批 Core ledger/仓储/事务已实现普通 record、显式不可变 DeliveryClaim、原子领取/限流等待采用、runtime 重试/未发送释放和终态条件写入；不查本地 PID。每个发送 await 必须携带当次 claim，不能只按 obligation_id 取最新 token，否则同实例的新领取也可能被旧回调覆盖。PG 同 id record 不替换现有领取或重置已花预算，与“旧持有者不得覆盖新领取”的计划要求对齐；普通网关调用仍待改为携带 proof 并按 process home 选择后端，尚不启用工厂。

### 验证证据

test_delivery_obligations.py 首轮测试把同 id 改 content 误当实际幂等输入，核对 compute_obligation_id 的 content 输入及现有 INSERT OR REPLACE 后修正为相同请求。有效红灯 SQLite 1 passed/Core missing-interface 1 failed + 1 setup error；首批实现并以显式 claim 测试后 3 passed / 0 failed，1.9s，exit 0。静态检查正在执行。crash-left、完整恢复/清理边界、所有普通调用、PG 并发及故障用例仍未完成；Task 14 in_progress，未提交。

Task 14 离线检查点：已补齐 crash-left 同回复去重登记、重试/陈旧上限、终态优先有界清理，以及所有普通账本函数的按后端派发。新增 gateway/delivery_backend.py 仅按 get_process_hermes_home 解析配置，持有进程/配置/作用域绑定 handle 并在退出释放；PG 未就绪/失败不回落 SQLite。工厂完整启用及网关 quiesce 后显式关闭由 Task 17 收口。普通 producer 捕获当次 DeliveryClaim，启动和 runtime 恢复的确认/未发送释放也携带该凭据；不按 id 借用后续 token。已有 best-effort 投递语义保留：数据库不可用时发送仍可能发生，不能承诺外部 exactly-once；领取 TTL 到期接管也不推断远程 PID 生死。

新增 crash-left 契约先 5 passed / Core 缺接口 1 failed，补齐后通过；当前 11 项离线投递契约覆盖 process home、adapter profile、跨 store、迟到/同实例旧 token、限流采用、未发送退款、预算、清理、事务回滚、真实提交后注入 ack 丢失，并在发送回调断言没有活动写事务。scripts/run_tests.sh tests/hermes_db 加投递/最终流式回复六个现有测试文件：66 files，430 passed / 0 failed，39.0s，exit 0；另连接泄露/单连接 2 passed，1.4s。日志 .build/postgresql/task14-tests.log。默认运行器排除了 integration，PG 文件显示的估算数量不是 PG 通过。新增 11 项真实 PG 定义（含三个屏障并发竞争）未执行；合计 201 项真实 PG 定义仍无执行证据。测试配置文件再次核对不存在。Task 14 保持 verification_pending，不能称 PG 投递后端已通过；下一任务 Task 15 可独立推进。

## Task 15：实现 PG 搜索与中文查询契约

状态：verification_pending

### 目标

在新 PG 数据上覆盖当前查询可见性、语法和索引范围。

### 涉及文件

- hermes_db/postgresql/search.py（新增）
- tests/hermes_db/contracts/test_search.py、search_corpus.py（新增）
- tests/hermes_db/postgresql/test_search.py（新增）
- tests/hermes_state/test_search_or_relaxed_fallback.py（依据）

### 依赖与接口

- 前置：Tasks 6–12；环境需具备所采用的搜索扩展。
- 输出：搜索契约通过，CJK/短词差异与性能证据清楚；缺扩展或不满足语义时不报告后端完整。

### 实施步骤

1. 固定英文、中文短词/长词、代码/路径、布尔组合、前缀和转义语料；明确排序、片段允许差异和稳定分页。
2. 验证全文检索 + pg_trgm 及必要 CJK 投影，保留当前工具输出索引投影与来源/活动/压缩过滤；不以默认英文分词或无界 LIKE 宣称等价。
3. 记录短词与大样本查询计划、索引大小和耗时；如果实例不能提供必需能力，明确停止该能力验收并更新设计，不能静默降低兼容标准。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db/contracts/test_search.py tests/hermes_state/test_search_or_relaxed_fallback.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_search.py -- -m integration --postgres-test-config $pgTestConfig`
- 在测试 Schema 对固定大样本执行 EXPLAIN (ANALYZE, BUFFERS)，记录数据规模、计划及查询耗时；不先承诺吞吐倍数。

### 完成条件

搜索契约通过，CJK/短词差异与性能证据清楚；缺扩展或不满足语义时不报告后端完整。

### 执行结果

从 Task 14 commit 31ca64409e 继续。按固定语料先验证查询语法、可见性、投影及放宽规则。PG 使用 simple 全文 GIN、pg_trgm GIN 与单字/双字数组 GIN 投影：短 CJK/短子串先查数组候选，再做精确子串复核；不依赖默认英文词干或无界短词 LIKE。新增可再生投影列及 Alembic 0002，不修改冻结 0001；压缩的全列 INSERT SELECT 会保留投影，普通修改同步更新。GIN 非唯一索引不要求 store_id 为首列（不额外要求 btree_gin 扩展），每条业务查询与所有唯一约束仍显式带 store_id。此项属于既定“必要 CJK 投影”的实现细节，未扩展产品范围。离线语法/投影与 SQLite 基线验证和真实 PG 行为验证分别记录。参考官方 [GIN 全文索引](https://www.postgresql.org/docs/current/textsearch-indexes.html) 与 [pg_trgm 索引限制](https://www.postgresql.org/docs/current/pgtrgm.html)。

### 验证证据

初轮固定语料因误传 SQLite 不支持的 create_session(started_at) 有两项 fixture 错误，已改为读取实际 session.started_at 建时间边界；PG 纯规划/投影两项缺模块为有效红灯。纯规划和 SQLite 语料随后 4 passed。新增消息投影/剪枝/参数化、约束与压缩克隆回归 35 passed / 0 failed，12.6s，exit 0。最后一次 SQL 参数断言原先未考虑 substring 参数转小写，核对绑定值后修正断言并通过。当前完整 hermes_db 回归正在运行；新增 PG 搜索用例尚未连接执行，不能称搜索语义或查询计划达标。


Task 15 实施细化：针对官方 tsvector <1 MB、位置上限 16383 和每 lexeme 256 位置限制，0002 新增 store/message/chunk 主键及级联 FK 的 message_search_chunks，由限定 search_path=pg_catalog 且对象全限定的 invoker 触发器在原消息事务内生成分块向量，直接 INSERT SELECT 克隆同样覆盖。查询 AND/NOT 在整条消息的 chunks 上判定；长短语用 GIN 数组候选加词边界复核，避免分块/重复词位置上限漏召回。另保留 pg_trgm/短字数组索引，普通工具正文只投影 8192 字，显式 tool 查询沿用全正文扫描。search_content 的结构化 Unicode 投影保持原字符，避免显式工具 CJK 查询落在 ASCII 转义串上。新增 PG 大消息、回滚、当前 PG 0001→0002 派生投影回填、隔离及 10,000 样本计划/索引大小证据采集用例，全部未运行。这里的升级仅是本功能新 PG Schema 演进，不读取 SQLite 旧数据。参考 [PostgreSQL 全文限制](https://www.postgresql.org/docs/current/textsearch-limitations.html)。

Task 15 离线检查点：scripts/run_tests.sh tests/hermes_db tests/hermes_state/test_search_or_relaxed_fallback.py：63 files，384 passed / 0 failed，100.7s，exit 0（.build/postgresql/task15-tests.log）。Unicode 全正文调整后受影响 64 passed，11.4s；减少非内容更新的重复投影后，消息/Worker/剪枝/压缩/搜索 62 passed，12.2s，exit 0（task15-final-affected.log、task15-sync-tests.log）。最新 14 staged 检查通过，16 code files，0 blocking / 0 advisory，exit 0（task15-final-checks.log）。10 项真实 PG 搜索用例未执行，合计 211 项真实 PG 定义仍无执行证据，查询耗时/索引大小未取得。状态为 verification_pending；工厂未提前启用。下一项 Task 16 继续独立工作，不将 integration 的默认排除当作成功。

## Task 16：替换文件身份、健康与归档引用依赖

状态：verification_pending（离线实现/契约和静态检查就位；真实 PG 与已证明的主机基线限制保留）

### 目标

让 PG 模式不再依赖本地 state.db 的存在或父目录。

### 涉及文件

- gateway/readiness.py、run_runtime.py
- tools/tool_result_storage.py
- tui_gateway/methods_profiles.py
- hermes_db/health.py、repositories/archive_refs.py（新增）
- hermes_cli/ 中读取数据库大小、健康或备份的消费者（Task 1 清单）
- tests/hermes_db/postgresql/test_health_archive_refs.py（新增）
- tests/gateway/test_readiness.py

### 依赖与接口

- 前置：Tasks 3、6–15。
- 输出：PG 不以本地文件充当数据库身份或健康依据；归档引用清理不误删有效结果。

### 实施步骤

1. 用显式 scope/profile_home 与数据库健康接口替代 db_path.parent、state.db 文件存在性和 sqlite_master 探测。
2. 工具结果清理通过会话存储查询引用；数据库不可读时保留文件，不能因本地无 state.db 得出无引用结论。
3. 移除 PG 路径的 _conn 直读，状态展示使用后端查询；SQLite backup/repair/recovery 保持本地专属，PG 命令清楚报告支持范围。

责任补正（Task 12 审计）：list_prune_candidates/archive_sessions 与其他 retention/maintenance 选择器在本任务完成；adopt_session_lineage_from、export_session_for_move/import_moved_session/delete_moved_session/delete_gateway_routing_rows 和其余 Profile repair 调用方一并核对。仅支持当前新数据业务，不加入 SQLite 旧格式/旧文件升级；跨 store 复制必须处理共享文件引用保留，不能把数据库行搬走等同于文件迁移完成。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/gateway/test_readiness.py`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_health_archive_refs.py -- -m integration --postgres-test-config $pgTestConfig`
- 手工验证 PG 模式本地没有 state.db 时健康判断正确，引用中的工具归档不会被过期清理。

### 完成条件

PG 不以本地文件充当数据库身份或健康依据；归档引用清理不误删有效结果。

### 执行结果

从 Task 15 commit 4f22e0ef39 继续。首批实现显式 profile_home/health、按配置的 PG readiness 和有界 spillover 名称投影查询；普通过期清理在作用域映射锁内完成引用检查及短本地 unlink，PG 配置/连接/引用未知时保留文件，不以缺少 state.db 推断无引用。为避免清理扫描大量正文，新增原消息事务同步的 spillover_names 派生列及 planned Alembic 0003，INSERT SELECT 克隆保留该列。0003、归档/移动、消费者状态/分析/本地维护尚待完成。

### 验证证据

首轮 4 failed：health/archive_refs 模块缺失三项及 readiness 将 PG 不可达误报本地未初始化一项。实现后 4 passed；联合原 readiness 为 6 passed / 1 failed。showlocals 确认 state_db/session_store/config/model 均 ok，C 盘实际 463002247168 used / 47931084800 free（约 90.6%），原磁盘降级阈值 90% 导致整体 degraded；在项目 D 盘隔离 basetemp 复验中，不更改阈值或伪造主机。ruff/health 首批 12 files，0 blocking / 0 advisory，exit 0；完整 Task 16 未完成，不提交、不进入 Task 17。

Task 16 过程证据：原 readiness 以已核对项目 D:/AI/hermes-agent/.build/postgresql/task16-readiness-temp 为 basetemp 后 3 passed / 0 failed，1.3s，证明 C 盘真实容量阈值触发而非 PG 接线回归。health/引用/驱动可选/迁移发现/既有删除文件契约合计 11 passed，4.8s。工具结果原文件 57 passed / 1 failed（Windows shlex 引号断言）；用 4f22e0ef39 的源码只读副本及原测试副本仅重定向模块导入，scripts/run_tests.sh 再现同一失败，日志 .build/postgresql/task16-tool-baseline.log，未修改原断言或路径转义。

新增 retention 共享契约先 SQLite 3 passed / Core 缺接口 3 failed，原生活动/筛选/完整压缩链选择器和同事务 archive/prune 实现后 6 passed / 0 failed，4.7s。任务仍 in_progress；自动维护、Profile 修复/移动、跨 store 文件保留、其余 file identity/分析/命令消费者和真实 PG 定义尚待完成。当前 REQUIRED_REVISION=0003_archive_refs；001/002 冻结，003 仅为当前新 PG 数据回填名称投影，不读取 SQLite 数据。

Task 16 维护补充：自动归档/孤儿关闭新契约先 8 passed / Core 缺接口 2 failed；实现中误把 titles 导入到 repositories 导致 5 setup errors，纠正到 operations 后 10 passed。新增自动 prune/跨 scope 节流时测试块插入位置不当导致 12 passed / 1 failed，移回原孤儿测试后，retention 13 + health/refs 5 共 18 passed / 0 failed，8.6s，exit 0。自动维护在同一映射/排序 root 事务内节流、数据清理及写状态，保持原来的已关闭孤儿完整保留窗口；心跳和 TTL 租约/运行账本保护活动会话，未知执行不关闭。PG 不执行物理 VACUUM；接纳原参数但 vacuumed=false，实例维护归用户。最新 ruff/health 18 files，0 blocking / 0 advisory，exit 0。仍有 Profile 移动/归档文件保留和消费者接线未完成。

Task 16 Profile 移动实施约束（编码前记录）：仅当前 PG 导出在同一连接目标/共享 Schema、不同 store_id 间移动；拒绝 SQLite 原始 payload、跨后端和同 store_id 自移动，保留 SQLite 原模式。准备快照带服务端随机凭据和正文/提示/用量摘要；目标需匹配已提交移动回执才能把同名 id 判为 present，源删除前重新核对数据未增长且目标已确认。父节点先删导致的受控 parent/root/generation 重定位不算新正文，保持现有 parents-first 批处理。源作用域仍保留删除/路由墓碑，不自动复活已删除 id。

文件不复制或迁移：采用 state_meta 内的作用域化引用授权，所有者与接收 store 的查询均显式带作用域并校验随机凭据。复合操作按 store_id 排序获取所有映射锁；分支/压缩及再次移动可保留原物理 home 的引用。目标最后一份引用清除后以独立短操作撤销授权，再由原 home 的受管清理回收；未知/截断引用保留文件和授权，避免永久无条件 pin 或跨 store 无作用域扫描。需要同 Schema 的直接引用授权是既定共享 Schema 与“跨 store 移动不能误删文件”要求的落地，不增加文件迁移、账号或数据库服务管理。

新移动契约首轮误调用不存在的 get_session_tool_names，已改为核对公开会话的工具 pin hash；SQLite roundtrip 基线随后 1 passed，Core 移动接口尚缺（-k sqlite 也选中了拒绝 SQLite 的 Core 用例，所以该次同时 1 failed）。待实现后统一复验。roster 新增原消息事务写入的 ≤83 字预览 BYTEA 投影，避免每次轮询加载整个正文；SQLite/Core 预览及迁移发现 9 passed，25.3s。003 同时添加该列并回填当前 PG 行，尚无真实 PG 执行。

Task 16 移动/文件检查点（2026-11-07）：当前 PG 移动使用摘要、随机票据、目标回执及源删除时重新核对；实现内层同连接跨 scope 操作和按 store_id 排序映射锁，未知提交不盲重放。第一轮实现暴露工具 pin 被 create_session 的 prompt GC 提前删除、测试未完成目标确认却期望增长拒绝，以及源文件回收未纳入保留授权三个问题，均已整改。最新 Profile 移动 9 passed，含 parents-first、目标冲突、源增长、全代消息/提示/工具 pin/用量、二次移动、分支最后引用回收、事务回滚和真实 Core 提交后注入 ack 丢失。再加 health/引用及既有退休文件，共 20 passed / 0 failed，10.6s，exit 0。延迟 spillover 候选记录本地 owner UUID 和 lstat 身份，同名替换不删；TTL 清理取得引用锁后重查 mtime。没有文件字节迁移；远程或未知文件所有者继续延后回收。

当前数据 Profile 修复新增作用域化 labels/parents/routes/topic evidence 与事务，并支持同共享 Schema 当前 PG 谱系采用，保持所有历史代、重置导入的运行字段、归档但不删除 donor，摘要不一致时不退休 donor。目标无采用回执的同 id 视为无关记录，拒绝以计数相同推断身份；这是 PG 新数据下对原计数护栏的收紧，影响仅是冲突数据需显式处理，不覆盖或隐藏已有对话。修复/采用契约 7 passed / 0 failed，4.1s，exit 0。

Insights 和 Web 用量/模型分析改为 PG 显式命名 Core 查询，完整 join 含 store_id；不把 SQLite SQL 字符串转译给 PG。每日统计用主机每行本地日历转换，避免 DST 窗口只套当前固定偏移。测试初次误传 create_session(billing_provider) 导致 4 fixture failures；纠正后发现 tool_calls 本来是 Text，而实现误作 BYTEA 解码，以及工具/技能断言用了错误公开字段，已纠正。最新标准 runner：analytics 契约、两个现有模型归因/去重及原 Insights 共 42 passed / 0 failed，8.2s，exit 0。最新 ruff/health 在新增分析/修复前为 33 code files、0 blocking / 0 advisory；新内容仍需复查。Task 16 未提交；下一恢复点为 CLI 本地维护支持边界、Web/TUI 文件存在性/缓存和 Profile repair 打开/跨后端护栏，再添加真实 PG 定义和统一局部验证。真实 PG 仍 211 项未执行。

Task 16 最新离线整轮：标准 runner 执行 tests/hermes_db 及 db_setup/db_commands、Insights、模型分析、Web sidebar、Profile repair、TUI roster、物理维护/状态相关 18 个既有文件，共 86 files、613 passed / 0 failed，63.3s，exit 0（.build/postgresql/task16-tests.log）。新增 SurfaceLabelReader 原先仍查 SQLite PRAGMA，消费者契约曾 75 passed / 1 failed，改为 PG 当前 Schema 能力后新消费者 4 passed。Ruff 首次未使用变量和 health 的未使用 table 导入遮蔽已修正，最新 ruff/health 66 code files、0 blocking / 0 advisory，exit 0。

本地文件维护扩展回归：126 passed、5 failed、1 teardown error、15 平台 skipped，exit 1（task16-file-maintenance-tests.log）。对 HEAD 4f22e0ef39 的 backup.py 只读副本运行原 test_backup.py，仅重定向模块；放在原 tests/hermes_cli 目录保持同 conftest 后，同样 5 failed / 1 passed / 1 teardown error（86 deselected，4.7s，exit 1；task16-backup-baseline-in-tests.log）。失败为 Windows wrapper 名称、路径分隔符、两处 CRLF 字节断言、POSIX mode 断言，以及测试将全局 monotonic 替为有限 iterator 使 teardown StopIteration；未修改这些基线或断言，最终验收须保留限制。临时基线测试已删除，用户文件保留。

新增真实 PG 定义 29 项，含维护/修复/移动/采用/分析/引用共享契约、当前 0002→0003 派生列回填、提交确认丢失、移动与追加竞争、用 pg_blocking_pids 证明确实等待引用发布映射锁的回收竞争。未执行，合计 240 项真实 PG 定义无证据，配置默认文件仍不存在。一次标准 runner --collect-only -m integration 返回 exit 1（0 tests ran，task16-pg-collection.log），不能计通过。物理维护提示已核对实际命令为 hermes db status/upgrade；文件备份输出与 quick manifest 明确 PG 数据库未包含，数据库服务和备份/恢复由操作者管理。Task 16 继续完成 staged 全检查后保存本地检查点，再推进 Task 17；真实 PG 状态将保持 verification_pending。

Task 17 额外审计点：Profile 克隆必须给新 PG Profile 分配新的稳定 store_id，不能照抄源身份；本地 .file-store-id 同样不能作为新 Profile 的文件所有者身份复用。重命名原 Profile 则保持 store_id。此项来自本任务新增文件所有权与既定 Profile 隔离的交集，不扩展账号或文件迁移。

Task 16 公开能力收口：首次 14 staged 检查通过后，对 SessionDB/PostgresSessionStore 的公开方法做实际导入/MRO 差集核对，发现当前业务的 meta KV、rich row、Kanban 谱系归属、ghost prune、profile purge，以及 Task 15 漏掉的 anchored view/recent-user 方法。先行共享契约为 SQLite 5 passed / Core missing-interface 5 failed（task16-audit-red.log），补齐后 36 项导航/退休受影响测试通过，随后含跨 scope meta/终态投递保留的最新六文件 45 passed / 0 failed，8.2s。pure around helper 被两种阅读组合复用，整个 anchored read 保持同一 read snapshot；Profile purge 只清理当前名字的 bookkeeping，保持消息历史和 delivered 状态。旧数据 backfill/retag/stamp、FTS rebuilding 与物理 SQLite size/vacuum 继续本地专属，由 Task 17 在调用点分流，不伪造 PG 方法。新 PG 定义加 6 项，Task 16 合计 35 项、全计划 246 项未执行。不能以早一轮 613 项离线通过覆盖后续代码；最新受影响验证与最终 staged 证据分别记录。

最后的配置/物理提示和 quick CLI E2E：tests/hermes_cli/test_backup_storage.py、test_db_setup.py 与新文件消费者 18 passed，8.9s；真实临时 home 的 quick backup 产出 manifest.session_storage={backend:postgresql,included:false}，没有 state.db 或 PG 连接。为遵守 backup.py 的 file cap，将原 run_quick_backup 移到现有主题 sibling backup_storage.py，唯一 main 调用点同时调整，没有 re-export shim。新增 _owning_profile 将 ConfigBackendUnavailable 转为脱敏 StorageConfigurationError，避免 daemon/RPC 直接 SystemExit。

Task 16 最终 staged 全部 14 检查通过，76 code files、0 blocking / 0 advisory，exit 0（task16-final-checks.log）。代码离线检查点可保存，真实 PG 仍 verification_pending；严格完成数不变为 3/18。恢复点：本任务本地 commit 后立即进入 Task 17，从资源获取/运行接口注入开始，工厂仍拒绝 PG 生产启用；先把普通入口、CoreEffect、API 的 scope/回执和关停资源接齐。无 PG 配置时继续离线接线，不对 246 个真实 PG 定义宣称成功。

## Task 17：统一 CLI、Web、Gateway、TUI、ACP 与 Agent 接线

状态：verification_pending

### 目标

所有普通会话路径使用同一工厂、作用域和释放规则。

### 涉及文件

- run_agent.py
- hermes_cli/cli_init_mixin.py、console_engine.py、oneshot.py、sessions_cmd.py、web_server_sessions.py、web_server_lifecycle.py
- hermes_cli/web_routers/ 中会话与状态消费者
- gateway/session_persistence.py、session_authority.py、run_runtime.py、run_shutdown.py
- tui_gateway/agent_factory.py、server.py、methods_session.py、methods_profiles.py
- acp_adapter/catalog.py、session.py、gateway_session_meta.py
- agent/ 与 cron/ 中实际直接打开会话存储的消费者（Task 1 清单）
- 各对应 tests/ 区域的行为测试；tests/hermes_db/postgresql/test_surface_flow.py（新增）

### 依赖与接口

- 前置：Tasks 6–16。
- 输出：普通入口没有遗漏的 SQLite/内存降级写入，资源释放与后台作用域正确，主链路在真实 PG 上跑通。

### 实施步骤

1. 在各入口的组合点经 db_setup/acquire_db 注入 db.sessions 和 db.runtime；受管 Worker 保持原所有者 RPC，未传存储的 Agent 懒打开也走统一选择。
2. 替换 authority 对 SQLite runtime 自由函数的直接调用；将结束、后台回调、线程跳转和路由所属 Profile 作用域明确绑定。
3. 统一 API 辅助存储与资源关闭；不把一个作用域句柄给其他用户复用，不在请求间修改全局环境/Schema。
4. 依据 Task 1 清单检查每个直连调用：普通路径已替换，保留调用必须有明确的 SQLite 专属用途；PG 失败所有降级入口均被阻止。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_cli tests/gateway tests/tui_gateway tests/acp_adapter`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql/test_surface_flow.py -- -m integration --postgres-test-config $pgTestConfig`
- 手工依次验证 CLI、网页与消息入口在同一授权逻辑空间创建/续接会话，重启恢复及不同空间同名 ID 隔离；测试不用真实用户数据。

### 完成条件

普通入口没有遗漏的 SQLite/内存降级写入，资源释放与后台作用域正确，主链路在真实 PG 上跑通。

### 执行结果

从 Task 16 commit 4e5a339721 继续。先补 Native scoped acquisition：native_registry 按 PID/PG 配置/scope 共享 SessionStore 与 RuntimeStore，连接仍是短期借用；建立/最终 usage flush 在全局锁外，引用独立释放，同 key 关闭结束前不发布替代对象。DatabaseHandle 禁止跨进程继续借用旧句柄。工厂完整 PG 激活守卫仍保留，等普通入口/授权/CoreEffect/API 与关停资源完成后再移除。

### 验证证据

首批 acquisition 契约 3 setup errors（缺 native_registry），实现后与原 factory/scope 共 14 passed / 0 failed，2.3s，标准 runner，PM Python 3.14.9。并发获取用六方 Barrier，验证共享一个 scoped store 且不同 scope 不共对象；Native Runtime 在 Core 隔离库实际准入/读取，最后引用关闭后重开仍保留消息。测试曾把 admission 的公开字段误写 session_id，实施时按现有 target_session_id 改正。尚未连 PG，也未声称普通生产接线完成。

本地会话幂等创建、路由/策略回执、提示前缀发布和 idle close 已接入 runtime/local 能力；Core 测试包含真实提交后注入确认丢失，必须保留已发布的提示前缀，原请求重查不重复发布。首批生产 runtime/local 自由函数调用已改为显式后端能力派发，SQLite 旧实现保留；原 SQL 授权回调仍需逐项适配 CoreEffect，工厂守卫继续保留。

普通共享获取已转到 access.acquire_sessions；释放统一识别独立 SessionResource，再转交原 SQLite registry。只读 CLI/ACP、Gateway reader、Insights 等入口按配置打开，PG 无 state.db 也尝试连接；受管 Worker 拒绝打开 owner store。Native 强制 unserve 后持有句柄失效，RecoverableHandleCache 可重开新 generation；测试曾发现缓存先 getattr(_db) 触发关闭代理，已按真实类型先检查并通过。Gateway PG 打开、退避、路由读写失败显式报错，不保存成 JSONL/sessions.json 降级成功，不导入旧路由 mirror。原异步获取/释放方法从 run facade 移入 run_session_storage sibling，保持借用句柄关停所有权。

Native authority 的 Profile home/资源 identity、启动 current receipt selector、lineage 检查、结果结算和 discarded boundary 已接入 scoped 能力。新当前会话的压缩/接管在原事务更新回执，明确绕过 SQLite 旧数据修复，不添加 PG 兼容格式。Core 隔离库已实际通过普通 owner 创建、读取授权、rename 精确重试和重启恢复；随后冷历史测试发现 Task 12 mutation_binding 误将列表传给只接收对象的 _json，已改为精确 JSON 列表编码，绑定随 mutation 提交并拒绝其他主体。当前继续扩展 owner submit、其余 CoreEffect、Worker RPC、API store 和 profile 克隆/关停接线；未启用生产 PG。

作用域接线审计：原 local_identity 输入是 authority.profile_id（目录路径），直接照搬会使同库同 store 在两个本地目录产生不同创建 ID，违背既定稳定 store_id 的跨实例身份约束。PG 持久化 local 创建命名空间将使用数据库目标/Schema 的不含凭据摘要加 store_id，回执相应采用此命名空间；公开 actor/ref 的 Profile 授权协议保留，文件和秘密继续使用 DatabaseScope.profile_home。这是落实已定隔离设计，未引入账号系统。Profile 创建/克隆须在发布 staging 前分配新 PG store_id，不能把源配置身份复制为新空间；已有 Profile 重命名保持 store_id。后续真实 PG 仍需验证相同请求跨实例与 epoch 竞争。

上述初版命名空间在后续资源审计中进一步修正：持久化 local/API 身份只取稳定 store_id，不再包含连接目标 URL 摘要，避免 DNS/连接地址切换让同一逻辑空间无法续接。数据库目标/Schema 的摘要只用于资源 identity、同连接目标校验与移动 guard；各表仍由实际数据库、Schema、store_id 的作用域键隔离，外部 ID 本来允许在独立空间相同。公开 actor/ref 授权协议保持原样；此项仍不涉及账号扩展或旧 PG 格式兼容，工厂尚未启用、无真实 PG 数据可迁移。

上述命名空间已接到 local、Bot、cron、Kanban、A2A、hosted 的创建 ID 推导及 local 回执恢复/结束列表。Core 实际两个不同本地 home、同目标/Schema/store 的 owner 先后创建相同请求，续接原 ID 和消息；另一个 store 同请求保持隔离。新 Profile staging 在发布前给已配置（包括未激活）的 PG 设置分配新 store_id，重置复制来的 .file-store-id；managed 层若不允许独立 ID 则拒绝发布。Native profile rekey 同事务改 local receipt 的 route/entry/origin，保留创建命名空间、策略、提示；使用现有命名空间函数正确处理名为 main 的 Profile（main~）。未将此处理扩展成文件迁移或账号改造。

API Responses 已在组合入口按拥有 Profile 选择存储；PG 使用 caller-owned API resource 持有 session acquisition，关闭 API 不关闭其他调用方的共享 SessionStore。缓存构造在锁外，关停先标关闭、drain 后在 worker close，迟到构造拒绝发布并释放；原 SQLite 默认/按 Profile 路径保留。普通 response admission 重查在同一 Response 事务连接解析/修复，先比较 scoped 数据库 identity，禁止另取 Session Connection。Run store 的路由、显式 scope、PG epoch 恢复以及其余 API bind/turn/effects 仍待接线；工厂未启用。

标准 runner 五文件合计 86 passed / 2 failed，264.8s，exit 1；其中新 acquisition 3、本地创建 5、原 alias retry 31、bot chat 36 通过。两个 client env 用例预期 /client/bin 而实际 PATH 首段为 Windows 盘符 D。将 48 个修改中的生产模块从 HEAD 4e5a339721 提取到隔离 overlay、原测试放在原 tests/gateway 下保留 conftest，原两个失败均复现（0 passed / 2 failed / 11 deselected，exit 1，task17-client-env-baseline.log）；未改这些平台断言或客户端环境实现。临时测试文件已移除，离线通过不代表 PG 验证。

Gateway fallback 契约首轮 1 passed / 2 failed（有效 save/open 红灯；旧 mirror 首轮因 SQLite 专用 helper 自身失败而未导入，改为观察实际文件打开后验证无读取），实施后联同原 recovery/fast save/transactions/acquisition 五文件 38 passed，5.3s，exit 0（task17-gateway-boundary-tests.log）。新资源、作用域、Worker guard 与 CLI/ACP 读侧九文件 72 passed，5.6s，exit 0（task17-acquire-reader-tests.log）。结算契约首轮 1 passed / 3 failed，其中一项测试误假定 discard 必有 result，按原 SQLite 约定改查 interrupted 终态；其余两项有效 Core 读连接/SQL 红灯，实施后与 private terminal retries 共 8 passed，4.1s，exit 0。

普通 Native owner 创建/恢复及受影响 SQLite 八文件最新 47 passed，10.2s，exit 0（task17-authority-readers-tests.log）。冷历史授权/压缩/原 history mount 五文件 32 passed / 2 Linux-only skipped，16.8s，exit 0（task17-history-tests.log；随后测试扩展仍须新证据）。最新 quick ruff 通过，health 曾报 facade 行数和 sibling Any/捕获日志三项，已整改，待复验；不能计为已通过。独立 PG 配置仍缺，246 个真实 PG 定义尚未执行。恢复点保持 Task 17 in_progress、未提交，不提前进入 Task 18。

扩展 submit 幂等、current history leaf 和 PG 打开失败四类入口后，最新四文件 60 passed，4.5s，exit 0（task17-entry-errors-tests.log）。扩大到 hermes_db 与原 authority/mutation 七文件共 83 files、489 passed / 1 failed / 3 Linux-only skipped，58.6s，exit 1（task17-runtime-regression.log）。唯一失败为原 shared_authority_peer 的 unsupported envelope ACKed；按 systematic-debugging 比较 HEAD 4e5a339721 原测试和 110 个改动生产模块的原源码，在子进程用隔离 source loader 保留 canonical __file__/资源路径后完全复现同一堆栈（0 passed / 1 failed / 1 deselected，exit 1，task17-authority-baseline.log），未更改该信任规则，临时测试已移除。最新 health 尚有 api_server facade 增长 1 行需在后续 API 接线中收口，不计为已通过。

Profile 克隆两项有效红灯（所有 ID 仍 source-store），实施后两项通过；原 Profile 三文件 115 passed / 9 failed / 4 platform skipped，48.5s 左右，exit 1（task17-profile-identity-tests.log）。九个失败含 WinError 1314、换行/权限及 .bat 名称假设，在 HEAD 原 Profile 测试及源码 loader 下逐项复现（0 passed / 9 failed，exit 1，task17-profile-baseline.log），原 conftest 保留，临时测试已删除。两种 Native local rekey 先错误导入测试 helper，修正后得到 5 passed / 2 route 不变 failed 的有效红灯；实现后含 routing/authority/克隆四文件 22 passed，4.9s，exit 0（task17-local-rename-tests.log）。

Responses 资源选择及原 Profile/off-loop 三文件最新 11 passed，4.3s，exit 0（task17-api-resources-tests.log）；新增普通 admission lookup 期间禁止第二个 Session read，仍完成原回执修复，并拒绝另一 store。第一轮 disconnect 发现将 root response 引用设 None 破坏原 fixture 的二次 close，已改为保留关闭对象、状态阻止重新获取，复验通过。最新 ruff/health 两项通过，140 code files、0 blocking / 0 advisory，exit 0（task17-quick-check.log）；不代表完整 14 checks 已跑。随后跨 home 冷历史测试发现 Native binding 中仍使用公开 Profile 路径：1 passed / 1 permission_denied failed；已改为作用域内 store_id 命名空间并保持主体核对，当前回归中，需更新最新证据。真实 PG 仍无证据，246 项定义未执行。

冷历史跨 home 修正后，owner/mutation receipts/portability/原 history mount 四文件 41 passed，16.6s，exit 0（task17-history-scope-tests.log）；当前绑定还要求规范 JSON 列表，拒绝其他格式。Gateway shutdown 在现有所有 producer/worker quiesce 检查之后，按顺序释放 delivery handle、SQLite/Native registries 和 PG Engine；Profile unserve/删除/snapshot 改为 scoped 双 registry 释放，不销毁其他 Profile 的共享 Engine。原 quiesce、unserve、snapshot guard 与当前 Native owner/acquisition 五文件 28 passed，4.4s，exit 0（task17-shutdown-tests.log）。新增 scoped close 契约与最新 ruff/health 待复验。Task 17 当前恢复点：先完成这些复验，再继续 Run store、API bind/turn、Worker owner RPC/CoreEffect、剩余普通直连/文件门槛审计和 PG surface 定义；仍未提交，工厂未启用。

上述 scoped close、当前绑定格式及单连接 API 契约最新四文件 12 passed，4.5s，exit 0（task17-latest-contracts.log）；ruff/health 最新 143 code files、0 blocking / 0 advisory，exit 0（31.2s，task17-quick-check.log）。随后 Responses 资源接线发现选择阶段会调用 Native 构造维护事务，已让 API 组合延迟该维护到首次持久化 worker 事务，成功提交后才记完成，失败/未知提交仍可幂等重查。测试在 prewarmed session resource 上禁止选择阶段 _write，真实 get/put/准入修复仍通过；受影响 response/resource/fault/off-loop 四文件 25 passed，6.4s，exit 0（task17-api-deferred-tests.log）。该后续改动尚须最新静态检查；Native registry miss 的 Schema 检查也须由启动 prewarm/owner 线程承担，不能据此声称所有 PG I/O 已在 worker。下一步继续 Run 资源按服务器 scope/home 绑定及 canonical/epoch 恢复，不使用远端 PID 推断终止；不改动冻结迁移来掩盖缺失证据。

Run 资源契约先 2 missing-module failed，ProfileRunStores/open_run_store 实现后 2 passed，2.1s，exit 0（task17-run-resources-tests.log）。按真实服务器 home 绑定 API scope，后台 update_status 必须用已捕获的显式 scope，未知 scope 拒绝，不从当前环境猜归属；SQLite 多 Profile 原有 launch runs 文件保留，PG 按本 Profile 的 session resource 打开，失败不转内存。已接 _initialize_run_state、状态持久化和关闭；Native run_admission 从 scoped 当前/退休 canonical 回执读取，PG 保留记录没有 canonical 证据时不使用本机 PID/birth 推断远端终止。原 API Run/轮询/导入隔离及新资源四文件 68 passed，11.3s，exit 0（task17-run-api-tests.log）。尚需 Native HTTP Run 恢复/unknown 行为证据、PG API auth namespace 稳定绑定、其余 API bind/turn 与 Worker 接线；不把这轮 SQLite API 回归当真实 PG 通过。

PG API auth 幂等 namespace 已以 database_identity 替代可变 Profile 标签，保留认证密钥哈希；Room grant 的签名作用域维持原规则。跨 home/标签测试保留同 store 身份，另一 store 不共享，连同原 Run 和 response Profile 三文件 69 passed，11.5s，exit 0（task17-run-namespace-tests.log）。Responses 缓存在 scoped registry force-close 后能重开新 generation；资源/Run/off-loop 三文件 13 passed，28.7s，exit 0（task17-api-generations-tests.log）。最新 ruff/health 在这些生产改动后 147 code files、0 blocking / 0 advisory，exit 0（33.1s，task17-quick-check.log）。随后新增 Native Run poll：由真实 Core epoch recover 将 started 变 unknown，普通 run_projection 返回 unknown；没有 canonical 准入证据的保留 Run 不凭本机 PID 改写 running，测试禁止调用 _owner_alive，四项通过，14.3s，exit 0（task17-run-recovery-tests.log）。这是 Core 离线证据，未执行真实 PostgreSQL 或完整 Native HTTP 运行链路。

Task 17 新恢复点（2026-11-07）：当前 PG 持久化命名空间已校正为仅依赖稳定 store_id（pg-store:<store_id>），不依赖本机 home、Profile 标签或 DSN/DNS；资源连接身份仍保留 target/schema 用于连接和移动校验。更正后三个文件 14 passed，4.5s（task17-stable-scope-final-tests.log）。Native API 绑定从原 _execute_write 缺失红灯起步，补齐 epoch→独占映射→根锁下的当前绑定、声明键、路由与源身份事务；不导入 SQLite 原始 key 历史格式。随后普通 API 准入在 retry_terminal_admission 的 _read_ctx 红灯，已接 Native 退休身份重放及 CoreEffect 事务内单目标校验/设置保存。API 绑定及原 SQLite 幂等/压缩/续接十二文件 31 passed，10.4s，exit 0（task17-api-admission-regression.log），含删除后原身份重放但不复活会话。中间两次新测试错误（错误访问 owner.runtime、将 outcome 误写对象）已修正为公开能力/合法 completed 值。当前继续策略刷新、API 启动恢复/媒体、Worker owner RPC 及剩余调用审计；Task 17 未提交、工厂守卫仍保留，246 项已有真实 PG 定义未执行；不能声称完整 Native HTTP/PG 链路通过。

Task 17 媒体/Worker 恢复点：API 设置读取、queued 恢复 selector、策略 picks/refresh 提交已分派到 Native 能力。API 单目标校验另加按 store_id+request hash 锁定的永久控制行，位于 epoch→共享映射→请求身份→根锁顺序，避免不同会话根上的并发同 key 同时通过；不改冻结 Schema、不把整个 store 的普通写入串行化，真实竞争用例仍待 PG。Native 终态 API 正文维护按 128 行分批、每批单连接；消息/媒体引用检查使用 scoped 仓储与原文件身份/捕获租约，当前 Profile 不匹配时不收集。新 API 媒体实际图片契约通过，删除后回收、不删除仍被终态 API 持有的图片、压缩后原请求可重放；中间测试误读公开行中不暴露的 payload_digest，改由精确重放验证。扩大媒体回归 52 passed / 3 failed，20.8s（task17-api-media-regression.log），首次通过 PYTHONPATH 的覆盖因标准 runner 清理环境而无效，task17-media-baseline.log 撤销为 HEAD 证据；已改用显式 pytest -p 在 conftest 前加载 131 个 canonical HEAD 模块并断言实际 loader，三项再次复现（3 passed / 同 3 failed，5.3s，task17-media-baseline-corrected.log）：Windows WinError 1314 符号链接权限、测试使用正斜杠拆分本机路径、Windows 长路径 capture replace。未修改这些原基线或放松保护。

受管 Worker recall 现在是认证 worker.recall 只读 RPC，携带已采用执行的身份/epoch/generation，仅允许现有工具参数，worker 不收到 DSN/schema/store_id/数据库路径；owner 绑定所属 home 后解析显式 Profile 并执行搜索或读会话，不再由 worker 私开 SQLite。该读取不消耗持久化序号；失败/未确认写入仍拒绝继续读。普通无 db 的受管 worker 明确拒绝，不回落本地。worker claim origin/verify、私有 admission-worker 预留与 loss、child.reserve CoreEffect、委派持久化/完成事件读取和 execution tip 均接 Native 能力，OS proof 保持在数据库事务外。首轮 recall/原采用与回执五文件 20 passed / 6 平台 skipped，3.5s（task17-worker-recall-tests.log）；新 owner 预留→采用→消息→子任务精确回执→容量拒绝→丢失 unknown 的双后端契约连同 recall/API media 三文件 5 passed，2.5s（task17-worker-owner-contracts.log）。OS proof 在该存储契约中固定为预先已验证输入，不能当真实子进程/PG 证据。首轮静态检查发现两个测试问题：共享 fixture 导入触发 F811/noqa、未用变量，已移入 conftest 并修正，待复验。下一步 Worker 扩大回归/静态检查、普通 API 持久化/资源首次打开线程边界、producer CoreEffect/hosted rooms 与普通入口审计；Task 17 未提交、工厂守卫仍保留。

Task 17 后续验证：扩大 Worker/委派十文件 31 passed / 8 平台 skipped，126.1s（task17-worker-regression.log）；该轮静态检查 167 文件 ruff/health 通过。公共 POST /api/sessions 的源 SQLite 原子创建已移入 api_server_session_create sibling，Native 当前库创建/标题冲突回滚/退休拒绝均为连接内 Core 操作；API 两类认证 wrapper 统一将 StorageError 与 UnknownCommitError 映射为明确 503，不泄漏驱动异常。缓存读取失效 Native handle 会重开，Run 替换代次后释放旧 OwnedApiStore。实际 aiohttp HTTP 测试在显式离线工厂 seam 下使用 Native Responses/Run/owner，创建/重名/标题冲突/不可达/真实提交后确认丢失/删除后拒绝均通过，连同原创建和 Run 三文件 7 passed，3.4s（task17-api-http-session-tests.log）；首轮测试遗漏 seam，正确被生产工厂守卫拒绝，已只修正测试。未连接 PG，不把 Core HTTP 证据称为真实 PG 证据。

producer 接线继续：队列编辑的取消/重放绑定、自动任务合并及 FIFO tail CAS、消息 /retry 的 transcript rewrite 与路由 memory fence 均组合为显式 CoreEffect；Source sqlite3 回调保留原路径。新双后端事务契约证明 FIFO 改变则合并整体拒绝，容量拒绝则重写不发生，接受后消息重写与准入一同提交，精确重试不重复修改；连同原队列/automation retry 三文件 13 passed，4.9s（task17-producer-effect-contracts.log）。初测误用不存在的 ordered_active_message_ids，已按真实 get_active_message_ids 改正。原普通 daemon automation 两项失败；HEAD pytest loader 下同样失败，原 stderr 解码又触发 UnicodeDecodeError。保留原环境的原始字节探针已定位在 automation_peer.py 第 2 行 import asyncio / _overlapped 的 Windows WinError 10106，尚未进入任何 Hermes 应用代码（task17-automation-raw-probe.log），不修改无关主机环境。临时 pytest plugin/probe 已移回被忽略的 .build/postgresql，未加入源码。

Kanban 独立本地账本继续用 SQLite；其 owner_admitted 对 Native 保存 storage_backend/store_id/profile_home/认证 principal，不伪造 state.db 数据路径。重查从配置重新选择并核对 stable store_id，不直接调用 SQLite，不凭本地 PID 推断 PG 远端 owner 消失；配置不匹配/不可达时保持暂停。新 Native 作用域/PID 禁止探针及原 reclaim/wait、producer 四文件 23 passed / 2 平台 skipped，4.8s（task17-kanban-owner-tests.log）。Bot/A2A 当前 generation selector 与 messaging pick 也已接 Native 能力。最新 ruff/health 在这些生产改动后 176 code files、0 blocking / 0 advisory，33.2s（task17-quick-check.log），最后新增 Kanban 契约尚需静态复验。当前仍为 Task 17 未提交恢复点；继续剩余直连/文件门槛/私有 SQL/HostedRoom 与 Native surface PG 定义审计。遵循原同步接口设计，不扩大为整条 Agent 异步重构；现有 write/维护/首次打开的 off-loop 边界须保留和测试。Tasks 4–16 的 246 项真实 PG 定义未执行，工厂守卫仍在，最终 verification/review 未执行。

Task 17 最新恢复点：工具侧最后三处普通直连（process_registry_results._owns_result、kanban_tools._persisted_session_id、cronjob_tools._run_session_usage）均改为配置选择的 open_session_store；受管 Worker 使用认证 worker.read 的三种固定操作 result.owns/session.persisted/cron.usage，不能提交 SQL、数据库路径、Schema 或 store_id，也不消耗写回执序号。owner 复用已采用身份/epoch 校验并绑定所属 home，纯读取业务集中在 tools/session_store_reads.py。Worker recall/closed reads 与原来源/工具四文件 12 passed，3.3s（task17-worker-tool-read-tests.log）；最新 ruff/health 180 code files、0 blocking / 0 advisory，33.1s（task17-quick-check.log）。Task 17 仍未提交、工厂守卫保留。下一步先完成 HostedRoom 与主会话后端的边界适配：计划明确独立 room 数据库不迁移，但其主会话的创建/读取/准入必须 Native；当前 CanonicalHostedRoomService 仍取 db.db_path、其 owner/task 授权 SQL 与会话事务共连接，尚不能在 PG 上运行。必须在记录具体调整及影响后实施，不能伪造 Native db_path、放开授权或把会话写回 SQLite。继续其余 Source 专属直连门槛审计、surface PG 用例和 Task 17 全量所需验证，再创建该 task 的本地 commit。真实 PG 仍未配置/未执行，最终 verification/review 仍待 Task 18。

Task 17 执行调整（已先说明影响）：HostedRoom 的既有同 SQLite 连接假设不适用于 PG，按布局设计新节拆分为独立本地房间协调与 Native 主库准入。PG 模式按 stable store_id 摘要命名新的 Profile 本地房间库，仅房间表/owner KV/本地 room epoch；旧 SQLite/standalone 任务不导入，避免在新 canonical 账本重复执行。跨库提交使用本地房间栅栏→PG 的固定顺序，保持房间状态到规范准入提交返回；桥接读事务无跨库双写。影响：房间协调仍属独立本机持久化，本轮不支持其多副本共享，主会话/消息/规范队列仍全部 PG；SQLite 模式行为和原数据保持。下一步先实现/验证该边界，再继续调用审计。另新增 Native resume 设置刷新测试首轮错误期待 CLI 在同一会话换模型，已按原缓存/恢复语义改正为刷新 max_turns、保留既有 model/prompt/history，四项通过，4.7s（task17-policy-refresh-tests.log）。默认 PG 测试配置最新探测仍不存在，未连真实 PG。

Task 17 HostedRoom 实现恢复点：新增 session_hosted_storage.RoomCoordination，在 PG 模式使用 hosted-pg-<sha256(store_id)>.db 保存独立本地房间协调、owner KV 与节点 room epoch，文件不含规范会话/消息/准入表。构造与本地 read/write 检查 Native epoch；Native 暂停旧 standalone 导入，SQLite 原导入保持。Canonical service 的 room SQL 改走该协调资源，Source 分支仍用原 SessionDB 事务。新边界首轮 db_path AttributeError 红灯，接线后与原 service 两文件 7 passed，4.4s（task17-hosted-coordination-tests.log）。

Native HostedRoomAuthorityRPC 的创建标签、历史/准入与远程绑定 KV 均接 scoped 能力；本地 HostedAdmissionFence 在持久化 worker 中先取得 SQLite BEGIN IMMEDIATE，再借用 PG Connection，通过 CoreEffect 检查被锁定的 owner/member/task，保持到规范提交返回。SessionAuthority 私有 _write_context 只用于这项已授权 producer 的同线程栅栏，不是客户端字段。附件准备使用显式 room_db_path，转送字节走原 attested 路径，不能回落 Native db_path。真实提交后注入 UnknownCommitError 的 Core 契约证明本地锁在 PG 借用前持有、未知结果后释放、原身份重试只有一行，授权撤销不产生准入；两项通过，3.5s（task17-hosted-submit-tests.log）。期间附件准备残留 db_path 红灯已修正。扩大十一文件 86 passed / 2 failed / 1 platform skip，209.2s（task17-hosted-regression.log）：一项为测试替身缺新 room_db_path，已按真实接口修正；另一项普通 SQLite daemon 的两个成员未全部结算尚在定位。更新后附件/Native 两文件 4 passed，4.6s（task17-hosted-followup-tests.log）。最新 ruff/health 在跨 Profile binding 之后 186 code files、0 blocking / 0 advisory，36.4s；随后本地 epoch 检查和测试替身改动仍需复验。

当前调试恢复点：普通 daemon 用已校验的 workspace 内 --basetemp 重跑仍超时（task17-hosted-daemon-short-path.log；1 failed / 1 deselected，约 55s；runner 总111s）。保留的独立测试数据在 .build/postgresql/task17-hosted-temp，Root canonical admission 已 terminal/completed，但房间任务/另一个 Profile 没有完成；不能据此归为基线。正在以显式 pytest plugin 对父进程及真实 daemon 子进程加载 HEAD 137 个原始 production 模块，sitecustomize 为 gateway.run/hosted service 写入进程独立源码标记，日志 task17-hosted-daemon-head.log，临时 plugin tests/gateway/_task17_hosted_head_plugin.py 必须在结束后移回 .build，不能提交。HEAD baseline 独立路径 .build/postgresql/task17-hosted-head-temp，仍在运行（完成后更新真实证据）。Task 17 未提交，PG 工厂守卫保留；真实 PG 和最终 review/verification 都未执行。

Task 17 恢复证据更新：HostedRoom 原 daemon 在显式 HEAD loader 下，父进程与真实子进程均加载 HEAD 137 个 production 模块并有逐进程源码标记，仍相同 member task 超时：0 passed / 1 failed / 1 deselected（task17-hosted-daemon-head.log；测试55.35s，runner约112s）。先前未定基线现已建立；具体根因仍未证明，不能直接归为 Windows。临时 plugin 已移回 .build/postgresql。附件 mock 增加显式 room_db_path 后，Native bridge/原附件四项通过。media 的初轮 PYTHONPATH 基线无效（runner清环境），已改显式 pytest -p、断言 BaselineSource，实际131个 HEAD production 模块；3 passed / 相同3 failed，5.3s（task17-media-baseline-corrected.log）。automation 原启动环境在 import asyncio/_overlapped、进入 Hermes 前 WinError10106，原始 bytes 探针见 task17-automation-raw-probe.log；保留限制，未放松测试。

Task 17 最新实现/验证：Native viewer close CAS、活动列表、故障结算 unknown 恢复、延后模型选择及其精确回执/CAS 已接线；viewer/HTTP/原生命周期三文件22 passed（20.3s），结算三文件13 passed（4.8s），deferred/原行为/HTTP四文件8 passed / 1 Linux-only skipped（5.9s）。HTTP history 的 StorageError 不回落空历史，UnknownCommit 返回503及 x-should-retry:false；默认API会话命名空间使用 pg-store:stable-store-id。quick ruff/health 最新202文件、0 blocking / 0 advisory，34.7s；之后新增修改须复验。

Bot Chat 原准入查询/标题让位、automation completion、ACP结束列表与分组 roster 改为 Native scoped 能力；房间路径显式选独立协调资源。当前格式JSON导入或本轮Agent创建的无路由本地会话保留续接：新增 Native current-history claim（gateway.native_history.v1），在 epoch→映射→根锁内重新授权、检查队列/Worker/租约/压缩并提交路由/策略，不读取旧SQLite或接受 legacy_session_id。恢复/压缩检查持久化 claim 证明，保留原ID/消息/提示，不拷贝或改写前缀。首轮恢复暴露 identity 仍只认派生ID，补原生claim校验后又遗漏导入，均已修正；最新Bot/当前历史重启恢复/普通创建三文件13 passed，5.2s（task17-bot-native-tests.log）。扩大76文件Bot/local/ACP/分组回归仍在执行（task17-bot-local-regression.log），不能计为通过。发现Web只读打开仍以文件是否存在为门槛、timeline与CLI代理有私有SQL，正在适配并补契约。Task17仍in_progress/未提交，工厂守卫仍在；246项真实PG定义未执行，Task18 verification/review未开始。

Task17 工厂接通恢复点：常规 source 专用接口差集检查（实际导入MRO）剩余项已逐一分流：SQLite物理FTS/vacuum/旧profile/ACP-cwd修复不在Native执行；项目发现的缺失repo-root更新是当前元数据行为，新增scoped Core更新，保持已记录root。额外发现run_runtime启动恢复/idle exit和webhook投递查询/终态直接SQL，已补 Native RuntimeRecovery 与JSON文本路径选择，保留当前epoch/精确generation/终态/后继队列拒绝；相关六文件18 passed，12.5s（task17-startup-webhook-tests.log）。Native current-history policy补保存reasoning/service tier/API mode，提示和原消息不改。

Web浏览现在按配置打开Native、timeline和标题查询走公开接口，离线metadata/import使用CoreEffect和当前epoch，不凭本机文件推断PG状态；owner-backfill/FTS进度只在SQLite执行。ACP对StorageError明确失败，不把消息读取失败恢复为空历史。Web/ACP修正测试JSON格式后新契约3 passed，2.2s；后续ACP/项目根目录/原行为四文件41 passed / 2平台skipped，10.5s。76文件扩大回归最终499 passed / 6 failed / 7平台skipped，267.7s；失败两文件bot_authority/local_automation的raw stderr证实均在fixture第2行import asyncio/_overlapped、任何Hermes代码前 WinError10106（task17-bot-launcher-probe.log），临时探针已移回.build。全区域计划命令已启动，CLI/Gateway/TUI/ACP共4105文件、约27313项，尚未结束（task17-full-surfaces.log），不能计为通过。

普通消费者接线后，factory.acquire_db 的开发期统一拒绝已替换为Native registry acquisition：仅显式PG配置启用，缺驱动/未初始化/不可达均返回typed StorageError且不回落；不自动执行DDL，不管理数据库服务。不可达契约现以构造边界注入具体失败，避免离线测试DNS/连接外部地址。工厂接通后全部离线存储+db_setup 93文件514 passed、0 failed，97.5s（task17-factory-contracts.log）；随后实际acquire_db（不替换factory）共享/释放和当前策略保真两文件8 passed，12.0s（task17-native-factory-test.log）。真实PG新增surface定义包括普通配置工厂/CLI/oneshot/Agent/TUI/ACP、Gateway+实际HTTP session创建+单连接池Responses/Run回执、Worker私有owner操作、HostedRoom隔离、当前历史重启与webhook JSON/终态；尚未执行，也未证明模型端到端推理。Task17仍in_progress/未提交，静态检查曾发现测试name-ladder，已改table dispatch待复验；真实PG与最终verification/review仍未执行。

Task17 最新恢复点（2026-11-07 05:57 Asia/Shanghai）：真实HTTP→Gateway authority→真实Agent→记录型本机模型服务→Native Core消息/终态链路已通过，包括同幂等键不重复调用模型和第二轮携带首轮历史。首轮测试工具集为空，使现有fake provider把主请求分类为aux并回答Fake title；改用既有file工具集后通过，不替换Agent/authority执行（task17-acp-full-http-regression.log）。该日志为PM新 full-test-env（postgresql/messaging/acp + dev/test）下95文件417 passed / 2 failed / 38平台skipped，185.4s；剩余两失败在显式HEAD loader（150 production模块，loader断言）均复现：MCP路径JSON转义与不存在的/tmp，0 passed / 2 same failed / 30 deselected，48.3s（task17-acp-head-baseline.log）。临时plugin已移回.build。原忙时接收测试只更新生产读取的新runtime_calls mock seam，该文件最新通过，未给生产增加None库兼容。

本任务全部14 staged检查已通过：218 code files，0 blocking / 0 advisory，exit0（task17-staged-checks.log）。随后独立房间文件作用域审计补数据库目标/Schema/store_id摘要，复用排除用户口令的resource_key；相同store_id/home切换目标不复用房间协调文件，凭据轮换仍用原文件，不迁移文件。Native桥/附件受影响两文件5 passed，40.7s（task17-hosted-scope-tests.log）；此后两代码文件和文档需重新暂存/静态复验。完整四区域回归仍在执行（session35135，task17-full-surfaces.log），目前有缺可选依赖、Windows fixture、超时与其他尚待判定失败，不能宣称全通过。该轮使用原api-test-env；ACP缺依赖已由上述新PM环境全区域复验覆盖。原索引零字节孤立锁已验证无持有者后备份，首次staged检查因锁未执行，不能计证据；以后Git状态读取必须 --no-optional-locks，避免受限只读状态刷新留下新锁。用户.gitignore和multi-user-web-chat.md仍未暂存。

新增PG surface现有10项定义（含参数展开），与前246项合计256项均未执行。--collect-only标准runner报告0 tests ran、exit1（task17-pg-surface-collection.log），不计通过，也不是PG证据。Task17仍in_progress/未提交，HEAD仍4e5a339721；本轮没有推送/发布/合并。下一步完成当前全区域失败归类/受影响整改、最新静态检查后保存Task17检查点；Task18最终verification-before-completion/code-review仍未开始。没有真实PG配置/连接证据，不称完整后端已通过。

Task17 扩大回归整改恢复点（06:20 Asia/Shanghai）：全四区域仍在执行（session35135，约27313项），最新已超过19000 passed；失败仍含已确认环境/平台项及未归类项，不计完整通过。发现新增worker.read/worker.recall漏登记 canonical wire，已新增 contracts/canonical_worker_reads.py，声明闭合回忆选项、固定read操作和标量结果；同步生成apps/shared TypeScript/OpenRPC。真实worker read/recall、旧canonical协议与生成制品六文件12 passed，8.7s（task17-worker-wire-tests.log）。该修正及两制品尚未暂存，不应把此前14项通过套用到它们。

旧测试composition seam同步：busy接收patch新runtime_calls读取点；Hosted附件mock补显式room_db_path；API能力测试操作实际被包裹的SQLite Run store；Kanban producer的no-listing探针只patch新的producer seam，不拦authority合法的pending列表。媒体/API/Kanban三文件126 passed，123.8s（task17-surface-seam-tests.log），API大测试文件后续仅调整为原行数，正在复验capability用例。shutdown spool两处acquire fake补公开可选path参数；原spool/恢复26项通过。连同group controls三文件合计32 passed / 1 failed，120.2s；group目录缓存相同失败在断言HEAD loader下0 passed / 1 same failed / 6 deselected（task17-group-cache-head.log，20.8s），未改缓存实现或断言，临时plugin已移回.build。

最新已暂存的房间资源隔离改动ruff/health通过，218 code files，128.1s（task17-latest-staged-checks.log）；其后的worker契约/生成制品/部分测试调整须重新暂存、检查。完整HTTP模型流程新增system prompt前缀不变断言正在复验（session34231，task17-http-prefix-tests.log），前一轮真实Agent幂等/续接已通过。默认PG配置最新探测仍不存在，未连接真实PG；256项PG定义无执行证据。Task17仍in_progress，尚未创建本task commit，HEAD仍4e5a339721；Task18 verification/review未开始。索引可能有只读git状态刷新留下的零字节锁，Git读取用--no-optional-locks；清理前核对时间/持有者，保留备份。用户两文件仍不暂存。下一步收齐全区域结果、优先整改新接线引入问题，再做最新静态检查及Task17本地commit。

Task17 补充最新证据：HTTP真实Agent第二轮system prompt与第一轮完全一致，同幂等键仍只执行一次；最新prefix/capability两文件2 passed，21.8s（task17-http-prefix-tests.log）。shared metrics busy同类stub改到runtime_calls读取点后10 passed，21.3s（task17-metrics-seam-tests.log）。默认Profile消息页的120 vs1失败，在已断言HEAD loader下仍2 passed / 1 same failed（task17-message-page-head.log；测试9.3s、runner26.2s），未修改这项业务或断言，临时plugin已移回.build。关闭spool/恢复fake的显式可选path契约复验已通过26项。

Task17 最新恢复点（2026-11-07 06:49 Asia/Shanghai）：清单中的 achievements dashboard 扫描器改为统一只读 open_session_store，检查点绑定不含凭据的存储身份，后台扫描使用 spawn_context_thread 继承发起 Profile。通过真实 dashboard discovery/mount 加载的 Native 作用域/故障/线程契约与原 SQLite 统计两文件16 passed，2.2s（task17-achievements-tests.log）。首轮语料误用 create_session(title=...)，随后相同内容/时间戳被既有显示去重，均已仅修正测试；最终不同内容但相同元数据指纹验证切换 store 后重算。该插件是 Task1 契约清单已有消费者，不新增插件能力。

原全四区域回归 session35135 已 exit1，无最终完整汇总；日志最后约89.9%、30035 passed / 516 failed，不能作为完整执行或通过证据，未完成部分不计通过。已确认并整改的本任务 mock/wire 问题各有上述复验，其他失败含平台/环境及尚未归类项，不能全部归为基线。正在新 full-test-env 单独补跑366文件 TUI（task17-tui-full.log）。最新14项 staged 检查 health 为226 files、0 blocking / 0 advisory；ruff 两处测试导入写法未通过（task17-final-staged-checks.log），现已修正。重跑14项全部通过，229 code files、0 blocking / 0 advisory，exit0（task17-final-checks-retry.log）；随后下述三文件边界修正须重新检查。Task17 仍 in_progress/未提交；256项真实PG未执行，最终 verification/review 尚未开始。

剩余调用核对：13个 Native 缺省同名方法调用均为 SQLite 专用迁移/FTS/物理维护；检查又发现 console optimize/repair 和 sessions_adopt 的前置后端门槛遗漏。三个有效红灯后补齐 PG 拒绝，原文件不变、不打开旧SQLite；受影响三文件19 passed / 2 Linux-only skipped，3.6s（task17-file-boundaries-tests.log）。prune_advisor 由 should_ask 的 PG gate 挡住，transcript rebuild 由能力检测挡住；Discord recovery 与 retaindb 使用各自独立本地账本，符合范围排除，不替换为主会话库。

Task17 离线实现检查点：14项完整检查后，最后控制台/adopt 三文件变更重新暂存并通过 ruff/health，231 code files、0 blocking / 0 advisory，exit0（task17-file-boundary-checks.log）。全部代码已接线，普通工厂可显式选择PG；本地commit仅保存实现，不代表交付验收。状态置 verification_pending，严格 completed 仍3/18。TUI补跑仍在执行，原四区域回归未完整结束且有未归类失败；这些限制及256项真实PG未执行均带入 Task18，继续不依赖数据库的文档、安装制品和审查工作。

## Task 18：完成配置文档、最终验证与代码审查

状态：pending

### 目标

以最新证据判定完整 PG 会话后端是否达到交付条件。

### 涉及文件

- website/docs/ 中会话存储、配置、部署与开发验证对应文档
- docs/designs/ 三份 PostgreSQL 设计与研究记录
- docs/plans/postgresql-session-storage-plan.md
- tests/hermes_db/test_distribution.py（新增，验证安装制品包含新包与迁移资源）
- 可选 CI 接线：.github/workflows/postgresql-tests.yml（仅在可提供独立测试配置时新增）

### 依赖与接口

- 前置：Tasks 1–17 全部 completed。
- 输出：完整覆盖矩阵、真实 PG 并发/故障、SQLite 回归和静态检查通过，审查无 blocking/major；否则最终状态为 BLOCKED 或 FAILED。

### 实施步骤

1. 文档明确安装 PG extra、配置 DSN 引用/schema/store_id、管理员初始化 Schema、连接池预算、支持的实际 PG 版本和扩展；明确不提供 SQLite 旧数据迁移。
2. 执行 verification-before-completion 所要求的当前变更检查，记录每个命令、时间、退出码、用例数量、实际数据库版本及未通过项。
3. 按 code-review 审查作用域、事务、并发、未知提交、提示缓存、降级、插件边界和测试质量；整改后只重跑受影响及必要的最终检查。
4. 需要 CI 时使用用户提供的独立测试配置，保护秘密并固定 Actions SHA；本计划不自动启动数据库服务、部署 K8s 或发布合并。
5. 通过项目 PM 构建路径验证安装制品，脱离源码导入路径检查 hermes_db 模块、Alembic 配置和版本资源可用，并在该安装模式运行 Schema 初始化测试。

### 验证方式

- `& $testRunner scripts/run_tests.sh tests/hermes_db tests/hermes_state tests/gateway tests/hermes_cli tests/tui_gateway tests/acp_adapter`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config $pgTestConfig`
- `python scripts/check`
- `& $testRunner scripts/run_tests.sh tests/hermes_db/test_distribution.py`
- 手工运行新库初始化、两空间同 ID 隔离、模型/工具回合、压缩/删除/重试、进程重启、断连、无本地 state.db 以及池关闭；记录实际结果。

### 完成条件

完整覆盖矩阵、真实 PG 并发/故障、SQLite 回归和静态检查通过，审查无 blocking/major；否则最终状态为 BLOCKED 或 FAILED。

### 执行结果

未开始；未修改本任务业务代码。

### 验证证据

未执行。实施时记录实际命令、退出码、数据库/解释器版本、关键结果、执行时间及偏差。

## 覆盖矩阵

| 设计要求 | 任务 |
| --- | --- |
| hermes_db 分层、稳定作用域、所有权隔离 | 1、3、5、17 |
| 配置入口、秘密、连接池、生命周期 | 2–4、16–18 |
| 新库初始化和 Schema 演进，无旧数据搬迁 | 5、18 |
| 会话、提示快照、用量和完整消息 | 6–7 |
| 准入、FIFO、epoch、generation、unknown 和未知提交 | 8 |
| Worker 幂等、回执与异步委派 | 9 |
| 压缩谱系、租约、并发尾部与水位线 | 7–10 |
| 路由、世代、整理、退休墓碑与重写 | 11–12 |
| API 续接与幂等、删除后重放 | 13 |
| 投递义务与外部效果恢复 | 14 |
| 中文/短词/布尔查询与索引投影 | 15 |
| 健康、文件路径依赖、工具归档引用 | 16 |
| CLI/Web/Gateway/TUI/ACP/Agent 主链路与 Worker 边界 | 17 |
| SQLite 回归、PG 并发/故障、静态检查和审查 | 18 |

## 计划变更

| 日期 | 变更 | 原因 | 影响 |
| --- | --- | --- | --- |
| 2026-11-06 | 排除旧数据迁移与回迁 | 用户明确“不需要兼容旧数据，也就是不迁移数据” | Schema 从空库设计；不增加历史导入任务 |
| 2026-11-06 | 测试目录使用 tests/hermes_db/ | tests/AGENTS.md 要求镜像源包目录 | 更正此前设计中的 tests/db/ |
| 2026-11-06 | 修正三个导出/删除探针归属为 Task 12，archive_and_compact 为 Task 10 | 与原计划的删除、完整压缩操作责任对齐 | 保留全部功能；在相应主题验证，不以未实现壳函数占位 |
| 2026-11-06 | Worker 接口归 Task 9，revision-fenced 会话动作/回执归 Task 12；旧队列导入留 SQLite | 清单粗归属与原计划主题不符；Task 8 不反向依赖尚未实施的删除/重写 | 功能范围不变，保持 8→9→10→11→12 依赖；PG 不增旧格式兼容 |

## 最终验证

### 执行命令

使用公共准备命令和 Task 18 命令；执行后在此记录实际命令与结果，不把计划中的命令当作验证证据。

### 当前结果

- 单元测试：未执行。
- PostgreSQL 集成、并发、故障与重启：未执行；没有数据库连接。
- SQLite 回归：未执行。
- 静态检查/类型检查：未执行。
- 构建：未执行；若未改 JS，JS 构建不属于本次数据库层变更要求；Python 包/PM 可选依赖须验证。
- 新库 Schema 初始化/升级：未执行。
- 旧数据迁移：不适用，用户已明确排除。
- 手工验证：未执行。
- 代码审查：未执行，尚无实现代码可审查。

### 验收标准

- [ ] 新空 PG Schema 可以由明确管理命令初始化；重复执行安全，应用仅检查版本。
- [ ] 默认 SQLite 保持现有行为；缺 PG extra 的本地安装可运行。
- [ ] 当前会话接口、完整消息、提示快照、用量、压缩、删除与搜索符合契约。
- [ ] 不同 store_id 使用相同业务键不串数据，数据库约束与所有查询均带归属。
- [ ] 重复请求无额外执行；FIFO、旧代次、unknown、Worker 回执和未知提交语义成立。
- [ ] 压缩竞争不分叉、不丢并发尾部、不改变既有提示与工具前缀。
- [ ] API 续接/幂等与投递账本可重启恢复；删除后旧请求不复活。
- [ ] 无本地 state.db 时 PG 健康和归档引用判断正确；PG 故障不降级写本地或内存。
- [ ] 全部普通入口接入统一工厂、作用域和资源释放；保留的 SQLite 直连仅用于明确本地功能。
- [ ] 实际 PG 版本、扩展、连接池预算和测试秘密准备方式有文档及验证证据。
- [ ] 不安装数据库实例，不实施历史数据导入、不发布 K8s、不自动提交推送或合并。
- [ ] 真实 PG、SQLite 回归、scripts/check 及代码审查通过，所有任务有最新证据。

### 未通过项目

全部实现与功能验收尚未执行。这是计划交付，不是数据库后端完成声明。

### 最终状态

尚未评定。实施验证与审查后，只能依据证据选择 READY_TO_MERGE、BLOCKED 或 FAILED；当前不得标记 READY_TO_MERGE。


## 恢复点

- 分支 feat/postgresql-session-storage；Tasks 1–3 完成；Task 4 实现可供集成验证，verification_pending；Task 5 离线 Schema/迁移/CLI 检查点已完成，verification_pending；Task 6 继续离线实现。Tasks 1–3 commits：b7648f08ee、bb221ec7d8、a7afe899c9。
- 测试解释器 .build/postgresql/test-env/Scripts/python.exe（PM 构建，postgresql + dev/test）；调用标准 runner 时显式指定 HERMES_PYTHON。
- 原 .gitignore 修改不纳入提交；原 docs/designs 三文件与实施计划作为本功能基线随 Task 1 提交。
- PostgreSQL 连接配置尚未提供；Task 4 真实环境和后续 PG 并发验收不可标通过。按用户要求继续不依赖数据库的工作。

- Task 3 已通过 37 项当前局部测试与 staged 全部 14 静态检查。旧 SQLite 注册表两个 Windows 基线失败见 Task 3 证据。
- 后续完整静态检查使用 PYTHONUTF8=1 与 scripts/check --staged，排除被忽略的临时测试环境/缓存归档；不修改用户 .gitignore。

- 执行偏差：按用户明确要求，缺真实 PG 配置时继续不依赖 DB 的实现。Task 4 和后续需要真实 PG 的任务可记录 verification_pending，不能标 completed；后续依赖先满足代码/接口，真实验收仍须按依赖顺序补齐。每 task 本地 commit 可以保存实现检查点，但不代表真实 PG 已验证。
- Task 4 的真实测试配置格式/命令见 contracts；没有读取用户业务凭据、没有连接 PG、没有创建数据库服务或扩展。

- Task 4 检查点 commit 47aa7638dc；Task 5 当前有 59 项离线测试与 staged 14 项静态检查通过，PG 的 6 项测试未执行，不计通过。下一步完成 Task 6 的主题方法，不启用 PG 生产写入。
- Task 5 新增 transcript_roots（稳定行锁目标）及 sessions.lineage_root_id；消息 UID 不能加唯一约束，多个物理副本是既有语义。初始 revision 冻结 24 表/13 索引，后续任务变更表形状须同步修订未发布的初始 revision 并验证，已发布后只能新增 revision。
- 当前未完成最终 verification-before-completion/code-review；全功能完成后统一执行并整改，绝不把这些局部结果当作完整后端通过。
- Task 6 离线检查点：114 tests/14 checks passed，状态 verification_pending。当前 26 表/15 索引已同步冻结初始 revision；后台作用域、短事务与失败分型已有离线契约。下一步 Task 7 完整消息编解码、UID/显示代表、行重写、计数/revision 与 watermark；工厂继续拒绝 PG 生产启用。Task 12 必须保留谱系控制键与根行。真实 PG 28 项未执行。
- Task 6 commit 7fd192bb81；Task 7 离线检查点 148 tests/14 checks passed，状态 verification_pending。当前 26 表/17 索引；42 个消息主题接口已核对。下一步 Task 8 队列、epoch、generation 与终态事务。archive_and_compact 在 Task 10 实施。真实 PG 47 项未执行，严格 completed 数仍为 3/18；不启用生产 PG 工厂。
- Task 7 commit 22c6fb7924；Task 8 离线准入/终态检查点：一轮 166 passed、后续受影响 18/依赖隔离 14/提交确认丢失 1 passed；14 staged checks 与最新 ruff/health 通过。下一步 Task 9 Worker 登记/采用/序列回执和异步委派（复用 worker_retirement）。Scope/epoch→映射→根锁顺序不得反转。59 项真实 PG 未执行；完整会话动作及 mutation receipt runner 在 Task 12，旧队列导入仅 SQLite，Task 17 须适配 CoreEffect。
- Task 8 commit 5b68f4ebd6；Task 9 检查点：186 项整轮局部回归、后续 14 项受影响测试与 14 项 staged 检查通过，状态 verification_pending。当前 26 表/18 索引，回执投影与候选标题均同步冻结 revision。下一步 Task 10 租约/压缩/尾部与 held coverage，复用 leases/append/title 的连接内操作；补齐压缩 Worker handlers。75 项真实 PG 未执行，工厂与普通入口仍未启用/接线。严格 completed 仍 3/18。

- Task 10 离线检查点：270 项整轮回归、随后 16 项受影响测试与 14 项 staged 检查通过，verification_pending；26 表/18 索引。下一步 Task 11 路由/心跳/代次/交接和整理状态；复用 root/map 锁与 PG TTL-only holder 规则。新增 27 项真实 PG 用例，合计 102 项未验证，默认配置仍不存在；PG 工厂仍拒绝生产启用。严格 completed 为 3/18。

- Task 10 commit 0b0ea642f4；Task 11 正在实现/验证，当前未提交。prune_never_active_keyed_sessions 已明确归 Task 12；没有删除功能缩水或无保护先行删除。Task 11 新增 21 项 PG 用例，仍未连接 PG。

- Task 11 离线检查点：321 项整轮回归、随后 10 项受影响测试、27 个公开接口核对及 14 项 staged 检查通过，verification_pending。当前 26 表/18 索引；新增 21 项真实 PG 用例，合计 123 项未执行。下一步 Task 12，从删除目标/租约/账本拒绝护栏和永久/可过期墓碑开始；保留 lineage-map-lock、transcript_roots、conversation_generations 与幂等身份。

- Task 11 commit fa346a033c；Task 12 已有 3 个公开导出/目标探针和 5 项离线契约通过，未提交。下一步完整 retirement/idle/租约 guard + Native 删除事务，随后 mutation receipts/rewrites/portability；123 项真实 PG 验证仍待配置，completed 仍 3/18。

- Task 12 Native 删除阶段已有 35 项受影响测试通过；工作区仍为未提交的 Task 12 实现。下一步 housekeeping/retirement expiry、canonical mutation guards/receipts 与重写/导出。完整 media/spillover 退休和 terminal private APIs 尚未接入，不能宣称 Task 12 完成。

Task 14 恢复点：14 staged 检查通过（11 code files，0 blocking / 0 advisory，exit 0），日志 .build/postgresql/task14-checks.log；离线实现已就位，PG 仍 verification_pending。Task 15 已置为 in_progress，从固定语料及现有纯查询规则开始；Task 17 需在网关 quiesce 后调用 close_delivery_handles。

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
- 当前任务：Task 14（对外投递义务账本）；Tasks 4–13 等待真实 PG 配置。
- 已完成：3 / 18。
- 产品范围阻塞：无。用户已确认使用新库，不迁移旧数据。
- 执行前置条件：真实 PG 验证时需用户提供本地测试配置，实际版本、权限和扩展由 Task 4 检查；当前没有连接数据库。
- 最近更新时间：2026-11-06（Asia/Shanghai）。

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

状态：in_progress

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

未开始；未修改本任务业务代码。

### 验证证据

未执行。实施时记录实际命令、退出码、数据库/解释器版本、关键结果、执行时间及偏差。

## Task 15：实现 PG 搜索与中文查询契约

状态：pending

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

未开始；未修改本任务业务代码。

### 验证证据

未执行。实施时记录实际命令、退出码、数据库/解释器版本、关键结果、执行时间及偏差。

## Task 16：替换文件身份、健康与归档引用依赖

状态：pending

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

未开始；未修改本任务业务代码。

### 验证证据

未执行。实施时记录实际命令、退出码、数据库/解释器版本、关键结果、执行时间及偏差。

## Task 17：统一 CLI、Web、Gateway、TUI、ACP 与 Agent 接线

状态：pending

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

未开始；未修改本任务业务代码。

### 验证证据

未执行。实施时记录实际命令、退出码、数据库/解释器版本、关键结果、执行时间及偏差。

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

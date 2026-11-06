# PostgreSQL 会话存储接入设计草案

## 状态与范围

- 状态：DESIGN_READY（实施范围和架构已收敛，详细接口与真实数据库行为按计划验证）
- 更新时间：2026-11-06
- 已确认：第一步覆盖完整会话存储，包括消息、系统提示快照、模型用量、执行准入、队列、Worker 回执、压缩和租约。
- 已确认：PostgreSQL 实例由用户管理；本任务不安装、启动或运维数据库，也不要求用户提供连接密码。
- 已确认：使用新 PostgreSQL 库，不兼容旧数据，不做 SQLite 历史数据导入、跨后端双写或回迁。
- 当前交付：数据层核查、配置契约和接入方案；尚未实现 PostgreSQL 后端，以下配置不能直接启用现有程序的 PostgreSQL 存储。
- 配置文件、用户 Markdown、工作区和其他独立 SQLite 数据库不在本阶段迁移范围。

后续源码深查见 [SQLite → PostgreSQL 调研报告](sqlite-postgresql-research.md)。其中补充了完整会话需要接入的 API 响应/幂等存储、同文件按需创建的投递账本，以及单一运行所有者与文件路径耦合；“其他独立 SQLite”不应据此排除这些会话关联记录。PG 采用共享 Schema 与稳定 store_id，具体任务见 [实施计划](../plans/postgresql-session-storage-plan.md)。

## 目标

通过明确的配置入口选择 SQLite 或 PostgreSQL，让现有会话读写链路使用选定后端。继续提供本地 SQLite 模式。选择 PostgreSQL 后连接、权限或迁移失败要明确报错，不能静默回退 SQLite 造成数据分散。

## 现有实现核查

| 位置 | 当前职责及结论 |
| --- | --- |
| hermes_state.py 的 SessionDB | 自定义 SQLite 会话门面，由多个业务 Mixin 组成；不是 ORM 模型或 ORM Session |
| hermes_state_dbfile.py | 通过 sqlite3.connect 打开 SQLite 文件，处理文件与 WAL 生命周期 |
| hermes_state.py 的 _read_one、_read_all、_execute_write | 集中的读写和事务辅助，但参数、异常、读池及重试仍绑定 SQLite |
| hermes_state_sessions.py | 会话创建、查找、列表、删除等手写 SQL |
| hermes_state_messages.py | 消息写入、读取、正文及显示身份等手写 SQL |
| hermes_state_common.py、hermes_state_schema.py | 手工建表、版本升级、触发器、SQLite JSON、索引及 FTS5 |
| hermes_state_registry.py | 按本地文件路径和文件代次共享 SessionDB；数据库后端需要独立的目标标识和连接生命周期 |
| agent/runtime_session_store.py | 受管 Worker 通过会话所有者提交读写的现有接口，不是通用数据库 ORM |
| pyproject.toml | 没有 SQLAlchemy、SQLModel、Peewee 或 psycopg 会话存储依赖；asyncpg 只声明在 Linux Matrix 插件依赖组中 |

会话存储包含约束、全文搜索和执行账本。SQLite 的 PRAGMA、BEGIN IMMEDIATE、INSERT OR IGNORE、INDEXED BY、FTS5 以及部分 JSON 与触发器语法不能原样交给 PostgreSQL。

## 方案比较

| 方案 | 复杂度与维护 | 兼容和测试风险 | 适用判断 |
| --- | --- | --- | --- |
| 继续手写 SQL，分别实现 SQLite 和 psycopg 后端 | 驱动依赖少；两套查询与事务细节需要维护 | 方言和行为容易逐渐分叉；需同一套后端契约测试 | 可行，但全会话模块长期双份维护成本较高 |
| 采用 SQLAlchemy Core，保留现有会话业务接口 | 引入表、SQL 表达式、连接池和事务管理；逐步迁移查询 | SQLite 特有的搜索、迁移和锁仍需分别适配；不是自动转换 SQL | 推荐作为完整会话存储的接入方向 |
| 将现有模块全部重写为 SQLAlchemy ORM | 同时改变存储和业务对象模型，改造面最大 | 对象状态、事务和复杂运行账本需重新验证 | 当前没有对象关系模型需求，不作为第一步 |

推荐 SQLAlchemy Core 加同步 PostgreSQL 驱动。现有调用接口主要是同步接口，因此无需为了数据库接入同时改造整个 Agent 调用链为异步。保留现有业务方法和执行语义，逐步收敛实际 SQL 操作；不对 SQLite 语句做通用字符串替换。

SQLAlchemy Core 提供 SQL 表达式、表定义、连接与事务能力，完整 ORM 是其上独立的一层。参考 [Core 官方文档](https://docs.sqlalchemy.org/en/20/core/index.html) 和 [连接与连接池](https://docs.sqlalchemy.org/en/20/core/connections.html)。

## 配置入口

行为放在当前 Profile 的 config.yaml 中：

```yaml
storage:
  session:
    backend: postgresql
    postgresql:
      dsn_env: HERMES_POSTGRES_DSN
      schema: hermes
      store_id: local-development
      pool_size: 5
      max_overflow: 5
      pool_timeout_seconds: 30
```

连接凭据放在秘密来源中，例如当前 Profile 的 .env，或部署时注入的环境：

```dotenv
HERMES_POSTGRES_DSN=postgresql+psycopg://user:password@host:5432/hermes
```

约束如下：

- backend 默认 sqlite，新增 PostgreSQL 选择不改变现有本地数据库路径规则。
- dsn_env 是秘密名称，通过已有 Profile secret scope 解析，不直接从全局 os.environ 获取其他用户的凭据。
- DSN 按秘密注册；日志、诊断、配置查询和异常不暴露密码。普通配置只保留引用。
- schema 必须显式配置并校验；store_id 是 PG 模式必需的稳定逻辑作用域，不能由客户端提交的路径决定，也不能把本机绝对路径作为跨实例身份。
- 多个 Profile 可以共用一个 Schema，但必须在服务端映射到各自的 store_id；表约束、查询、幂等键、墓碑和 epoch 都带作用域。示例值仅代表一个开发空间，不作为所有 Profile 的隐式默认值。应用账号授权后续接入，不能只靠 namespace 代替授权。
- 连接池参数是每个服务进程的预算，多副本总连接数需一起计算；不能每次请求或每个 Agent turn 新建一套 Engine。
- 选择 PostgreSQL 时缺驱动、缺 DSN、Schema 无权限、数据库不可达或模式版本不兼容，启动或接入该 Profile 应明确失败。
- 这是新配置的拟定契约。实际代码落地时还需补充 DEFAULT_CONFIG、根键登记、秘密登记、消费入口及行为验证，不能只添加无人读取的配置。

## 接入边界

数据库层统一命名为 `hermes_db`：`tables/` 定义 SQLAlchemy Core 表，`repositories/` 封装数据仓储查询与写入，`operations/` 组织完整业务事务，`engine.py` 管理连接池，`migrations/` 保存版本迁移。工厂入口为 `acquire_db`，配置桥接位于 `hermes_cli/db_setup.py`。具体依赖和调用示例见 [数据库层代码组织设计](postgresql-storage-code-layout.md)。本轮已选定 Core，不引入完整 ORM。

```text
CLI / Webapp / Gateway / Agent
              ↓
现有会话业务接口与运行账本语义
              ↓
hermes_db：后端选择、数据仓储与事务
              ↓
SQLite 后端 / PostgreSQL 后端
```

行为继续放在主题模块，不向 hermes_state.py 门面堆实现。创建、查询、消息写入和运行控制必须使用同一个后端，不建立一份仅供 Web 查询的 PostgreSQL 镜像，也不长期双写两个数据库。

所有直接操作连接或执行 SQLite SQL 的调用者都需要列入迁移清单。需要同时处理 SessionDB 注册表、网关运行账本、会话搜索、压缩、删除及后台任务，不能仅替换消息表的保存函数。

## 数据与事务要求

- 保留现有会话、消息身份、提示词内容与摘要、模型用量和所有业务可见字段。
- 执行准入去重、运行代次、租约、Worker 回执和删除墓碑保持现有行为。
- 事务锁定按 PostgreSQL 语义实现，避免依赖 SQLite 的全库写锁；未知提交结果不能直接当作失败后重跑。
- Schema 变更有显式版本与迁移步骤；应用实例并发启动时不得重复执行冲突迁移。
- PostgreSQL 搜索与中文/子串匹配须定义并验证契约；不以简单 LIKE 或 PostgreSQL 默认英文分词替代现有完整搜索能力后声称等价。
- 保持会话提示词与工具前缀稳定，数据库切换不重组或改写历史上下文。

参考 [PostgreSQL 事务锁](https://www.postgresql.org/docs/current/explicit-locking.html) 和 [psycopg 事务管理](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)。

## 新库初始化、后端切换与验证

本轮从空 PostgreSQL Schema 初始化，覆盖完整会话读写与运行事务；不开发 SQLite 整库导入、旧 Schema 升级、旧格式数据兼容或历史数据校验工具。Alembic 只管理新库建表及后续 PG Schema 版本。现有业务字段、提示缓存、消息保真与运行不变量仍须在新数据上验证。

PostgreSQL 实例由用户配置。本轮不连接用户数据库，也不管理 Docker 或数据库服务。后续可提供由连接配置启用的独立 Schema 集成测试入口；没有真实 PostgreSQL 测试证据时，不能声称事务、并发和完整会话后端已经验证。

选择 SQLite 与选择 PG 对应独立数据集。本轮不提供数据回迁，切换后端不搬运记录；PG Schema 或应用版本回退须依据具体版本兼容性验证，不能宣传为跨后端无损回滚。

## 验收标准

- 切换后端后，现有会话创建、历史、续接、工具消息、压缩、归档、删除、搜索及运行控制通过同一套行为契约。
- PostgreSQL 连接失败明确报错，不悄悄创建或使用 SQLite 保存新数据。
- 真实 PostgreSQL 验证包含并发写入、租约争用、重复准入、旧代次结果、事务回滚及重启读取。
- SQLite 模式的现有契约继续通过。
- 配置入口、秘密解析、Schema 版本、诊断及文档与实现一致。

## 实施状态

2026-11-07：Tasks 1–17 的实现检查点已在独立普通分支保存，包含 Core/同步驱动/Alembic、作用域配置、完整账本与普通入口接线。Task18 正在补发行验证、文档和审查。[实施计划](../plans/postgresql-session-storage-plan.md) 是状态和证据来源：真实PG尚未连接，迁移/并发/故障验收未执行，扩大回归存在失败及未完成部分，不得宣称完整后端已通过或可合并。

## Task 1 实施契约

2026-11-06：已建立 [业务契约与消费者清单](../plans/postgresql-session-storage-contracts.md)。后续表、操作和接线以该清单的作用域键、原子边界、保真编码和方法归属为检查依据。PG 仍未实现或验证。

## Task 15 搜索实现选择

新增 Schema revision `0002_search_projection`：全文分块向量、pg_trgm 和单字/双字候选数组配合精确复核。采用分块是为了让派生全文索引不因单个 tsvector 的 1 MB/词位置限制拒绝大消息写入；短语另做词边界复核，覆盖块边界和重复词位置上限。[PostgreSQL 全文限制](https://www.postgresql.org/docs/current/textsearch-limitations.html)

分块属于可再生派生数据，由对象全限定、`search_path=pg_catalog` 的 invoker 触发器在原消息事务内同步，不改变规范消息、提示词或工具快照。依然只要求管理员预备 pg_trgm；不安装数据库服务或扩展。默认工具正文搜索保留 8192 字投影，显式 tool 搜索保留全正文路径。PG 片段无 SQLite 的高亮标记，默认排序按匹配单元覆盖数、时间和物理 id 稳定排列；时间排序及分页继续提供。固定语料、长消息和实际查询计划仍需真实 PG 执行，离线规划/SQL 编译通过不等于兼容性验收完成。

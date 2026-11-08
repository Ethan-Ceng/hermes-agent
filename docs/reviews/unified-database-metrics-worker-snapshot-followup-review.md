# Metrics / worker snapshot 交界独立复审

审查范围：Foundation 在 8d6f 完整 safe-mode 合同中观察到的 config-only worker `.env` 读取，以及 Root 当前 `hermes_cli/db_setup.py::storage_backend` 的局部修复。只读源码和现有真实审计证据；未修改生产、仓库测试或环境，未运行替代红绿测试。Root 负责最新完整 CLI 合同与 PG 回归。

受审 `db_setup.py` SHA256：`72647E6356629183E365B36FAA959DF0677B8216E58A88E52BEDB9AC140491ED`。本次差异只增加真实 `worker_config_snapshot() is not None` 分支，仍调用原 `_storage_config(home)` → `_storage` → `_backend`，跳过其之前的 `_owning_profile`。

## 确认的问题与修复边界

已读取 `unified-database-foundation-operations-followup-review.md` 末节及 `.build/postgresql/review-foundation-safe-mode-owner-env-observed.log` 的实际 worker 打开栈：

```text
conversation_loop → lifecycle → observability.observe_lifecycle
→ relay_shared_metrics._reconcile_send_consent_once:1411
→ storage_backend → _owning_profile → build_profile_secret_scope → owning .env
```

`relay_shared_metrics.observe_lifecycle:1435` 在检查 collection gate 前先执行 consent reconciliation；因此 config-only 保留插件/lifecycle 时会到达它。原 `load_user_config_effective:67` 自身优先返回绑定 snapshot，额外 Profile `.env` I/O 发生在进入这个 loader 之前。该位置确实适合在 selector 中去掉多余 secret hydration；不能用关闭 metrics、插件、lifecycle 或删除审计断言解决。

当前局部修复没有新增配置来源或 backend 默认值。已有 worker snapshot 时，`_storage_config` 原本也会经 snapshot-aware loader 返回冻结配置；缺少 storage 时原 `_backend` 默认 SQLite，明确 PG 时仍返回 PG，无效 storage / 遗留 `storage.session` 仍由原校验拒绝。没有绑定 worker policy 的真实 owner 继续走完整 `_owning_profile` 和有效配置解析。不要把此条件扩大为环境变量、仅 safe-mode 布尔值或任意 agent 默认配置。

注意，此 fastpath 只负责探测；它没有修改 `resolve_db_configuration`，也没有把 worker agent 的默认 snapshot 注入 owner 已持有的 settings、scope 或资源。

## PG metrics 获取和拥有者边界

实际调用链仍为：

```text
SharedMetricsStore.__new__ → shared_metrics_storage.postgres_store
→ PostgresMetricsStore.__init__ → capture_metrics
→ acquire_profile_domain('metrics') → resolve_db_configuration
→ acquire_domain / schema check / real PG transactions
```

`hermes_db/domains/metrics.py` 的不可变 `MetricsRef` 保留 `profile_home / store_id / target`。每次 `open_metrics` 重新绑定捕获 Profile，获取真实指标域，再检查 backend 必须 PG、store_id 必须一致、目标指纹必须一致；不满足就拒绝，未新增 SQLite 或内存回落。`PostgresMetricsStore.reconcile_send_consent` 仍调用真实短写事务的 `metric_consent.reconcile`。后台 sender 保持捕获 store 和 context thread 语义。

`test_metrics_consumers.py` 的既有合同具体覆盖捕获 Profile 后在另一 ambient Profile 的线程写入、setup opt-out、真实 scoped session age；`test_metrics_consent.py::test_fully_disabled_lifecycle_closes_each_profile_without_sqlite_file` 覆盖 collection/send 全关闭时，两个 PG Profile 的 consent 仍实际关闭。它们是本次改动后需保留/重跑的证据，不能以一个 SQLite config-only selector 用例代替。

结论限定为：**没有发现当前 fastpath 本身禁用普通 owner 的 PG metrics、改变已捕获 metrics 资源，或把 owner 现有 PG store 切成 SQLite 的新代码路径。** 本轮是独立静态复审，不宣称这些 PG 合同已在当前文件 hash 上绿跑。

## 剩余交界，不得以本次窄修外推通过

1. **默认 worker snapshot 与遗留 metrics SQLite。** `_reconcile_send_consent_once` 仅在 `backend == sqlite` 且 send=False 且 `metrics.sqlite3` 不存在时短路。一个属于真实 PG Profile 的 config-only worker，其默认 snapshot 不含 storage 时，selector 在修复前后都会返回 SQLite；若该 Profile 留有旧 `telemetry/shared_metrics/metrics.sqlite3`，后续 `SharedMetricsStore.__new__` / SQLite `_connection` 的 `assert_sqlite(home)` 又都会读到相同 snapshot，代码上没有实际 owner PG 身份的额外交叉核对。当前完整 CLI 原合同使用无旧 metrics 文件的临时 home，不能覆盖这条。此处是从代码追踪得到的待实证边界，本 Reviewer 未执行该反例，不将它冒充本次 fastpath 引入的新红测。
2. **普通 managed PG worker 的指标获取。** `acquire_domain:28` 保留 `_owner_only()`；worker 在成功自注册后是 process-scoped compute-only。若普通 worker snapshot 含 PG 且触发指标 store 获取，`PostgresMetricsStore.capture_metrics` 会遇到 owner-only 拒绝；`relay_shared_metrics._get_runtime:1657` 捕获初始化异常并记 `_RUNTIME_FAILED`。本轮在 managed worker / worker RPC / RuntimeSessionStore 范围未找到指标域的 owner 转发消费者。这是既有边界，不是新增 fastpath 造成；但它意味着不能把“owner PG metrics 正常”直接外推为“全部 managed worker 的 model/tool 指标均持久化”。若总体验收要求该语义，需要真实普通 PG worker → owner metrics 证据。
3. **探测和真实 acquire 不可混淆。** 新分支不应扩展到 `resolve_db_configuration`、`open_metrics` 或 `acquire_profile_domain` 来跳过 owner/settings/secret 校验，也不应为了让 worker 直开 PG 指标而移除 `_owner_only`。若后续验证发现上述交界，沿明确 owner 资源/受控持久化通道处理，保留 opt-in、consent withdrawal 和 no-SQLite 合同。

最小验证建议交 Root：原未修改的完整 `tests/hermes_cli/test_safe_mode.py`（普通、safe1、坏 YAML safe2、config-only 插件和 worker open audit）；普通 owner 的 PG metrics consumers/consent/store/fault 组；原 PG owner inventory/资源不受默认 worker snapshot 改选的反向断言。遗留 metrics SQLite 的 bypass worker 场景另记证据，不假设原 CLI 用例已经覆盖。

本次局部 selector 方向符合已定位根因；最终修复验收仍取决于 Root 的真实红绿和完整原合同。上述未实证交界与全局门禁保留，整体 **FAILED / CHANGES_REQUIRED**。

## 真实 PG daemon / managed worker 补证：两个 major 均已复现

按 Root 后续明确要求，将上节两条静态限制升级为实际端到端验证。本节取代“仅待实证”的状态，不撤销前节对 selector 窄修的范围判断。

ignored probe：`.build/postgresql/test_review_pg_managed_metrics.py`。复用已有 `pg_profiles`（私有 config、数据库归属检查、随机且拥有者标记受控的 Schema）、`scenarios.kanban_full_gateway.daemon` 的普通 `python -m gateway.run`，及 `local_recovery_probe` 的真实 ticket/WebSocket RPC。设置 `gateway.managed_workers=True`、custom loopback model、明确指标 opt-in。没有设置假 `is_worker_process`，没有替代 metrics 或 worker 协议；真实 owner 启动 `python -m agent.managed_worker`，真实自注册、消息持久化、PG worker/admission 终态及退出均检查。

测试进程保留原 PG autouse SQLite guard；daemon 和所有继承的子进程另由 sitecustomize 同时替换 `sqlite3.connect` 并注册 SQLite audit 拒绝，记录实际 pid/parent_pid 和调用栈。读数通过真实 PG store/transactions；结束 owner 后重新构造 PG metrics store；同随机 Schema 的 peer store 指标为空、没有本测 session。日志和 JSON 都不输出 DSN、`.env` 内容或凭据。

冻结观测版本为 `51b3e61c6c2c6338f84acc5965f32c078a58d520`，使用已有 PM Python 3.14.9。Core Relay **nemo-relay 0.11.0** 的既有环境 metadata 与实际 import 已核对；观测更直接记录真实 worker 中 `_load_nemo_relay` 成功返回 module、`nemo_loaded=True`。未安装依赖。

### [major] 普通 opt-in PG managed worker 的模型指标未持久化

位置：`hermes_cli/observability/relay_shared_metrics.py:266` / `:1652`，`hermes_db/metrics_store.py:18`，`hermes_db/factory.py:28`。

真实普通 worker 的结果：owner PID **2859222** → compute worker PID **2859405**；loopback 主模型恰 1 次；原回复出现在 PG session snapshot；PG admission 为 `terminal/completed`、compute ledger 为 `terminal`，worker 真正退出。没有任何 SQLite 尝试。结束 daemon 后重开 metrics，仍只有 `hermes.startup.latency`，`hermes.model_route.count` 为 **0**；peer 指标为空且没有本测会话。

不能归为 SDK 缺失或 collection 关闭：新观测 JSON 的 `metrics_boundary` 记录该 worker 真实 frozen policy 为 `collection=True, send=False, backend=postgresql`，`enabled()` 实际返回 True，Core Relay 已加载。随后实际运行：

```text
relay_shared_metrics._get_runtime → _Runtime.__init__ → SharedMetricsStore()
→ PostgresMetricsStore.__init__ → capture_metrics
→ acquire_profile_domain('metrics') → acquire_domain('metrics')
→ _owner_only → WorkerPersistenceError('owner_store_access_from_worker')
```

完整异常来自本测 owned `logs/agent.log:49–70`（另有 `logs/errors.log` 副本），已在 JSON 的 `logs` 字段脱敏保存；`_get_runtime` 记录初始化失败并返回 None。观测同时记录实际 `_owner_only` 入口的 worker=True，未伪造此标志。业务完成不能掩盖指标丢失。

建议：补明确 owner 持久化协议或等价正确的 domain port，让真实 worker 产生的 allowlisted 指标经所属 owner、store_id、target 和有效 execution/epoch 边界落到 PG；保留 bounded payload、幂等/失败重放及关闭/退出 drain 的合同。不得移除 `_owner_only`、直接让 compute worker取得 owner PG 资源、关闭 collection 或吞掉初始化错误后声称指标已可用。整改后的永久测试需要模型指标真实出现、owner 关闭/重开仍存在、peer 隔离及零 SQLite。

### [major] PG config-only worker 会尝试打开遗留 metrics SQLite

位置：`hermes_cli/observability/relay_shared_metrics.py:1413`，`shared_metrics.py:225` / `:548` / `:530`，`shared_metrics_storage.py:9` / `:16`。

最终独立负例：owner PID **2861537** →实际 compute worker PID **2861719**。owner 配置保持 PG；session.create 设置 `ignore_user_config=True`，仍执行真实 worker、loopback 模型、PG消息/终态。该 worker 默认 snapshot 记录 `collection=False, send=False, backend=sqlite`，保留 config-only 插件/lifecycle 语义。

PG home 的旧 `telemetry/shared_metrics/metrics.sqlite3` 路径存在时，真实 audit 捕获 **1 次 SQLite 连接尝试**，被严格 guard 拒绝。实际栈：

```text
managed_worker.execute → run_worker_turns → conversation_loop
→ lifecycle.invoke_hook → relay_shared_metrics.observe_lifecycle
→ _reconcile_send_consent_once:1413 → SharedMetricsStore.__init__:225
→ _ensure_schema:548 → _write:542 → _connection:530 → sqlite3.connect
```

`_reconcile_send_consent_once` 先于 collection gate，且 `SharedMetricsStore` / `assert_sqlite` 使用默认 agent snapshot 的 SQLite 选择，未沿真实 PG owner 身份隔离文件型指标。guard 异常被 metrics 捕获后模型仍完成；因此只检查回复或没有新建 SQLite 文件会漏掉这次非法访问。旧文件字节不变、peer 为空，无法冲淡零 SQLite 合同失败。

本负例的遗留文件是直接写入的 4096 字节 SQLite-header artifact，不为测试准备调用 SQLite；它用于验证“存在旧路径也不得打开”的合同，并未声称覆盖旧指标数据库的数据兼容性或旧 counter 内容。连接在解析任何 SQLite 内容前已被拒绝，真实访问栈与此内容无关。

建议：config-only 的 agent 默认配置不能决定实际 owner 的持久化 backend。将 consent/persistence 交给 owner 明确资源处理；session 的默认 disabled/send=False 也不能被误当成 Profile 用户主动撤回 consent。保留原 config-only 默认采集策略、插件/lifecycle 和 Profile 文件不读取合同，不以删旧文件、放宽 SQLite guard 或禁用 metrics 修复。

### 执行账本与观测修正

全部通过 `run_matrix_linux.py` → `scripts/run_tests.sh`，retries 0、`-j 1`、原 runner deadline；ignored 文件单独加载原 tests / hermes_db / postgresql conftest，避免正常 tests 的重复 plugin 注册。实际可复用命令核心为：

```text
run_matrix_linux.py --state task24-selector-checkout-state.json --log <name>
  /mnt/d/AI/hermes-agent/.build/postgresql/test_review_pg_managed_metrics.py
  -j 1 -s --tb=short
  -p tests.conftest -p tests.hermes_db.conftest -p tests.hermes_db.postgresql.conftest
```

PG 私有 config 仅由现有 runner 添加，未抄录凭据。记录如下：

| 日志 | 真实结果和范围 |
| --- | --- |
| `review-pg-managed-metrics-red.log` | 首批 current-worktree 两项，2 failed / 88.56s / exit 1。普通项准确在 PG 模型指标为 0 处红；负例已有真实 SQLite audit，但 Reviewer 的“所有 HTTP 请求恰 1 次”观测假设先失败，不能把此计数失败记作产品负例。原始 JSON `review-pg-managed-metrics-evidence.json` 保留。 |
| `review-pg-managed-metrics-observed-red.log` | 冻结 51b3、完整真实执行与观测，2 failed / 42.18s / exit 1。普通项再次在模型指标为 0 处红，并取得实际冻结 gate、Core Relay 加载和 owner-only 完整异常。负例 exact user prompt 仍出现两次，因 title 请求使用相同 user_snippet，计数分类尚需修正；SQLite audit 本身再次成立。 |
| `review-pg-managed-metrics-config-only-final-red.log` | 仅补负例，1 failed / 1 deselected / 25.33s / exit 1。依据实际 `title_generator.py:516` 的固定 system prompt 前缀分类，实测请求为 `['turn', 'title']`，业务 prompt 1 次；其余终态/peer/退出/文件不改断言通过，最终准确在 **Actual PG worker attempted legacy SQLite** 处红。没有改生产或原仓库断言。 |

最终合并观测 JSON：`.build/postgresql/review-pg-managed-metrics-observed-evidence.json`。其 `ordinary_opt_in` 保留 51b3 普通观测，`config_only_old_sqlite` 保存最终负例；每项都有实际 home / owner_pid、ledger、PG 重开结果、peer、模型计数、进程审计与相关 owned 日志摘录。首轮只搜 stderr 未包含 agent/errors 日志，因此当时没有直接归因；第二轮按实际日志证实根因。观测计数的两次修正明确记账，不隐藏或改写原日志。未做“反复争绿”，最终两条业务合同均为红。

这两项是关键验收缺口，已立即发给 Root；前节 selector `.env` 窄修不能闭合它们。Root 负责设计记录、生产整改和永久合同；Reviewer 未改实现/仓库测试、未提交或安装。**整体继续 FAILED / CHANGES_REQUIRED，Task 24 不得关闭。**

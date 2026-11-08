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

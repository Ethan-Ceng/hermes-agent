# PostgreSQL 入口恢复投影阶段性独立审查

当前状态：本轮发现及最终 hex/0004 整改验证缺口均已关闭；最终证据见末节。整体分支仍为 `CHANGES_REQUIRED`，保留 Task 18 发行实库安装、整体基线与构建门禁。

## 审查范围

- 日期：2026-11-07；分支：`feat/postgresql-session-storage`；对象为 Task 17 当前未提交的 `runtime_recovery.py`、`runtime_viewer.py` 及对应契约/真实 PG 测试。
- 独立 Reviewer，生产只读；未读取凭据或连接数据库，未进行 Git 写操作。
- 阅读完整生产 diff、新增 recovery/projections 测试、现有 webhook delivery/finalization 调用者、viewer 契约、调试文档、实际日志和 HTTP fixture 的 Profile 解析路径。

## 问题列表

### [major] Viewer 的文本 getter 仍受 policy 其他字段的 NUL 影响

位置：本轮初版 `hermes_db/runtime_viewer.py:46`，`live_store_facts` 对整段 policy 执行 `json_path_text`。

将 TEXT 与 JSONB 比较改为文本 getter 可以修复类型错误，但 PG getter 仍解析整个 JSON 输入。`LocalSessionPolicy.skills_prompt` 可以保存字符串，当前创建和恢复规则未禁止其中的 NUL。因此即使 `entry.session_id` 完全正常，其他 policy 字段的 NUL 也会使整个 viewer 列表读取失败。

复现：沿用 viewer 契约，保留 `entry.session_id="target"`，在同一合法 policy 对象内加入 `skills_prompt="before\u0000after"`，随后调用 `_store_facts(store, ["s", "absent"])`。主 Agent 已按此增加契约；本 Reviewer 读取了真实 PG 的 `.build/postgresql/pg-task17-viewer-nul-red.log`：1 failed / 2 deselected，失败发生在 `live_store_facts`。这不是依赖直接篡改数据库根 JSON 类型的假设。

建议：对请求的当前 store 会话范围读取 policy 文本，在 Python 提取目标 ID，再按相同 store 查询目标结束时间；保持与列表、pending 数据在一致读快照中，不改写或删除 policy 内容。主 Agent 已接手整改；本段记录初版发现，后续通过证据应追加处置状态。

## 分批恢复路径核对

- 每个查询都带 `store_id`。按作用域 `max(seq)` 固定上界，页条件为 `seq > cursor AND seq <= ceiling`、升序、每页最多 128 行，cursor 取本页最后一行；空页终止。静态检查未发现 off-by-one、重复或连续新增导致无限扫描的问题。
- 连接在读取每批后释放，再用 Python 解析原文；不会为 NUL 清洗正文、改变原 payload 或把恢复结果写回 SQLite。payload 查找需扫描所属 store 的准入历史，最终列表仍可能较大；该代价已在调试记录说明，不能宣传为按 chat 索引查询或总工作量为常数。
- SQL 预先限定 finalization 的会话 source、结束状态、准入终态和 generation；真正结束操作再次检查 epoch、root、当前代次、准入所有者及后继 pending。分页候选不是授权或无条件结束指令。
- 分页使用多个短读事务，不提供跨全部页的单一快照。扫描过程中才提交或才变成候选的低 seq 记录可能由下次恢复观察；现有 finalization 再校验可阻止过时结果造成错误关闭，不能据此宣称本次扫描囊括所有并发变化。
- 非 object payload 的候选已撤回：`hermes_state_runtime._json:57` 在准入写入前明确拒绝非 dict，公开准入无法写入该候选。不建议为这个不可达前提增加防御代码。合法对象内 `native_text_v1`/`source` 的非 dict 情形已有检查。
- 根据本次建议，已新增跨 128 行的契约：前 129 条为无关 dict，最后一条为含 NUL 的目标，验证满页后仍能找到下一页。该契约已接入真实 PG wrapper；需要将其新增后的最终执行结果作为证据，不能只沿用旧四条 payload 的测试结果。

## 测试与其他证据

- 初始真实 red 日志与 diagnostics 分别定位 webhook 的 22P05 和 viewer 的 42883；中间名为 `pg-task17-projections-fixed.log` 的文件仍是 1 failed / 1 passed，不能据文件名当作绿灯。
- 此后已观察 `.build/postgresql/pg-task17-surface-final.log`：2 文件，13 passed / 0 failed，24.8s，包含跨满页测试。新增 viewer NUL 回归发生在其后，因此这份通过不能覆盖该新边界及后续整改。
- 已观察较早的扩大离线日志 `pg-task17-offline-regression.log`：103 文件，521 passed / 0 failed / 2 skipped，54.6s；`pg-task17-projections-checks.log`：14 项 ok，6 文件 0 blocking / 0 advisory。它们同样不能替代后续 viewer 整改和新测试的最新复验。
- automation 缺失/null 入选，空对象/false 排除；NUL 原文、chat/store 隔离均有行为契约。测试通过实际公开能力建立数据，不读取源代码。
- HTTP 503 的 fixture 修正已核对：根隔离 fixture 显式覆盖 `DEFAULT_DB_PATH` 时，生产 `_default_db_path()` 按既定规则优先此值；surface fixture 恢复 `_IMPORT_DEFAULT_DB_PATH` 后才测试 call-time Profile resolver，并增加实际 home/authority 断言。此项是测试组合修正，不是 PostgreSQL 生产降级修复。

本 Reviewer 只核对主 Agent 已执行日志，没有另连数据库重跑。当前没有独立发现另一个确定的重大分页或授权缺陷。

## 门禁与结论

**`CHANGES_REQUIRED`，不批准完整分支。** Viewer NUL 边界在本轮初版得到真实红灯，需完成整改并取得最新局部、离线和静态证据；Task 17/18 的总体后端及最终验收仍须按计划完成。本报告不将任何较早绿灯外推到后续修改。

## Viewer 整改后独立复查

已重新读取当前 `runtime_viewer.py` 的完整整改 diff：只查询请求会话对应的 scoped policy 原文，在 Python 提取 `entry.session_id`，再按相同 store 读取目标结束时间。会话列表、policy、目标 ended 和 pending 均在同一个 `_read` 的 REPEATABLE READ 快照内，原有隔离和一致性边界保留。没有清洗或改写 policy。无消费者的 `json_path_text` 已移除，不保留内部兼容壳。

主 Agent 的中间实现曾因 `dict(CursorResult)` 出现 TypeError，已在当前代码改为 `.all()` 后构造字典；该中间失败不计绿灯。本 Reviewer 已读取新增 NUL 契约之后的最终日志：

| 复验 | 已观察结果 |
| --- | --- |
| `pg-task17-projections-reviewed-final.log` | 3 passed / 0 failed，6.6s；覆盖 viewer policy NUL、webhook NUL/automation/store/chat 及跨满页扫描 |
| `pg-task17-reviewed-offline.log` | 103 文件，522 passed / 0 failed / 2 skipped，87.2s；包含两个 recovery payload 契约和 viewer 契约 |

以上均为 `.build/postgresql/` 中主 Agent 已执行日志的独立核对；本 Reviewer 未另连数据库。初版 viewer major 在此局部范围内关闭，最终 diff 未发现新增确定缺陷。最新代码之后的全部静态检查仍应由主 Agent 取得并记录，不能沿用先前六文件检查来证明后续修改。

本轮没有把剩余 `model_config`/`display_metadata` 的所有 JSON selector 纳入已验证声明。已向主 Agent 提供具体 API `model_options` 保存 NUL 的入口与相应公开查询候选，是否另行立项按可复现结果决定，不把未经实证的泛化风险写成已确认缺陷。

**更新结论仍为 `CHANGES_REQUIRED`，不批准完整分支。** 原 viewer 问题已关闭，剩余 Task 17/18 和最终门禁按最新计划继续。

## 0004 模型标记投影独立复查

已阅读此次完整 diff、`0004_model_markers.py`、`json_paths.py`、新增迁移/模型配置/路径测试及相应日志；仍未读取凭据或连接数据库。先前模型配置候选已经实证：正常 API 创建可原样保存 `browser_model_lock.model_options.extra_body.stop=["\u0000"]`。原 `key_scan` 和 `deletion` 是有效 SQL 红灯；最初 listing 误用参数导致的 TypeError 不算第三个有效 SQL 红灯。

核对结果：

- 新的 `delegate_origin` BYTEA 和两个存在标记只派生自原 model_config。字符串来源按 UTF-8 保真编码，字段存在性使用非 None 判断，因此 false/0/空串与 null/缺失的区分保持。业务会话映射去除三个派生字段，不把它们暴露为普通会话字段。
- `create_on_connection` 是当前唯一 sessions INSERT；已有会话的 merge、patch、`update_session_meta`、Worker sidecars、prune/compression 配置写入均经中央 `repositories.sessions.update_session`，与原 model_config 在同一 SQL/事务重算投影。
- 压缩/分支/Worker child 的会话构造走上述入口；portable import 在构造时重算，跨 store move 的原始记录 copy 也通过中央 update 再计算，adoption 通过 portable import。正文 INSERT SELECT 克隆不绕过会话配置写入。静态追踪未发现普通生产 model_config 写入旁路；异常会使同事务投影和原值一同回滚，条件更新未命中不会单独留下投影。
- 删除闭包、孤儿候选、列表固定 marker 过滤改用有作用域派生字段；没有再解析模型 stop 等无关 JSON。迁移不修改 0001–0003；0004 的回填算法自行冻结，不导入当前 metadata，按 `(store_id,id)` 每批 128 行覆盖共享 Schema 中全部当前 store，保留原 JSON 文本。
- 任意配置路径扫描在固定的当前 store/RR 快照内按 id keyset 读取 128 行，以 Python 求值；保留 newest-first 输出。路径测试覆盖 dotted/quoted key、转义引号、数组索引/尾索引、false/0、NUL 和明确无效路径。不会将路径拼进 SQL。该查询仍需扫描当前 store 的配置，不宣称具有固定键投影的查询成本。

### [major，已修复] 纯派生列回填会使已有移动内容摘要漂移

位置：`hermes_db/move_values.py:snapshot_digest` 与 `repositories/profile_move.py:snapshot`。

独立复查发现：新列随 raw session 进入 move/adoption 快照，原摘要函数未排除它们。0003 已生成的源/接收票据会仅因 0004 回填而失效，即使模型配置、消息、提示和用量没有变化；fresh-0004 的移动测试不能覆盖此升级边界。

主 Agent 已增加 `test_move_fingerprints.py`；本 Reviewer 读取 `pg-task17-move-fingerprint-red.log`，源与接收摘要两个参数均有效失败，另外 model-config/JSON-path 合计 20 项通过。当前代码已从内容摘要排除三个新派生列，同时继续包含原 model_config，修改真实业务配置仍改变摘要。后续双后端局部验证已包含这两个参数并通过，见下节；此问题属于当前 PG revision 的连续升级，不是 SQLite 历史格式导入。

0004 初轮实库结果 `pg-task17-markers-migration-tests.log` 已观察：4 文件 23 passed / 0 failed，22.2s，包含 0003→0004、重复升级、双 store、原文保留、当前入口和 marker 更新。`pg-task17-markers-checks.log` 为 14 项 ok、21 文件 0 blocking / 0 advisory；后加摘要修复仍须最新检查。初轮离线的新 marker 契约混入 physical parent 排除规则，导致 SQLite 一项失败；主 Agent 已将该契约改成无 physical parent 的 marker 会话，随后上述局部 model-config 文件 8 项通过。不得把初轮失败日志算作整轮离线通过。

另已向主 Agent 提供正常 Desktop `title_preview` 可保存 NUL 到 display_metadata 的具体入口、helper 链路及公开 display 查询复现候选；目前本报告不把尚未观察实库红灯的候选升级为已确认缺陷。它也不属于本节已验证的 model_config 投影范围。

**结论继续 `CHANGES_REQUIRED`。** 0004 的核心写路径未发现投影遗漏；摘要修复待最终复验，0004 改变当前 Schema，全部真实 PG 主题及发行资源需要按最新 revision 重新验收，不能沿用 0003 的历史绿灯批准分支。

## Display 查询投影与最终键编码复查

Desktop 预览的候选已经实证：`admit_display` → `worker_display_kwargs` → 公开追加 → `display_message_count` 在原实现触发真实 PG 失败，日志 `pg-task17-display-metadata-red.log` 为 1 failed / 7 deselected。当前 0004 尚未发布，主 Agent 在冻结前将消息派生投影纳入同一 revision；0001–0003 保持不变。

本 Reviewer 已读取最终 `query_projections.py`、所有消费者 diff、中央消息写入、克隆/导入/移动及冻结回填算法，结果如下：

- 值使用 `json.dumps(ensure_ascii=True, sort_keys=True, separators=(',', ':'))` 的 ASCII token；None 保留为 JSON null。NUL 与字面反斜杠转义、布尔值与同字字符串、数值与同字字符串保持区分。SQL 提取的是派生 JSONB 中的 ASCII 字符串，不再次将 token 解析为原 JSON。缺失和 null 的 `IS NULL`/`IS NOT NULL` 选择语义保持。
- 初版把含双引号的 token 直接作为 JSON key，在真实 PG 可用，但 Core/SQLite 的 JSON path 无法定位该键；全离线日志 `pg-task17-all-projections-offline.log` 得到三个文件共五项失败，不能计为通过。最终改为统一 `query_key = query_token(key).encode('ascii').hex()`，实时写、SQL 查询和 0004 回填使用同一算法。hex 是可逆编码，不引入哈希碰撞，并避免 SQLite quoted-key 限制。
- 全部原 `json_value` 消费者已替换：owner 查找、reaction 存在性、结果通知幂等、display/model-only 选择。四种既有 PG model-only 真值 True、1、`'true'`、`'1'` 用显式 token 集合保留；delivery_notice 缺失的空串回退也转成同一 token。未发现遗留的原 JSON getter 消费路径。
- `insert_row` 同事务生成 `display_query`；`update_row` 在 metadata 改变时同步重算。全部普通 metadata 改写均经过该中央入口；压缩 clone 和 archived twin 的 INSERT SELECT 复制此列；portable import 和跨 store copy 重新走 insert_row。原 metadata 不变，异常使原值和投影一同回滚。`decoded_row` 去除此内部列，业务消息、导出和移动内容摘要不纳入它。
- 0004 用自行冻结的同一编码算法按 `(store_id,id)` 每批 128 行回填消息；JSONB bind 类型明确，不从当前 helper 或 metadata 导入算法。测试覆盖两个 store 的原 metadata 不变和派生结果。最新 hex 版本仍需重新取得真实迁移执行证据，不能只靠此前 token-key 版本的成功。

已观察最新局部绿灯 `pg-task17-projections-dual-tests.log`：6 文件，**42 passed / 0 failed，24.3s**。包含两后端的 admitted NUL 预览、metadata 修改后的 owner 查询、字面转义与实际 NUL 不混淆、既有 reaction/result/model-only 行为、模型 marker/路径和两个移动摘要参数。因此初版 SQLite 键查找失败与移动摘要 major 在此局部范围内关闭，最终 diff 未发现新增确定缺陷。

另已观察 `pg-task17-query-projections-tests.log` 的真实 PG 28 passed（19 消息、8 入口投影、1 迁移），以及 `pg-task17-all-projections-checks.log` 的 14 项 ok、31 代码文件 0 blocking / 0 advisory。它们均早于最终 hex 变更；在运行的旧键版本全 PG 也不作为 hex 最终证据。本 Reviewer 未重跑数据库，也未把任何部分进度当作完整通过。

**当前结论：`CHANGES_REQUIRED`，不批准完整分支。** 本轮独立发现均已在代码及局部契约范围修复；最终 hex/0004 的全离线、全部真实 PG、最新静态及 Task 18 发行和最终门禁仍须收齐，不能沿用中间版本结果。

## 最终 hex/0004 证据收口

本节只核对主 Agent 提供的最终日志并更新处置状态，没有重开已关闭实现、连接数据库或读取凭据。已逐一读取以下最终结果；主 Agent 已直接确认各次进程 exit 0：

| 最终验证 | 已核对结果 |
| --- | --- |
| `pg-task17-final-hex-postgresql.log` | 当前 0004/hex 的全部真实 PG 主题，20 文件，284 passed / 0 failed，237.4s |
| `pg-task17-hex-projections-offline.log` | 108 文件，546 passed / 0 failed / 2 skipped，73.0s；两个发行参数缺失的 skip 不计通过 |
| `pg-task17-hex-projections-checks.log` | 14 项检查全部 ok；31 个代码文件，0 blocking / 0 advisory |
| `pg-task17-changed-consumers-final.log` | 14 个受影响消费者文件，189 passed / 0 failed，74.6s |

日志均位于 `.build/postgresql/`。这些是最终键编码及当前 revision 的完整结果，替代本报告前面各阶段“最终版本尚缺复验”的限制；较早红灯和中间版本日志仍保留为问题定位及整改过程证据，不混算为当前失败。

本轮 viewer、模型配置、display_metadata、移动摘要及 Core/SQLite 键查询问题均已关闭；最终 hex/0004 的真实 PG、离线、消费者及静态验证缺口也已关闭。本次独立复查没有留下未处理的确定代码问题。

**最终阶段结论仍为 `CHANGES_REQUIRED`，不批准完整分支。** 剩余原因仅是 Task 18 发行实库安装、整体基线与构建等总体门禁尚未完成；不再将本轮已通过的整改验证列为缺失。

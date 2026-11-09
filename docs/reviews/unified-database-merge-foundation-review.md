# develop 合并：统一 PG foundation 接口与语义复审

审查输入：ours `264dc200772afce2d681e81f6bf55221bbc05f37`，incoming `781dc1e05fc7e781b714790d6ea2ab459835b3bb`，merge base `ff09cead02`；三方/初始冲突现场在 `.build/postgresql/merge-781dc1-audit/`。本 Reviewer 只读审查新增 `hermes_state*` 接口及 gateway/agent/delegate 消费者与 PG 的差异，仅编辑本报告；未实施、stage/commit、运行测试、连接数据库或操作正式Profile，未派生agent。

最终限定状态见末节：**本次用户已发起的develop→feature本地合并foundation整改APPROVED；整体Task24仍BLOCKED / CHANGES_REQUIRED。** 中间各节为保留的真实发现和检查点，不代表最终源码仍有这些未修问题。

下列是本轮初始合并候选的已核对缺口及最小整改方向。Root正在并行整改，已开始接入PG snapshot及room端口；本文不是声称这些文件其后仍未变化，也未给未结算实现判绿。当前增量处置状态见文末复审，不能把初始发现继续当成现源码未修。旧689项是旧生产证据，不能证明这个合并候选；非WSL七项原缺证继续保留。

## 发现清单

### [major] owner binding 的内部符号/参数变更破坏现有双后端入口

位置：`hermes_db/repositories/mutation_binding.py:6`、`:68`，`hermes_db/authority_access.py:108`，incoming `hermes_state_mutation_binding.py:42`、`:58`。

PG仍导入已删除的 `_bindings_agree`，新SQLite模块只公开 `bindings_agree`；经过PG history/import/retirement模块导入会产生ImportError。SQLite authority分支仍以三参数调用 `binding_names(saved, actor.profile_id, actor.subject)`，incoming签名已变为 `(saved, subject)`，会TypeError。

不能只把PG import改名：incoming `67c9a47c02`/`ed06004f89`/`a9ff9799e2` 的意图是SQLite数据库随home移动后忽略binding的旧home半部、按同一owner识别；PG已有稳定的 `store:<store_id>` namespace（`binding_names:14`），必须保留这项硬检查。最小改动是SQLite分支改新两参；PG本地实现scoped `bindings_agree(first, second, scope)`，两个非空binding都验证shape及namespace为当前store，再用 `gateway.owner_identity.owners_agree`，两None一致、一None不一致。不要给SQLite加旧名re-export掩盖接口迁移。

另 `hermes_db/operations/portability.py:111` 的canonical导入父关系仍用binding原字符串相等，未承接a9ff的同owner兼容。应在“父binding非空”前提下使用同一PG scoped比较；未绑定父仍拆、同owner但外国store标签仍拒绝，不能为移动home削弱store边界。

### [major] stored session list 新参数和picker读端口未移植

位置：`gateway/session_listing.py:73`，`hermes_db/session_queries.py:54`，`gateway/session_picker_fields.py:17`、`:38`、`:61`。

stored list现在无条件传 `workspace_key=workspace`，即使workspace为None；PG `list_sessions_rich`签名没有此参数，普通stored feed也会TypeError。新picker还直接调用 `sessions_in_workspace`、`picker_session_facts`、`session_current_segments`，初始PG门面没有这些方法。

需把文件夹规则移到PG原过滤查询中，在LIMIT/OFFSET与pin补齐之前按同repo/该目录及子目录过滤；根row提供cwd/workspace，tip或local receipt提供当前segment/preview/reply等字段。不能仅接收后丢弃参数或先截页后Python过滤。

### [major] stored transcript 的读快照、keyset页与子agent读取缺少PG接口

位置：`gateway/session_stored_reads.py:174`、`:386`、`:452`、`:518`，`hermes_state_stored_reads.py:130`、`:196`、`:215`、`:309`，`hermes_db/session_store.py:43`。

初始PG门面缺少 `_resume_lineage_ids`、`transcript_read_snapshot`、`transcript_lineage_ids`、`transcript_cursor_state`、`transcript_display_index_complete`、`transcript_segment_page`、handoff/context读及picker/子agent查询接口；whole-lineage分支还直接消费SQLite门面的 `_fetch_conversation_rows`/codec helpers。因此已授权普通 `session.transcript` 和完成子agent的读取在进入业务页之前即会AttributeError。

已独立读取Root的 `audit/pg-merge-contracts-red.log`：canonical runner真实PG **3 failed/15.3秒**，其中两个实际错误分别为snapshot/cursor_state缺失，第三项为room端口（由Root另行整改）。Root随后已接入 `SessionReadSnapshots`，本项处于整改中，不能凭新类存在关闭原红。

PG已有 `postgresql/transactions.py:31` 的REPEATABLE READ checkout，可复用为每次完整页的同一Connection，并使所有嵌套public reads复用该pin、可重入且最终归还。每个嵌套读各checkout一个RR事务仍不是同一generation，pool1还会自等。应使用PG Core原生查询/现有display索引，保留durable first-id、removed identity、handoff、最老/最新方向、旋转/rewind reset、resume上限和有界payload；不能继承含SQLite SQL/PRAGMA的Mixin或退回全量读所有历史。

### [major] 当前PG修订计数与“纯append不重置cursor”新合同相反

位置：`hermes_db/repositories/messages.py:105`–`:109`，`hermes_state_stored_reads.py:215`，`gateway/session_stored_reads.py:430`。

PG append的 `bump_counters` 当前在inserted>0时递增 `transcript_revision`；新cursor三元状态明确要求仅追加当前segment尾部不改变状态，而reaction、display rewrite、Codex字段改写等必须改变。若新接口直接求当前revision之和，每次正常append都会让oldest poll重置；不能把旧 `conversation_revision` 原样当新cursor状态。

需明确两者修订语义并保留既有cache/prepared-policy并发保护。可在统一writer路径对齐SQLite更新修订规则，或使用专门的display-state修订；选择前核对所有消费者。新SQLite `messages_display_revision_update`覆盖display_kind/display_metadata/codex_reasoning_items/codex_message_items，PG也必须覆盖每种实际写路径；不仅实现一个返回tuple的方法。Root的真实PG初始cursor合同已红，需同一合同绿并加入reaction/重写/祖先修改、append不reset的双向见证。

### [major] 拒绝turn的owner持久回退缺PG实现，旧拒绝数据修复也未承接

位置：`hermes_db/session_rewrites.py:11`，`hermes_state_rewind.py:95`，`gateway/session_transcript.py:670`、`gateway/run_turn_persistence.py:635`。

incoming新增 `retain_refused_turn_for_display` 及boundary_row_id目标；PG只复用两个旧rewind算法，没有该方法。owner/CLI wrapper会捕获AttributeError并返回None/False，使已持久化的拒绝输入仍在模型上下文；重开会再次发送它，不能以当前内存已清理或teardown未崩溃当成功。

需原生PG在同一短事务里验证boundary/active-id快照、保留carrier handoff、退活整个准确turn、只把人类输入标为compacted/content_refused及notice，保留/合并现有display metadata；internal输入不误显示、不猜成较新的steer。按incoming `33ef50d31f` 的原子要求实现，不能套用其SQLite SQL。

`hermes_state_legacy_refusal.py` 的旧数据尾段修复只在SQLite打开执行；PG既有数据可能含旧failed_turn/content_policy_blocked形状。需要同范围、幂等且store-scoped的受控PG数据修复/升级入口，跳过非chat、已回答、已折入summary和有lease/compression的行；不能把“新Schema没有旧行”外推到本地已运行的PG数据集。本Reviewer未查询正式数据，不声称其中已存在这类行。

### [major] 委派后代消费者缺少PG原生读端口

位置：`tui_gateway/session_notifications.py:473`、`:490`，`hermes_state_delegate_children.py:22`，`tools/delegate_tool_sessions.py:32`、`:81`。

初始新通知消费者把PG resource交给 `delegate_descendant_ids`，该helper直接调用 `_session_lineage_root_to_tip`、`_read_one`、`_read_ctx`；初始PG没有这组SQLite接口。不能用catch后空列表或关闭回收“补齐”功能。初审曾把 `_kbc.connect(board=slug)` 也列成SQLite I/O；该判断不成立，已撤回：`hermes_cli/kanban_db_connect.py:731` 实际先检查backend并分流PG，不能仅凭函数名或返回类型注解认定后端泄漏。

PG已有retirement的store-scoped delegate图查询，可扩展具名读端口和具名订阅retarget事务，保留分支/reset/别人的child拒绝、递归后代及compression continuation语义。完成子agent transcript另需 `subagent_session_ids` 与backend-neutral fork判断；不要让 `tools/delegate_tool_sessions._continues` 对PG直接调用缺失的SQLite私有方法。

incoming v33对丢失 `_delegate_from` 的source=subagent旧行回填，PG没有对应数据修复；需同步更新PG现有 `delegate_origin`/`has_delegate_marker` 物化投影，保留真正的subagent compression continuation。还要验证 `lineage_root_id` 与root/lease不变量，不能只修JSON就假定PG图必然一致。新reserved-child构造后已在 `run_agent.py:327` 补真实patch_model_config，避免重复提出“首turn构造配置必然被丢”的未经核对问题。

### [major] tool-source rotation root 未加入PG owner/Worker协议

位置：`agent/runtime_session_compression.py:42`，`hermes_db/operations/worker_compression_reads.py:57`，`hermes_state_compression.py:947`。

Worker getter现在硬读 `compression.lineage` 的 `tool_root`，PG结果无此key，ReadView/PG门面也无 `get_tool_rotation_root`。`agent/prompt_cache_scope.py:59` 的owner路径会异常回落物理session id、不memoize，使tool会话压缩旋转后的稳定conversation identity合同丢失。

需移植tool→tool且父compression、无branch/delegate/reset的准确爬链；在现有receipt Connection的已授权ReadView计算并返回tool_root，保留readable_ids校验。不能用通用get_conversation_root跨越本应断开的tool fork，也不能让Worker自选外部profile/目标。

### [major] deliberate archive 的新canonical Bot Chat退休合同只在SQLite生效

位置：`hermes_db/session_metadata.py:107`、`hermes_db/session_titles.py:56`；incoming `hermes_state_titles.py:211`。

incoming明确让用户Archive退休可见/隐藏canonical Bot Chat的名称，并清recoverable end_reason、unhide，让下一次bot打开/投递生成新chat；PG仍只置archived/auto_archived，get_session_by_title无退休过滤，仍命中旧canonical。`292620b6b7` 特别覆盖reaper已结束的visible chat，不能只处理hidden case。

需把同一显式archive事务的lineage状态/title/title_search/title_source更新及lookup规则移植PG；闲置自动archive/bulk/reaper不触发用户退休。覆盖压缩tip、已归档重复操作和unarchive后普通Archived聊天。

### [major] user-row metadata rewrite 仍整包覆盖，违背新merge-patch语义

位置：`hermes_db/session_message_edits.py:38`、`:48`；incoming `hermes_state_messages.py:1056`、`hermes_state_common.py:86`。

SQLite新 `set_user_message_content` 使用JSON merge-patch，保留别的writer已加的reaction，null删键；PG仍将传入display_metadata整包替换。确定的公开调用序列是给user row添加reaction，再 `set_user_message_content(..., display_metadata={'new': 1})`，PG会丢reaction；传 `{'old': None}`也不实现新删键合同。

在原root锁/同Connection读取的最新metadata上应用等价merge-patch并更新物化display_query/revision；不要修改所有reaction setter为同一种patch，保留各公共操作原语义。验证既有reaction/嵌套对象/null删除及peer同ID隔离。

## PG迁移范围判断

- PG已有transcript_revision、display_order/display_identity及display索引，不能机械复制SQLite SCHEMA_VERSION=33或CJK tokenizer退役DDL。PG数据本来不依赖该SQLite索引。
- snapshot/picker/tool_root多为具名Core读与协议移植；cursor revision必须先决定更新/append语义。若新增物理列/索引或持久修复标记，再追加0028之后的新Alembic revision/健康合同；不能改0001–0028或启动时偷偷DDL。
- 已存在PG数据的delegate标记/投影回填与legacy refusal修复是实际数据升级范围；需可重入、明确store域、并发租约/压缩保护和重复升级见证。普通打开不应执行无界全表修复，不能靠只测试新空Schema省略旧PG前向升级。
- PG history binding本来使用稳定store namespace，home移动无需重写为路径身份；保留namespace，移植owner兼容与导入父检查即可。不要把SQLite“忽略home”变成PG“忽略store”。

## 本轮证据与门禁

本轮新增发现来自三方差异、实际合并源码与确定调用链；只有前述Root保存的三个初始PG红已读取，不冒称Reviewer运行了复现。其余需Root建立对应最小原行为红/整改绿，再核对最终实现。至少需：双后端history binding/import及跨store拒绝、stored list/picker、真实PG同快照分页/游标并发、拒绝turn持久重开、delegate图/订阅回收、Worker tool_root、Bot Chat显式archive及metadata patch；PG用测试fixture归属的随机Schema，SQLite继续独立运行。原incoming相关SQLite合同也须执行，不能用PG适配撤销develop功能。

当前尚无该合并候选完整静态、契约、业务/升级及回归终态；冲突标记和生成契约消失不足以关闭上述语义问题。Root并行snapshot/room修复必须按最终源码及当前候选测试再复审，原统一PG的689、688或正式试运行就绪都不是本次新候选证明。**结论：CHANGES_REQUIRED / 未验收；不得据本轮批准合并或重启正式Profile。** 原非WSL七项验收缺口继续另列。

## 新端口增量复审（2026-11-09，未提交工作区）

本节独立复读实际实现、incoming行为与现有日志；未执行测试、导入运行产品、连接数据库或改生产/测试。源码仍由Root并行变化，以下是逐次检查点，不是冻结候选批准。前文 `_kbc.connect` 判断已明确撤回；它已有PG分流。

### 本轮发现后整改的额外major

1. **整条谱系读重新加载已移除的完整body。** 初版 `session_transcript_pages.py:_fetch_conversation_rows` 直接 `repo.select_rows` 全取谱系消息。`gateway/session_stored_reads.py:196` 只以visible resume count选择whole-lineage，因此少量可见行加大量被rewind/rewrite移除的大body仍会全部加载；500行和PAGE_BYTES的响应截断发生在之后。incoming `hermes_state_stored_reads.py:164` 对removed行只取dedupe identities，只有legacy缺identity才读取content。Root现已加 `repositories/messages.py:41 display_set`：同一Connection读visible完整行、removed最小投影，已有identity的content为NULL；whole-lineage和公开display读已接此投影。已读取 `pg-merge-read-cost-pool.log`，storage新增实测确认removed大body不被带回、显示仍为保留的两行。该省读缺口已有局部源码及真实PG证据，不再列作未改问题；它不替代长谱系分页/compaction handoff的业务证据。

2. **无boundary拒绝保留在单连接池自等。** 初版 `session_rewrites.py:16` 持有外层 `_read` 时调用incoming公开planner；`hermes_state_rewind.py:247` 的planner又通过public methods多次checkout，pool_size=1会等待自己。Root现已先退出外层read，再执行fallback planner，仍在rewind写事务里检查expected_active_ids及root/lease；当前没有把这个复核删除。上述14项日志中的新增case使用真实pool_size=1/max_overflow=0/connection_budget=1，确认无boundary保留后MODEL为空、DISPLAY仍有原输入。该路径局部闭合；有效boundary、late steer和持久重开另由原10项中的拒绝case覆盖。

3. **Worker metadata写仍覆盖全包。** `operations/worker_lifecycle.py:154` 最初仍直接encode payload metadata，只有owner的 `SessionMessageEdits` 被改成merge-patch；incoming `hermes_state_worker_lifecycle.py:184` 已明确同改Worker端。Root现已在receipt原Connection读取的当前row metadata上使用同一merge helper，再走 `messages.update_row`，所以reaction/嵌套/null删键和display_query/revision维护没有另开连接。此处源码已修；前述owner metadata绿不能证明Worker消费端已绿，需实际Worker闭合操作的对应证据。

4. **只修公开archive，遗漏authority/桌面及bulk语义。** `operations/mutations.py:119` 原仍只有lineage_flag，绕过incoming `hermes_state_mutations.py:114` 为Desktop Archive新增的canonical退休；现已在同一mutate/receipt事务对实际affected ids调用 `titles.retire_bot_chat`。另 `repositories/retention.py:74` 原只排compression祖先，PG的bulk和visible-tip idle sweep仍会匹配canonical；incoming `hermes_state_maintenance.py:239` 明确按title排除它。现已在共用lineage_tips_only selector排除Bot Chat，保留非canonical归档。源码接缝与incoming相符；已有visible/reaped公开set_session_archived绿只证明公开setter，不能当作新authority/housekeeping两条端口的运行结果。

5. **Telegram topic新增CAS接口未移植。** `gateway/run_topics.py:154` 每次绑定都传 `expected_session_id`，默认None也传；初版PG `session_topics.py:73` 无此参数，普通刷新和rowless修复都会TypeError，refresh路径仅debug后吞掉，绑定不能持久更新。incoming `7366bc7a19` 的实际意图是防止rowless repair等待期间的 `/new` 被旧绑定覆盖。Root现已在原store-exclusive事务按当前store/profile/chat/thread核对expected：不存在或不符返回False，成功upsert返回True；session唯一topic约束保留。此处不是可忽略的附加参数。源码已修，仍需默认绑定、匹配CAS、失配/删除及其他store同id的实际端口证据。

### 原发现的当前实现与证据边界

| 范围 | 本次独立源码核对 | 已读运行证据与边界 |
| --- | --- | --- |
| owner binding/import | 本地scoped `bindings_agree` 两边都验证当前store namespace，再调用owners_agree；两个None/单None区分；SQLite调用改两参；canonical导入仍要求父已绑定，再比较scoped owner | storage原10项含当前host/login兼容、foreign store及空binding反例；未据此声称完整history/import/API路由均已复验 |
| 快照/分页/picker | `SessionReadSnapshots` 为每个store按线程pin一个RR Connection，嵌套复用、finally清pin，`PostgresSessionStore._read`消费该pin；picker每个查询带store，workspace过滤位于SQL LIMIT之前 | 原10项含同snapshot读旧generation、nested pin、peer同id隔离、重开、基本单segment oldest poll/reset、workspace limit=1；未覆盖完整多segment/handoff和所有cursor方向 |
| revision写路径 | 新0029把cursor专用transcript_edit_revision与既有conversation revision分开，插入只bump旧counter；row update仍bump两者。独立追踪update_row、批量deactivate、clear、queued retirement、replace/rewind、compaction、publish、branch/import等写路径，均有相应edit bump或新目标初始化；insert内部display-order维护不当成rewrite | 原10项证明纯append不reset、user内容rewrite会reset；不能据此外推每种codex/reaction/metadata rewrite及删除、compaction的游标回归已测试 |
| delegate与物化root | 新具名PG descendant/subagent查询及fork判定代替SQLite私有I/O；creation防止未标记subagent误并入普通parent compression root；0031补旧marker与delegate_origin/has_delegate_marker，并把该child及真正compression continuations拆回child root | upgrade文件2项证明旧materialized parent root被纠正、continuation仍无伪造delegate marker、重复upgrade不再次改rewind_count、活lease拒绝且revision/数据回滚；不是正式Profile数据检查 |
| refusal旧数据升级 | 0031仅显式upgrade调用，先取表写fence，按store分页，修前检查turn/compression lease及非terminal Worker；复用incoming拒绝尾段判定，跳过非chat、已回答/已折入summary等形状 | 同2项含持久旧failed_turn修复、reaction保留、cron不动和活lease全事务拒绝；更多legacy排除形状尚未见本候选PG测试 |
| Worker tool_root | ReadView使用原receipt Connection并在既有authorize后返回tool_root；准确沿tool→tool compression且无fork/reset/delegate爬链，不自选profile或另开store | 原10项直接在真实PG Connection调用lineage证明返回字段和基本tool rotation；它没有经过完整认证Worker RPC，不冒称该层端到端通过 |
| canonical/metadata | 公开setter和lookup、owner merge-patch已移植；本轮另找出并修Worker/authority/bulk遗漏，见上文 | 原10项仅覆盖visible/reaped直接archive及owner反应保留/嵌套/null patch；新消费入口另待结算 |

### 已读日志、无法验证项与门禁

- `pg-merge-foundation-red.log`：当时选中4项，2pass/2fail；真实红为直接archive保留了Bot Chat title、refusal方法缺失。不是本Reviewer运行。
- `pg-merge-foundation.log`：1文件10pass、0fail、37.3秒。包含基本stored reads、owner binding/metadata、公开archive/refusal和Worker tool_root的真实PG结果。
- `pg-merge-current.log`：当时3文件18pass、0fail、50.0秒，构成为storage10、collaboration6、data-upgrade2；其collaboration深层由对应Reviewer负责。
- `pg-merge-read-cost-pool.log`：其后2文件14pass、0fail、89.0秒，storage12加Discord2，实际补了上述removed-body与pool1两个case。不能把14与18相加当去重总数，也不能把前一批运行声称绑定到后一批新增源码。

0031新增升级入口已存在且已有2项真实PG旧行/活lease局部见证，因此不再把“只测fresh schema、没有旧数据升级”列成当前事实；仍需最终候选按正式schema健康合同/前向升级核对。当前未见最后四条新消费者整改后的终态日志、完整incoming stored-read行为矩阵（旋转whole-lineage、handoff只显一次、旧/新方向游标与rewrite/rewind/删除reset、长谱系tip-only边界）、完整认证Worker与API owner身份路由回归，以及本候选完整静态/生成契约/分域回归结算。列这些是新代码的具体验收边界，不是无证据断言它们已经失效。

当前初始接口缺失已有实质补齐，本轮没有通过未执行的假设增加额外安全指控；尚未结算的新消费者与合并整体仍不能批准。**当前结论仍为CHANGES_REQUIRED / 未验收**。不操作正式Profile/数据库，不以旧689、正式PG试运行或Git等价代替此次候选业务测试；原非WSL七项仍缺适用主机的真实运行，不能因本轮合并局部绿而解除。

## 发行包旧Schema seed 的有界复审

**[major，验收夹具；当前已静态整改、运行未验收]** `tests/hermes_db/postgresql/test_distribution_initialization.py:_PROBE` 原先先执行 `command.upgrade(..., '0004_model_markers')`，随后在 `phase='previous-pg-revision'` 用当前 `PostgresSessionStore.create_session` 准备旧行。这条调用在 `operations/sessions.py:24` 即进入 `repositories/sessions.py:18 raw_session`，无条件 `select(sessions)`；当前 `tables/conversations.py:28` 包含新transcript_edit_revision，而冻结0001/0004没有此列，它只由0029添加。因而在可用PG上这段也会先遇到undefined-column（SQLSTATE 42703，再经写事务包装），不能执行到真正forward-upgrade。不能把它归为本次server recovery的后果，也不能靠换成HEAD revision先创建Schema绕过原前向升级合同。

最小修正是冻结0004的合法seed格式，显式参数化旧列，并保留root/session/message外键先后、合法BYTEA内容envelope与提示词原字节；另一可行方案是真正固定并运行历史API。没有必要让生产Store猜测或回退旧Schema。当前Root已只把这段seed改为显式旧格式SQL：先创建root，再创建session，最后插入message。独立核对冻结DDL，所需无default的NOT NULL列均已提供，其余必需列有default，旧display_identity允许NULL；提示词是原UTF-8 BYTEA，消息是`T`加UTF-8 envelope，二者均保留NUL。当前业务API仍在实际0004→当前upgrade之后读取旧记录，独立已安装payload、第二进程重启、epoch/admission、store隔离及禁止SQLite的断言保留。该夹具修正静态合理，不是生产升级功能修复或运行通过。

已读取探索日志 `pg-suite-exploratory.log` 的真实终态：128文件637pass、5fail、29errors、34skip，退出失败；其中发行初始化文件显示两项skip，不能拿该批声称本发行probe已运行。当前依赖仍recovery/unavailable，本Reviewer依授权未运行测试、未连库，也未将离线/Native通过外推为发行包PG前向升级成功。后续需要在归属明确的测试Schema、可用PG及独立PM安装payload上运行原发行初始化/重开合同；保留0004旧行升级，不降低断言或去掉该合同。**总体仍CHANGES_REQUIRED，原非WSL七项缺证不变。**

## 冻结运行tree 95242301 的限定合并复审

本节目标为运行代码tree `95242301fef57260b46accb5adf65387d816699a` 的develop→feature本地合并兼容整改，和原统一后端Task24完成度分开。已用Git比较当前foundation相关生产路径与该tree，结果无差异；其后测试/文档变化不冒称新的生产实现。仍只读源码/日志，仅改本报告，未代跑测试、连库、操作正式Profile或stage/commit。

### [major] 旧格式NULL display identity无法补齐，单segment存储转录可丢显示行

位置：`hermes_db/session_transcript_pages.py:29`、`:38`，`hermes_db/repositories/messages.py:95`，`gateway/session_stored_reads.py:449`、`:461`、`:473`。

`_ensure_display_order` 检测到display_order或display_identity缺失后只调用 `reconcile_orders`。该repository函数只读固定列，直接令 `identity=row['display_identity']`，从未为NULL identity计算内容身份；多条不同消息会共同使用 `first[None]`，归入相同display_order，identity也始终NULL。下一快照仍判missing，重试后 `_unproven` 的page最终进入按display_order分组的 `display_ids`，每个slot仅rank=1一行：两条不同NULL-identity消息会只显示其中一条，oldest cursor一直reset。incoming `hermes_state_messages.py:1246` 明确要求真实补齐legacy identity/order；本PG读端口没有完成这个接缝。

这不是声称正式业务库已含这种行。本轮发行probe刚明确接受的冻结0004 seed没有提供identity/order，冻结DDL允许NULL，0029/0031未补齐它们；当前发行绿只通过conversation API读取旧内容，没有执行stored transcript。因此“合法旧PG数据经升级后可读取”的已有合同尚留该显示边界，现16项storage绿也没有覆盖它。上述为确定源码路径分析，本Reviewer没有运行重现，不能写成真实红。

建议用归属明确的旧格式测试数据保存至少两条不同content、NULL identity/order，执行前向升级后调用真实 `read_transcript` 的oldest/latest，并检查显示两条、索引完整、后续cursor稳定。最小实现可在原root锁下仅为缺identity的历史行读取必要body并生成纯codec identity，然后按现有UID/carrier规则reconcile orders；正常已索引路径继续只读固定宽度字段。不能仅让函数返回True、删掉完整性检查、给发行fixture补字段来掩盖公开补齐缺口，或退回SQLite。该项已通知Root，冻结tree尚未闭合。

### 新终态证据及当前接受性

- `pg-merge-final-contracts.log` 已真实终态：6文件34pass、0fail，162.0秒，包含storage16、collaboration10、consumer2、data-upgrade2、独立进程恢复2、COMMIT丢ACK恢复2。它覆盖新增Worker metadata receipt端口、authority归档/重放、bulk保留canonical、Telegram同ID跨store/CAS及一次真实rotation/handoff reset；上述初审消费遗漏不再作为未验收实现指控。
- `pg-http-supervisor-final.log` 2pass；`pg-merge-process-recovery-corrected.log` 2pass验证write/read不同PID、实际wrapper持久关闭键/owed债务及peer scope隔离，拒绝SQLite；`pg-merge-commit-ack-recovery.log` 2pass在真实dialect commit完成后才注入ACK异常，调用者收到UnknownCommitError，重开/重放仍保留关闭键或准确一次旧grant债务。没有把普通异常前回滚测试冒称COMMIT后故障。
- 原依赖恢复后的 `pg-interrupted-files-restored.log` 4文件75pass、0fail，371.9秒。原探索637pass/5fail/29errors/34skip失败记录保留；此局部复验不能倒写成原全批成功。
- `contracts-current.log` 90文件503pass、0fail、4skip；`run-wrapper-scoped-contract.log` 5pass；`native-peer-http-regressions.log` 6文件75pass；`pg-linux-sdk-restored.log` 11文件32pass。orchestrator日志与后者是同一批，不把它们重复相加。Native历史legacy-refusal busy用例以 `pid=1` 充当活owner在Windows不成立，当前测试改为真实 `os.getpid()` holder并用同holder释放，全部busy/pending/之后重开断言仍在；`native-latest-followups.log` 对该文件5项通过，加boundary lint7项，共12pass。该修正未伪装OS，也没有禁用活lease保护。
- 独立安装v2已实际运行：Windows `distribution-source-windows-v2.log` 2文件4pass、2个Linux平台skip；Linux `linux-bundle-native-v2.log` 4pass；`linux-bundle-pg-v2.log` 2pass，19.7秒，含旧0004→当前升级与独立全领域/SDK重开。前节发行seed缺列问题已有当前独立安装运行证据，局部关闭；仍不证明上面的stored transcript NULL身份补齐。
- `checks-staged-final-candidate.log` 当前实际为15checks中ruff失败，health1045文件0blocking/0advisory。唯一ruff项为新增process recovery测试 `subprocess.run` 缺显式check参数（PLW1510）。需修后结算新的统一检查，不能仅因health绿写全部静态通过。

**此冻结tree的foundation限定合并结论仍为CHANGES_REQUIRED**：需先处置上面新发现的NULL identity显示major并取得对应证据，另结算静态检查。其他已读通过合同在其实际范围有效，不因一个新边界被全盘否定；也不能把所有历史依赖中断认定为产品缺陷。原Task24的非WSL七项适用主机证据仍独立缺失；即便限定合并整改最终接受，也不能据此宣布Task24或全系统完成。

## NULL identity整改复审与运行tree bb811be4 检查点

已实际读取 `pg-legacy-display-red.log`：真实PG oldest/latest **0pass/2fail，canonical Summary 12.2秒**，两方向均只返回old reply、漏old prompt；这是前节源码分析之后新增的实际反证，不能把先前静态判断倒写成已运行。Root随后仅在 `repositories/messages.py:95` 的reconcile入口增加 `_backfill_missing_identities`。独立复审确认它在传入的原Connection/root锁事务内，以当前store/session、visible、NULL identity及id keyset、每批1000行读取必要body，用当前纯codec生成identity，同时清除该行不可信旧slot，再复用原固定列UID/carrier整理。完整identity行不会成为body查询结果，没有另开事务或SQLite回落；当前未发现该窄修新增blocking/major。

`pg-merge-final-contracts-v3.log` 已真实终态：**6文件36pass、0fail，246.0秒**，data-upgrade文件4项包含原两方向红测，所有原内容/完整index/oldest后续不reset且空页/再次读取断言保留。前节NULL身份major据此局部关闭；36是本次整批计数，不与旧34重复相加。Root补的发行v3 probe又把0004旧格式seed强化为真实user+assistant两消息，并在升级后经实际stored transcript检查两行与稳定cursor，独立进程重开/零SQLite/作用域断言仍在；本次只审其源代码，尚不把在跑的发行v3登记通过。

当前运行代码已冻结为tree `bb811be4a8132bcdb52190ab730ae1ab329b8512`；独立Git比较本工作区hermes_db/gateway/hermes_cli/plugins/tui_gateway/agent/cron/pm生产路径无差异。`repositories/messages.py` 本地文件SHA256为 `ceb6292bbb2a2e23cc731a637966707811d6e0c212cf7ba91494519e168de5da`。PLW1510对应测试现已显式check=False，没有改子进程成功断言；统一 `checks-staged-v3.log`、发行v3和包含完整SDK环境的PG全目录v3仍待终态。**本域当前未发现未处理源码blocking/major，限定合并接受性仍待这些当前候选门禁结算；尚未给APPROVED。** 原探索红和静态首轮失败不删除，Task24非WSL七项缺证继续独立保留。

## 发行v3 stdout完成通道诊断

`distribution-source-windows-v3-complete.log` 真实终态为2文件3pass、1fail、2skip，81.4秒；失败是父测试在子进程returncode为0后解析空stdout产生IndexError，不能登记发行PG通过。临时最外层改捕获BaseException的 `distribution-probe-exit-diagnostic.log` 仍在同处失败。只读追踪已定位真实渲染链：`session_stored_reads.py:383` → `session_controls.display_projection:112` → `tui_gateway.server` 模块级220–221保存real stdout并把sys.stdout改为stderr。该load-bearing行为在incoming历史 `29f2610e4b` 已存在，注释明确为了保护stdio JSON-RPC不被tool print破坏；`session_controls.py:128` 也已记录此副作用。最终probe JSON因此可能写入stderr；并非已有证据显示SystemExit、未执行升级或PG回落。

当前Root仅在probe任何import前保存 `receipt_stream=sys.stdout`，成功和经脱敏的失败JSON都显式写该stream，最外层恢复Exception。独立复读确认没有取任意stderr尾行冒充回执、伪造成功或删除真实stored transcript/稳定cursor断言；父测试仍要求子进程成功且读取实际JSON。此测试完成通道修正静态合理，不应为它修改产品stdio协议。再次比较bb811be4的相关生产路径仍无diff。修正后发行运行尚待终态，不把returncode单独当作成功。

另已读取 `checks-staged-v3.log` 新终态：**15checks ok，1045文件health 0blocking/0advisory，338.6秒**，上一轮PLW1510门禁局部关闭；该检查早于后续完成通道测试/报告更新，最终staged结算仍由Root保留。PG全目录v3未终态，限定合并未批准，整体Task24七项缺证保持。

## 最终限定合并结算（2026-11-09）

目标仍是用户已发起的develop→feature本地合并兼容整改，运行代码tree为 `bb811be4a8132bcdb52190ab730ae1ab329b8512`。最终独立比较全仓tracked差异，除tests/docs之外无差异；相关runtime目录没有未跟踪生产文件，messages源码SHA仍为前节记录值。未以旧689、正式Profile试运行或Git等价代替本次运行证据。本Reviewer仍只读生产/测试/已有日志，未代跑、连库、stage/commit、推送或部署。

### 当前实际证据

| 门禁 | 已独立读取的终态 | 证明范围 |
| --- | --- | --- |
| 当前PG全目录 | `pg-suite-v3.log`：131文件686pass、0fail、34skip，2024.6秒，j3 | 当前合并候选的PG业务、迁移及故障合同；这是新批次，不是把旧探索637改成绿 |
| 精确合并合同 | `pg-merge-final-contracts-v3.log`：6文件36pass、0fail，246.0秒 | 本轮新增接口/consumer、旧数据升级、NULL身份双方向、不同进程恢复与真实COMMIT后丢ACK重放 |
| 最后receipt测试静态检查 | `checks-staged-v3-receipt.log`：15checks ok，health1045文件0blocking/0advisory，327.6秒 | 包含回执通道修正后的当前候选静态门禁；最终报告文档入stage后的检查由Root继续执行 |
| Windows独立发行 | `distribution-source-windows-v3-receipt.log`：2文件4pass、0fail、2个Linux平台skip，45.7秒 | 独立安装payload、旧0004两消息前向升级、实际stored transcript完整页/稳定cursor及新进程重开；Windows平台skip未记作当地执行 |
| Linux独立发行 | `linux-bundle-pg-v3-receipt.log`：2pass、0fail，43.4秒；`linux-bundle-native-v3.log`：4pass、0fail，87.4秒 | Linux PG旧数据/全领域SDK重开及Native实际发行合同，保留各自后端和独立进程身份 |
| Linux专属PG/SDK | 前节已读 `pg-linux-sdk-restored.log`：11文件32pass、0fail | Windows全目录中的Matrix/单后端Linux项由独立Linux环境执行；与orchestrator副本不重复计数 |
| Native与公开peer消费回归 | 前节已读contracts503pass/4skip、wrapper5pass、peer HTTP75pass及相关follow-up | 对应incoming原行为及本轮PG路由接入；未宣称新的完整八目录全批 |

PG全目录34skip为32个Linux专属Matrix/单后端项及发行初始化2项；对应独立Linux32项和显式发行载荷2项已有上述运行，不能把Windows的skip说成Windows本地通过。四套v3 PM source bundle的构建日志均有实际成功终态，且发行测试执行的是各自安装路径中的模块。stdout通道修正后Windows与Linux当前发行已取得真实JSON成功回执，前节发行门禁局部关闭。

证据历史继续保留：Windows-v3-complete的3pass/1fail/2skip、原NULL身份0/2、探索637pass/5fail/29errors/34skip、静态首轮ruff失败均不删除。Root明确报告Linux发行初轮1pass/1fail约51秒的原始同名log被后续wrapper覆写，保留工具终态回执；本Reviewer没有可重新读取的该初轮原始日志，不把当前43.4秒绿冒充它，也不声称独立复核了它全部失败现场。这是历史证据完整性的局部限制，当前独立Linux发行合同本身已有新的可读终态。

### 外部Chrome只读SQLite边界

已限定核对新增 `tools/browser_real_profile_logins.py:66`：路径为真实浏览器快照的 `Default/Login Data` 与 `Login Data For Account`，通过绝对file URI和 `mode=ro` 打开，仅SELECT origin_url/username_value、过滤blocklist，finally关闭连接；该读取没有SELECT password_value或写Chrome数据库。`agent/vault_backends/base.py:131` 的backend开启条件复用真实profile consent，`BrowserProfileLoginBackend.list_items` 消费其快照；浏览器生命周期也核对use_real_profile并在撤回时清理快照。

这里的文件可以位于Hermes管理的浏览器副本目录，但其数据格式/协议仍属于外部Chrome应用，**不是Hermes业务持久store**。将它列为外部格式只读适配边界合理；不能据统一PG任务改Chrome格式、静默禁掉已有功能，或为它放宽Hermes自有数据库的PG零SQLite guard。本节只结算数据库所有权边界，不扩展为整个incoming浏览器密码/自动填充功能的独立安全批准。hosted_rooms、kanban通知的新持久操作已通过各自PG路由，未因该外部适配增加新PG store或SQLite fallback。

### 本域结论

初审owner namespace、stored snapshot/picker/keyset/revision、delegate与物化root、拒绝输入/旧数据升级、Worker tool_root/metadata、canonical退休/housekeeping、Telegram CAS，以及末轮NULL身份与发行完成通道问题，均已对照当前实现和对应实际证据处置。**当前本域未发现未处理blocking或major。** 既有稳定store namespace、原receipt Connection、root/lease保护、零业务SQLite回落及平台实测边界未因适配而削弱。

**APPROVED：仅本次用户已发起的develop→feature本地合并foundation整改，适用于上述冻结运行代码与当前已结算合同，可支持Root完成该本地合并的文档/staged收尾。** 这不授权推送、部署、重启或修改正式Profile/服务。

**整体统一后端Task24仍为BLOCKED / CHANGES_REQUIRED**：非WSL POSIX适用主机的七项私有启动页证据仍缺失。准备好的bb811执行包/hash不是该主机运行结果；本次本地合并接受不能把Task24标成完成或全系统APPROVED。至此本Reviewer停止编辑本报告，交由Root保存最终文档与本地合并。

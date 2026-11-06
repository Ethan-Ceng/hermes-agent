# PostgreSQL 核心存储阶段性独立审查

## 审查范围

- 日期：2026-11-07；独立 Reviewer，只读生产代码。
- 分支：`feat/postgresql-session-storage`；审查快照：`f874e6be49`；与 `main` 的 merge-base：`ff09cead02e906a4b1da909268c2cc58ec6e144d`。
- 依据：根 `AGENTS.md`、`supercoder:code-review`、`docs/designs/postgresql-session-storage.md`、`docs/designs/postgresql-storage-code-layout.md`、实施计划及业务契约。
- 重点阅读：`hermes_db` 的 scoped 表/外键、epoch/映射/谱系锁、事务故障分型、准入与结算、Worker sequence/receipt、压缩发布、退休账本/墓碑，以及同 Schema 跨 store 移动。检查对应主题契约测试和部分原 SQLite 行为。
- 这是高风险阶段性审查，没有逐行审完本分支所有应用入口、搜索实现和全部 diff。以下行号对应上述审查快照；主 Agent 正在整改，不能将本报告当作整改后重新批准。

## 问题列表

### [major] 移动接收方仅凭消息数量被判定仍保留源快照

位置：`hermes_db/operations/profile_move.py:58`（尤其第 62–63 行）；调用：第 80 行及第 161–164 行。

问题：`_present` 核对的是首次导入留下的 source digest 和当前消息总数，未核对接收方仍持有当时导入的正文、提示及用量。首次导入后的接收方可以整体替换消息，只要条数不少于原快照，旧回执仍被当作接收确认。源删除虽重新核对了源快照，但随后凭这个过时确认执行物理删除。

复现建议：在两个不同 store 的 `core_pair` 上，source 创建 `s` 并追加一条 `original`；export 后由 target import；target 对 `s` 调用 `replace_messages`，换成一条 `replacement`；随后 source 调用 `delete_moved_session("s")`。当前判断仍满足 `actual >= count`，允许删除 source，原正文不再存在于任一 store。重试 `import_moved_session` 也会错误返回 `present`。这是代码路径推导，本 Reviewer 未新增或运行该回归；主 Agent 已接手建立红灯与修复。

影响：移动期间接收方发生重写后，源可能被不可恢复地清除。单纯消息数量不能作为安全删除的内容保全证明。

建议：保存并核对实际导入记录的内容证明，允许正常追加但拒绝已导入记录被替换/移除；源删除和导入重放共享该证明，并补同条数替换与正常追加两个行为契约。

### [major] 准备式压缩未对直接 transcript 写入建立有效 CAS

位置：`hermes_db/operations/mutation_policy.py:26`；`hermes_db/operations/mutation_transcript.py:19` 和第 23–25 行；相关：`hermes_db/repositories/messages.py:95`。

问题：准备快照只记录物理目标的 `runtime_revision`。公开 `append_message`、批量追加及行编辑更新 `transcript_revision`，不会更新 `runtime_revision`。准备完成到最终提交之间发生这类写入时，`validate_prepared` 仍可通过；原位 compact 没有传 watermark/coverage，轮换 publish 也没有传 watermark。因此压缩提交使用旧摘要替换当前 active 历史，没有将晚到消息并入结果。

复现建议：沿用 `tests/hermes_db/contracts/test_mutation_transcript.py` 的 `local_setup`、`_args`；`mutate_session(..., _prepare_only=True)` 后，直接向物理目标追加 `late`，再用旧 snapshot 和仅包含旧历史摘要的 prepared 提交压缩。分别检查 `in_place=True/False`：当前快照比较不会发现该追加，最终目标的 active 历史丢失 `late`。同样应覆盖准备期间原行编辑。该路径为静态推导，尚未取得此新增回归的执行证据。

影响：在普通 SessionStore writer 与准备式压缩并发时，最新消息不再进入续接上下文。原位模式旧行仍归档存在，不能据此声称 active 历史完整。managed Worker receipt 会另外更新 `runtime_revision`，所以其写入受现有 CAS 保护；本问题明确针对公开直接 transcript writer。

建议：最终提交核对目标 `transcript_revision` 并拒绝过期准备结果，或在同一快照中保存有效 watermark/覆盖证明后合并晚到尾部；不要通过全局改变 runtime revision 的含义来掩盖缺口。若业务层确实禁止所有这类并发 writer，需用真实入口证据证明，而非仅靠 managed Worker 情形推断。

### [minor] 不存在的 donor 会话触发 TypeError，无法返回已有的失败结果

位置：`hermes_db/operations/adoption.py:37` 和第 54 行；相关：`hermes_db/repositories/messages.py:116`。

问题：`target.adopt_session_lineage_from(source, "missing")` 调用 `resume_lineage`。后者即便未找到会话也返回 `[session_id]`，导致 `adoption` 的空列表检查永远不处理这个情况，之后 `_export(..., session=None)` 在访问 `session["id"]` 时抛出 TypeError。已有 SQLite 契约 `tests/tui_gateway/test_stranded_session_adoption.py:93` 期待明确的 `adopted=False` 结果。

影响：会话不存在或在发起采用前已删除时，调用者收到非业务异常。事务会回滚，未发现由此直接丢失数据。

建议：在采用事务获取映射锁后先检查 donor 目标存在，返回现有 not-found 结果；添加 Native 缺失 ID 契约。无需为此擅自改变 `resume_lineage` 所有调用者的语义。

## 已检查的结构与无法验证项

- 已阅读的作用域查询/外键以 `store_id` 限定；Worker handler 与回执使用同一个 Connection；`Transactions.write` 将提交阶段断连分类为 `UnknownCommitError`，没有盲目重放外部效果。
- epoch → 映射 → 根锁的主路径已阅读；涉及多个独立谱系的短操作多使用独占映射栅栏。未发现另一个可定位、足够确定的重大锁序缺陷。这不是对所有并发交错的证明。
- 未连接、安装或启动 PostgreSQL；没有读取用户凭据。256 项真实 PG 定义没有执行证据，DDL、真实行锁、sequence 提交顺序、死锁和进程故障恢复仍未验证。离线 Core/SQLite harness 不能证明这些 PG 语义。
- 本 Reviewer 启动了标准 runner 的 Worker atomicity、Worker receipts、retirement housekeeping 三个文件，但未取得完整最终输出，不计为测试通过证据。新增问题的回归与修复复验交由主 Agent 执行。
- 未完成全部应用入口、搜索索引/查询计划、发行构建和完整分支回归审查；现有大回归含平台/环境及未归类失败，不能据局部通过批准。
- 未发现需按 `SECURITY.md` §3.1 进行私下报告的已确认边界突破；上述问题按数据正确性处理。

## 合并门禁

| 门禁 | 结果 | 依据 |
| --- | --- | --- |
| 无 blocking | 本范围未发现 | 不等于完整安全审计 |
| 无未处理 major | 失败 | 上述移动与准备式压缩缺口；整改后须重新审查 |
| 验收满足 | 无法验证 | 缺真实 PG 事务/并发/故障证据 |
| 相关测试与完整回归通过 | 未满足 | 本轮无完整最终验证通过证据；大回归仍有失败 |
| 构建通过 | 无法验证 | 不在本 Reviewer 动态验证范围 |
| 新库迁移通过 | 无法验证 | 真实 PG 未运行；SQLite 旧数据迁移不适用 |

## 结论

`CHANGES_REQUIRED`。先复现并修复可定位问题，运行受影响契约，再进行真实 PG 和所需最终验证。此报告仅描述 `f874e6be49` 的阶段性审查，不替代主 Agent 的验证记录，也不批准后续工作区修改。

## 整改后独立复查（2026-11-07）

复查对象为 `f874e6be49` 上当前未提交的四个生产文件修改：`move_values.py`、`operations/profile_move.py`、`operations/adoption.py`、`operations/mutation_policy.py`，以及新增 `tests/hermes_db/contracts/test_review_data_safety.py`。完整读取了这些 diff 与新测试，并核对主 Agent 的 `task18-review-fix-tests.log`；本节更新上述问题的处置状态，不重写原始发现。

| 原问题 | 处置 | 独立核对 |
| --- | --- | --- |
| 移动接收方数量证明不足 | 已修复 | 首次导入同事务保存接收方实际快照摘要；`_present` 与 adoption 的 `_existing_matches` 使用共同的 `recipient_snapshot_digest`。比较导入前缀的全部消息字段及提示/工具 pin/用量等快照，忽略正常追加产生的部分会话汇总字段。接收方重写或提示改变拒绝退休源，原消息完整时允许追加。 |
| 准备式压缩遗漏 transcript CAS | 已修复 | `local_snapshot` 在现有映射/根栅栏内记录压缩连通成员的 `id → transcript_revision`；最终 `validate_prepared` 的现有快照比较覆盖这些 revision，因此直接追加/行修改导致的漂移会拒绝发布。未改变 managed Worker sequence 语义。 |
| 不存在的 donor 触发 TypeError | 已修复 | `adopt` 在已持有映射栅栏时显式检查 donor 存在，再求谱系；缺失时返回已有的失败业务结果。 |

新增七项测试验证同数量替换、提示改变、采用后重写、缺失 donor、接收方正常追加，以及原位/轮换压缩的晚到公开追加。它们调用真实公开能力并断言数据及拒绝结果，不读取源代码。主 Agent 报告整改前六项有效失败、一项追加通过；本 Reviewer 核对了最终绿灯日志，但没有独立重跑旧实现的红灯阶段。

本 Reviewer 独立使用标准 runner 再运行了上述新文件和原 profile moves、profile repair、mutation transcript、prepared mutations，共五个文件：**41 passed / 0 failed，exit 0，11.7s，3 workers**。解释器为 PM 的 `.build/postgresql/full-test-env/Scripts/python.exe`；完整输出：`.build/postgresql/task18-core-review-recheck.log`。该次完整输出已观察到；它替代本 Reviewer 前一轮未取得最终输出的尝试，作为本次局部验证依据。

复查未发现这些整改中的新增确定缺陷；三项原问题在上述离线范围内关闭。接收方其他元数据或用量发生改变时，当前证明会保守保留 donor，符合此次修复的数据保全取向。需要区分这些 Core/SQLite harness 结果与真实 PG 锁、事务及并发证明。

还核对了新增 `tests/hermes_db/postgresql/test_review_regressions.py`：它通过真实 `pg_pair` 复用上述七项契约，并标记 integration/allow_network；仅确认接线，未运行或读取数据库配置。

更新门禁：本次三项问题不再是未处理项，局部五文件验证通过；真实 PostgreSQL 原 256 项及新增七项定义、真实新库迁移/并发/故障、完整分支回归及发行验证仍没有全部通过证据。**整体结论继续为 `CHANGES_REQUIRED`，不批准完整分支。**

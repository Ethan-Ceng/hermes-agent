# PostgreSQL INSERT 计数阶段性独立审查

## 审查范围

- 日期：2026-11-07；基准：`d1ea6e5f40`；分支：`feat/postgresql-session-storage`。
- 独立 Reviewer，生产只读；未读取凭据，未连接数据库，未执行 Git 写操作。
- 完整阅读 `hermes_db/postgresql/transactions.py`、`changes.py` 的本轮 diff、新增 `tests/hermes_db/postgresql/test_insert_counts.py`、调试记录，以及路由修复和 Worker 观察器调用路径。
- 枚举 `hermes_db` 中全部 `.rowcount` 消费者；阅读当前安装 SQLAlchemy 2.1.6 的 `CursorResult.rowcount` API 文档和结果封装实现；核对已有 Worker/事务失败测试及主 Agent 的真实 PG 红绿日志。

## 问题列表

本轮未发现 blocking、major 或 minor 缺陷，也未发现需要另补的同类 INSERT 计数遗漏。

## 修复评估

- `Transactions.write` 第 53 行在返回本次短连接前增加 `preserve_rowcount=True`。选项属于 Connection，不改变共享 Engine 配置；读事务没有新增该选项，提交阶段标记和错误分型保持原样。
- 当前 SQLAlchemy 实现于创建结果对象前保存 DBAPI `cursor.rowcount`，没有额外 SQL、结果 fetch、重放或提交。API 文档支持用该选项保留 INSERT 等语句的驱动计数；依赖下限 `SQLAlchemy>=2.0.44,<3` 覆盖该 API。本修复不把未知 `-1` 数值转成伪造计数，而是在游标关闭前保留实际可用值。
- `operations/profile_repair.insert_routes` 是本范围直接累加 INSERT `.rowcount` 的唯一位置；它通过会话 `_write` 使用修复后的共同连接，因此新增、冲突空写和重复输入都覆盖。其他直接 `.rowcount` 消费者是 UPDATE/DELETE 返回值，不需要复制修复。
- `track_changes` 在同一连接的 handler 范围观察 Core DML，回执日志写入位于观察范围之外。实际冲突空写现在保留计数 0，因此不再无故推动客户端 revision；新 INSERT 仍报告变化。代码仍保留 `count != 0` 的保守判断，没有将其他未知计数错误解释为无变化。
- SQLite `RETURNING` 的 `returns_rows && !supports_sane_rowcount_returning` 分支完全保留。SQLite 在 fetch 前报告 0 时，该分支继续把 DML 视为变化；本轮没有改写该离线 harness 的既有语义。没有改变普通 SQLite SessionDB 后端。

## 测试质量与已观察证据

两项新增真实 PG 测试验证公开路由修复的实际返回总数、同批重复、后续重复、冲突不覆盖、跨 store 隔离，以及同连接观察器的空写/新行区别。测试使用真实 DML 和业务结果，不读取源码，也没有把预期计数直接 mock 成正确值。既有 Worker 回执、只读 revision、回滚和并发回执契约补充了观察器实际消费者的覆盖。

| 验证 | 本 Reviewer 已读取的最终日志 |
| --- | --- |
| 修复前新增回归 | `pg-task16-insert-counts-red.log`：2 failed；重复输入返回 -3 而非 2，冲突空写误报 changed |
| 新计数 + Worker + 事务失败 | `pg-task16-count-fix-tests.log`：3 文件，23 passed / 0 failed，24.9s |
| 原 health/archive/ref 回归 | `pg-task16-health-archive-fixed.log`：35 passed / 0 failed，44.5s |
| 修改后扩大离线回归 | `pg-task16-count-fix-offline.log`：101 文件，520 passed / 0 failed / 2 skipped，53.2s；两个 skip 位于发行环境未传入的 distribution 用例，不计通过 |
| 修改后静态检查 | `pg-task16-count-fix-checks.log`：`scripts/check` 全部 14 项 ok；3 个代码文件相对本轮基准为 0 blocking / 0 advisory |

日志位于 `.build/postgresql/`。以上为对主 Agent 已执行的验证证据的独立核对，本 Reviewer 没有另行连接数据库重跑。扩大离线回归和静态检查的最终结果已补齐，不再是本次修复的证据缺口；离线默认未执行的 integration 用例也不计真实 PG 通过。

## 未验证与门禁

本轮已观察的真实回归、扩大离线回归和全部静态检查支持这个有界修复，未发现需要扩大实现范围的问题。本报告不替代 Task 17/18 的剩余整体后端、应用入口、发行环境及最终验收。其他驱动、未来 SQLAlchemy 版本或任意 executemany 的计数保证不由本轮测试证明；当前生产路径使用 psycopg，实际 INSERT 结果已覆盖。

**整体结论：`CHANGES_REQUIRED`，不批准完整分支。** 本次最小计数修复未发现已确认代码问题，相关真实回归、扩大离线及静态验证已经通过；按计划继续 Task 17/18，并保留尚未完成的总体门禁。

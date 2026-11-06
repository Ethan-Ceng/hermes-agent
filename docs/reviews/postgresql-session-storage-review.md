# PostgreSQL 会话后端验收审查

日期：2026-11-07。分支：`feat/postgresql-session-storage`；功能起点：
`ff09cead02e906a4b1da909268c2cc58ec6e144d`；Task17检查点：`f874e6be49`。
本报告对应Task18审查整改后的工作区，最终本地commit可由分支日志定位。

## 范围与限制

主Agent对照既有设计、消费者清单、逐任务实现和验证记录进行自检。
高风险数据库事务另有[独立阶段性审查及复审](postgresql-core-review.md)。
独立Reviewer没有逐行审完所有入口、搜索和完整分支diff；自检也不能替代真实
PostgreSQL执行或外部平台投递验证。本报告不是完整安全审计。

## 发现及处置

| 级别 | 位置 | 问题与处置 |
| --- | --- | --- |
| major，已整改 | `hermes_db/operations/profile_move.py`、`adoption.py` | 旧接收确认只核对消息数量。同数量重写可能让移动删除唯一源正文。导入同事务保存实际接收快照证明；重放及退休共同检查消息前缀、提示、用量等，正常追加保留，其他漂移保守保留源。 |
| major，已整改 | `hermes_db/operations/mutation_policy.py` | 准备压缩只比较运行revision，直接追加不改变它。快照现包含压缩谱系所有成员的transcript revision，提交锁内比较，漂移拒绝旧摘要发布。 |
| minor，已整改 | `hermes_db/operations/adoption.py` | 不存在的donor经过谱系fallback触发TypeError。现先检查存在，返回失败业务结果。 |

七项新行为契约中，整改前六项有效失败、一项正常追加通过。整改后新旧五文件
主Agent41 passed，独立Reviewer重跑41 passed；没有在这次整改中发现其他确定缺陷。
新增七项实际PG回归接线，尚未执行。位置以最终代码为准，原始快照行号见独立报告。

## 验证与门禁

| 门禁 | 实际证据 | 结论 |
| --- | --- | --- |
| 后端离线契约 | 整改后98文件522 passed、0 failed；含两套source-bundle制品 | 通过此范围 |
| 全分支静态检查 | 功能起点到当前暂存，14项通过；474代码文件、0 blocking/advisory | 通过此范围 |
| 默认SQLite/可选依赖 | 独立PM载荷，默认SQLite实际写读；缺PG extra明确失败 | 通过此范围 |
| 安装资源 | 独立载荷的PG模块与Alembic config/env/revision链可加载 | 通过此范围，不等于执行迁移 |
| SQLite扩大回归 | 2224 passed、9 failed、1 error；9失败及1 teardown error在功能起点源码覆盖下同样复现 | 原始回归仍未全绿，不隐去平台/fixture基线 |
| 普通入口扩大回归 | 四区域及独立TUI运行均exit1且没有完整汇总；部分失败已整改/隔离基线，其他待归类 | 未通过，覆盖不能外推 |
| 实际PG | 263项定义、真实迁移/锁竞争/断连/重启/查询计划未执行，无服务器版本及扩展证据 | 无法验证 |
| 发行/前端 | Windows支持的source-bundle已验证；非Nix wheel被既定守卫拒绝；Nix及TypeScript编译未执行 | 未全部验证 |

源码/测试没有旧SQLite向PG导入、双写或回迁；保持单一gateway owner及Worker RPC。
HostedRoom等独立本地数据库、文件、账号系统与自动扩容的范围边界未扩展。
PG连接失败不应降级成功的离线契约已执行，真实故障情况下仍待证明。

## 结论

**CHANGES_REQUIRED**。本次可定位的三项审查问题在离线范围关闭；实际PG、完整回归
和其余验证门禁仍未满足，不能批准完整分支。验收状态为**FAILED**，真实PG部分同时
受缺少独立测试配置阻塞。恢复时按实施计划的依赖顺序补验，不把当前检查点称为完整后端通过。

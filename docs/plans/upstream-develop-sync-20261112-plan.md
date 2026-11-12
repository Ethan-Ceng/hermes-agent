# 上游更新合入 develop 执行计划（2026-11-12）

- 设计：docs/designs/upstream-develop-sync-20261112.md。
- 指导：docs/upstream-sync-guide.md。
- 分支：sync/upstream-20261112。
- 工作区：D:/AI/hermes-agent/.build/upstream-sync-20261112。
- 整体状态：IMPLEMENTING；当前任务：Task 2；完成：1/5。
- 日期：2026-11-12 Asia/Shanghai。
- 阻塞：官方fetch DNS失败；本轮冻结本地main，线上最新未确认。
- 授权：本地指导、整合和合入develop；没有推送或部署授权。

## 全局约束

保留原分支和backup，不覆盖共享历史、不批量ours/theirs、不动正式配置和数据。
遵守数据库分层、scope、事务、Schema、关闭与缓存约束；测试统一scripts/run_tests.sh。
依赖仅使用项目PM；验证失败不提前推进develop。
原目录.idea/、dify-main/及另一工作区owned/、target/均保留。

## Task 1：冻结输入、建立备份和检查上游

状态：completed

目标：保存可恢复输入并确定范围。涉及：Git refs与remote配置。
步骤：检查分支/工作区/现有计划，建backup，配置并fetch upstream。
验证：git show-ref --verify与rev-list --left-right --count。
完成条件：输入SHA、包含关系与fetch结果记录，原分支不变。
结果与证据：两个backup show-ref exit0；develop=cbfc773dd79241752697e647067c63338fc01680；
个人=37fd59cf8d4ac63d74dc5ed34e5456ac2bc2bbea；main=6c95ee82ef2121bea9e8964b66c3ec6f09278072。
develop...个人=0/64；main...个人=5024/161。官方fetch exit1：Could not resolve host: github.com。

## Task 2：保存指导、设计和计划

状态：in_progress

目标：保存可持续执行的同步协议。涉及：本指导、设计、计划及独立sync工作区。
步骤：从个人起点创建sync工作区，记录分支职责、冲突规则、验证门禁与恢复。
验证：工作区HEAD/文档一致性、git diff --check及暂存范围。
完成条件：三份文档保存于sync分支的指导提交。
结果：worktree add exit0，检出24029个文件，HEAD=37fd59cf8d。
文档首次apply_patch自动审批超时；一次重试因父目录创建失败未写入，改用获授权的文件写入。
验证证据：文档差异检查与提交待执行。

## Task 3：整合main并适配冲突与迁移读取点

状态：pending

目标：在新架构中保留双方行为及历史。涉及：实际冲突及双方修改路径、迁移后的消费者。
步骤：对冻结main SHA执行no-commit merge；登记冲突；按模块最小适配并审查自动合并。
验证：未合并路径为空，git diff --check成功，受影响行为合同通过。
完成条件：冲突清零，上游修复未被静默丢弃，个人架构不回退。
结果与证据：尚未开始；merge-tree预览进行中。

## Task 4：最新验证和代码审查

状态：pending

目标：以当前整合源码证明可合入develop。
涉及：受影响测试、静态/边界/生成检查与docs/reviews/upstream-develop-sync-20261112-review.md。
步骤：检查隔离环境及PM依赖，执行scripts/check、受影响行为与数据库合同；审查并整改后重跑。
验证：记录每条实际命令、退出码、通过/失败/跳过数及限制；核对祖先与无major/blocking问题。
完成条件：必需验证通过，审查APPROVED；环境不足则BLOCKED，不推进develop。
结果与证据：尚未开始，旧分支结果不计本次通过。

## Task 5：本地合入develop并交付

状态：pending

目标：已验收结果fast-forward进入develop。涉及：本地整合提交、develop引用与本记录。
步骤：保存整合提交，核对develop未并行前进，在整合工作区切换develop并ff-only合入。
验证：merge-base --is-ancestor核对三条输入；核对develop SHA、状态与未推送关系。
完成条件：develop包含三条输入，无意外文件/推送/部署/正式数据操作。
结果与证据：尚未开始。

## 最终验证

实际命令与结果：整合后的测试、静态、构建、数据库合同和代码审查尚未执行。
验收清单：指导落盘；冲突及自动合并审查；当前静态/行为/数据库验证；审查APPROVED；develop三条祖先核对。
未通过项目：后续整合与验证待执行，不能声称可合并。
最终状态：IMPLEMENTING，尚非READY_TO_MERGE。

# Fork 上游同步指南

执行记录：[2026-11-12 计划](plans/upstream-develop-sync-20261112-plan.md)。

## 分支约定

| 分支 | 职责 |
| --- | --- |
| main | 跟随官方 upstream/main，避免个人定制 |
| develop | 已验收的个人定制集成线 |
| feat/*、refactor/* | 具体开发，验收后进入 develop |
| sync/* | 吸收上游、适配冲突并验证 |
| backup/* | 保留整合前已提交状态 |

origin 为个人 Fork，upstream 为 https://github.com/NousResearch/hermes-agent.git。
同步方向为 upstream/main → sync/* → develop。

## 每次同步

1. 检查所有工作区和提交包含关系，确定包含所需全部改造的个人起点。
2. 备份 develop 和个人起点。另存有价值的未提交内容，backup 分支只保护已提交状态。
3. fetch 上游并冻结 SHA；网络失败时写清使用的本地 main SHA，不能宣称已同步线上最新。
4. 从个人起点新建 sync 分支，执行 `git merge --no-ff --no-commit <冻结的上游SHA>`。
5. 按行为意图处理冲突，并审查双方都改过但自动合并的文件。实现已搬迁时，把上游修复移植到新所有者。
6. 执行 `python scripts/check`；测试统一 `scripts/run_tests.sh`，使用隔离 HOME/RUNTIME 和测试数据。记录验证命令、范围、失败和未验证项。
7. 验证与审查通过后创建本地整合提交，通过 `git merge --ff-only sync/<名称>` 更新 develop。develop 如被并行推进，重新整合并验证。
8. 保留备份和记录。推送、上游 PR、部署与正式实例重启另行授权。

禁止批量选择 ours/theirs、删除正常断言或恢复旧内部 re-export 来制造通过。
依赖使用项目 PM 锁定；生成文件从真实输入重新生成。
长期共享 develop 通过 merge 保留历史；未共享短期功能分支可 rebase。
准备贡献上游时，在最新 main 上整理干净贡献分支并遵守项目 rebase 规范。

## 中止与恢复

整合提交前先保存新增指导和记录，然后在 sync 工作区执行 `git merge --abort`。
原分支和 backup 保留。develop 更新后需要回退时，从 backup 建恢复分支复核；
已共享历史通过 revert 恢复，不自动 hard reset 或强推。源码回退不等于数据库回退。

## 2026-11-12 输入

- 原 develop：cbfc773dd79241752697e647067c63338fc01680。
- 个人起点：37fd59cf8d4ac63d74dc5ed34e5456ac2bc2bbea；包含 develop 之后64个提交。
- 本地 main：6c95ee82ef2121bea9e8964b66c3ec6f09278072。
- 备份：backup/develop-before-upstream-20261112、backup/custom-before-upstream-20261112。
- 整合分支：sync/upstream-20261112；工作区：D:/AI/hermes-agent/.build/upstream-sync-20261112。
- 官方 fetch 失败：Could not resolve host: github.com。本轮先整合本地 main，线上最新未确认。
- 保留用户未跟踪目录，不操作正式配置、秘密和业务数据库，不推送、不部署或重启。
- 完成状态和最新验证证据以执行计划为准，不能复用旧分支通过记录冒充本次验收。

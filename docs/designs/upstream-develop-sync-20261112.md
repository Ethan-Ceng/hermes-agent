# 上游与个人数据库架构整合设计（2026-11-12）

## 背景、目标与范围

用户已授权保存同步指导并将更新合入 develop，包括必要的本地提交。
保留37fd59cf8d的最新数据库分层改造，吸收6c95ee82ef的本地main更新。
原develop为cbfc773dd7；个人起点比develop多64个提交，双方有143个共同修改路径。
不推送、不部署、不操作正式配置或业务数据，不增加本次目标以外的能力。

## 现有能力与方案比较

复用Git三方合并、祖先检查、Hermes PM、scripts/check和scripts/run_tests.sh。
旧验收仅用于选取风险，不能当作本次通过证据。

| 方案 | 成本与兼容性 | 风险与验证 |
| --- | --- | --- |
| sync分支merge main | 保留双方历史，后续同步可持续 | 推荐；审查冲突、自动合并、搬迁后的真实消费者 |
| 整体rebase个人历史 | 重放161个个人提交及历史合并，维护成本高 | 已共享历史身份变化，不用于本次 |
| cherry-pick上游 | 适合独立临时补丁 | 5024个提交的依赖难以维护，不满足完整吸收本地main |

## 决策与流程

冻结三条输入并保存backup；在ignored .build下创建普通sync分支的独立工作区。
保存指导及计划后进行no-commit merge，按目录读取AGENTS，移植真实行为并审查自动合并。
数据库实现沿用最新infra/domain/application所有权；保持事务、scope、CAS、回执、显式Schema和关闭约束。
生成合同从输入生成，依赖仅通过PM处理。没有计划新增业务接口或迁移。
完成最新验证及审查后创建整合提交，再以ff-only更新develop；分支并行前进时重新整合验证。

## 风险与恢复

大型搬迁不能恢复旧垫片掩盖新调用；自动合并不证明语义兼容。
使用隔离HOME/RUNTIME与测试数据；必需验证不可执行则BLOCKED，不提前更新develop。
未提交merge可abort；原分支和backup保留，源码恢复与数据库恢复分开处理。
上游fetch遇DNS失败，本轮冻结已存在的本地main，不声称覆盖远程后来提交。

## 验收与假设

develop最终包含原develop、个人起点、本地main且历史不重写；冲突和迁移读取点已核对；
指导、计划、审查落盘；必需静态、行为及数据库验证通过；无无关文件暂存、推送或正式实例操作。
用户的确认沿用前轮建议，以最新数据库重构为个人起点；无待用户决定的实现歧义。

## 迁移回执身份校验的安全替代方案

自动审批拒绝直接把persisted_profile_id比较限定到PG，被拒绝的修改未执行。
已核对上游main两个恢复函数：原生回执保留minting home，按实际存储行和route/origin隔离；6c8606d51d明确禁止重写minting home。
替代提案保留PG store-id严格相等；SQLite旧home不相等时，额外核对authority自身DB的session行、sid、route、origin profile/chat/user，任何不符均profile_mismatch。
新增独立validator与两个行为合同先验证该规则；验证后替代方案获准接入生产恢复函数，未绕过自动审批。

替代validator已通过规范runner的2个测试，明确拒绝foreign PG store-id、origin beta、其他user/chat、foreign route和缺失session；本次接入该已验证规则，保持现有后续session-id/lineage/route/policy检查。

## 上游新增持久化能力适配决策

比较新增PG表/revision与复用现有scoped state_meta命名记录：本轮选择后者，保存每个子代理一个具名版本化键，在域层通过当前store-id和短事务锁隔离，保留原claim/recovery/TTL/pin行为；不新增Schema或改动历史资源。
SQLite维持上游原表。两后端通过具名记录操作接口提供相同结果，不提供通用SQL翻译或SQLite回落。Profile/秘密与后台scope绑定仍归tools应用装配。
PG metadata前缀扫描只用于有界清理和pin列表，单条读写使用组合主键；如后续规模证明需要专表，再独立设计索引与迁移。
同轮为上游新增room_task_summary补PG具名查询及groups变更签名读取，不把PG引用转换成文件路径。新增两个真实PG行为合同先证明当前缺口，测试fixture只用已标明独立验收DB与随机Schema。

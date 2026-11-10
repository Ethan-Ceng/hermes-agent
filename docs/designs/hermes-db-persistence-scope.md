# hermes_db 持久层职责精简设计

## 文档状态

- 状态：NEEDS_USER_DECISION；持久层定位已明确，历史修复CLI整体退役或外置的产品处置待用户选择。
- 日期：2026-11-10；基准：90a2987e8c，运行时代码为9a8093841b。
- 实施分支：refactor/hermes-db-persistence-scope；隔离检出：D:/AI/hermes-db-packages。
- 正式源码D:/AI/hermes-agent及已运行网关不因本轮准备而修改、停止或重启。
- 关联：[原统一后端设计](unified-database-backends.md)、[分包设计](hermes-db-package-layout.md)、[本轮计划](../plans/hermes-db-persistence-scope-plan.md)。原18项分包已经交付，不重写其完成记录。

## 背景与目标

用户明确hermes_db是可替换的持久层。顶层选择storage.backend，各后端实现相同业务存储合同，应用不因选择SQLite或PostgreSQL改变业务流程。支持后端不意味着负责把旧数据搬到新后端，也不意味着持续承担旧版本错误归属的补偿与修复。

上一轮按“保留现有公共存储方法”完成分包，仍保留历史修复接口。本轮改以职责为准缩减这些接口；有消费者只证明需要处理调用链，不能作为留在持久层的充分理由。

目标：移除hermes_db的历史Profile数据修复、搬移票据和自动承接遗留数据职责；保留正常业务CRUD/完整事务、锁、作用域、回执、unknown结果恢复、关闭与资源生命周期。

## 范围与非范围

- 现有SQLite/PostgreSQL仍由统一配置选择；不引入尚无实现消费者的新后端注册框架。
- 后端切换选择独立数据集。禁止启动时自动迁移、复制、双写、回迁，故障不得回落另一后端。
- 退役候选包括repair-profiles专用的查询/更正/搬移接口，以及TUI恢复时自动承接旧版本错归属会话的路径。
- 正常Profile删除/重命名、显式业务导入导出、会话恢复/分支/压缩、Worker/调度恢复分别核对，不能因含move/repair/import字样就删除。
- Schema建表、版本校验和显式版本升级是后端生命周期。沿用此前约束：0031要求、31个revision、29个表模块不变，历史SQL/算法不重写；本轮不压平Alembic或缩短支持版本链。
- 不改正式配置/秘密/PG或SQLite业务数据，不用正式Profile做测试，不推送/发布PR/合并或切换正式运行实例。

## 当前实现与消费者核对

| 实现 | 实际消费者/职责 | 本轮处置边界 |
| --- | --- | --- |
| integration/postgres/operations/profile_move.py | CLI sessions_repair_profiles.py的export/import/delete三阶段，修复错Profile数据 | 从hermes_db合同和实现移除；CLI整体退役或外置待选 |
| integration/postgres/queries/profile_move.py | 搬移snapshot/ledger护栏，也被adoption复用 | 处理adoption后删除专用模块，不以重命名空壳保留 |
| integration/transfer/move_values.py | Profile move票据key、快照digest，adoption也用digest | 随上述实际消费者处置；不删除仍有业务身份消费者的共享定义 |
| integration/postgres/operations/profile_repair.py及queries/profile_repair.py | repair-profiles的标签、父关系、路由、topic修复 | 修复能力从DB合同移除；先分离下项正常生命周期共享查询/操作 |
| integration/postgres/operations/profile_purge.py | Profile删除通过session_composition及gateway/profile_identity调用，复用repair.delete_routes | 保留删除时隔离/路由/投递清理；将真实共享操作归正常所有者，不能整文件连带删除 |
| integration/postgres/operations/adoption.py | tui_gateway/methods_session.py:_resume_adopt_stranded | 明确为旧版本错路由遗留补偿，不是常规resume；纳入移除自动数据承接范围 |
| integration/transfer/session_store.py | 混合正常导入导出、历史修复、adoption | 仅去除上述维护方法，剩余能力按真实业务职责收敛 |
| domains/sessions/postgres/store.py | 对维护方法显式委托 | 删除维护合同与对应委托；无旧方法shim或万能反射代理 |
| hermes_state_profile_repair.py及SessionDB组合 | SQLite对应维护实现/SessionLedgeredError等身份 | 根据产品处置同步处理，不能只让PG缺方法后运行时AttributeError |
| migrations/merge_data_repair.py | 仅revision0031显式upgrade调用 | 本轮保留；普通启动不运行；不把已部署升级历史当无用脚本删除 |

初步15项专用接口：export_session_for_move、import_moved_session、delete_moved_session、find_crossed_profile_sessions、_ledgered_session_ids、list_gateway_routing_rows、find_profile_less_telegram_topic_rows、count_messages_all、relabel_sessions_to_key_profile、sever_crossed_parents、rekey_legacy_main_sessions、delete_gateway_routing_rows、insert_gateway_routing_rows_if_absent、relabel_telegram_topic_rows、key_profiles_for_chat。最终逐项以全仓直接/动态/测试读取点复核，不按名字一刀切。

## 可选方案与比较

| 方案 | 持久层结果 | 产品兼容/维护成本 | 主要风险 |
| --- | --- | --- | --- |
| A：整体退役历史修复功能 | 删除旧CLI与双后端专用实现，自动遗留承接移除；代码和合同真正减少 | 显式取消repair-profiles功能；维护成本最低 | 旧版本错归属数据不再由应用修复，须明确文档 |
| B：外置显式维护工具 | DB合同同样移除；维护实现放独立可选工具，正常启动/业务资源不依赖它 | 保留手工运维价值，但仍要维护双后端与版本/锁协议 | 仅移文件而DB仍传入维护方法会造成假精简；不得新增通用raw SQL代理 |
| C：只改目录/名称 | 维护职责仍进入DB资源和公共方法 | 兼容代价低、耦合不减 | 不满足用户要求，不采用 |

推荐A实现实际精简。用户若需保留手工修复入口则采用B，但两者都必须让hermes_db只负责持久化合同。已通过文本选择问题请求A/B决定；在选择到达前只进行不依赖该决定的核对，不删除CLI或应用接口。

## 目标流程、数据与接口

1. 顶层捕获Profile配置和稳定scope，factory选择一种已实现后端。
2. 业务使用同一组具名存储操作；选中的适配器负责SQL/事务/方言。
3. 所选后端未配置、未初始化、不可用或不支持时明确失败，不扫描/导入其他数据集。
4. resume等常规流程不会因目标缺失而到另一Profile/store自动复制旧会话；正常已存在/临时未落库/权限拒绝/不存在分支保持明确。
5. Profile删除等真实生命周期继续在其原作用域内清理状态，不能借精简破坏资源与投递边界。

无表、列、索引、业务DTO、RPC字段或配置键变化。缩减的公共方法是历史维护合同，不新增迁移服务、通用CRUD、通用连接代理或可选flag兼容层。业务接口错误身份保持；维护专用异常若无剩余消费者才删除。

## 风险、恢复与验证

- 共享函数被误删：以consumer+symbol台账处理profile_purge/delete_routes及adoption/snapshot；运行正常Profile删除、TUI resume、路由与持久化合同。
- 双后端不一致：产品入口同步处置SQLite与PG维护路径；正常业务套用同一合同；无PG extra的SQLite实际运行。
- 隐式历史回落仍存在：测试缺失/错scope会话不会从其他store自动承接，并验证实际隔离与新PID恢复。
- 脱离运行环境：继续独立worktree和隔离HERMES_HOME/HERMES_RUNTIME_DIR，依赖仅PM，测试仅scripts/run_tests.sh。
- Schema风险：固定61锚点及0031要求，历史SQL/算法不动；真实PG仅归属随机Schema，不接触正式数据。
- 回滚仅恢复代码检查点，不回迁数据或降级Schema；当前正式服务一直使用90a2987e8c的运行时代码等价9a8093841b。

## 验收标准

- [ ] 顶层选择SQLite或PG即覆盖同Profile全部自有数据库；切换不搬移数据，故障不回落。
- [ ] hermes_db不再暴露历史Profile修复/搬移合同，启动/普通resume不自动承接错归属数据。
- [ ] 用户选定的旧CLI处置完整落实，无动态调用悬空或仅改PG造成的兼容崩溃。
- [ ] Profile正常生命周期、会话/Worker恢复、隔离/权限/事务/回执/关闭合同保持。
- [ ] 独立SQLite载荷、真实PG读写/持久化/多scope/新PID、实际Matrix SDK适用回归有当前证据。
- [ ] 0031、31revision/29表模块及历史升级算法保持；正式实例及数据未被开发步骤影响。
- [ ] 活跃文档、skills、边界台账、直接/动态导入及patch读取点同步，最终验证和独立审查通过。

## 待决策项

只待用户选择历史repair-profiles等功能整体退役(A)或外置手工工具(B)。持久层定位、统一后端选择、禁止自动数据迁移的方向无需再次确认。原统一后端Task24及七项非WSL缺证继续独立保留。

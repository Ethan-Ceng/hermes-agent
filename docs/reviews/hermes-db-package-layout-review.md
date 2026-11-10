# hermes_db 分包与模块收敛代码审查

## 审查范围

- 目标基准：`cbfc773dd79241752697e647067c63338fc01680`。
- 变更分支：`refactor/hermes-db-packages`；固定代码范围：`cbfc773dd7..d6e5f62e75`，共 909 个变更文件。
- 实施检出：`D:/AI/hermes-db-packages`；审查者为未承担实施任务的独立 Reviewer。
- 日期：2026-11-10。
- 输入：`docs/designs/hermes-db-package-layout.md`、`hermes-db-package-map.json`、`hermes-db-package-final-freeze.json`、`unified-database-backends.md`，以及 `docs/plans/hermes-db-package-layout-plan.md`。
- 按根及涉及目录的 `AGENTS.md`、Supercoder code-review 技能及 review-template 审查。固定 tip 之外仅复审了下述三份统计文档修正；Python、测试、依赖、Schema 和生成接口未再修改。
- 审查包含完整变更清单、原始/目标代码的方法体与导入对照、组件组合及实际消费者、测试实现和安全日志摘要，并非仅依据计划声明。Reviewer 自行执行只读 Git/AST 核对；业务测试由实施 Agent 经标准 runner 执行，Reviewer 核对其日志与冻结源码对应关系。未触碰正式运行源码、Profile、秘密或业务数据，未重启服务。

## 问题列表

未发现 blocking、major 或未处理的代码问题。发现并关闭 1 项 minor；无其他 suggestion。

### [minor，已处置] “业务模块”统计未按设计排除表和迁移

位置：`docs/designs/hermes-db-package-map.json:6398`；关联设计文档第 149 行及实施计划 Task16/Task18。

问题：固定审查 tip 将仅排除 `__init__.py` 的 389→315 命名为业务模块，尚未落实设计要求的表/迁移排除口径。

影响：读者会把包初始化之外的全部模块与业务模块混为一谈；不影响运行逻辑或实际净减少结果。

建议与处置：同时保留“非 namespace 模块”和“业务模块”两组定义。实施 Agent 已修订映射、设计和计划，Reviewer 已复核实际 diff 并独立重算：

- 全部模块：398→365，净减 33；根入口精确 11。
- 仅排除包初始化：389→315。
- 再排除 `tables/`、`migrations/`：328→254，净减 74。
- 历史验证数字保留，Task18 明确解释标签更正。此项已关闭，无运行时或测试整改。

## 无法验证项与适用边界

- 本结论仅覆盖本次分包重构；原统一后端 Task24 和七项非 WSL 平台缺证继续独立开放，未以本轮结果解除。
- Windows 的 5 项平台 skip 及独立发行组的 2 项 Linux SDK skip 保留；实际 Matrix SDK 验证在 Linux 进行，不外推为 Windows 能力。
- 未执行全仓测试、前端构建或正式实例切换。两处生成文件仅修改 JSDoc/description，wire JSON shape 与 TypeScript tokens 不变；契约生成检查已通过。
- 真实 SDK 测试使用实际加密对象及数据库，网络交互由协议测试控制；本报告不声称对外部生产 Matrix 服务或正式 Profile 做过验收。

## 合并门禁

### 需求符合度

- [x] 398 个原始 Python 源与映射逐项一致且源名无重复；每项最终目标存在，两个旧技术层初始化模块有明确删除处置；新增模块有归属。
- [x] 根保留 11 个实际入口/定义，365 个总模块；未保留旧全局 operations/repositories 或内部路径兼容空壳。
- [x] 原 Session 36 Mixin 与 Runtime 10 Mixin 改为明确组件和显式委托；没有通用 CRUD、万能 `__getattr__` 或反射批量导出。
- [x] 计划偏差、初次非零批次和修正复验均有记录；本次未扩大核心工具、插件公共 API、配置或数据库结构。

### 正确性

- [x] 从原始基准类及静态兼容别名独立重建接口：Session 288、Runtime 85 个方法的参数、默认值、返回注解和 property/staticmethod/classmethod 属性均 0 差异；显式委托未漏传参数。
- [x] `SessionContext` 拥有捕获的 scope、事务、同线程 snapshot pin 和关闭状态；六个 Session 组件及五个 Runtime 组件共用原资源。Runtime 写入仍先激活拥有者 Profile，未另造池或独立 close 状态。
- [x] Worker lineage、消息、retirement/media、metrics 及授权查询在要求同事务的路径继续传递同一 Connection/scope；准备阶段和提交后应用协调由具名 integration 能力承接。未因模块合并改变锁、CAS、回执 operation、generation、重放或 unknown commit 边界。
- [x] DTO/异常使用原对象身份；Native 公共导出仍指向共享实际定义。Kanban/Room 动态路由改为明确模块表，生产消费者与真实 patch 读取点同步更新。
- [x] 31 个 revision 文件/图、表定义与 metadata/SCHEMA 身份、`0031_merge_data_repair` 要求保持；表包初始化仅调整 catalog 导入，历史 repair helper 仅有必要导入迁移，算法和 SQL 未变。
- [x] 检查了实际 COMMIT 后再抛连接错误的恢复测试，以及真实 0004/0030 前向、重复升级、0031 新 PID 重开及跨 store 隔离；不是只编译 SQL 或在提交前模拟失败。

### 安全性

- [x] 拥有者 Profile、store/target、权限与精确 grant/回执边界保持，未发现本次引入的越权、注入或敏感信息扩张。
- [x] PG 业务测试进程拒绝 SQLite connect、别名及直接构造；单后端业务与新 PID 恢复证据为 0 SQLite 尝试，无 SQLite/内存回落。
- [x] 审查仅读取脱敏摘要和代码；没有读取或输出实际 .env、DSN、密码、加密材料及原始失败堆栈。

### 可维护性

- [x] core/backend 不选择领域或应用组合；运行时 PG 下层不再依赖完整 Native 门面或 Mixin。共享纯值、Agent 转录语义、同连接窄查询、SQLite 桥接和入口组合在 consumer+symbol 台账中分别说明。
- [x] 边界 checker 的审核条目不能绕过方向规则；其 miniature-package 测试验证“批准 LIMIT 不等于批准同模块 SECRET”，不是读取生产源形状的 change-detector。
- [x] 插件边界仅精确迁移既有目标路径，`plugin_api.json` 未扩张，既有 847/26 计数保持；活动指南已更新，历史快照明确保留。
- [x] 小域合并、Kanban/Room 工作流归组及明确能力注入与设计一致，没有为减少文件引入新的巨型隐式基类集合。

### 测试质量与最新证据

Task17 初次完整 PG 718 通过/2 失败、Linux Native 582 通过/2 失败及外目录 option 错误、Windows Native 577 通过/2 失败均未抹去；已核对缺 messaging 依赖、发行 driver/source 前提及外目录专属选项的具名复验。以下 Task18 完整命令在同一冻结源码上重新取得 exit 0，作为最终门禁，不将旧 686/36/32 基线当作新结果。

| 最终批次 | 标准 runner 结果 | 日志 |
| --- | --- | --- |
| Linux PostgreSQL 全目录 | exit 0；131 文件，720 通过、0 失败、0 skip；1630.7s | `.build/package-layout/task18-full-pg-linux.log` |
| Linux DB Native 全目录 | exit 0；234 文件，584 通过、0 失败、0 skip；797.6s | `.build/package-layout/task18-full-native-linux.log` |
| Windows DB Native 全目录 | exit 0；234 文件，579 通过、0 失败、5 平台 skip；552.9s | `.build/package-layout/task18-full-native-win.log` |
| CLI/TUI 三文件 | 两端各 49 通过、0 失败，exit 0 | `.build/package-layout/task17-cli-native-{linux,win}.log` |

Linux 所选 Native/CLI/TUI 共 633 通过；Windows 共 628 通过、5 skip。234 文件含 integration deselected 文件，不将其当作执行过 PG 测试。Windows 五项 skip 对应 `contracts/test_single_backend.py` 的完整 SQLite+SDK、`contracts/test_domain_resources.py` 的 fork、`contracts/test_matrix_close.py` 的两个异步关闭用例，以及 `test_distribution.py` 的 Linux SDK 恢复；逐文件日志分别为 1s、1s、2s、1s，与实际平台 marker 一致。三份完整日志均无失败/FLAKY 节点。

- 独立发行：`task17-distribution-final-linux.log` 6 通过/0 skip；`task17-distribution-final-win.log` 4 通过/2 Linux SDK skip。源码载荷无 .git，driver 与 source 分离，环境由 PM 从冻结源创建。
- 普通 SQLite 独立环境无 SQLAlchemy/psycopg/Alembic/asyncpg；实际读写与新进程重开通过。SQLite+Matrix 使用单独 Linux SDK 环境并拒绝 PG 连接。
- Matrix 当前十文件 31 项真实 SDK/PG 测试覆盖协议、加密对象、并发、错误传播、关闭及重开；`task17-sdk-protocol.log` 确认 mautrix 0.21.1、python-olm 3.2.16，CryptoStore/SyncStore 均实现且类非 abstract。
- 两端 `task17-final-hashes-*.log` 各核对 17,735 个生产/测试文件，0 差异；运行时与测试对应 bd82697cb4，冻结 tree 为 `97542f2a099f7c0a4da4da0689ce1a64f240cec5`，另两份生成描述覆盖层有明确记录。
- `git diff --check cbfc773dd7 d6e5f62e75` 通过；当前 16 项静态检查、插件边界及生成契约检查均通过，详见 `task18-final-check.log`。

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 无 blocking | 通过 | 独立 diff/代码审查 |
| 无未处理 major | 通过 | 未发现 major；唯一 minor 已处置 |
| 本次验收标准满足 | 通过 | 归属、接口、生命周期、边界、发行及实库证据 |
| 相关测试通过 | 通过 | Task18 完整 Native/PG exit 0，CLI/TUI 与发行专项通过 |
| 构建/静态检查 | 通过（适用范围） | PM 独立发行、16 静态、插件边界和契约生成；未声称前端构建 |
| 数据迁移兼容 | 通过 | 无新 revision；0004/0030→0031、重复升级、重开及丢 ACK 恢复 |

## 审查结论

- 结论：`APPROVED`。
- 理由：本次分包重构满足设计与适用门禁；未发现 blocking 或 major，唯一统计 minor 已关闭。
- 剩余风险：以上平台、全仓/前端与原统一 Task24 边界仍保留；测试及静态审查不能证明所有未触发的执行交错。
- 下一步：由主 Agent 完成 Task18 计划与本地交付记录；正式部署、重启、推送、PR、合并或生产数据操作均不属于本报告授权。

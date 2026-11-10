# hermes_db 持久层职责精简独立代码审查

## 审查范围

- 审查者：独立 Reviewer 子 Agent；未参与本轮实现，未再委派。
- 日期：2026-11-10。
- 检出：`D:/AI/hermes-db-packages`；分支：`refactor/hermes-db-persistence-scope`。
- 源码基准：`90a2987e8c`（运行时代码等价 `9a8093841b`）；规划提交：`f9b777f9c0`。
- 审查 HEAD：`972a5ff3956059a1c19e229552f4d303cd5a3be0`；运行代码/测试冻结：`90a6412b220d4894d5bf030c9d7662207a6de23d`，tree `03205940e6167ad2f15abd7ce863c89ed509358f`。
- 读取相对基准的完整变更范围（52 文件），包括删除的实现/测试、保留与改名组件、新边界合同及活动文档；对照 `hermes-db-persistence-scope.md`、实施计划、处置映射、freeze 清单和 `unified-database-backends.md`。遵循根、CLI、TUI、测试区 AGENTS 及 `supercoder:code-review`。
- 本报告也覆盖审查中由实施 Agent 修正的映射状态。该修正和计划进度仅涉及文档，未改变冻结运行代码。
- Reviewer 仅写本报告及 `.build/persistence-scope` 安全审计/测试日志；未修改生产代码、测试、配置或正式 checkout，未切分支、提交、重启进程或管理任何数据库服务/角色/扩展，未读取私有连接配置或原始失败堆栈。

## 问题列表

未发现未处置的 blocking、major、minor 或 suggestion。

### [minor，已整改] 混合包装器处置状态未结算

位置：`docs/designs/hermes-db-persistence-scope-map.json:553`。

问题：`test_dispositions` 中 `tests/hermes_db/postgresql/test_review_regressions.py` 仍为 `in_progress`，而删除的 5 个 move/adoption 参数、保留的 2 个 compression 参数已实施并在 V3 实际通过。

影响：处置台账与源码/验收证据不一致，可能误判混合测试仍未完成；不影响运行行为。

建议与处置：将该唯一条目标记 `completed`。实施 Agent 已修改；Reviewer 重新读取确认 `completed`，并复核运行代码/测试仍与冻结一致，问题关闭。无需重新执行完整数据库批次。

## 审查依据与判断

### 需求、正确性与范围

- `repair-profiles` 的 parser、预打开 dispatch、CLI 编排、SQLite repair mixin 和 PG 专用 move/repair/adoption 调用链整体退役；没有废弃空壳、兼容 flag、旧路径 re-export、反射代理或替代迁移工具。独立搜索包含方法名、模块名、动态字符串与 patch 点，未发现活动消费者悬空。现存 Profile 目录 rename、正常 `migrate-identity`、其他业务 adoption 名称没有被误删。
- `tui_gateway/methods_session.py` 只取消 stranded donor 探测/复制分支。拥有者 store 的 ID/title、live-lazy、server-minted key、compression tip、错误 4007 与 handle 交接/释放路径保留。新合同实际检查另一 store 的 get_session/get_session_by_title 均未调用，并比较 donor 导出内容保持不变，避免仅断言“目标没有行”。
- `storage.backend` 通过正常配置写入/解析在新子进程中选择独立数据集。SQLite A → PG B → SQLite A → PG B 验证独立标记和原内容、新 PID；缺配置、未初始化、不可达明确失败且 0 SQLite attempts，未初始化目标仍 0 表。没有热换会话上下文、双写、隐式搬移或故障回落。
- 独立 AST/签名审计确认 PG Store 295→279，只取消映射指定的 16 项方法；剩余唯一签名差异是内部构造 `transfer`→`portability`。没有新增方法或业务 DTO/配置/公共合同扩张。DB Python 模块 365→359，root 11；6 项净减少与 3 次现有模块改名分别计数。
- `delete_routes` 从 repair 所有者移到现有 `queries/gateway.py:97`，保留同 Connection、scope、store exclusive lock、路由删除和共享退休调用。`integration/profile_lifecycle.py` 保留 Profile 删除顺序、其他 Profile 隔离及 terminal delivery 处理。正常 Profile 文件 rename/恢复、业务 import/export/foreign import、Worker 与调度持久合同仍在。
- `integration/media_grants.py` 仅保留 received/origin/lock/remaining/release。对照基准的全部保留 grant 函数，以及 `SessionPortability` 除构造之外的全部保留方法，AST 完全相同。新跨 store 授权生成、move/adoption 票据生成已删除；既有授权读取、pin、token/recipient/owner 校验和最后引用回收保留。

### 事务、scope、安全与资源

- 本轮没有改动事务管理、连接池、scope 捕获、锁协议、Runtime receipt 或 unknown commit 分类；共享函数迁移没有将完整操作拆开或新增隐式 commit。
- 实际读取 `postgresql/conftest.py`、`single_backend_guard.py`、`pg_support.py`：PG 业务 guard 通过 CPython `sqlite3.connect` audit 事件并记录尝试，含 URI/内存/预先捕获别名/直接 Connection 构造；fixture teardown 也拒绝调用方捕获后隐藏的尝试。单独 guard 行为测试覆盖这四入口。PG 临时 namespace 使用随机 schema、current_database 核对及所有权 marker；删除前复核 marker，没有服务/扩展/角色管理。
- 读取实际 `test_merge_commit_recovery.py`：注入函数先调用真实 dialect `do_commit`，之后才抛 psycopg OperationalError；验证 UnknownCommitError、关闭/重开后原 receipt/tombstone 与精确 grant debt。不是提交前异常模拟。`test_merge_process_recovery.py` 实际运行两个不同 PID，并检查另一个 scope 无该状态。
- 读取真实 Matrix SDK 协议、OlmMachine、Olm/Megolm 对象往返、并发 ratchet、cursor 错误传播、close drain 和新进程恢复代码；PG SQL/持久化未用存储 mock 替代，网络边界通过本地/stub transport 控制。V3 完整 PG runner 安全成功行实际列出 SDK flows、concurrency、close、recovery、merge commit/process、single backend 与保留 compression 文件通过。Linux PM 载荷事实为 mautrix `0.21.1`。
- Reviewer 独立逐项读取基准/freeze Git blob 并复算 61 个固定 Python 锚点与 4 项迁移资源，65 项 0 变化；`0031_merge_data_repair`、31 revision、29 table 模块与历史 SQL/算法/版本链保持。本轮没有新 DDL 或普通启动升级动作。

### 测试退役质量与证据绑定

- 映射 65 条是 59 retired、5 replaced、1 converted；含 wrapper 参数条目，不能称为删除 65 个 pytest 用例。qualified wrapper 审计为 46 个完整模块/函数身份、0 callable/getattr 残留，避免把短名称碰撞当退役消费者。
- 逐项检查混合文件：file_consumers 仍有 roster/stats/resource release/backup；review_data_safety 与 PG review_regressions 仍执行 in_place True/False 的晚到 append 冲突；health_archive_refs 仍有 health、archive backfill、retention、Profile purge 和 publication 并发；insert_counts 保留真实 Worker no-op/new-row tracking。新增第 24 个包装器只取消 5 项已退役参数，2 项正常 compression 参数实际通过。
- 新既有授权合同直接准备有效持久记录，再执行普通导出/import 分支/删除及资源 release，覆盖最后引用前保留、token/recipient 不匹配保守保留、file owner 变更保护；不依赖已退役 mover 建立前提。普通 import 的 hidden/pinned/archived、checkpoint、deleted-parent 保护未被删掉。
- 实际读取 `.build/persistence-scope/task8-v3-*.json` 最终安全回执、`task8-state.json`、`task8-full-hashes.json`、`task8-v3-final-static.json`、`task8-completion-check.log` 与 qualified retirement audit，没有只接受口头成功。最终 9 批均绑定冻结 90a641、完整命令 exit 0、failure_nodes 为空。
- 独立复算归档 SHA256 与 freeze 相符；Windows source 23,911 项及独立 driver 23,911 项均与完整 manifest hash 一致；当前 production 9,490 + tests 8,239 = 17,729 项中 633 个 raw 差异全部仅 CRLF/LF，其余内容差异 0。各改动运行区 Git diff 对 freeze 也均 exit 0。Linux source/driver 各项身份由实际读取的 V3 identity 安全回执支持（合计 47,822 项、0 差异），Reviewer 未重新复制 Linux 载荷。

## 验证记录

### 已读取并核实的冻结 V3 完整验收

| 批次 | 文件 | passed | failed | skipped | exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Native Windows | 235 | 563 | 0 | 5 | 0 |
| Native Linux | 235 | 568 | 0 | 0 | 0 |
| 完整 PostgreSQL Linux | 133 | 709 | 0 | 0 | 0 |
| Consumers Windows / Linux | 各 16 | 各 129 | 0 | 0 | 0 |
| 独立纯 SQLite Windows / Linux | 各 1 | 各 3 | 0 | 0 | 0 |
| Distribution Windows | 2 | 4 | 0 | 2 | 0 |
| Distribution Linux | 2 | 6 | 0 | 0 | 0 |

Windows Native 5 项 skip 对应 fork 资源、两项 Linux close 协议、完整 SQLite SDK 业务与发行 SQLite SDK 恢复。Windows发行另 2 项是 Linux SQLite SDK 恢复与全 PG domains+SDK 新 PID；当前 Linux 适用组实际执行，不能计作 Windows SDK 通过。runner 安全 per-file 行、未改的 platforms marker 与计划具名处置相符。

冻结静态：DB boundaries 10,130 resolved imports / 0 violations；plugin boundaries 847 module_to_core / 26 core_to_module，无扩张；generated gateway contracts 检查 exit 0；completion check 为 16 checks ok、0 blocking/0 advisory。无 TS 可执行代码或 wire 形状改动，本轮没有全前端构建声明。

首轮 93fb Native collection error、PG 恢复窗口失败及被中止的无效 Linux 批次不计入上述通过。它们在计划中分别保留；V3 完整重跑证据没有沿用首轮成功数或把环境问题称为本轮修复。

### Reviewer 独立补验

两批均在 `D:/AI/hermes-db-packages` 执行，解释器为 `D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe`。运行前绑定：

```powershell
$env:HERMES_HOME='D:/AI/hermes-db-packages/.build/persistence-scope/profile'
$env:HERMES_RUNTIME_DIR='D:/AI/hermes-db-packages/.build/package-layout/runtime'
$env:HERMES_PYTHON='D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe'
$env:HERMES_TEST_FILE_RETRIES='0'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

实际展开命令一：

```powershell
& 'D:/Programs/Git/bin/bash.exe' scripts/run_tests.sh tests/hermes_cli/test_sessions_command_boundary.py tests/tui_gateway/test_session_resume_store_boundary.py tests/hermes_db/contracts/test_existing_media_grants.py tests/hermes_db/contracts/test_review_data_safety.py -j 2 --file-timeout 1200 -- --tb=short -ra -vv
```

结果：exit 0，4 files / 20 passed / 0 failed / 0 skipped，17.1s；日志 `.build/persistence-scope/task9-review-focused.log`。

实际展开命令二：

```powershell
& 'D:/Programs/Git/bin/bash.exe' scripts/run_tests.sh tests/tui_gateway/test_resume_live_lazy_session.py tests/hermes_db/contracts/test_remaining_read_maintenance.py -j 2 --file-timeout 1200 -- --tb=short -ra -vv
```

结果：exit 0，2 files / 18 passed / 0 failed / 0 skipped，12.4s；日志 `.build/persistence-scope/task9-review-retained.log`。

独立结构与 hash 审计安全结果：`.build/persistence-scope/task9-independent-review-audit.json`，实际运行 exit 0。相对基准的 `git diff --check` 也 exit 0。未为审查重复完整 PG 批次或操作数据库。

## 无法验证项与保留限制

- Reviewer 未独立重复 709 项完整 PG/5 个 PM 构建/所有平台批次；以已读取的本轮冻结回执、独立 hash 复算、实际测试代码及 38 项局部独立复验作审查证据，不声称全仓所有测试均通过。
- Windows Profile 八项已由实施方在独立 90a 基准同 ID 复现，相关生产与测试文件未改；Linux 完整相关组 135 passed / 3 Windows-host skips。八项既有问题仍未解决，不把它们改称本轮通过，也不因本轮精简要求扩大为系统权限/平台修复。
- 原统一后端 Task24 和七项非 WSL 缺证独立保留；本报告未验收或解决它们。PG 曾进入恢复窗口的环境根因未被本轮修复。
- 正式运行切换、部署、真实用户历史迁移不在本次审查/授权范围。此报告仅支持持久层精简变更的代码批准。

## 合并门禁

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 无 blocking / 未处理 major | 通过 | 完整变更与调用链检查，未发现 |
| minor 已处置 | 通过 | 映射 :553 现为 completed，独立复读确认 |
| 本轮需求与兼容性决定满足 | 通过 | 整体退役、独立数据集、正常路径及既有授权保持 |
| 运行代码绑定与相关行为验收 | 通过 | 冻结 V3 九批 exit 0；独立 38 项通过；hash/AST 审计 |
| 固定 Schema/迁移资源 | 通过 | 独立 65 项基准/freeze hash 一致，无 SQL/链变化 |
| 构建/生成/边界 | 通过（本轮适用范围） | 5 PM 载荷及冻结静态；无 TS/wire 行为改动 |
| 数据迁移执行 | 不适用 | 产品合同明确取消跨后端/跨 store 历史搬移 |
| Task9 最终文档提交前 staged 检查 | 由实施 Agent 完成 | 本报告写入后执行最终文档静态/空白检查；代码审查批准不代替该流程 |

## 审查结论

`APPROVED`。

本轮精简符合确认后的持久层职责与兼容性决定；未发现新增正确性、安全性、scope/锁、事务/receipt 或正常业务回归问题。唯一台账 minor 已整改。Task9 可继续完成最终文档门禁、计划结算及本地提交；本报告不自动标记全系统验收、合并或正式部署完成。

# hermes_db 持久层职责精简实施计划

## 关联设计与当前进度

- 设计：[持久层职责精简](../designs/hermes-db-persistence-scope.md)；映射：[生产文件/接口/测试/锚点](../designs/hermes-db-persistence-scope-map.json)。
- 实施分支：`refactor/hermes-db-persistence-scope`；隔离检出：`D:/AI/hermes-db-packages`。
- 源码基准：`90a2987e8c`；与正式启动`9a8093841b`仅部署记录文档不同。首轮准备提交`7f151a3299`不含运行代码。
- 整体状态：`IMPLEMENTING`；阶段：feature-development；当前实施任务：Task2；完成：1 / 9；阻塞：无。
- 日期：2026-11-10。本轮用户已授权按计划实施并逐Task本地commit；旧分包/规划证据不计为本轮实施。
- 准备依据：已核对22个生产路径、16项Store方法、22个相关测试文件及正常生命周期共享依赖；精确hash/处置在映射中。

## 目标、非目标与执行纪律

顶层`storage.backend`选择一种已实现持久层；业务存储合同一致，切换数据集不迁数据。退役repair-profiles、stranded adoption及专用搬移/修复方法，不创建外置维护产品。保留正常Profile生命周期、显式业务导入导出、session/Worker/调度恢复与文件安全回收。

0031要求、31个revision/29表模块（合计61个固定Python锚点，含versions初始化）和4项迁移资源按90a基准逐字节保持；不压平Alembic、不改历史SQL/算法、不清理持久票据或数据。配置、DTO、正常错误身份和Runtime合同不扩张。

1. 正式Hermes正在D:/AI/hermes-agent运行，只在独立checkout改代码；不能为方便测试切正式源码分支。先核对工作区与来源，保留用户修改。
2. PM/应用导入前绑定隔离HERMES_HOME/HERMES_RUNTIME_DIR；依赖只通过项目PM；现有lock/extras能满足时不改依赖、不使用raw pip/uv。
3. 测试只用scripts/run_tests.sh；PG仅核对归属的随机Schema。正式Profile/秘密/PG/SQLite数据不改，不管理服务、扩展、角色。
4. PG完整业务子进程拒绝全部SQLite连接；控制器切换数据集使用独立子进程，不能混跑后豁免。SQLite无PG依赖载荷必须实际读写/新PID重开。
5. 每Task同时更新直接/动态消费者、patch读取点及活动文档；不得把这些留给末尾才修。Task7是最终查漏，不是允许中间提交悬空引用。
6. 每Task通过匹配检查后立即更新计划、命令/退出码/计数/skip/未验证项/恢复点并本地commit；失败任务不计完成，后续依赖不能越过。
7. 不写source-reading或数量快照pytest；文件/签名/引用审计是单独工具，不能代替行为合同。退役用例需具名记录；混合测试只去掉退役部分。
8. 不保留旧内部re-export shim、兼容flag、反射代理、通用SQL/CRUD框架或无消费者的第三后端注册层。
9. 不推送、发布PR、合并/部署或重启正式服务。原统一后端Task24及七项非WSL平台缺证保持独立。

## 顺序与检查点

`T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9`。T2先解共享依赖；T3先取消自动adoption；T4再退役CLI与最后维护消费者；T5最后删授权生成并收敛正常业务模块。这样每个提交可独立运行，不用保留临时shim过渡。

| Task | 单一交付结果 | 必需依赖 |
| --- | --- | --- |
| 1 | 当前接口/行为/源码/测试环境基线及可复核恢复点 | 无 |
| 2 | 正常路由清理脱离repair所有者；既有授权读/回收安全合同 | 1 |
| 3 | 双后端及TUI不再自动承接错store会话 | 2 |
| 4 | repair-profiles整条功能及16项维护/兼容方法退役 | 3 |
| 5 | 删除跨store授权生成，剩余组件按真实业务职责收敛 | 4 |
| 6 | 顶层配置选择独立数据集、无隐式搬移/回落的多进程合同 | 5 |
| 7 | 全仓消费者/活动说明/边界审议表收口 | 6 |
| 8 | 冻结当前源码后的双后端、真实SDK、发行与故障恢复验收 | 7 |
| 9 | 独立审查、整改复验与本轮交付判定 | 8 |

## 标准命令与环境协议

下列是实施时的实际入口，不代表本次规划已经执行业务测试。Task1记录PM返回的Windows测试解释器、Linux测试解释器及extras；Task8通过pm.build_environment创建新source payload的独立环境，并把source/driver/python写入隔离payload.json。禁止硬套上一轮解释器、source归档或测试数字。

Windows从隔离checkout执行，PowerShell在任何Python/PM之前绑定：

```powershell
$env:HERMES_HOME = Join-Path $PWD '.build/persistence-scope/profile'
$env:HERMES_RUNTIME_DIR = Join-Path $PWD '.build/package-layout/runtime'
$env:PYTHONIOENCODING = 'utf-8'
$env:HERMES_TEST_FILE_RETRIES = '0'
$runner = 'D:/Programs/Git/bin/bash.exe'
$pgTestConfig = 'D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml'
# HERMES_PYTHON使用Task1由PM获得并记录的测试解释器，不使用正式运行解释器。
```

下列命令中的文件在对应Task创建或仍被保留时执行；退役文件不能继续留在组表。DB专用选项只传tests/hermes_db；CLI/TUI/gateway另组执行，避免前轮出现的option注册范围错误。每批完整原始输出只写隔离.build，工具仅输出安全Summary/失败节点和退出码。

```powershell
& $runner scripts/run_tests.sh tests/hermes_db -j 4 --file-timeout 1200 -- --tb=short
& $runner scripts/run_tests.sh tests/tui_gateway/test_session_resume_store_boundary.py tests/tui_gateway/test_session_resume_materializes_minted_key.py tests/tui_gateway/test_session_resume_db_ownership.py tests/gateway/test_bot_chat_follows_profile.py tests/gateway/test_session_resume_compression_tip.py -j 4 --file-timeout 1200 -- --tb=short
& $runner scripts/run_tests.sh tests/hermes_cli/test_sessions_command_boundary.py tests/hermes_cli/test_db_setup.py tests/hermes_cli/test_profiles.py tests/hermes_cli/test_profile_identity_purge_cmd.py tests/gateway/test_profile_identity_purge.py -j 4 --file-timeout 1200 -- --tb=short
& $env:HERMES_PYTHON scripts/check --staged --base 90a2987e8c
& $env:HERMES_PYTHON scripts/boundary_lint.py --check
& $env:HERMES_PYTHON scripts/gen_gateway_contracts.py --check
git diff --cached --check
```

真实Linux/PG由适用主机执行同一标准runner，cwd为Task8冻结的独立test-driver，source与driver不同。以下变量由Task8的payload.json绑定为实际PM路径；执行记录必须展开而非保留变量：

```bash
HERMES_PYTHON="$pg_python" bash scripts/run_tests.sh tests/hermes_db/postgresql -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source="$source" --hermes-postgresql-python="$pg_python" --hermes-sqlite-python="$sqlite_matrix_python"
HERMES_PYTHON="$pg_python" bash scripts/run_tests.sh tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/test_distribution_initialization.py -j 2 --file-timeout 1200 -- -m 'integration or not integration' --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source="$source" --hermes-postgresql-python="$pg_python" --hermes-sqlite-python="$sqlite_matrix_python"
```

SQLite纯载荷另以不含PG/Matrix的PM环境执行其普通业务与新PID合同；Matrix载荷单独验证实际SDK。上述发行参数须对应当时源码的conftest/协议，Task1核对实际支持；发生差异先更新计划。控制进程可以协调两种子环境，PG业务子进程不能导入/连接SQLite。

## Task 1：冻结当前合同、实施源与隔离环境

状态：completed

### 目标

取得本轮可比较的行为、源码和接口基线，避免把上一轮成功当精简后的证据。

### 涉及文件

映射中的22个生产文件、tests/hermes_db/conftest.py、tests/AGENTS.md、PM入口；计划/映射及隔离.build基线记录。

### 依赖与接口

无前置；输出当前全部Store方法签名/DTO身份、16项计划退役集合、365模块/root11、61+4锚点、测试收集与PM环境manifest，供所有后续任务比较。

### 实施步骤

1. 核对正式与隔离HEAD/dirty，读涉及目录AGENTS，确认正式进程不引用隔离路径；不覆盖新用户修改。
2. 校验映射SHA与实际Git blob、直接/动态/getattr及测试patch消费者。签名基线明确区分内部组合构造和业务方法；未来只允许16项明确取消，其余保持。
3. 绑定隔离目录，由项目PM准备/验证dev/test、postgresql/messaging/matrix声明依赖与适用Linux SDK环境；记录真实Python/SDK路径和版本，不复制正式环境。
4. 标准runner运行现有test_profile_moves、test_profile_repair、test_remaining_read_maintenance及相关TUI/CLI现状用例；真实PG小组选health_archive_refs、profile_file_scope、review_foundation_profile_delete，验证环境和正常保护合同。
5. 记录当前用例ID与已知基准问题；确属基准失败时对同源码复现并登记，不冒称完成、也不通过删除断言掩盖。

### 验证方式

标准命令协议下按上述明确文件分组执行，DB Native与CLI/TUI分开、PG加-m integration与私有配置路径。基准源/签名/锚点操作审计exit0；适用行为组exit0，所有skip具名。

### 完成条件

本轮实际基线和恢复commit可复核；必需PM/PG/SDK环境可用或被准确阻塞，未改正式运行数据。

### 执行结果

本轮基于f9b777f9c0重新核对：隔离分支正确、两个checkout干净，正式HEAD90a2987e8c；运行代码与基准无差异。进程只读探针未发现既有进程引用隔离checkout（探针自身排除），未停止/修改任何进程。

独立PM环境已实际重新探测：Windows Python3.14.9 dev/test+postgresql/telegram/discord；Linux Python3.14.9 dev/test+postgresql/matrix/telegram/discord，mautrix0.21.1、python-olm3.2.16，实际CryptoStore非抽象且加载隔离源码。PG17.11独立验收DB归属、pg_trgm就绪。沿用已由项目PM创建的开发测试环境，不复制或修改正式环境；Task8仍须创建冻结源码的新发行载荷。

`.build/persistence-scope/task1-baseline.json`保存295项PostgresSessionStore签名、224个类方法合同、消费者候选（含字符串/getattr路径）、22文件测试节点和61+4锚点；365个DB Python/root11。映射22文件Git blob与工作树规范blob完全一致，无基准影响需要修订。

### 验证证据

命令均在D:/AI/hermes-db-packages执行；PM/应用之前已绑定隔离HOME/RUNTIME，retries=0。原始日志仅留隔离.build，未提交秘密/原始堆栈。

- `D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe .build/persistence-scope/validate_scope_plan.py`：exit0，22路径/16方法/61锚点/4资源/365模块/root11匹配。
- 同解释器执行`.build/persistence-scope/task1_audit.py`：exit0，源码/接口审计PASS。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts/test_profile_moves.py tests/hermes_db/contracts/test_profile_repair.py tests/hermes_db/contracts/test_remaining_read_maintenance.py -j 2 --file-timeout 1200 -- --tb=short -ra`：exit0，27passed/0failed/0skip；日志`task1-native.log`。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/tui_gateway/test_stranded_session_adoption.py tests/tui_gateway/test_session_resume_materializes_minted_key.py tests/tui_gateway/test_session_resume_db_ownership.py tests/hermes_cli/test_sessions_repair_profiles.py -j 2 --file-timeout 1200 -- --tb=short -ra`：exit0，51passed/0failed/0skip；日志`task1-consumers.log`。
- `wsl.exe -d Ubuntu-26.04 --cd /mnt/d/AI/hermes-db-packages -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/persistence-scope-profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime HERMES_PYTHON=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/test-env/bin/python HERMES_TEST_FILE_RETRIES=0 PYTHONDONTWRITEBYTECODE=1 bash scripts/run_tests.sh tests/hermes_db/postgresql/test_health_archive_refs.py tests/hermes_db/postgresql/test_profile_file_scope.py tests/hermes_db/postgresql/test_review_foundation_profile_delete.py -j 2 --file-timeout 1200 -- --tb=short -ra -m integration --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`：exit0，43passed/0failed/0skip；日志`task1-pg.log`。
- `wsl.exe -d Ubuntu-26.04 --cd /mnt/d/AI/hermes-db-packages -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/persistence-scope-profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime PYTHONDONTWRITEBYTECODE=1 /var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/test-env/bin/python .build/package-layout/linux_probe.py`：exit0；安全事实见task1-linux-probe.json。

未验证：完整双后端/发行/新PID切换/最终SDK行为在后续Task执行；本Task没有生产代码变动，不把SDK协议探针当SDK业务通过。原统一Task24/七项非WSL缺证保持独立。恢复点为本Task本地commit，下一Task2。

## Task 2：先解正常Profile生命周期与既有授权的共享依赖

状态：pending

### 目标

使正常Profile删除/文件回收不再依赖即将删除的修复实现，建立删代码前的保护合同。

### 涉及文件

hermes_db/domains/sessions/postgres/queries/gateway.py、integration/postgres/operations/profile_repair.py、profile_purge.py、integration/transfer/session_store.py；新建contracts/test_existing_media_grants.py及postgresql/test_existing_media_grants.py。

### 依赖与接口

前置Task1；delete_routes的实际定义归现有gateway SQL模块，同Connection/scope/锁及retirement调用；当前CLI修复暂仍可通过更新后的真实读取点工作。

### 实施步骤

1. 先补既有有效授权数据的普通读取/pin/释放合同，在临时store直接准备持久记录；不依赖旧mover创建测试前提。
2. 将delete_routes唯一实际定义移至gateway.py，修复模块不re-export；同步profile_purge、SessionTransfer.delete_gateway_routing_rows及所有测试读取点。
3. 保留原店内锁、共享路由墓碑、pending投递与其他Profile隔离；不重写算法或SQL。
4. 运行当前修复功能尚存时的相关合同，确保此提交只有解耦、没有提前取消入口。同步导入/活动说明与计划。

### 验证方式

标准runner：test_remaining_read_maintenance.py、test_profile_repair.py、test_retired_files.py和新增既有授权合同；真实PG health_archive_refs、review_foundation_profile_delete、profile_file_scope和新授权组；外目录Profile purge两文件单独执行。

### 完成条件

正常Profile删除只依赖正常SQL所有者；既有授权读/回收合同在两后端实际适用路径通过，旧CLI仍可运行，未留shim。

### 执行结果

未实施。

### 验证证据

未执行；记录真实行/文件结果，不用函数存在性断言。

## Task 3：取消恢复时的历史stranded adoption

状态：pending

### 目标

普通session.resume不再从另一Profile承接、复制或退休旧数据，正常恢复保持。

### 涉及文件

tui_gateway/methods_session.py、hermes_state_portability.py、PG store/SessionTransfer、integration/postgres/operations/adoption.py；test_stranded_session_adoption.py替换为test_session_resume_store_boundary.py；相关import flags和gateway混合测试。

### 依赖与接口

前置Task2；取消adopt_session_lineage_from、SQLite _retire_donor_segment及TUI _resume_adopt_stranded；其余15项CLI维护方法暂留，直到Task4整条退役。

### 实施步骤

1. 增加一个在基准上先失败的行为用例：非minted、非live的目标只存在另一store，当前Profile resume按原不存在结果拒绝，双方会话、消息、归档状态不变；验证没有donor读取/承接。
2. 移除自动分支、双后端adoption方法和专用PG模块；保留live-lazy、minted-key、owned-store title/id、压缩tip及handle释放分支。
3. 混合用例逐项拆分：保留普通import的inactive/checkpoint/deleted-parent合同；本Task即移除test_profile_repair.py、test_review_data_safety.py中的adoption专用用例及health_archive_refs聚合表的对应条目，不能等Task4才让测试恢复。正常路由测试若用adoption准备前提，改为直接准备目标store中的有效数据，保留路由断言。
4. move_values/profile_move及file_grants.transfer仍被CLI使用，本Task不得顺手删除。同步动态引用、patch、活动文档。

### 验证方式

标准runner执行新resume边界、minted-key、db_ownership、bot_chat_follows_profile、legacy_session_route_turn及session_resume_compression_tip；DB修复/普通import/隔离合同与真实PG health_archive_refs复验。基准red→当前green与消息/归档状态均记录。

### 完成条件

历史承接合同取消；不因当前数据缺失跨store搬移。正常真实恢复不退化，CLI尚存路径无悬空引用。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 4：整条退役repair-profiles与双后端专用维护方法

状态：pending

### 目标

取消旧修复产品入口和其最后数据库消费者，实际移除专用实现。

### 涉及文件

CLI parser/dispatch与2个repair文件；hermes_state.py及hermes_state_profile_repair.py；PG store/SessionTransfer及profile_move/repair operations/queries、move_values；映射中的退役/混合测试和对应活动文档。

### 依赖与接口

前置Task3；取消剩余15项维护方法，使计划累计16项Store方法退役；普通Session/Runtime合同、正常Profile purge不变。

### 实施步骤

1. 删除repair-profiles parser、handler import/dispatch及两文件，不保留deprecated命令或兼容flag；标准未知子命令拒绝发生在存储打开/写入前。
2. 删除SQLite SessionProfileRepairMixin的import/基类与专用文件；核对helper/异常无其他业务消费者；不把纯业务定义一同删掉。
3. 删除5个剩余DB专用模块及对应Store/组件方法，清理无用注入/导入。只读保留旧持久票据，不触发数据清扫。
4. 专用move/repair/digest测试按清单退役；混合file_consumers保留roster/stats/资源释放/backup；review_data_safety保留prepared compression；health_archive_refs保留health/retention/archive旧升级/purge/concurrency及正常授权合同，修正参数表/导入。
5. 新CLI边界用例验证退役命令无存储副作用及正常sessions命令仍分发，不能仅断言help缺一个字符串；同步CLI用户指南、引用锚点及skills。

### 验证方式

标准runner对保留的DB混合文件、当前Profile/普通import合同、正常CLI与新命令边界执行；真实PG health_archive_refs及Profile purge/文件scope组通过。操作审计验证恰好取消计划方法、其他业务签名不变、无残留生产/动态入口。

### 完成条件

命令和双后端维护能力完整退役，无AttributeError悬空；正常功能不靠删除断言变绿，所有取消用例有明确功能理由。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 5：移除跨store授权生成并收敛剩余组件

状态：pending

### 目标

去掉维护退出后的死代码，使剩余模块只承载真实业务持久化与生命周期。

### 涉及文件

file_grants.py→integration/media_grants.py；profile_purge.py→integration/profile_lifecycle.py；transfer/session_store.py→integration/session_portability.py；session_composition、media_retirement、store及实际消费者/patch/文档。

### 依赖与接口

前置Task4；保留既有授权的received/origin/lock/remaining/release行为，业务导入导出由SessionPortability继续承载，不再创建搬移票据。

### 实施步骤

1. 核对transfer/_grant/_texts/_mentioned/_known_media/_subset已无消费者，再删除它们；不得删除普通媒体/溢出文件读取和最后引用前的防误删检查。
2. 按映射迁移3个现有模块，SessionTransfer改为SessionPortability，同步实际构造/委托；不新增Facade自引用或通用service。
3. 既有授权fixture证明源/目标读、pin、最后引用、token/所有者与替换文件保护；授权不完整或状态不明时维持原显式拒绝/保留，不能为了清理而误删。
4. 验证普通会话/foreign import、导出、Profile rename/purge、路径重绑定与内容不重写；同步直接/动态/测试patch和文档。

### 验证方式

标准runner执行既有授权新合同、retired_files、native_file_boundaries、普通import/导出和Profile生命周期；tests/gateway/test_retired_media_ownership.py单独按外目录组运行；真实PG既有授权、profile_file_scope、health_archive_refs、review_foundation_profile_delete。记录365→实际模块数、root11和16项方法差异。

### 完成条件

至少净减6个DB模块、不超过359；3次改名不冒充净减少，16项方法已取消；剩余业务签名/身份保持，既有数据/授权仍安全。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 6：验证顶层后端选择与独立数据集语义

状态：pending

### 目标

把用户核心定位变成实际可执行的多进程合同，不只验证factory分支。

### 涉及文件

新增tests/hermes_db/test_backend_dataset_selection.py、postgresql/test_backend_dataset_selection.py及必要测试子进程载荷；复用实际配置写入/解析、factory、scope和单后端SQLite拒绝设施。

### 依赖与接口

前置Task5；正常配置、领域API和错误合同不新增；若既有实现已满足行为则仅加有意义的端到端验证，不为测试引入新生产接口。

### 实施步骤

1. 控制器用临时Profile及PM独立载荷：SQLite进程写A；同Profile配置选PG，新进程只见PG数据、看不到A并写B；切回SQLite只见A；新PG进程恢复B，scope身份不混用。
2. 每次配置选择在新进程/新会话完成，不热换运行会话缓存前缀。PG业务子进程全程拒绝全部SQLite连接；普通SQLite环境不含PG依赖。
3. 在可归属的临时目标上验证PG未就绪/不可用/配置错误显式失败，未生成/打开本地SQLite；不停止数据库服务或修改角色制造错误。
4. 执行既有参数化正常业务合同，不增加为未来后端服务的注册框架、SQL翻译、数据迁移或新HERMES行为环境变量。

### 验证方式

标准runner执行两新增文件、test_factory.py、test_optional_dependencies.py、contracts/test_single_backend.py及真实PG test_single_backend.py。DB option只用于DB组；真实新PID、实际记录标记、0 SQLite attempts与无PG依赖事实进入结果。

### 完成条件

顶层选择真实生效，数据集互相独立且可持久恢复；拒绝路径不读另一库或回落。不是mock配置枚举或纯导入检查。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 7：全仓消费者、文档与边界闭合

状态：pending

### 目标

关闭各Task局部同步后的遗漏，确保新定位贯穿实际入口与活动说明。

### 涉及文件

scripts/hermes_db_boundary_rules.json、受影响真实consumer；website/docs/user-guide/sessions.md、reference/cli-commands.md、对应developer-guide/skills/AGENTS；本轮映射和计划。

### 依赖与接口

前置Task6；原plugin_api.json和插件边界计数不扩张；旧设计/基准/处置清单可保留历史名字，但不能留下可执行旧命令指南。

### 实施步骤

1. 全仓直接/from-parent/getattr/importlib/字符串分发表及patch读取点核对，不止grep显式import。
2. 删除已退役symbol的DB边界许可；模块改名按consumer+symbol精确调整，不重刷全量baseline掩盖新耦合；纯共享/SQLite桥接等剩余例外仍逐项说明。
3. 活跃指南说明统一backend、独立数据集、功能退役及Schema生命周期；修复交叉链接。历史18项账本/冻结基准不倒写成当前通过。
4. 验证无新通用框架、配置键、工具、Schema变更或旧内部shim；本轮方法/文件/测试退役清单逐项结算。

### 验证方式

PM解释器执行scripts/check --staged --base 90a2987e8c、boundary_lint.py --check、gen_gateway_contracts.py --check与git diff --cached --check；标准runner执行tests/scripts/test_hermes_db_boundary_lint.py及必要实际消费者组。测试中禁止读取源文本做断言。

### 完成条件

静态/边界门禁通过，无未处置调用/活动指南；所有结构数字、退役测试和共享符号有可审议理由。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 8：冻结当前源码并执行完整双后端/发行/SDK验收

状态：pending

### 目标

在精简后的真实源码和独立安装载荷上取得最终完整命令exit0。

### 涉及文件

本轮冻结/manifest记录，当前tests/hermes_db Native/PG、受影响CLI/TUI/gateway组、发行/SDK及新数据集合同；需要实际修复时涉及的生产文件另记。

### 依赖与接口

前置Task7；全部退役已闭合，当前source/driver/testhash绑定。旧720 PG、633/628 Native、31 Matrix不作为当前成功证据或必须凑齐的数量。

### 实施步骤

1. Git冻结当前源码/测试及活动生成资源，导出独立无.git source和独立driver，记录hash；PM从该源新建纯SQLite、PG+messaging+matrix及SQLite+Matrix适用载荷，明确SDK extra与普通SQLite无PG依赖载荷分开。
2. Windows/Linux完整DB Native；CLI/TUI/gateway受影响文件另组；真实Linux完整PG目录，PG业务进程拒绝所有SQLite连接。记录实际收集、退役ID、通过/失败/skip，不用局部补跑替代完整命令exit0。
3. 实际Matrix SDK加密对象与PG读写/并发/关闭/新进程恢复；数据集切换合同与多scope持久化；实际COMMIT后丢ACK恢复，不能改成提交前模拟。
4. 独立发行组验证资源、普通SQLite独立运行、旧版本前向/重复升级及0031重开；61+4锚点逐字节保持，不以此次精简压平历史版本。PG所有操作只在fixture所属随机Schema。
5. 最终staged静态/生成契约/插件边界通过；若实际触及TS可执行代码或wire形状，按对应AGENTS跑构建/类型检查，不用Python绿替代；纯Python与描述范围不冒称全前端已验。

### 验证方式

使用本计划标准命令协议，并将manifest中实际路径、解释器、展开命令/退出码/安全Summary、skip理由写回本Task。每端payload对应当前hash，完整批次exit0且无未解释失败。

### 完成条件

当前代码的双后端、实SDK、发行/故障恢复与Schema证据完整；不是全仓所有测试执行声明，不覆盖原统一Task24/七平台缺证。

### 执行结果

未实施。

### 验证证据

未执行。

## Task 9：独立审查、整改复验与本轮交付

状态：pending

### 目标

按新持久层边界确认精简完成、正常能力保持，给出可合并状态。

### 涉及文件

本设计/计划/映射、新建docs/reviews/hermes-db-persistence-scope-review.md及审查整改实际文件。

### 依赖与接口

前置Task8；输入固定源码tip、完整diff与当前验收日志，输出APPROVED/CHANGES_REQUIRED与READY_TO_MERGE/BLOCKED/FAILED，不能拿旧分包审查代替。

### 实施步骤

1. 使用verification-before-completion逐声明绑定新证据；独立code-review覆盖需求、接口退役、正常生命周期/文件授权、scope/事务/SDK/恢复、测试删改质量和部署隔离。
2. 审查指明所有blocking/major/minor处置。代码有整改就重新冻结并复验受影响行为，必要时完整组复验；不凭口头报告批准。
3. 9项状态与最新证据齐全、无必需失败/阻塞、APPROVED后才标READY_TO_MERGE。逐Task本地commit/恢复点完整；不自动切换正式实例。

### 验证方式

读取完整diff、实际输出/退出码/skip、source/payloadhash及最终staged静态/空白结果；核对原Task24及七非WSL范围仍独立保留。

### 完成条件

新精简方案全部验收通过并独立APPROVED；正式数据/运行未受开发影响，当前实现与用户定位一致。

### 执行结果

未实施。

### 验证证据

未执行。

## 设计覆盖与最终验证

| 设计要求 | 任务 |
| --- | --- |
| 当前源码/方法/环境、精确处置与隔离 | 1 |
| 正常Profile purge、共享路由与旧授权保护 | 2、5 |
| 无自动跨store遗留承接，正常恢复保持 | 3 |
| CLI及双后端维护合同整体退役 | 4 |
| 实际模块/接口净减少、无shim或替代迁移工具 | 4、5、7 |
| 顶层backend选择、独立数据集、无回落 | 6、8 |
| 实际消费者/动态/patch/文档/边界 | 每项同步，7收口 |
| 双后端独立载荷、真实PG/SDK/恢复、Schema兼容 | 8 |
| 最新最终验证及独立审查/整改 | 9 |

### 最终执行命令

见前述标准命令协议及Task8 manifest展开记录。未来必须在本节写入最终实际源码/解释器、每个完整命令的退出码、通过/失败/skip与未验证范围；规划检查不占用业务验收计数。

### 当前执行结果

- 本轮Task1 completed，完成1/9：局部Native27、消费者51、真实PG43均exit0，无skip；完整验收仍待后续Task。
- 规划核对：映射22生产路径、16方法、22测试文件、6个拟新增行为测试文件及61锚点/4迁移资源已静态核对；方案文档/依赖/本地链接/基准hash和本轮staged检查的实际结果在准备记录补入。
- 正式目录保持90a2987e8c及已启动运行时代码，未停止、重启、改配置/秘密或接触业务数据库。

### 未通过项目与最终状态

尚未实施，业务验证和独立审查均待执行。本计划当前仅`PLAN_READY`，不能标READY_TO_MERGE。未来据实际证据填READY_TO_MERGE、BLOCKED或FAILED，并保留所有具名skip/初次失败与复验记录。

## 方案准备记录与恢复

`7f151a3299`为首轮准备，包含职责核对、A/B草案，未改运行代码；当时的1/7是调研检查点，不是精简实现完成。本次按用户“准备实施方案”将推荐A细化为22项生产路径、16方法和9个可验证实施Task，全部从pending开始。方案及映射只存在隔离分支，本轮只做规划验证和本地文档提交；开始实施从Task1继续，不重跑数据库选型，不覆盖旧18项分包/发布记录。


### 2026-11-10方案准备自检

- 隔离PM测试解释器在planning-home及既有隔离package-layout/runtime绑定后执行`.build/persistence-scope/validate_scope_plan.py`，exit0：22项生产路径Git blob hash、16项现有Store方法、22个相关测试、6个拟新增行为测试路径、9项全部pending及依赖无环、61锚点/4迁移资源、6个本地链接均通过；365个DB模块/root11基准与净减至少6的目标一致。该工具只用标准库/Git读取源码，没有导入应用或连接数据库。
- `PM Python scripts/check --staged --base 90a2987e8c`真实exit0，16项全通过，health为no measured files changed；日志`.build/persistence-scope/planning-check.log`。这是方案阶段静态证据，不是未来业务通过。
- 最后仅调整规划文字和测试分步处置元数据：明确Task3当即移除混合文件内adoption用例，Task4才移除余下move/repair用例；外目录gateway媒体测试单独运行。随后重跑方案一致性及暂存区空白检查，结果见本次文档提交。
- 只暂存设计、计划、映射三份docs文件；正式D:/AI/hermes-agent仍在90a2987e8c且clean，未触及运行进程、配置、秘密、数据库或业务文件。本轮没有执行业务测试、数据迁移或Schema升级。
- 本次准备完成后以本方案所在本地commit恢复；开始实施从Task1 in_progress及基准核对继续。最终发布和运行验收不属于此次准备动作。

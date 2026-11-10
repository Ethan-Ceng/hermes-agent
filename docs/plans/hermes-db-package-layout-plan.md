# hermes_db 分包与模块收敛实施计划

## 关联设计与当前进度

- 设计：[按业务域分包](../designs/hermes-db-package-layout.md)。
- 全量归属：[398项基准映射](../designs/hermes-db-package-map.json)。
- 文档分支：`docs/hermes-db-package-layout`；实施分支：`refactor/hermes-db-packages`。
- 源码基准：`cbfc773dd7`，运行实现等价`0d69702244`。
- 整体状态：`READY_TO_MERGE`（仅本次分包重构）；当前阶段：最终验证与独立审查完成；当前任务：无；完成：18 / 18。
- 本轮已在独立实施检出完成Task1–18并逐Task本地提交；未改正式源码/Profile/Schema/数据，未停止正式Hermes。
- 核心设计待决策：无；Task1隔离PM与PG基线已通过，Matrix实际SDK已由Task6新环境核对并实测。原统一后端Task24及七项非WSL缺证独立保留。
- 更新时间：2026-11-10（Asia/Shanghai）。交付位置：`D:/AI/hermes-db-packages`；全部任务已完成，恢复点见Task18最终完成记录，不重跑整轮数据库选型。

## 任务依赖与全局约束

Task1–10形成可独立检查点的机械迁移；11–16为规则/组件/工作流收敛；17为完整验证；18为独立审查及整改复验。编号为推荐顺序，真实前置见各Task；不要求并行或子Agent。
环境阻塞时保持该任务blocked，可继续依赖已满足的独立pending任务；不能越过依赖、跳过必需SDK或把blocked计为完成。功能失败先定位根因并记录受影响范围，依赖该行为的任务不得推进。
每项开始先改in_progress；完成后立即记录实际修改、命令、退出码、通过/失败/skip、未验证项、恢复点并本地commit。初始18项均pending；当前实施状态以每项状态及证据为准。

1. 在不被正式进程引用的独立checkout工作，普通Git分支即可，可选worktree/clone。新检出不得继承正式Profile的HERMES_HOME。
2. SQLite/PG配置、稳定store/Board/账号/房间身份、公开方法/DTO/错误及回执/序号/目标摘要保持；31个revision、29个表模块和0031要求保持。
3. 机械迁移任务不改变SQL或状态规则；随后结构调整分别验证。所有引用包含动态import、getattr路由、SDK factory、RPC和patch读取点。
4. 首阶段不批量移动测试文件，先保持已有合同文件及用例语义，仅更新真实patch/import点；新增必要行为测试按新域归属。禁止源码阅读/变更检测pytest。
5. core/domain/组合分层按设计实施；既有纯共享模块、Native桥接、历史迁移例外具名保留，运行时私有facade反向依赖最终关闭；不建万能utils、通用CRUD或反射代理。
6. PG测试仅从既有秘密路径读取配置，用fixture验证归属的随机Schema；不操作正式表、服务、扩展或角色；不打印DSN/密码/加密材料或提交.env。
7. 依赖只由PM管理；必需环境缺失准确blocked，继续不依赖它的工作，但不越过任务完成门禁。
8. 各测试批次按真实来源记录；早期686 PG/36专项/SDK32/Native503只为旧代码基线，不作新布局通过证据。Windows/Linux跳过与实际SDK结果分别记账。
9. 不推送、不发布、不创建PR、不合并到主线；正式运行切换不是本轮准备方案的动作。

## 验证命令约定

下列PowerShell函数只是计划中的调用约定，不新增测试框架。Task1把HERMES_PYTHON设为项目PM实际返回的dev/test解释器；实际SDK组还需PM声明的postgresql、telegram、discord、matrix extras和适用Linux环境。

```powershell
$testRunner = 'D:/Programs/Git/bin/bash.exe'
$pgTestConfig = 'D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml'
$env:HERMES_HOME = Join-Path $PWD '.build/package-layout/profile'
$env:HERMES_RUNTIME_DIR = Join-Path $PWD '.build/package-layout/runtime'
$env:HERMES_TEST_FILE_RETRIES = '0'
$BaseRev = 'cbfc773dd7'
function Invoke-NativeCases([string[]]$Files, [string]$Log) {
    & $testRunner scripts/run_tests.sh @Files -j 4 --file-timeout 1200 -- --tb=short *> $Log
    $result = $LASTEXITCODE
    Select-String -LiteralPath $Log -Pattern '^=== Summary' | ForEach-Object { $_.Line }
    if ($result -ne 0) { throw 'Native合同非零；查看本地脱敏诊断。' }
}
function Invoke-PgCases([string[]]$Files, [string]$Log) {
    & $testRunner scripts/run_tests.sh @Files -j 2 --file-timeout 1200 -- -m integration --tb=short "--postgres-test-config=$pgTestConfig" *> $Log
    $result = $LASTEXITCODE
    Select-String -LiteralPath $Log -Pattern '^=== Summary' | ForEach-Object { $_.Line }
    if ($result -ne 0) { throw 'PG合同非零；查看本地脱敏诊断。' }
}
```

PG选项只用于tests/hermes_db下已注册该选项的文件；其他目录Native批另跑。Linux同样经bash scripts/run_tests.sh与显式私有配置路径，不能伪装platform/is_wsl。原始日志放隔离检出的.build/package-layout/，不得把原始失败堆栈直接打印或提交。
每任务还执行`PM Python scripts/check --staged --base $BaseRev`及`git diff --check`；规划阶段检查不能冒充未来业务验证。

## 状态变更记录

| 日期 | 状态 | 记录 |
| --- | --- | --- |
| 2026-11-09 | PLAN_READY | 用户要求准备分包方案；完成实际模块归属与设计/计划，0/18，尚未实施 |
| 2026-11-09 | IMPLEMENTING | 独立checkout/PM及Task1接口依赖基线完成，1/18；Native504+PG26，4平台skip单列 |
| 2026-11-09 | IMPLEMENTING | Task2基础设施/组合40模块移动并验证，2/18；Native504、PG41、driver-free2、15静态全绿，4平台skip单列 |
| 2026-11-09 | IMPLEMENTING | Task3 Projects/verification六项移动并验证，3/18；Native/CLI513、PG7、15静态通过，4平台skip单列 |
| 2026-11-09 | IMPLEMENTING | Task4 Cron/metrics十六项及闭合动态路由验证，4/18；Native504、PG26、15静态通过，4平台skip单列 |
| 2026-11-09 | IMPLEMENTING | Task5 插件十项移动、两条既有边界路径精确迁移并验证，5/18；Native504、PG25、15静态通过；更正表模块计数文字口径 |
| 2026-11-09 | IMPLEMENTING | Task6 Matrix九项及真实Linux新PM SDK验证完成，6/18；SDK/完整PG32、Linux Native11、Windows Native504、最终15静态通过 |
| 2026-11-09 | IMPLEMENTING | Task7 Sessions九十项机械落位完成，7/18；Native516、PG121及15静态通过，组件收敛仍待Task12 |
| 2026-11-09 | IMPLEMENTING | Task8 Runtime/Worker五十二项机械落位完成，8/18；Windows Native504、Linux PG38及15静态通过 |
| 2026-11-09 | IMPLEMENTING | Task9 Rooms/附件三十九项与17-topic路由完成，9/18；根精确11，Native566+Linux附件24、PG40及15静态通过 |
| 2026-11-09 | IMPLEMENTING | Task10 Kanban五十八项与28-topic路由完成，10/18；全部320移动落实；Native536+Linux核心24、PG整改复验40、15静态通过 |
| 2026-11-09 | IMPLEMENTING | Task11八组合并与共享规则完成，11/18；462→444；Native513、PG失败整改后62、15静态通过 |
| 2026-11-10 | IMPLEMENTING | Task12 Session36 Mixin→六显式组件，12/18；444→419；Native整改复验560、PG160、15静态通过 |
| 2026-11-10 | IMPLEMENTING | Task13 Runtime10 Mixin→五显式组件，13/18；419→415；Native504、PG43及15静态通过 |
| 2026-11-10 | IMPLEMENTING | Task14 Kanban52→17工作流，14/18；415→378，净少于原398；Native536+Linux24、PG104及15静态通过 |
| 2026-11-10 | IMPLEMENTING | Task15 Room/附件32→九组，15/18；378→351；Native529+Linux附件24、PG109及15静态通过 |
| 2026-11-10 | IMPLEMENTING | Task16依赖/归属闭合，16/18；365模块、根11，Native618+Linux11、PG45、16项静态与插件边界通过；最终冻结验证待Task17 |
| 2026-11-10 | REVIEWING | Task17冻结源码/独立发行/完整Native与PG/实际SDK/升级恢复完成，17/18；所有初次失败已具名复验闭环，待独立审查 |
| 2026-11-10 | READY_TO_MERGE | Task18完整批次PG720、Linux Native584、Windows Native579/5平台skip均exit0；独立APPROVED、文档minor闭环，18/18，仅本次分包重构 |

## 方案准备自检

已用PM测试解释器执行`.build/hermes-db-package-design/validate.py`，exit0：398项源覆盖完整、320移动/76保留/2删除，目标无重复或文件/目录冲突；根目标11项，31个revision及29个表模块保持原位；18项均pending、依赖无环，Matrix环境阻塞不锁住独立Sessions任务；78个实际测试路径及本地文档链接存在；运行代码与cbfc基准无差异。
模块指纹使用基准Git blob的SHA256，不受检出换行差异影响。该检查只证明方案结构和引用，不是重构后的业务或独立代码审查结果。
PM解释器执行`scripts/check --staged --base cbfc773dd7`实际exit0、15检查通过、health为no measured files changed，日志`.build/hermes-db-package-design/checks.log`。暂存区空白检查通过；本轮没有执行或声称通过重构业务测试。

## Task 1：冻结模块/接口基线与建立隔离检出

状态：completed

### 目标

在正式进程不读取的独立检出建立普通refactor分支和隔离PM测试环境，冻结可比的源、接口与依赖台账。

### 涉及文件

- `docs/designs/hermes-db-package-map.json`。
- `hermes_db/`。
- `hermes_cli/data/plugin_api.json`。
- `scripts/boundary_lint_baseline.json`。
- `tests/hermes_db/`。

### 依赖与接口

前置：无；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 从文档提交建立独立checkout，实施分支refactor/hermes-db-packages；当前正式目录不改运行代码。先绑定隔离HERMES_HOME/HERMES_RUNTIME_DIR，再初始化PM。
2. 核对398项源hash；记录公共方法签名、DTO/异常类型、动态导入/patch字符串、Worker/SDK入口、持久化命令/资源摘要是否依赖模块名及跨域/反向依赖。
3. 单独冻结31个revision文件、29个表模块、配置键、逻辑DomainSpec及已知测试/平台缺口。引用686/36/SDK32仅作为同源基线，不能预记重构通过。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task1-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_surface_flow.py', 'tests/hermes_db/postgresql/test_merge_storage_contracts.py') -Log '.build/package-layout/task1-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

隔离位置/分支、PM返回解释器、模块与接口清单均已记录；没有未归属文件，动态/持久名称风险已明确，无正式Profile/进程副作用。

### 执行结果

已从规划提交建立 `D:/AI/hermes-db-packages` worktree、`refactor/hermes-db-packages` 普通分支，原目录干净且分支未切换。首次PM/应用导入前绑定本检出的 `.build/package-layout/profile` 与 `runtime`。PM从既有Python 3.14.9 bootstrap创建专用 `test-env`，dev/test及postgresql/telegram/discord extras构建exit0。没有修改既有环境或正式Profile。

新增 `scripts/hermes_db_layout_audit.py` 和两份历史JSON基线、具名依赖分类账本 `docs/designs/hermes-db-package-baseline.md`。398项Git blob全部匹配；359个公共定义模块、239个外部依赖拥有者、内部依赖、动态路由/patch/Worker入口、外部DTO/异常和配置注册值已冻结。31个revision、版本包init及29个表模块（含tables init）共61锚点，0031要求不变。基准两个提交只有文档差异，没有映射修订需要。

持久值核对：闭合JSON command/DTO kind、目标摘要和SDK Olm pickle不以hermes_db完整模块名作为反序列化地址；动态物理路径须在Task4/9/10更新，逻辑操作名保持。纯共享符号、Native桥接、历史迁移和待移除私有facade逐类登记，不扩大plugin API或全量重生成boundary baseline。

### 验证证据

实际测试解释器：`D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe`；源码 `7f5f1e74ed`，运行实现等价 `cbfc773dd7`。环境与所有原始日志只在本地 `.build/package-layout/`，不提交秘密或日志。

- PM：`bootstrap-python -m pm.build_env --source . --out .build/package-layout/test-env --group dev --group test --extra postgresql --extra telegram --extra discord`，exit0；初次SSL EOF经自动重试成功（pm-build.log）。
- `PM Python scripts/hermes_db_layout_audit.py`，exit0：398 hash全匹配，无未归属模块；脚本不导入应用。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，289.5秒（task1-native.log）。四项分别为domain_resources一个POSIX合同、matrix_close两个Linux SDK合同、single_backend一个Linux SDK合同，均不算通过。
- 同runner `tests/hermes_db/postgresql/test_surface_flow.py tests/hermes_db/postgresql/test_merge_storage_contracts.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，2文件26passed/0failed/0skip，74.9秒（task1-pg.log）。fixture验证独立验收DB及随机Schema所有权；非正式Schema。surface流程拒绝SQLite连接。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，最终exit0，15checks全部通过，health1文件0blocking/0advisory（task1-check-accepted.log）。首轮BOM读取/超时/blob超限均已整改；拆分台账保留全部记录。最终计划记录更新后 `git diff --cached --check` exit0。
- 未验证：重构后行为、独立无PG发行载荷、完整PG/SDK/升级/跨进程恢复均属后续任务，不以本Task基线代替。原统一后端Task24及非WSL七项缺证不变。
- 恢复点：本地提交 `1564c08225`，标题 `docs(storage): freeze hermes_db packaging implementation baseline`；下一任务Task2，先置in_progress再机械搬迁。

## Task 2：搬迁基础设施与组合桥接

状态：completed

### 目标

落位清单Task2的52项，建立11个根入口、core、backend及integration边界。

### 涉及文件

- `hermes_db/factory.py`。
- `hermes_db/access.py`。
- `hermes_db/integration/`。
- `hermes_db/core/`。
- `hermes_db/backends/`。
- `hermes_db/migrations/merge_data_repair.py`。

### 依赖与接口

前置：Task1；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射移动Engine/事务/SQLite获取及实际组合注册；root入口保留实际定义，不增加旧内部路径shim。
2. 同步所有直接/延迟导入、动态路径与patch点；迁移helper仅同步必要import，31个revision和表模块不改。
3. SQLAlchemy/psycopg/SDK仍仅在所选后端/能力入口加载；配置/secret/Profile绑定在组合边界，保持Native桥接。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task2-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_schema.py', 'tests/hermes_db/postgresql/test_domain_schema.py', 'tests/hermes_db/postgresql/test_sessions.py', 'tests/hermes_db/postgresql/test_surface_flow.py') -Log '.build/package-layout/task2-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

Task2映射均落实；SQLite driver-free入口及PG构造/作用域合同通过，未出现新Engine粒度或默认Profile读取。

### 执行结果

以Task1 `1564c08225`为起点，完成映射52项（40移动、12保留）。连接/事务/表达式移到backends/postgresql，Native桥接到backends/sqlite；值/目录能力/资源定义到core，具体registry/Profile活动/跨域维护到integration。同步生产消费者、延迟导入、测试读取/patch字符串与活跃开发文档；历史方案/执行记录和Task1冻结清单不重写。新增8个空父包初始化文件已逐项登记new_files，无旧路径re-export shim。

根Python文件113→90，总文件398→406（暂增8个必要包初始化；业务模块不增）。最终根11及净减少仍由后续分域/收敛任务实现，不能在本Task声称达到最终结构。398模块AST审计未发现导入与模块路径字符串以外逻辑漂移；31 revision和28表定义Git规范hash保持。tables/__init__.py只把catalog导入改为core.catalog，merge_data_repair.py只调整values导入，未改历史SQL、算法、DTO、错误、事务或池粒度。

正式checkout仍为规划分支且工作区干净；所有源码改动/测试在独立worktree，未操作正式配置或业务数据。

### 验证证据

沿用Task1专用PM解释器与隔离home/runtime，retries=0；下列日志仅在本检出的 `.build/package-layout/`。

- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，852.8秒（task2-native.log）。四项与Task1相同：1 POSIX、3 Linux SDK；没有把skip算通过。
- 同runner `tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_sessions.py tests/hermes_db/postgresql/test_surface_flow.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，4文件41passed/0failed/0skip，151.2秒（task2-pg.log）。独立DB/随机Schema归属fixture，surface进程SQLite拒绝护栏保留。
- 同runner `tests/hermes_db/test_optional_dependencies.py -j 1 --file-timeout 1200 -- --tb=short`，exit0，2passed/0failed/0skip，6.1秒（task2-optional.log）；真实子进程拒绝PG依赖导入仍完成SQLite会话/队列持久操作。
- 本地 `PM Python .build/package-layout/task2-audit.py`，最终exit0（task2-audit-accepted.log）：398模块机械AST等价、31 revision和28表定义hash不变。首轮审计工具对未存入object DB的新tables初始化blob执行cat-file失败；已修正为31+29锚点比较，初始化文件必要导入变化单列，不是业务失败。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health336文件0blocking/0advisory（task2-check-final.log）；最终映射/计划元数据更新后暂存空白检查exit0。
- 未验证：完整PG/实际Matrix SDK/发行及旧Schema业务升级由后续任务验收；本Task局部绿不解除Task17/18或原统一Task24缺证。表metadata身份与Schema保持原模块路径。
- 恢复点：本地提交 `ee2ea1130c`，标题 `refactor(storage): package database infrastructure and composition`；下一Task3，继续机械分包Projects/verification。

## Task 3：Projects与验证证据分包试点

状态：completed

### 目标

机械迁移两个小域，验证域内api/PG实现/查询落位和消费者更新流程。

### 涉及文件

- `hermes_db/domains/projects/`。
- `hermes_db/domains/verification/`。
- `hermes_cli/projects_db.py`。
- `agent/verification_evidence.py`。

### 依赖与接口

前置：Task2；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task3六项移动，同步装饰器/函数导入与真实消费者。
2. 保留规范化、重复目录、事务锁、查询排序及证据作用域算法；本任务不合并SQL逻辑。
3. 记录试点完整移动diff，作为后续域的操作样例。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_cli/test_projects_db.py', 'tests/hermes_cli/test_projects_cli.py') -Log '.build/package-layout/task3-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_projects_store.py', 'tests/hermes_db/postgresql/test_verification_store.py') -Log '.build/package-layout/task3-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

六项机械迁移完成，CLI与两个后端的真实持久化/隔离合同通过。

### 执行结果

从Task2 `ee2ea1130c`继续，将Projects与verification的api/operations/queries六项一对一移动到各自业务域。同步CLI装饰器、Agent验证证据入口、Worker领域handler及真实测试import/patch读取点；public DTO与异常仍由原定义模块提供，规范化/重复目录/排序/锁/SQL保持。Projects私有规则提取仍属Task11。

新增8个必要空初始化文件逐项进入new_files台账；当前16个新增均为空命名空间，总Python文件414、根90。398项机械AST等价，全部源/新增文件有归属；31 revision与28表定义不变。公开plugin_api与boundary baseline均未改；没有旧内部路径shim或SQL行为变更。历史设计/执行证据保持原基准路径。

### 验证证据

沿用Task1 PM解释器/隔离home/runtime，所有日志在本地 `.build/package-layout/`，retries=0。

- `PM Python .build/package-layout/audit_mechanical.py`，exit0（task3-audit.log）：398 AST机械等价、源/新增归属闭合、31 revision/28表定义保持。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_projects_db.py tests/hermes_cli/test_projects_cli.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件513passed/0failed/4skipped，276.8秒（task3-native.log）；skip仍为1 POSIX+3 Linux SDK，均未记通过。
- 同runner `tests/hermes_db/postgresql/test_projects_store.py tests/hermes_db/postgresql/test_verification_store.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，2文件7passed/0failed/0skip，22.0秒（task3-pg.log）；使用所有权核对随机Schema验证真实持久化与store隔离。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health349文件0blocking/0advisory（task3-check.log）；最终计划/映射状态更新后暂存空白检查exit0。
- 未验证：完整DB/SDK/独立发行/最终升级与组件收敛仍属后续，原Task24缺证不变。
- 恢复点：本地提交 `210831263e`，标题 `refactor(storage): package projects and verification domains`；下一Task4。

## Task 4：Cron与指标分包

状态：completed

### 目标

完成Cron四类持久操作与metrics资源/发送状态的域内机械归组。

### 涉及文件

- `hermes_db/domains/cron/`。
- `hermes_db/domains/metrics/`。
- `cron/`。
- `hermes_cli/observability/`。

### 依赖与接口

前置：Task3；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task4十六项移动，更新执行、incident、delivery、notepad与指标消费者。
2. 保留TTL/配额、claim、unknown/终态墓碑、consent及指标包去重语义。
3. 文件/HTTP发送继续位于事务之外，后台回调沿用捕获的Profile。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task4-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_cron_executions.py', 'tests/hermes_db/postgresql/test_cron_delivery_store.py', 'tests/hermes_db/postgresql/test_cron_notepad.py', 'tests/hermes_db/postgresql/test_cron_bot_delivery.py', 'tests/hermes_db/postgresql/test_metrics_store.py', 'tests/hermes_db/postgresql/test_metrics_http.py', 'tests/hermes_db/postgresql/test_metrics_process.py') -Log '.build/package-layout/task4-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

16项归位且实际Cron/metrics入口的持久化、发送状态和隔离通过，未禁用指标或调度功能。

### 执行结果

从Task3 `210831263e`继续，按映射机械移动Cron/metrics十六项，更新Cron四类消费者、metrics sender/snapshot/bound store、Worker指标路径及测试patch/import读取点。Cron原全局cron_{topic}拼接改为四项显式模块表（executions/incidents/delivery/notepad），仅在所选PG分支调用时导入；逻辑topic、原函数名、domain键及回执保持。无额外驱动启动依赖。

未改TTL/配额、claim/unknown/终态、consent/去重或时钟语义；文件/HTTP/等待仍在原事务外，Profile捕获不变。审计对Cron新表精确核对四个目标并将此唯一预期路由差异规范化后，398模块AST机械等价。31个revision和28个表定义保持，未改Schema/历史SQL。再增8个必要空初始化文件，全部入图；累计24个新增命名空间、总Python422、根87，业务模块未增加；最终净减少仍由阶段二验收。公开plugin API/boundary baseline未变化。

### 验证证据

沿用Task1隔离PM解释器/home/runtime，retries=0，本地日志根 `.build/package-layout/`。

- `PM Python .build/package-layout/audit_mechanical.py`，exit0（task4-audit.log）：精确Cron路由表规范化后398 AST机械等价、源/新增归属闭合，31 revisions/28表定义不变。没有以读取源码的pytest代替行为合同。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，547.6秒（task4-native.log）；skip仍为1 POSIX+3 Linux SDK，单列未算通过。
- 同runner `tests/hermes_db/postgresql/test_cron_executions.py tests/hermes_db/postgresql/test_cron_delivery_store.py tests/hermes_db/postgresql/test_cron_notepad.py tests/hermes_db/postgresql/test_cron_bot_delivery.py tests/hermes_db/postgresql/test_metrics_store.py tests/hermes_db/postgresql/test_metrics_http.py tests/hermes_db/postgresql/test_metrics_process.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，7文件26passed/0failed/0skip，103.1秒（task4-pg.log）；真实消费者、HTTP发送状态、独立进程恢复和store隔离使用有归属随机Schema。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health380文件0blocking/0advisory（task4-check.log）；计划/映射最终状态更新后暂存空白检查exit0。
- 未验证：实际Matrix SDK、独立发行、全量业务/旧Schema升级/最终组件收敛由后续任务验收，原Task24非WSL七项缺证保持。
- 恢复点：本地提交 `494b1a99c7`，标题 `refactor(storage): package cron and metrics domains`；下一Task5。

## Task 5：通用插件记录、Discord与Retain分包

状态：completed

### 目标

明确维护中插件持久化的域归属，保留公开插件面与真实恢复/队列协议。

### 涉及文件

- `hermes_db/domains/plugin_storage/records/`。
- `hermes_db/domains/plugin_storage/discord/`。
- `hermes_db/domains/plugin_storage/retain/`。
- `plugins/plugin_storage.py`。
- `plugins/platforms/discord/`。
- `plugins/memory/retaindb/`。

### 依赖与接口

前置：Task3；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task5十项移动并更新构造、composition和插件调用。
2. 不恢复core继承具体插件；公开API不新增hermes_db内部模块。
3. 保留CAS/ABA、总配额、scan keyset、Discord游标/恢复与Retain取消/COMMIT/关闭边界。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task5-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_plugin_storage.py', 'tests/hermes_db/postgresql/test_plugin_storage_process.py', 'tests/hermes_db/postgresql/test_discord_backfill.py', 'tests/hermes_db/postgresql/test_discord_recovery.py', 'tests/hermes_db/postgresql/test_retain_queue.py', 'tests/hermes_db/postgresql/test_retain_queue_transactions.py', 'tests/hermes_db/postgresql/test_retain_queue_worker.py') -Log '.build/package-layout/task5-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

十项落位，真实插件消费者与新进程恢复通过；无core→具体插件依赖和PG→SQLite回落。

### 执行结果

从Task4 `494b1a99c7`继续，按映射将records、Discord、Retain十项移动至domains/plugin_storage各业务包，更新插件真实factory/recovery/queue入口和全部测试读取点。保留公开PluginRecord/PluginStore/错误身份；没有core继承具体插件或PG向SQLite回落。

boundary baseline仅精确替换Retain PostgresWriteQueue及Discord PostgresDiscordRecoveryStore两条既有module路径，各计数仍为1；未运行全量baseline更新，plugin_api.json未变化。CAS/ABA、配额、scan、游标、队列取消/COMMIT/close均保留。新增11个空命名空间逐项归属，累计35个，总Python433、根84，业务模块不增。

398项机械等价，29表模块路径/metadata身份保持，其中28定义模块及31 revisions的内容不变。Task5发现并更正早期“29表定义”文字/审计打印标签：61个冻结锚点实际为31 revisions、versions init及29表模块（含tables init）；冻结JSON一直完整。tables init仅有Task2必要导入调整，详见本计划末尾更正说明，没有改Schema/历史SQL/算法。

### 验证证据

沿用Task1隔离PM解释器/home/runtime，retries=0，日志只在本地 `.build/package-layout/`。

- `PM Python .build/package-layout/audit_mechanical.py`，exit0（task5-audit-accepted.log）：398 AST机械等价、源/新增归属闭合；Cron既有四项路由表按Task4规则精确规范化。更正后的锚点计数标签如上，不修改历史日志或基准hash。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，294.3秒（task5-native.log）；1 POSIX+3 Linux SDK skip仍单列未算通过。
- 同runner `tests/hermes_db/postgresql/test_plugin_storage.py tests/hermes_db/postgresql/test_plugin_storage_process.py tests/hermes_db/postgresql/test_discord_backfill.py tests/hermes_db/postgresql/test_discord_recovery.py tests/hermes_db/postgresql/test_retain_queue.py tests/hermes_db/postgresql/test_retain_queue_transactions.py tests/hermes_db/postgresql/test_retain_queue_worker.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，7文件25passed/0failed/0skip，85.7秒（task5-pg.log）；真实PG持久读写、独立进程恢复、插件隔离和队列事务/关闭合同通过，均为所有权核对随机Schema。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health409文件0blocking/0advisory（task5-check.log）。最终计数说明及状态元数据更正后暂存空白检查exit0；运行源码未再变化。
- 未验证：Task6 Matrix实际SDK、最终发行/全量业务/旧Schema升级与组件收敛仍待后续；不以旧SDK32代替，原Task24缺证保持。
- 恢复点：本地提交 `0636043bb7`，标题 `refactor(storage): package records discord and retain storage`；下一Task6。

## Task 6：Matrix分包并验证真实SDK

状态：completed

### 目标

移动Matrix九项，实现文件归属清晰且实际SDK协议完全保持。

### 涉及文件

- `hermes_db/domains/plugin_storage/matrix/`。
- `plugins/platforms/matrix/`。

### 依赖与接口

前置：Task5；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task6移动，更新SDK延迟导入、factory与实际adapter。
2. 保留可变Olm对象身份、异步gate/事务顺序、generation、游标、fault传播和close。
3. 在适用Linux环境用PM准备实际SDK，执行Matrix及single_backend完整文件；Windows跳过不算通过。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task6-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_matrix_adapter_storage.py', 'tests/hermes_db/postgresql/test_matrix_close.py', 'tests/hermes_db/postgresql/test_matrix_crypto_store.py', 'tests/hermes_db/postgresql/test_matrix_devices.py', 'tests/hermes_db/postgresql/test_matrix_faults.py', 'tests/hermes_db/postgresql/test_matrix_recovery.py', 'tests/hermes_db/postgresql/test_matrix_sdk_concurrency.py', 'tests/hermes_db/postgresql/test_matrix_sdk_edges.py', 'tests/hermes_db/postgresql/test_matrix_sdk_flows.py', 'tests/hermes_db/postgresql/test_matrix_sessions.py', 'tests/hermes_db/postgresql/test_single_backend.py') -Log '.build/package-layout/task6-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

九项移动及实际SDK/PG加密读写、并发、故障、关闭、新进程恢复正向齐全；环境缺失则blocked。

### 执行结果

从Task5 `0636043bb7`继续，Matrix九项按清单移动到domains/plugin_storage/matrix，更新SDK factory/延迟导入、codec/cache/fault通道及实际adapter/测试读取点。boundary baseline仅精确迁移checkpoint与PostgresCryptoStore两条路径，原计数1/2保持；未扩展公开API，无旧路径shim。新增4个空初始化文件已入图，累计39个、总Python437、根79。398模块机械等价，29表模块路径/身份及31 revision保持；28表定义和版本文件规范内容不变，tables init仍只有Task2 import差异。

在已有Ubuntu-26.04 WSL2中绑定全新随机隔离根。旧临时SDK解释器已清理，改以系统/usr/bin/python3（3.14.4）bootstrap执行项目PM，从当前checkout锁文件新建dev/test+postgresql/matrix/telegram/discord环境；实际返回Python3.14.9、mautrix0.21.1、python-olm3.2.16。只读探针确认加载当前checkout、真实CryptoStore可实例化、独立验收DB/PG17.11/pg_trgm已就绪。未改变服务/扩展/角色/正式Profile。

真实SDK/PG覆盖加密对象身份、异步gate、事务/COMMIT故障、SDK吞异常后的checkpoint、close、账户/设备/游标及新进程恢复。single_backend完整文件包含全部SQLite连接（含内存/URI）拒绝护栏、双PID真实持久重开与跨store隔离。Windows跳过的4项由Linux三个完整Native文件正向执行。WSL的SDK证据不解除原统一Task24七项非WSL缺证。

### 验证证据

Windows沿用Task1专用环境；Linux解释器为 `/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/test-env/bin/python`，home/runtime位于同一隔离根。所有批次retries=0，原始日志仅在本检出的 `.build/package-layout/`。

- PM：WSL中绑定新home/runtime后 `python3 -m pm.build_env --source . --out /var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/test-env --group dev --group test --extra postgresql --extra matrix --extra telegram --extra discord`，exit0（task6-linux-pm.log）。既有临时解释器缺失探测非零，未安装前未计SDK通过；系统bootstrap与新PM环境成功。临时只读探针曾因scratch脚本导入根缺少tests非零，修正cwd导入根后exit0（task6-linux-probe.log），未改运行实现。
- `PM Python .build/package-layout/audit_mechanical.py` exit0（task6-audit-final.log），398 AST机械等价、源/新增归属完整、固定锚点保持。
- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，795.6秒（task6-native.log）。
- Linux使用上述新解释器，经 `bash scripts/run_tests.sh tests/hermes_db/contracts/test_domain_resources.py tests/hermes_db/contracts/test_matrix_close.py tests/hermes_db/contracts/test_single_backend.py -j 2 --file-timeout 1200 -- --tb=short`，exit0，3文件11passed/0failed/0skip，103.6秒（task6-native-linux.log）；覆盖Windows4项skip的真实宿主正向合同。
- Linux同runner完整文件：`tests/hermes_db/postgresql/test_matrix_adapter_storage.py tests/hermes_db/postgresql/test_matrix_close.py tests/hermes_db/postgresql/test_matrix_crypto_store.py tests/hermes_db/postgresql/test_matrix_devices.py tests/hermes_db/postgresql/test_matrix_faults.py tests/hermes_db/postgresql/test_matrix_recovery.py tests/hermes_db/postgresql/test_matrix_sdk_concurrency.py tests/hermes_db/postgresql/test_matrix_sdk_edges.py tests/hermes_db/postgresql/test_matrix_sdk_flows.py tests/hermes_db/postgresql/test_matrix_sessions.py tests/hermes_db/postgresql/test_single_backend.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，最终exit0，11文件32passed/0failed/0skip，124.3秒（task6-pg-linux-final.log）。首次109.4秒同样32passed；静态发现两个测试runtime别名冗余后改为from导入，并完整重跑以上11文件，而非复用旧基线32。随机Schema所有权fixture保持。
- 最终验证候选暂存树 `a13f743f028d3c61c7aef795942e83844aa1a3be`（随后仅更新完成记录/状态元数据）；Linux探针checkout_source=true。相同数字32是当前新运行的结果，不能与旧统一后端SDK32混用。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7` 最终exit0，15checks通过，health426文件0blocking/0advisory（task6-check-final.log）。初轮ruff两处PLR0402已整改；最终计划/映射状态更新后暂存空白检查exit0。
- 未验证：阶段二、完整DB/独立发行/旧Schema升级与最终审查仍属后续；Task24及非WSL七项缺证不变。
- 恢复点：本地提交 `e4b5146f9a`，标题 `refactor(storage): package matrix storage with real SDK verification`；下一Task7。

## Task 7：Sessions机械分包

状态：completed

### 目标

按清单搬迁90项会话相关模块，暂保原Mixin和算法，建立清晰移动检查点。

### 涉及文件

- `hermes_db/domains/sessions/`。
- `hermes_db/integration/transfer/`。
- `hermes_state.py`。
- `gateway/session_stored_reads.py`。
- `hermes_db/migrations/merge_data_repair.py`。

### 依赖与接口

前置：Task3；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task7移动Store、能力、操作、查询与codec；更新全部生产/测试读取点。
2. 涉及Profile portability的能力按映射落到integration临时检查点，阶段二再改为显式注入委托。
3. 保持Core SELECT、NUL/BYTEA、显示索引、edit revision、快照pin、旧PG补齐及操作回执，不顺便改查询行为。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_state/test_append_messages_batch.py', 'tests/hermes_state/test_compacted_message_reactions.py') -Log '.build/package-layout/task7-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_sessions.py', 'tests/hermes_db/postgresql/test_messages.py', 'tests/hermes_db/postgresql/test_search.py', 'tests/hermes_db/postgresql/test_retirement_rewrites.py', 'tests/hermes_db/postgresql/test_merge_storage_contracts.py', 'tests/hermes_db/postgresql/test_merge_data_upgrade.py') -Log '.build/package-layout/task7-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

90项归位且会话、分页/压缩、归档、旧数据升级合同通过；31个revision哈希未改。

### 执行结果

从Task6 `e4b5146f9a`继续，一对一搬迁Sessions九十项：store、36个能力类、操作、查询、codec及支持代码按域落位；四个Profile portability/move/repair能力按映射临时落到integration/transfer/session_capabilities。更新实际生产消费者、Runtime当前读取的会话查询、测试import/patch及迁移helper必要导入。保留现有Mixin/MRO、公开签名、存储方法和算法；显式组件仍由Task12完成。

398模块AST机械等价、全部原模块与新增文件有归属；无旧内部路径shim。新增7个必要空初始化文件已入图，累计46个，总Python444、根33；业务模块未增。Core SELECT、NUL/BYTEA、显示索引/edit revision、快照pin、metadata回执、canonical归档与旧PG补齐保持。31 revisions及版本包初始化/28表定义规范内容不变；全部29表模块锚点路径和metadata/表身份保持，tables init仅有Task2既有import调整。未改历史SQL/正式数据。活跃website/skills未找到遗留本Task完整旧路径，冻结历史证据保持旧基准说明。

### 验证证据

沿用Task1专用Windows PM解释器与隔离home/runtime，retries=0，日志在本地 `.build/package-layout/`。

- `PM Python .build/package-layout/audit_mechanical.py`，exit0（task7-audit.log）：398模块机械等价、所有源/新增归属完整、固定锚点保持；Cron已验证四项表按Task4规则规范化，无新行为例外。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_state/test_append_messages_batch.py tests/hermes_state/test_compacted_message_reactions.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件516passed/0failed/4skipped，277.7秒（task7-native.log）。四项平台skip单列；Task6的Linux局部证据不冒充未来最终全量验证。
- 同runner `tests/hermes_db/postgresql/test_sessions.py tests/hermes_db/postgresql/test_messages.py tests/hermes_db/postgresql/test_search.py tests/hermes_db/postgresql/test_retirement_rewrites.py tests/hermes_db/postgresql/test_merge_storage_contracts.py tests/hermes_db/postgresql/test_merge_data_upgrade.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，6文件121passed/0failed/0skip，369.6秒（task7-pg.log）；实际会话/消息/检索/归档/快照/旧数据前向修复在所有权核对随机Schema通过。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health516文件0blocking/0advisory（task7-check.log）；最终计划/映射状态元数据更新后暂存空白检查exit0。
- 未验证：组件收敛、最终全DB/SDK/独立发行/旧Schema完整验收仍待后续；本Task未移除36 Mixin，不计作Task12。原统一Task24及非WSL七项缺证不变。
- 恢复点：本地提交 `b5a2fcd7f2`，标题 `refactor(storage): package session persistence by domain`；下一Task8。

## Task 8：Runtime与Worker机械分包

状态：completed

### 目标

完成52项运行/准入/Worker持久化归组，保留owner-RPC执行边界。

### 涉及文件

- `hermes_db/domains/runtime/`。
- `agent/runtime_session_store.py`。
- `agent/runtime_domain_store.py`。
- `gateway/`。
- `tui_gateway/`。

### 依赖与接口

前置：Task7；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按映射Task8移动，更新Runtime facade、Worker handlers、后台/线程回调与RPC登记路径。
2. 保持epoch、admission FIFO、输入/内部事件receipt及Worker执行代次。
3. compute进程仍调用owner，不能因为新包名而改为子进程直连PG或SQLite。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task8-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_runtime.py', 'tests/hermes_db/postgresql/test_workers.py', 'tests/hermes_db/postgresql/test_worker_domain_receipts.py', 'tests/hermes_db/postgresql/test_worker_metrics_receipts.py', 'tests/hermes_db/postgresql/test_worker_retain_transport.py', 'tests/hermes_db/postgresql/test_merge_process_recovery.py') -Log '.build/package-layout/task8-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

52项归位，owner/Worker真实命令、新进程恢复与作用域拒绝通过，未降级成内存状态。

### 执行结果

从Task7 `b5a2fcd7f2`继续，Runtime/准入/Worker五十二项按映射落入runtime业务域；更新Gateway/CLI真实消费者、Worker handler导入/登记、后台/线程回调及测试patch读取点。epoch/FIFO、输入与内部事件回执、Worker generation及逻辑RPC命令保持；compute仍经owner，不增加直连PG/SQLite路径。10 Mixin与当前构造关系在机械阶段保留，Task13负责显式组件化。

398模块AST机械等价，源/新增模块归属完整；新增5个空初始化文件已入图，累计51个，总Python449、根16。固定31 revisions/版本包init/28表定义内容不变，29表模块路径和metadata身份保持；tables init仍只有Task2必要import调整。核对数据库层唯一__file__资源定位位于保留原位的schema.py，Alembic目录不漂移。活跃website/skills未发现本Task完整旧路径，插件API和boundary baseline未改。

### 验证证据

Windows沿用Task1专用PM环境；PG使用Task6新建Linux PM环境及同一隔离checkout当前源码，home/runtime分别显式绑定；retries=0，日志只在 `.build/package-layout/`。

- `PM Python .build/package-layout/audit_mechanical.py` exit0（task8-audit.log）：398 AST机械等价，固定锚点与所有源/新增文件归属通过。
- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，600.0秒（task8-native.log）。平台skip单列，不冒充本候选的最终Linux全量证据。
- Linux `HERMES_PYTHON=<Task6 PM返回解释器> bash scripts/run_tests.sh tests/hermes_db/postgresql/test_runtime.py tests/hermes_db/postgresql/test_workers.py tests/hermes_db/postgresql/test_worker_domain_receipts.py tests/hermes_db/postgresql/test_worker_metrics_receipts.py tests/hermes_db/postgresql/test_worker_retain_transport.py tests/hermes_db/postgresql/test_merge_process_recovery.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，6文件38passed/0failed/0skip，119.0秒（task8-pg-linux.log）。真实owner/Worker协议、主连接领域回执、指标/Retain transport、双进程恢复及scope拒绝在所有权随机Schema通过；没有把状态降级为内存。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health563文件0blocking/0advisory（task8-check.log）；最终计划/映射状态更新后暂存空白检查exit0。
- 未验证：10 Mixin显式收敛、最终完整DB/SDK/发行与升级仍待Task13/17；本Task Linux PG通过不解除原Task24七项非WSL缺证。
- 恢复点：本地提交 `d37a05a611`，标题 `refactor(storage): package runtime and worker persistence`；下一Task9。

## Task 9：Rooms与附件机械分包

状态：completed

### 目标

完成39项房间/附件模块和实际路由桥接归属。

### 涉及文件

- `hermes_db/domains/rooms/`。
- `hermes_db/integration/room_router.py`。
- `gateway/hosted_rooms.py`。
- `gateway/hosted_room_driver.py`。
- `tui_gateway/hosted_room_peer_http.py`。

### 依赖与接口

前置：Task8；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按Task9映射移动，显式处理room_operation动态模块选择和typed location。
2. 保留exact-grant、held/owed、receipt CAS、generation、member home、附件配额及文件token。
3. 使用真实HTTP/collector/supervisor和两个进程重开验证，禁止只测底层helper。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/gateway/test_hosted_room_attempt_home.py', 'tests/gateway/test_hosted_room_attachments.py', 'tests/tui_gateway/test_groups_methods.py') -Log '.build/package-layout/task9-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_rooms_store.py', 'tests/hermes_db/postgresql/test_room_runs.py', 'tests/hermes_db/postgresql/test_room_policy_process.py', 'tests/hermes_db/postgresql/test_room_attachment_service.py', 'tests/hermes_db/postgresql/test_room_attachment_concurrency.py', 'tests/hermes_db/postgresql/test_merge_collaboration_consumers.py', 'tests/hermes_db/postgresql/test_merge_commit_recovery.py', 'tests/hermes_db/postgresql/test_merge_process_recovery.py') -Log '.build/package-layout/task9-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

39项归位，真实房间消费者、债务付偿及附件持久化/隔离/恢复通过。

### 执行结果

从Task8 `d37a05a611`继续，房间/附件及路由桥接三十九项按映射落位；room_router归入integration，typed RoomStoreRef及scope/target校验保留。同步生产消费者/HTTP/driver/TUI读取点及测试import/patch。实际含别名登记核对17个topic、67处注册，全量映射到显式惰性_ROOM_MODULES；不再按旧全局operations.{topic}拼接，逻辑topic、原函数名/回执值不改。

398模块在精确核对Room模块表并规范化此预期路由差异后AST机械等价。exact-grant、held/owed、receipt CAS、generation、member home、附件配额/文件token及后台付债保持，没有新增事务或改SQL。再增8个空命名空间，累计59个、总Python457；根目录首次精确等于映射root_keep的11个实际定义/组合入口（113→11），无内部shim。文件总数净减少和36/10 Mixin收敛仍未完成，不能以根11冒充最终验收。

同步活跃开发文档的core/integration与领域SQL路径，设计状态改为引用实施账本，历史证据不重写。31 revisions/版本init/28表定义规范内容不变，29表模块路径/metadata身份保持；tables init仍仅有Task2 import差异。

### 验证证据

Windows使用Task1 PM环境、Linux使用Task6新环境；各自home/runtime绑定隔离路径，retries=0。日志均只在 `.build/package-layout/`。

- 路由别名扫描exit0（task9-alias-preflight.log）：17 topic/67注册均映射。最初辅助扫描因rg继承stdin且未显式给根返回1；改为显式仓库根和DEVNULL后重新核对全部别名，未改变生产逻辑。`PM Python .build/package-layout/audit_mechanical.py`最终exit0（task9-audit-final.log）：398 AST等价、源/新增归属、固定锚点通过。
- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/gateway/test_hosted_room_attempt_home.py tests/gateway/test_hosted_room_attachments.py tests/tui_gateway/test_groups_methods.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，93文件566passed/0failed/5skipped，298.6秒（task9-native.log）。原4项平台skip加附件1项symlink不可创建；均不计通过。
- Linux `bash scripts/run_tests.sh tests/gateway/test_hosted_room_attachments.py -j 1 --file-timeout 1200 -- --tb=short`，exit0，完整文件24passed/0failed/0skip，10.2秒（task9-attachments-native-linux.log）；新增Windows symlink缺证在真实Linux正向闭合，未伪造OS或改测试语义。
- Linux同runner `tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/test_room_runs.py tests/hermes_db/postgresql/test_room_policy_process.py tests/hermes_db/postgresql/test_room_attachment_service.py tests/hermes_db/postgresql/test_room_attachment_concurrency.py tests/hermes_db/postgresql/test_merge_collaboration_consumers.py tests/hermes_db/postgresql/test_merge_commit_recovery.py tests/hermes_db/postgresql/test_merge_process_recovery.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，8文件40passed/0failed/0skip，143.0秒（task9-pg-linux.log）；实际HTTP/collector/supervisor、债务及附件持久化、提交故障、双PID恢复与store隔离使用随机所有权Schema通过。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health624文件0blocking/0advisory（task9-check.log）；最终计划/映射状态元数据更新后暂存空白检查exit0。root_keep集合比较精确11。
- 未验证：Room工作流及私有门面依赖收敛仍由Task15/16；最终全量双后端/SDK/发行及升级仍待Task17。原Task24七项非WSL缺证保持。
- 恢复点：本地提交 `80d8a53e8b`，标题 `refactor(storage): package rooms attachments and routing`；下一Task10。

## Task 10：Kanban机械分包

状态：completed

### 目标

完成58项Kanban模块落位，消除全局kanban_文件堆及旧拼接导入路径。

### 涉及文件

- `hermes_db/domains/kanban/`。
- `hermes_cli/kanban_db.py`。
- `hermes_cli/kanban_db_notify.py`。
- `agent/kanban_turn_recovery.py`。
- `gateway/session_kanban.py`。

### 依赖与接口

前置：Task8；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按Task10映射移动，不改transition/命令/回执名或SQL规则。
2. 替换全局operations.kanban_{topic}路径构造；更新wire/DTO转换、实际Worker和通知消费者。
3. 保持Board/store隔离、附件引用、workspace tokens、lease以及副作用outbox。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_cli/test_kanban_core_functionality.py', 'tests/hermes_cli/test_kanban_cli.py') -Log '.build/package-layout/task10-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_kanban_tasks.py', 'tests/hermes_db/postgresql/test_kanban_dispatch.py', 'tests/hermes_db/postgresql/test_kanban_worker_e2e.py', 'tests/hermes_db/postgresql/test_kanban_notify.py', 'tests/hermes_db/postgresql/test_kanban_transfer.py', 'tests/hermes_db/postgresql/test_kanban_command_receipts.py', 'tests/hermes_db/postgresql/test_kanban_workspaces.py', 'tests/hermes_db/postgresql/test_kanban_integration.py') -Log '.build/package-layout/task10-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

58项机械落位、真实Kanban入口/Worker/通知/重放通过，没有旧物理路径动态分发或shim。

### 执行结果

从Task9 `80d8a53e8b`继续，将Kanban五十八项按清单机械落位；更新CLI/Worker/通知/文件/转移实际消费者及测试读取点。显式惰性_KANBAN_MODULES覆盖28个逻辑topic、111处真实注册，替代全局kanban_{topic}拼接；Board/store身份、命令/回执名、租约、workspace token及outbox保持。

映射修正：原kanban_import.py目标operations/import.py含Python关键字，首次辅助改写在kanban_transfer消费者解析时SyntaxError停止，尚未物理移动/运行测试。只恢复从干净Task9点产生的78个本轮部分改写，保留账本/诊断；将唯一目标改为operations/imports.py，源hash/归属/SQL不变。全部320个move目标已补验合法模块标识符，设计与JSONimplementation_amendments记录此修订，没有重做整轮方案。

第一轮PG发现一处子进程代码字符串遗漏旧分组导入，派发租约child在取得租约前ImportError退出。具体为test_kanban_dispatch.py的dead_dispatch_process_lease测试；历史4bd7861dfc确认其本意是持久租约死亡/接管。仅把子进程from hermes_db.operations import kanban_dispatch_lease改为实际新模块的dispatch_lease，保留leases绑定/LEASE_SECONDS及测试全部行为。现有实库合同提供修复前红；全仓同类operations/repositories/domains/postgresql/sqlite分组导入及旧动态导入扫描无其他遗漏，修复后完整八文件PG复验全绿。

398模块机械AST在精确校验三处路由表后等价；31 revisions/版本init/28表定义内容保持、29表模块路径/metadata身份保持，tables init仅Task2必要import差异。新增5个空初始化文件，累计64个、总Python462、root精确11；全部320移动已落实。仅两个空旧operations/repositories初始化文件按计划留Task16删除，无内部re-export shim。36/10 Mixin及薄碎片尚待阶段二；当前文件总数尚未净减少。

### 验证证据

Windows使用Task1专用PM环境；Linux使用Task6新PM环境，均绑定隔离home/runtime，retries=0；日志只在 `.build/package-layout/`，失败诊断先遮蔽既有DSN/密码/令牌后读取。

- `PM Python .build/package-layout/audit_mechanical.py` 最终exit0（task10-audit-final.log）：398 AST机械等价、全部源/新增归属和固定锚点通过；28-topic/111注册表精确核对。模块名关键字修正及本轮部分改写恢复清单仅本地诊断，原始秘密/日志未提交。
- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_kanban_core_functionality.py tests/hermes_cli/test_kanban_cli.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件536passed/0failed/6skipped，645.1秒（task10-native.log）。原4平台skip加核心文件2个Linux专用，均未算通过。
- Linux `bash scripts/run_tests.sh tests/hermes_cli/test_kanban_core_functionality.py -j 1 --file-timeout 1200 -- --tb=short`，exit0，完整文件24passed/0failed/0skip，31.4秒（task10-kanban-native-linux.log），真实Linux补齐zombie liveness及protocol-violation budget两个用例。
- Linux同runner `tests/hermes_db/postgresql/test_kanban_tasks.py tests/hermes_db/postgresql/test_kanban_dispatch.py tests/hermes_db/postgresql/test_kanban_worker_e2e.py tests/hermes_db/postgresql/test_kanban_notify.py tests/hermes_db/postgresql/test_kanban_transfer.py tests/hermes_db/postgresql/test_kanban_command_receipts.py tests/hermes_db/postgresql/test_kanban_workspaces.py tests/hermes_db/postgresql/test_kanban_integration.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，最终exit0，8文件40passed/0failed/0skip，274.1秒（task10-pg-linux-final.log）。第一轮226.1秒39passed/1failed（task10-pg-linux.log）是上述child旧导入；一行修复后含原回归用例的完整批次通过，没有更改租约期限或绕过真实Worker。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health690文件0blocking/0advisory（task10-check.log）；最终完成记录/映射元数据更新后暂存空白检查exit0。
- 未验证：第一阶段检查点不替代阶段二职责收敛、最终完整DB/SDK/独立发行/升级/审查；原统一Task24七项非WSL缺证仍独立保留。
- 恢复点：本地提交 `c0a4b50397`，标题 `refactor(storage): package kanban workflows and explicit routing`；下一Task11。

## Task 11：收敛小型域并提取共享纯规则

状态：completed

### 目标

以Projects为试点合并同域薄操作/查询，形成两后端共享规则的明确边界。

### 涉及文件

- `hermes_db/domains/projects/`。
- `hermes_db/domains/verification/`。
- `hermes_db/domains/cron/`。
- `hermes_db/domains/metrics/`。
- `hermes_db/domains/plugin_storage/records/`。
- `hermes_cli/projects_db.py`。

### 依赖与接口

前置：Task3、Task4、Task5；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 先提取Projects规范化/slug/path纯规则，两后端调用同一实现；保留公共DTO/异常身份。
2. 按设计合并确无独立职责的本域SQL/操作，不强制每域创建rules/repository/service全套文件。
3. 记录每次合并的前后数量和保留小模块理由；不改变SQL、事务及文件/网络等待边界。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_cli/test_projects_db.py', 'tests/hermes_cli/test_projects_cli.py') -Log '.build/package-layout/task11-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_projects_store.py', 'tests/hermes_db/postgresql/test_verification_store.py', 'tests/hermes_db/postgresql/test_cron_notepad.py', 'tests/hermes_db/postgresql/test_metrics_store.py', 'tests/hermes_db/postgresql/test_plugin_storage.py') -Log '.build/package-layout/task11-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

试点PG不再引用CLI私有规范化；两后端合同保持，至少有实际薄模块收敛并记录收益。

### 执行结果

从Task10 `c0a4b50397`继续，完成八个实际归组：Projects与verification各合并为单一postgres.py；Cron execution/incident/query归为executions，独立delivery/notepad保留；metrics counter/query归为records、consent/package/send-claim归为outbox；插件records协议实现与CAS/配额SQL合并。Projects四个纯slug/path规则移入rules.py，由Native和PG直接复用；公共DTO/异常身份保持。删除11个经核验为空的临时namespace，462→444个Python文件（业务模块净减7，namespace净减11），根仍精确11。映射记录final_target/八组合并沿革与移除namespace，398源项仍完整归属。

保留小模块理由：Cron delivery有独立durable claim/settlement，notepad有独立quota/write fence；metrics Store提供实际协议、sender包裹真实HTTP、snapshot提供实际跨域查询。Task16仍需关闭时钟/DTO转换、Native metrics格式化等私有facade耦合，本Task不宣称闭环。

首轮PG真实暴露Projects.create_project的folders参数与内联表别名遮蔽（2失败），改为明确的project_folders表名；对所有被内联的原模块属性进行局部绑定冲突扫描，仅发现这一处。原有两个失败合同作为本次red证据，整改后全16文件复验，不改公开folders参数或SQL。

### 验证证据

- Windows隔离PM Python3.14.9、Linux独立PM环境与Task6相同，均在导入前绑定隔离HERMES_HOME/HERMES_RUNTIME_DIR；源码来自独立checkout，不使用PM安装的旧拷贝。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_projects_db.py tests/hermes_cli/test_projects_cli.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件513passed/0failed/4skipped，327.0秒（task11-native.log）。1 POSIX及3 Linux SDK skip单列，最终Linux全量待Task17。
- Linux PG首轮误写两个测试文件名导致runner exit2、未执行任何业务；核对实际文件名后16文件exit1，60passed/2failed（均为上述folders遮蔽），221.6秒（task11-pg.log）。原始失败日志仅存忽略目录，不提交或打印秘密。
- 复验PG覆盖计划五文件以及Cron execution/delivery/bot、metrics consent/consumers/faults/HTTP/process、Discord恢复、Worker领域回执与metrics root共16文件；Linux最终命令为`bash scripts/run_tests.sh tests/hermes_db/postgresql/test_projects_store.py tests/hermes_db/postgresql/test_verification_store.py tests/hermes_db/postgresql/test_cron_notepad.py tests/hermes_db/postgresql/test_cron_executions.py tests/hermes_db/postgresql/test_cron_delivery_store.py tests/hermes_db/postgresql/test_cron_bot_delivery.py tests/hermes_db/postgresql/test_metrics_store.py tests/hermes_db/postgresql/test_metrics_consent.py tests/hermes_db/postgresql/test_metrics_consumers.py tests/hermes_db/postgresql/test_metrics_faults.py tests/hermes_db/postgresql/test_metrics_http.py tests/hermes_db/postgresql/test_metrics_process.py tests/hermes_db/postgresql/test_plugin_storage.py tests/hermes_db/postgresql/test_discord_recovery_faults.py tests/hermes_db/postgresql/test_worker_domain_receipts.py tests/hermes_db/postgresql/test_worker_metrics_root.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，16文件62passed/0failed/0skip，214.4秒（task11-pg-final.log）。
- 独立AST/绑定/归属审计：152个合并函数/类、4个共享规则等价；60个不可变文件内容相同（31revision + versions初始化 + 28表定义），tables初始化另仅保留Task2必要导入；总444、根11，398源项与所有新增项无缺失/无未登记文件（task11-audit-final.log exit0）。此核对不替代业务合同。
- 静态首轮15检查通过、health672文件0blocking/0advisory（156.7秒）；修复后的最终`PM Python -X utf8 scripts/check --staged --base cbfc773dd7` exit0、15检查通过，health672文件0blocking/0advisory（135.3秒，task11-check-final.log）；最终账本/映射状态更新后暂存空白检查通过。
- 未验证：大域组件收敛、最终全DB/SDK/独立发行/旧Schema仍由后续Task负责。原统一后端Task24及七项非WSL缺证独立保留。恢复点：本地提交`36c38d72fe`，标题`refactor(storage): consolidate small persistence domains and shared project rules`；下一Task12。

## Task 12：Sessions改显式组件并收敛碎片

状态：completed

### 目标

去除36基类组合，按目录/消息/历史/生命周期等实际能力形成显式委托。

### 涉及文件

- `hermes_db/domains/sessions/postgres/store.py`。
- `hermes_db/domains/sessions/postgres/`。
- `hermes_db/integration/registry.py`。
- `hermes_db/integration/transfer/`。
- `hermes_state_messages.py`。

### 依赖与接口

前置：Task8；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按设计合并单元制定最终落位和方法归属，保留现有公共存储方法签名/返回。
2. 引入单一Store上下文共享scope、事务、close状态与snapshot pin；具体跨域/Profile活动绑定由组合处提供，不把整个Facade当万能self。
3. 提取确需共享的持久化codec，去掉PG对Native存储Mixin的依赖；不把Agent业务格式化搬入DB。
4. 保留异步usage flush、主连接回执、metadata patch、canonical归档、refusal及old-PG补齐。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_state/test_get_messages_around.py', 'tests/hermes_state/test_get_messages_include_compacted.py') -Log '.build/package-layout/task12-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_sessions.py', 'tests/hermes_db/postgresql/test_messages.py', 'tests/hermes_db/postgresql/test_retirement_rewrites.py', 'tests/hermes_db/postgresql/test_search.py', 'tests/hermes_db/postgresql/test_merge_storage_contracts.py', 'tests/hermes_db/postgresql/test_merge_data_upgrade.py', 'tests/hermes_db/postgresql/test_transaction_failures.py') -Log '.build/package-layout/task12-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

36 Mixin组合移除，显式组件无万能反射导出；消息/快照并发/旧数据/unknown/关闭的真实证据齐全。

### 执行结果

从Task11 `36c38d72fe`继续，36个Session Mixin已收敛为catalog/messages/history/lifecycle/usage五个域内组件及integration/transfer/session_store.py一个跨Profile组件；PostgresSessionStore不继承业务Mixin，以显式方法委托，未引入__getattr__或万能代理。SessionContext唯一持有scope、事务、profile绑定、writer、close状态和线程snapshot pin；组合入口在integration/session_composition.py，真实构造消费者已更新。

Worker原来借用Session类的未绑定方法改为复用Connection/scope的lineage_reads窄查询。共享消息codec、覆盖证明、导入值校验、检索规则、标题/网关投影提取真实纯方法体，Native与PG使用同一实现；PG Session与transfer已无Native存储Mixin导入。rewind算法留在原应用所有者模块，以明确的读/写回调接入。移除38个旧能力/辅助文件和2个空namespace，新结构当前444→419文件、根仍11；映射记录每项final_target和六组件沿革。

首次Native批发现两处边界遗漏：Profile move unknown-ack测试仍patch旧Store._write，已改到context.write真实读取点；RuntimeMedia.release_media仍把Store传给接收Context的清理函数，已改为实际context，不给组件添加Facade代理。原有两个红例在完整Native复验中均已通过（9项Profile moves、1项media），最终整批已通过。公共门面288个方法参数/返回注解与descriptor已全部对照通过；补齐了session_gateway_runtime注解。新增PG断言验证同一snapshot内catalog消息计数与messages投影共享同一历史代际。

### 验证证据

- 环境仍为Task6已核验的Windows/Linux独立PM解释器；每批在应用导入前绑定隔离HERMES_HOME/HERMES_RUNTIME_DIR。未触碰正式checkout/Profile/秘密/业务数据或PG服务。
- 共享纯规则提取后，经项目runner运行SQLite九文件：append_messages_batch、compacted_message_reactions、composite_carrier_rewind、repaired_history_commit_coverage、search_or_relaxed_fallback、canonical_title_guard、message_uid、get_messages_include_compacted、get_messages_around，exit0，143passed/0failed/0skip，45.5秒（task12-pure-native.log）。这是中间代码证据，不冒充最终组件全量结果。
- 构造探针exit0：PostgresSessionStore仅object直接基类；六组件共享同一Context；构造期间拒绝一切事务仍可成功；close状态从false→true（task12-construction-probe.log）。独立静态名称绑定检查F821/F822/F823全通过。
- 公共门面AST审计：旧36基类的288个方法参数/返回注解与descriptor全部逐项对照、无差异（task12-public-signatures-final.log）；生成器在任何应用写入前已处理contextmanager显式委托协议（门面返回组件contextmanager，避免重复装饰）。
- Windows首轮`D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_state/test_get_messages_around.py tests/hermes_state/test_get_messages_include_compacted.py tests/hermes_db/test_usage_writer.py -j 4 --file-timeout 1200 -- --tb=short`，exit1，93文件558passed/2failed/4skip，380.0秒（task12-native.log）；2失败为上述真实边界遗漏。最终同命令exit0，93文件560passed/0failed/4skipped，955.2秒（task12-native-final.log）；4skip仍为1 POSIX与3 Linux SDK，均单列不算通过，最终宿主/SDK全量由Task17负责。
- Linux PG计划7文件加compression_leases，首轮exit0、8文件153passed/0failed/0skip，586.7秒（task12-pg.log）；此前一次误写不存在的worker_handler_surface路径导致runner exit2、未执行业务，核对实际文件后移除该错误路径。
- Linux最终`bash scripts/run_tests.sh tests/hermes_db/postgresql/test_sessions.py tests/hermes_db/postgresql/test_messages.py tests/hermes_db/postgresql/test_retirement_rewrites.py tests/hermes_db/postgresql/test_search.py tests/hermes_db/postgresql/test_merge_storage_contracts.py tests/hermes_db/postgresql/test_merge_data_upgrade.py tests/hermes_db/postgresql/test_transaction_failures.py tests/hermes_db/postgresql/test_compression_leases.py tests/hermes_db/postgresql/test_profile_file_scope.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0、9文件160passed/0failed/0skip，615.5秒（task12-pg-final.log）。PG随机Schema所有权由既有fixture验证，快照、并发回执、unknown、旧数据前向修复和真实Profile文件恢复均通过；未输出连接/密码/原始堆栈。
- 补充静态审计exit0：51个共享纯方法体AST完全等价；267个组件方法在Context/窄回调和导入归一后主体完全一致；11个窄查询/纯规则适配、4个真实共享算法委托和1个共享snapshot入口单列核对，未改SQL或锁/事务规则。398个基准源项完整归属；61个table/version文件相对Task11原样（含tables初始化），原基准只含Task2必要catalog导入差异；总419文件、根11（task12-audit.log、task12-component-semantics-final.log）。
- 最终`PM Python -X utf8 scripts/check --staged --base cbfc773dd7` exit0、15检查通过，health658文件0blocking/0advisory，198.3秒（task12-check-final.log）。首轮ruff两项多余括号及health三项已整改：恢复两条原有optional maintenance豁免注释，并具名记录既有optional persisted route解析的ambient fallback边界，保持原catch/恢复行为；不以改算法消除lint。首次收尾空白检查exit2指出coverage/search两个Native文件EOF空行；已去除多余末尾空行后复验整个Task12差异exit0，并修订本地提交。
- 恢复点：本地提交`e7439e9b20`，标题`refactor(storage): compose session persistence and share pure rules`；下一Task13。忽略目录保留生成/审计和原始日志，apply脚本非幂等、不得重复运行。
- 未验证：最终跨域/发行/SDK全量、Runtime10 Mixin、Kanban/Rooms工作流、最终发行/SDK/升级及独立审查；原统一Task24与七项非WSL缺证独立保留。

## Task 13：Runtime改显式组件与关闭所有权

状态：completed

### 目标

去除10 Mixin组合，按运行准入、local/history、权限和Worker生命周期组织。

### 涉及文件

- `hermes_db/domains/runtime/postgres/store.py`。
- `hermes_db/domains/runtime/postgres/`。
- `hermes_db/integration/registry.py`。

### 依赖与接口

前置：Task12；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 将policy/bot/viewer、local/history/recovery、Worker等按实际输入/状态归组并显式委托。
2. 复用Session/Runtime的拥有者上下文，保留同Connection receipt和epoch检查；组件不重复获取Engine。
3. 关闭/取消不丢持久意图，RPC方法/命令/序号与DTO保持。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts') -Log '.build/package-layout/task13-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_runtime.py', 'tests/hermes_db/postgresql/test_workers.py', 'tests/hermes_db/postgresql/test_worker_domain_receipts.py', 'tests/hermes_db/postgresql/test_worker_retain_transport.py', 'tests/hermes_db/postgresql/test_merge_commit_recovery.py', 'tests/hermes_db/postgresql/test_merge_process_recovery.py') -Log '.build/package-layout/task13-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

10 Mixin组合移除，owner/RPC/恢复/关闭合同通过且池预算和Profile绑定不退化。

### 执行结果

从Task12 `e7439e9b20`继续，将10个Runtime Mixin及原门面业务方法收敛到admissions/local/policy/workers/media五个明确组件，PostgresRuntimeStore改为显式82方法委托。RuntimeContext借用原SessionContext的read、scope、profile和关闭状态；write仍先激活所属Profile，再进入同一Session事务。AsyncDelegationStore改为接收RuntimeContext，并在原Connection内保持store fence；不向组件传完整Session/Runtime Facade，不创建新池。

内部构造消费者改用integration/runtime_composition.create_runtime_store；WorkerMetricsStore保留实际RPC协议职责、从临时capabilities落到runtime/postgres/metrics.py，Native metrics耦合仍由Task16关闭。移除10旧Mixin文件/1个迁移的metrics文件及1个空namespace，新增context/组合入口，419→415个Python文件、根仍11；映射覆盖全部398源项。原public方法、FIFO/epoch/receipt/Worker命令字符串未改。

9个测试文件的15处故障注入与单连接守卫改到实际Context.read/write读取点，同时更新原方法捕获，防止旧Facade patch静默失效或递归。更新器先保护性拒绝一个未列入白名单的实际runtime测试变量，核对PG fixture后补齐并完成；这不是业务失败或环境阻塞。候选apply非幂等，不得重复运行。当前合同与15项静态均已完成，不扩大为最终全系统验收。

### 验证证据

- 仍为Windows/Linux各自PM环境和隔离HERMES_HOME/HERMES_RUNTIME_DIR；本Task还用标准PYTHONPYCACHEPREFIX把两平台字节码缓存分别放到各自隔离runtime/pycache-tests，避免共享同一源码缓存，不改应用配置/依赖/数据库。
- 构造/关闭/签名探针exit0：旧10 Mixin→object直接基类，五组件和委托账本共享一个RuntimeContext，其session为原SessionContext；构造拒绝一切事务仍成功；关闭Session后Runtime读和delegations访问均抛原StorageClosedError；85方法参数和返回注解完全保持（task13-probe.log）。
- 独立AST审计exit0：82个方法经Context引用/导入归一后主体等价；61个table/version文件与Task12内容相同；398源项完整归属、当前415文件/根11（task13-audit.log）。F821/F822/F823和ruff均通过。
- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，750.1秒（task13-native.log）；1 POSIX与3 Linux SDK skip单列，不算通过。Runtime隔离、同连接回执、关闭/取消和故障注入合同保持。
- Linux `bash scripts/run_tests.sh tests/hermes_db/postgresql/test_runtime.py tests/hermes_db/postgresql/test_workers.py tests/hermes_db/postgresql/test_worker_domain_receipts.py tests/hermes_db/postgresql/test_worker_retain_transport.py tests/hermes_db/postgresql/test_merge_commit_recovery.py tests/hermes_db/postgresql/test_merge_process_recovery.py tests/hermes_db/postgresql/test_worker_metrics_receipts.py tests/hermes_db/postgresql/test_worker_retain_commands.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0、8文件43passed/0failed/0skip，126.5秒（task13-pg.log）；包含当前源码Worker序号/unknown/metrics/retain及新进程恢复，不复用旧686/36/32证据。Schema仍由fixture验证随机所有权。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0、15checks通过，health655文件0blocking/0advisory，142.2秒（task13-check.log）；没有新增豁免，沿用Task12具名边界。最终元数据更新后对整个Task13差异执行空白检查exit0。
- 恢复点：本地提交`683718050b`，标题`refactor(storage): compose runtime persistence with shared owner context`；下一Task14。忽略目录task13-virtual.json、生成/审计/patch脚本和日志保留；apply非幂等。
- 未验证：后续Kanban/Rooms合并、Task16依赖闭环、Task17最终DB/SDK/独立载荷与Task18独立审查。原统一后端Task24与七项非WSL缺证独立保留。

## Task 14：Kanban按工作流合并

状态：completed

### 目标

把48个操作及关联查询收敛到可定位的工作流模块，移除临时碎片目录。

### 涉及文件

- `hermes_db/domains/kanban/`。
- `hermes_db/integration/`。

### 依赖与接口

前置：Task10、Task13；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 依设计catalog/claims/review/completion/dispatch/runs/files/workspaces/notify/transfer/owners/maintenance/effects归组，先记录最终模块表。
2. 保持所有权、CAS、租约、回执/outbox在原事务内；文件锁、stage和hook等待仍在连接外。
3. 逐个实际consumer核对，更新patch生产读取点；保留公共wire/异常身份，不反向依赖CLI私有实现。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_cli/test_kanban_core_functionality.py', 'tests/hermes_cli/test_kanban_cli.py') -Log '.build/package-layout/task14-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_kanban_completion.py', 'tests/hermes_db/postgresql/test_kanban_review.py', 'tests/hermes_db/postgresql/test_kanban_worker_e2e.py', 'tests/hermes_db/postgresql/test_kanban_command_receipts.py', 'tests/hermes_db/postgresql/test_kanban_notify.py', 'tests/hermes_db/postgresql/test_kanban_transfer.py', 'tests/hermes_db/postgresql/test_kanban_sweeps.py', 'tests/hermes_db/postgresql/test_merge_collaboration_consumers.py') -Log '.build/package-layout/task14-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

最终工作流表与净减少数量明确，临时前缀碎片收敛；真实命令/文件生命周期/重放/通知合同通过。

### 执行结果

从Task13 `683718050b`继续核对52个Kanban操作/查询模块，先冻结实际归组表与111路由入口。初拟16个目标，写源码前的eager依赖图检查拒绝repository↔runs环：evidence依赖run读，而合并后的run操作依赖基础repository。将43行evidence保留为独立Connection/scope窄查询，调整为17目标，保持原52源项、基准hash和所有SQL/事务不变；不靠lazy循环导入或shim绕过。第二次eager图核对发现Catalog经reopen.invalidate/terminate依赖Completion，而Completion经graph._unsatisfied依赖Catalog；将共享的父节点/后代撤回与DAG同置Catalog，使Completion单向使用Catalog。仍为17目标，无新增算法/接口。17目标重验无环、48候选文件F821/F822/F823/自导入检查无误后已应用。52操作/查询→17实际工作流/共享能力，移除两空namespace，415→378文件；相对原398已净减20，根仍11。所有生产导入、显式分发、测试patch和内嵌子进程Python读取点同步迁移；源码未添加shim。



| 最终PG模块 | 源文件数 | 原始总行数 |
| --- | --- | --- |
| `catalog.py` | 10 | 953 |
| `claims.py` | 2 | 235 |
| `review.py` | 1 | 170 |
| `completion.py` | 4 | 319 |
| `dispatch.py` | 6 | 413 |
| `runs.py` | 3 | 240 |
| `files.py` | 5 | 590 |
| `workspaces.py` | 3 | 291 |
| `notify.py` | 1 | 199 |
| `transfer.py` | 4 | 513 |
| `owners.py` | 2 | 146 |
| `maintenance.py` | 6 | 432 |
| `effects.py` | 1 | 101 |
| `swarm.py` | 1 | 88 |
| `repository.py` | 1 | 105 |
| `evidence.py` | 1 | 43 |
| `receipts.py` | 1 | 58 |

保留小模块理由：evidence为跨工作流同Connection/run快照；receipts统一主效应/回执与commit verdict；effects是独立持久副作用生命周期；notify有独立游标/投递声明；swarm是独立原子拓扑创建。未强造通用CRUD或空repository/service接口。

### 验证证据

- 解释器、隔离HOME/RUNTIME和平台独立PYTHONPYCACHEPREFIX沿用Task13，未改PM依赖或生产配置；Node/Schema/服务/角色均未操作。
- 真实模块探针exit0：17个新模块在拒绝SQLite连接时成功导入；28个逻辑topic的111个现存注册函数逐一解析为callable，未改命令名（task14-probe.log、task14-routes.json）。
- 独立源级审计exit0：331函数/类与13常量在真实导入/导出身份归一后完全等价；无可变/调用型全局同名误合并；61个table/version锚点与Task13相同；398源项完整归属、378模块/根11（task14-audit.log、task14-semantics.json）。这不是行为pytest，也不替代业务测试。
- Native依计划92文件与扩大后的PG27文件均通过；命令清单如下。

```text
bash scripts/run_tests.sh tests/hermes_db/postgresql/test_kanban_artifacts.py tests/hermes_db/postgresql/test_kanban_audit_receipts.py tests/hermes_db/postgresql/test_kanban_board_files.py tests/hermes_db/postgresql/test_kanban_command_receipts.py tests/hermes_db/postgresql/test_kanban_completion.py tests/hermes_db/postgresql/test_kanban_dashboard.py tests/hermes_db/postgresql/test_kanban_dispatch.py tests/hermes_db/postgresql/test_kanban_failures.py tests/hermes_db/postgresql/test_kanban_integration.py tests/hermes_db/postgresql/test_kanban_interactive_process.py tests/hermes_db/postgresql/test_kanban_interactive_worker.py tests/hermes_db/postgresql/test_kanban_notify.py tests/hermes_db/postgresql/test_kanban_owner_policy.py tests/hermes_db/postgresql/test_kanban_owner_recovery.py tests/hermes_db/postgresql/test_kanban_review.py tests/hermes_db/postgresql/test_kanban_routing.py tests/hermes_db/postgresql/test_kanban_runs.py tests/hermes_db/postgresql/test_kanban_swarm.py tests/hermes_db/postgresql/test_kanban_sweeps.py tests/hermes_db/postgresql/test_kanban_tasks.py tests/hermes_db/postgresql/test_kanban_transfer.py tests/hermes_db/postgresql/test_kanban_watchers.py tests/hermes_db/postgresql/test_kanban_worker_e2e.py tests/hermes_db/postgresql/test_kanban_worker_rpc.py tests/hermes_db/postgresql/test_kanban_worker_upload.py tests/hermes_db/postgresql/test_kanban_workspaces.py tests/hermes_db/postgresql/test_merge_collaboration_consumers.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_kanban_core_functionality.py tests/hermes_cli/test_kanban_cli.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件536passed/0failed/6skipped，311.9秒（task14-native.log）。原4平台skip加core文件2个Linux专用，均未算通过。
- Linux `bash scripts/run_tests.sh tests/hermes_cli/test_kanban_core_functionality.py -j 1 --file-timeout 1200 -- --tb=short`，exit0，完整1文件24passed/0failed/0skip，86.3秒（task14-native-linux.log）；当前源码覆盖Windows的2个core跳过项，不覆盖原非WSL缺证。
- 上述完整PG27文件命令exit0，104passed/0failed/0skip，456.3秒（task14-pg.log）；所有Schema由fixture核对随机所有权，当前源码文件/Workspace生命周期、通知游标、Worker/RPC、命令/审计回执、dispatch租约、恢复与merge消费者均通过，无新DB服务/扩展/角色操作。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0、15checks通过，health618文件0blocking/0advisory，136.9秒（task14-check.log）；无新增豁免。最终元数据更新后整个Task14差异空白检查通过。
- 恢复点：本地提交`3857ae68ba`，标题`refactor(storage): consolidate kanban persistence by workflow`；下一Task15。忽略目录task14-virtual.json、groups、probe、audit、原始日志保留；apply非幂等。
- 未验证：Rooms合并、Task16依赖闭环、Task17最终全DB/SDK/独立载荷及Task18独立审查；原统一Task24与七项非WSL缺证独立保留。

## Task 15：Rooms按工作流合并

状态：completed

### 目标

收敛实际23个room操作、4个关联查询与5个附件metadata模块，保持任务/策略/债务和附件事务边界。

### 涉及文件

- `hermes_db/domains/rooms/`。
- `hermes_db/integration/room_router.py`。

### 依赖与接口

前置：Task9、Task13；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按设计lifecycle/ownership/grants/tasks/work/policy/replication/attachments归组；附件内容IO保持独立职责。
2. 同一操作继续使用原Connection/锁，不因分成组件改变generation/receipt身份。
3. 保留superseded grant、held期限和disband/purge后债务，验证真实HTTP晚到与后台supervisor。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/gateway/test_hosted_room_attempt_home.py', 'tests/gateway/test_hosted_room_attachments.py') -Log '.build/package-layout/task15-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_room_runs.py', 'tests/hermes_db/postgresql/test_room_faults.py', 'tests/hermes_db/postgresql/test_room_policy_process.py', 'tests/hermes_db/postgresql/test_room_attachment_faults.py', 'tests/hermes_db/postgresql/test_room_attachment_concurrency.py', 'tests/hermes_db/postgresql/test_merge_collaboration_contracts.py', 'tests/hermes_db/postgresql/test_merge_collaboration_consumers.py', 'tests/hermes_db/postgresql/test_merge_commit_recovery.py') -Log '.build/package-layout/task15-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

房间碎片净减少且职责清楚，exact-grant/后台付债/附件恢复及scope隔离在当前实现通过。

### 执行结果

从Task14 `3857ae68ba`继续，按实际文件/映射核对为23个room操作 + 4查询 + 5附件metadata，修正概述“26操作”的计数，不存在源文件/hash缺失或业务差异。按已有生命周期落为lifecycle/ownership/grants/tasks/work/policy/replication/repository及附件metadata九组；附件内容I/O仍由files、store、read composition负责。32源→9目标，移除4空namespace，378→351个Python文件，根仍11。

内联前局部遮蔽检查拦截work_snapshot.content与capture_locked局部content、附件查询blob与put参数blob；仅将实际内部helper具名为_snapshot_content/_blob_row，同步成员读取点，公开store方法、wire字段、DTO/错误、SQL与参数不变。候选全部编译、F821/F822/F823通过且eager图无环后才写跟踪源码；更新生产消费者、17-topic路由及测试实际读取点。当前合同和15项静态已通过。

| 最终模块 | 源模块数 | 原始行数 |
| --- | --- | --- |
| `postgres/lifecycle.py` | 4 | 268 |
| `postgres/ownership.py` | 5 | 292 |
| `postgres/grants.py` | 3 | 285 |
| `postgres/tasks.py` | 4 | 327 |
| `postgres/work.py` | 4 | 320 |
| `postgres/policy.py` | 4 | 303 |
| `postgres/replication.py` | 1 | 125 |
| `postgres/repository.py` | 2 | 138 |
| `attachments/postgres/metadata.py` | 5 | 334 |


### 验证证据

- Windows/Linux独立PM环境、隔离HOME/RUNTIME与各自字节码缓存沿用Task13；未新增依赖或修改正式配置、数据库服务/扩展/角色。
- 真实导入/路由探针exit0：九组模块在拒绝SQLite连接时全部导入，17逻辑topic的67注册方法解析为callable（task15-probe.log）。
- 独立AST/归属审计exit0：184函数/类、2常量经真实导入/导出身份归一后等价，无可变/调用型全局误合并；61锚点相对Task14内容一致；398基准源项完整闭合、当前351模块/根11（task15-audit.log、task15-semantics.json）。
- Native依计划92文件通过；PG扩为全部19个test_room文件及三个merge合同/消费者/commit恢复共22文件通过，实际命令如下。

```text
bash scripts/run_tests.sh tests/hermes_db/postgresql/test_room_attachment_concurrency.py tests/hermes_db/postgresql/test_room_attachment_faults.py tests/hermes_db/postgresql/test_room_attachment_guards.py tests/hermes_db/postgresql/test_room_attachment_limits.py tests/hermes_db/postgresql/test_room_attachment_service.py tests/hermes_db/postgresql/test_room_attachment_values.py tests/hermes_db/postgresql/test_room_attachments.py tests/hermes_db/postgresql/test_room_coordination.py tests/hermes_db/postgresql/test_room_driver_runtime.py tests/hermes_db/postgresql/test_room_faults.py tests/hermes_db/postgresql/test_room_policy_bounds.py tests/hermes_db/postgresql/test_room_policy_process.py tests/hermes_db/postgresql/test_room_policy_schema.py tests/hermes_db/postgresql/test_room_policy.py tests/hermes_db/postgresql/test_room_route_fences.py tests/hermes_db/postgresql/test_room_run_faults.py tests/hermes_db/postgresql/test_room_runs.py tests/hermes_db/postgresql/test_room_work.py tests/hermes_db/postgresql/test_rooms_store.py tests/hermes_db/postgresql/test_merge_collaboration_contracts.py tests/hermes_db/postgresql/test_merge_collaboration_consumers.py tests/hermes_db/postgresql/test_merge_commit_recovery.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
```

- Windows `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/gateway/test_hosted_room_attempt_home.py tests/gateway/test_hosted_room_attachments.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件529passed/0failed/5skipped，315.7秒（task15-native.log）；原4平台skip加附件1项symlink不可创建，均单列未算通过。
- Linux `bash scripts/run_tests.sh tests/gateway/test_hosted_room_attachments.py -j 1 --file-timeout 1200 -- --tb=short`，exit0、完整1文件24passed/0failed/0skip，20.7秒（task15-native-linux.log），验证Windows symlink缺证的真实宿主正向路径。
- 上述PG22文件命令exit0、109passed/0failed/0skip，328.0秒（task15-pg.log）；当前源码exact/superseded grant、held期限、disband/purge后债务、任务/策略/晚到恢复、附件并发故障和merge消费者均通过。随机Schema归属由fixture检查，未操作正式数据或PG服务/扩展/角色。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7` exit0，15checks通过，health591文件0blocking/0advisory，137.1秒（task15-check.log）；无新豁免。最终元数据更新后对整个Task15差异执行空白检查exit0。
- 恢复点：本地提交`9ebe26513d`，标题`refactor(storage): consolidate room and attachment persistence`；下一Task16。忽略目录task15-virtual.json、groups、probe、audit与原始日志保留；apply非幂等。
- 未验证：Task16依赖闭环、Task17最终全DB/SDK/独立载荷及Task18独立审查；原统一Task24与七项非WSL缺证仍独立保留。

## Task 16：关闭依赖例外与全量归属核对

状态：completed

### 目标

完成跨域组合、私有门面依赖与旧技术层清理，验证最终结构达到设计。

### 涉及文件

- `hermes_db/integration/`。
- `hermes_db/core/`。
- `hermes_db/domains/`。
- `hermes_db/operations/__init__.py`。
- `hermes_db/repositories/__init__.py`。
- `scripts/boundary_lint_baseline.json`。
- `scripts/`。
- `website/docs/`。
- `skills/`。

### 依赖与接口

前置：Task6、Task11、Task14、Task15；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 按Task1台账移除运行时私有facade反向依赖；纯共享模块、历史迁移、Native桥接分别登记。
2. 删除两处旧空namespace、已迁移的内部模块和临时Mixin层；不新增re-export壳。跨域能力由组合边界注入。
3. 精确迁移既有插件boundary项及理由，不扩大公共API或批量更新baseline；通过现有lint机制检查依赖。
4. 核对398源逐项最终处置、新模块归属、root11、文件净减少和主动文档引用；历史证据不改写为新执行命令。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db/contracts', 'tests/hermes_cli/test_projects_db.py', 'tests/tui_gateway/test_groups_methods.py') -Log '.build/package-layout/task16-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql/test_surface_flow.py', 'tests/hermes_db/postgresql/test_plugin_storage.py', 'tests/hermes_db/postgresql/test_merge_storage_contracts.py', 'tests/hermes_db/postgresql/test_merge_collaboration_consumers.py') -Log '.build/package-layout/task16-pg.log'
```

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

归属/依赖闭环、无内部shim、根11且总文件数净减少，所有例外可审议，公开API未扩张。

### 执行结果

已完成本Task依赖/归属收口及局部验证；下列阶段检查点保留真实实施历史，最终完成记录见本Task末尾。完整冻结验收仍属Task17。

- 已移除 PG metrics Store、Worker metrics、PG sender 和 PG room router 对完整 Native 类的继承；实际共用代码分别归入 metrics/policy、package_exports、sending 及 tui_gateway/hosted_room_router_lifecycle。SendOutcome 的定义仍在原公共模块，通过真实构造器传入；Native sender 保持公开返回注解。审计补回 Worker 原有 consented_day/create_and_export_package 的相同拒绝语义。
- Session 原 resume/export 配置解析与原公共错误构造器从 integration/session_composition 注入共享 SessionContext；Projects 原 Project/ProjectFolder 定义不动，通过 ProjectResource 注入 DTO 构造器与原时钟读取点。
- Runtime 的13个公共值/纯投影、24个本地/终态回执及 mutation 校验定义提取到实际共享 owner；Native SQL 方法不搬迁。RuntimeStoreError/SessionGoneEvent 与13个 Room 公共错误仍由原公共路径导出同一实际类型，保留原 __module__/pickle 身份。没有双份异常。
- Room 68个实际限额/校验/投影定义与10个通用纯叶子定义归入 rooms/rules；安装身份读取由 RoomResource 的具体回调在 integration 组合。policy sync 直接调用带原 scope 的 PG read_events，不回绕 Native 门面。
- 纯 transcript 历史修复移到 Agent 现有 message_sanitization；消息时间戳/工具调用计数归现有 Session codec，JSON 解码归 Session rules。直接 import、模块别名中的私有读取点和测试 patch 点随实际定义更新。
- 新增8个 hermes_db 具体 owner 已登记；当前 Python 模块359，根11，较398源净减39。原398项归属无遗漏；两个旧空技术 namespace 仍待全部依赖闭环时删除。metrics/export.py 被既有 export* 忽略规则命中，已在写入发行映射前改名 package_exports.py，不依靠强制加入忽略产物。
- 仍须完成：Kanban 私有门面耦合、Room 其余 policy/context/replica 等 helper、Session/Runtime 剩余共享规则与跨域能力核对；精确依赖检查、活跃文档/skills/AGENTS、插件 boundary 项审议、61锚点及最终归属审计、全部受影响验证。未执行静态门禁，不得标记完成。


### 验证证据

阶段性实际命令/结果（所有原始日志在忽略目录，不含待提交秘密；本 Task 后续修改后仍需最新复验）：

Windows 绑定 HERMES_HOME=.build/package-layout/profile、HERMES_RUNTIME_DIR=.build/package-layout/runtime、HERMES_PYTHON=.build/package-layout/test-env/Scripts/python.exe、PYTHONPYCACHEPREFIX=.build/package-layout/runtime/pycache-tests、HERMES_TEST_FILE_RETRIES=0。

1. `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_cli/test_relay_shared_metrics.py tests/hermes_cli/test_shared_metrics_sender.py tests/hermes_cli/test_shared_metrics_sender_e2e.py tests/tui_gateway/test_hosted_room_router.py tests/tui_gateway/test_hosted_room_router_authority.py -j 2 --file-timeout 1200 -- --tb=short`：exit0，5文件196通过/1 POSIX skip，48.9s；task16-metrics-router-native.log。
2. 真实 Ubuntu-26.04 使用 linux-state.json 的 PM Python3.14.9/独立 home/runtime/cache；`env ... bash scripts/run_tests.sh <task16-metrics-router-pg-files.txt列出的16文件> -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`：exit1，41通过/1失败，192.3s；task16-metrics-router-pg.log。失败为 Worker root late 日期回放：Worker 仍读旧 Native 时钟；已改到与 PG 记录/打包相同的实际 policy 时钟，未隐藏失败。
3. 同 Linux 环境 runner，8文件为 surface_flow、plugin_storage、merge_storage_contracts、merge_collaboration_consumers、projects_store、worker_metrics_root、metrics_faults、metrics_store，完整参数同上：exit0，51通过/0skip，159.4s；task16-core-pg.log。包含修复后的 Worker root 四种场景。该证据早于后续纯值/Room 抽取，不能冒充最终重构验证。
4. Windows `scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_projects_db.py tests/tui_gateway/test_groups_methods.py tests/hermes_state/test_background_review_session_isolation.py tests/hermes_state/test_stale_tool_call_marker_session_repair.py -j 2 --file-timeout 1200 -- --tb=short`：exit1，94文件524通过/2失败/35 errors/4skip，773.0s；task16-core-native.log。执行中新增 Runtime values 首次漏导入 DATA_USE，影响 profile_moves、sessions、retention_selection、message_rewrites、retirement_housekeeping 五文件（后者一次collection error）；已补入并通过拒绝 SQLite 的导入及公共类型身份探针，五文件尚待重新执行，未计完成。
5. Room 纯定义依赖闭包、Runtime receipts/mutation_rules 自由全局引用预写审计均通过；实际 Room/Runtime 模块在 sqlite3.connect 一律拒绝的进程中导入成功，原公共 Runtime/Room 错误 is 身份与 __module__ 核对通过。机械 AST/SQL/61锚点和最终全量依赖检查仍待完成。

当前无外部环境阻塞；Task16 为 in_progress，不创建阶段性完成 commit，不进入 Task17。原统一后端 Task24 和七项非WSL平台缺证独立保留。




### 后续实施检查点（Task16未完成）

- Kanban 原 Task/Run/Comment/Attachment/Event 与原拒绝类型通过 KanbanValues 注入；DispatchResult/SwarmCreated 也保留原定义并注入，没有复制 DTO。原 pack/unpack/CommandRefusal 通过 KanbanCodec 注入，SQL 回执不导入上层转换模块；Gateway owner RPC 拒绝消费者已同步新参数。
- 现有绕经 Native 分发表的调用改为14个明确 Board 方法，保留同一 Profile/board_files 作用域；Profile策略、进程、提交后观察者和文件四组具体应用能力共享捕获的 DatabaseScope，只有实际消费者，无完整 Native 服务、getattr代理或通用CRUD。
- Kanban SQL 工作流已无 Native kanban_db/sibling、上层工厂、owner/观察/迁移协调器导入。独立 Profile 计数解析在 integration，计数 SQL 仍使用原同一 Connection/scope；文件路径、终态观察、owner引用、import最终化通过具体能力传入。
- owner 与 generation file scope 合并为 integration/kanban_owner；Worker/RPC协调归 integration/kanban_worker 和 kanban_wire；Board 迁移协调归 integration/transfer/kanban。原 routing 空namespace删除。TaskEvidence/typed_owner_receipt 经实际核对是纯值，合并到域 rules，不保留无职责 integration 壳。
- 原资源 resource_key、digest、_bytes 算法原样归 core/values，跨域目标摘要编码不变；原 transfer helper 直接消费实际定义。原 Native Profile 标识的7个纯定义归 CLI-owned profile_names，Native公开入口/函数pickle路径保持；Agent业务未搬到数据库层。
- 当前398源归属集合与全部新 owner 精确吻合，Python358、root11，较398净减40；仍有两个旧空技术namespace待最后清理。Task16无本地完成commit，恢复提交仍9ebe26513d。

新增实际验证与失败记录（均为阶段证据，后续代码修改后仍需最新复验）：

- task16-shared-native.log：原列表 task16-shared-native-files.txt 的84文件，exit1，759通过/2失败/5collection errors/6skip，431.3s。Root cause为一处 Discussion 模块别名仍读旧common.identifier；当前实际读取点已迁移。六失败文件以规定 runner 重跑：task16-room-retry-native.log，exit0，59通过/0skip，45.7s。原DATA_USE影响五文件均在84文件批次通过。
- task16-shared-pg.log：task16-shared-pg-files.txt 的25文件，exit1，112通过/3失败/1collection error，351.3s。三失败是测试仍patch旧Native配额读取点，collection是同一common别名遗漏。四文件第一次复验 task16-room-retry-pg.log：18通过/1collection error，48.2s；该错误是混合import补入quota owner时误带Gateway driver，已恢复独立driver导入；随后10文件批次的room_coordination通过。
- task16-values-native.log：5文件，exit1，280通过/8失败/5skip，63.5s。8项均在扩展的完整test_profiles.py；Task15独立无.git源码载荷 profile-base-9ebe26513d 已核对模块真实导入来源，使用同PM Python和隔离home/cache复跑 task16-profile-base-windows.log：exit1，99通过/同一8失败/4skip，45.8s；自动比对失败ID集合精确相同。当前真实Linux完整Profile套件 task16-profile-linux.log：exit0，108通过/3skip，52.8s。Windows命名/校验本身通过；8项现有平台/链接权限问题单列，未改标记、未拿Linux结果覆盖非WSL缺证。
- task16-values-pg.log：10文件，exit1，35通过/3失败，140.1s。两项Kanban任务ID冲突测试仍patch旧生成器，已迁到实际rules；一项Gateway owner RPC漏传新拒绝转换器参数，已补齐。未用放宽断言掩盖。
- task16-kanban-pg.log：30文件，exit1，14通过/26collection errors，64.6s；task16-kanban-native.log：93文件，exit1，547通过/1失败/1collection error/4skip，442.4s。共同原因为共享DEFAULT_FAILURE_LIMIT导入位置晚于原函数默认参数求值；已提前到future import之后，全新进程冷导入且SQLite全拒绝探针通过。
- 当前 task16_kanban_probe.py：全部具体PG owner、原DTO、无I/O构造、捕获scope及所有函数自由全局引用通过，SQL查询不反向导入上层服务。预写guard另找出两个无owner helper（提交后terminate、归档metadata），已显式传owner；路径检查用同一捕获home/board_id，不依赖删去的临时frame。
- 正在运行：task16-kanban-recheck-pg.log（同30文件）、task16-native-import-recheck.log（single_backend + Kanban CLI）。必须获取真实退出码/汇总后记录，不计完成。

下一恢复：保持Task16 in_progress，先收取上述正在运行结果；继续Session/Runtime剩余共享规则、Room其余policy/context/replica helper和构造边界；完成精确依赖lint、61锚点/接口/语义审计、活跃文档/skills/AGENTS、两旧namespace清理，再运行当前源码匹配的Task16静态与业务验证。不得跳到Task17、不得把已知失败批次冒充通过。原统一Task24及七项非WSL缺证仍独立保留。


### 共享规则与 Room 组合检查点（Task16仍未完成）

- 已取得前一检查点真实退出码：task16-kanban-recheck-pg.log exit1，30文件113通过/3失败，372.2s；task16-native-import-recheck.log exit0，2文件13通过/1skip，10.3s。3项PG失败均为消费者读取点：两处确定任务ID的旧patch、一处归档故障注入缺显式owner参数。已同步所有同类PG任务ID patch及domain_maintenance的归档注入签名，不弱化断言。
- Session20项状态/预览/结束原因及prompt键共享定义归既有rules；rewind的8项算法/原公开DTO、错误归sessions/rewind，原公开类路径与对象身份保留。随后23项Session/Runtime纯字段、路由/退役/Worker回执标记及校验归既有values/receipts/mutation_rules/rules/search_rules；Native SQL未移动，没有为这些常量新增模块。
- Room经逐定义闭包审查，将161项实际校验/限额/DTO及必要纯依赖归rooms/rules、driver_rules、replication_rules、authority_rules、work_rules与attachments/rules；五个新增owner分别对应任务/租约值、复制页、权威历史、工作证据、附件协议。27个原公开类保持原__module__和同一实际对象，原Native模块仍拥有真实SQL并导入其实际共用值。
- PG附件不再继承完整Native SQLite Store；原8个内容/提交便捷方法归既有attachments/files的AttachmentContent，两后端真实共用。Native __new__完全构造PG对象，保持初始化顺序；共享内容的导入不加载PG metadata，SQL清理依赖在实际PG清理方法内导入。PG附件及Policy的资源获取/跨事务协调归integration/room_attachments与room_policy，SQL工作流仍归域。Context更新直接调用同scope的room_state和捕获的安装身份回调。
- 新Room纯定义全部SQLite连接拒绝的冷导入及自由全局引用审计通过；230个与Task15 AST完全相同的提取定义恢复原源文本（包括WHY注释），其余仅实际import/别名重绑定仍须最终语义核对。未改31 revisions、表定义或历史SQL。
- 机械改写发现一处新旧_storage_shared_1别名碰撞：gateway/hosted_room_work_records.py把_task_payload错误绑定到rooms/rules。全仓库AST审计仅此1处，已具名改成_driver_values；离线生成器补上import绑定保留集，避免重犯。不是业务规则修复，未新增万能运行时代理。实际setattr故障读取点另同步6个现有测试消费者。

实际命令与结果：

- Windows隔离环境与runner参数同Task16前述，文件清单task16-room-new-native-files.txt的39文件：task16-room-new-native.log，exit1，283通过/62失败/8errors/3skip，190.6s。共同实际异常为上述别名碰撞；未计通过，修复后正在task16-room-fixed-native.log复验42文件（另含work_evidence、discussion_manifests、TUI groups）。
- Linux独立PM/随机Schema的同一既有命令（`env ... bash scripts/run_tests.sh <task16-room-new-pg-files.txt的24文件> -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=<既有私有配置>`）：task16-room-new-pg.log，exit1，120通过/1失败/0skip，308.1s。前次3项Kanban失败均已通过；仅Room evidence容量测试patch旧MAX_BYTES，已同步实际work_rules。首次枚举Windows路径未规范化导致runner exit2，未运行测试；已改为正斜线并取得以上真实业务结果。
- 正在复验：task16-room-work-fixed-pg.log的test_room_work.py，标准runner/同隔离Schema参数。必须获取真实退出码和汇总后记录。
- task16_room_probe.py冷进程：所有Room模块及Session/Runtime当前共享owner导入成功、自由全局名0缺失、sqlite3.connect一律拒绝。该检查不代替业务测试或独立发行。

恢复点仍9ebe26513d；所有以上为未提交Task16工作。当前无外部环境阻塞。尚须关闭Session/Runtime应用所有权/跨域回调、逐符号审议其余Agent/SDK依赖、精确依赖lint与插件baseline迁移、活跃引用和最终归属/61锚点、当前源码静态和业务复验；两个空技术namespace尚未删除。未进入Task17，未宣称最终验收。原统一Task24及七项非WSL缺证独立保留。


### Session 所有权/生命周期收口检查点（Task16仍未完成）

- SessionContext现有捕获范围中注入HistoryOwnership四个实际比较/分类函数，以及SessionEffects四个真实提交后/跨Profile操作；原Native实现和Gateway的OS/login/catalog语义不搬进SQL域。canonical删除/历史claim/Worker reservation/Bot roster/导入父关系沿同Connection和scope显式传入所需比较器。Gateway authorize_core、history_binding_names及跨Profile adoption消费者已同步，不设ambient回退。
- 原纯ImportValues及列策略归sessions/import_rules；实际当前转录导入SQL归sessions/postgres/operations/imports，原bulk retention SQL归operations/retention。跨Profile文件清理归integration/media_retirement，经原生命周期调用时序注入；profile purge及on_session_delete同样由组合边界提供具体回调。新增模块数0，SQL、锁、回执及日志算法不变。
- Room authorize_room同时用于Room资源和Gateway持有的Session资源，不能假设store有Room专有字段。已改为调用者显式传入same_owner；Gateway在原持有Connection处传同一公共比较函数。删除无实际消费者的RoomResource.same_owner字段，没有给Session Store扩张公共方法。
- 全仓库显式函数调用核对：23个已解析实际调用点，必要回调缺漏0；156个Session/Runtime/Room及组合owner在全新SQLite连接全拒绝进程中导入/自由全局名均0错误；两个Store组合共享同SessionContext，构造未调用数据库，effects持有同一原Profile对象。
- 第一次现有静态预检`python scripts/check --base cbfc773dd7 --only health,ruff`（绑定Windows隔离home/runtime/cache，PM Python）exit1，714文件、8 blocking/0 advisory，120.0s。记录了漏Native常量import、重复/未使用绑定及codec方法CC21；已逐项修正。原转录修复日志阶段抽成同模块具名函数，原谓词、修复调用和日志文本/位置时序保持；该方法CC降到20，没有waiver压过门禁。

本检查点实际验证：

1. task16-room-fixed-native.log：42文件，exit1，385通过/9失败/3skip，218.1s。前述生产别名碰撞已消除；9项为setattr跨后端迁移过宽，Native SQL仍读其本模块绑定，已恢复4个Native测试文件的实际读取点；PG保持共享规则读取点。
2. task16-room-work-fixed-pg.log：同标准Linux隔离PM/随机Schema命令，单文件test_room_work.py，exit0，6通过/0skip，25.6s。
3. task16-context-native.log：标准runner运行task16-context-native-files.txt所列路径（contracts目录展开，共98文件），exit1，650通过/6失败/4skip，652.1s。4失败为Native import列策略漏import，2失败为Gateway直接调用新history query时漏传ownership。已修正；其余95文件通过，包含前次4个Native Room失败文件。不是最终冻结验证。
4. task16-context-pg.log：标准Linux命令运行task16-context-pg-files.txt的12文件，exit1，151通过/5失败/0skip，367.9s。2项为测试重开Store误加ownership参数，3项为Room授权把Session Store当成Room资源；已恢复正确构造调用并显式传比较器。离线审计另外找出import_current父关系和history_binding_names消费者缺参数，均已补齐。
5. 修正后Native标准runner重跑portability/session_controls/gateway_authority：task16-context-fixed-native.log，exit0，3文件20通过/0skip，21.8s。
6. 修正后PG标准runner重跑surface_flow/merge_storage_contracts/merge_collaboration_consumers/room_coordination：task16-context-fixed-pg.log，exit0，4文件32通过/0skip，88.3s。
7. 同一现有静态命令复验：task16-precheck-fixed.log，exit0，ruff+health共2 checks通过，714文件、0 blocking/0 advisory，107.4s。其余13项与新增边界lint仍待Task16最终执行；不把2项预检冒充15项完整门禁。

当前364个hermes_db Python模块、根11；398源及新增owner集合精确吻合，两个旧空namespace仍待最终清理。恢复commit仍9ebe26513d，Task16没有完成commit。余项为Gateway/Worker实际私有依赖的纯规则/具体组合、精确依赖lint/插件baseline迁移、活跃文档与最终61锚点/接口/源码匹配验证。无外部环境阻塞，不进入Task17。原统一Task24及七项非WSL缺证继续独立保留。


### Gateway纯值、检索与Worker指标检查点（Task16仍未完成）

- 23项实际API run状态/身份编码、API generation、deferred pick、委托闭合载荷校验和automation投影归现有Runtime values/receipts；Source taxonomy与admission media纯投影归现有Gateway session_contract，Agent/Gateway业务没有整体搬入DB。字面字段、哈希分隔符和回执键未改，无新增模块。Room PG任务默认参数也改读实际driver_rules，消除仅默认参数残留的完整Native导入。
- 针对Task1待审议的“纯模块”实际读函数：kanban_respawn_policy仍late-import Native配置/dispatch，不能整模块豁免。PG改调用捕获Profile的两个具名策略能力，原查询/调用顺序保持；Native代码原样使用原策略。Swarm plan原late-import的纯文本验证实际提取到既有kanban/rules，现有CLI-owned纯plan继续复用，无完整Native服务引用。
- PG backend/search实际只依赖会话表、Session查询与投影，已逐字移动到sessions/postgres/support/search。生产与两个测试直接读取点同步，模块正文（包括SQL/算法/注释）字节相同；清除基础设施反向依赖业务域，模块数不增。
- Worker指标prepare_policy和跨Profile membership协调归integration/worker_metrics，RuntimeContext注入原闭合handler工厂；配置预读、handler构造仍在receipt事务前，计数SQL继续复用原Connection/scope；Root先提交再Source CAS删除的算法/顺序未改。Gateway drain和测试fault patch同步实际owner。没有把通用接口或整个Native Store塞进Context。
- 进程/PID/birth验证从PG操作移到integration/authority_access的verify_worker_delegation_owner；Gateway仍在原借Connection前的位置调用。原VerifiedDelegationOwner纯DTO归Runtime values，原__module__和SQL handlers实际isinstance所用对象保留。Session近期消息摘要分类由原Agent方法的具体回调注入，Agent业务仍由Agent拥有。此最后一小组正在业务/静态复验。

已取得的实际结果：

1. task16-gateway-values-native.log：标准Windows runner，task16-gateway-values-native-files.txt的11文件，exit1，157通过/1失败/1skip，134.0s。唯一失败为test_session_policy的Windows原始路径直接对JSON文本做子串比较（反斜杠编码），未改不相关断言。Task15独立无.git载荷profile-base-9ebe26513d已先断言真实导入来源，再同PM/独立home/runtime运行同一单例：task16-policy-base-windows.log，exit1，同一失败ID，0通过/1失败、22 deselected，runner33.6s。当前真实Linux完整test_session_policy.py：task16-policy-linux.log，exit0，23通过/0skip，134.5s。该已复现基准问题与此前Windows Profile八项及原七项非WSL缺证分开保留，未以Linux清除Windows缺证。
2. task16-gateway-values-pg.log：标准Linux runner，task16-gateway-values-pg-files.txt的6文件，exit0，50通过/0skip，134.6s。
3. task16-gateway-values-check.log：同现有`python scripts/check --base cbfc773dd7 --only health,ruff`，exit0，717文件0 blocking/0 advisory，116.5s，2 checks通过；仍不是全量静态门禁。
4. task16-worker-metrics-native.log：标准Windows runner，mixed_root/workers/search三个文件，exit0，14通过/0skip，11.8s。但mixed_root文件属于integration，默认选择没有执行其测试，不把它算作混合后端验证。
5. task16-worker-metrics-pg.log：同标准Linux命令，task16-worker-metrics-pg-files.txt的6文件，exit1，18通过/0失败/1collection error，136.1s。只有test_worker_metrics_root的父包from-import漏改（不含连续完整旧模块字符串）；已改真实owner，补做全仓库AST解析父包import审计，而非只搜索完整字符串。单文件复验task16-worker-root-fixed-pg.log：exit0，4通过/0skip，21.4s。
6. 显式单独选择混合Profile合同：标准Linux runner对`tests/hermes_db/contracts/test_worker_metrics_mixed_root.py -m integration`并传同私有PG配置，task16-mixed-root-selected.log，exit0，1通过/0skip，9.0s。随机PG satellite + 临时SQLite root，既有audit验证SQLite连接只属于明确SQLite root。此独立混合模式合同不计入Task17 PG全进程零SQLite验收。
7. task16-worker-metrics-check.log：同2项现有静态预检exit0，717文件0 blocking/0 advisory，90.3s。
8. 全部原始/第一阶段/中间模块映射离线解析（区分仍有效的同名包）：478个已删除模块搬移，实际Python import/父包from-import/精确动态字面量残留0；task16-obsolete-module-imports.json。159个当前Session/Runtime/Room与实际integration owner冷进程SQLite全拒绝，导入/自由全局名0错误、同Context及无DB构造检查通过；task16-worker-identity-probe.log。此为结构审计，不冒充最终全业务验证。

插件边界说明与实际检查：

- 初次`scripts/boundary_lint.py --check`报告Kanban dashboard机械改写带入rules模块及_safe_attachment_name两条新目标，exit1。插件已有Native kanban_db导入仍有真实存储/DTO消费者，两个原helper绑定也仍由Native SQL实际使用；没有必要为这个现有Native消费者添加DB私有依赖。已精确恢复该文件原Native读取点（与Task15该文件无diff），不是重建旧内部模块shim。
- 复验task16-plugin-boundary-fixed.log：exit0，module_to_core847、core_to_module26，无新穿越。未使用--update；Task16未改boundary_lint_baseline.json或plugin_api.json，也未新增公共API。第一阶段既有DB路径迁移保持原已提交审议。

当前159模块冷探针后的一小组正在运行：task16-worker-identity-native.log（委托回执/bridge、remaining_read_maintenance）、task16-worker-identity-pg.log（workers/sessions）、task16-worker-identity-check.log（ruff/health）。必须取得真实退出码/结果后继续记录。当前仍364个DB Python模块、root11、398源归属闭合；尚未删除两个旧空namespace。

恢复commit仍9ebe26513d；Task16在进行，无环境阻塞。尚须完成残余Routes/Media/Delivery/Worker codecs应用依赖及逐符号台账、实际依赖lint接入、活跃文档/skills/AGENTS、两空namespace与最终61锚点/接口/源码匹配验证和全量静态；不得提前完成Task16或进入Task17。原Task24及七项非WSL缺证独立保留。

### 媒体/Cron/依赖门禁与最终归属检查点（Task16仍未完成）

执行结果：

- SessionRouting 的实际分支/重置值与 messaging_platform 分类、Worker自动化State编码由integration在原操作点解析；required callback 调用审计覆盖32处、缺失0。Runtime媒体操作获得两项具体能力：在原绑定scope中解码 admission media，以及原 API inline-image compaction。held_media_paths 实际应用协调移入integration/media_retirement；候选持久化、退役ledger、锁与Connection仍由域内SQL持有，没有换文件根、放松校验或提前执行回调。
- Gateway delivery_rules 保存实际纯重试/限额/可见标记和死目标分类定义；Native与PG消费同一实现，SDK错误分类仍按原时机调用。VerificationEvidence、时钟及保留限额为实际共享值，DTO的原 __module__ 身份不变；Worker/PG选择移至已存在 verification/api，域内SQL不再导入完整Worker服务。自动退役source闭集共享，Native真实class读取点保留。
- Cron execution/incident/delivery/notepad只消费四类实际能力；原进程ID、活跃投递set+lock、限额、时钟、liveness和post-commit observer保持原拥有者/时序，回调绑定resource拥有的Profile。Retain HTTP/client/thread/profile协调整文件移至integration/retain_transport，PG队列SQL不动。插件baseline仅将既有Retain类目标精确改名，计数仍1，不运行--update、不扩充plugin_api.json。
- 新增 scripts/hermes_db_boundary_lint.py 与逐consumer+symbol审议表，接入scripts/check的db-boundaries；基础设施禁止选择域/组合、下层域禁止选择factory/integration或完整Native门面。325项实际符号登记共享值/纯规则、Agent语义、基础设施、入口或SQLite桥接理由，无模块前缀通配权限；历史迁移不获得运行时许可。独立小型package合同证明批准LIMIT不能批准同模块SECRET，显式批准也不能绕过依赖方向。
- 两处旧operations/repositories namespace经AST确认只有历史docstring后删除；398源处置与新增owner精确等于365实际模块，根11、总量净减33、非namespace模块389→315。61固定锚点无偏移：31revision、versions初始化与28表定义原Git字节保持；tables初始化仍只有Task2 catalog导入调整。REQUIRED_REVISION保持0031_merge_data_repair；未执行数据迁移。
- 活跃文档指向真实域/组合及lint入口；历史布局文档明确标为旧设计快照，保留旧路径证据。website/docs、skills、optional-skills与所有AGENTS对已删除模块的扫描仅命中已明确标记的历史快照，不将旧命令改写成新执行证据。

实际验证（原始日志仅在忽略目录，以下没有最终Task17验收含义）：

1. task16-routes-codecs-native.log：标准Windows runner，7文件（prepared_mutations、local_creation、gateway_peers、gateway_rekey、worker_compression、worker_metadata、session_controls），exit0，51通过/0skip，43.4s。task16-routes-codecs-pg.log：标准Linux PG runner，4文件（retirement_rewrites、routing、compression_leases、workers），exit0，114通过/0skip，228.9s。task16-routes-codecs-check.log：scripts/check --only ruff,health --base cbfc773dd7，exit0，730文件、0blocking/0advisory，118.2s。
2. task16-media-delivery-native.log：标准Windows runner，13文件（retirement_housekeeping、retirement_rewrites、retention_selection、profile_moves、prepared_mutations、api_native_media、api_settled_row_retention、delivery_ledger、delivery_ledger_single_connection、delivery_ledger_process_home、retired_media_ownership、verification_evidence及retention），exit0，166通过/0skip，75.9s。
3. task16-media-delivery-pg.log：标准Linux PG runner，6文件（retirement_rewrites、health_archive_refs、messages、deliveries、managed_verification、verification_store），exit1，119通过/1失败，325.5s。唯一失败为共享合同仍patch Native gateway.delivery_ledger._MAX_ROWS，PG读取点已为delivery_rules；已按实际后端选择patch owner，未改业务断言。task16-cron-delivery-pg.log：标准Linux PG runner，deliveries与Cron四文件复验，exit0，29通过/0skip，74.4s，覆盖修正后的完整deliveries文件及Cron实际协议。
4. task16-media-delivery-check.log：scripts/check --only ruff,health --base cbfc773dd7，exit0，734文件、0blocking/0advisory，118.4s，早于最新Cron/依赖门禁改动。新lint合同最初3项失败暴露namespace package解析遗漏；实现补认无__init__的实际namespace后，task16-boundary-fixed-native.log标准runner，exit0，4通过/0skip，3.2s。最新方向/Native禁止规则及全仓边界仍需最终复验。
5. PM Python task16_ownership_anchors.py：398原始处置=365实际，根11，非namespace模块389→315，61锚点0偏移；audit_session_public.py：原36Mixin的288公开/兼容方法签名0差异；audit_runtime_probe.py：原10Mixin的85签名相同，共享Context/关闭状态有效、构造0事务。无PG业务数据读取或SQL改写。

最新验证补充：

- task16-final-native.log：Windows标准runner，完整contracts、Projects、TUI groups、lint合同及Agent verification两文件，95文件618通过/0失败/4平台skip，432.1s（-j4）。新lint合同实际运行7项；另task16-boundary-final-native.log：独立同runner复验7通过/0skip，4.3s，覆盖裸Native模块、namespace包及core初始化入口不能越界。
- task16-final-pg.log：Linux标准PG runner，Task16必需四流程加verification_store、managed_verification、worker_domain_receipts、worker_retain_transport，8文件45通过/0skip，214.8s；覆盖最新Retain真实线程与Worker RPC/PG分流。
- task16-final-check.log：staged全门禁结果打印受Windows GBK编码影响，exit1，未计为静态通过。显式PYTHONIOENCODING=utf-8后的task16-final-check-utf8.log：16项中15项通过，health738文件0blocking/0advisory（141.7s）；唯一footguns为新lint读取JSON未用utf-8-sig，已改兼容BOM读取，未用noqa或豁免。最终全16项复验仍在执行。
- 扩展离线callback审计包含媒体退役整条链及同模块调用，60处resolved calls、缺失0；旧模块AST审计479条已删除模块映射、直接/父包from-import/精确动态字符串残留0。正式checkout仍无修改；暂存区未包含.env、原始日志或.build。

未验证/恢复点：Task16继续in_progress，恢复commit仍9ebe26513d；最新全部修改未提交。仍须最新受影响Retain/verification用例、完整必需Native与PG四流程、全16项staged静态、插件lint及最后动态引用/导入/身份审计。Task17/18未开始；原统一Task24与七项非WSL缺证独立保留。

### Task16最终完成记录

- 状态completed。398原始源及所有新增模块归属闭合，365实际Python模块、根精确11，总模块净减33，非namespace模块389→315；不再保留旧operations/repositories技术namespace或旧内部路径空壳。
- PG的Native类继承、CLI/Gateway私有门面helper与应用协调已改为实际共享纯定义或integration注入的具体能力；Agent转录语义精确登记，仍归Agent。Session/Runtime共用原scope/Connection/pin/close；公开签名与DTO/错误身份保持。没有通用CRUD、反射代理、双写、数据迁移或新增配置环境变量。
- 最后验证：Windows 95文件618通过/0失败/4平台skip（432.1s）；真实Linux补验Windows跳过的single_backend、domain_resources、matrix_close三文件，11通过/0skip（23.7s），task16-platform-native-linux.log。四个Windows skip为Linux full SQLite+Matrix业务、POSIX fork、两个Linux Matrix close协议；Linux证据不宣称Windows获得其平台能力。
- Linux PG必需四流程与最新受影响用例8文件45通过/0skip（214.8s）；Cron/投递另5文件29通过。完整命令/环境与先前失败整改记录见上述检查点，未重用旧686/36/32结果。
- `PM Python scripts/check --staged --base cbfc773dd7`，PYTHONIOENCODING=utf-8，task16-final-check-fixed.log：exit0，16项全通过，health738文件0blocking/0advisory，140.4s；无新增豁免。`PM Python scripts/boundary_lint.py --check`，task16-final-plugin-boundary.log：exit0，module_to_core847/core_to_module26，既有Retain一条目标仅等量改名、无新跨界。公共plugin_api.json未变化。`git diff --cached --check 9ebe26513d`通过。
- 结构/接口探针：61锚点0偏移、Schema要求0031不变；Session288/Runtime85方法签名相同，构造0事务、共享关闭状态有效；60处所需回调0缺失；479条已删除模块直接/父包import与动态字面量残留0。活跃指南更新，历史布局明确保留旧快照。
- 恢复：本Task创建本地提交（父9ebe26513d；精确提交hash由下一Task启动记录补入），工作区为D:/AI/hermes-db-packages，普通分支refactor/hermes-db-packages。正式D:/AI/hermes-agent保持clean，未重启/部署/改Profile、秘密或业务数据。原始日志及.env没有暂存。
- 未验证项归Task17/18：最终源码冻结后的全域Native/PG、无PG依赖独立安装、真实Matrix PG与旧Schema/双PID/丢ACK恢复、独立审查及整改复验。本Task不是整系统验收；原统一Task24和七项非WSL缺证继续独立开放。

## Task 17：独立发行、旧Schema与最终业务验证

状态：completed

### 目标

用最终冻结源码获得完整双后端、实际SDK、故障及独立安装证据。

### 涉及文件

- `tests/hermes_db/`。
- `hermes_db/migrations/`。
- `hermes_db/tables/`。
- `pm/`。
- `pyproject.toml`。
- `docs/plans/hermes-db-package-layout-plan.md`。

### 依赖与接口

前置：Task16；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 冻结全部生产代码和测试hash；验证31个revision、29个表模块、0031要求与资源位置保持。仅迁移helper import允许变化，逻辑SQL不得漂移。
2. 在Windows及适用Linux用PM从独立无.git源码payload建立SQLite/PG环境；SQLite载荷不安装PG依赖，PG业务进程拒绝所有SQLite连接。
3. 执行完整DB Native/PG、SDK及接入消费者批；逐个skip/错误读取真实汇总，证明业务/持久化/隔离/双PID恢复和实际COMMIT丢ACK。
4. 使用实际0004/0030旧行升级、新0031数据重开、重复升级验证；不向正式Schema试升级。执行共享gateway契约和scripts/check。

### 验证方式

```powershell
Invoke-NativeCases -Files @('tests/hermes_db', 'tests/hermes_cli/test_projects_cli.py', 'tests/hermes_cli/test_kanban_cli.py', 'tests/tui_gateway/test_groups_methods.py') -Log '.build/package-layout/task17-native.log'
```

```powershell
Invoke-PgCases -Files @('tests/hermes_db/postgresql') -Log '.build/package-layout/task17-pg.log'
```

独立载荷另经tests/hermes_db/test_distribution.py和postgresql/test_distribution_initialization.py，传PM实际返回的`$SqlitePython`/`$PostgresPython`/`$DistributionSource`与既有私有配置路径；明确选择`-m "integration or not integration"`避免漏选PG。Linux执行实际Matrix组，另做现有0031数据双进程重开。

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

当前冻结源码的必需双后端/实际SDK/前向升级/发行/静态均有真实证据；缺必需环境仍blocked，不以旧686/32或无.db替代。

### 执行结果

实施中。Task16本地恢复提交为`bd82697cb49a8d2b45fcf24d9a77439feca3af75`（修正误入的测试生成fixture后提交；artifact保留在忽略目录，不属于载荷）。从该提交冻结生产与测试源码，不继承正式Profile或业务数据。独立source payload、PM环境与完整验证正在建立；未获得最终结果前不计完成。

### 验证证据

冻结与独立PM检查点（实施中，非最终验收）：

- 源码提交`bd82697cb49a8d2b45fcf24d9a77439feca3af75`，冻结记录为`docs/designs/hermes-db-package-final-freeze.json`；Git archive SHA256 `200a2d8011b9712908bc029e5754f6373955c71041a46fd4d5d9d9b5ee991ba2`。9498个生产代码/清单条目、8237个测试条目的完整hash清单保存在忽略目录；提交中的聚合hash及624个DB/合同文件hash可由源commit恢复核对。完整归档tree同时绑定其他资源与配置，未包含.git、.env或测试生成fixture。
- Windows独立载荷：`D:/AI/hermes-db-task17-16c4a1931a33/source`；Linux独立载荷：`/var/tmp/hermes-db-task17-16c4a1931a33/source`。两者均在Git工作区之外、没有.git，归档sha一致。Linux额外从同一归档建立test-driver，保持发行测试驱动与实际安装源目录分开。
- 先绑定独立HERMES_HOME再import PM，HERMES_RUNTIME_DIR使用已有隔离PM管理器（不是正式runtime）；`pm.build_environment(source=..., out=..., python=..., extras=..., groups=('dev','test'), explicit=True, frozen=True)`建立全新环境，不用raw pip/uv、不改pyproject/uv.lock。Windows有sqlite（无extra）/postgresql；Linux有sqlite（无extra）/postgresql+matrix/sqlite+matrix。实际解释器均3.14.9，`-I`探针证实hermes_db从独立安装源加载。两个普通SQLite环境均实际没有SQLAlchemy/psycopg/Alembic/asyncpg/mautrix；SQLite+Matrix环境无前三项、asyncpg只提供上游SDK要求的异常类型，业务guard仍拒绝其PG连接。
- PM证据：task17-win-pm.log、task17-linux-pm.log exit0，解释器路径及无秘密的依赖事实保存在各独立root/environments.json。manager复用不等于复用应用环境，所有out在创建前不存在。
- 首轮发行测试在安装源自身作为test-driver时，business_process的source!=checkout前提拒绝；task17-pure-sqlite-linux.log，exit1，2通过/1失败（3.2s），未实际计入业务通过。改为同归档的独立test-driver后：task17-pure-sqlite-fixed-linux.log exit0，3通过/0skip（27.5s），真实无PG依赖载荷读写、新PID恢复通过。
- task17-distribution-linux.log：独立test-driver中标准runner，`tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/test_distribution_initialization.py -j2 --file-timeout1200 -- -m "integration or not integration" --tb=short --postgres-test-config=<既有私有路径> --hermes-distribution-source=<独立source> --hermes-postgresql-python=<新PG环境> --hermes-sqlite-python=<新SQLite+Matrix环境>`，exit0，6通过/0skip（25.0s）。覆盖安装资源、无PG storage extra的SQLite业务/实际SDK、0004真实旧行前向升级、重复升级、PG十域/实际Matrix与双Profile隔离/新PID恢复、全SQLite连接拒绝。该批不替代仍在进行的完整PG及0030升级专项。
- task17-cli-native-linux.log与task17-cli-native-win.log：标准runner单独运行Projects CLI、Kanban CLI、TUI groups三文件，不传DB目录专属参数，分别exit0，49通过/0skip（20.8s / 51.2s）。首轮Linux完整Native混合命令对三个外目录文件传递DB专属option，属于调用范围错误，完整汇总后逐项登记并以该无option组复验闭环。
- 全量批仍运行：Linux131个PG文件使用新PG+Matrix环境、真实随机Schema；Linux全部DB Native及Windows全部DB Native使用冻结匹配代码/新PM解释器。所有PG配置由既有私有文件加载，标准runner参数只传路径，不打印秘密或原始堆栈。
- 全量批目前暴露依赖配置差异：Windows native_http_sessions缺aiohttp；Linux discord_backfill在未安装Discord时使用fallback、缺DMChannel。均先用脱敏源码帧/异常类型定位，未修改业务代码或弱化断言。正通过声明的messaging extra另建env-business（原运行环境不变），准备对实际HTTP/Discord消费者复验；随后按完整汇总处理所有未通过项。

### 完整批次、失败闭环与最终载荷检查点

- task17-full-pg-linux.log：独立无Git source、新PG+Matrix环境，标准runner完整postgresql目录131文件，exit1，718通过/2失败，1800.9s。两个失败逐项闭环：discord_backfill因缺声明messaging依赖导致fallback缺DMChannel，task17-discord-fixed-pg-linux.log在另建env-business（postgresql+messaging+matrix）用真实Discord2.7.1复验整文件2通过（9.9s）；发行十域测试因source==test-driver前提，已在同归档独立test-driver复验整发行组6通过。两处均无Python/测试修改、未弱化断言。完整131文件所选720项现均有当前冻结代码通过证据，原686基线未计入。
- task17-full-native-linux.log：冻结source完整DB加CLI/TUI首批，237文件（含integration deselected文件），exit1，582通过/2用例失败、4文件非零，941.8s。两例均为发行source==driver前提，已由分离driver的发行组覆盖；其余三外目录文件因DB专属option不被注册，已单独无option三文件49通过。按不同用例计，Linux所选Native/CLI/TUI共633通过、无平台skip；不是将重复发行复验次数直接累加。
- task17-full-native-win.log：标准runner完整DB，新PM PG环境，234文件（含integration deselected），exit1，577通过/2失败/5平台skip，1326.6s。两个HTTP用例均缺aiohttp，另建声明messaging的env-business（aiohttp3.14.5）：task17-http-fixed-win.log、task17-http-turn-fixed-win.log各1通过（18.6s / 12.2s）。CLI/TUI三文件另49通过。按不同用例计，Windows共628通过/5平台skip；五例均为Linux full SQLite+SDK、POSIX fork、两例Linux Matrix close和Linux安装SDK恢复，不伪装平台、不以Linux结果抹去Windows边界。
- 0004前向/重复升级与0031双PID恢复：task17-distribution-final-linux.log在最终载荷中6通过/0skip（21.4s）。task17-distribution-final-win.log新Windows实际PG驱动及同一测试数据库随机Schema，4通过/2 Linux SDK平台skip（15.3s），覆盖Windows真实0004→0031与新PID会话/Admission重开。普通SQLite环境确无任何PG依赖；Linux纯core环境另3通过，SDK extra只在独立SQLite+Matrix环境使用。
- 当前完整PG已实际执行Matrix十文件31项（adapter_storage4、close2、crypto_store2、devices3、recovery1、faults5、sdk_concurrency2、sdk_edges5、sdk_flows3、sessions4），全通过/0skip；与旧32结果分开。test_merge_data_upgrade四项通过，真实0030旧行前向/拒绝活跃lease回滚/重复升级与稳定页面；test_merge_process_recovery两项通过；test_merge_commit_recovery两项通过，其fault先调用真实dialect.do_commit再抛psycopg.OperationalError，不能算提交前模拟。single_backend完整业务子进程在全部SQLite连接审计拒绝下读写十域、隔离两个scope并由新PID恢复，SQLite attempts均0。
- 原共享契约生成检查exit1（task17-gateway-contracts.log）来自Task16将SessionMutateParams描述的validate_action实际owner更新后，两份生成文档仍留旧引用。相同解释器的Task15基准生成无漂移，已确认这是本次遗漏。同步generated.ts的一条JSDoc及openrpc.json的一个description；逐hunk断言TS仅注释、移除该description后JSON完全相等，接口/TypeScript tokens/路由分发0变化，不宣称做过前端构建。task17-gateway-contracts-fixed.log检查exit0。
- 最终文档覆盖层明确列入冻结记录：source tree `97542f2a099f7c0a4da4da0689ce1a64f240cec5`，archive v2 SHA256 `cf06ffb3bfed422b3805c2238a35e65d32169469cb6a0efff6e588e9218ac9d9`；Python与全部测试仍为bd82697cb4的相同内容，只有上述两份生成描述改变。Windows/Linux已安装源及独立driver同步覆盖层；当前完整业务测试无需因描述变更重跑全部PG，最终发行组已复验。
- task17-final-hashes-win.log、task17-final-hashes-linux.log：两端各实际逐文件核对17735个生产/测试条目及覆盖层，0差异、没有.git；生产聚合hash `92ac6be517b6fab48946c055231f27cd3034e13ef0c8893846cd9d045271bf33`，测试聚合hash `fe11f8b76f3b5dcef97396b471331639c7df7b6f1eab9f3046a0cb353c729978`。冻结JSON说明运行时代码基准commit与描述覆盖层tree的关系，不把文档tree冒称已存在源码commit。

恢复/未完成：Task17为in_progress，不能计入完成或创建本Task完成commit；最后已验证恢复点为Task16的bd82697cb4。源/测试目前没有实施改动，只有计划、冻结记录与生成描述同步未提交。完整批次、缺依赖消费者、SDK/0030/丢ACK/契约及hash检查已收口；最终staged静态/插件边界、Schema锚点复核和完成提交仍待执行。Task18未开始，原统一Task24及七项非WSL缺证独立保留。


### Task17最终完成记录

状态completed；完整运行时与测试源码仍为bd82697cb4，另有明确的两份生成描述覆盖层，最终tree/文件hash见冻结记录。本Task不增加迁移、不改Python行为或测试断言。

- 独立无Git环境：Windows/Linux各有实际无PG依赖SQLite与PG环境，另有真实Linux SQLite SDK环境；所有依赖经项目PM及原uv.lock建立。missing messaging依赖已在新环境补齐，原运行环境未被修改。
- 完整验证的初次非零与逐项复验均保留，所选不同用例最终为PG720、Linux Native/CLI/TUI633通过；Windows628通过/5已说明的平台skip。不是把重复复验次数或旧686/36/32基线累加。
- Linux最终独立发行组6通过/0skip；Windows最终独立发行组4通过/2 Linux SDK平台skip。源码/驱动分开、实际安装源、无PG依赖载荷、真实SDK、随机Schema所属核对、0004/0030前向与重复升级、0031双PID隔离恢复、真实COMMIT后丢ACK、严格PG业务0 SQLite均有当前证据。
- task17-sdk-protocol.log：真实mautrix0.21.1/python-olm3.2.16，已安装源的PG Store同时实现CryptoStore/SyncStore、非abstract；SDK协议及PG业务由当前31项Matrix用例和发行业务补充验证，不输出密钥。
- task17-final-check.log：`PM Python scripts/check --staged --base cbfc773dd7`，exit0，16项全通过、health738文件0blocking/0advisory（161.4s）。task17-final-plugin-boundary.log：`PM Python scripts/boundary_lint.py --check` exit0，847/26无新增边界。`scripts/gen_gateway_contracts.py --check` exit0。61固定锚点0漂移、31revision/29表模块/0031要求不变，迁移helper仅5处必要import调整。
- Windows/Linux实际逐文件hash均0差异，Python/测试无修改；两处生成变化仅JSDoc/description，JSON shape与TypeScript tokens不变，因此未以Python结果宣称执行过前端构建。
- 本Task本地commit创建前父为bd82697cb4；精确新commit由Task18启动记录补入。正式checkout始终clean，未推送/发布/合并/重启、未动正式Profile/秘密/业务数据。原统一Task24与七项非WSL缺证独立保留，不以本次局部平台证据覆盖。

### 可复核的实际命令展开

Windows命令从D:/AI/hermes-db-packages执行；HERMES_HOME均为D:/AI/hermes-db-task17-16c4a1931a33下相应test-profile，HERMES_RUNTIME_DIR=D:/AI/hermes-db-packages/.build/package-layout/runtime，HERMES_TEST_FILE_RETRIES=0，缓存位于独立root/runtime-tests*，必要输出设置PYTHONIOENCODING=utf-8。

```powershell
$env:HERMES_PYTHON='D:/AI/hermes-db-task17-16c4a1931a33/env-postgresql/Scripts/python.exe'
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db -j 2 --file-timeout 1200 -- --tb=short --hermes-distribution-source=D:/AI/hermes-db-task17-16c4a1931a33/source --hermes-postgresql-python=D:/AI/hermes-db-task17-16c4a1931a33/env-postgresql/Scripts/python.exe --hermes-sqlite-python=D:/AI/hermes-db-task17-16c4a1931a33/env-sqlite/Scripts/python.exe
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_cli/test_projects_cli.py tests/hermes_cli/test_kanban_cli.py tests/tui_gateway/test_groups_methods.py -j 2 --file-timeout 1200 -- --tb=short
$env:HERMES_PYTHON='D:/AI/hermes-db-task17-16c4a1931a33/env-business/Scripts/python.exe'
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts/test_api_native_http_sessions.py -j 2 --file-timeout 1200 -- --tb=short
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts/test_native_http_turn.py -j 2 --file-timeout 1200 -- --tb=short
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/test_distribution_initialization.py -j 2 --file-timeout 1200 -- -m 'integration or not integration' --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source=D:/AI/hermes-db-task17-16c4a1931a33/source --hermes-postgresql-python=D:/AI/hermes-db-task17-16c4a1931a33/env-business/Scripts/python.exe --hermes-sqlite-python=D:/AI/hermes-db-task17-16c4a1931a33/env-sqlite/Scripts/python.exe
```

Linux实际通过wsl -d Ubuntu-26.04调用；完整PG/首轮Native cwd为/var/tmp/hermes-db-task17-16c4a1931a33/source，纠正后的发行cwd为同root/test-driver。HERMES_HOME为相应test-profile，HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime，HERMES_TEST_FILE_RETRIES=0，PYTHONPYCACHEPREFIX在该独立task17 root。下列为进入相应cwd后的展开命令。

```bash
HERMES_PYTHON=/var/tmp/hermes-db-task17-16c4a1931a33/env-postgresql/bin/python bash scripts/run_tests.sh tests/hermes_db/postgresql -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source=/var/tmp/hermes-db-task17-16c4a1931a33/source --hermes-postgresql-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-postgresql/bin/python --hermes-sqlite-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-sqlite/bin/python
HERMES_PYTHON=/var/tmp/hermes-db-task17-16c4a1931a33/env-postgresql/bin/python bash scripts/run_tests.sh tests/hermes_db tests/hermes_cli/test_projects_cli.py tests/hermes_cli/test_kanban_cli.py tests/tui_gateway/test_groups_methods.py -j 2 --file-timeout 1200 -- --tb=short --hermes-distribution-source=/var/tmp/hermes-db-task17-16c4a1931a33/source --hermes-postgresql-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-postgresql/bin/python --hermes-sqlite-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-sqlite-matrix/bin/python
HERMES_PYTHON=/var/tmp/hermes-db-task17-16c4a1931a33/env-postgresql/bin/python bash scripts/run_tests.sh tests/hermes_cli/test_projects_cli.py tests/hermes_cli/test_kanban_cli.py tests/tui_gateway/test_groups_methods.py -j 2 --file-timeout 1200 -- --tb=short
HERMES_PYTHON=/var/tmp/hermes-db-task17-16c4a1931a33/env-business/bin/python bash scripts/run_tests.sh tests/hermes_db/postgresql/test_discord_backfill.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml
HERMES_PYTHON=/var/tmp/hermes-db-task17-16c4a1931a33/env-business/bin/python bash scripts/run_tests.sh tests/hermes_db/test_distribution.py tests/hermes_db/postgresql/test_distribution_initialization.py -j 2 --file-timeout 1200 -- -m 'integration or not integration' --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source=/var/tmp/hermes-db-task17-16c4a1931a33/source --hermes-postgresql-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-business/bin/python --hermes-sqlite-python=/var/tmp/hermes-db-task17-16c4a1931a33/env-sqlite-matrix/bin/python
```

## Task 18：独立审查、整改复验与交付判定

状态：completed

### 目标

对分包重构进行独立高风险审查，完成整改后的最终验证和可恢复交付记录。

### 涉及文件

- `docs/reviews/hermes-db-package-layout-review.md`。
- `docs/plans/hermes-db-package-layout-plan.md`。
- `受审查意见影响的实际源码/消费者/测试`。

### 依赖与接口

前置：Task17；输入为关联设计、基准归属及前置已验证commit；输出为本目标的已验证代码检查点。接口/数据边界遵守全局约束。

### 实施步骤

1. 执行verification-before-completion，按源码/接口/事务/作用域/SDK/迁移/发行验收逐项绑定证据。
2. 独立code-review检查完整diff与实际日志，按blocking/major/minor/suggestion处置；Reviewer方式不强制子Agent。
3. 出现修改则重新冻结并运行受影响验证，关闭所有必需major后给出本次重构READY_TO_MERGE；环境缺证给BLOCKED，已发现失败给FAILED。
4. 每Task记录本地commit/恢复点；不推送、发布或部署。原统一后端Task24平台缺口单列，不宣称全系统已验收。

### 验证方式

对照设计验收逐项读取完整diff/当前日志，记录独立审查的真实APPROVED或CHANGES_REQUIRED。任何整改后，重新执行受影响任务列出的标准runner命令，并按Task17核对最终源码与载荷对应；仅文档变更不重复全PG。

以上命令须exit0、无未解释的失败/错误；所有skip和必需环境缺口单列。执行标准静态检查，核对本任务语义/结构完成条件。

### 完成条件

独立APPROVED和整改后匹配当前代码的验证齐全；无遗留blocking/major，本次重构与原系统验收分别判定。

### 执行结果

已完成。Task17恢复提交`d6e5f62e75`；verification-before-completion核对最新完整命令、载荷与验收证据，独立code-review结论APPROVED，无遗留blocking/major。唯一统计口径minor已修正文档并获复核；审查后没有运行时代码、测试或依赖修改。本次重构状态READY_TO_MERGE，不合并、不发布。

### 验证证据

审查启动记录（历史检查点）：verification-before-completion已按Task17完整命令、原始安全Summary和冻结hash逐项核对；当前分支refactor/hermes-db-packages，审查tip为d6e5f62e75，开始审查后Python/TS/测试/依赖清单未改。正式checkout git status为空。独立Reviewer正审查完整范围cbfc773dd7..d6e5f62e75，尚未作最终APPROVED/CHANGES_REQUIRED，报告目标为docs/reviews/hermes-db-package-layout-review.md。该段为审查启动检查点；最终结论、完整命令exit0与恢复点见下方Task18最终完成记录。

### Task18完整命令退出状态补验（启动记录）

最终门禁复核发现，Task17虽已逐用例纠正环境/驱动调用并验证全部不同用例，但计划还字面要求完整批次命令本身exit0。为避免用局部修正掩盖完整命令状态，Task18在源码/测试不变的前提补做：

- task18-full-pg-linux.log：同一冻结test-driver，HERMES_PYTHON改为已具完整postgresql+messaging+matrix的env-business，完整postgresql目录-j2，发行source仍为独立source。
- task18-full-native-linux.log、task18-full-native-win.log：完整DB目录-j4，分别使用上述Linux/Windows env-business，DB option只传DB组；CLI/TUI的三文件49通过证据继续单独保留。
- 运行结果尚待收集，Task18保持in_progress/REVIEWING。独立Reviewer继续审查固定tip d6e5f62e75；不会修改已冻结源码。只有全批次exit0与独立APPROVED齐全后才完成最后任务。

### Task18已完成的最终门禁

- task18-full-pg-linux.log：完整postgresql目录131文件720通过/0失败/0skip，1630.7s，主进程真实exit0；真实随机Schema、全部SQLite拒绝、SDK及故障恢复覆盖与Task17冻结源码一致。
- task18-full-native-win.log完整DB：exit0，234文件579通过/0失败/5平台skip，552.9s；加此前同源码CLI/TUI 49通过，Windows所选合计628通过/5skip。
- task18-full-native-linux.log完整DB：exit0，234文件584通过/0失败/0skip，797.6s；加CLI/TUI 49通过，Linux所选合计633通过。234文件包含integration deselected文件，不把它们计作执行了PG用例。
- task18-final-check.log：exit0，全16项通过，health738文件0blocking/0advisory（169.2s）。task18-final-plugin-boundary.log exit0，module_to_core847/core_to_module26无新增；task18-gateway-contracts.log exit0。均在minor文档修正后执行。
- 独立Reviewer在完整PG exit0后核对最终日志并出具[独立审查报告](../reviews/hermes-db-package-layout-review.md)：APPROVED；无blocking/major，统计口径minor已复核关闭。

### 独立审查 minor 口径更正

Reviewer独立指出原final_counts.business_modules的389→315只排除__init__.py，未按设计排除表/迁移。已复核原398项和当前365项：非namespace为389→315；排除hermes_db/tables/、hermes_db/migrations/后的业务模块为328→254，净减74。映射同时保存两套命名明确的数值，当前设计/计划改正术语；历史工具审计打印的business标签为旧口径，原hash/数字不改写。这是文档/统计minor，不改Python、测试、SDK、Schema、事务或受验载荷代码；后续完整命令补验已全部exit0。

### Task18最终完成记录与实际命令

2026-11-10，独立审查范围为cbfc773dd7..d6e5f62e75及统计minor文档修正；最终受验运行时/测试仍为bd82697cb4加冻结记录明确列出的两份生成描述覆盖层。Task18没有Python、TypeScript可执行代码、测试、依赖清单或历史迁移修改；冻结载荷的17735项hash证据继续适用。全量命令失败的初轮记录保留，不能以旧686/36/32或重复复验累加充数。

下列最终命令均已真实执行并exit0；HERMES_HOME/HERMES_RUNTIME_DIR和缓存预先绑定Task17隔离root，所有解释器由项目PM建立，HERMES_TEST_FILE_RETRIES=0。Linux cwd是同归档独立test-driver，安装源是同root/source，两者不同；Windows cwd为独立实施检出。PG仅从既有私有配置路径读取秘密，并使用fixture核对所属的随机Schema。

```powershell
$root='D:/AI/hermes-db-task17-16c4a1931a33'
$env:HERMES_PYTHON="$root/env-business/Scripts/python.exe"
& D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db -j 4 --file-timeout 1200 -- --tb=short "--hermes-distribution-source=$root/source" "--hermes-postgresql-python=$root/env-business/Scripts/python.exe" "--hermes-sqlite-python=$root/env-sqlite/Scripts/python.exe"
# exit0: 234 files, 579 passed, 0 failed, 5 platform skips, 552.9s
```

```bash
root=/var/tmp/hermes-db-task17-16c4a1931a33
HERMES_PYTHON=$root/env-business/bin/python bash scripts/run_tests.sh tests/hermes_db -j 4 --file-timeout 1200 -- --tb=short --hermes-distribution-source=$root/source --hermes-postgresql-python=$root/env-business/bin/python --hermes-sqlite-python=$root/env-sqlite-matrix/bin/python
# exit0: 234 files, 584 passed, 0 failed, 0 skips, 797.6s
HERMES_PYTHON=$root/env-business/bin/python bash scripts/run_tests.sh tests/hermes_db/postgresql -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml --hermes-distribution-source=$root/source --hermes-postgresql-python=$root/env-business/bin/python --hermes-sqlite-python=$root/env-sqlite-matrix/bin/python
# exit0: 131 files, 720 passed, 0 failed, 0 skips, 1630.7s
```

CLI/TUI标准runner三文件两端各49通过的实际命令见Task17；不向其传DB专属option。原初轮非零日志和环境/调用修正均已具名保留。最终静态为PM解释器执行`scripts/check --staged --base cbfc773dd7`（16项通过，health738文件0blocking/0advisory，169.2s）、`scripts/boundary_lint.py --check`（847/26，无新增穿越）和`scripts/gen_gateway_contracts.py --check`（无漂移），均exit0。最终文档/映射/冻结元数据及审查报告再经一致性检查和`git diff --cached --check d6e5f62e75`，不以该检查替代业务测试。

最终交付文档检查：`PM Python .build/package-layout/task18_final_audit.py` exit0（task18-final-doc-audit.log），18项completed、398→365、业务328→254、root11、61锚点及唯一预期tables初始化import调整、10个本地链接均通过；审查后运行时代码变化为false。最终文档更新不影响已验代码或载荷，不重复全PG/全静态，以本次一致性及暂存区空白检查收口。首次`git diff --cached --check d6e5f62e75`指出审查报告EOF多一个空行；已仅去除该多余空行，后续同命令exit0，报告内容及APPROVED不变。

恢复点：Task18父commit为d6e5f62e75，最终Task18本地commit可由本节所在提交和`git log -1`直接定位；18个Task各有独立本地commit。代码恢复只针对隔离分支，不回迁数据、不降级Schema、不覆盖正式或用户修改。正式checkout仍在原规划分支且clean；本次交付不包含任何发布、合并、服务或Profile切换。

## 设计覆盖与最终验证

| 设计要求 | 任务 |
| --- | --- |
| 模块归属、动态/持久名称、独立checkout、基线 | 1 |
| 根11、后端/组合基础设施、driver-free入口 | 2、16 |
| 各业务域落位 | 3–10 |
| 纯规则、薄模块、36/10 Mixin及工作流收敛 | 11–16 |
| 无shim、依赖/插件边界、最终清单和净减少 | 16 |
| 表/迁移不变、双后端/实SDK/故障/发行与旧数据 | 17 |
| 最终独立审查、整改复验、恢复和交付状态 | 18 |

### 最终执行命令

执行Task17所列当前源码的完整DB Native/PG、Linux Matrix及独立source payload命令，另执行：

```powershell
& $env:HERMES_PYTHON scripts/check --staged --base $BaseRev
& $env:HERMES_PYTHON scripts/gen_gateway_contracts.py --check
git diff --check
```

若改动实际影响TypeScript或TUI/Desktop分发路径，按对应目录AGENTS和项目PM入口补齐其构建/类型检查；不能只凭Python绿认定前端可用。未触及的前端构建不伪称本轮已运行。

### 执行结果

- 单元/Native/消费者：Task17冻结匹配的所选DB/Projects CLI/Kanban CLI/TUI groups在Linux633通过；Windows628通过/5已说明的平台skip。不是全仓8237个测试文件均已执行，hash冻结只证明身份。
- 集成/实际SDK/并发/故障/关闭：Task18完整131文件PG命令exit0，720通过/0失败/0skip；Matrix十文件31项真实SDK/PG用例通过，实际双PID恢复和真实COMMIT后丢ACK有独立证据。
- Schema：31个revision、版本初始化及28表定义保持，tables初始化仅Task2必要catalog导入；0004/0030真实旧行前向/重复升级、0031重开及拒绝活跃租约回滚通过。未操作正式业务数据。
- 静态/共享契约/发行：Task1–15的15项静态与Task16/17的新增边界门禁后全16项均有证据；最终契约检查及Windows/Linux独立source payload、实际无PG依赖SQLite均通过。两处生成差异只为描述，TS代码token/JSON结构不变，不声称执行了前端构建。
- 手工/身份检查：398源处置、365模块/root11、非namespace389→315（业务328→254）、288/85方法签名、61锚点、回调和旧动态路径核验闭合；两端17735生产/测试条目与覆盖层hash0差异。Profile/池/pin/close/回执以实际合同补充，静态不能替代运行证据。
- 独立审查：[最终报告](../reviews/hermes-db-package-layout-review.md)为APPROVED；完整diff、AST行为差异、288/85公共方法签名、实际消费者/SDK/事务/回执/迁移及最终完整日志已独立复核。唯一minor为统计术语，已关闭；审查后仅交付文档与元数据变化，适用最终空白/文档一致性检查，不重复全PG。

### 验收标准检查

- [x] 398项及新增模块归属闭合，根11、文件数净减少。
- [x] 36/10 Mixin改显式组件，方法/DTO/回执/作用域与事务语义保持。
- [x] driver-free、无内部shim、无新增插件穿越及未审议依赖例外。
- [x] 当前源码SQLite独立安装、PG零SQLite完整业务、实际Matrix及双PID持久恢复通过。
- [x] 31个revision和29表模块锚点保持，旧PG升级/0031重开和独立载荷通过。
- [x] 最新verification-before-completion及独立APPROVED，整改后复验闭合。
- [x] 正式运行/数据未被开发步骤影响；原统一后端全局缺口仍如实单列。

### 未通过项目与最终状态

本次分包重构18/18 completed，最终状态`READY_TO_MERGE`，没有遗留必需失败、环境阻塞或未处理blocking/major。Windows Native五项平台skip及Windows发行组两项Linux SDK skip已逐项记录；适用行为有真实Linux证据。未执行全仓8237个测试文件或前端构建，不把hash核对当作运行验证。
原统一后端Task24及七项非WSL平台缺证继续独立保留，本次没有新增其完整实机验收证据，不宣称全系统验收完成。不推送、不发布、不创建PR、不合并或部署，不重启正式Hermes。

### Task5锚点计数说明更正

固定61项为31个revision + versions/__init__ + 29个表模块；29个表模块包括tables/__init__，其余28个为定义模块。Task1–4账本中“29个表定义”口径已更正；历史审计日志的同名字样为打印标签错误，源hash清单始终完整。31 revisions、版本初始化及28表定义内容不变；tables初始化仅有Task2必要catalog导入调整，29模块路径及metadata/表身份保持。没有新增迁移或Schema变更。

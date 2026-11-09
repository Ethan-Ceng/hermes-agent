# hermes_db 分包与模块收敛实施计划

## 关联设计与当前进度

- 设计：[按业务域分包](../designs/hermes-db-package-layout.md)。
- 全量归属：[398项基准映射](../designs/hermes-db-package-map.json)。
- 文档分支：`docs/hermes-db-package-layout`；实施分支：`refactor/hermes-db-packages`。
- 源码基准：`cbfc773dd7`，运行实现等价`0d69702244`。
- 整体状态：`IMPLEMENTING`；当前阶段：第一阶段机械落位；当前任务：Task4（待开始）；完成：3 / 18。
- 本轮已建立独立实施检出并完成Task1–3；未改正式源码/Profile/Schema/数据，未停止正式Hermes。
- 核心设计待决策：无；Task1隔离PM与PG基线已通过，Matrix实际SDK由Task6核对。原统一后端Task24及七项非WSL缺证独立保留。
- 更新时间：2026-11-09（Asia/Shanghai）。恢复位置：`D:/AI/hermes-db-packages`；从首个in_progress任务继续，不重跑整轮数据库选型。

## 任务依赖与全局约束

Task1–10形成可独立检查点的机械迁移；11–16为规则/组件/工作流收敛；17为完整验证；18为独立审查及整改复验。编号为推荐顺序，真实前置见各Task；不要求并行或子Agent。
环境阻塞时保持该任务blocked，可继续依赖已满足的独立pending任务；不能越过依赖、跳过必需SDK或把blocked计为完成。功能失败先定位根因并记录受影响范围，依赖该行为的任务不得推进。
每项开始先改in_progress；完成后立即记录实际修改、命令、退出码、通过/失败/skip、未验证项、恢复点并本地commit。当前18项均pending，准备方案不等于Task1已实施。

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

新增 `scripts/hermes_db_layout_audit.py` 和两份历史JSON基线、具名依赖分类账本 `docs/designs/hermes-db-package-baseline.md`。398项Git blob全部匹配；359个公共定义模块、239个外部依赖拥有者、内部依赖、动态路由/patch/Worker入口、外部DTO/异常和配置注册值已冻结。31个revision/29个表模块及tables init共61锚点，0031要求不变。基准两个提交只有文档差异，没有映射修订需要。

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

根Python文件113→90，总文件398→406（暂增8个必要包初始化；业务模块不增）。最终根11及净减少仍由后续分域/收敛任务实现，不能在本Task声称达到最终结构。398模块AST审计未发现导入与模块路径字符串以外逻辑漂移；31 revision和29表定义Git规范hash保持。tables/__init__.py只把catalog导入改为core.catalog，merge_data_repair.py只调整values导入，未改历史SQL、算法、DTO、错误、事务或池粒度。

正式checkout仍为规划分支且工作区干净；所有源码改动/测试在独立worktree，未操作正式配置或业务数据。

### 验证证据

沿用Task1专用PM解释器与隔离home/runtime，retries=0；下列日志仅在本检出的 `.build/package-layout/`。

- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts -j 4 --file-timeout 1200 -- --tb=short`，exit0，90文件504passed/0failed/4skipped，852.8秒（task2-native.log）。四项与Task1相同：1 POSIX、3 Linux SDK；没有把skip算通过。
- 同runner `tests/hermes_db/postgresql/test_schema.py tests/hermes_db/postgresql/test_domain_schema.py tests/hermes_db/postgresql/test_sessions.py tests/hermes_db/postgresql/test_surface_flow.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，4文件41passed/0failed/0skip，151.2秒（task2-pg.log）。独立DB/随机Schema归属fixture，surface进程SQLite拒绝护栏保留。
- 同runner `tests/hermes_db/test_optional_dependencies.py -j 1 --file-timeout 1200 -- --tb=short`，exit0，2passed/0failed/0skip，6.1秒（task2-optional.log）；真实子进程拒绝PG依赖导入仍完成SQLite会话/队列持久操作。
- 本地 `PM Python .build/package-layout/task2-audit.py`，最终exit0（task2-audit-accepted.log）：398模块机械AST等价、31 revision和29表定义hash不变。首轮审计工具对未存入object DB的新tables初始化blob执行cat-file失败；已修正为31+29锚点比较，初始化文件必要导入变化单列，不是业务失败。
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

新增8个必要空初始化文件逐项进入new_files台账；当前16个新增均为空命名空间，总Python文件414、根90。398项机械AST等价，全部源/新增文件有归属；31 revision与29表定义不变。公开plugin_api与boundary baseline均未改；没有旧内部路径shim或SQL行为变更。历史设计/执行证据保持原基准路径。

### 验证证据

沿用Task1 PM解释器/隔离home/runtime，所有日志在本地 `.build/package-layout/`，retries=0。

- `PM Python .build/package-layout/audit_mechanical.py`，exit0（task3-audit.log）：398 AST机械等价、源/新增归属闭合、31 revision/29表定义保持。
- `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts tests/hermes_cli/test_projects_db.py tests/hermes_cli/test_projects_cli.py -j 4 --file-timeout 1200 -- --tb=short`，exit0，92文件513passed/0failed/4skipped，276.8秒（task3-native.log）；skip仍为1 POSIX+3 Linux SDK，均未记通过。
- 同runner `tests/hermes_db/postgresql/test_projects_store.py tests/hermes_db/postgresql/test_verification_store.py -j 2 --file-timeout 1200 -- -m integration --tb=short --postgres-test-config=D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml`，exit0，2文件7passed/0failed/0skip，22.0秒（task3-pg.log）；使用所有权核对随机Schema验证真实持久化与store隔离。
- `PM Python -X utf8 scripts/check --staged --base cbfc773dd7`，exit0，15checks通过，health349文件0blocking/0advisory（task3-check.log）；最终计划/映射状态更新后暂存空白检查exit0。
- 未验证：完整DB/SDK/独立发行/最终升级与组件收敛仍属后续，原Task24缺证不变。
- 恢复点：本地提交标题 `refactor(storage): package projects and verification domains`；下一Task4。

## Task 4：Cron与指标分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 5：通用插件记录、Discord与Retain分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 6：Matrix分包并验证真实SDK

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 7：Sessions机械分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 8：Runtime与Worker机械分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 9：Rooms与附件机械分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 10：Kanban机械分包

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 11：收敛小型域并提取共享纯规则

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 12：Sessions改显式组件并收敛碎片

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 13：Runtime改显式组件与关闭所有权

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 14：Kanban按工作流合并

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 15：Rooms按工作流合并

状态：pending

### 目标

收敛26个room操作及关联读写，保持任务/策略/债务和附件事务边界。

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 16：关闭依赖例外与全量归属核对

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 17：独立发行、旧Schema与最终业务验证

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

## Task 18：独立审查、整改复验与交付判定

状态：pending

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

未执行。

### 验证证据

未执行；实施时记录实际解释器/源码commit、展开命令、退出状态、计数、日志、未验证项和恢复commit。

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

- 单元/Native/PG/实际SDK/并发/故障/关闭：未执行重构验证。
- Schema：设计要求零变化；旧数据前向/重复升级和0031重开仍须Task17实测。
- 静态/类型/共享契约/发行：重构后未执行。
- 手工检查：方案阶段已核对源目录和迁移依赖，未触碰正式Profile/进程；不替代未来运行验证。
- 独立代码审查：未执行重构审查。

### 验收标准检查

- [ ] 398项及新增模块归属闭合，根11、文件数净减少。
- [ ] 36/10 Mixin改显式组件，方法/DTO/回执/作用域与事务语义保持。
- [ ] driver-free、无内部shim、无新增插件穿越及未审议依赖例外。
- [ ] 当前源码SQLite独立安装、PG零SQLite完整业务、实际Matrix及双PID持久恢复通过。
- [ ] 31个revision和29表模块锚点保持，旧PG升级/0031重开和独立载荷通过。
- [ ] 最新verification-before-completion及独立APPROVED，整改后复验闭合。
- [ ] 正式运行/数据未被开发步骤影响；原统一后端全局缺口仍如实单列。

### 未通过项目与最终状态

实施推进中，当前3/18；局部验证见已完成Task，最终重构验收仍未执行；原Task24非WSL七项没有新增实机证据。准备方案阶段为`PLAN_READY`，不得标为READY_TO_MERGE。
实施后仅可根据真实终态填写本次重构`READY_TO_MERGE / BLOCKED / FAILED`，并与原系统统一后端整体验收状态分别报告。

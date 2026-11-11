# hermes_db infra 与业务持久化分层实施计划

## 关联设计与当前进度

- 设计：[两层边界设计](../designs/hermes-db-two-layer-boundary.md)；逐项映射：[模块、符号、消费者和固定资源](../designs/hermes-db-two-layer-map.json)。
- 源码基准：`0d8782ba8adb168a86abb6a8e338591d70d03428`。上轮精简已完成，本轮Task全部重新从pending开始；旧测试/旧审查只作参考。
- 正式目录：D:/AI/hermes-agent，HEAD `90a2987e8c5decb7997157ca17a301ff51ecce78`；正式运行实例不得修改、切换或停止。
- 隔离实施目录：D:/AI/hermes-db-packages。规划当前分支refactor/hermes-db-persistence-scope；目标实施分支`refactor/hermes-db-two-layer-boundary`，2026-11-11已创建。
- 规划提交：`f735660e8db182ca2b9fb8c139815a5bed2caf06`；保存用户原有10个暂存规划文件，不计Task实现完成。
- 整体状态：`VERIFYING`；阶段：Task20 R1独立复审与最终验证；当前实施任务：Task20；完成：19 / 20；阻塞：无；日期2026-11-12。
- 提交策略：沿用用户每完成一个Task立即更新计划并创建本地commit的要求。规划自检不代替Task1或业务验收；不推送/PR/合并/部署/重启。

## 验证策略修订：按本轮分层风险精简（2026-11-11用户指示）

用户最新指示：“不用特别多测试，因为我们只是拆分层，之前pgsql改造已经深度验收了”。本节优先于下文精简前的目录级全量/重复回归要求；20项实现、逐Task计划更新及本地commit、固定资源/安全边界及独立最终审查继续保留。

- Task13起只执行实际改动边界的关键合同：导入/装配、显式Schema、scope/target、原事务/锁/回执/关闭与必要真实SDK。纯搬迁先核对原函数/SQL/ABI及真实读取点，再选相关少量完整测试文件；不再扩展大批无关消费者，已有PG深度验收仅作背景，不计本轮新成果。
- 纯空白/文档及可证明运行代码等价的调整，采用compile/AST/源码身份与轻量门禁，不再触发业务整组重测。实际行为、事务/锁/回执、Schema、资源关闭或打包改变时验证受影响合同；失败仍如实保留并整改，不能通过删正常断言/强制skip取得通过。
- Task16冻结精简且有风险理由的最终文件清单；Task17仍冻结当前源码及61+4资源，并用项目PM建立原定全新载荷，不能把旧环境/旧结果充作本轮验收。
- Task18/19改为新载荷上的分层关键合同和冒烟：两后端真实读写/新PID恢复、无PG依赖SQLite、普通打开无DDL、0031与资源可用、scope隔离/数据集选择、一个真实COMMIT后丢ACK恢复及本轮SDK生命周期。不再运行完整tests/hermes_db、完整tests/hermes_state、完整tests/hermes_db/postgresql或旧PG各领域深测。
- 最终仍执行verification-before-completion和独立子Agent code-review。结论只覆盖本轮分层及实际精简验证；原统一Task24、七项非WSL缺证、Windows八项基准及具名环境skip独立保留，不宣称全系统重新验收。

## 范围与可判定边界

映射采用索引与按职责分区的JSON，全部文件都须随规划检查点保存。按索引sections读取当前Task的源码/Native/消费者/边界分区，校验sha256后合并；不要把整个机械追踪数据导入上下文。versioned目录保存每个消费者文件、确切行号集合及provider集合；完整45160项target-by-line追踪和方法AST在ignored .build中，由Task1按0d基准及既有boundary collector重新生成。

infra承担已解析数据源选择、连接/池、短事务、关闭、版本检查和显式迁移执行；domains及固定Schema资源承担业务持久化。应用Profile/秘密绑定、进程/RPC、文件和事件协调回到具体应用拥有者。根11个文件按实际职责分类，不能用空壳维持数量。

冻结映射含359个DB provider、141个外部provider，191个DB混合符号路由及134个Native符号路由；3033个文件45160个静态读取点采用索引表编码，29个Native patch候选单列。67个领域边界文件、63个应用capability函数和69个直接I/O站点均有所属Task。另有58个非Python引用文件区分活动消费者与历史证据。读取点数量含保留公共API及静态literal候选，不能冒充3033个必改文件；Task1/16按实际符号影响结算。

默认DB Python<=359、根11；目标路径并集含必要包初始化的当前投影348。投影不是已实现净减，迁出到应用的源码仍计全项目生产文件，不能以改名/迁出数字宣称算法减少。新增文件/health或预算无法闭合时先修订设计与映射，不损失正常覆盖或堆大文件。

### 必须保持

1. 0031要求、31revision、29表模块、61固定Python锚点及4项迁移资源原路径/字节/SQL/算法/metadata身份保持。tables/__init__读取core/catalog的事实依赖保留真实定义，无旧路径re-export shim；历史helper直接依赖继续可解析。
2. 数据源切换选择独立数据集，不搬迁、不双写、不回迁、不故障回落；新进程/新会话生效，不热换运行上下文或提示缓存。
3. 业务方法、参数、DTO、返回和异常身份保持；SQLite Schema诊断可增加就绪/版本信息并明确失败退出，原已有诊断字段保留，这不是业务RPC/Worker DTO变更；内部获取/装配/私有连接读取点可调整，但同步所有实际消费者/动态表/patch。只复用有实际消费者的窄能力，不增CRUD/SQL翻译、反射代理、后端注册框架或兼容flag。
4. 事务/连接/scope/锁顺序、CAS、回执、unknown commit、文件代次、pin及最后引用安全保留；不恢复已退役的repair-profiles、stranded adoption和搬移授权生成。
5. 原生SQLite业务创建/升级仍是可执行的显式操作。普通生产获取统一走open_existing/已初始化资源，不执行DDL；已有公开创建构造如保留，必须明确归创建/升级生命周期，不能被普通服务打开继续调用。不增加“兼容模式”布尔开关。
6. 原有短本地文件栅栏（archive cleanup、media collect/release）由包外应用持同一短事务协调，保持已有顺序；长准备/发布/网络/进程等待继续连接外。分层移动不新增持久token格式，也不拆开已有原子边界。
7. 插件走已发布的plugins.plugin_storage或ctx能力；若补实际命名获取facade，必须有当前Matrix/Discord/Retain消费者与行为合同。不用扩展私有import白名单掩盖依赖，不在核心导入具体插件。Matrix显式Schema命令注册在插件自身的现有CLI/setup扩展点。
8. 测试只用scripts/run_tests.sh；依赖仅用项目PM，任何PM/应用导入前先绑定隔离HOME/RUNTIME。保留正常测试断言，不新增source-reading/change-detector pytest；结构/引用/源码hash审计属于独立操作工具。
9. PG仅fixture核对数据库归属的独立随机Schema；不管理服务/扩展/角色，不触及正式Profile/配置/秘密/SQLite/PG业务数据。秘密仅从既有来源读取，不打印DSN/密码/加密材料或原始失败堆栈，日志仅本地ignored .build且不提交。
10. 原统一Task24、七项非WSL缺证及Windows Profile8项既有问题独立保留；环境阻塞或本轮必需失败不计Task完成，不把Linux通过写成Windows通过。

## 接口与所有者冻结

- factory.acquire_backend(settings,scope,*,sqlite_path=None,schema_token=None)返回真实BackendResource，不携带Session/Runtime。SQLite实际路径和PG业务schema token由应用/业务描述显式提供；无默认state.db推断。
- Transactions(engine,schema,*,schema_token,lock_timeout=10,statement_timeout=60)不再导入tables.metadata；所有构造/fixtures同步传token。
- 旧acquire_db/acquire_domain/acquire_profile_domain真实获取逻辑移到hermes_cli.db_sessions/db_domains；现有参数和业务返回保留，旧内部符号删除。root access仍保留实际release/liveness等业务定义。
- DomainResource/SessionResource归业务；DatabaseHandle保持真实Session/Runtime聚合。typed sessions.registry.acquire(settings,scope,*,build)由应用传实际构造callback，保留原引用计数而不另造通用registry。
- SessionDB.open_existing(db_path=None,read_only=False)是普通获取入口；显式创建/upgrade调用真实Schema算法。原公开初始化构造如继续保留，仍做真实工作并按创建语义验证。
- 根schema保留实际业务结果/能力汇总，infra PG执行器接收资源位置、版本、扩展和token；core/catalog及core/values真实定义继续服务固定资源。
- Matrix显式初始化：Database.create(sqlite_url,upgrade_table=PgCryptoStore.upgrade_table).start()，沿原SDK算法；普通启动Database.create(sqlite_url).start()后SELECT校验版本/表，再创建真实crypto对象。SDK 0.21.1源码已核对：默认upgrade即使最新也CREATE版本表，不能忽略该调用。
- 应用共享Profile/会话/领域装配归现有hermes_cli.db_setup拥有者的db_*兄弟；Cron归cron/storage_application，Kanban归hermes_cli/kanban_storage_*与agent的实际worker拥有者；Rooms文件/策略归Gateway，router生命周期归TUI，Retain线程归原插件目录。逐符号目标以映射为准。

## 可执行验证命令协议

以下是未来实施命令，尚未运行。Task1建立开发环境后可以直接使用；目录和变量均有具体定义，测试文件必须在对应Task创建后执行。

### 环境与PM

Windows bootstrap Python为D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe，运行前：

```powershell
$env:HERMES_HOME='D:/AI/hermes-db-packages/.build/two-layer-dev/profile'
$env:HERMES_RUNTIME_DIR='D:/AI/hermes-db-packages/.build/package-layout/runtime'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
& 'D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe' -m pm.build_env --source D:/AI/hermes-db-packages --out D:/AI/hermes-db-packages/.build/two-layer-dev/win/env --group dev --group test --extra postgresql --extra messaging
$DevPython='D:/AI/hermes-db-packages/.build/two-layer-dev/win/env/Scripts/python.exe'
$env:HERMES_PYTHON=$DevPython
$env:HERMES_TEST_FILE_RETRIES='0'
```

如果目标已存在先核对归属和进程，不覆写环境/不自动递归删除。Linux同样用已有隔离PM bootstrap，源是当前隔离checkout，dev/test+postgresql+messaging+matrix：

```powershell
wsl.exe -d Ubuntu-26.04 --cd /mnt/d/AI/hermes-db-packages -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-two-layer-dev/profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime /var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/test-env/bin/python -m pm.build_env --source /mnt/d/AI/hermes-db-packages --out /var/tmp/hermes-db-two-layer-dev/env --group dev --group test --extra postgresql --extra messaging --extra matrix
```

PG私有配置文件既有路径为D:/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml，Linux对应/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml；只传路径，不回显内容。

### 任务测试函数

```powershell
$ErrorActionPreference='Stop'
$ValidationSourceCommit=(git -c safe.directory=D:/AI/hermes-db-packages rev-parse HEAD).Trim()
function Invoke-SafeBatch {
    param([string]$Label,[string]$Executable,[string[]]$Arguments)
    $logRoot=Join-Path $PWD.Path '.build/two-layer-evidence'
    [IO.Directory]::CreateDirectory($logRoot) | Out-Null
    $runId=[guid]::NewGuid().ToString('N')
    $log=Join-Path $logRoot ($Label+'-'+$runId+'.log')
    & $Executable @Arguments *> $log
    $code=$LASTEXITCODE
    $summary=@(Get-Content -LiteralPath $log | Where-Object {$_ -match '^=== Summary:|^scripts/check:|^hermes_db boundaries:|^module_to_core:|^core_to_module:'})
    $record=[ordered]@{label=$Label;source_commit=$ValidationSourceCommit;cwd=$PWD.Path;command=@($Executable)+$Arguments;python=$env:HERMES_PYTHON;home=$env:HERMES_HOME;runtime=$env:HERMES_RUNTIME_DIR;exit_code=$code;summary=$summary}
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath ($log+'.json') -Encoding utf8
    $summary | Write-Output
    if ($code -ne 0) { throw "Batch failed: $Label exit $code; inspect private log with redaction" }
}
function Test-Native {
    param([string[]]$Files)
    $batchArgs=@('scripts/run_tests.sh')+$Files+@('-j','4','--file-timeout','1200','--','--tb=short','-ra')
    Invoke-SafeBatch -Label 'native-win' -Executable 'D:/Programs/Git/bin/bash.exe' -Arguments $batchArgs
}
function Test-NativeLinux {
    param([string[]]$Files)
    $batchArgs=@('-d','Ubuntu-26.04','--cd','/mnt/d/AI/hermes-db-packages','--','/usr/bin/env','HERMES_HOME=/var/tmp/hermes-db-two-layer-dev/profile','HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime','HERMES_PYTHON=/var/tmp/hermes-db-two-layer-dev/env/bin/python','HERMES_TEST_FILE_RETRIES=0','PYTHONUTF8=1','PYTHONIOENCODING=utf-8','bash','scripts/run_tests.sh')+$Files+@('-j','4','--file-timeout','1200','--','--tb=short','-ra')
    Invoke-SafeBatch -Label 'native-linux' -Executable 'wsl.exe' -Arguments $batchArgs
}
function Test-Pg {
    param([string[]]$Files)
    $batchArgs=@('-d','Ubuntu-26.04','--cd','/mnt/d/AI/hermes-db-packages','--','/usr/bin/env','HERMES_HOME=/var/tmp/hermes-db-two-layer-dev/profile','HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime','HERMES_PYTHON=/var/tmp/hermes-db-two-layer-dev/env/bin/python','HERMES_TEST_FILE_RETRIES=0','PYTHONUTF8=1','PYTHONIOENCODING=utf-8','bash','scripts/run_tests.sh')+$Files+@('-j','1','--file-timeout','1200','--','--tb=short','-ra','-m','integration','--postgres-test-config=/mnt/d/AI/hermes-agent/.build/postgresql/private/acceptance-postgresql.yaml')
    Invoke-SafeBatch -Label 'pg-linux' -Executable 'wsl.exe' -Arguments $batchArgs
}
function Check-Storage {
    Push-Location 'D:/AI/hermes-db-packages'
    try {
        Invoke-SafeBatch -Label 'static' -Executable $DevPython -Arguments @('scripts/check','--staged','--base','0d8782ba8a')
        Invoke-SafeBatch -Label 'db-boundary' -Executable $DevPython -Arguments @('scripts/hermes_db_boundary_lint.py','--check')
        Invoke-SafeBatch -Label 'plugin-boundary' -Executable $DevPython -Arguments @('scripts/boundary_lint.py','--check')
        Invoke-SafeBatch -Label 'contracts' -Executable $DevPython -Arguments @('scripts/gen_gateway_contracts.py','--check')
        Invoke-SafeBatch -Label 'whitespace' -Executable 'git' -Arguments @('-c','safe.directory=D:/AI/hermes-db-packages','diff','--cached','--check')
    } finally {
        Pop-Location
    }
}
```

原始失败输出只写本地ignored日志，工具仅输出上述固定安全Summary。独立SDK/PM构建同样捕获日志并只输出状态/错误类型；不得回显原始失败栈。开发阶段记录HEAD及当前改动hash，Task17后ValidationSourceCommit取冻结manifest的source_commit。执行Task2–16时所有指定Native组两主机运行；真实SDK/系统行为按实际platform marker记录。每条命令须保存展开后的解释器、cwd、环境路径、source commit、退出码和安全Summary，不只写函数名。Check-Storage仅在完成具体变更并核对staged文件之后执行；逐Task保存所有失败、修正、skip与未验证项。

## 状态变更记录

| 日期 | 状态 | 当前任务 | 原因 |
| --- | --- | --- | --- |
| 2026-11-10 | PLAN_READY | 无；下一项Task1 | 用户要求准备infra两层实施方案，全部20项pending；生产实现未开始 |
| 2026-11-11 | IMPLEMENTING | Task1完成；下一项Task2 | fresh双主机PM、基准Native/PG及结构/静态门禁通过，1/20 |
| 2026-11-11 | IMPLEMENTING | Task2完成；下一项Task3 | PG infra/Schema token/消费者及最新双主机合同、真实PG和静态通过，2/20 |
| 2026-11-11 | IMPLEMENTING | Task3完成；下一项Task4 | SQLite机制/应用策略、纯载荷恢复、双主机合同及最新全部静态通过，3/20 |
| 2026-11-11 | IMPLEMENTING | Task4完成；下一项Task5 | 两端完整Native、105消费者与资源合同exit0，4/20 |
| 2026-11-11 | IMPLEMENTING | Task5完成；下一项Task6 | 后端/业务/应用获取拆分，两端合同、真实PG及静态exit0，5/20 |
| 2026-11-11 | IMPLEMENTING | Task6完成；下一项Task7 | PG执行/业务就绪分离，双主机新发行载荷及真实PG前向重开exit0，6/20 |
| 2026-11-11 | IMPLEMENTING | Task7完成；下一项Task8 | Native完整批次与显式SQLite升级、无PG载荷验证exit0，7/20 |

## 任务依赖总表

| Task | 目标 | 前置 | 状态 |
| --- | --- | --- | --- |
| 1 | 冻结隔离源码、合同和完整调用点 | 无 | completed |
| 2 | 提纯PostgreSQL连接池与事务基础设施 | 1 | completed |
| 3 | 提取SQLite公共连接与WAL机制 | 2 | completed |
| 4 | 分离SessionDB连接状态、池与关闭语义 | 3 | completed |
| 5 | 拆开数据源选择和业务资源获取 | 2,3,4 | completed |
| 6 | 分离PG迁移执行与业务Schema就绪判断 | 5 | completed |
| 7 | 建立SQLite会话显式生命周期和普通打开 | 4,5,6 | in_progress |
| 8 | 闭合其他SQLite领域的首次创建与无DDL打开 | 7 | pending |
| 9 | 迁出Sessions与Runtime应用装配 | 5,6,7,8 | pending |
| 10 | 拆开Profile和媒体回收的存储与应用职责 | 9 | pending |
| 11 | 闭合Cron、Projects、Verification和Metrics边界 | 8,9 | pending |
| 12 | 迁出Kanban拥有者、进程和RPC适配 | 9,11 | pending |
| 13 | 拆开Kanban事务工作流与文件归档编排 | 10,12 | pending |
| 14 | 拆开Rooms附件、路由与应用生命周期 | 9,10 | pending |
| 15 | 闭合插件存储、API辅助库及真实SDK生命周期 | 6,8,9,11,14 | pending |
| 16 | 收口所有消费者、patch、文档与层次检查 | 2,3,4,5,6,7,8,9,10,11,12,13,14,15 | pending |
| 17 | 冻结最终源码并创建全新独立PM载荷 | 16 | pending |
| 18 | 执行双主机完整Native与消费者验收 | 17 | pending |
| 19 | 执行完整PG、发行与SDK故障恢复验收 | 17,18 | pending |
| 20 | 独立代码审查、整改复验和最终交付 | 18,19 | pending |

## Task 1：冻结隔离源码、合同和完整调用点

状态：completed

### 目标

冻结本轮源码/获取接口/SQLite生命周期与测试合同，确认隔离实施条件。

### 涉及文件

- 设计、计划、映射索引及全部分区文件、实际源码/测试基准清单、两主机隔离PM开发环境；本Task不提前改领域业务。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：无。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：源码/资源/接口和消费者基准一致，fresh环境与局部基准命令可复核；基准差异已修订映射，只有Task1计完成。

### 实施步骤

1. 在隔离checkout检查未提交内容、HEAD0d8782ba8a、正式目录HEAD90a2987e8c及引用路径；保留现有设计和用户修改。
2. 用户授权开始后在隔离目录建立refactor/hermes-db-two-layer-boundary；设计、计划、映射索引及全部分区文件创建单独本地规划检查点，再记录实际规划tip，不在正式目录切分支。
3. 建立全新Windows/Linux开发PM环境，先绑定独立HOME/RUNTIME；源码仅为当前checkout。验证解释器包路径及可选依赖，不复用旧冻结载荷假充当前源码。
4. 核对500个provider、全部359个DB文件、65固定资源、191个DB混合符号路由和134个Native符号路由；逐项处理基准差异。将3033个消费者文件/45160个静态读取点与29个Native patch候选分类为路径更新、接口更新或保留，记录普通SessionDB打开与显式创建调用点。
5. 运行新鲜基准Native/消费者及真实PG小组，记录原有失败/skip；全量旧709等不计本轮完成。建立后续Task能复用的安全结果记录格式和行为合同清单。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_domain_resources.py','tests/hermes_db/contracts/test_single_backend.py','tests/tui_gateway/test_session_resume_store_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_domain_resources.py','tests/hermes_db/contracts/test_single_backend.py','tests/tui_gateway/test_session_resume_store_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_schema.py','tests/hermes_db/postgresql/test_existing_media_grants.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

源码/资源/接口和消费者基准一致，fresh环境与局部基准命令可复核；基准差异已修订映射，只有Task1计完成。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11：完成隔离身份核对，目标分支refactor/hermes-db-two-layer-boundary，规划检查点f735660e8db182ca2b9fb8c139815a5bed2caf06。正式目录HEAD90a2987e8c且clean，CIM未发现引用隔离目录的应用进程。两个全新PM开发环境exit0；-I核对Python3.14.9、包来自当前隔离checkout、SQLAlchemy2.1.6/psycopg3.3.7/Alembic1.20.1。未改生产/测试/历史Schema，未删除测试。

从0d基准重新核对500源码/ABI hash、全部359DB模块、191/134混合符号路由、61+4固定资源、31编号revision/29表模块、根11。重建3033文件/45160读取点，2317路径更新候选、18445接口核对候选、24398保留；29 Native patch均交所属连接拆分Task核对。分类是逐符号实施输入，不把候选数当必改数量。1934个SessionDB调用分为1902测试准备、22评估、8生产普通打开、2显式恢复/repair；10个生产调用逐项列于证据。原审计误把versions/__init__.py计入revision，修正工具后完整重跑exit0，资源无差异。

### 验证证据

所有实际展开命令、解释器、cwd、隔离HOME/RUNTIME、源码commit、exitcode及安全Summary见[Task1基准与批次记录](../designs/hermes-db-two-layer-baseline.json)。完整原始日志仅ignored .build/two-layer-evidence；重建AST/逐读取点分类及其hash在.build/two-layer-dev/audit，摘要及hash已版本化。

- Windows新PM + Linux新PM：各exit0。两端-I来源/依赖探针：各exit0。
- Windows scripts/run_tests.sh三个计划文件：exit0，15 passed/0 failed/2平台skip（fork POSIX、实际Matrix SDK Linux）；同组Linux exit0，17 passed/0 failed/0 skipped。
- Linux真实PG test_schema.py + test_existing_media_grants.py：exit0，10 passed/0 failed/0 skipped。保留fixture随机Schema归属与全SQLite guard。
- 新Windows解释器scripts/check --staged --base 0d8782ba8a：exit0，16 checks ok；DB边界10130 imports/0 violations；插件边界、生成契约和git diff --cached --check均exit0。
- 规划检查点不计实现；本Task完成提交以本次紧随计划更新的本地commit为恢复点，实际hash在下一Task启动记录。Tasks2-20、最终冻结/完整验收和独立审查尚未完成；原Task24、七非WSL与Windows八项基准独立保留。

## Task 2：提纯PostgreSQL连接池与事务基础设施

状态：completed

### 目标

PG驱动/池/事务独立于业务表、Store和应用模块。

### 涉及文件

- `hermes_db/backends/__init__.py`。
- `hermes_db/backends/postgresql/__init__.py`。
- `hermes_db/backends/postgresql/changes.py`。
- `hermes_db/backends/postgresql/engine.py`。
- `hermes_db/backends/postgresql/expressions/__init__.py`。
- `hermes_db/backends/postgresql/expressions/json_paths.py`。
- `hermes_db/backends/postgresql/expressions/projections.py`。
- `hermes_db/backends/postgresql/transactions.py`。
- `hermes_db/errors.py`。
- `hermes_db/settings.py`。
- 新落位：`hermes_db/domains/runtime/postgres/change_tracking.py`, `hermes_db/domains/sql/postgresql.py`, `hermes_db/infra/backends/__init__.py`, `hermes_db/infra/backends/postgresql/__init__.py`, `hermes_db/infra/backends/postgresql/engine.py`, `hermes_db/infra/backends/postgresql/transactions.py`。
- 新建：`hermes_db/infra/__init__.py`。
- 新建：`hermes_db/domains/sql/__init__.py`。
- 新建：`tests/hermes_db/contracts/test_infra_independence.py`。
- 新建：`tests/hermes_db/postgresql/test_infra_independence.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task1。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：真实PG通用事务在禁止业务/应用导入的子进程中工作，底层0业务表依赖，正常事务与回执测试通过。

### 实施步骤

1. 移动engine/transactions至infra/backends/postgresql，changes移至Runtime，现有表达式/投影移至domains/sql/postgresql；不修改SQL/值身份。
2. Transactions显式接收schema_token，更新全部真实构造/fixture，移除tables.metadata的底层反向依赖。保留PID/目标/池配置键、连接预算和close_engines语义。
3. 先为真实PG与导入独立性合同取得基准红证据，再实现；unknown commit分类、SQLSTATE和无盲目写重试保持。
4. 同Task更新生产imports、动态路径、测试patch及符号审查条目；不在旧backends路径留shim。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_infra_independence.py','tests/hermes_db/contracts/test_domain_resources.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_infra_independence.py','tests/hermes_db/contracts/test_domain_resources.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_infra_independence.py','tests/hermes_db/postgresql/test_transaction_failures.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

真实PG通用事务在禁止业务/应用导入的子进程中工作，底层0业务表依赖，正常事务与回执测试通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task1恢复commit为a936df0ec1af7e627b6043e363dd9d598693e24f。实施前预算核算：原Task2机械落位新增infra/__init__与domains/sql/__init__会使359→361；将同职责的两个小型PG查询值助手收敛为domains/sql/postgresql.py，删除原空expressions初始化文件，抵消2个新增初始化文件，Task2保持359。SQL/算法/异常身份不变；这属于同职责模块合并，不宣称算法净删除。目标路径投影同步350→348，359上限不变。先加入Native及真实PG独立性合同并取得红证据。

实现结果：engine/transactions已归infra/backends/postgresql；Transactions要求显式schema_token，20个AST实际构造已同步，普通业务仍传固定metadata.SCHEMA。池/关闭实现、6个查询助手函数体与Worker change tracking经AST等价审计保持。所有旧PG内部Python路径清零，生产消费者、测试patch/string、发行探针及活动website文档同步，无shim。新infra方向守卫拒绝业务表/catalog/Store/应用依赖；22个现有查询值边缘按4个精确符号和原消费者审查，不放宽方向。DB实际359/root11、61+4 hash、31revision/29表保持，未删除业务测试。

### 验证证据

实际展开命令、解释器/cwd/HOME/RUNTIME、源码父commit、exitcodes、安全Summary和全部失败/整改记录见[Task2记录](../designs/hermes-db-two-layer-task2.json)。源码父a936df0ec1；当前生产源码审计hash b90dc3d9de62b029c02c285af2618d14e864dcf583bafac2d75c8922b10353f2，算法见记录。原始日志仅ignored .build/two-layer-evidence。

- 新Native/PG独立性合同在基准均exit1（缺少infra路径），取得红证据后实现。
- 最新Windows六文件完整组exit0：50 passed/0 failed/1 POSIX fork skip；Linux同组exit0：51 passed/0 failed/0 skipped。包含计划两文件及直接受影响的transactions/engine_lifecycle/json_paths/boundary_lint。
- Linux真实PG test_infra_independence.py + test_transaction_failures.py最新完整组exit0：6 passed/0 failed/0 skipped，包含真实do_commit之后丢ACK、锁/语句/池超时；test_insert_counts.py额外exit0，1 passed。
- Check-Storage最新全部exit0：scripts/check 16 checks ok（health 0 blocking/0 advisory）；DB边界10135 imports/0 violations；插件边界module_to_core847/core_to_module26；生成契约和空白检查exit0。
- 审计工具exit0：固定资源、预算、6函数体/池/变更观察AST、20构造token、运行Python旧路径0。失败记录包括工具非空缓存/最后摘要NameError、提前Linux组3 collection errors、22待审边缘和ruff两处check参数；已整改且完整组重跑，不抹除原失败。
- 最终冻结/完整发行、全量消费者及独立审查仍待Tasks17-20；本Task提交为本次记录后紧接的本地commit，实际hash记入Task3恢复点。

## Task 3：提取SQLite公共连接与WAL机制

状态：completed

### 目标

SQLite公共连接、锁安全和WAL机制成为纯技术能力。

### 涉及文件

- `hermes_db/backends/sqlite/__init__.py`。
- `hermes_cli/sqlite_util.py`。
- `hermes_state_lockguard.py`。
- `hermes_state_wal.py`。
- `hermes_cli/sqlite_runtime.py`。
- `hermes_cli/sqlite_safe_read.py`。
- 新落位：`hermes_cli/db_sqlite_policy.py`, `hermes_db/infra/backends/sqlite/__init__.py`, `hermes_db/infra/backends/sqlite/connections.py`, `hermes_db/infra/backends/sqlite/lockguard.py`, `hermes_db/infra/backends/sqlite/runtime.py`, `hermes_db/infra/backends/sqlite/safe_read.py`, `hermes_db/infra/backends/sqlite/schema.py`, `hermes_db/infra/backends/sqlite/transactions.py`, `hermes_db/infra/backends/sqlite/wal.py`。
- 新建：`hermes_db/infra/backends/sqlite/schema.py`。
- 新建：`hermes_cli/db_sqlite_policy.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task2。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：共享SQLite原语不导入CLI/Profile/SessionDB服务；纯载荷实际读写恢复，WAL及锁/close行为保持。

### 实施步骤

1. 将sqlite_util中连接/事务/DDL执行原语、sqlite_safe_read、sqlite_runtime、lockguard及WAL技术部分按映射移入infra/backends/sqlite。
2. Profile配置解析、升级提示归hermes_cli/db_sqlite_policy；技术接口接收已解析选项。保留原canonical错误类型，不复制异常或保留旧内部工具路径。
3. 普通open_db不执行initialize回调；业务Schema由显式生命周期调用。保留IMMEDIATE事务、always-close和rollback原异常保护。
4. 保持WAL-reset门禁、已活动库禁止降级、跨VM/网络FS判据、FD追踪及Windows锁重试；machine facts依旧通过hermes_platform。
5. 补齐独立纯SQLite实际读写/重开、无PG导入合同，并更新所有实际工具/消费者读取点。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_infra_independence.py','tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_sqlite_audit_guard.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_infra_independence.py','tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_sqlite_audit_guard.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

共享SQLite原语不导入CLI/Profile/SessionDB服务；纯载荷实际读写恢复，WAL及锁/close行为保持。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11：Task2实际恢复commit为124302809fe656ee33c3cfedecef7de8ed61cc0e。读取并校验Task3的sources-native分区hash、逐符号路由与当前SQLite实现。开始实现Task3生产/测试，完成前保持in_progress。

发现既定Task3路径将连接/事务/DDL执行3个模块及lockguard/WAL/runtime/safe_read共7个包外技术模块迁入hermes_db，使中间状态359→366；最终全计划投影348。此前发出中间提交范围澄清。续行要求允许推进中的临时状态，现按既有依赖与最终路径预算继续；逐Task准确记录实际数，最终DB<=359/root11仍为阻断门禁，不把迁入/迁出当代码净减少。

已核对的实际合同：WAL读取config与非阻塞_CONFIG_LOCK协调、安装类型repair hint属于应用；显式配置必须传入技术机制，保留锁忙时沿用已观测mode、WAL-reset门禁和never-live-downgrade。open_db当前11个initialize读取点需随新接口同步；Profile解析归open_profile_sqlite，业务callback仅显式initialize_profile_sqlite/infra Schema执行器执行，但真正普通获取无DDL要在Task7/8/15完整生命周期闭合；不得只删初始化能力。所有失败/未验证均不计完成。


补充实际影响：0d原基准独立导出、使用本轮新Windows解释器运行原TestDetectCrossVmFs，完整选定类exit1（16 passed/3 failed），与当前同3个POSIX路径断言一致。该类检查Linux /proc/self/mountinfo路径匹配，生产调用也仅Linux启用；按tests/AGENTS主机规则加platforms(linux)，19个用例全部保留在Linux执行，不用假OS或改算法获得通过。该新增Windows平台skip与原Windows八项基准分别记录。

Discord两个原私有SQLite helper跨界已移除，真实消费者通过原已公开plugins.plugin_storage模块的事务/WAL能力；public helper行为测试已加，未扩展私有infra白名单。插件baseline只移除两个精确旧键，847→845，未自动重刷其他权限。

### 验证证据

实际展开命令、父/子解释器、cwd/HOME/RUNTIME、source_parent=124302809f、每批dirty diff hash、退出码与失败/整改见[Task3完整记录](../designs/hermes-db-two-layer-task3.json)。原始日志只在ignored .build；独立0d基准导出archive SHA256与原WAL SHA256已记录，未使用旧环境结果充当本轮验收。

- 最终规定Native三文件+公开插件helper测试，Windows/Linux各exit0，6 passed/0 failed/0 skipped。
- 13文件直接消费者完整组：Windows exit0，168 passed/0 failed/24 skips；Linux exit0，189 passed/0 failed/3 skips。Windows含19个Linux mountinfo真实marker；原基准同3失败的exit1保留。Linux的2 macOS同步floor和1 Windows fcntl marker具名记录。
- 额外4文件真实OFD/WAL代次/退出恢复：Linux exit0，23 passed/0 failed/7 skips（6 macOS、1当前setconfig能力使退化场景不适用）；Windows exit0，5 passed/0 failed/25平台/能力skips。正常业务断言保留，未退役/删除测试。
- canonical连接、冷导入配置锁、旧daemon缓存模块skew三文件两端各exit0，26 passed/0 failed。
- 通过PM新建无extras的Windows纯SQLite载荷，构建exit0；-I证实SQLAlchemy/psycopg/Alembic/mautrix/asyncpg均不存在。以该解释器为父子执行统一runner的SQLite独立性合同，真实写入、不同PID恢复及覆盖open起点的SQL trace零DDL，exit0/1 passed。早期误标pure但实际使用PG开发解释器的那条命令不计纯载荷证据。
- Check-Storage最新完整exit0：scripts/check16 checks ok、health0 blocking/0 advisory；DB边界10141 imports/0 violations；插件module_to_core845/core_to_module26；生成契约及git diff --cached --check通过。未改TS/wire，未以Python结果声称前端构建。
- 独立操作审计exit0：65固定资源hash、31编号revision/29表、根11；runtime/safe_read/lockguard及原事务/DDL帮助函数AST保持，WAL纯机制函数等价；实际旧Python import清零（测试中模拟旧缓存模块有明确理由），infra无应用/领域表依赖。当前DB366，全项目生产Python3435→3438（+3），不宣称迁入/迁出减少算法。最终<=359仍待Task16及最终冻结阻断检查。
- 当前生产Python hash：a3777659260383a552dbb3a841c8973ca8469363619f0db744fca57b1fc58beb；计算方式及源码文件口径见审计。Task4以后及最终独立载荷/SDK/完整PG/审查未验；本Task紧随本次完成记录创建本地commit，实际hash写入Task4恢复点。

## Task 4：分离SessionDB连接状态、池与关闭语义

状态：completed

### 目标

SessionDB与底层连接池、FD预算和代次保护的所有权分离。

### 涉及文件

- `hermes_state.py`。
- `hermes_state_dbfile.py`。
- `hermes_state_readpool.py`：实际FD预算实现随本Task归infra，不留旧路径shim。
- `tests/hermes_db/contracts/test_session_connection_pool.py`：真实无应用导入的池借还、关闭与数据读取合同。
- 新落位：`hermes_cli/db_session_schema.py`, `hermes_db/infra/backends/sqlite/generation.py`, `hermes_db/infra/backends/sqlite/session_connections.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task3。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：SessionDB业务对象不再拥有底层池实现；完整Native state组通过，代次/FD/锁/关闭行为无回归。

### 实施步骤

1. 按Native方法路由迁出读池、writer连接、重试、文件代次、WAL丢失、退休连接和关闭机制；不向infra传入完整SessionDB self。
2. 连接状态由具体SQLite连接资源持有；SessionDB保留会话/消息/token等业务。同步所有真实私有字段/方法读取点，不增加属性反射代理或旧字段兼容层。
3. 原schema/FTS/quarantine与进程holder策略仍由业务/应用生命周期提供；底层只执行捕获参数和纯技术判据。
4. 保持读连接预算按文件共享、非阻塞退化到writer锁、close与在途读竞争、lost generation不危险checkpoint及最后释放writer flush顺序。
5. 原有超复杂函数按既有职责拆小并满足health ratchet，不通过noqa/批量allow增加债务；算法与SQL保持。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_native_file_boundaries.py','tests/hermes_db/contracts/test_domain_resources.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_native_file_boundaries.py','tests/hermes_db/contracts/test_domain_resources.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Native -Files @('tests/hermes_state')`及同参数`Test-NativeLinux`：完整目录实际exit0，平台项具名。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

SessionDB业务对象不再拥有底层池实现；完整Native state组通过，代次/FD/锁/关闭行为无回归。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task3实际恢复commit为a3fb7f4b5644c3dbb5a5225996099af4a107567e。当前先核对SessionDB所有连接状态、纯技术方法与业务Schema边界，所有资源读点与patch须同步，禁止传整个SessionDB self或增加旧私有字段反射/兼容层；完整Native state两端exit0为必需。

当前Task核对修订：_execute_write含压缩租约/FTS fail-open和提交后merge；_read_ctx含业务快照pin；_ensure_db_file_generation访问state_meta。它们必须按真实子职责拆开，不能整段搬进infra，也不把有业务行为的会话方法伪装为旧路径兼容壳。读取/事务机制只接收捕获参数或明确连接，资源不持有整个SessionDB。原映射Task16的hermes_state_readpool实际属于Task4机制，已重新映射。先为独立具体连接资源建立红测，再接入生产SessionDB和全部读取点。

### 验证证据

实施诊断中，尚未完成。首轮完整Windows目录222文件真实exit1：1676 passed、79 failed、7 errors、141 skipped；环境C盘可用仅0.70GiB，许多repair合同被既有10GiB余量保护阻断。后续控制器在同一隔离checkout的D盘（可用1159.70GiB）绑定独立TMP/TEMP；不改余量门槛，不删测试，不计首轮通过。定点修正动态读取点、真实patch seam及原测试清理后，最终仍须两端完整目录exit0。

精确0d导出+本轮新Windows解释器已复现：Linux flock/proc-lock两个测试失败（独立2文件1passed/2failed/2skipped），live-file replacement两个测试WinError32和interrupted snapshot共享clock teardown错误（2文件1passed/2failed/1error）。前四个保留原断言并加真实Linux marker；snapshot按原断言触发Timeout后恢复共享clock。它们在Linux实跑，不能把Windows skip计为验证，也不解除原Windows八项/非WSL缺证。

实际writer/锁/代际状态、预算与物理关闭已迁入具体资源；应用取证文件操作及writer策略保留在db_session_schema。业务压缩/FTS/健康/快照与token drain由SessionDB执行，未传完整SessionDB给infra。新DB模块中间数368、root11，最终硬359门禁保持。所有失败与后续完整结果将写入Task4证据及恢复commit。


2026-11-11继续整改/冻结：完整接收者审计同步85个Native目录外测试文件及所有具名patch；ACP编辑器连接、独立ResponseStore和测试自身连接包装器保留原所有者。迁出的纯锁错误判据最初缺失sqlite3绑定，导致一次完整Windows223文件32pass/32fail/215error/11skip、Linux223文件33pass/41fail/215error/1skip，以及外部84文件162pass/223fail/304error/7skip，均exit1且不计验收。已保持runtime导入安全性并核对SQLite主结果码5/6，修正旧_lock和截断展示接收者清单。代表组最新Windows126pass/0fail、Linux134pass/0fail；初始化准备失败诊断/创建前无副作用红测先失败，再两端各2pass。旧内部无用技术导出已移除，公开异常仍由原公开facade提供。

冻结生产源码hash为62dbb6098df2967b4d8bbe64f96cbee63e2e2c565c534bf953bd5158aafbfc88（操作审计task4-audit.json；3439生产Python，原基准3435，净+4，不把迁移算净减少）。固定65资源、31revision、29表、root11，703种/992处审计SQL字面量对Task3父提交完全相同；infra应用导入及退役实际导入0。完整Check-Storage已对该候选实际exit0：16check、health无新增豁免/债务、DB10180/0、plugin845/26、生成契约及空白均0。Native完整目录现为224文件（新增初始化行为合同；原4个DDL错误方法完整迁出巨型测试文件），双主机最新完整批次正在执行。Task4仍in_progress、未提交；不能用此前任何失败/局部通过替代该完整门禁。

2026-11-11后续完整失败及整改：source-local Linux224文件1871pass/17fail/16skip，均由取证文件头解析的单个旧延迟导入引起，已改向实际infra定义并加入独立符号绑定审计，不恢复shim。Windows85消费者文件2073pass/3fail/27skip；其中同类Thread替身污染已统一使用窄helper，其余两个TUI工作区断言在精确0d+安装树内TMP复现0pass/2fail，在独立D盘随机TMP原断言2pass。外部复验范围扩大为105测试文件（另1fixture），所有原断言保留。第三版Linux开发快照tree e74def9bde9ac85fb44dc1a9ee63e8ef368affac，tar SHA256 a8177a01bf6407b97ae8555aea13f928b6cb6f4182c4ea787833bdd3240d414b，逐23939项校验后fresh PM构建并再次校验真实导入来源；它是Task4开发证据，不代替Task17最终冻结。最新生产hash a8996da469633348f8d68a14ef4d7aa9b711ccdbdb997240433a874ca9e78f1b；最新完整批次尚在执行，Task4保持未完成。

最新完整Native state门禁：Windows224文件1757pass/0fail/147skip，exit0，343.8秒；Linux第三版隔离源码224文件1888pass/0fail/16skip，exit0，339.0秒。两端真实用例总数均1904，skip按原生能力与OS marker保留，不计平台验证。当前105消费者双主机完整批次及3文件资源合同仍待结束，保持Task4 in_progress。

Task4完成结算（此前诊断/失败历史全部保留）：生产hash a8996da469633348f8d68a14ef4d7aa9b711ccdbdb997240433a874ca9e78f1b。最新完整Windows Native224文件1757pass/0fail/147skip、Linux224文件1888pass/0fail/16skip；Windows105消费者文件2283pass/0fail/27skip、Linux105文件2309pass/0fail/1skip；三文件资源合同Windows8pass/0fail/1skip、Linux9pass/0fail/0skip，六个批次均实际exit0。最新静态16check/health0、DB10180/0、plugin845/26、生成契约和空白均exit0，提交前再次核对。固定61+4、31revision、29表、root11保持；DB中间368及全项目生产Python3439不是最终预算/净减少声明。无退役测试删除，原四个正常Schema错误测试整类迁移，新增初始化与独立资源行为合同。

完整安全命令记录、实际解释器/cwd/source身份、两端SDK版本、退出码、逐文件skip和失败整改见[Task4证据](../designs/hermes-db-two-layer-task4.json)及[诊断账本](../debug/hermes-db-task4-consumers.md)。原始日志仍ignored；最终Task17–20冻结/完整PG/发行/真实SDK/独立审查未执行，不解除原统一Task24、七项非WSL缺证或Windows八项基准问题。本地Task4提交创建后在Task5启动记录实际hash；不推送/合并/部署。

Task4提交后校验补记：本轮额外比较实际Git blob时发现sources-native分区的索引值记录了Windows CRLF字节，工作区校验未覆盖Git的LF归一化。已创建仅改映射索引的独立本地补丁提交0417ac0f3aab60e34cad42fe66c22024bca18a48，并逐项重新验证所有已提交分区。原Task4实现提交11f46b5dc5d6af39f24ab181debfb41771d89e15及生产源码未改。当前Task5字段已完整备份/恢复；所有后续分区写UTF-8/LF，操作审计同时校验working/index/committed三方，记录该验收缺口与修正，不以旧工作区通过掩盖。

## Task 5：拆开数据源选择和业务资源获取

状态：completed

### 目标

factory只选择技术资源；Profile获取与业务资源装配明确归应用。

### 涉及文件

- `hermes_db/access.py`。
- `hermes_db/backends/sqlite/acquire.py`。
- `hermes_db/contracts.py`。
- `hermes_db/core/resource.py`。
- `hermes_db/core/session_resource.py`。
- `hermes_db/factory.py`。
- `hermes_db/handle.py`。
- `hermes_db/health.py`。
- `hermes_db/integration/domain_composition.py`。
- `hermes_db/integration/profile_context.py`。
- `hermes_db/scope.py`。
- 新落位：`hermes_cli/db_diagnostics.py`, `hermes_cli/db_domains.py`, `hermes_cli/db_scope.py`, `hermes_cli/db_sessions.py`, `hermes_cli/db_setup.py`, `hermes_db/domains/resource.py`, `hermes_db/domains/runtime/sqlite.py`, `hermes_db/domains/sessions/resource.py`, `hermes_db/domains/sessions/sqlite.py`, `hermes_db/infra/resource.py`。
- 新建：`hermes_db/infra/resource.py`。
- 新建：`hermes_cli/db_domains.py`。
- 新建：`tests/hermes_db/contracts/test_infra_resource_ownership.py`。
- 新建：`tests/gateway/test_storage_owner_acquisition.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task2, Task3, Task4。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：技术选择、业务资源及应用Profile解析单向依赖，普通消费者正常获取/释放且错误owner在开库前拒绝。

### 实施步骤

1. 实现factory.acquire_backend(settings,scope,*,sqlite_path=None,schema_token=None)，返回真实BackendResource；SQLite路径与PG schema token由调用方显式提供，不推断Profile。
2. 将acquire_db/acquire_domain/acquire_profile_domain及Profile绑定获取移入hermes_cli/db_sessions.py和db_domains.py；已有参数/业务返回保持，所有旧内部消费者一次迁移。
3. DomainResource/SessionResource移入业务域；DatabaseHandle保持真实Session/Runtime业务聚合定义；infra资源没有业务成员。
4. scope中bind_profile_home/OwnedProfileContext归db_scope；public ordinary获取在应用入口做owner-only检查，Worker不能直接获取owner数据库。
5. 已有SQLiteSessions/SQLiteRuntime按业务归属拆分并注入捕获作用域；保留既有必要代理，不新增反射代理或注册框架。
6. 验证同一进程两Profile、线程跳转、peer close和fork后重获资源。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_infra_resource_ownership.py','tests/gateway/test_storage_owner_acquisition.py','tests/hermes_cli/test_db_setup.py','tests/tui_gateway/test_session_resume_db_ownership.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_infra_resource_ownership.py','tests/gateway/test_storage_owner_acquisition.py','tests/hermes_cli/test_db_setup.py','tests/tui_gateway/test_session_resume_db_ownership.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_single_backend.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

技术选择、业务资源及应用Profile解析单向依赖，普通消费者正常获取/释放且错误owner在开库前拒绝。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task4实际恢复commit为11f46b5dc5d6af39f24ab181debfb41771d89e15。Task4六个完整Native/消费者/资源批次及提交前静态均exit0，4/20；Task5尚未验证。先按索引核对当前路线，建立独立infra资源及owner-only开库前拒绝红测；SQLite适配只接受应用捕获的激活callback，不从业务层读取Profile/秘密。

### 验证证据

未执行本Task业务验证。实施后记录实际展开命令、source/解释器/cwd、退出码、passed/failed/skipped、失败修正/未验证项及恢复commit。

Task5当前核对：原_bound_method同时服务Sessions与Runtime，按真实消费者归公共业务resource模块一次定义；边界检查器需把该共享模块与具体领域包区分，不能通过新增跨层豁免掩盖。SQLite业务适配接收应用捕获的activate及原固定名字分发表解析函数，保留现有必要代理和晚绑定patch行为，不从业务层导入Profile/Native应用facade。BackendResource选择与短事务借还归infra，DomainResource保持每个业务视图独立关闭，进程池不因peer/board close失效。原新红测Windows2文件1pass/3fail（缺新入口、两个Worker配置先读），现有两Profile/线程/peer合同为绿；失败与后续完整证据继续保留。

Task5中期证据：规定的四文件合同组Windows/Linux各24pass，exit0。当前PG三文件完整批次（single_backend、新公开插件历史、Profile删除身份竞态）9pass/0fail，exit0；真实Schema仍由fixture确认归属并随机隔离。边界行为新增两例先11pass/2fail，修正共享模块方向约束后13pass；实际DB依赖10008/0。自动审批曾把增加拒绝规则误判为允许范围扩大并拒绝，未绕过；只读内存比较10092条边保留24个旧拒绝、增加16个拒绝、移除0个拒绝后，精确hash重试获准。该拒绝及证明保留，不新增许可。

插件原Achievements扫描是实际消费者，改用已发布plugins.plugin_storage模块的session_history上下文，保留查询、identity及关闭语义；原业务测试及新SQLite异常关闭合同均通过。私有插件跨界引用从845降843，精确删除两个退役允许项，不自动更新/扩展基线。此消费者闭合提前于Task15，但不能计作Task15完整插件/SDK生命周期成果。Windows完整扩展合同遇到264字符媒体fixture路径失败；独立短D盘TMP下原三例3pass，生产授权、文件名、pin及路径算法未改。双主机扩展批次/最终静态仍在执行，Task5保持in_progress。

Task5最新扩展合同：同一106文件组Linux566pass/0fail/4skip，exit0；Windows初次559pass/3fail/8skip均为264字符文件路径错误，短D盘独立TMP完整重跑562pass/0fail/8skip，exit0，原断言全部保留，两端真实总数均570。规定四文件组Windows最新24pass、Linux最新24pass，均exit0。操作审计生产hash d8bde783dd66ff8b98131c6a013a81dd4675fcd3a2b800a27e76b3efdb407c21，65固定资源/31revision/29表/root11、原固定runtime分发表及190处受影响实际SQL字面量保持；DB中间368，原计数口径全项目Python3443对基准3435（该旧口径含插件内测试，非算法净减少）。暂存源码与映射三方hash门禁及最新Check-Storage仍待完成，Task5尚不计完成。

Task5完成结算：最终生产hash8dc212d75c7ba425675d3f2e3d6f13f0f07df796ddec1d99dd4cd4c431144b6d。规定完整四文件组Windows24pass/0fail、Linux24pass/0fail，真实PG三文件组9pass/0fail，均最新exit0。扩展106文件组Windows562pass/0fail/8skip、Linux566pass/0fail/4skip；扩展组之后仅有已记录的EOF格式修正及基准复现支持的测试事件预算修正，原业务断言未删除。最新Check-Storage16check/health0、DB10008/0、plugin843/26、生成契约和空白均exit0。working与暂存Git分区hash校验通过，提交后还核对全部committed blob。

实际定义、全部消费者/模块别名patch、固定分发表、190处SQL及65资源审计，展开命令/解释器/cwd/source身份、退出码、skip和全部失败整改见[Task5证据](../designs/hermes-db-two-layer-task5.json)及[Task5诊断记录](../debug/hermes-db-task5-resource-acquisition.md)。没有删除正常或退役测试，旧内部路径无shim；公开插件历史API有实际消费者。DB中间368和全项目旧口径3443并非最终359门禁或算法净减少。Task6–20、最终冻结/完整SDK/发行/独立审查及原统一Task24、七项非WSL、Windows Profile8均不在本Task宣称完成。本地Task5提交创建后在Task6启动记录实际hash。

## Task 6：分离PG迁移执行与业务Schema就绪判断

状态：completed

### 目标

PG迁移执行不内置业务Schema，完整历史链保持。

### 涉及文件

- `hermes_db/core/schema_status.py`。
- `hermes_db/schema.py`。
- 新落位：`hermes_db/domains/schema_status.py`, `hermes_db/infra/backends/postgresql/schema.py`。
- 新建：`hermes_db/infra/backends/postgresql/schema.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task5。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：通用PG生命周期无业务名单和表导入，历史资源零变化，普通打开0DDL，真实升级/重开通过。

### 实施步骤

1. 将版本读取/升级锁/扩展核对/Alembic执行提到infra/backends/postgresql/schema；接收显式资源位置、revision、扩展需求和schema token。
2. 根schema保留实际业务就绪聚合和现有公共结果；core/schema_status移到domains/schema_status，core/catalog保留真实业务Schema清单以满足固定tables/__init__导入。
3. 保留0031、31revision、29表及61+4原路径/字节/metadata身份；必要helper和其直接依赖继续可解析。
4. 普通获取只读检查，缺配置/未初始化/缺扩展明确失败；不自动创建扩展/角色/服务，不降级或压平版本。
5. 独立安装载荷执行从旧revision前向、重复upgrade及0031重开，随机schema所有权fixture全程保留。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/test_distribution.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/test_distribution.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_schema.py','tests/hermes_db/postgresql/test_distribution_initialization.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

通用PG生命周期无业务名单和表导入，历史资源零变化，普通打开0DDL，真实升级/重开通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task5实际恢复commit为58fb51560a8ea841af30cb4ab996afa1c642e0bf，提交后11个映射分区实际Git blob全部校验；当前5/20。Task6只拆当前PG迁移执行、版本/扩展检查与业务就绪汇总，不改固定61+4或历史31revision。现有旧revision升级测试直接读取_prepare_schema；同步真实infra定义与显式业务资源参数。发行测试的载荷选项必须实际提供；用本Task全新独立源快照及PM载荷，不沿用Task4/5开发环境作为发行验收。

### 验证证据

未执行本Task业务验证。实施后记录实际展开命令、source/解释器/cwd、退出码、passed/failed/skipped、失败修正/未验证项及恢复commit。

Task6红测：归属校验的独立随机PG Schema上，原五项合同5pass，新技术资源/普通获取零DDL合同因infra入口尚不存在而1fail，完整批次exit1。实际表清单读取同时服务就绪汇总和非空未版本库拒绝，统一迁入infra。根业务Schema保留0031/扩展需求和原动作文案，显式执行传固定metadata的SCHEMA token、真实资源路径及目标revision。所有分区写UTF-8/LF并同步hash，真实发行参数/最新业务/静态门禁仍待执行。

Task6实现及初次真实PG复验：技术版本/表清单读取、显式扩展需求、原升级锁与Alembic执行已经分离，业务所需版本/表聚合及公共状态字典保持。SQL扩展名由原固定pg_trgm条件改为同语义绑定参数，公共表清单查询去除重复定义；历史迁移SQL/资源零修改。原_schema.py的_prepare_schema读取点（含实际发行子进程）6处已同步明确需求与原动作提示。真实PG schema/startup/merge-upgrade三文件15pass/0fail，exit0；当前正在准备双主机全新独立Task6发行载荷及其余受影响PG合同。Task6尚未完成，不以环境缺选项skip替代发行验证。

Task6完成结算：最终生产hashe59835f6fbd8b65c1cea1e5c0490ee73afc69949a9f71ad753a75b36899a0359。独立源码tree 8185a76fb71c8080058ff7b3b22b47cdc9e61eaf，tar SHA256 53c4469f61cbdb5502ab9d2e5a27f4560185d75d4fc73a917f99540c2c884136，逐23951项校验；两主机共五个全新PM载荷，每个均在-I下核对真实模块路径、已装/缺失驱动及全部源码hash。Windows发行完整3pass/0fail/1skip（仅Linux Matrix SDK marker）；Linux发行完整4pass/0fail/0skip；PG schema与发行完整2文件8pass/0fail/0skip，均实际exit0。真实PG辅助批次15pass与33pass，涵盖原升级锁、旧revision历史、搜索/媒体/房间、无DDL普通获取及缺扩展拒绝；不自动管理扩展/角色/服务。纯SQLite独立载荷实际读写并由新PID恢复；Linux真实SDK及PG子进程恢复通过，PG拒绝全部SQLite连接。

Linux PG新载荷PM成功后，首次-I探针启动收到WSL 0x8007274c、exit-1；只读枚举确认Ubuntu仍Running后，同一新载荷重试exit0，未重启或管理服务；失败记录不计通过。最新Check-Storage16check/health0、DB10019/0、plugin843/26、生成契约和空白exit0；完成记录只改文档，暂存与已验源码tree代码一致。固定61+4、0031、31revision、29表、root11与实际Git blob一致；DB中间369，最终359尚未验证。活动后端文档已同步；skills/AGENTS无实际旧路径引用；没有删除测试。展开命令、实际解释器/cwd/source、退出码、skip与故障恢复见[Task6证据](../designs/hermes-db-two-layer-task6.json)。本地Task6提交后在Task7启动记录实际hash。

## Task 7：建立SQLite会话显式生命周期和普通打开

状态：completed

### 目标

SQLite会话的普通服务打开与显式创建/升级成为不同真实入口。

### 涉及文件

- `hermes_cli/db_cmd.py`。
- `hermes_cli/db_parser.py`。
- `hermes_cli/db_setup.py`。
- `hermes_state_schema.py`。
- 新建：`hermes_cli/db_session_schema.py`。
- 新建：`tests/hermes_db/contracts/test_sqlite_open_lifecycle.py`。
- 新建：`tests/hermes_cli/test_db_sqlite_upgrade.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task4, Task5, Task6。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：普通服务获取0DDL且首次Profile创建可用；旧Schema显式升级与原Native恢复能力有真实证据。

### 实施步骤

1. 增加SessionDB.open_existing(db_path=None,read_only=False)，使用已经拆出的连接资源及SELECT/PRAGMA只读就绪检查，普通acquire/registry/服务启动全部迁入此入口。
2. 保留现有公开业务创建构造/迁移算法，明确它是显式创建/升级操作；新建Profile/首次创建和现有db upgrade主动调用。禁止根据普通open中的exists分支偷做初始化，也不添加compat flag。
3. 根SessionSchema/FTS算法保持；旧版本、损坏Schema的普通打开明确拒绝并指向显式upgrade/doctor修复；现有升级和恢复断言移到相应显式生命周期测试，不能删正常断言。
4. 扩展现有hermes db status/upgrade的SQLite分支及正常Profile setup/创建入口，保持外部命令形状；不管理正式数据。
5. 用实际SQL trace证明显式init可创建/读写，重复安全，普通服务重开和新PID恢复0DDL；测试数据准备明确初始化，不用全局monkeypatch隐藏DDL。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_sqlite_open_lifecycle.py','tests/hermes_cli/test_db_sqlite_upgrade.py','tests/hermes_cli/test_db_setup.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_sqlite_open_lifecycle.py','tests/hermes_cli/test_db_sqlite_upgrade.py','tests/hermes_cli/test_db_setup.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Native -Files @('tests/hermes_state')`及同参数`Test-NativeLinux`：完整目录实际exit0，平台项具名。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

普通服务获取0DDL且首次Profile创建可用；旧Schema显式升级与原Native恢复能力有真实证据。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task6实际恢复commit为4767f5939ed685b84764a78667ef8138fbbcdaad，11个working/committed分区hash已复核，当前6/20。db_session_schema.py在Task4已承接应用文件/连接策略，本Task继续扩展真实生命周期而非再建重名模块。先建立无DDL实际trace、缺库不创建和现有CLI显式upgrade红测；分类普通服务、显式创建/修复/归档检查消费者，保留原Schema/FTS算法及真实代次保护。普通写连接使用mode=rw抵御exists检查后路径消失，不能隐式补建。

Task7普通 open_existing 使用 mode=rw/mode=ro 和声明列/版本 SELECT。SessionDB 构造和受保护的旧库补齐保留为显式生命周期，首次 Profile 建库在发布前执行。Dashboard/TUI启动和观察获取转到普通入口。锁、错误、数据、FTS显式算法和关闭语义保留。未删除测试，Dashboard旧自动触发断言改为显式入口，已有完整业务断言保留。

### 验证证据

Windows、WSL三文件各15项通过，完整 Native 分别224文件1757通过/147平台skip、224文件1888通过/16平台skip，均实际exit0。WSL新PM本地源码快照和最终暂存版本的差异仅显式锁冲突 stop 提示和对应测试，后者在当前源码完整应用两文件42项exit0。静态16check、DB/插件边界、生成契约、空白、65个固定资源与映射分区校验exit0。独立无PG SQLite载荷5项和真实随机Schema混合Profile批次7项exit0。展开命令、解释器、cwd、Git身份、具名skip及历史失败见[Task7证据](../designs/hermes-db-two-layer-task7.json)及[调试记录](../debug/hermes-db-task7-sqlite-open.md)。DB当前369/root11，最终359、最终冻结验收、独立审查未验证。Task7实际提交hash在Task8启动记录。

## Task 8：闭合其他SQLite领域的首次创建与无DDL打开

状态：completed

### 目标

其余受管SQLite领域都有显式Schema创建路径，普通连接不承担DDL。

### 涉及文件

- `hermes_cli/kanban_db_connect.py`。
- `hermes_cli/projects_db.py`。
- `cron/delivery_queue.py`。
- `cron/executions.py`。
- `cron/incidents.py`。
- `cron/notepad.py`。
- `cron/scheduler.py`。
- `gateway/delivery_ledger.py`。
- `gateway/hosted_room_attachments.py`。
- `gateway/hosted_room_driver.py`。
- `gateway/hosted_room_policy_checkpoint.py`。
- `gateway/hosted_room_replicas.py`。
- `gateway/hosted_room_work_records.py`。
- `gateway/hosted_room_work_storage.py`。
- `gateway/hosted_rooms.py`。
- `gateway/hosted_rooms_common.py`。
- `gateway/hosted_rooms_gateway_import.py`。
- `gateway/hosted_rooms_legacy_import.py`。
- 其余2项及全部逐符号落位见映射task=8条目；本Task主责实际变更候选共20项。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task7。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：映射内所有受管Native库均有真实首次创建/升级拥有者，普通运行路径无DDL；用户SQLite文档输入仍独立可读。

### 实施步骤

1. 按106个SQLite候选及其AST/真实调用链核对，PG历史revision和用户SQLite输入标为保留，不将候选数误报为需要修改的库数。
2. 处理Cron executions/incidents/delivery/notepad、Projects、Kanban、Rooms/attachments/policy/work、metrics以及API辅助库的实际初始化入口；SQL和版本算法仍在原业务拥有者。
3. 连接获取改用已拆原语，显式逻辑领域创建/安装/setup或db upgrade调用原Schema迁移；普通tick、getter、读写与重开仅校验。插件SDK/portable库在Task15闭合。
4. 保持SQLite Board共享目录、slug/代次、跨进程init锁、文件损坏隔离及业务错误身份；保留可调用的显式修复能力，避免普通启动隐式DDL。
5. 更新各领域测试setup和patch读取点，保留原创建/升级/备份/保留/恢复覆盖。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_cron_delivery_store.py','tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_metrics_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_cron_delivery_store.py','tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_metrics_sqlite_optional_drivers.py','tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

映射内所有受管Native库均有真实首次创建/升级拥有者，普通运行路径无DDL；用户SQLite文档输入仍独立可读。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11启动：Task7实际commit 3daa6acb55ed518939cc7f023d7708141779fa9e。11个映射引用对应7个物理分区，working/HEAD逐字节核对通过。Task7提交后工作区无已跟踪改动。Task8先对实际受管库创建入口、普通读取/写入与动态patch做定向审计，先录入冷启动真实SQL trace红测。已有SQL、跨进程初始化锁、文件栅栏和业务调用顺序继续保持。


### 验证证据

当前保持in_progress。初始三项真实生命周期红测0pass/3fail。分离Cron/Projects/Rooms、Kanban和Metrics后的Windows必需4文件4项exit0，WSL必需4文件及新增2文件合计9项exit0。当前更多变更仍需最新复验。扩展Cron全目录实际179文件1212pass/334fail/61skip、exit1，69个失败文件已逐项列入本地AST/fixture整改索引；没有删减批次来获得通过。已确认部分测试直接把路径/作业字典作为数据准备，仍依赖普通获取建库，还有未验证的原因需继续检查。Task7 owner-transport测试fixture在更广Cron消费中的缺库也需同步，作为本Task跨依赖消费闭合记录。静态中间批次health0阻塞/0advisory，但Ruff集合字面量1项失败。当前不计Task8完成。

第二轮完整Cron仍为exit1，179文件1336pass/209fail/62skip、53个失败文件。9文件重点组223pass/0fail/5skip。后续4文件77pass/1fail，独立router claim租约测试缺少显式数据准备已补，需复验。扩展受影响消费者大批次仍在运行，保留原批次范围。继续核对合成作业、覆盖路径、SessionDB owner seam和指标首次创建fixture，未删业务断言。

后续同范围完整批次依次为179文件1454pass/88fail/3error/62skip，181文件1585pass/13fail/3error/65skip，188文件1674pass/1fail/24error/65skip，均exit1。最后一轮24项error及1fail来自Notepad导入别名替换误伤，已恢复正确别名，完整188文件正在复验。WSL同源186文件1643pass/3fail/24error/2skip、exit1，另两项Linux消费者首次daemon/Board数据准备已修正，尚须最新完整复验。

房间/指标/剩余Cron定向5文件124pass/0fail、exit0。附件、replica、handoff、ledger另外7文件正在验证。广域消费者诊断批次已到99.9%，实际范围仍固定，93个失败文件进入整改索引；初轮时间较长，出现1200秒文件timeout，保留失败及源码变化期间的诊断身份，不能计为最终验收。静态第二轮Ruff通过、health45项fixture导入重定义，已将fixture直接迁到现有tests/hermes_cli/conftest.py并同步全部实际读取点，等待最新静态复验。当前Task8仍in_progress，未创建实现commit。



所有当前批次保持诊断/局部验证身份，命令与环境见对应安全控制器的.log.json。Task8实现尚未完整通过，不能计为completed。


2026-11-11后续恢复记录。Windows188文件完整中间组1699pass/0fail/65skip、exit0，日志native-win-494e3148b7fe428d818526cd8956945f。此后有生产及fixture修改，最终必须重新完整复验。第一次广域245文件实际1784pass/377fail/141error/33skip、exit1（3613.8秒）；第二次245文件2065pass/214fail/22error/34skip、exit1（1236.0秒）。两批完整保留，不缩减其范围。

已确认executions与incidents共享executions.db，显式首建必须在任何Schema写入前记录整组缺失物理路径，再初始化该路径的全部领域。普通重复job创建SQL trace已加入验收。普通Kanban冷打开保留原只读损坏检查、错误身份、备份和锁序；REINDEX仍通过原显式初始化/修复算法，新增3项生命周期合同exit0。原自动重建/升级/修复测试改接明确生命周期，文件消失/空替换后先验证普通打开拒绝，再保留原Schema、数据和恢复断言，没有删除测试。

共享hosted_owner fixture实际读取_default_db_path，并非sessions_dir对应路径，现按真实默认路径显式准备，且失败也关闭事件循环。原timeout相关5文件34pass/0fail、exit0。指标关闭时的无telemetry目录断言原样保留，未初始化和显式启用fixture分别提供实际前置条件。31文件Kanban中间组240pass/39fail/1error/2skip，4文件专用迁移/修复组59pass/5fail/2skip，均exit1；已继续修正pytest导入、async插入缩进、显式修复调用及准确patch读取点。最新静态和完整Native/消费者复验仍未全部通过。Task8持续in_progress，恢复提交仍3daa6acb55ed518939cc7f023d7708141779fa9e。

最新整改后32文件Kanban完整重点组283pass/0fail/2skip、exit0，包含原31文件全部业务断言及迁出主题模块的3项WAL合同。文件拆分用于符合既有规模限制，没有删除测试。完整245消费者及188 Native双宿主仍在复验。新增db_commands消费者发现上轮SQLite升级拒绝断言未同步，现保留status缺库无文件断言，接通显式upgrade并同步配置解析patch签名；八文件20项Windows exit0。中间一次误写不存在文件名导致runner exit2和后续旧断言/签名失败全部保留。静态16check已通过一轮，空白EOF失败已修正，最新全部门禁待完成。65个固定资源working/staged/HEAD、11映射引用、业务DDL字面量无变化、369/11/31/29以及正式目录HEAD/clean核对通过。Task8仍in_progress。


后续完整结果保持失败记录。246文件2186pass/102fail/14error/34skip、exit1，失败29文件；针对性17文件132pass/26fail/1skip、29文件232pass/48fail/1skip均exit1。房间共享fixture、HTTP回执、直接保留库及指标关闭/多Profile首次准备继续同步，正常恢复构造保持checked open。发现真实API首次成员邀请先保留房间再建领域的遗漏，已在该显式创建入口初始化缺失协调库，未改原grant或reserve算法，添加真实首邀和重复无DDL合同。两次导入遗漏失败也完整保留并修正。后续7文件61pass/1fail、5文件56pass/5fail和3文件28pass/1fail仍exit1，最后一项为双网关异步恢复终态等待，正在定向定位。

Windows188完整最新组1701pass/0fail/65skip，必需扩展八文件Windows及WSL各20pass/0fail，16check与全部边界/合同/空白exit0。WSL188完整1762pass/2fail/2skip、exit1，分别为真实gateway restart启动等待和SDK后台导出10秒join；同两文件在无其他Linux全批次时95pass/0fail、exit0。没有增加skip、超时或删除断言。原188范围正在两worker完整重跑，消费者范围已扩到251文件，全部必需完整exit0仍待完成。Task8保持in_progress，完成7/20。


最新WSL原188文件完整批次1764pass/0fail/2skip、exit0（879.7秒、两worker）。Windows251文件完整两次分别2344pass/2fail/34skip、2345pass/1fail/34skip，exit1。共享owner fixture缺Projects的前置条件已修正并去掉重复准备，四文件43pass/0fail；剩余HTTP滴流测试与传输源码的AST/字节均核对与0d8782基准一致。底层剩余socket预算可在下一次monotonic检查前触发TimeoutError，原固定文案断言没有区分这两种实际异常链。该测试现保留真实滴流、重试和上限断言，新增响应体已开始、实际耗时下限、异常链类型及各类型对应原错误身份核验。HTTP生产算法未修改，整批验收范围仍为251文件，须重新完整exit0。前面双网关临时诊断已去除，最后单文件4pass/0fail、完整251中的双网关也4pass/0fail，原间歇等待失败继续保留记录。


补充状态一致性回归先红（5pass/1fail，重试未拒绝），修正publish_job_record在原jobs锁前以现有_connect分别校验四个存储后，四文件130pass/0fail/1skip。两个只准备executions的真实Worker/发生槽fixture因共用路径暴露12fail，补齐明确准备后两文件17pass/0fail。普通Room连接重复检查全部组件会使主表查询依赖尚未获取的附件等组件；真实缺附件表回归先红（6pass/1fail），现在恢复主表原_schema_is_current/settled检查，显式完整初始化仍检查全部组件，各组件在自身实际获取时校验。原SQL未改。

双网关捕获到deferred/同一代次1/实际执行1次、recovery probe endpoint unreachable。测试原来在真实HTTP事件循环执行同步SQLite轮询，现把轮询与消息读取送入asyncio.to_thread，保留原20秒等待及同一回执/一次执行断言，临时诊断已去除。两文件5pass/0fail。最新大批次仍为过程中诊断，存在旧fixture与旧同步轮询的失败，恢复点仍3daa6acb55ed518939cc7f023d7708141779fa9e。Task8未完成，后续须稳定源码下全部必需完整exit0及最新静态。


最终结算。Windows434文件完整并集3894pass/0fail/99平台skip，包含原188 Native与251消费者全部选择范围，其中2个辅助入口没有独立测试case。WSL188完整1766pass/0fail/2平台skip。最新Windows/WSL八文件各22pass/0fail，全部实际exit0。最新16check、DB边界、插件边界、生成契约和空白均exit0。业务DDL字面量delta为0，固定65资源working/staged/HEAD、31 revisions、29表模块、root11校验通过。DB当前369为中间数，最终359预算仍待后续Task闭合。3项WAL测试的原业务assert AST逐项一致，没有删除测试。最后仅清理一个未使用导入，其余Python字节及业务AST一致，清理后两主机22项合同通过。源码hash d9cb72035a92b75455ec56de1fadab398c22d5d612f6d8a47a2d9d603e85c912。

展开命令、解释器/cwd/源码身份、失败/整改/skip和未验证项见[Task8证据](../designs/hermes-db-two-layer-task8.json)。普通资源获取只检查已有Schema，首次创建与升级由实际应用生命周期拥有者执行。原统一Task24、七项非WSL缺证和Windows八项Profile基准问题独立保留。正式目录HEAD90a2987e8c且clean，只读核对通过。Task8验证完成后立即创建本地commit，实际hash在Task9启动记录，8/20。

## Task 9：迁出Sessions与Runtime应用装配

状态：completed

### 目标

Sessions/Runtime存储组合及应用依赖有明确唯一拥有者。

### 涉及文件

- `hermes_db/domains/runtime/postgres/context.py`。
- `hermes_db/domains/runtime/postgres/media.py`。
- `hermes_db/domains/runtime/postgres/policy.py`。
- `hermes_db/domains/sessions/postgres/catalog.py`。
- `hermes_db/domains/sessions/postgres/lifecycle.py`。
- `hermes_db/domains/sessions/postgres/messages.py`。
- `hermes_db/domains/sessions/postgres/support/usage_writer.py`。
- `hermes_db/integration/authority_access.py`。
- `hermes_db/integration/events.py`。
- `hermes_db/integration/local_access.py`。
- `hermes_db/integration/registry.py`。
- `hermes_db/integration/runtime_access.py`。
- `hermes_db/integration/runtime_calls.py`。
- `hermes_db/integration/runtime_composition.py`。
- `hermes_db/integration/session_composition.py`。
- `hermes_db/integration/session_portability.py`。
- `hermes_db/integration/worker_access.py`。
- 新落位：`gateway/session_storage_authority.py`, `gateway/session_worker_process_proof.py`, `hermes_cli/db_runtime.py`, `hermes_cli/db_sessions.py`, `hermes_cli/db_session_lifecycle.py`, `hermes_cli/db_usage_writer.py`, `hermes_db/domains/runtime/access.py`, `hermes_db/domains/runtime/authority.py`, `hermes_db/domains/runtime/calls.py`, `hermes_db/domains/runtime/local_access.py`, `hermes_db/domains/runtime/worker_access.py`, `hermes_db/domains/sessions/postgres/portability.py`, `hermes_db/domains/sessions/registry.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task5, Task6, Task7, Task8。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：包内Session/Runtime无应用装配/线程/进程实现，业务资源与原事务/缓存/恢复合同保持。

### 实施步骤

1. 迁出session/runtime_composition、events、Profile上下文和usage writer至具体db_*应用兄弟；保留当前真实DTO/异常构造和捕获的owner作用域。
2. session_portability归sessions/postgres，local/runtime/worker access和calls归Runtime业务；authority中的进程证明及当前actor授权协调归Gateway。
3. typed registry归sessions业务，真实构造callback由应用提供；保持PID/配置/scope键、构造等待、引用计数、writer最后flush与close，不额外造通用registry。
4. 拆出Session/Runtime组件中的外部效果：业务SQL/回执/压缩快照不动，事件/队列/外部调用在应用拥有者；必要的窄生命周期端口只保留实际消费者，不持有完整应用Service。
5. 同步所有消费者和Native adapters；保留minted/live-lazy/压缩tip、正常导入导出、终态/Worker/unknown恢复，已退役adoption不恢复。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_remaining_read_maintenance.py','tests/hermes_state/test_session_import_keep_flags.py','tests/tui_gateway/test_resume_live_lazy_session.py','tests/tui_gateway/test_session_resume_store_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_remaining_read_maintenance.py','tests/hermes_state/test_session_import_keep_flags.py','tests/tui_gateway/test_resume_live_lazy_session.py','tests/tui_gateway/test_session_resume_store_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_workers.py','tests/hermes_db/postgresql/test_merge_commit_recovery.py','tests/hermes_db/postgresql/test_merge_process_recovery.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

包内Session/Runtime无应用装配/线程/进程实现，业务资源与原事务/缓存/恢复合同保持。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-11实施中：装配、事件、UsageWriter、进程证明与短文件清理迁到应用所有者。typed registry使用必需build回调，缓存键、等待、引用计数与关闭顺序不变；Runtime访问读取实际成员，原生handle复用同一Runtime。第一批4文件22pass/1fail，工厂共享引用fixture缺显式Schema准备；补齐后7文件28pass/12fail，两个TUI恢复fixture同样缺Schema。仅补显式空库准备，正常懒会话/隔离/404断言保留。最新Windows7文件41pass/0fail、PG3文件20pass/0fail，均exit0；新增Runtime构造失败清理与重新获取合同。其他必需批次、静态与完整消费者仍待核验，不计完成。

2026-11-11启动。Task8实际commit 2c18b7a48ef4c0eba6602868a5f6d66f58da2388，8/20。11个映射引用对应7个分区hash已核对，Task8提交后已跟踪工作区clean。按当前源码保留前置Task改动，先核对本Task逐符号、消费者和动态patch，再按现有设计迁移所有者。

开始按实际模块落位实施。141项中124项为保留审查，17项为迁出/拆分。runtime_access原含对象装配，业务访问改读真实runtime成员，构造归应用；旧数据及raw Native/PG/SessionResource真实调用入口均须保持。retired_files实际文件删除不属于业务查询，作为原映射误分类同步迁到应用生命周期，算法与授权目录限制保持。Transcript marker、活动规范化和Tool上限由现有应用所有者传入，SQL及事务不改。

### 验证证据

扩大消费者完整104文件首轮Windows552pass/5fail/4skip，WSL555pass/6fail，均exit1。3个Delivery fixture遗漏显式账本初始化；两个真实SQLite单后端/Matrix恢复合同先构造附件再创建Room，应按真实首次创建顺序创建Room后获取附件；CLI不可用后端测试仍patch旧registry构造位置。修正仅涉及准备/真实patch读取点，原业务assert保留。修后Windows四文件23pass/0fail/1平台skip。第一轮16checks因新业务路径55个未复核逐符号依赖失败；已人工复核26个真实符号依赖，保留边界方向规则和插件API。核对时发现local commit触发owner memory读取/发布，将该选择协调迁到Gateway而未修改Native实现。PG依赖隔离检查发现Native Runtime工厂不能与PG子类顶层导入同一模块，已留在无PG导入的db_sessions。全部整改后重新运行104文件双主机完整批次、PG必需3文件及静态，结果待收集。

结构审计最初采用Git自动rename视图漏计旧路径，出现新增2个原有SQL字面量的假阳性；改为--no-renames逐源/目标计数后SQL字面量delta0。固定65资源working/staged/HEAD、11映射引用hash、root11、31revision、29表模块通过；当前DB364为中间预算。进程证明与受限snapshot清理函数AST保持一致，测试未删除。

未执行本Task业务验证。实施后记录实际展开命令、source/解释器/cwd、退出码、passed/failed/skipped、失败修正/未验证项及恢复commit。


第二轮Windows104文件551pass/6fail/4skip，均来自test_local_creation中的混合import：commit选择迁到Gateway时，同一import中的local_receipt/end_idle被一起改写。按AST逐符号拆分，Gateway仅接收commit/authorize_history，纯local读取仍留业务；未增加旧路径shim。WSL同轮结果继续如实收集。16check、DB边界0违规、插件边界与生成契约均exit0；空白检查发现一个EOF多余空行，去除后exit0，业务AST一致。

A2A实际消费者加入后105文件首批Windows558pass/3fail/4skip；补准备后两个局部批次各9pass/2fail。根因是测试既改Profile环境home又由公共fixture固定DEFAULT_DB_PATH：只准备一侧会缺Session或Projects。现在显式准备两个实际拥有者home，局部11pass/0fail。为固定载荷，终止两个旧源码诊断批次（工具实际exit1，均不计通过），完整105文件范围保留并重新运行。最新Windows105文件561pass/0fail/4平台skip，exit0；最新16check、DB边界0违规、插件边界、生成契约与空白均exit0。现存58修改测试文件的209既有测试、797条业务assert全部保留。WSL采用2worker完整105文件复验，仅并发数变化，选择范围不减。等待其实际exit0前Task9仍in_progress。

最终结算：Windows105文件561pass/0fail/4平台skip，WSL同105文件565pass/0fail/0skip；PG必需3文件20pass/0fail，均实际exit0。最新16check、DB边界0违规、插件边界、生成契约和空白均exit0。两个被停止的旧源码诊断批次实际exit1，单独记录且不计通过。保留全部必需范围与原业务断言，没有删除测试。结构审计固定65资源canonical working/staged/HEAD、11映射引用、root11、31revision、29表模块、SQL字面量delta0通过；两个未触碰的既有CRLF checkout文件有明确记录，Git字节与冻结hash相同。当前DB364为中间数，最终<=359仍待后续闭合。

Session/Runtime装配、Profile回调、事件、线程、进程证明、文件清理及owner memory commit协调有实际应用拥有者；业务端保留同Connection/事务/回执/快照，Runtime读取真实已装配成员。141映射条目已逐项复核，原124preserve/17active经retired_files修正为123preserve/18active；源文件迁出不冒充算法净减少。58修改测试文件的209既有测试、797条业务assert逐项保留。展开命令、解释器/cwd/源码身份、退出码、失败/整改/skip与恢复点见[Task9证据](../designs/hermes-db-two-layer-task9.json)。正式目录HEAD90a2987e8c且clean，只读核对通过。Task9完成后立即本地commit，实际hash由Task10启动记录；9/20，最终验证与独立审查仍待完成。

## Task 10：拆开Profile和媒体回收的存储与应用职责

状态：completed

### 目标

Profile生命周期和媒体授权数据规则留存储，实际文件协调归应用。

### 涉及文件

- `hermes_db/core/file_scope.py`。
- `hermes_db/integration/archive_refs.py`。
- `hermes_db/integration/media_grants.py`。
- `hermes_db/integration/media_retirement.py`。
- `hermes_db/integration/profile_lifecycle.py`。
- `hermes_db/integration/profile_paths.py`。
- `hermes_db/maintenance.py`。
- 新落位：`hermes_cli/db_archive_files.py`, `hermes_cli/db_file_identity.py`, `hermes_cli/db_maintenance.py`, `hermes_cli/db_media_retirement.py`, `hermes_db/domains/profile_paths.py`, `hermes_db/domains/sessions/postgres/media_grants.py`, `hermes_db/domains/sessions/postgres/profile_lifecycle.py`, `hermes_db/domains/sessions/postgres/queries/archive_refs.py`, `hermes_db/domains/sessions/postgres/queries/media_retirement.py`。
- 新建：`tests/hermes_db/contracts/test_application_effect_fences.py`。
- 新建：`tests/hermes_db/postgresql/test_application_effect_fences.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task9。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：全部保留授权/生命周期安全合同通过；实际文件副作用归应用，原数据和锁/事务边界不变。

### 实施步骤

1. media_grants/profile_lifecycle/profile_paths按逐符号落位到业务；Profile删除/rename触发及文件identity/root/lease/回收归db_*应用拥有者。
2. 既有授权读取、token/recipient/owner验证、pin、最后引用和安全释放保留；不生成新跨store搬移授权，不改历史文本/数据/持久记录格式。
3. 保留原archive cleanup与media collect/release中的短本地栅栏：应用持同一短事务与原锁完成已存在的引用核对/本地回收，不在本次架构移动中拆开它们或新增token。
4. 已有file jobs的长文件准备/发布与网络/进程等待仍在连接外；DB候选、引用和回执SQL由业务提供。
5. 新增实际并发引用/文件替换/最后pin合同并验证真实PG；保留正常Profile目录rename失败恢复/回收、terminal投递和其他Profile隔离。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_application_effect_fences.py','tests/hermes_db/contracts/test_existing_media_grants.py','tests/hermes_cli/test_profile_identity_purge_cmd.py','tests/gateway/test_profile_identity_purge.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_application_effect_fences.py','tests/hermes_db/contracts/test_existing_media_grants.py','tests/hermes_cli/test_profile_identity_purge_cmd.py','tests/gateway/test_profile_identity_purge.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_application_effect_fences.py','tests/hermes_db/postgresql/test_profile_file_scope.py','tests/hermes_db/postgresql/test_existing_media_grants.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

全部保留授权/生命周期安全合同通过；实际文件副作用归应用，原数据和锁/事务边界不变。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task9实际本地commit d20361745731344cc1b31a928a2f7579b44f3545，当前9/20。全部映射分区hash已核对，按Task10条目和实际短事务文件栅栏继续实施；Task9测试不计Task10验收。

### 验证证据

未执行本Task业务验证。实施后记录实际展开命令、source/解释器/cwd、退出码、passed/failed/skipped、失败修正/未验证项及恢复commit。


当前代码细化：archive纯查询已存在，保持原模块不复制。queries/media.retire_spillover含文件identity/owner读取，补映射至应用实际callback，并从原删除/变更链在相同Conn/锁位置调用。media_grants的历史/held解释通过真实应用提供的必需窄回调传入；业务不反向import应用。maintenance根保留实际200条插件过期清理和附件namespace SQL，Profile/资源/文件协调外移。开始先为文件替换、嵌套capture最后pin及原短事务栅栏建立保留合同，再迁代码。owned/SOUL.md与新发现的target/SOUL.md均保留、不暂存。

迁移前新增保留合同：Native2文件8pass/0fail、真实PG1文件4pass/0fail，均exit0，作为本Task原有栅栏行为基线。生产第一阶段完成文件/业务归属迁出，引用改写脚本遇到AST Module无col_offset而中断；未重放已完成移动，改为只恢复引用阶段并明确排除owned/与target/。继续编译和本Task必需验证，当前不计完成。

迁移后首个Windows必需4文件12pass/1fail，Profile purge fixture在SessionStore首次获取前未准备Schema，导致JSONL路由处理后未清数据库心跳。只在实际两个测试home显式初始化，原删除/保留断言不变；复验4文件13pass/0fail，PG必需3文件16pass/0fail，均exit0。DB边界初检6违规来自3个新位置未复核符号；已核对同Connection锁顺序和纯namespace编码，增加精确消费者/符号说明，不允许应用文件IO反向依赖。WSL必需批次、扩大消费者及静态仍待完成。

扩大Windows98文件512pass/0fail/4平台skip、PG7文件50pass/0fail，均实际exit0。WSL必需4文件13pass/0fail。源码审计：11分区引用working/staged hash、65固定资源canonical working/staged/HEAD、31revision、29表模块、root11通过；DB362为中间数。文件owner/identity、archive unlink、media/spillover collect、retire_spillover与bounded history scanner共7组算法体逐项AST一致；生产SQL字面量delta0。现存36项业务测试116条assert保留，无测试删除。等待WSL同98文件和最新文档后的静态门禁；证据见hermes-db-two-layer-task10.json，仍in_progress。

文档同步后的16check再次发现AGENTS链长度超限（gateway30152、hermes_cli30096）。只将本轮新增的详细owner/文件栅栏说明移入既有设计，AGENTS保留精简路由和关键约束；保留30000上限和原有规则，随后重新运行完整静态门禁。

最终结算：Windows98文件512pass/0fail/4平台skip，WSL相同98文件516pass/0fail/0skip，PG7文件50pass/0fail，均实际exit0。必需4文件/PG3文件全部包含，验收范围未删减。最新16check、DB边界0违规、插件边界、生成契约与空白均exit0。固定65资源、11分区hash、root11、31revision、29表模块和生产SQL字面量delta0通过。文件身份与回收/历史scanner7组原算法体AST保持一致，36既有测试116条业务assert全部保留，无测试删除。DB362为中间数，最终<=359继续由后续Task闭合，迁出不冒充算法净减少。

文件/资源/Profile协调已迁到实际应用拥有者，短事务、同Connection、store/lease锁顺序、最后pin和既有授权读取保持。首次保留基线和全部失败/整改、展开命令/解释器/cwd/源码身份/退出码/skip与恢复点见[Task10证据](../designs/hermes-db-two-layer-task10.json)。正式目录预期HEAD且clean，只读核对通过。立即创建本地commit，实际hash由Task11启动记录；完成10/20。原统一Task24、七项非WSL缺证、Windows八项基准及最终冻结验证/独立审查仍独立保留。

## Task 11：闭合Cron、Projects、Verification和Metrics边界

状态：completed

### 目标

小领域的存储模型与应用上下文/发送/Worker路由分离。

### 涉及文件

- `hermes_db/integration/cron_application.py`。
- `hermes_db/integration/metrics_snapshot.py`。
- `hermes_db/integration/observations.py`。
- `hermes_db/integration/worker_metrics.py`。
- `hermes_cli/observability/shared_metrics.py`。
- `hermes_cli/observability/shared_metrics_sender.py`。
- `hermes_cli/observability/shared_metrics_snapshot.py`。
- 新落位：`agent/runtime_metrics_snapshot.py`, `cron/storage_application.py`, `hermes_cli/db_observations.py`, `hermes_cli/observability/worker_metrics_bridge.py`, `hermes_db/domains/metrics/postgres/worker_metrics.py`, `hermes_db/domains/observations.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task8, Task9。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：小领域业务持久化无Profile/发送/进程装配，正常返回及opt-in/配额/时间语义保持。

### 实施步骤

1. Cron应用能力归cron/storage_application，Projects值构造归db_domains，Verification worker/owner路由归agent/runtime_domain_store，Metrics网络/owner桥接归现有observability兄弟。
2. 领域api仅保留已解析资源下具名操作/DTO及值规则；当前Profile解析和worker_resource选择由实际应用入口完成。
3. worker_metrics的SQL原子更新归metrics业务，跨Profile root/consent及发送策略归应用；隐私/opt-in、队列、no-op revision不变。
4. 保留现有逐符号登记的无I/O纯规则复用；对有环境读取/副作用的实际调用外移，不自动扩展白名单。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_cron_delivery_store.py','tests/hermes_db/contracts/test_metrics_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_cron_delivery_store.py','tests/hermes_db/contracts/test_metrics_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_projects_store.py','tests/hermes_db/postgresql/test_verification_store.py','tests/hermes_db/postgresql/test_cron_executions.py','tests/hermes_db/postgresql/test_metrics_store.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

小领域业务持久化无Profile/发送/进程装配，正常返回及opt-in/配额/时间语义保持。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task10实际本地commit 6f00d9b0dbe9b4a024337e96ca1901e625886836，当前10/20；映射分区hash已校验，依Task11实际消费者继续。旧Task验证不计本Task成果。

### 验证证据

未执行本Task业务验证。实施后记录实际展开命令、source/解释器/cwd、退出码、passed/failed/skipped、失败修正/未验证项及恢复commit。


按domain_io_sites补充复核：Metrics package_exports、PG store文件导出/回收和sending HTTP虽在preserve入口列表，实际I/O分区明确归Task11，须拆到observability应用兄弟。Profile捕获/重开归应用，业务API只处理已绑定source；PG业务Store/claim接受真实opener、worker bound用同receipt Connection。共享队列纯常量/parser保留metrics.policy真实定义。原Runtime下WorkerMetricsStore是RPC适配，迁到agent/runtime_metrics_store。新增无PG依赖的worker session-age RPC回归，先验证现有过早SQLAlchemy导入的失败，再分层整改。均保留SQL、DTO、consent/回执/no-op revision及时间语义，不增加框架/兼容flag/shim。

新增worker无PG驱动回归先红（1pass/1fail，明确在metrics_snapshot顶层from sqlalchemy导入被拒），将Worker RPC分支放在SQL查询导入之前后Native必需2文件3pass/0fail。Cron应用runtime原体迁出，观测query/获取拆分，Metrics Profile/fingerprint打开、HTTP transport、文件export/prune由真实应用拥有者组合，原队列常量/parser在业务policy有实际定义。业务Store/claim通过必需opener处理已解析/已绑定资源，bound worker保留receipt Connection；RPC facade迁到agent。生产Python编译通过，继续必需PG/WSL、扩大消费者和静态。

PG必需4文件首批16pass/1fail，唯一失败是test_metrics_store仍patch旧业务模块atomic_json_write，现改应用实际读取模块，并同步faults/process同类patch，保留pool.checkedout()==0、保留期、未导出数据与故障恢复断言。搬移PG导出方法时同时补齐其timedelta依赖（在PG执行前通过代码核对发现）。后续完整复验不计此前失败为通过。

必需Windows/WSL各2文件3pass/0fail，PG必需复验4文件17pass/0fail；扩大PG14文件44pass/0fail，均exit0。初始边界19读取点来自9个未登记新位置的纯值/同Connection依赖，已逐符号复核后最新16check、DB边界0违规、插件边界、生成契约和空白exit0。源码审计固定65资源、11分区hash、root11、31revision、29表模块及生产SQL字面量delta0通过；DB当前357≤359，最终仍复核，不以迁出宣称算法净减少。12组Cron/RPC/文件export/HTTP backoff/parser/queue bounds/观测query算法AST一致，25既有测试114条正常assert保留。扩大Native批次仍待完成，当前Task11不计完成。

中间结算：Windows扩大批次已完整exit0：302文件2579pass/0fail/75skip。只剩同302文件选择范围的WSL完整批次未结束，当前0失败；Task11仍in_progress，不将中间结果计完成。源码审计hash仍db6908bef5b65cd5155bfe7f0f3a5fbbb80420f10cd128aae99b0f06782d1076。


失败/根因记录：扩大WSL302文件实际exit1：2651pass/1fail/2skip，prepared_compaction原lt_1s等待分桶收到1s_to_5s。实际日志首轮冷插件发现落在_effective_aux_timeout配置加载中；独立隔离新进程同调用首次2.160s、第二次0.001s，压缩生产实现相对0d基准0差异。仅在该测试开始真实0.2s deadline前预热实际配置，不更换时钟、不扩大界限，原分桶/取消/会话边界/失败分类全部assert保持。保持Task11 in_progress，重跑两端相同302完整文件与PG/static门禁；原失败不得用单文件补跑冒充完整通过。


复验中间失败：第二轮扩大WSL报告真实Cron managed_gateway_restart合同1项失败（该文件39pass/1fail），完整批次仍在执行，完整失败段及实际exit码待收取。当前只读定位，不改运行中源码，不将环境推测计作根因，保留原302文件范围与全部断言。


Cron诊断：同源完整文件actualexit1：39pass/1fail，精确失败为原10s启动窗口内started不存在；聚焦原真实managed-restart用例随后actualexit0：1pass，保留真实systemd scope/新Worker/ledger completed/单次副作用/单次投递全部断言。独立保存的测试工件记录payload到started为6.343s、副作用1行。无生产代码、时限或assert修改。原失败完整批次结束后，以相同302文件选择范围、2workers且不同时执行其他主机/PG/static批次复验，以隔离启动资源竞争；仅降低并发，不删除文件/用例/断言。原失败记录继续保留，不用聚焦结果冒充完整通过。


第二轮完整WSL结算：302文件2651pass/1fail/2skip，实际exit1，1618.8s/4workers，完整失败段确认仍为Cron started.exists()原10s启动窗口，后续未增加失败。最新Windows完整302文件2579pass/75skip、PG14文件44pass及静态全门禁均exit0。核对源码hash1309d3e3未变化；所有其他测试批次已结束，现在仅运行WSL同302文件、2workers完整复验。不更改文件/用例/断言/时限，保留所有失败，不用聚焦通过替代整批exit0。


第三轮同302范围/2workers中间证据：原Cron完整文件40pass/0fail，34.6s，原10s启动等待及真实scope/PID/单次副作用/投递assert均未改。当前累计105文件1320pass/0fail；仍等待完整302文件actualexit0，不以完整单文件替代整批结算。


最终结算：=== Summary: 302 files, 2579 tests passed, 0 failed, 75 skipped (100% complete) in 899.5s (4 workers) ===；=== Summary: 302 files, 2652 tests passed, 0 failed, 2 skipped (100% complete) in 2366.7s (2 workers) ===；PG14文件44pass/0fail，均实际exit0。两端同302文件，全部32选择器及必需文件完整保留。实际skip逐文件、所有初始失败/修正、展开命令/解释器/cwd/home/runtime/temp/源码身份/退出码见[Task11证据](../designs/hermes-db-two-layer-task11.json)。最新16check、DB边界0违规、插件边界、生成契约及空白exit0。固定65资源/11分区hash/root11/31revision/29表模块保持，DB357≤359、生产SQL字面量delta0；12组原算法体AST一致，28既有测试130条业务assert保留，无删除。正式目录预期HEAD且clean，只读核对通过。立即创建本地commit，实际hash由Task12启动记录；完成11/20。最终冻结验证、独立审查及既有独立平台缺证仍保留。

## Task 12：迁出Kanban拥有者、进程和RPC适配

状态：completed

### 目标

Kanban owner、Profile、进程与RPC属于应用，DB身份和命令回执属于业务。

### 涉及文件

- `hermes_db/integration/kanban_application.py`。
- `hermes_db/integration/kanban_owner.py`。
- `hermes_db/integration/kanban_wire.py`。
- `hermes_db/integration/kanban_worker.py`。
- 新落位：`agent/runtime_kanban_storage.py`, `hermes_cli/kanban_storage_application.py`, `hermes_cli/kanban_storage_owner.py`, `hermes_cli/kanban_storage_wire.py`, `hermes_db/domains/kanban/owner.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task9, Task11。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：owner/RPC控制仍在应用且多Profile/新代次保护保持，业务SQL无进程/Profile发现依赖。

### 实施步骤

1. 迁出kanban_application/owner/worker/wire，纯board_reference/校验留业务；唯一应用拥有者使用hermes_cli/kanban_storage_*和agent/runtime_kanban_storage。
2. 保留固定Board代次、scope/target指纹、owner-only与Worker只读claim；Worker不获直接DB能力或自选DSN/Profile。
3. 原命令ID/outbox/RPC名称及错误/DTO身份保持，存储只接收已验证owner/数据，不在底层探测进程或重选Profile。
4. 真实读取点、动态COMMANDS/READS和patch同步；若发现wire形状需要变化先修订设计并运行实际前端构建，不凭Python通过外推。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_kanban_owner_reference.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_kanban_owner_reference.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_kanban_worker_rpc.py','tests/hermes_db/postgresql/test_kanban_owner_policy.py','tests/hermes_db/postgresql/test_kanban_command_receipts.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

owner/RPC控制仍在应用且多Profile/新代次保护保持，业务SQL无进程/Profile发现依赖。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task11实际本地commit 805122d791b9a2068aed2eeb170b37149b09800d；完成11/20。已验证全部11分区hash并核对4主责/28索引读取点。按实际代码，另将API中4个Worker/Profile选择函数及_KANBAN_MODULES一起迁至应用兄弟，业务BoardResource/DTO及主责Task13仍保留。managed_scratch_roots的原SELECT留为已给Connection的具体业务查询。dashboard使用既有kanban_db模块读取点，删除旧私有decorator crossing，不新增facade定义、旧内部路径shim或plugin_api白名单。全部调整先映射后实施。

### 验证证据

当前将先执行原合同基线，再迁移与复验；本Task不能沿用历史Task11验收。所有实际展开命令、解释器/cwd/源码身份/退出码、skip/失败及恢复点写入Task12证据。


实施审计：4个旧内部文件移除、40个Python定义/读取点同步。10组原capability/owner/Worker/RPC/BoardResource/selector/dispatch/SELECT/plugin事务函数体等价，生产SQL字面量delta0，15既有测试59条assert全保留，无删除。固定65资源、11分区暂存hash、root11/31revision/29表模块保持，DB354≤359；不宣称迁出等于全项目算法净减少。插件白名单未改、旧私有crossing减少1。原基线两端Native各1pass、PG3文件8pass；搬迁后Windows必需+无PG依赖2文件2pass，边界0违规。扩大验证文件列表在失败前冻结为Native18/PG13，保留全部原必需文件，顺序执行两主机/PG/static，避免叠加启动资源竞争。展开命令及实际结果由Task12证据保存。


首次完整复验结果：PG13文件41pass/0fail/0skip，Windows18文件211pass/0fail/6skip，WSL同18文件215pass/0fail/2skip，均exit0；两端各217项收集。16checks/边界/契约均exit0，最后whitespace实际exit2：API抽取后EOF多余空行。只移除末尾多余换行，compile marshal代码对象字节相同；仍保持Task12 in_progress，重算源码hash并重跑原Native18/PG13与静态门禁，不缩减范围或将旧hash结果冒充新验收。Windows skip包括5平台项及原DB过小合成截断条件1项；Linux为Windows锁测试1项和既有Node不可用的UI touch/drag测试1项，该Linux UI分支未验证，不冒充平台覆盖；UI代码/RPC wire未变，Windows实际Node分支通过。


EOF整改后源码审计hash 77b6ab7838d8f9bfabe4550a75c67216872dd8993a38a29e9cdb419cef36e800；10组原算法、SQL delta0、15既有测试59条assert、65固定资源及354/11/31/29计数再次通过。新hash的全部原固定Native18/PG13及静态门禁重新执行；此前源码hash628664的成功结果保留为历史记录。


最终结算：=== Summary: 18 files, 211 tests passed, 0 failed, 6 skipped (100% complete) in 102.0s (4 workers) ===；=== Summary: 18 files, 215 tests passed, 0 failed, 2 skipped (100% complete) in 388.6s (4 workers) ===；=== Summary: 13 files, 41 tests passed, 0 failed (100% complete) in 452.1s (1 workers) ===。均实际exit0，两端同18文件、PG13文件全部原冻结选择器完整包含。最新16check、DB/插件边界、生成契约与空白均exit0。固定65资源/11分区hash/root11/31revision/29表模块、DB354≤359、生产SQL字面量delta0通过。10组原算法体/DTO/RPC/selector/SQL/原插件事务体一致，15既有测试59条业务assert保留，无测试删除；plugin_API白名单不变、旧私有crossing移除1。全部实际argv/解释器/cwd/源码身份/退出码、实际skip文件及失败修正见[Task12证据](../designs/hermes-db-two-layer-task12.json)。正式目录预期HEAD且clean，只读核对通过。立即创建本地commit，实际hash由Task13启动记录；完成12/20。最终冻结验证、独立审查及既有独立平台缺证仍保留。

## Task 13：拆开Kanban事务工作流与文件归档编排

状态：completed

### 目标

Kanban工作流中的原子写与外部准备/发布/清理有可核对边界。

### 涉及文件

- `hermes_db/domains/kanban/postgres/catalog.py`。
- `hermes_db/domains/kanban/postgres/claims.py`。
- `hermes_db/domains/kanban/postgres/completion.py`。
- `hermes_db/domains/kanban/postgres/dispatch.py`。
- `hermes_db/domains/kanban/postgres/effects.py`。
- `hermes_db/domains/kanban/postgres/files.py`。
- `hermes_db/domains/kanban/postgres/maintenance.py`。
- `hermes_db/domains/kanban/postgres/review.py`。
- `hermes_db/domains/kanban/postgres/swarm.py`。
- `hermes_db/domains/kanban/postgres/workspaces.py`。
- `hermes_db/integration/transfer/kanban.py`。
- `hermes_cli/kanban_db.py`。
- `hermes_cli/kanban_db_context.py`。
- `hermes_cli/kanban_db_dispatch.py`。
- `hermes_cli/kanban_db_failure.py`。
- `hermes_cli/kanban_db_graph.py`。
- `hermes_cli/kanban_db_notify.py`。
- `hermes_cli/kanban_db_runs.py`。
- 其余4项及全部逐符号落位见映射task=13条目；本Task主责实际变更候选共22项。
- 新落位：`hermes_cli/kanban_storage_transfer.py`, `hermes_db/domains/kanban/postgres/transfer.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task10, Task12。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：原子业务写和现有恢复材料不变，外部进程/文件协调归应用，真实并发与完整归档恢复通过。

### 实施步骤

1. 按63个capability函数及隐藏I/O站点拆catalog/dispatch/completion/review/files/workspaces/maintenance/swarm，DB快照、锁、CAS、事件/回执留原领域；进程/文件/通知协调归具体kanban_storage_<workflow>应用兄弟。
2. 应用先准备原证据，短事务重核原水位/claim/代次后写入；保留dispatch租约、连接外等待、failure预算及run/claim原子性。
3. transfer/kanban拆真实SQL快照/图插入到领域与归档文件/stage/发布到应用；既有v2逻辑归档、校验、run映射和文件job不变。
4. 保持commit后丢ACK原命令/stage恢复、共享workspace与cleanup token fencing，不加入新通用Outbox/表/数据格式。
5. 每一条外移同Task更新生产调用/patch及活动文档，保留真实interactive Worker及文件发布并发测试。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_kanban_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_kanban_dispatch.py','tests/hermes_db/postgresql/test_kanban_completion.py','tests/hermes_db/postgresql/test_kanban_transfer.py','tests/hermes_db/postgresql/test_kanban_workspaces.py','tests/hermes_db/postgresql/test_kanban_worker_e2e.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

原子业务写和现有恢复材料不变，外部进程/文件协调归应用，真实并发与完整归档恢复通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task12实际本地commit 72d2d16ac05a47e4eeaae75aea9ce2a42544121c；完成12/20。当前Task所有11分区hash已验证，22个DB条目（含保留）和11个Native外部条目、251个消费者候选及实际I/O已按索引展开。依用户最新精简要求，仅做分层直接相关的原合同与边界/源码审计，不增加旧PG业务深测或重复基线。

### 验证证据

最终当前源码：=== Summary: 1 files, 1 tests passed, 0 failed (100% complete) in 2.5s (4 workers) ===；=== Summary: 1 files, 1 tests passed, 0 failed (100% complete) in 6.2s (4 workers) ===；=== Summary: 5 files, 28 tests passed, 0 failed (100% complete) in 244.0s (1 workers) ===。全部实际exit0、无skip。16check、DB/插件边界、生成契约及空白均exit0。完整展开命令/解释器/cwd/home/runtime/源码身份/失败与整改/恢复点见[Task13证据](../designs/hermes-db-two-layer-task13.json)。


结算：11个应用工作流兄弟接收实际文件/进程/租约线程/Profile/通知编排，业务保留具体SQL与原短事务栅栏、CAS、回执。117个实际操作闭合静态分发；旧transfer模块删除且无shim。65固定资源/11分区hash、DB354/root11/31revision/29表模块，生产SQL字面量delta0，135原算法/关键方法AST相同，28既有测试143断言保留。首轮static与5项PG失败及实际修正均保留，不计为通过。必需复验均通过后立即本地commit；实际hash在Task14启动记录。完成13/20，继续Task14。

## Task 14：拆开Rooms附件、路由与应用生命周期

状态：completed

### 目标

Rooms领域保留日志/策略/附件元数据，文件与路由生命周期归Gateway/TUI。

### 涉及文件

- `hermes_db/domains/rooms/attachments/files.py`。
- `hermes_db/integration/room_attachments.py`。
- `hermes_db/integration/room_policy.py`。
- `hermes_db/integration/room_router.py`。
- 新落位：`gateway/hosted_room_attachment_files.py`, `gateway/hosted_room_attachment_store.py`, `gateway/hosted_room_policy_store.py`, `hermes_db/domains/rooms/postgres/router_claims.py`, `tui_gateway/hosted_room_router_storage.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task9, Task10。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：无隐藏文件实现留在业务目录，Rooms/attachments/router的事务、授权、发布和恢复合同保持。

### 实施步骤

1. attachment files中的AttachmentContent/files_gate/replay/sweep实际I/O全部迁出domains，PostgresAttachmentStore归Gateway应用组合。
2. RoomStoreRef/DTO/事件/策略/cursor/claim SQL保留业务；capture/open/当前Profile解析及RouterCallLifecycle继承归应用。
3. 保留room authority/cursor一致快照、FIFO、不可变退休身份、容量/字节配额及短锁；附件内容写入/回收沿用原文件gate、cleanup job和metadata原子协议。
4. 同Task同步HostedRoom facades、TUI/router及API读点，保留Native与PG两条真实路径和新PID恢复。

### 验证方式

- `Test-Native -Files @('tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/hermes_db/contracts/test_rooms_sqlite_optional_drivers.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_rooms_store.py','tests/hermes_db/postgresql/test_room_attachments.py','tests/hermes_db/postgresql/test_room_attachment_concurrency.py','tests/hermes_db/postgresql/test_room_policy_process.py','tests/hermes_db/postgresql/test_room_run_faults.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

无隐藏文件实现留在业务目录，Rooms/attachments/router的事务、授权、发布和恢复合同保持。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task13本地提交c358fad2318cf3dee0fde9397317a566d0aef029，13/20；11分区hash全部验证。原映射中API Profile选择/获取/dispatch及AttachmentReaders隐藏文件读取按真实调用补入应用迁出；先修订映射再实施。RoomStoreRef/字段归一/metadata SQL与授权快照留业务，文件读取两侧重授权和短事务顺序不变。

### 验证证据

最终当前源码：=== Summary: 1 files, 1 tests passed, 0 failed (100% complete) in 2.4s (4 workers) ===；=== Summary: 1 files, 1 tests passed, 0 failed (100% complete) in 3.8s (4 workers) ===；=== Summary: 5 files, 15 tests passed, 0 failed (100% complete) in 75.9s (1 workers) ===。全部实际exit0、无skip；16check、DB/插件边界、生成合同及空白均exit0。实际展开命令、解释器/cwd/home/runtime/源码身份、预检修正与未验证项见[Task14证据](../designs/hermes-db-two-layer-task14.json)。


结算：实际文件/读取授权重核/Profile/路由生命周期均有Gateway/TUI真实所有者；DTO及metadata/claim SQL保留业务。10项原算法/SQL/dispatch/生命周期AST证明通过；14既有受影响测试50断言未改，无测试删除。65固定资源/11分区hash、DB350/root11/31revision/29表模块、SQL字面量delta0。350只是路径计数，迁出不计整体代码净减少。全部必需验证通过后立即本地commit，hash在Task15启动记录。完成14/20，继续Task15。

## Task 15：闭合插件存储、API辅助库及真实SDK生命周期

状态：completed

### 目标

插件/真实SDK/API辅助存储使用已发布应用获取边界与显式Schema生命周期。

### 涉及文件

- `hermes_db/backends/sqlite/plugin_storage.py`。
- `hermes_db/integration/api_resources.py`。
- `hermes_db/integration/retain_transport.py`。
- `hermes_db/integration/run_resources.py`。
- `gateway/platforms/api_server_response_store.py`。
- `gateway/platforms/api_server_run_idempotency.py`。
- `plugins/kanban/dashboard/plugin_api.py`。
- `plugins/memory/retaindb/__init__.py`。
- `plugins/platforms/discord/recovery.py`。
- `plugins/platforms/matrix/adapter.py`。
- `plugins/platforms/matrix/adapter_crypto_sqlite.py`。
- `plugins/plugin_storage.py`。
- 新落位：`gateway/platforms/api_server_run_resources.py`, `hermes_cli/db_api.py`, `hermes_db/domains/plugin_storage/records/sqlite.py`, `hermes_db/domains/runtime/resources.py`, `plugins/memory/retaindb/transport.py`, `plugins/platforms/matrix/storage_schema.py`。
- 新建：`plugins/platforms/matrix/storage_schema.py`。
- 新建：`tests/gateway/test_matrix_sqlite_schema_lifecycle.py`。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task6, Task8, Task9, Task11, Task14。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：真实SDK、插件和API辅助库正常工作；普通打开无DDL，私有/具体插件跨越未增加，核心与插件各自承担实际生命周期。

### 实施步骤

1. portable SQLitePluginStore归records业务，constructor中的Schema只由明确安装/setup/upgrade调用；普通plugin_store操作不隐式DDL。
2. 通过已有发布模块plugins.plugin_storage实现实际Matrix/Discord/Retain获取facade，更新真实插件消费者；不把新私有infra路径加入plugin_api白名单，也不从核心导入具体插件。Retain应用线程归原插件目录，Profile/owner/redaction能力通过真实公开facade取得。
3. API OwnedApiStore保持业务生命周期；Response/Run Store/ProfileRunStores应用获取归db_api和API应用拥有者。
4. 真实mautrix0.21.1已核对：UpgradeTable.upgrade即使最新也CREATE版本表；显式Matrix setup/插件CLI status/upgrade使用原SDK升级表，普通Database.create(sqlite_url)不挂升级表、start后SELECT验证版本/表再创建真实PgCryptoStore/OlmMachine。
5. 复用现有ctx.register_cli_command及platform setup_fn注册插件自己的matrix db status/upgrade，核心db命令不硬编码导入Matrix插件；保留crypto对象、ratchet、关闭drain及新PID恢复。
6. 保留插件host/Profile/秘密及owner-only边界，真实PG全进程拒绝全部SQLite连接；SDK SQLite不依赖PG服务。

### 验证方式

- `Test-Native -Files @('tests/gateway/test_matrix_sqlite_schema_lifecycle.py','tests/gateway/test_matrix_crypto_store_per_profile.py','tests/gateway/test_matrix_plugin_setup.py','tests/hermes_db/contracts/test_matrix_close.py','tests/hermes_db/contracts/test_native_http_turn.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/gateway/test_matrix_sqlite_schema_lifecycle.py','tests/gateway/test_matrix_crypto_store_per_profile.py','tests/gateway/test_matrix_plugin_setup.py','tests/hermes_db/contracts/test_matrix_close.py','tests/hermes_db/contracts/test_native_http_turn.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_matrix_sdk_flows.py','tests/hermes_db/postgresql/test_matrix_sdk_concurrency.py','tests/hermes_db/postgresql/test_matrix_close.py','tests/hermes_db/postgresql/test_single_backend.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- 两端附加直接受影响的5个Native合同：tests/gateway/test_api_sqlite_schema_lifecycle.py、tests/plugins/test_plugin_schema_lifecycle.py、tests/plugins/test_portable_storage.py、tests/hermes_db/contracts/test_plugins_sqlite_optional_drivers.py、tests/hermes_db/contracts/test_discord_sqlite_optional_drivers.py。验证实际新PID、普通打开0DDL、缺失Schema拒绝及原DDL初始化原子性；不扩大到旧业务目录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

真实SDK、插件和API辅助库正常工作；普通打开无DDL，私有/具体插件跨越未增加，核心与插件各自承担实际生命周期。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task14本地commit91af47415bb0bcb7350d278bf61639d5faf69948；14/20。11分区hash全部验证，当前Task主责/读取点按索引展开。依用户精简策略，仅验证当前插件/SDK/API边界，历史PG深度结果不计本轮成果。

### 验证证据

必需Native两端10文件：Windows12passed/6Linux-only skips，Linux18passed；PG4文件8passed。SDK当前等待方式4passed，旧模拟协议直接读取点14passed；全部实际exit0。16check及DB/插件边界、生成合同、空白exit0。命令/解释器/cwd/home/runtime/源码身份、先失败与修正、验证源差异及未验证项见[Task15证据](../designs/hermes-db-two-layer-task15.json)。


结算：插件Profile/Worker与具体应用wrapper归已发布facade，Matrix actor归应用，业务保留SQL/资源/SDK合同。Native辅助库及真实SDK普通打开不执行DDL，创建/升级有实际显式入口；缺失Schema保留旧pickle，原事务/close/unknown commit语义保留。195原测试/504断言完整，27断言仅实际读取点改变；72方法AST证明，2处旧launch参数按明确生命周期移除。原SQL无删改，新增只读readiness5种7处；65固定资源/11hash/DB346/root11/31/29有效。移出路径不计整体代码净减少。立即本地commit，Task16启动记录hash；完成15/20。

## Task 16：收口所有消费者、patch、文档与层次检查

状态：completed

### 目标

全量读取点、活动文档和自动层次规则闭合，预算可核实。

### 涉及文件

- `hermes_db/integration/__init__.py`。
- `hermes_db/integration/postgres/__init__.py`。
- `hermes_db/integration/postgres/operations/__init__.py`。
- `hermes_db/integration/postgres/queries/__init__.py`。
- `hermes_db/integration/transfer/__init__.py`。
- 本设计/计划/映射、对应冻结manifest和安全验证记录；Task20新建docs/reviews/hermes-db-two-layer-boundary-review.md。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task2, Task3, Task4, Task5, Task6, Task7, Task8, Task9, Task10, Task11, Task12, Task13, Task14, Task15。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：每个变更/读取/测试点有已核对处置；边界与活动文档闭合，65固定资源/文件预算/静态门禁通过。

### 实施步骤

1. 逐项结算3033文件读取候选、29个Native patch候选、67个领域外依赖文件、63个capability函数和69个直接I/O候选，明确保留的值规则与已外移效果。
2. 扩展现有boundary lint：infra和技术根入口禁止业务表/catalog/Store及应用装配依赖；业务目录禁止实际进程/网络/文件副作用，逐符号纯规则复用有理由，历史固定helper单独处理。
3. 新旧内部路径、动态分发表、literal patch、AGENTS、skills与website活动文档同步；旧integration空包清除，无re-export/代理/compat flag。
4. 不删业务测试。将所有改动前测试ID映射到保留/改名/初始化setup调整，Windows基准8项/原Task24/七非WSL另账保持；freeze本轮必需测试文件列表及平台理由。
5. 真实测量DB<=359/root11、全项目生产文件变化和health，迁出应用的文件不计整体净删；若实际不能满足先修订计划/设计，不静默放宽或堆大文件。

### 验证方式

- `Test-Native -Files @('tests/scripts/test_hermes_db_boundary_lint.py','tests/tui_gateway/test_session_resume_store_boundary.py','tests/hermes_cli/test_sessions_command_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-NativeLinux -Files @('tests/scripts/test_hermes_db_boundary_lint.py','tests/tui_gateway/test_session_resume_store_boundary.py','tests/hermes_cli/test_sessions_command_boundary.py')`；预期完整命令exit0，实际计数/skip按本轮收集记录。
- `Test-Pg -Files @('tests/hermes_db/postgresql/test_cron_notepad.py','tests/hermes_db/postgresql/test_verification_store.py')`：实际API审计发现残留应用装配，迁往Cron/Agent真实拥有者；只补这两份直接合同，保留全部正常断言，不扩大旧业务目录。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

每个变更/读取/测试点有已核对处置；边界与活动文档闭合，65固定资源/文件预算/静态门禁通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task15本地commit391c4537494289c654d0d9959c63b637ed927245；15/20。全部11分区hash核对后按索引展开当前Task，保留owned/SOUL.md及target/SOUL.md；本Task只做消费者/规则/文档与最终精简清单收口。

### 验证证据

Native3文件两端各31passed，PG2文件6passed；恢复混合断言与最严格checker两端focused各6passed；全部exit0、无skip。当前完整16check及DB/插件边界、生成合同、空白均exit0。完整命令、解释器/cwd/home/runtime/源码身份、失败/修正及未验证项见[Task16证据](../designs/hermes-db-two-layer-task16.json)。


实际细化：Cron domain_operation/闭合后端表与Verification Profile/Worker RPC真实定义此前仍留API。映射补充Task16符号路由并同步7个实际消费者，业务SQL/事务边界保持，删除5个空integration入口；规则不再豁免业务api.py。最终精简清单见[verification manifest](../designs/hermes-db-two-layer-verification.json)，8层次+5消费者+3纯SQLite+1真实SDK+1发行+7PG文件组，不重跑旧目录。


结算：全部3033读取候选/132431当前解析读点、67领域边界/63能力、69I/O、29Native patch、106生命周期及58非Python文件逐项审计并回写reviewed_in=16。7旧namespace命中仅为lint拒绝规则及负例；无运行旧路径。5798保留测试ID及27例外已说明：17迁文件/改名、10显式生命周期断言调整，无业务测试删除；正常corrupt误分类断言恢复并复验。5原应用算法AST完全等价，SQL字面量delta0。65固定资源/11hash、DB340/root11/31/29通过。全项目生产Python3591→3620，迁出不冒充净减少。最终精简manifest冻结，立即本地commit，Task17启动记录hash；16/20。

## Task 17：冻结最终源码并创建全新独立PM载荷

状态：completed

### 目标

最终可执行源码/测试/资源冻结并产生全新独立安装载荷。

### 涉及文件

- 本设计/计划/映射、对应冻结manifest和安全验证记录；Task20新建docs/reviews/hermes-db-two-layer-boundary-review.md。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task16。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：5个全新PM构建真实exit0，载荷/source/driver和测试列表同一冻结身份，尚不计业务完整验收通过。

### 实施步骤

1. 从Task16真实commit冻结Git tree和archive；source与test-driver各自导出无.git/.env，记录全部tracked、生产、测试及65资源hash。
2. 用冻结源自身PM创建Windows普通SQLite、PG+messaging和Linux普通SQLite、PG+messaging+matrix、SQLite+Matrix共5个新载荷；均dev/test，普通SQLite实际不含SQLAlchemy/psycopg/Alembic/mautrix/asyncpg。
3. 用-I核对包来自冻结source、解释器/extra/SDK版本与platform；SQLite+Matrix的asyncpg只作SDK类型依赖，guard拒绝实际PG连接。
4. 参数沿用已存在的--hermes-distribution-source/--hermes-sqlite-python/--hermes-postgresql-python/--hermes-sqlite-matrix-python；控制器只记录脱敏结果和实际展开命令。
5. 不可执行源码/测试/依赖变更后需重新冻结、重建并重跑所有最终必需批次；文档结果结算只可在运行代码等价审计后沿用证据。

### 验证方式

- 执行下文“最终冻结与分层关键验证命令”；本Task相关全部命令真实exit0才完成，不能沿用旧载荷/旧数字。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

5个全新PM构建真实exit0，载荷/source/driver和测试列表同一冻结身份，尚不计业务完整验收通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-12 Task20独立初审发现major R1；以下旧完成记录属于初版SOURCE_TIP e3898db771，仅历史保留。整改源必须在全新v2根重新完成本Task；不能以旧158passed代替。

启动：Task16本地commite3898db77144cded81d64a1a750f6c2d9a31eefa作为唯一SOURCE_TIP。同一archive先导出Windows source/test-driver，全tracked哈希逐项核对；Linux独立导出及5个全新PM载荷尚待真实exit0。

### 验证证据

Windows2/Linux3全新PM环境全部实际exit0；5个独立解释器安装身份/依赖探针全部exit0。构建前后两端source与test-driver各23998文件hash0差异；SQLite及SQLite+Matrix均无SQLAlchemy/psycopg/Alembic，Linux实际SDK0.21.1。完整16check、DB/插件边界、生成合同、空白exit0。实际命令/解释器/cwd/home/runtime/源码身份及全部tracked8分区hash见[冻结manifest](../designs/hermes-db-two-layer-freeze.json)和[Task17证据](../designs/hermes-db-two-layer-task17.json)。本Task不含业务用例通过声明，skip不适用。


结算：唯一SOURCE_TIP e3898db77144cded81d64a1a750f6c2d9a31eefa，archiveSHA256 743f6d0ce34827f994f7cd631204300933e0fb7550523a111f8124dbafcef763。五载荷使用冻结源自身PM/dev,test及精确extras，不使用resolve/rawpip/rawuv/旧载荷；当前Git可执行源与冻结源一致。完成17/20并立即本地commit，Task18启动记录实际hash；当前最终业务验收与独立审查仍未完成。


R1复验启动：整改运行检查点0aa4f5973542615cd044ec748313c8c4b9c988be为v2唯一SOURCE_TIP；同一新archive先导出Windows source/test-driver并逐项核对24019文件0差异。Linux独立导出、5freshPM载荷及当前门禁尚待，旧初版结果不计新源通过。


V2当前结算：SOURCE_TIP 0aa4f5973542615cd044ec748313c8c4b9c988be；两端各source/driver 24019文件构建前后0差异，5个全新PM载荷构建及5身份/依赖探针全exit0。SQLite(含LinuxMatrix)无PG栈，SDK0.21.1。当前16check/DB与插件边界/生成合同/空白全exit0。实际argv/python/cwd/home/runtime/来源见当前freeze.json和Task17.json；初版*-initial.json及旧根独立保留，未借用其结果。完成17/20后立即本地commit，继续Task18v2。

## Task 18：执行双主机分层关键合同与消费者冒烟

状态：completed

### 目标

当前冻结版本在Windows/Linux完成Task16精简清单内的分层关键合同和消费者冒烟。

### 涉及文件

- 本设计/计划/映射、对应冻结manifest和安全验证记录；Task20新建docs/reviews/hermes-db-two-layer-boundary-review.md。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task17。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：当前源全部必需Native/消费者/纯载荷命令实际exit0；skip有理由，独立基准限制未冒充通过。

### 实施步骤

1. 两主机分别执行Task16冻结的native_layer与native_consumers精简文件组，实际给全载荷参数；同源driver运行，不调用整个旧目录回归。
2. 每个实际变化的所有权边界选必要的代表合同，优先复用本轮已通过证据；不再整组重跑hermes_state或所有消费者。精简文件组仍完整exit0并准确记录skip，不能隐瞒功能失败。
3. 单独用两主机普通SQLite载荷做真实读写/新PID恢复；Linux SQLite+Matrix做真实SDK恢复与普通startup 0DDL。
4. 逐批记录实际收集/通过/失败/skip、用例ID和平台理由；Windows既有基准8项如果仍重现，单独记录，不将失败批次标exit0或删正常断言。关键本轮失败或必需环境阻塞不能计Task完成。

### 验证方式

- 执行下文“最终冻结与分层关键验证命令”；本Task相关全部命令真实exit0才完成，不能沿用旧载荷/旧数字。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

当前源全部必需Native/消费者/纯载荷命令实际exit0；skip有理由，独立基准限制未冒充通过。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-12 Task20独立初审发现major R1；以下旧完成记录属于初版SOURCE_TIP e3898db771，仅历史保留。整改源必须在全新v2根重新完成本Task；不能以旧158passed代替。

启动：Task17实际commit8456ec7d728031d0d4c475e26d58d7483b745925；17/20。继续唯一SOURCE_TIP e3898db77144cded81d64a1a750f6c2d9a31eefa，本Task运行native_layer/native_consumers/sqlite_payload双端及sqlite_matrix_payload Linux；发行/PG组留Task19，全部使用冻结driver/新解释器。

### 验证证据

冻结driver与5载荷中的实际指定新解释器：Windows3组63passed/2Linux-only SDK close skips；Linux4组69passed/0skip；全部真实exit0。测试后两端source/driver各23998文件0差异，当前Git运行源/测试等价。当前16check/DB边界/插件边界/生成合同/空白exit0。完整展开命令、解释器/cwd/home/runtime/源码身份、每个skip用例与未验证项见[Task18证据](../designs/hermes-db-two-layer-task18.json)。


结算：本轮关键分层/消费者、纯SQLite实际读写新PID恢复及Linux真实SDK普通打开0DDL均由冻结载荷实际通过，未借用旧开发批次数字。无本Task失败或测试删改。65固定资源/DB340/root11/31/29由相同源码及23998文件hash保持。完成18/20后立即本地commit，Task19启动记录hash；不宣称全系统重新验收。


V2复验启动：Task17实际commit6549ee9bf014a369b85dfbcb887c2dd30202a11a，source/driver清单hash全部核对后运行7个新载荷Native/SQLite/SDK完整精简组；发行/PG组留Task19。


V2当前结算：7个完整精简组全部实际exit0，Windows63passed/2Linux-only SDK close skips，Linux69passed/0skip。当前24019文件source/driver两端0差异，运行源/测试与整改检查点0aa4f597等价；16check/DB与插件边界/生成合同/空白全exit0。实际命令/解释器/cwd/home/runtime/SourceTip、skip用例见当前Task18.json。初版数字不计本次通过。完成18/20后立即本地commit，继续Task19v2。

## Task 19：执行PG、发行与SDK分层关键验证

状态：completed

### 目标

当前冻结版本完成分层相关PG/发行/Schema/SDK及关键故障恢复合同，不重复旧PG全部领域深度验收。

### 涉及文件

- 本设计/计划/映射、对应冻结manifest和安全验证记录；Task20新建docs/reviews/hermes-db-two-layer-boundary-review.md。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task17, Task18。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：当前精简PG/发行/SDK/迁移与关键恢复清单实际exit0、同源hash可核对，未验证平台及未重跑的旧深度业务验收均具名独立。

### 实施步骤

1. 在fixture拥有的随机Schema执行Task16精简pg_layer清单 -j1 -m integration；重点覆盖本轮所有权/Schema/回执与资源边界，保留必要用例内部并发，不管理数据库服务。
2. 两主机做必要独立发行/初始化冒烟；Linux执行本轮Matrix实际生命周期代表合同，PG关键业务子进程继续捕获全部sqlite3 audit连接入口。不重跑未变化的SDK全部业务场景。
3. 验证临时Profile新PID SQLite A→PG B→SQLite A→PG B独立数据集，故障/未初始化明确失败且0SQLite、0意外DDL；从旧revision升级、重复升级及0031重开。
4. 真实do_commit后丢ACK、receipt/tombstone/debt、新进程与多scope恢复必须保留；不能用提交前异常或mock存储替代。
5. 全部精简最终命令真实exit0后核对两主机source/driver最终hash0差异、当前源码Git等价及静态/生成契约/插件边界；不外推旧PG所有领域已在本轮重验。

### 验证方式

- 执行下文“最终冻结与分层关键验证命令”；本Task相关全部命令真实exit0才完成，不能沿用旧载荷/旧数字。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

当前精简PG/发行/SDK/迁移与关键恢复清单实际exit0、同源hash可核对，未验证平台及未重跑的旧深度业务验收均具名独立。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

2026-11-12 Task20独立初审发现major R1；以下旧完成记录属于初版SOURCE_TIP e3898db771，仅历史保留。整改源必须在全新v2根重新完成本Task；不能以旧158passed代替。

启动：Task18实际commitbcfdeaaff9c4d293139f6dbd934a15e4b07eb6f1；18/20。唯一SOURCE_TIP e3898db77144cded81d64a1a750f6c2d9a31eefa及全部新载荷保持不变，执行distribution两端和pg_layer Linux全部完整精简文件，显式传独立source/解释器及私有fixture路径。

### 验证证据

Windows发行1文件3passed/1Linux-only SDK skip；Linux发行1文件4passed，PG7文件19passed/0skip；全部真实exit0。真实COMMIT后丢ACK、根锁/超时/rollback、临时Profile独立切换、0030→0031/重复升级重开、独立PG全业务/多scope/新PID/实际SDK及全部SQLite入口拒绝均由本轮新载荷执行。测试后两端source/driver各23998文件0差异；16check与DB/插件边界、生成合同、空白exit0。全部10冻结批次完整输出已读审计，总158passed/3真实平台skip，详细命令/解释器/cwd/home/runtime/源码身份、每个skip、原始输出hash见[Task19证据](../designs/hermes-db-two-layer-task19.json)。


结算：全部必需精简冻结批次实际exit0、当前源码与唯一SOURCE_TIP等价，无本Task失败/源码或测试删改。固定65资源/DB340/root11/31/29通过同源hash保持。完成19/20后立即本地commit，Task20启动记录实际hash；尚待最终verification与独立审查，不能READY_TO_MERGE，不外推全系统验收。


V2当前启动：Task18实际commit8925f5ca1805a2bbff2e65a2907a15da31591d5c；source0aa4f597保持。使用v2新源/新解释器运行distribution两端和PG8文件完整组，包含R1真实业务合同，之后重新核对所有hash及独立复审。


V2当前结算：两端发行Windows3passed/1Linux-only SDKskip、Linux4passed；真实PG8文件20passed/0skip（含R1新合同）。全部3组及当前16check/DB与插件边界/生成合同/空白实际exit0；测试后source/driver双端各24019文件hash0差异。全10组完整输出及hash已重新审计，总159passed/3真实平台skip，初版158不计本次通过。实际argv/python/cwd/home/runtime/源码/skip见当前Task19.json。R1原始报告与真实红灯保留，整改源仍待独立复审，不得READY_TO_MERGE。完成19/20后立即本地commit。

## Task 20：独立代码审查、整改复验和最终交付

状态：pending

### 目标

以独立审查和最新证据判定本轮分层是否可合并。

### 涉及文件

- 本设计/计划/映射、对应冻结manifest和安全验证记录；Task20新建docs/reviews/hermes-db-two-layer-boundary-review.md。
- 同Task同步映射consumer_files中实际读取点、动态字符串和测试patch；主责Task之外的依赖导入变化也必须当场完成。

### 依赖与接口

- 前置：Task18, Task19。
- 输入：固定源码/已有合同与前置Task已通过的实际资源/接口。
- 输出：独立APPROVED、无未处置问题、最新证据完整，本轮20/20及本地commit可恢复；不外推全系统验收。

### 实施步骤

1. 执行verification-before-completion，逐条核对20Task、全部源/资源/测试清单和实际exitcodes，缺证不得READY_TO_MERGE。
2. 独立code-review读取从0d基准的完整diff、映射/冻结/日志和测试改动，检查层次真实职责、原子性/文件安全、SDK/插件边界、普通打开无DDL以及生产隔离。
3. 每项blocking/major/minor给出处理；实际改代码/测试/依赖则回到Task17重新冻结和全部最终组复验；只改文档结果则做源码等价及最新文档门禁。
4. 主Agent实际读取报告及结果，独立APPROVED、必需门禁全通过和全部Task完成后才标READY_TO_MERGE；更新恢复点并本地commit。
5. 不推送、创建PR、合并、部署或重启正式实例，不解除原Task24及七非WSL/Windows基准问题。

### 验证方式

- 读取正式独立审查报告与实际验证输出；独立APPROVED且所有当前必需证据齐全，整改后按影响重新冻结/复验。
- `Check-Storage`；固定61+4路径/hash、DB文件预算、接口/SQL与读取点审计写回实际命令和结果。结构审计不替代业务测试。

### 完成条件

独立APPROVED、无未处置问题、最新证据完整，本轮20/20及本地commit可恢复；不外推全系统验收。 所有必需失败/阻塞清零或在本Task保持未完成；立即记录本地恢复commit。

### 执行结果

启动：Task19实际commitc24e694e03200f5eaa60a3225f42a961d4c89fa1；19/20。verification-before-completion已逐条核对1–19Task/规划checkpoint、全部10冻结批次完整输出及hash、5freshPM载荷、当前Git运行源/测试/lock等价、11分区hash/65固定资源与正式目录HEAD/clean；均通过。状态REVIEWING，独立审查尚待，不宣称READY_TO_MERGE。

### 验证证据

verification-before-completion：当前Git全部运行Python/测试/pyproject/uv.lock逐字节与唯一SOURCE_TIP相同；10冻结完整批次全exit0，158passed/3真实平台skip；测试后5个新解释器再核对依赖/安装身份均exit0；11映射hash/65固定资源/规划与Task1–19祖先/正式HEAD90a2987且clean全部通过。实际命令、解释器/cwd/home/runtime/源码身份见[Task20证据](../designs/hermes-db-two-layer-task20.json)。独立只读Reviewer任务/root/final_two_layer_review正在审查；最终元数据静态门禁仍在运行，不能READY_TO_MERGE。


独立初审结论CHANGES_REQUIRED，R1真实PG红灯后只加ids is None提前return，focused1passed。原子成功分解兼容合同/新冻结全量精简组/独立复审尚待。初审报告与失败保留，Task17–19重置为复验，当前16/20；这是补齐必需验收，未缩减范围。

## 最终冻结与分层关键验证命令

初版Task17取Task16运行代码commit；R1整改后Task17取整改运行代码检查点commit作为新的唯一SOURCE_TIP，旧快照另存*-initial.json。保存Git tree、archive SHA256、全tracked/生产/测试hash及PM参数，source和test-driver分别从同一archive导出。以下固定的最终根与测试参数只用于该唯一冻结；若需要重新冻结使用新的独占根并更新全部记录，禁止覆写或混合旧成功结果。

- Windows最终根：D:/AI/hermes-db-packages/.build/two-layer-acceptance-final-v2；source、test-driver、env-sqlite、env-postgresql在该根下。
- Linux最终根：/var/tmp/hermes-db-two-layer-acceptance-final-v2；同上并增加env-sqlite-matrix。
- 所有环境由冻结source自身PM建立；两端dev/test。Windows extras为空或postgresql,messaging；Linux为空、postgresql,messaging,matrix或matrix。PM CLI默认frozen，本轮不使用--resolve或raw pip/uv。
- 冻结导出与5个构建的实际执行协议如下；全部输出通过Invoke-SafeBatch或等价的安全控制器捕获。Task17将实际source tip/tree/hash/路径与展开命令写入docs/designs/hermes-db-two-layer-freeze.json，不使用旧载荷。

```powershell
$FreezeRoot='D:/AI/hermes-db-packages/.build/two-layer-acceptance-final-v2'
$Archive='D:/AI/hermes-db-packages/.build/two-layer-acceptance-final-v2.tar'
if (Test-Path -LiteralPath $FreezeRoot) { throw 'Frozen root already exists; choose a new exclusive root and update the manifest/commands' }
$ValidationSourceCommit=(git -c safe.directory=D:/AI/hermes-db-packages rev-parse HEAD).Trim()
git -c safe.directory=D:/AI/hermes-db-packages archive --format=tar --output=$Archive $ValidationSourceCommit
if ($LASTEXITCODE -ne 0) { throw 'Git archive failed' }
& $DevPython -c 'import sys,tarfile; from pathlib import Path; root=Path(sys.argv[2]); root.mkdir(); [(root/name).mkdir() for name in ("source","test-driver")]; bundle=tarfile.open(sys.argv[1]); [bundle.extractall(root/name,filter="data") for name in ("source","test-driver")]; bundle.close()' $Archive $FreezeRoot
if ($LASTEXITCODE -ne 0) { throw 'Independent extraction failed' }
Push-Location ($FreezeRoot+'/source')
Invoke-SafeBatch -Label 'pm-sqlite-win' -Executable $DevPython -Arguments @('-m','pm.build_env','--source',($FreezeRoot+'/source'),'--out',($FreezeRoot+'/env-sqlite'),'--group','dev','--group','test')
Invoke-SafeBatch -Label 'pm-pg-win' -Executable $DevPython -Arguments @('-m','pm.build_env','--source',($FreezeRoot+'/source'),'--out',($FreezeRoot+'/env-postgresql'),'--group','dev','--group','test','--extra','postgresql','--extra','messaging')
Pop-Location
```

Linux独立导出同一archive，再运行冻结源自身PM（通过安全控制器保存完整argv/exitcode；HOME/RUNTIME在PM启动前绑定）：

```powershell
wsl.exe -d Ubuntu-26.04 -- /usr/bin/python3 -c 'import sys,tarfile; from pathlib import Path; root=Path(sys.argv[2]); assert not root.exists(); root.mkdir(); [(root/name).mkdir() for name in ("source","test-driver")]; bundle=tarfile.open(sys.argv[1]); [bundle.extractall(root/name,filter="data") for name in ("source","test-driver")]; bundle.close()' /mnt/d/AI/hermes-db-packages/.build/two-layer-acceptance-final-v2.tar /var/tmp/hermes-db-two-layer-acceptance-final-v2
wsl.exe -d Ubuntu-26.04 --cd /var/tmp/hermes-db-two-layer-acceptance-final-v2/source -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-two-layer-acceptance-final-v2/pm-profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime /var/tmp/hermes-db-two-layer-task5-dev/env/bin/python -m pm.build_env --source /var/tmp/hermes-db-two-layer-acceptance-final-v2/source --out /var/tmp/hermes-db-two-layer-acceptance-final-v2/env-sqlite --group dev --group test
wsl.exe -d Ubuntu-26.04 --cd /var/tmp/hermes-db-two-layer-acceptance-final-v2/source -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-two-layer-acceptance-final-v2/pm-profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime /var/tmp/hermes-db-two-layer-task5-dev/env/bin/python -m pm.build_env --source /var/tmp/hermes-db-two-layer-acceptance-final-v2/source --out /var/tmp/hermes-db-two-layer-acceptance-final-v2/env-postgresql --group dev --group test --extra postgresql --extra messaging --extra matrix
wsl.exe -d Ubuntu-26.04 --cd /var/tmp/hermes-db-two-layer-acceptance-final-v2/source -- /usr/bin/env HERMES_HOME=/var/tmp/hermes-db-two-layer-acceptance-final-v2/pm-profile HERMES_RUNTIME_DIR=/var/tmp/hermes-db-packages-f2dc945598034dcca7f2bd6b9ae4794a/runtime /var/tmp/hermes-db-two-layer-task5-dev/env/bin/python -m pm.build_env --source /var/tmp/hermes-db-two-layer-acceptance-final-v2/source --out /var/tmp/hermes-db-two-layer-acceptance-final-v2/env-sqlite-matrix --group dev --group test --extra matrix
```


以下最终测试由Task16冻结到docs/designs/hermes-db-two-layer-verification.json，逐组包含files、覆盖的边界、平台/载荷与理由、必要参数及sha256。Task17在任何业务测试前从同一冻结archive导出该清单；Task18/19通过Invoke-SafeBatch展开真实argv并记录exitcode，不使用开发checkout或旧载荷。

- Windows/Linux native_layer、native_consumers：同根PG测试解释器，scripts/run_tests.sh加清单中的少量完整文件，-j2 --file-timeout1200 -- --tb=short -ra及原有独立载荷参数。
- 纯SQLite：同根env-sqlite父/子解释器，在sqlite_payload精简组实际写入并新PID恢复，拒绝PG依赖导入；Linux sqlite_matrix_payload组验证实际SDK显式升级、普通启动0DDL和恢复。
- PG：同根PG解释器，pg_layer精简组，-j1 --file-timeout1200 -- --tb=short -ra -m integration --postgres-test-config=<既有私有fixture配置路径>。仅fixture拥有的随机Schema，不打印配置、DSN或秘密。
- distribution与sdk：仅精简清单的本轮路径/资源/生命周期关键合同；保留真实COMMIT后丢ACK、新PID、scope与0SQLite验证。
- 若实际变更使某一关键合同不足，补充该直接风险对应的用例，不按习惯扩大成目录级全部旧业务深测。纯格式/文档修正使用运行等价与轻量检查，避免重复整组业务测试。

精简前的完整目录命令保留在Git历史805122d791及更早计划中，属于可选深度回归，不再作为当前必需执行项。源码/资源冻结、5个全新PM构建、当前精简批次真实exit0与独立审查继续强制；实际结果只支持本轮分层声明。

## 设计覆盖与验收对应

| 设计要求 | Task |
| --- | --- |
| infra独立、两种真实数据源和技术生命周期 | 2–8、17–19 |
| 业务资源/查询/回执/Schema明确归属 | 5、6、9–15 |
| SQLite连接与业务适配分开、普通打开无DDL | 3、4、7、8、15、18 |
| 固定历史资源、真实升级和独立发行 | 1、6、7、15、17、19 |
| 应用装配/进程/文件归包外、原事务和栅栏保持 | 9–15 |
| Worker owner、Profile绑定、提示缓存和数据集隔离 | 5、9–15、18、19 |
| 全量消费者/patch/动态/文档、无shim和预算 | 每Task同步，16收口 |
| 当前精简关键合同、独立审查、按影响整改复验 | 17–20 |

## 最终验证

### 执行命令

后续执行用户精简策略下的关键合同清单及必要门禁，不执行精简前的目录级全量组。完成后以真实manifest中的source/解释器/cwd/环境路径和退出码替换执行记录；不得将本轮规划自检或旧分包/精简验收算入。

### 当前执行结果

- 当前实施：Task1–19已完成；R1最小修正、真实红绿灯、全新v2五载荷及全部10精简冻结批次已通过。当前19/20，Task20独立复审仍待；初版CHANGES_REQUIRED和158结果单独历史保留。
- 初版精简冻结验证（已被R1失效，不能算整改源结果）：10完整命令均exit0，Windows66passed/3Linux-only skips，Linux92passed/0skip，总158passed。PG7文件19passed；SDK、独立发行及纯SQLite实际读写/新PID均使用5个全新PM载荷。
- 冻结source/test-driver两端各23998文件hash0差异；当前Git全部Python/测试/lock逐字节等价，固定65资源/DB340/root11/31/29保留。
- 本轮Task20独立初审CHANGES_REQUIRED，仅R1一项major；整改后须独立复审APPROVED，旧结果不能作为整改源批准。
- Task1–19证据见各Task及对应诊断记录。当前精简冻结批次、SDK与5个全新PM载荷均已实际通过；Task20独立审查尚未完成。
- 规划结构/基准/本地链接及文档静态自检：实际命令与结果写入下方准备记录。
- 代码审查：本轮独立初审CHANGES_REQUIRED，原始报告及R1证据已保存；整改源独立复审尚待，不能READY_TO_MERGE。

### 未通过项目与最终状态

当前为`VERIFYING`，Task1–16已完成；Task20独立初审major R1已作最小修正，Task17–19须用v2新源/新载荷重验，独立复审仍待，因此不能READY_TO_MERGE。启动后如有实际失败为FAILED、外部阻塞为BLOCKED并记录；独立APPROVED及全部20Task/必需门禁完成后才READY_TO_MERGE。本轮计划不解除原统一Task24、七非WSL缺证或Windows八项基准问题。

## 规划准备记录与恢复

以下保留规划阶段原始记录。当前恢复入口是文首进度及Task20，不重新从Task1实施；规划数字/未创建分支的描述只指2026-11-10。

2026-11-10只在隔离checkout读取源码/Git/已有测试和真实SDK协议并准备文档；没有导入应用、连接业务数据库、初始化PM环境、创建实施分支或提交。已有隔离PM解释器仅执行标准库/Git/AST自检；实际SDK检查只读mautrix0.21.1的create/start/upgrade协议。

开始实施从Task1恢复：先读设计、计划、映射索引及相关AGENTS，按Task读取分区，核对当前用户修改和源基准，在隔离新分支建立规划检查点；每Task完成立即记录实际结果并本地commit，不在单项完成后主动停止。正式实例保持原样。

### 规划自检实际记录

- 在绑定隔离HOME/RUNTIME后，使用`D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe .build/two-layer-plan/validate_plan.py`：exit0。500个Git源码hash、359个DB模块全覆盖、141个外部源码、20项全部pending及依赖有序、61+4固定资源及原位、测试路径/本地链接/Markdown、所有分区hash/条目数和预算均通过；planning-check.json。
- 使用PowerShell Language.Parser静态解析计划内7个PowerShell代码块：0语法错误，未执行代码块；powershell-check.json。
- 首轮`PM Python scripts/check --staged --base 0d8782ba8a`真实exit1，仅blob-size失败：单个生成映射4184 KiB超过500 KiB。已按源码/Native/生产与测试消费者/边界分区，并保留实际决策、源码及ABIhash、所有消费者文件/行号/provider集合；可由Git重建的完整AST/45160读取点保留ignored .build。所有分区均低于500 KiB，不修改allowlist。初轮日志planning-static-first-failed.log。整改后实际运行`D:/AI/hermes-db-packages/.build/package-layout/test-env/Scripts/python.exe scripts/check --staged --base 0d8782ba8a`：exit0，16 checks, ok；完整结果在planning-static-final.log及带实际退出码的planning-static-final.json。
- 实施分支未创建、规划提交未创建、20项未实施；未创建本轮开发/最终PM载荷或连接业务数据库。正式目录只读核对仍90a2987e8c且clean；当前隔离HEAD仍0d8782ba8a，既有生产/测试/旧规划历史未改。

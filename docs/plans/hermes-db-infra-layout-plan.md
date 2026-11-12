# hermes_db infra 目录简化实施计划

## 决策与范围

- 用户已确认移除冗余 `backends` 目录；依据既有 [两层设计](../designs/hermes-db-two-layer-boundary.md) 继续实施，无业务边界变化。
- 基准：`a8afc874d94f0a58fa89a7a91fec35699f25fa48`。实施目录 `D:/AI/hermes-db-packages`，普通分支 `refactor/hermes-db-infra-layout`；正式目录 `D:/AI/hermes-agent` 在准备完成前保持原代码运行。
- 路径：`hermes_db/infra/backends/sqlite` → `hermes_db/infra/sqlite`；`hermes_db/infra/backends/postgresql` → `hermes_db/infra/postgresql`。删除空的中间包初始化文件，不保留内部 re-export shim。
- 只移动模块并同步生产导入、动态字符串、测试 patch 点和活动文档/AGENTS。SQL、算法、事务/锁/scope、Schema 生命周期、异常与关闭语义保持；不变更依赖或正式配置/数据。
- 原20项实施、冻结清单、映射和独立审查是此前源码身份的历史证据，原样保留。本轮另建移动清单和最新证据，不改写旧 hash 或把旧结果计为本轮通过。

## 当前状态

`READY_TO_MERGE`；3/3 完成；用户已有未跟踪 `owned/`、`target/` 保留。最终本地合入沿用用户已授权的正式目录验收流程，无推送或PR。

| Task | 内容 | 状态 | 完成条件 |
|---|---|---|---|
| 1 | 核对实际源码、引用、相对路径与固定资源，保存移动清单 | completed | 全部活动读取点与历史证据分类，固定资源记录，计划检查点 |
| 2 | 移动两个后端实现，删除空中间包，同步读取点和活动文档 | completed | 归一化后代码/SQL等价，活动旧引用为零，轻量合同通过 |
| 3 | 最终静态门禁、完整差异自审与验收准备 | completed | 最新检查通过，保存范围与限制，允许正式目录快进更新 |

## 必需验证

先绑定隔离 `HERMES_HOME=D:/AI/hermes-db-packages/.build/infra-layout/profile`、`HERMES_RUNTIME_DIR=D:/AI/hermes-db-packages/.build/package-layout/runtime`，使用既有项目PM解释器 `D:/AI/hermes-db-packages/.build/two-layer-dev/win/env/Scripts/python.exe`。本轮机械目录简化不重复五载荷/PG深测；不改变之前验收结论的覆盖范围。

- 操作审计：逐文件基准文本仅替换模块/路径前缀后应与新文件一致；AST与SQL字符串归一化后相同。核对65固定资源字节、31 revision、29表模块、根11及DB Python上限；编译受影响Python。
- 测试统一 `D:/Programs/Git/bin/bash.exe scripts/run_tests.sh`，少量完整文件覆盖技术隔离、PG池生命周期、SQLite真实读写/新PID恢复、API显式Schema和一个真实生产消费者；`HERMES_PYTHON` 为上述PM解释器，`HERMES_TEST_FILE_RETRIES=0`。
- `python scripts/check --staged --base a8afc874d94f`；`python scripts/hermes_db_boundary_lint.py --check`；`python scripts/boundary_lint.py --check`；`python scripts/gen_gateway_contracts.py --check`；`git diff --cached --check`。
- 正式应用：官方入口安全停止/快进合入/启动，绑定原正式HOME；确认新PID、运行源码身份、存储状态及Webapp监听。优先正常空闲停止，保持既有生命周期保护。

## 执行证据

Task1：实际基准a8afc874d94f；14模块、175活动文件（172Python/3规则与活动文档）、11历史引用文件；原11分区引用hash及65固定资源均通过，无固定资源需要移动或改写。映射见[本轮清单](../designs/hermes-db-infra-layout-map.json)。inventory/prepare命令均由上述PM解释器在隔离cwd执行，exit0；无应用导入或数据库操作。原用户未跟踪目录保留。首次raw hash校验exit1发现Windows工作树CRLF；Git blob与原映射一致，随后分别冻结Git规范字节和工作树原始字节，未改固定文件。一次诊断因默认GBK读取JSON失败，改为显式UTF-8后exit0。完整输出仅留本地ignored `.build/infra-layout/`，不提交秘密或原始运行日志。

## 最终验证

Task3已完成：当前运行代码为 `9d6870622c1f007cb9ff7908d29c294452b995fd`。`python scripts/check --staged --base a8afc874d94f` exit0：16 checks；181文件health 0 blocking/0 advisory（87.9s）。插件边界829/26、生成合同、完整差异/暂存空白均exit0。上述命令使用计划指定PM解释器、隔离cwd/HOME/RUNTIME，完整输出在 `.build/infra-layout/static.log`、`boundary_lint.log`、`gen_gateway_contracts.log`。

完整Git差异自审 `python .build/infra-layout/review.py` exit0：181Python逐字节只变模块/路径前缀，1359个SQL字面量相同，65固定Git资源hash相同，零越范围修改、零活动旧namespace读取点，无未处理问题。审查结论为 [APPROVED（自审）](../reviews/hermes-db-infra-layout-review.md)，明确不冒充独立审查；原20项独立审查保留原源码范围。

当前5完整文件12passed/0failed/0skip。未新增安装载荷、未重跑PG全领域深测或SDK全组，未变Schema/SQL/事务/配置；当前结论只覆盖机械目录简化、动态读取点及实际轻量合同。此前Task24/非WSL/Windows历史问题维持原记录。

最后证据提交只改活动文档和计划，运行Python/测试/依赖必须与上述实施commit等价。正式目录更新执行及新PID/代码身份/存储/Webapp状态保存到本地ignored `.build/infra-layout-rollout-20261112/runtime-result.json`（正式目录），用户功能验收仍由用户进行。

Task2：Task1实际commit `cf3df8824cd8c47ebef0bca36d5c79e229eef380`。14模块直接迁入infra/sqlite和infra/postgresql；175活动引用文件同步，另更新当前设计与hermes_db/AGENTS。原184文件的181Python逐字节仅允许模块/路径前缀替换，AST/编译通过，3550条assert保持；固定65原工作树字节不变。移除唯一空中间包后DB339/root11/31revision/29表模块。14新模块实际导入身份通过，旧namespace不存在；活动读取点零旧引用（历史映射/冻结记录保留）。

实际验证cwd为隔离checkout，上述PM解释器和隔离HOME/RUNTIME；`python .build/infra-layout/move.py` exit0；`python scripts/hermes_db_boundary_lint.py --check` exit0，8534依赖/0违规。`D:/Programs/Git/bin/bash.exe scripts/run_tests.sh tests/hermes_db/contracts/test_infra_independence.py tests/hermes_db/contracts/test_infra_resource_ownership.py tests/hermes_db/contracts/test_session_connection_pool.py tests/hermes_db/contracts/test_sqlite_open_lifecycle.py tests/hermes_cli/test_sessions_command_boundary.py -j 2 --file-timeout 180 -- --tb=short -ra` exit0：5完整文件12passed/0failed/0skip。无业务测试退役或正常断言删除；本轮只减少一个空初始化文件，不宣称业务代码净减少。

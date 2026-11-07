# PostgreSQL 会话后端验收审查

日期：2026-11-07。分支：`feat/postgresql-session-storage`；功能起点：
`ff09cead02e906a4b1da909268c2cc58ec6e144d`；生产基准及已归档独立发行载荷：
`2192e598eb`。工作区另有下述 SQLite 默认路径兼容和 CLI 恢复导入顺序修正；
后端及受影响入口验证已通过。严格完成 17/18，Task 18 不标完成；
当前验收门禁 **FAILED**，整体审查结论 **CHANGES_REQUIRED**。

## 审查范围

本轮独立 Reviewer 只读检查新增 `tests/hermes_db/postgresql/test_distribution_initialization.py`、
发行测试、PG 测试夹具，以及三项 gateway 测试修正的完整 diff、相关实现和基线日志，
并复核 `hermes_db/access.py` 默认路径兼容修正、历史意图和新增行为契约，
以及后续四份 CLI 测试与 voice fixture 修正，
最后核对 CLI 恢复顺序、hosted-room 时钟/TTL 测试和最终补验日志，
核对当前文档差异及下列日志，仅更新本报告。没有读取秘密配置、
连接数据库、操作数据库服务、修改生产或测试代码，亦无 Git 写操作。实际 PG、Linux 和
构建由主 Agent 执行，Reviewer 核对日志，不声称亲自执行。没有逐行覆盖完整分支所有
入口、搜索和平台投递，本报告不是完整安全审计。

已有四份独立阶段性报告，其早期限制属于各自检查点，后续事实以处置记录和当前门禁为准：

- [作用域、事务、移动保全、压缩与幂等](postgresql-core-review.md)。
- [初始化、扩展前置与启动健康](postgresql-initialization-review.md)。
- [真实驱动 INSERT 计数与变更观察器](postgresql-insert-counts-review.md)。
- [入口恢复、NUL、模型标记与查询投影](postgresql-surface-projections-review.md)。

## 问题列表及处置

本轮未发现新的 blocking 或 major 生产代码问题。此前可定位问题已整改并有对应回归：

| 级别与状态 | 问题及处置 | 详细证据 |
| --- | --- | --- |
| major，已关闭 | 移动接收确认只比较数量可能删除唯一源数据；现核对实际接收快照及消息前缀，允许保全原消息的正常追加，其他漂移拒绝退休源。 | core 报告 |
| major，已关闭 | prepared 压缩未观察直接追加；现以压缩谱系 transcript revision 在提交锁内拒绝快照漂移。 | core 报告 |
| minor，已关闭 | missing donor 触发 TypeError；现返回明确业务结果。 | core 报告 |
| major，已关闭 | 实际驱动 INSERT rowcount=-1 导致计数错误及冲突空写误报变化；写连接保留实际 rowcount。 | insert-counts 报告 |
| major，已关闭 | PG JSON getter 因其他合法字段的 NUL 使恢复、viewer、模型配置和显示查询失败；使用作用域原文分页或 0004 派生投影。SQLite quoted-key 路径与移动摘要的派生列问题一并关闭。 | surface-projections 报告 |
| major，已关闭 | 新 storage 导入发生在 interrupted-pull 恢复钩子之前，混合源码可能阻止自恢复；现移到恢复和 fast-version 之后普通导入组，保留原 entry-spy 行为测试。 | 本报告启动复核与 Linux 40 项 interrupted-pull 测试 |

### [minor，已整改] 发行子进程改变 cwd 后相对参数路径失效

位置：本轮初版 `tests/hermes_db/postgresql/test_distribution_initialization.py:94`。

父夹具可从当前工作目录读取相对 `--postgres-test-config`，新测试将原始参数转交给
`cwd=tmp_path` 的子进程后，相同路径指向另一位置，得到 FileNotFoundError。发行源码及
解释器使用相对路径也受影响。当前实际执行使用绝对路径，不否定初轮通过证据。
主 Agent 已在父进程 resolve 配置、源码及解释器路径，Reviewer 已读取该修改；最新
安装模式进程重启复验 3 passed，代码及验证处置关闭。此项仅涉及新测试。

## 发行初始化核对

- 独立 PM 解释器、`-I`、临时 cwd/home 及 `hermes_db.__file__` 路径断言能证明加载独立
  source-bundle。载荷已刷新至 `2192e598eb`，两个 PM 环境依赖清单未改变；这不等于
  Nix/wheel 发行构建通过。
- 秘密通过显式私有文件路径交给子进程；DSN 不进入 argv 或正常 JSON 报告，异常仅输出
  phase 和异常类型。当前代码未发现主动输出凭据的路径；Reviewer 未读取配置内容。
- 父夹具验证独立测试库和随机 Schema 标记，清理前再次核对；最新子进程在 upgrade 前
  也核对 `current_database()` 与现有标记。没有自动安装扩展或管理服务的路径。
- 单连接设置 `pool_size=1/max_overflow=0/connection_budget=1` 下，断言重复初始化、真实
  写读、请求重放、相同 session ID 的 store 隔离及无本地 `state.db`。这覆盖所测顺序流程，
  不能外推并发负载。
- 最新版本还启动第二独立进程并比较 PID，重读两个 store 的内容，确认原 epoch 持久化，
  新 owner 的 epoch 加一后重放同一 admission identity；覆盖句柄释放重开及进程退出后的恢复。
- 初轮原发行两项加实际 PG 初始化一项为 **3 passed / 8.4s**。之后显式改用 `chr(0)`，
  并增强归属检查、跨进程重开和路径解析。最新
  `pg-task18-distribution-process-restart-final.log` 已为 **3 passed / 17.3s**，覆盖该最终版本。

## Gateway 测试修正的独立复核

本轮没有改动生产运行时代码，以下三项测试修正未发现需要阻止采用的断言削弱：

- `test_duplicate_reply_suppression.py`：用真实 send 事件及当前 drain 任务完成取代两秒
  轮询，保留 stale 发送次数为零、pending 回复恰好一次的断言。事件不伪造成功条件，错误
  回复也会被最终断言拒绝。两侧原隔离测试均通过；这支持移除固定时间假设，但不能仅凭
  隔离通过宣称已复现或消除宽负载下所有时序问题。
- `test_journey_compress_restart_fifo.py`：原测试假定 PRESSURE_1 必定被压缩，真实基线
  显示它可属于保护尾部，实际移除的是 ACK_PRESSURE_0。新测试由压缩前模型输入与已提交
  continuation 的正文差集得到实际移除集合，要求集合非空，并拒绝每个 follower 输入
  重新出现这些内容；FIFO、原 admission identity、compacting turn 不重放、单一 continuation、
  原已提交前缀及摘要恰好一次的断言均保留。它验证恢复后的行为，没有读取实现源码或
  将预期直接 mock 成正确值。原 graceful/crash 两失败已在功能起点复现。
- `test_session_client_env.py`：生产本来就会前置合法 Hermes launcher。测试按原生
  `os.pathsep` 处理 PATH，要求 client/daemon 标志恰好出现所期望的一个；允许合法前缀，
  同时会发现旧“首项正确”检查漏掉的另一方后续路径。GEM_HOME 在三类工具环境中不得
  泄露、配置覆盖优先级、locality 证明及远程 host 值过滤等断言均保留。原两失败已在
  功能起点复现，错误值确为安装 launcher 目录。

已读局部结果：`pg-task18-linux-corrected-tests-on-base.log` 为修正后前两文件在基线
3 passed / 23.5s；`pg-task18-linux-entry-fixture-fixes.log` 为当前五文件及周边
14 passed / 22.8s；client-env 在当前和基线分别为 13 passed / 68.2s、13 passed / 45.9s
（`pg-task18-linux-client-env-corrected.log`、`pg-task18-linux-client-env-corrected-base.log`）。
这些局部结果不能替代完整宽轮的实际结果和剩余验证限制。

### 后续 CLI 与语音 fixture 复核

四份 CLI 测试改动未发现核心断言削弱：doctor 仅固定待测 gh 的可达性，仍模拟旧 JSON
字段失败并断言实际 auth 状态；无服务 restart 场景固定 service capability 为 false，仍
拒绝 caller 成为 gateway 并检查默认 profile 的 replacement argv，有单元/linger 的其他
契约未改；service 的 which 仅 mock node，其他命令恢复真实解析，仍比较完整 unit、
managed dirs 和 root PATH 隔离；oneshot 改 patch 生产函数 late-import 的
`hermes_db.access.acquire_sessions`，保留 `session_db` sentinel 的实际注入断言。

`test_session_tui_ops.py` 只给 voice 用例的独立 home 设置
`security.allow_lazy_installs=False`。实际 `voice.record` handler 先检查会话 voice gate，
之后才进入音频依赖，故该配置不绕过 off/on/off 的 4015 断言。它限制无关安装副作用，
不是把待测 gate mock 成通过。原 current 多次 RPC 超时，base 全文件通过；禁用懒安装后
单例 1 passed / 4.9s，后续 `pg-task18-linux-failed-files-recheck.log` 中完整 voice/TUI ops
文件 12 passed / 216.9s。没有原超时点的服务端栈，不能宣称 PM 下载是已证实根因。

三项原 CLI 失败已由 `pg-task18-linux-cli-failures-baseline.log` 在功能起点复现。
`pg-task18-linux-cli-fixtures-corrected.log` 中 doctor 文件 68 passed / 8 skipped、
service 文件 113 passed / 3 skipped；该组合整体仍因第一次 restart fixture 修错位置而
失败，不能标整轮通过。随后 `pg-task18-linux-restart-fixture-corrected.log` 目标完整文件
5 passed / 1.9s。oneshot seam 所在文件后续 Linux 12 passed / 2.8s，并在最终 Windows
CLI 四文件集合中再次通过。

## SQLite 默认路径兼容修正

### [minor，已关闭] 无参数普通入口忽略显式 DEFAULT_DB_PATH

位置：基准 `hermes_db/access.py:26`、`:39`、`:47`；消费者
`tools/kanban_tools.py:1178`。

原 `hermes_state_registry.acquire(None)` 和 `SessionDB(None)` 保留显式重定向；改用普通
后端入口后，无参数被提前转换成 profile home 下固定文件，既有 continuation 无法被找到。
Kanban 因而仍订阅已被压缩替代的旧 session key。15 消费者补验为 530 passed / 1 failed
（`pg-task18-linux-edge-consumers.log`），原 Kanban 用例在功能起点为 1 passed / 7.2s；
新增 shared/独立只读两项行为测试在未修复代码有效 2 failed
（`pg-task18-sqlite-default-redirect-red.log`）。

Reviewer 用 `git log -p -S _IMPORT_DEFAULT_DB_PATH -- hermes_state.py` 核对到
`05afea65f4`：该提交明确要求既有显式重定向继续优先，当前 resolver 文档及实现亦保持
此规则。因此保留 SQLite 委托语义有既有依据，不应仅改变 Kanban 测试的绑定方式。

已独立复核最终修正边界：先按当前 owning profile 或显式 path 的父目录选择后端；
PG 无参数仍用当前 profile，不读全局 DEFAULT 来决定 scope；SQLite 仅在原参数为 None
时交还 legacy 入口，显式参数继续转为 Path。exists 也先识别 PG，再仅在 SQLite 分支
检查 legacy 默认文件。中途将 `_default_db_path()` 放进共同 `_path` 的尝试导致两个 PG
失败入口用例失败，该方案已移除，其失败日志作为历史保留。直接转交显式字符串的中间
方案也已按 Reviewer 意见改回 Path，避免 `SessionDB` 对字符串执行 `.parent`。

`pg-task18-sqlite-default-scope-fixed.log` 已有 surface 契约与完整 Kanban 两文件
64 passed / 73.9s；之后显式 Path 和 exists 断言有微调。最新 Linux 同集合 64 passed /
27.0s（`pg-task18-linux-default-scope-fixed.log`），最终 109 文件 835 项完整后端亦通过。
独立 source-bundle 已同步本次生产修正，Reviewer 核对 `access.py` 与工作区 SHA256 一致；
同步后 PG 入口与发行 13 passed，当前修正的验证缺口关闭。

## 启动恢复与时钟测试的最终复核

`hermes_cli/main.py` 原新增 `main_session_storage` 导入位于恢复钩子之前；
`pg-task18-linux-clean-consumer-recheck.log` 的 entry spy 确实观察到 storage、hermes_db
和其他模块先被导入，是有效行为红灯。当前导入已移动至
`restore_interrupted_pull()`、必要 relaunch 及 fast-version 之后，未改变读库业务。
测试临时源码包补上 hermes_db，仅补齐新增实际依赖，没有 mock 恢复流程。Linux 最终
interrupted-pull 40 项及 update-finish 14 项通过；Reviewer 未发现当前顺序遗漏。

新 `tests/tui_gateway/test_hosted_room_worker_capacity.py` 保留真实 runtime.start/stop、
单 worker 预算、SQLite 状态、准确超时原因及后续 room settled。只替换 driver 模块局部
time 引用，独立 wall clock 固定 100；monotonic 从 0 起，生产在 submit 前记录 2 秒 deadline，
只有 stalled submit 完成准入后才推进至 3 秒。没有全局修改 time，也没有直接写期望终态；
测试的真实等待仍有 10 秒上限。健康 room 的 deadline 从新时刻计算并实际完成，因而仍能
发现 worker 容量没有释放。原 0.05 秒超时和 0.4 秒 lease 的机器负载依赖已从本用例移除。
logging/合法长等待用例将 lease TTL 改为 30 秒，保留秘密不入日志、长等待不 stop/重复
submit 的断言。未改变生产超时值，也未减少原行为覆盖。

最终 `pg-task18-linux-lifecycle-final-no-retry.log` 为 10 文件 **794 passed、0 failed、
2 skipped、136.8s**；包含最终时钟/TTL 用例、poller 及原六份 flaky 文件，禁用了自动重试。
这关闭本次选定集合的复验缺口，不证明原 flaky 或 poller 的根因已修复。

## 当前门禁及无法验证项

以下日志均位于 `.build/postgresql/`，由 Reviewer 只读核对。

| 门禁 | 实际证据 | 当前结论 |
| --- | --- | --- |
| Task 17 最终 PG 主题 | `pg-task17-final-hex-postgresql.log`：20 文件、284 passed、0 failed、237.4s，全部使用 0004；整改见 surface 报告。 | 此范围通过 |
| Task 17 离线及变更消费者 | `pg-task17-hex-projections-offline.log`：108 文件、546 passed、2 个缺发行参数 skip；`pg-task17-changed-consumers-final.log`：14 文件、189 passed。 | 此范围通过；skip 不计通过 |
| Task 18 后端与发行组合首轮 | `pg-task18-complete-backend-final.log`：109 文件、795 passed、0 assertion failed、38 setup errors、430.0s、exit1；9 个 PG 文件在首次连接的夹具阶段失败。 | 整轮未通过 |
| 原始连接诊断 | `pg-task18-connection-cause-probe.log`：服务端 FATAL database system is not yet accepting connections / Consistent recovery state has not been yet reached；SQLSTATE=null。 | 有拒绝连接证据，无根因证据，不归因代码、连接池或维护行为 |
| 当前完整后端 | 恢复后先有 109 文件 833 passed；默认路径修正后 `pg-task18-final-access-backend.log` 为 109 文件、835 passed、0 failed、0 skipped、866.3s。其后仅调整 main 导入位置，另以受影响入口补验。 | 此范围通过，不抹去原连接失败或推测恢复原因 |
| Linux Source SQLite 完整集合 | 同一 `2192e598eb` 真实 Ubuntu/PM 副本：`pg-task18-linux-sqlite-regression.log` 其余 210 文件 1536 passed、16 平台 skip；唯一大文件因 300s 上限被杀。后由标准 runner -j1/timeout900 得到 296 passed、238.8s，见 `pg-task18-linux-sqlite-large-file.log`。 | 211 文件两轮合计 1832 passed、0 assertion failure、16 平台 skip；原整轮 exit1/超时保留，未冒充 Windows/macOS 通过 |
| 四入口完整回归原轮 | `pg-task18-linux-all-surfaces.log`：4105 文件、35749 passed、54 failed、206 errors、517 skipped、4715.9s；44 文件失败，另有 6 flaky 文件。 | 原整轮失败，不能改写为全绿；后续逐文件补验及剩余限制见下节 |
| 后续失败集合 | 补 Node/uv 后 41 文件 566 passed/27 failed/1 error/13 skipped；clean PM 解释器 25 文件 645 passed/21 failed/3 skipped。其余闭合证据包括下述启动、生命周期以及已记录的 fixture/路径复验。 | 保留中间失败；最终剩余适用平台缺口与 flaky 不外推关闭 |
| main 移位后入口与发行 | `pg-task18-final-pg-installed-readers.log`：三文件 13 passed、0 failed、21.7s，包含 PG surface、独立 source-bundle 及 PG 跨进程恢复。access.py 和 main.py 已与独立载荷核对 SHA256 相同。 | 当前修正后的所测范围通过 |
| CLI 与启动恢复 | Windows `pg-task18-final-cli-launch-readers.log` 四文件 47 passed/9.9s；Linux `pg-task18-linux-launch-order-fixed.log` 三文件 58 passed/2 skipped/33.2s，包含 40 interrupted-pull、14 finish 及 4 logging。 | 此范围通过 |
| 最终生命周期补验 | `pg-task18-linux-lifecycle-final-no-retry.log`：10 文件 794 passed/0 failed/2 skipped/136.8s，禁重试，覆盖最终时钟和 TTL、poller 以及原六 flaky 文件。 | 该次复验通过，历史不稳定性仍保留 |
| 全功能静态门禁 | 旧 496 文件检查曾因 test_gateway_service 多一行而失败，后已修正并复验；最新 `pg-task18-final-launch-checks.log`：500 文件、14 checks ok、0 blocking/0 advisory、93.1s。 | 最新范围通过 |
| 发行与可选依赖 | SQLite 无 PG extra 的真实写读、显式缺驱动报错、独立载荷资源及 PG 初始化/跨进程恢复均在上述刷新后的发行范围通过。 | source-bundle 所测范围通过；不冒充 Nix 发行构建 |
| 类型及其他构建 | `pg-generated-typescript-final.log`：TypeScript 6.0.3，生成的 gateway contract 独立 strict typecheck 通过。 | 仅该文件通过；完整前端及 Nix/uv2nix 构建无通过证据 |

PG 17.11 / pg_trgm 1.6 环境与初始化前置已实际通过，不再把缺配置/缺扩展记作当前
阻塞。服务端拒绝连接没有被降级成成功；后续恢复原因未知，原失败日志保留。

## 尚未关闭的范围与合并限制

本轮独立复核**未发现未解决的、具有确定代码依据的 blocking/major 生产缺陷**。
这不代表完整分支获批；剩余限制有明确范围：

1. `tests/hermes_cli/test_webapp_private_launch.py:45` 起的七项私有启动页断言在现有 WSL
   失败，功能起点也同样 7 failed/5 passed，见 `pg-task18-linux-host-and-poller-baseline.log`。
   `hermes_cli/webapp_launcher.py:124` 明确在 WSL 拒绝创建只能由当前用户读取的浏览器页，
   是已有安全政策；本功能未改该文件。缺非 WSL 适用环境证据，不能 fake is_wsl，也不能
   把这七项当作 PG 后端回归。没有收到可替代平台的完成证据。
2. `test_tui_gateway_notification_poller.py:52` 曾在 current 无诊断复验中出现线程 3 秒仍不
   退出，base 隔离通过；诊断 wrapper 下通过不能证明修复。最新无诊断、禁重试集合该
   文件 1 passed，但没有生产或测试修复以及根因证据，应保留为观察到的 flaky 限制。
3. 原宽轮六份 flaky：abandoned_turn_process_cleanup、managed_worker_launch、update_lock、
   groups_route_parity、detached_process_notify_keepalive、tui_gateway_server。均在最终禁重试
   集合通过，但一次后续通过不能抹去原失败或宣称稳定性问题已消失。

干净解释器中的 recovery closure 14 passed、补缺失 extra 后 vault-key 3 passed，均已在
`pg-task18-linux-clean-consumer-recheck.log` 核对。原 editable 污染、缺工具/依赖、WSL
政策和当前已整改缺陷分别记录；不把它们笼统归为 PG 后端业务失败。

## 历史基线与文档

早期 Windows SQLite 扩大回归为 2224 passed、9 failed、1 teardown error；主 Agent 已在
功能起点复现其中七文件的 9 失败及 1 error。早期四入口和独立 TUI 运行 exit1，缺少完整
最终汇总，不能算通过。保留这些历史事实；Linux 成功不能替代 Windows 基线，历史未归类
结果也不能冒充当前 Linux 结果。当前完整宽轮已结束并失败；后续局部通过及剩余限制
按上节记录，不重新命名原整轮退出状态。

本轮根 `README.md`、`AGENTS.md`、`CONTRIBUTING.md` 没有新的暂存或工作区差异。
历史执行记录仍含早期事实，当前进度及最终验证已按新证据更新，包括 835 项后端、
刷新载荷及入口验证、794 项禁重试生命周期、500 文件静态检查和 17/18 的事实。本报告明确
区分当前已验证范围、非 WSL 证据缺口和历史基线，没有扩大实现范围或重开已关闭实现。

## 结论

**CHANGES_REQUIRED**。当前完整 PG 后端、默认路径兼容修正、启动恢复、独立安装模式、
受影响入口及最新静态检查在所述范围通过；没有新的确定 blocking/major 生产问题。
当前验收门禁为 **FAILED**：七项非 WSL 适用平台证据尚未补齐；原完整宽轮失败以及
六 flaky/poller 的不稳定性记录保留。该缺口与已通过的 PG 业务验证分开，不能将整体
改为 APPROVED 或 READY_TO_MERGE。

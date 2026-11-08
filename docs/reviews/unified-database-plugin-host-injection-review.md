# Plugin Host keyless inject：120bf8 Native 失败的独立只读核对

审查 ref：`120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b`。范围仅为 `test_plugin_keyless_inject.py` 的 host 参数失败、实际插件 Host 协议、keyless owner 路由和相关历史。此次没有运行测试、连接 PG、修改生产/仓库测试、安装依赖或提交。

**结论：该验收失败仍未闭环，现有证据不足以定位新的 blocking/major 产品缺陷；也不足以将失败降为环境抖动或基线既有问题。Task24 保持 FAILED / CHANGES_REQUIRED。** 本报告不以另一参数通过、插件返回 True 或 HTTP 响应替代持久化/执行证明。

## 实际失败证明到哪一步

已读取 `.build/postgresql/unified-task24-120bf8-partial-native-replay.log:492` 起该文件完整输出：Linux/Python 3.14.9，5项收集，**4 passed / 1 failed**，101.79s；失败为 `test_a_key_less_inject_goes_to_the_session_the_plugin_is_working_for[host]`。20秒观察未获得 `('turn', 'TURN_TEXT')` note。该59文件批次最终 **315 passed / 4 failed / 7 skipped**，868.8s，非全绿。

`tests/gateway/test_plugin_keyless_inject.py:32` 的 probe 在 `ctx.inject_message` 返回**之后**才写 JSONL。`noted`（110行）以 `[r['ok']]` 作为 truthy 匹配，因此已返回并记录的 False 会使 `noted` 返回 False，随后结果断言失败；它不会表现为本次缺 note 超时。此次输出不能区分：目标 hook 尚未进入、被既有 hook 策略跳过、执行/Host RPC 尚未返回、或者记录前异常。不能由此直接推定选错 Profile/session、owner-only 拒绝、SQLite 锁或 Host 死锁。

结果收集顺序说明 CMD_TEXT、TUI_TEXT、HOOK_TEXT 的 note 已被读取，Host 已能完成这些路径；不能笼统归为 Host 未启动/缺 SDK。`landed_once`（125行）的 canonical admission terminal/唯一目标/真实模型精确一次断言尚未执行。其他文本已有 note 不等于已证实这些文本持久化执行成功。

失败 traceback 给出的精确 owned tmp 为 `/var/tmp/hermes-pytest-1000/r-9slfyzxa/pytest-of-ethan/pytest-0/test_a_key_less_inject_goes_to1`。Reviewer 仅只读请求其中四个明确文件（inject note、restart、agent/errors 日志），当时均为 No such file；没有扫描其他测试目录/进程，没有开启或重跑 daemon。因此本轮没有该失败实例的 admission 状态、模型请求序列或实际 Host/owner 堆栈。

## 已核对的正常协议与意图

- `agent/turn_context.py:849` 将原始 user message 传给 `pre_llm_call`。`plugins_dispatch.py:350` 的 bounded hook 线程复制调用 context；Host callable proxy 再通过 `PluginHost.invoke` 发出请求。
- `hermes_cli/plugin_host_wire.py:310` 给在飞请求保存 `copy_context`，帧带 `origin`；每个入站 method 请求在独立 RPC 线程运行（352行），不是在读帧线程或单 worker 池中串行等待。`plugin_host.py:377` 通过该 origin 找回外层调用 context；400行在该 context 内调用实际 ctx 方法。同步 pre_llm hook → child ctx 注入 → parent 的嵌套协议有明确实现，不能仅凭双方同步等待就称为重入死锁。
- `RemotePluginContext.__getattr__`（`plugin_host_child.py:97`）将公开 ctx 方法转发；inject_message 不在 Host unsupported/skipped 列表。`plugins_injection.py:58` 使用 `bound_session_key()` 和 manager 的固定 home；不存在无条件改选默认 Profile 的分支。
- `gateway/plugin_keyless_inject.py:68` 先按 plugin home 找 authority，再按调用 session key 找其已授权 LOCAL live session；有调用 key 时不会回退猜唯一 CLI。`run_plugin_injection.py:39` 同步解析并线程安全调度，返回 True 表示接受调度；后续 `plugin_keyless_inject.py:102` 的 admit 才在 owning authority/scope 内取得 session 并真正提交 producer admission。False/异常的普通调度拒绝会返回给 probe；调度成功仍须依靠后面的 canonical ledger/模型断言证明执行。
- 此 fixture 的配置（测试90行）只有 `gateway.multiplex_profiles`，没有 `managed_workers=True`，session.create 也没有 bypass。`session_managed_worker.managed_policy:40` 对普通 session 仅显式 opt-in 才 spawn。因此这里是 owner 进程运行 turn、另一个进程运行插件 Host，不能把另一 managed-worker history/compress 测试的 journal fsync/RPC 堆栈当成这个失败实例的证据。

历史 `f7322744fc` 明确要求：有调用会话就选该会话；无调用 context 才可选该 Profile 唯一 attached classic CLI；不明确就拒绝；真实入队遵循 FIFO。提交说明也明确 Host forwarded ctx 保留 caller context。这是正常可达且应维持的产品合同。测试、keyless resolver、注入入口、Host wire/child/parent、hook dispatch 在 `a875342384..120bf8` 没有直接 diff；**没有执行同条件基线 A/B，不能据此称失败已存在于 a875**，外围执行/调度的变化仍可能相关。

## 已证实的夹具观测接缝与最小后续

这里记录观测接缝，不作为已定位的产品根因或降级关闭理由。

1. 测试155–156行先向 cli1 注入 HOOK_TEXT，再向同一 session 提交 TURN_INJECT，等待 TURN_TEXT note 前没有确认前序 HOOK_TEXT terminal。原20秒等待可能同时涵盖前序 FIFO turn 的等待/执行和目标 hook；JSONL 已有 HOOK_TEXT note 只表示其调度调用返回。应保留原顺序/期限，观察这三条精确 text 的 admission 状态及目标 turn 进度，不能凭超时猜是哪条停住。
2. 生产 pre_llm_call 是 bounded hook，默认单 callback 预算30秒（`plugins_dispatch.py:183`），可因相同调用仍运行、抑制窗口、异常等 fail-open。fixture 只观察20秒后的 note，未记录 hook-enter、ctx-call-enter/return 或父子 RPC origin。其 timeout 不能直接证明生产30秒边界失效，也不能自动说明放大 fixture 期限就能解决问题。

若 Root 进行后续安静串行对照，最小观测应在原超时后、原 teardown 前保存：本测试原 note/restart/agent/error 日志；HOOK_TEXT、TURN_INJECT TURN_TEXT、TURN_TEXT 的只读 canonical admission 状态和已观察模型请求；插件 hook 的 enter/ctx-before/ctx-after、对应父子 request id/origin；以及已核对持有 PID/birth 的 owner/Host 线程栈。由此分别判断是否未轮到目标 admission、未触发匹配 hook、嵌套 RPC 等待还是返回后记录异常。保留原20/30秒边界、真实 daemon/Host/loopback/SQLite FIFO、全部后续唯一执行与目标隔离断言；不通过跳过 host、改 in_process、禁用 hook 或只等返回 True 来取绿。

当前只读证据未给出需要修改哪一行生产代码的充分根因，因此不提出猜测性实现修正，也没有代跑。该失败继续列入最终 Native 未闭合项；完整 PG recovery-mode 失败、最新发行/全域结算与非 WSL 七项适用主机缺口亦不由本局部审查解除。

## 原单项增加观测后的串行一次通过（不关闭原失败根因）

Reviewer 已只读核对 `.build/postgresql/unified-task24-host-injection-observed-corrected.log`、`.build/postgresql/host-injection-observed-test_a_key_less_inject_goes_to_the_session_the_plugin_is_working_for[host].json` 及诊断准备脚本 `task24_prepare_host_injection_diagnostics.py`。本轮没有运行测试/daemon、访问数据库或修改实现/测试。该日志为 canonical runner **1文件、1 passed / 0 failed，15.4s，-j1**；只选择原 host 单项，不称原五项文件或59文件批次全绿。

所用 native state 的 revision/source 仍冻结于生产 `120bf8c9d6c9f3ac9e2d35e995ed976a4e175c3b`。当前本地 HEAD `20a4789b35d4b38eec098c5a1203699200833474` 相对120bf8仅含两项 CLI 测试及文档变化，已核对文件列表；不能将本次结果误记为新增生产修复的红→绿。

准备脚本将原测试模块 `_probe_plugin` 包装为先生成原 probe，再加 hook-enter/ctx-before/ctx-after 单调时钟记录及10秒重复 faulthandler；对原 `keyless_gateway` 仅在退出前采日志、只读 SQLite ledger 和 loopback 请求。没有替换原测试函数、改变20秒 note/30秒 terminal 期限、插入前序 terminal 屏障或移除目标/精确一次断言。生产 Host/owner 路由、真实 daemon、真实 Host 进程、loopback 模型和持久 admission 保留。

这次已证实的范围为：

| 证据 | 本次实际观察 |
| --- | --- |
| phase | 插件进程 PID 3755054 依次记录各输入的 pre_llm hook-enter；`TURN_INJECT TURN_TEXT` 进入后真正调用注入，TURN_TEXT before→after约 **0.56ms**，随后目标 TURN_TEXT 自身也进入 pre_llm hook |
| notes | command两项、HOOK_TEXT、KEYED_TEXT、TURN_TEXT五项均为 True；这是调度回执，需与下面两行共同阅读 |
| canonical SQLite ledger | CMD_TEXT、TUI_TEXT、HOOK_TEXT、TURN_INJECT TURN_TEXT、TURN_TEXT **五条均 terminal**；前两项各在独立 cli2/TUI session，后三项同在 cli1；原 `landed_once` 与最终目标断言实际执行并通过 |
| loopback model | 正好五个请求的 last_user 分别为上述五项，各一次；不是只有返回 HTTP 或只读到 admission 已排队 |
| keyed 隔离 | KEYED_TEXT 没有成为上述 ledger/model 任一项，保留 `plugin=probe-inj session=agent:main:telegram:dm:nobody` 的 keyed 路径未路由日志，原无本地误投断言通过 |
| FIFO 进度 | gateway/agent 日志显示 cli1 先执行 HOOK_TEXT，再执行 TURN_INJECT TURN_TEXT，最后执行 TURN_TEXT；此运行没有复现前序阻塞 |

JSON 内的10秒 faulthandler 文本虽然以 `Timeout (0:00:10)!` 开头，但这是诊断主动定时 dump，**不是测试20秒等待失败**。本次样本中 Host reader 在 readline、async loop 在 select、主线程在停止 Event 等待，没有正在等待嵌套 ctx 回包的请求处理线程；不能将这个绿色运行的空闲样本用作原失败实例的堆栈。

证据限制仍保留：这是加了额外日志 IO/watchdog 的串行单次通过，调度和原三 worker 并发批次不同；没有在原失败实例中记录的 hook 阶段、父子 request id/origin 或 owner/Host 堆栈，也没有证明该失败可稳定归因于负载。上述结果证明 **120bf8 的这条实际业务链在本次完整原断言下能够成功，原故障本次未复现**；不证明已修复根因、不称环境抖动、也不称 a875 既有问题。Host 原并发20秒缺 note 继续未解释；未结算的全PG串行批次不以中途通过数并入本报告结论。总体仍为 **FAILED / CHANGES_REQUIRED**。

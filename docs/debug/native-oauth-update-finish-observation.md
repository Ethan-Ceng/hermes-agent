# 冻结 Native 的 MiniMax 与 update_finish 失败独立诊断

## 范围与结论

2026-11-08，独立 Reviewer，只读核对冻结 `58d0003f83d1c99505e1173508ea7e2934d89411` 的实际 Native 宽回归失败，与基线 `a8753423841362c6c8d76e2dca094c95d690ba27` 比较。主日志 `.build/postgresql/unified-task24-frozen-native-areas.log:4459`、`:5897`。观测仅写忽略的 `.build`；未改生产或仓库测试，未安装依赖，未提交。

- MiniMax：定位到原测试 HTTP server 未消费 POST body 后关闭 socket 的竞态；已在原用例观测到未读 body、客户端仍打开而响应未到截断界限即 RST，并用实际原生 TCP 单变量对照重现该机制。没有发现本分支直接引入的 OAuth 业务逻辑变化。原红测仍保留，窄绿不能关闭它。
- update_finish：原两项失败都在 Node 缺失的测试前提断言。已有 PM Node/npm 加入后，完整原文件为 **14 passed / 0 failed / 2 skipped**；缺 checkout 的 esbuild/TypeScript/Vite 导致两项按既有规则 skip。因此构建业务合同仍未运行，不能记成 16 passed。

## 环境与历史意图

实际宿主为 WSL Linux，Python 3.14.9，同一既有 PM 解释器，精确路径见忽略目录 `task24-linux-state.json`。两份 snapshot 路径与隔离 home 读取 `task24-native-checkout-state.json` 和 `task24-baseline-linux-state.json`。所有产品测试均由 `.build/postgresql/run_matrix_linux.py` 调用 `scripts/run_tests.sh`，`HERMES_TEST_FILE_RETRIES=0`，不伪造 OS、存储后端或 Profile 作用域。

Git `a875342384..58d0003f83d1` 中以下直接链路没有 diff；实际 Linux 两树也逐文件 SHA256 相同：`hermes_cli/auth.py`、`auth_minimax.py`、`auth_constants.py`、`update_finish.py`、两个原测试文件、两层 conftest、canonical runner 两文件。清单 `.build/postgresql/review-native-oauth-update-source-sha256.txt`。

历史 `219bb35c359ba546cd1a05b3f9bd70496be49843` 明确要求 MiniMax 非 200 streamed body 在 `httpx.Client` 上下文关闭前读取，以真实 socket 防止 MockTransport 缓冲掩盖缺陷。现 `hermes_cli/auth_minimax.py:248` 的客户端上下文仍覆盖 `:258` 的 `_minimax_response_error_text`，该历史修复没有回退。历史 `53e6f001c7a409c9f61094f9a744dbb7815cd7b5` 引入更新 completion 真实构建验收；`_npm_graph` 的 Node 硬前提和缺编译器时 Python lane skip 规则已存在于基线。

## MiniMax 实际调用链与证据

原用例 `tests/hermes_cli/test_minimax_oauth.py:447` 创建真实 loopback `TCPServer`，通过真实 httpx 发送 refresh POST。其 `Handler.do_POST`（`:466`）直接发送 400、Content-Length=65550 和 body；它没有读取请求的 Content-Length。HTTP/1.0 handler 返回后，真实 stdlib `TCPServer.shutdown_request` 执行 `shutdown(SHUT_WR)` 后 close。

独立 `.build/postgresql/review_minimax_socket_observation.py` 原样调用该原用例，仅包装实际 `TCPServer.shutdown_request`、`_minimax_post_form` 与 `Response.iter_bytes`；服务端 peek 使用非阻塞 `MSG_PEEK`，不消费请求，不改响应、返回值、状态、15 秒 HTTP 超时或 16 KB 断言。观测无论红绿都写 JSON，不依赖 runner 显示成功 stdout。

冻结 58d 观测红：

- 服务端关闭前 socket 上尚有 **95 字节未读请求 body**，与客户端真实 POST content 长度相同。
- 客户端收到 400/65550 Content-Length，`client_closed=false`。
- 实际响应迭代先后得到 **7240 + 5792 = 13032 字节**，然后 `httpx.ReadError: [Errno 104] Connection reset by peer`；出错时仍 `client_closed=false`。尚未达到 16384 字节截断界限，故 bounded reader 还必须继续读取。
- 日志 `.build/postgresql/unified-review-native-minimax-58d-observation.log`，**0 passed / 1 failed，exit 1**；原始 JSON `.build/postgresql/review-minimax-58d-socket.json`。

同环境基线观测单次绿：首个响应 chunk=47784，足够直接触发 bounded break；关闭前仍有 95 字节请求 body 未读。日志 `.build/postgresql/unified-review-native-minimax-base-observation.log`，**1 passed / 0 failed**；JSON `.build/postgresql/review-minimax-base-socket.json`。JSON 末尾的 GeneratorExit 是原迭代器在提前 break 后被关闭的观察，不是 HTTP ReadError。

随后各执行一次**未加观测的完整原测试文件**，保留原文件内执行顺序：基线与冻结版本均 **16 passed / 0 failed，exit 0，2.4 秒**，日志分别为 `unified-review-native-minimax-base-original.log`、`unified-review-native-minimax-58d-original.log`。这些结果说明失败对实际传输/关闭时序敏感，不抵销已经复现的红测，也不把相同源码或一次基线绿当作独立排除全部间接影响的证据。

### 单变量原生 TCP 反事实

为验证关闭机制，独立 `.build/postgresql/review_minimax_reset_probe.py` 使用同宿主真实 TCP、95 字节 POST、同样 65550 字节 400 response。用 Event 确保 body 在 header 解析后送达，`select` 等待 socket 可读；唯一业务变量为服务端是否读取请求 body，然后执行相同发送与真实 server close。该诊断没有调用或替换产品函数，不充当产品回归通过证据。

| 服务端行为 | 实际结果 |
| --- | --- |
| 不消费 body | MSG_PEEK=95；客户端收到 13156 字节（含 headers）后 ConnectionResetError |
| 消费 body | rfile.read=95；客户端收到完整 65674 字节（含 headers），正常 EOF |

canonical runner **2 passed / 0 failed，exit 0，1.4 秒**，日志 `.build/postgresql/unified-review-native-minimax-reset-counterfactual-v2.log`，JSON `review-minimax-reset-False.json`、`review-minimax-reset-True.json`。首版私有诊断在 sendall 后立即非阻塞 peek，尚未等待网络可读，因其自身 BlockingIOError 而 1 failed / 1 passed；原日志 `unified-review-native-minimax-reset-counterfactual.log` 保留。v2 仅为该诊断补 `select` readiness，不改任何原测试或产品 deadline。

原用例的未读请求体、实际 red 的响应长度及上述单变量对照共同支持根因：测试 server 在未消费请求 body 时关闭连接，造成 RST；响应分片若先超过 16 KB 会被 bounded break 掩盖。该缺陷位于未修改的测试 Handler，不是历史“client 已关闭”缺陷复发。同文件正常 portal Handler（`:550`）已先按 Content-Length 读取 body。最小建议供 Root 决策：仅让此测试 Handler 在发送响应前消费 Content-Length，保持真实 socket、15 秒 HTTP 超时、invalid_grant、relogin_required 与 16 KB/truncated 断言；无需通过生产层吞 ReadError 来令此测试通过。本 Reviewer 未实施修复，未证明修复后的原用例可靠。

## update_finish 原失败与工具前提

原 traceback 两项分别来自 `test_selected_child_builds_and_finalizes_under_parent_lock`（`tests/hermes_cli/test_update_finish.py:435`）与 `test_real_compiler_failure_is_owed_build_and_completion_continues`（`:480`）。两者都在 `_npm_graph`（`:377`）的 `shutil.which("node")` 返回 None、`:382` 的 assert 失败；尚未调用更新 completion child、真实编译或数据库维护。

按父任务要求，只追加原文件，不重复其余 29 个工具文件。使用已有 `--tools-state task24-linux-tools-state.json`（Node v26.12.1、npm 12.0.2）运行完整原文件，结果 **14 passed / 0 failed / 2 skipped，exit 0，41.0 秒**；日志 `.build/postgresql/unified-review-native-update-finish-tools.log`。原 `run()` 的 child timeout=90 保持原样。

这两项越过 Node 前提后，会进入同 helper 的 `require.resolve('<compiler>/package.json')`；该文件唯一 skip 点是 `:389` 的“Python lane 无 npm ci / checkout 缺编译器，真实构建走 install E2E”规则。独立在相同工具 PATH、相同 source cwd 检查，esbuild、typescript、vite 三者都 `MODULE_NOT_FOUND`，首个 esbuild 即触发原 skip。原始输出分别为 `.build/postgresql/unified-review-update-finish-{esbuild,typescript,vite}-precondition.log`。没有安装或链接缺失包。

定位结论：原两项失败是宿主 Node 前提缺失，非当前生产 completion 的返回值或 deadline 失败；helper、原测试、直接 completion 实现与基线相同。已有工具补验符合当前 Python lane 的 skip 规则，但未验证父锁保持、真实 npm/compiler、成功盖章和编译失败 follow-up 等两项业务合同。若最终验收要求这些合同，仍须对应具备真实编译器的源安装 E2E 或同条件实测证据；不将 skip 改成通过。

## 门禁与未完成项

此诊断没有发现统一数据库 diff 引入的这三项业务逻辑回归，但没有把 Native 宽回归原失败抹去。MiniMax 原 fixture 缺陷及 Root 的处置/修复后回归尚待确认；update_finish 两项真实构建合同缺少可执行编译器前提及相应运行证据。完整大批次、其他未决失败、最新生产代码/发行载荷及非 WSL 七项平台证据继续由总门禁核对。总体仍 **`CHANGES_REQUIRED`**，不宣称全局 APPROVED 或 READY_TO_MERGE。

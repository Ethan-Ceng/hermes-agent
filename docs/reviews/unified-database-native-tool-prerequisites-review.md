# Native 宽回归工具前提独立审计

审查对象：冻结 `58d0003f83d1c99505e1173508ea7e2934d89411` 的 Native 宽回归。依据 `.build/postgresql/unified-task24-frozen-native-areas.log` 中指定错误及后续至 `test_safe_mode.py` 的错误块、实际 fixture、PM 和 resolver 源码。只读诊断；未安装工具、修改运行环境、执行复验或修改生产/仓库测试。

## 指定错误的实际归因

这些是 setup error / assertion failure，不能称为 collection error。指定文件已经完成 collection；当前读取日志未显示这些文件缺少 Python SDK 的 `ModuleNotFoundError` 或 `ImportError`。

| 文件（`tests/hermes_cli/` 下） | 本次结果 | 直接证据与缺失前提 |
| --- | --- | --- |
| `test_desktop_build_reuse.py` | 2 setup errors | 日志 3768 起，`packaged_checkout` 第 42 行断言 `shutil.which('node')`，实际 `None`。缺 Linux Node PATH。尚未运行复用断言。 |
| `test_desktop_source_build.py` | 3 setup errors | 日志 3818 起，共享 `test_source_build.py:98` 的 `source_checkout` 要求真实 node/npm；node 为 `None`。必须提供一套 Linux node/npm。 |
| `test_desktop_update_verify.py` | 1 passed / 9 setup errors | 日志 3859 起，`bundle:33` → `test_source_build.py:40` 把 `shutil.which('node')` 的 `None` 作为命令首项；`live_system_guard` → `git_safety.py:31` 的 `fsdecode(None)` 是次生错误。缺 Node，不是 guard 已证明损坏。 |
| `test_enable_no_capabilities.py` | 6 setup errors | 日志 3941 起，`plugin_worker_support.isolated_python` → `tests/pm/_fixtures.py:147`，真实 uv PATH 断言失败。尚未运行 consent 行为。 |
| `test_login_backend_provenance.py` | 3 passed / 7 setup errors | 日志 4346 起，`world` → `client` → 同一 `isolated_python:147`，缺 uv PATH。真实 git 已存在。 |
| `test_memory_dependency_admission.py` | 2 failed | 日志 4417 起，用例第 23 行直接断言真实 uv 存在，实际 `None`；尚未进入 dependency admission 合同。 |

这 6 个文件需要工具补齐后完整复验。现有 4 个 passed 不能替代未执行的 29 个用例。

## Linux 实地只读核对

诊断脚本：`.build/postgresql/review_native_tools_audit.py`；原始输出：`.build/postgresql/review-native-tools-audit.log`，exit 0。在原 Native state 指定的真实 Linux source / test Python 下，调用 `hermes_platform.resolver.locate_command`，并由 `pm.build_operations.verified_tools` 对既有 store 的锁、事实、完整树摘要及声明环境作只读 admission；未执行二进制或下载。

| 工具 | 冻结锁版本 | 实际状态 |
| --- | --- | --- |
| uv | `0.13.5` | 原 runtime 的 `uv-0.13.5-linux-x64/uv` 存在且可执行，`verified_tools(['uv'])` 成功；ambient PATH 找不到。 |
| Node | `26.12.1` | 原 runtime 的 `node-26.12.1-linux-x64/bin/node` 不存在；锁身份校验不通过。 |
| npm | `12.0.2` | 对应 Linux entry 未准备；ambient resolver 却找到 `/mnt/c/Program Files/nodejs/npm`，不能将此 Windows launcher 计为 Linux 工具链。 |
| git / bash | 系统工具 | 分别解析到 `/usr/bin/git`、`/usr/bin/bash`。 |

`uv` 在 `pm/packages.py:200` 被声明为 internal / 不上 PATH。`pm.env_for('uv')` 和 `verified_tools(['uv']).environment(...)` 都不会把它暴露给测试直接使用的 `shutil.which('uv')`；只设置 `HERMES_RUNTIME_DIR` 同样不能解决这些 fixture 的前提。

`hermes_platform/resolver/core.py:116` 的 `locate_command` 只查 PATH 和调用方显式 known_dirs，不安装也不自动搜索 PM store。无需修改 resolver。`scripts/run_tests.sh` 的最终 `env -i` 保留传入 PATH，同时刻意清理 `HERMES_RUNTIME_DIR`；正确注入点是本地 ignored orchestration 启动标准 runner 的环境。

## 由 Root 执行的最小 PM 方案

创建独立 work/cache/store，沿用冻结源码和现有 test Python；不向原 runtime 或 `task24-full-test-env` 安装任何内容。已有 `scripts.bundles.desktop_toolchain.bootstrap_environment` 会隔离 HOME、PM store、下载及 npm 缓存，适合本次临时工具准备。

下面是 Linux orchestration 的可执行核心；Reviewer 没有运行其中的准备或测试步骤。`state` 从现有 `.build/postgresql/task24-native-checkout-state.json` 读取，脚本本身放 ignored 目录：

```python
import json, os, subprocess, sys, uuid
from pathlib import Path

state = json.loads(Path('/mnt/d/AI/hermes-agent/.build/postgresql/task24-native-checkout-state.json').read_text())
source = Path(state['source'])
sys.path.insert(0, str(source))
from scripts.bundles.desktop_toolchain import bootstrap_environment
from pm.build_operations import verified_tools
from pm.store import current_target
from hermes_platform.resolver import locate_command, LookupContext

target = current_target()
uv = verified_tools(['uv'], source_store=Path(state['runtime']), target=target).entries['uv'].binary
assert uv is not None
work = Path(state['root']) / ('task24-native-tools-' + uuid.uuid4().hex[:12])
cache = work / 'cache'
prepare_env = bootstrap_environment(source, work, cache, os.environ)
Path(prepare_env['HOME']).mkdir(parents=True)
store = Path(prepare_env['HERMES_RUNTIME_DIR'])
prepare_code = (
    'import os, sys; from pathlib import Path; import pm; '
    "pm.prepare_tools(['npm'], out=Path(os.environ['HERMES_RUNTIME_DIR']), "
    'target=pm.current_target(), cache=Path(sys.argv[1]))'
)
subprocess.run([state['python'], '-B', '-c', prepare_code, str(cache / 'python/runtime')],
               cwd=source, env=prepare_env, check=True)

selected = verified_tools(['npm'], source_store=store, target=target)
run_env = selected.environment(dict(os.environ))
run_env['PATH'] = str(uv.parent) + os.pathsep + run_env['PATH']
for name in ('uv', 'node', 'npm'):
    command = locate_command(name, LookupContext(path=run_env['PATH'])).command
    expected = uv if name == 'uv' else selected.entries[name].binary
    assert command and Path(command[0]) == expected, (name, command, expected)
run_env.update(HERMES_PYTHON=state['python'], HERMES_HOME=state['home'], HERMES_TEST_FILE_RETRIES='0')
files = [
    'tests/hermes_cli/test_desktop_build_reuse.py',
    'tests/hermes_cli/test_desktop_source_build.py',
    'tests/hermes_cli/test_desktop_update_verify.py',
    'tests/hermes_cli/test_enable_no_capabilities.py',
    'tests/hermes_cli/test_login_backend_provenance.py',
    'tests/hermes_cli/test_memory_dependency_admission.py',
]
raise SystemExit(subprocess.run(['bash', 'scripts/run_tests.sh', *files, '-j', '2'],
                                cwd=source, env=run_env, check=False).returncode)
```

`pm.prepare_tools(['npm'])` 按冻结 `pm/lock.json` 准备 npm 的 Node 依赖闭包，PM 自行 bootstrap 所需的内部 Python/uv；没有裸 pip/uv/npm 安装。必须令 child 的 `HERMES_RUNTIME_DIR` 与 `out` 相同：`pm/packages.py:711` 的 npm unpack 从 PM 当前 store 查找已准备的 Node，单独传新 `out` 而保留旧 runtime 会遗漏这个依赖。该示例只改变新 child 的环境，不设置账户全局 PATH，不更改标准 runner 或任何测试 deadline。实际准备、版本执行核验和 retries 0 复验结果仍须 Root 记账。

## 同批后续文件与非工具错误

读取截点内，以下文件错误明确落在同一 `tests/pm/_fixtures.py:147` uv 前提，应加入同环境补充复验：

- `test_plugin_install_inspected_sha.py`（4e）、`test_plugin_install_inspected_sha_catalog.py`（5e）、`test_plugin_install_manifest_version.py`（1 passed / 3e）。
- `test_plugin_worker_lifecycle.py`（12e）、`test_plugins_admission_setter.py`（6e）、`test_plugins_catalog_requires_hermes.py`（5e）。
- `test_plugins_cmd.py`（42 passed / 8e）、`test_plugins_cmd_catalog.py`（2 passed / 24e）、`test_plugins_cmd_enable_disable_nested.py`（7e）、`test_plugins_picker_effective_state.py`（2e）。

另有 `test_plugin_dependency_consent.py`（3 passed / 6e）、`test_plugin_update_scan_override.py`（1 passed / 6e）、`test_plugin_update_transaction.py`（16e）、`test_plugins_auto_update_boundary.py`（2 passed / 4e）、`test_plugins_update_sync.py`（6e），真实堆栈都指向 `tests/pm/test_plugin_survival_contract.py:150` 的 `[shutil.which('uv'), 'lock']`，继而触发 guard 的 `fsdecode(None)`；补 PATH 后完整复验。`test_plugin_install_ref.py` 的 34e 摘录只有用例列表，源码显示其 autouse fixture 依赖同一 `isolated_python`；可列入复验，但当前截断输出不足以逐项证明这 34 项全部同因。

`test_source_build.py` 共享 fixture 是上述 Node 故障源；即使它的独立执行结果在本次读取截点尚未出现，也应与 Node 组一并复验，验证真实 npm 调用链。

以下错误必须独立保留，不能并入缺工具或 SDK：

- 日志 4461 起，`test_minimax_oauth.py::test_refresh_error_body_bounded_and_readable_with_real_client`（15 passed / 1 failed）：已建立 loopback 真 socket，`hermes_cli/auth_minimax.py:39` → httpx `iter_bytes` 遭遇 `ReadError: [Errno 104] Connection reset by peer`。httpx 已可导入并实际运行。当前未独立复现或确定生产/fixture 根因。
- 日志 5461 起，`test_safe_mode.py::test_canonical_safe_launch_is_frozen_policy_executed_in_isolated_worker`：真实 CLI 返回 `request_failed` / exit 1；错误发生在源码第 240 行、用例主动写入损坏 config 后的 safe launch。伴随 config 格式警告是该阶段的上下文，不能仅凭截断输出将其定为根因，也没有缺工具证据。

结论：指定错误具有可执行的工具准备/PATH 修复方向，但修复尚未执行、业务合同尚未重跑，不能转绿。后续仍在运行的宽回归不包含在本报告完成声明内。总体保持 **FAILED / CHANGES_REQUIRED**。

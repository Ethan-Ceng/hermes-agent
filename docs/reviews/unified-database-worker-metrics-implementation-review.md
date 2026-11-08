# Managed metrics owner bridge 独立实现复审

审查基点为 RetainDB 恢复提交 `ed0cdbe604cded73026f28f4b96937c6e204a5cf` 后的 Task24 工作区。重点读完 `operations/worker_metrics{,_engagement}.py`、`gateway/session_worker_metrics.py`，并追踪 `WorkerMetricsStore`、bound store、receipt handlers、gateway persist、engagement 原消费者、owner consent/sender、managed worker quiesce 及新增测试。沿用 `supercoder:code-review`：本 Reviewer 不改生产/仓库测试、不安装、不提交，只写 ignored 观察 probe 和独立报告；独立测试均经既有 PM Linux 环境与 `scripts/run_tests.sh`，retries=0、拥有者随机 Schema 和严格 SQLite guard。

## 问题列表

**当前重点范围未发现有实证的新 blocking/major。** 不将静态接缝猜测记成红测，也不因普通/config-only 首批通过就批准整个 Task24。

早期 `maintain` 候选在 collection gate 前无条件打包，本 Reviewer 读到该顺序后指出待证风险；Root 同时收紧为当前代码：在 owner scope 内解析真实 send config，先独立 reconcile consent、drain intent，`enabled=False` 随即返回，只有 collection 开启才打包、只有 send 开启才请求原 owner sender。旧候选未被本 Reviewer 跑出产品红，不登记为已复现缺陷。下面单独列当前版本实际正例。

## 方案与隐私边界核对

- **冻结 collection 与实际 owner consent 分开。** Relay 的 collection 仍由原冻结 worker policy 决定；代理 `reconcile_send_consent` 不传 worker 的 send_enabled/now。`prepare_policy` 在借 receipt 连接前，以 `_owning_profile(scope.profile_home)` 读取 owner 真实 `_resolved_send_config().send`；未知 owner/clock/state/consent 字段由 exact fields 拒绝。config-only 默认值不能关闭 owner 的既有窗口。发送端仍重复检查真实配置、当前 consent 与 endpoint，不以旧 receipt 当永久发送许可。
- **同一 Connection 与原 metrics fence。** `RuntimeWorkers.mutate_worker` 在事务外准备可信 policy；Core handler 的 `ReceiptDomainResource` 只借 receipt 当前连接，`repo.lock_store` 保留原 metric_store_locks。bound store 不重新 acquire pool；领域 effect 与原 worker seq receipt 同一次提交。原 worker 4 MiB journal 外，metrics payload 另限 16 KiB；时钟、首会话年龄、latch/state key 及数据集身份均不由 RPC 指定。
- **Profile 与 root 由 owner 推导。** engagement payload 只有闭合 surface/route/resource。owner 从 scope 推 profile_home/root/hash/owner 标志，生成时钟与每日 `worker.root_profile.v1:<day>` intent；不接受 worker 自选 root、profile hash、时间或任意 state_key。采纳时读取 root collection，drain 时重读，撤回就退休。root 写入仅 profile 集合，不转抄 source surface、model 次数或会话内容；原 profile hash 仍只保存在本机 state，发送合同只包含桶。
- **跨 Profile 不假称原子。** source effect/intent/receipt 同事务；source 连接归还后 root 按自身 backend 独立短事务写入；root 成功之后再借 source 短事务，以 key+原 value CAS 删除。root 提交、source 删除之前失联可以重复应用同日集合；root.day 晚于观察日时不回填新日。它不提供跨 Profile 单事务保证。
- **flush 与 worker 退出。** `domain.metrics.flush` 是空 Core effect，gateway 在真实 mutate 返回、连接释放后运行维护，缓存 receipt 重放亦进入维护。维护异常不能成为成功 RPC ACK，原 worker journal 保留原 seq。当前 quiesce 在 execution.finish 前停用本 worker runtime、等待原 flush thread、flush Relay subscriber，再发显式 flush 并检查 journal；未把吞异常的 atexit shutdown 当持久化屏障。没有对 owner 全 Profile runtime 执行 worker shutdown。

## Reviewer 独立真实 PG 探针

文件 `.build/postgresql/test_review_worker_metrics_boundaries.py`，SHA256 `2664F43EE9BE5A2A5B5DB7A3E7E2AF3329B23D94E89B633FAD5598D4C15854F5`。日志 `.build/postgresql/review-worker-metrics-boundaries.log`：**3 passed / 0 failed、exit 0**，15.3s。脱敏结果 `.build/postgresql/review-worker-metrics-boundaries-observed.json`。只在拥有测试 Profile 下准备真实 root/profiles/child 配置与私有 `.env` 副本，不输出秘密，不改正式 Profile。

| 合同 | 实际观察 |
| --- | --- |
| 同 target、同一 pool=1，child → root | 三次 root apply 前 checkedout 均为 0，root 提交后回 source 前亦为 0；没有依赖额外 overflow 绕过嵌套借连接 |
| root 实际提交后 source delete 故障 | 注入源删除前 OSError，PG root 已有 profile、source intent 仍在；恢复后同日集合仍只有一个 profile，source 模型累计仍为 1，root models/surfaces 均为空 |
| source CAS 不删更新后的 intent | 故意在 root apply 后写一个更新的 owner observation，原 key+value delete 保留它；下一轮真实 apply 后才清空 |
| root collection withdraw | intent 在 opt-in 时实际采纳，root 关闭 collection 后 drain 不改 root 并退休源 intent；关闭期间新的 source engagement 不创建 root intent |
| late root day | 在本测试 Schema 准备晚两日的 root state；旧 intent drain 后 root 完全不变、源 intent 退休 |

这是 owner 短事务/intent 故障窄测，使用实际 runtime receipt 与 PG，不伪造 worker 标志；它没有启动实际 managed 进程或发送 HTTP，不能替代下节真实消费者与 SDK/RPC 故障验收。

这份独立三项日志属于初版 drain 的当时运行证据。Root 后续增加 drain 结束后的残留检查：若有新 observation 或超过 128 条的未排空工作，抛 `StorageNotReadyError`，不确认本次 flush。原 CAS 保留新值的事实仍成立，但当前代码应在保留后报告“尚未完成”，不能继续把本 probe 旧版本的返回行为冒充最新运行结果；Reviewer 未为此修改或重跑 ignored probe。

## 已核对的其他实际证据

以下为逐项读取的 Root/其他独立 Reviewer 产物，明确不冒称本 Reviewer 执行。

| 日志 | 真实范围与结算 |
| --- | --- |
| `unified-task24-worker-metrics-port-first.log` | Windows 三文件 **5 passed / 0 failed**，86.1s：Core effect/receipt、PG engagement、真实 ordinary/config-only 两项；仅该初版范围 |
| `unified-task24-worker-metrics-quiesce-first.log` | Windows metrics/verification/Retain 三个真实 managed 文件 **6 passed / 0 failed**，101.9s，覆盖加入 metrics quiesce 后的消费者交界 |
| `unified-task24-worker-metrics-root-http-first.log` | Windows root intent 与实际 managed metrics 两文件 **5 passed / 0 failed**，77.7s：root 三项、ordinary/config-only 两项；新 config-only 场景要求 receiver 真正收到已同意完整日的历史包，普通 send=false 则 receiver 空 |
| `review-foundation-metrics-maintenance-withdrawal.log` | Foundation 独立 owner 维护探针 **1 passed / 0 failed**，runner 6.0s：pool1 真 PG、严格 SQLite；ambient peer 仍 opt-in，owner 当前 enabled/send=False。owner 窗口关闭、counter=1/packaged=0、package=0、outbox 空，peer 窗口空、返回后 foreground scope 恢复 |
| `unified-task24-worker-metrics-mixed-barrier.log` | Windows 两文件 **3 passed / 0 failed**，11.7s：PG satellite + 真实 SQLite root 一项，真实 SDK barrier 正常/commit 确认丢失两项 |
| `unified-task24-worker-metrics-barrier-scoped.log` | Windows SDK barrier **2 passed / 0 failed**，11.3s：caller 线程未绑定 owner Profile，quiesce 从已采用身份绑定并恢复调用者上下文 |
| `review-foundation-metrics-gateway-flush-replay.log` | Foundation 独立真实 handler 探针 **1 passed / 0 failed**，7.3s：真实 live child PID/birth/claim/register/adopt、pool1 PG、维护后故障、原 seq 回执重放；进程内调用，不是 WebSocket 故障 |
| `unified-task24-worker-metrics-maintenance-first.log` | Windows 三文件 **6 passed / 0 failed**，15.4s：永久 maintenance 一项、Core 当时两项、root 当时三项；不把后来新增第四项算进这批 |
| `unified-task24-worker-metrics-linux-domains.log` | 首轮 Linux误将 scenarios/metrics.py 作为 pytest 文件收集：**33 passed / 0 failed / 1 collection error**，14 文件、190.9s。该错误执行了缺业务 fixture 的脚本入口，不能记整体绿色；其中 root 文件实际 **4 passed** 的子结果仍保留 |
| `unified-task24-worker-metrics-linux-accepted.log` | 正确 `test_*.py` 清单的 Linux **13 文件、34 passed / 0 failed**，182.7s；含最新 Core 三项、root 四项、maintenance、barrier、真实 managed 两项、mixed root 及原 metrics store/consumer/consent/HTTP/fault/process 合同 |
| `unified-task24-worker-metrics-checks-final.log` | **14 checks ok**；相对 ed0cdbe604cd 的 23 个 Python 文件 health **0 blocking / 0 advisory**，不代称最终全分支所有文件检查 |

`test_managed_metrics.py` 已读完其实际链：普通 `gateway.run` → 采用 managed worker → 真实 loopback 模型 → worker Relay/公共 metrics → PG；owner 退出重开后模型 route 为普通 1/config-only 0，consent 窗口按真实 owner send 保留/关闭，旧 metrics.sqlite3 字节不变，子进程 SQLite audit=0、peer 无会话/指标。新 config-only 发送项在测试 fixture 准备真实完整历史 consent 日和旧 counter，receiver 解码实际包后核对 period；没有让 disabled worker 虚造新模型指标，也没有跳过 SDK 或让 worker 自开 PG/SQLite。

## 新增永久证据后的增量复核

已只读核对新增测试及对应生产增量，未发现新的问题；本次未改生产/仓库测试、未新增测试执行。前述旧的“root SQLite/不同 target 无证据”和“维护 handler 链未验证”已由以下具体范围取代：

- `tests/hermes_db/contracts/test_worker_metrics_mixed_root.py` 真实配置 root=SQLite、satellite=PG，在 SQLite audit 中要求每次连接的当前 Profile 必须是 root；source pending 来自真实 PG receipt，drain 后读取真实 SQLite telemetry_state 的唯一 child hash，返回后 source scope 恢复且 source 不存在 metrics.sqlite3。这是在独立 Profile 各自后端选择下的合法跨后端工作，不是在同一个 PG Profile 放宽 SQLite 回落；生产 apply_root 用同步 SQLite `_write` 提交后才删除 PG intent。
- `test_worker_metrics_root.py` 新第四项由 `isolated_namespace` 在已授权测试数据库中创建第二个随机 Schema；该 helper 核对数据库名称与随机归属 marker，清理前再次核对归属。测试显式断言 satellite `resource_key` 与 root target 不同，分别从其真实 store 读回，root 得到 child profile、source profiles 仍空，intent 清除。**这是两个 Schema 对应的不同 PG target；没有第二个数据库服务/实例或不同数据库的实证。**
- `test_worker_metrics_maintenance.py` 永久化 live child 的实际 PID/birth 与 claim/register/adopt 验证，以真实 authority 和 gateway `worker_request` handler 经过 PG receipt 提交、连接归还、真实 maintain 后注入 OSError。磁盘 journal 保留原 seq=1，canonical execution 仍 running、last_sequence=1；finish 拒绝；原 seq 重放只保留原一条 receipt、maintain 实际调用两次，随后才可 finish。Foundation 的独立 probe 已有同范围正例。**这两项都是进程内调用实际 handler，不经过 WebSocket，不代表 socket 断线、包丢失或重连已验证。**
- `test_worker_metrics_barrier.py` 使用已安装 Nemo Relay 的真实 runtime/subscriber/event、真实公共指标代理和 canonical PG commit，不以假的 subscriber flush 替代。一个线程在指标 receipt 前被 Event 暂停，另一个未绑定 owner Profile 的 caller 进入 quiesce：必须真的阻塞 subscriber flush；正常释放后 PG 仅一条指标。确认丢失分支在 PG effect+receipt 实际提交后抛 UnknownCommitError，要求 journal/sticky 阻止 finish，显式恢复后才通过。当前 quiesce 从 `owner_binding` 用 `bind_profile_home` 绑定真实 owner，并恢复 caller 原上下文；没有要求 caller 预先提供恰好正确的 ambient Profile。
- `worker_metrics_engagement.drain` 当前处理一个有界批次后重读 pending，有残留就抛 `StorageNotReadyError`，避免旧的“处理过 128 条便等于 flush 完成”表述。此收紧保留原 journal/receipt 重放，不为消除错误而提高批量上限或删掉新 observation。

## 未验证项与门禁

- root=SQLite 和不同 Schema target、gateway handler 内的 post-maintenance 失败重放已有上节真实证据；不再保留为“完全未测”。不同数据库服务/不同 DSN 的组合，以及通过真实 WebSocket 的该维护失败/确认丢失/重连故障，仍未由这些测试证明。
- 当前 intent 每 Profile/day 一条且每 drain 最多处理 128；这不等于所有停机积压、损坏 intent 或无限期失败的维护/保留情形已穷尽。未据此虚构当前实际故障。
- 普通/config-only 两个原 metrics major 的相应实际消费路径，现有 Windows 与 Linux 局部整改证据；不能继续说当前 Linux 两项没有运行。但最新统一冻结的全域强验收/原生宽回归与故障恢复、最终独立发行载荷复验、适用平台尤其非 WSL 主机证据及最终独立终审尚未闭合，不能仅据 metrics 13 文件或这些补充场景关闭整个门禁。

Task24 全局结论继续 **FAILED / CHANGES_REQUIRED**。本报告未批准合并、未将计划改为完成，也未把上述“未验证”写成生产已失败。

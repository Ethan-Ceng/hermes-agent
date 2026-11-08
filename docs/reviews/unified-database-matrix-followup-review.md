# Matrix 整改独立复审补记

## 范围与版本

2026-11-08，承接 `unified-database-plugins-acceptance-review.md`。原报告针对 `3febe6fc31` 的两项 major 和 `CHANGES_REQUIRED` 结论原样保留；本补记记录随后未提交工作区的整改代码与独立验证，不把旧 HEAD 或旧 source-bundle 视为已包含整改。

复审文件：`hermes_db/matrix_crypto.py`、`matrix_olm_cache.py`、`matrix_failures.py`，`plugins/platforms/matrix/adapter_pg_client.py`、`adapter_sync.py`；同时重新核对真实 mautrix 0.21.1 的发送、群密钥共享、Olm/Megolm 接收、SDK 事务及派生事件分发消费者。

本次最终运行前后核对的 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| hermes_db/matrix_crypto.py | BB8036BB2A028699B7E32D74F91140F347EF1931E44CFE01893FA59601147667 |
| hermes_db/matrix_olm_cache.py | 0940FC568194084167DDAA09EBAA84B4654962E114CFA23D5A9C9C22FCAB1A36 |
| hermes_db/matrix_failures.py | 7F4CD401130BA6DD243A150CA641EA63E87F9F24F88A4C5417D459176F7CACC8 |
| plugins/platforms/matrix/adapter_pg_client.py | C669992A861E7381FEF94228AB2694139C662F76087A3E9525707A8C89A49C85 |
| plugins/platforms/matrix/adapter_sync.py | 96CAE996F30415FA6E77F5EDD3B93F12053CD479BD4EB5748B828CE3A87EE7DB |

## 问题处置

原 major 1 的当前整改可关闭：存储失败通过 ContextVar checkpoint 留存，实际 SDK 内部吞掉异常仍会在 handler 边界抛出。事务结束的 StorageError 也进入同一记录。PG sync batch 持续收集 SDK 后续派生的 handler task，等待其完成后再允许游标提交；仅强制返回 task 而不等待派生 task 的缺口已补齐。非存储协议错误保持原隔离语义。

原 major 2 的当前整改可关闭：真实 PG 读取、scope/target/generation 校验仍在每次获取会话时执行，然后对同一 sender/session 复用同一 Olm Session 对象。读取列表与读取 latest 共用缓存，群密钥和普通 to-device 消费者能看到同一 ratchet。保存锁仅覆盖本地缓存/短 PG 操作，不跨 HTTP。显式事务先取得同一可重入 gate，再取得数据库 root 锁；事务子任务先被 runtime owner 检查拒绝，避免锁倒置。事务写次数快照已移到 gate 内。

复审过程另确认并整改了一条取消窗口：`save` 在等待 gate 时被取消，原内部 try 尚未进入，缓存不会 poison；真实 SDK 已解密并推进缓存状态，重处理同一未持久消息报 `MatchingSessionDecryptionError`。Root 已将整个保存等待纳入失败/取消保护。独立复验确认旧缓存明确拒绝继续使用，新的 store 从 PG 恢复后可解密原消息。

没有发现本次 Matrix 整改范围内其他已证实且未处理的 blocking/major。所有保存失败、取消或包含 Olm 写入的事务回滚均选择明确拒绝继续使用不确定 ratchet；本补记不声称自动重连或远端 exactly-once。

## 独立运行证据

Reviewer 未改生产代码或仓库测试；诊断只写在 `.build/postgresql/`。使用已有真实 Linux PM SDK 环境、实际 PostgreSQL fixture、核对归属的随机 Schema 与全 SQLite 拒绝 guard，全部经 `scripts/run_tests.sh`，无重试。

1. 原两条诊断：`.build/postgresql/test_review_matrix_key_request.py`。日志 `review-matrix-fix-edges-accepted.log` 中该文件实际 `2 passed`：真实 ROOM_KEY_REQUEST 存储失败不推进游标；真实并发 to-device 两条均能由对端 libolm 解密。
2. 补查诊断：`.build/postgresql/test_review_matrix_fix_edges.py`。最终日志 `review-matrix-fix-edges-final.log`，退出0，`4 passed, 0 failed`，43.8秒：
   - 真实 SDK 设备抓取事务实际 COMMIT 后丢失确认；设备行已存在，原游标保留且 UnknownCommitError 可见。
   - 实际 Olm 密文包含 ROOM_KEY_REQUEST，由 SDK 解密再分发派生 handler；其 PG 读取失败可见且原游标保留。
   - 实际 SDK 接收消息已推进 ratchet，保存等待 gate 时取消；旧缓存拒绝继续，新 store 从 PG 成功重放该消息。
   - 真实群密钥共享与普通 to-device 并发，同一会话对象，两条均由对端解密；关闭重开后再次发送也可解密。当前任务的网络边界不持有 SDK 数据库事务/cache gate；双方完成后连接池无借出，重开后的单任务网络回调也无借出连接。

最终补查命令通过包装器执行以下实际 runner：

```text
scripts/run_tests.sh .build/postgresql/test_review_matrix_fix_edges.py -j 1 -s -p tests.conftest -p tests.hermes_db.conftest -p tests.hermes_db.postgresql.conftest -- -m integration --postgres-test-config=<私有配置路径>
```

中间失败保留：`review-matrix-fix-edges.log` 为2 pass/2 fail，其中一项是上述真实取消遗漏；另一项是 reviewer 群加密 fixture 漏设算法。补正该 fixture 后，`review-matrix-fix-edges-accepted.log` 为总计5 pass/1 fail，唯一失败是 reviewer 错将并发进程池全局 `checkedout()==0` 当成当前 task 没有持有连接，实际计入了合法 sibling 读操作。最终改为当前 task 的事务/gate 检查及所有任务完成后的池检查后，四项全部通过。这两次 fixture 失败不计作产品缺陷。

## 未验项与门禁

| 项目 | 本次结论 |
| --- | --- |
| 原两项 major 的生产整改与真实 SDK 消费者复验 | 已独立验证，可关闭 |
| 新发现取消窗口 | 已整改，独立红后绿并验证重开重放 |
| 当前 Matrix 修复范围的未处理 blocking/major | 未发现 |
| 关键补查行为的永久仓库回归 | Root 仍在补充；最终提交前须保留并完成标准 runner 复验 |
| Task24 全域宽回归、静态门禁与其他 Reviewer | 本补记不代替其最新证据 |
| 新提交的独立安装载荷 | 旧 `2219b69afd` 包不含整改，需更新证据 |
| 非 WSL POSIX 私有启动页7项 | 既有适用主机缺口仍保留，不能由本次 Linux/WSL SDK 测试补齐 |

本次代码整改及独立局部验证已解决原两项 major。整个分支仍按原报告的 `CHANGES_REQUIRED` 总体门禁处理，最终状态须结合永久回归、最新独立发行与 Task24/适用主机证据判断。

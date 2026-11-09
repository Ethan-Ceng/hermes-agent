# 合并后旧 PG 消息展示身份缺失

## 预期与实际

合法旧 PG 消息允许 `display_identity` / `display_order` 为空。升级后调用实际
`gateway.session_stored_reads.read_transcript` 应完整返回两条不同消息，后续正序轮询应稳定。
合并候选却在正序、倒序均只返回后一条消息。

## 复现与证据

标准 runner 执行 `tests/hermes_db/postgresql/test_merge_data_upgrade.py`，
`-j 1 --file-timeout 1200 -- -m integration -k legacy_pg_display --tb=short`
及已有私有配置路径。只使用 fixture 验证归属的随机 Schema。

在 revision0030 的隔离 store 中写入两条消息，将可空展示投影置空，再真实升级至0031，
通过实际 stored transcript 分页读取。修复前 `pg-legacy-display-red.log`：
0 pass / 2 fail，exit1，12.2秒；两方向实际均只有 `old reply`，缺失 `old prompt`。
日志位于忽略目录 `.build/postgresql/merge-781dc1-audit/`，秘密不入文档。

## 调用链与根因

`read_transcript` → `_ensure_display_order` → `repositories.messages.reconcile_orders`。
后者只读取固定宽度的既存身份列，没有像上游 Native 实现一样生成缺失身份。
多条 NULL 身份共享 `first[None]`，最终 `display_ids` 的同位置代表行选择丢失前面的消息，
而身份始终为空，索引完整性也无法恢复。此问题是 PG 内部旧格式兼容问题，与 SQLite 数据迁移无关。

## 最小修复与回归

在既有 root 锁和同一写事务/Connection 中，先按 store/session、visible、NULL identity
和 id keyset 分批读取缺失行，每批最多1000行，用当前纯 codec 生成身份，清除该行不可信旧位置，
再执行既有固定列 UID/carrier 整理。已有完整身份的历史消息不会被补齐查询读取消息体。
同类调用均经该 repository；没有增加 SQLite 路径、启动 DDL 或回落。

新增正序/倒序真实升级与稳定页回归；独立发行 probe 也以冻结0004形状写入两条消息，
在独立载荷升级和新进程重开后读取实际 stored transcript，验证完整页和稳定游标。

修复后 `pg-merge-final-contracts-v3.log` 六文件36pass/0fail、exit0、246秒，
包含旧PG两方向回归。运行源码冻结bb811be4，独立发行Windows4pass/2平台skip、
Linux Native4pass、Linux PG2pass；其中原0004合法空投影行经升级及两个独立进程实际分页，
完整消息和稳定游标均通过。探针因真实stdio服务重定向stdout导致的空回执另以保留原始回执流修正，
没有改生产stdio协议或取消分页断言。最新 `checks-staged-v3-receipt.log` 15检查通过，
health1045文件0blocking/0advisory、exit0、327.6秒。

准确日志、完整PG目录回归和独立审查结算见
[实施计划](../plans/unified-database-backends-plan.md) 当前合并整改恢复点；
本缺陷已局部闭合，整体Task24的七项非WSL适用主机缺证另行保留。

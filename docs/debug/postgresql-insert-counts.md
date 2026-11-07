# PostgreSQL INSERT 计数与空写观察

2026-11-07，Task16真实验收，PG17.11、psycopg3.3.7、SQLAlchemy2.1.6。

## 预期与复现

`insert_gateway_routing_rows_if_absent` 返回实际新增行数，重复键不覆盖原行；
Worker `track_changes` 对冲突后未写入的 INSERT 应保持 changed=false。
标准runner的真实health/archive文件首次34 passed/1 failed，routing repair
单行新增返回-1。补充 `tests/hermes_db/postgresql/test_insert_counts.py`，在原代码
得到两项有效失败：三个输入含一个重复，返回-3而非2；空写误报changed=true。
日志：`.build/postgresql/pg-task16-insert-counts-red.log`。

## 证据与根因

路由修复直接累加INSERT结果的rowcount；通用DML观察器以非零rowcount判断变化。
其他同模式调用已核对，直接rowcount返回主要用于UPDATE/DELETE。
实际安装的SQLAlchemy `CursorResult.rowcount` API文档说明，默认用途是单次
UPDATE/DELETE，INSERT计数需要preserve_rowcount才能在关闭游标前无条件保留。
未保留时-1表示不可用，不能当作新增数量或实际变化证据。SQLite离线harness
没有重现该驱动差异，因此只有真实PG验收发现了它。

## 最小修复与验证范围

在 `Transactions.write` 返回的短连接上统一启用 `preserve_rowcount=True`，
使所有写操作调用方及DML观察器取得实际驱动计数。SQLite RETURNING 的现有
未知行数判断保持，读事务、锁序、Schema和回执协议不变。
复验新计数/空写回归、health/archive、Worker、事务故障、离线契约及静态检查；
最新真实PG：新回归/Worker/事务故障23 passed，原health/archive 35 passed；
全离线520 passed、0 failed、2发行环境未传入跳过；14静态检查全部通过。
独立审查未发现修复缺陷，整体仍等待Task17/18门禁。详细命令与日志见实施计划。

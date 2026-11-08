# 归档配置原始文档解析独立复审

## 审查范围

2026-11-08，独立 Reviewer，按 `supercoder:code-review` 复核 `hermes_cli/config_backend.py` 与 `hermes_cli/backup_database_policy.py` 的当前工作区完整 diff（11 insertions / 5 deletions）。审查时 HEAD 为 `dcb0e7df59df0e644e6def1157332a2bda2b7394`，两处生产修改仍在工作区；证据绑定实际文件，SHA256 清单见 `.build/postgresql/review-archive-config-source.json`。

同时追踪 ZIP、quick snapshot 恢复调用者、既有 YAML 解析器、后端字段验证及原有备份验收合同。对应设计与计划为 `docs/designs/unified-database-backends.md`、`docs/plans/unified-database-backends-plan.md`。仅审查，未改生产代码或仓库测试，未提交。

## 问题列表

未发现本次修改引入的 blocking、major 或 minor 问题。

- `hermes_cli/config_backend.py:176` 的 `parse_config_document` 仅调用既有 `utils.fast_safe_load`（`utils.py:687`），后者仍使用 `hermes_yaml.safe_load`。没有取配置后端、读有效配置、应用默认值、managed overlay、环境变量展开或临时文件。`hermes_cli/config_backend.py:196` 的 FileBackend 继续使用原 `utf-8-sig` 文本流及同一解析器；原返回值、YAML 1.1/C→pure 解析策略和普通异常行为保留。
- `hermes_cli/backup_database_policy.py:131` 仍以 `read_payload()` 的归档自身 bytes 证明 backend。`policy_for_archive`（`:149`）传入 `archive.read(member)`；quick 路径 `hermes_cli/backup_restore_quick.py:11` 传入快照文件的 `read_bytes`。选择目标 Profile 后端时读取目标配置是既有策略行为；归档证明阶段没有用目标有效配置替代归档内容。
- ZIP 的 `hermes_cli/backup.py:923` 在进入发布函数前完成 `policy_for_archive`；直接进入 `:975` 的发布函数也先构造策略。quick 路径在文件复制循环前校验全部配置。语法/编码错误仍转换为固定 `StorageConfigurationError` 并 `from None` 隐藏解析器 payload；`_storage`/`_backend` 的错误同样是固定文本。归档 backend 缺省、显式 SQLite 或 `${ENV}` 值均不能充当 PG 证明。

上述结论核对了实际调用链、异常路径与设计的“任何配置写入前拒绝无法证明 PG scope 的档案”要求；此次抽取没有扩大后端恢复能力或新增状态。

## 独立验证

使用既有 PM Windows Python `.build/postgresql/full-test-env/Scripts/python.exe`，`HERMES_TEST_FILE_RETRIES=0`，全部经 `scripts/run_tests.sh`，临时 Profile 均在 pytest 隔离目录内。

| 验证 | 结果 | 原始日志 |
| --- | --- | --- |
| 原 ConfigBackend 42 项 + 新归档配置 6 项 | 48 passed / 0 failed，exit 0，5.9 秒 | `.build/postgresql/unified-review-archive-config-owner-contracts.log` |
| 独立 `.build/postgresql/review_archive_config_probe.py` | 11 passed / 0 failed，exit 0，2.2 秒 | `.build/postgresql/unified-review-archive-config-independent.log` |

独立 probe 在真实构造隔离目标策略后，禁止 live backend、文件 open 和临时文件创建，确认 BOM 原始 bytes 可直接证明 PG 后端，普通 `${ENV}` 字符串原样返回。另对 ZIP 与 quick 各运行五种拒绝输入：metadata 声称 PG 而配置 SQLite、backend 为环境占位符、含私有标记的坏 YAML、非 mapping 文档、含私有标记的坏编码。归档中普通 marker 文件刻意排在 config 前；实际恢复入口均抛固定配置错误，原配置与 marker 字节完全保留，格式化异常不包含私有标记。没有改写恢复函数、存储实现、scope 配置或恢复返回值来制造结果。

复现命令（前置设置上述解释器及 retries）：

```text
scripts/run_tests.sh tests/hermes_cli/test_archive_config_documents.py tests/hermes_cli/test_config_backend.py -j 1 -- --tb=short
scripts/run_tests.sh .build/postgresql/review_archive_config_probe.py -j 1 -- --tb=short
```

## 无法验证项与合并门禁

| 门禁 | 状态 |
| --- | --- |
| 本次实际生产 diff 无 blocking / 未处理 major | 通过 |
| 原始归档证明、拒绝前不覆盖、错误不泄漏、FileBackend 合同 | 上述 59 项独立通过 |
| 最新代码实际 PG backup、完整 Native 备份回归 | 本 Reviewer 未执行，待父任务核对实际日志 |
| 新生产提交后的发行载荷重建、安装验证、完整最终回归 | 尚未由本报告证明 |
| 非 WSL 私有启动页七项适用主机证据 | 既有缺口仍须保留 |

## 审查结论

本次归档解析修改的局部复审通过，未发现需要整改的问题。总体结论继续保留 **`CHANGES_REQUIRED`**，不以局部结果批准整个统一数据库实现。旧冻结 `58d0003f83d1c99505e1173508ea7e2934d89411` 的 659 项或其他旧载荷结果不能外推到这两处新生产修改；最终发布、全域及适用主机门禁仍以匹配最终代码的证据判定。

# 上游同步合入develop代码审查

## 审查范围

- 目标：原develop cbfc773dd7；个人起点37fd59cf8d；本地main 6c95ee82ef。
- 整合分支：sync/upstream-20261112；2026-11-13 Asia/Shanghai。
- 设计：../designs/upstream-develop-sync-20261112.md；计划：../plans/upstream-develop-sync-20261112-plan.md。
- 同一Agent自检，未使用独立Reviewer。审查实际冲突及相对三方预览树066ba3640191e56db5e908e28c3bea75396fda2e的完整整合适配diff，并以全树语法/迁移导入审计和行为合同覆盖自动合并风险。未逐行重审上游5024个提交。

## 问题列表与处置

未发现未解决的blocking或major；以下整合问题已修复并复验。

- major：旧SQLite内部模块及SessionDB内部字段已搬迁，上游新增消费者仍引用旧位置。修正实际infra读取点和测试patch位置，不恢复shim；变更路径对8个已删除模块的导入审计0遗漏。
- major：上游resumable与room task summary只实现原生存储，PG使用时会访问文件或缺少操作。实现现有scoped metadata具名记录和房间具名查询，捕获Profile与store，事务锁覆盖物理target和store-id；真实PG先红后绿、30项合同通过及最新4项复验。
- major：原生Profile迁移后旧minting-home与现路径不同。精确PG身份保持；原生必须同时匹配实际session行、sid、route、origin profile/chat/user，保留后续lineage/policy检查。跨Profile、chat/user、route和缺行的负向合同通过；简单放松身份检查的被拒方案未执行。
- major：旧home/secret setters与上游原子scope模型不兼容。迁入bind_state；同一turn/fence、冻结terminal policy和捕获secret保持，原生scope与实际PG合同通过。
- major：健康与API读取点需在接受新tracked连接的同时保留mode=ro；探针不能隐式创建数据库。lifecycle17项与实际Linux header11项通过。
- minor：规范提示渲染不能伪造解释器OS，快照字节不能随Windows检出变化。改传入展示/技能元数据，固定snapshot LF；两端完整快照合同通过，stock fixtures相对main无内容修改。
- minor：上游宿主隔离测试的symlink在普通Windows权限下不能创建。用真实NTFSjunction并按沙箱路径格式断言；Windows/Linux各14项通过，保留实际隔离断言。

## 需求、正确性与安全性

保留双方历史及最新个人数据库分层，没有整体ours/theirs或隐式SQLite回落。
claim/recovery/TTL/pin、快照一致性、投递claim proof和取消后的release路径与原语义核对。
SQL使用参数和现有组合scope；PG metadata键有版本前缀，锁标识由无秘密的物理target摘要组成。
不增加业务Schema或修改历史迁移；普通获取检查ready，测试显式provision。
Matrix异常通过现有proxy redaction脱敏，无敏感原始traceback。
新代码落实际域/应用所有者，边界lint0新增违规；测试覆盖真实后端及反向隔离，没有删正常断言制造通过。

## 无法验证项

线上最新因DNS不可达未确认；本轮仅吸收冻结的本地main。
未执行全仓测试或完整前端/桌面构建；现有TypeScript包缺失使额外noEmit检查无法启动。
没有正式实例Schema升级、重启或部署；PG测试使用专用验收DB随机Schema，不能外推为正式迁移完成。
同一Agent自检不能提供独立Reviewer的额外保障。

## 合并门禁

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 无未处理blocking/major | 通过 | 本文处置及对应行为回归 |
| 冲突与旧模块引用 | 通过 | 未合并路径为空，1643变化Python路径审计0旧引用 |
| 原生与PG相关回归 | 通过 | 执行计划中的完整文件组、修正复验与日志 |
| 静态与架构边界 | 通过 | scripts/check18项exit0；DB/plugin边界exit0 |
| stock提示与生成合同 | 通过 | Windows/Linux prompt surface各2项，Python生成合同 |
| 新Schema迁移 | 不适用 | 未新增PG Schema，原生沿用显式初始化；正式升级未执行 |
| 完整前端构建 | 未执行 | 非本轮手动适配范围，限制已披露 |
| develop祖先与并行保护 | 通过 | 三条输入祖先exit0，expected-old比较交换快进至9cd5c2854d |

## 审查结论

APPROVED：支持已授权的本地整合与受保护快进；结论限于本轮兼容适配与列明门禁。
不代表全仓测试、完整UI构建、线上最新或正式数据迁移已经验收。

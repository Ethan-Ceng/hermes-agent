# Task7 SQLite会话普通打开诊断

- Task6 基线 4767f5939ed685b84764a78667ef8138fbbcdaad 上，2 个新增文件共 3 项失败。普通获取创建缺库、已有库打开执行 DDL、CLI status 返回 ready。此前一个未绑定项目解释器的本地写入命令 exit1，没有修改文件，改用隔离 Windows PM 解释器后执行了红测。
- 第一次 Windows 全 Native 批次 exit1，224 文件中 1739 passed、18 failed、147 skipped。Registry 真实获取的临时库缺少显式初始化，Named Profile 和 guard 用例仍 patch 构造器。逐测试明确初始化，并迁移真实打开入口，保留隔离、重试、并发、回执、锁和关闭断言。
- 8 文件跟进批次 67 passed、2 failed、6 skipped。冷进程的声明探针会在 _parse_schema_columns 中对 :memory: 执行 SCHEMA_SQL，目录缺失时 Profile 连接配置又会先建目录。真实 sqlite3 SQL trace 与函数名栈定位到这两处。普通打开先检查文件并使用静态声明列清单，清单由 SQLite 解析 Schema 的现有合约测试逐列核对。旧算法仍用于显式升级。
- Dashboard 3 文件中 202 passed、1 failed、5 skipped，唯一失败是缺库 503 的提示已改为显式 db upgrade。修改提示断言时保留了 503 和文件未创建断言。后续 6 文件 exit0，235 passed、16 skipped。Dashboard 扫描保护的原算法和锁目的值保留给显式升级，没有删除测试。
- 14 个外部消费文件 120 passed、7 failed。根因是一个 TUI 字符串分派仍使用构造器、Achievements 测试替换整个模块、一个单引号 CLI patch 未同步及一个 fixture 导入问题。动态读取点和 fixture 已同步，后续 15 文件 exit0，138 passed。
- 中间 Native 完整批次 Windows 224 文件 1757 passed/147 skipped，WSL 224 文件 1888 passed/16 skipped。实现还有后续变更，保留为阶段记录。再一次 Windows 全批次 1756 passed/1 failed/147 skipped，测试确认 frame 审计被拒绝时诊断不得阻断 DB。使用特定 PermissionError 降级，保留真实业务写读断言。
- 静态初跑报 Ruff 正则别名和 health 的诊断 catch、Profile 线程、文件行数等。改用项目线程绑定、精确异常、既有文件行数上限。消费点跟进阶段报慢打开时序测试 HX013。原测试的等待上限由模拟的慢打开触发，在该行说明保留真实延迟的理由。失败记录留在本轮证据，不能计作通过。
- 正式 checkout HEAD 90a2987e8c5decb7997157ca17a301ff51ecce78 已再次只读核对，工作区 clean。

- WSL checkout上的后续完整224文件批次同样由frame PermissionError测试触发唯一失败，1887 passed/1 failed/16 skipped。修复后在新PM本地快照完整224文件1888 passed/16 skipped、Windows完整224文件1757 passed/147 skipped，实际exit0。
- Linux显式补齐应用批次有一次在计时断言上失败，41 passed/1 failed。触发点为真实慢DDL已中断但断言把之前的锁外完整性扫描算入同一预算，总时间5.2636s超过5s。计时锚定在实际持锁慢阶段，仍执行原3s预算、5s断言界限、启动等待、完整事务回滚、文件签名及列缺失断言。相同完整两文件复验42 passed、exit0。
- 显式升级冲突文本改为命名实际持锁网关的stop命令。Native WSL快照之后只改该提示及对应应用测试；相同源码上的两文件应用复验覆盖实际锁冲突、附着、回滚及恢复。历史锁目的、SQL及算法未改变。

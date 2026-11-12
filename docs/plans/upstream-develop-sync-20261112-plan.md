# 上游更新合入 develop 执行计划（2026-11-12）

- 设计：docs/designs/upstream-develop-sync-20261112.md。
- 指导：docs/upstream-sync-guide.md。
- 分支：sync/upstream-20261112。
- 工作区：D:/AI/hermes-agent/.build/upstream-sync-20261112。
- 整体状态：MERGED；当前任务：全部完成；完成：5/5。
- 日期：2026-11-13 Asia/Shanghai。
- 范围限制：官方fetch DNS失败；本轮冻结本地main，线上最新未确认。
- 授权：本地指导、整合和合入develop；没有推送或部署授权。

## 全局约束

保留原分支和backup，不覆盖共享历史、不批量ours/theirs、不动正式配置和数据。
遵守数据库分层、scope、事务、Schema、关闭与缓存约束；测试统一scripts/run_tests.sh。
依赖仅使用项目PM；验证失败不提前推进develop。
原目录.idea/、dify-main/及另一工作区owned/、target/均保留。

## Task 1：冻结输入、建立备份和检查上游

状态：completed

目标：保存可恢复输入并确定范围。涉及：Git refs与remote配置。
步骤：检查分支/工作区/现有计划，建backup，配置并fetch upstream。
验证：git show-ref --verify与rev-list --left-right --count。
完成条件：输入SHA、包含关系与fetch结果记录，原分支不变。
结果与证据：两个backup show-ref exit0；develop=cbfc773dd79241752697e647067c63338fc01680；
个人=37fd59cf8d4ac63d74dc5ed34e5456ac2bc2bbea；main=6c95ee82ef2121bea9e8964b66c3ec6f09278072。
develop...个人=0/64；main...个人=5024/161。官方fetch exit1：Could not resolve host: github.com。

## Task 2：保存指导、设计和计划

状态：completed

目标：保存可持续执行的同步协议。涉及：本指导、设计、计划及独立sync工作区。
步骤：从个人起点创建sync工作区，记录分支职责、冲突规则、验证门禁与恢复。
验证：工作区HEAD/文档一致性、git diff --check及暂存范围。
完成条件：三份文档保存于sync分支的指导提交。
结果：worktree add exit0，检出24029个文件，HEAD=37fd59cf8d。
文档首次apply_patch自动审批超时；一次重试因父目录创建失败未写入，改用获授权的文件写入。
验证证据：git diff --check、git diff --cached --check均exit0；指导提交3c8c3ef18d，仅3份文档。

## Task 3：整合main并适配冲突与迁移读取点

状态：completed

目标：在新架构中保留双方行为及历史。涉及：实际冲突及双方修改路径、迁移后的消费者。
步骤：对冻结main SHA执行no-commit merge；登记冲突；按模块最小适配并审查自动合并。
验证：未合并路径为空，git diff --check成功，受影响行为合同通过。
完成条件：冲突清零，上游修复未被静默丢弃，个人架构不回退。
结果与证据：实际24个冲突均已解决并暂存；从三方预览树审查适配差异，移植到实际所有者。AST复核1643个相对main变化的Python路径，对8个已删除内部模块的直接及from-package导入引用为0。

## Task 4：最新验证和代码审查

状态：completed

目标：以当前整合源码证明可合入develop。
涉及：受影响测试、静态/边界/生成检查与docs/reviews/upstream-develop-sync-20261112-review.md。
步骤：检查隔离环境及PM依赖，执行scripts/check、受影响行为与数据库合同；审查并整改后重跑。
验证：记录每条实际命令、退出码、通过/失败/跳过数及限制；核对祖先与无major/blocking问题。
完成条件：必需验证通过，审查APPROVED；环境不足则BLOCKED，不推进develop。
结果与证据：最新分组回归、Windows/Linux规范提示快照和真实PG合同通过；完整scripts/check的18项exit0；同一Agent自审APPROVED。详细命令与范围见最终验证。

## Task 5：本地合入develop并交付

状态：completed

目标：已验收结果fast-forward进入develop。涉及：本地整合提交、develop引用与本记录。
步骤：保存整合提交，确认develop未在任何工作区检出且仍为原SHA，核对祖先后以update-ref的expected-old比较交换等价快进。并行变化则中止提升并重新整合。
验证：merge-base --is-ancestor核对三条输入；核对develop SHA、状态与未推送关系。
完成条件：develop包含三条输入，无意外文件/推送/部署/正式数据操作。
结果与证据：整合提交9cd5c2854df435d50f24ee2f6bc8fe68a2c30adb已创建，双亲为指导提交3c8c3ef18d及冻结main 6c95ee82ef。develop从cbfc773dd7以expected-old比较交换快进至该提交；三条输入的merge-base --is-ancestor均exit0。最后仅追加完成记录，不改动已验收源码。

## 最终验证

### 执行命令与范围

所有命令在sync工作区执行，使用已有PM环境Python 3.14.9，HOME/RUNTIME和测试临时目录均隔离。
每组完整测试文件名与原始结果保存于ignored .build/validation/*.log，不提交秘密或日志。
门禁代码树（之后仅更新指导/设计/计划/审查）：d03452b0981461cf957f02a10808ede06ced8762。

- python scripts/check --staged --base main：exit0，18 checks ok；health1638文件，0 blocking/0 advisory，260.6秒；先前失败整改历史见下文。
- python scripts/hermes_db_boundary_lint.py --check：exit0，8565 resolved imports，0违规。
- python scripts/boundary_lint.py --check：exit0，848 module_to_core/20 core_to_module，与已批准baseline一致。
- git diff --cached main --check：exit0。未合并路径为空，fixtures/prompt_surface相对main无内容差异。
- bash scripts/run_tests.sh <文件列表> -j 2 --file-timeout 240 -- --tb=short -ra，实际文件集：
  - 恢复/回执/子代理6文件36passed；存储抽取后原生子代理4文件31passed（resumable-backend-native.log）。
  - 房间driver、两个change watcher和attachment routes4文件70passed（rooms-native.log）。
  - 投递、重投、Cron、Matrix、宿主隔离、prompt surface和生成合同12文件初次169passed/3failed/4skip；3处失败由后述复验关闭（integration-regressions.log）。
  - 最新Windows7文件147passed/1failed/3skip，其中运行scope52、prompt builder55、lifecycle17、宿主14、存储scope2、技能平台数据6通过。唯一失败为两份fixture被CRLF检出，已固定LF，单独prompt surface完整2项exit0（prompt-windows-pass.log）。3skip为POSIX限定的提示构建测试。
  - Cron与新增存储scope的修正组6项exit0（gate-fixes.log）。
- 真实Linux（WSL Ubuntu-26.04）同一runner：header probe11和宿主14项通过，首次prompt1passed/1failed仍为共享checkout的CRLF；修正后prompt surface完整2项exit0（final-linux.log、prompt-linux-pass.log）。没有伪造sys.platform或强制skip。
- bash scripts/run_tests.sh tests/hermes_db/postgresql/test_upstream_resumable.py tests/hermes_db/postgresql/test_upstream_rooms.py tests/hermes_db/postgresql/test_surface_flow.py tests/hermes_db/postgresql/test_merge_storage_contracts.py -j 2 --file-timeout 240 -- -m integration --tb=short -ra --postgres-test-config=<私有验收配置>：30passed/0failed（pg-final-contracts.log）。锁加入物理target后受影响两文件4项再次exit0（final-pg.log）。使用专用验收DB的fixture随机Schema，SQLite护栏保持。
- 全树AST语法审计12004个Python文件0错误；最新变化路径旧模块导入审计0遗漏。

### 执行结果与限制

原生及PG新持久化合同均经过先红后绿；保留实际隔离、回执、claim/recovery、readonly和描述符断言。
PG复用已有scoped metadata，无新revision和历史SQL改写；原生测试fixture显式初始化Schema。正式数据升级、重启和部署均未执行。
规范renderer现在只注入展示/技能元数据，保持真实宿主。快照目录固定LF，与main的stock内容一致。
完整前端/桌面构建未执行；额外TS noEmit因现有tsc shim缺实际TypeScript包无法启动，未安装或修改依赖。Python生成合同检查通过；不外推为全仓测试或完整构建通过。
WSL共享Windows worktree的gitdir指针在runner预编译阶段有诊断警告，测试发现、运行和退出码正常；Git门禁均在原生Windows运行。
上游fetch因DNS失败，线上最新未确认；本轮只覆盖冻结本地main。

### 未通过项目与最终状态

必需门禁无未通过项；前端完整构建与线上最新不在本轮已验证范围，限制见上文。自审APPROVED（独立Reviewer未执行），合并前状态READY_TO_MERGE，受保护快进已成功；交付状态MERGED。

## Task 3 发现与范围修订

实际24个冲突；已逐块处理22个内容冲突，旧dbfile的上游描述符释放修复已移到infra/sqlite/generation，旧API测试已有上游替代文件，保留同一行为断言。
上游新增内部引用约22处已随新所有者修正；Matrix代理错误脱敏移植到实际sync sibling；投递提取保留PG claim proof。
首批4完整文件exit1：header测试仍导入旧dbfile（collection失败），新恢复测试3失败来自fixture未显式初始化schema；两组change watcher结果需从日志汇总，不能外推全部通过。
修正测试真实导入及共享profile fixture，保持普通生产获取不执行DDL。
新发现：上游resumable_subagents是新的持久化能力；必须检查PG后端、显式Schema和恢复/claim语义，不能仅保留SQLite分支。新增groups任务摘要/变更通知也要适配PG。若涉及新Schema需先更新设计并验证升级，不改历史revision。

## 2026-11-13 当前证据

- 24个冲突已处理：保留上游改动并适配现有所有者，不批量选择ours/theirs。旧dbfile修复移入infra，替代API测试保留原断言。
- 身份校验最初直接限定到PG的方案被自动审批拒绝，未执行；保留精确PG身份，新增原生实际行/路由/profile/chat/user联合校验，2个含反向场景测试通过后获准接入。恢复组6文件36passed；后续存储适配后原生子代理4文件31passed。
- 新PG持久化2测试先红（错误读取SQLite位置），具名scoped metadata实现后2passed，真实随机Schema且SQLite连接护栏保持。
- 新PG群组2测试先红（缺失PG摘要及将RoomStoreRef转Path），具名快照查询与Profile绑定后2passed。原生房间/变更/附件4文件70passed。
- 首轮header/变更组19passed/3failed/11skip；失败已由后续恢复合同覆盖修正，11项为当前Windows不适用的POSIX合同，不冒充通过。
- 全树AST审计12004个Python文件，0语法错误；3个缺失字面模块属于插件虚拟名称和旧版fallback，无生产缺失模块。
- hermes_db_boundary_lint --check exit0：8565 imports/0违规；boundary_lint --check exit0：848 module_to_core/20 core_to_module，无新增未批准跨界。
- 测试临时Git仓库最初置于checkout内被测试保护拒绝；已改为系统临时目录，无bypass，所有31个原生合同通过。
- 所有日志留在本工作区ignored .build/validation，不提交原始日志或秘密。

## 首轮最终门禁与整改

scripts/check --staged --base main：18项，agents链超70字符、ruff2项、health5项失败。整合树相对main的whitespace检查通过；相对个人HEAD出现的15处EOF空行来自原上游文件，未扩大格式修改。
整改：压缩活动gateway指南且保留所有存储约束；修正ruff风格；把旧DB Profile setters迁入上游统一bind_state，保留同一turn/fence及冻结terminal和捕获secret；为敏感SDK日志边界注明不打印原始traceback理由。
扩展回归12文件169passed/3failed/4skip：Cron新测试缺少显式executions初始化；prompt renderer的Windows干净子进程缺少USERPROFILE；宿主隔离测试真实symlink缺Windows权限。分别补显式fixture、隔离USERPROFILE/TEMP和真实NTFSjunction，不移除断言或强制skip。新增两个存储scope合同后重验。

## 后续验证与边界说明

- scope API整改后：真实PG4完整文件30passed/0failed；Windows新增scope与Cron6项通过。
- 新提示规范渲染保留真实OS，只注入Linux展示/技能元数据，统一LF和临时根路径；不改写stock snapshot。此前发现WSL提示导致差异，修正后待二端复验。
- POSIX header首次8passed/3failed，三处失败为读取搬迁前SessionDB._conn；已改实际连接owner._connections._conn，并补所有fixture显式Schema及新模块导入。
- Windows宿主隔离14项通过：采用真实临时junction及POSIX沙箱线协议路径分隔符断言，没有强制skip或放松隔离。
- 自审修正：PG resumable短事务锁纳入物理target与store-id，避免不同Schema同名store无谓争用；健康探针保留原mode=ro，新增tracked读不隐式创建数据库。
- 额外共享TS noEmit检查暂不可执行：现有node_modules只有tsc shim，实际TypeScript包缺失，未安装或修改用户依赖；Python生成合同验证已通过，未宣称桌面/前端完整构建通过。
- Task5改用等价快进CAS：先确认develop未在任何工作区检出、仍为原SHA且为整合结果祖先，再用git update-ref <new> <expected-old>更新，避免两次全树检出；不强推、不覆盖并行提交。


## 本地交付核对

- 合并提交：9cd5c2854df435d50f24ee2f6bc8fe68a2c30adb；保留双方历史，没有squash、rebase或force。
- develop已经包含原develop、最新个人37fd59cf8d及本地main 6c95ee82ef，三条祖先命令exit0。
- 源码验证后的差异只有指导、设计、计划与自审记录；合并前最终文档agents-md单项和相对main whitespace均exit0。
- 最后完成记录另存docs提交并再次以expected-old比较交换快进develop；同步分支保留。
- 两条backup、主工作区main和原个人工作区保留；没有push、正式配置/秘密/业务数据修改或正式实例重启。
- 限制：线上最新未确认；没有执行全仓测试、完整前端/桌面构建或正式数据迁移。

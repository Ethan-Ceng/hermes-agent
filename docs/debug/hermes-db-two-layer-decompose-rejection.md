# 两层重构 R1：拒绝分解请求仍触发自动晋升

## 范围与预期

独立初审：[原始报告](../reviews/hermes-db-two-layer-boundary-review-initial.md)，初版SOURCE_TIP e3898db77144cded81d64a1a750f6c2d9a31eefa。此问题属于本轮抽取应用编排引入的控制流回归，不是既有后端行为差异。

对不存在、非triage或已经分解的根任务，分解应返回None并保持任务状态、事件不变。首次分解使用auto_promote=False时，子卡等待人工审核；拒绝的重复请求不能替代审核。

## 实际复现

新增真实PG合同 tests/hermes_db/postgresql/test_kanban_decompose_boundary.py：首次显式禁止自动晋升，记录子卡todo及created事件；重复调用返回None，却观察到ready及额外promoted事件。fixture仅使用既有私有配置核对归属的随机Schema，路径与Profile在临时目录；没有使用mock存储或修改正式实例。

在隔离cwd D:/AI/hermes-db-packages，先绑定controller的隔离HOME/RUNTIME、使用本轮PM解释器后执行：

```powershell
. .build/two-layer-dev/controller.ps1
Test-Pg -Files @('tests/hermes_db/postgresql/test_kanban_decompose_boundary.py')
```

红灯：1文件，0passed/1failed，实际exit1。失败为实际业务状态/事件元组('ready',['created','promoted'])与预期('todo',['created'])不符。完整展开argv、解释器/cwd/来源与退出码见Task20 review_remediation.red_record；原始日志仅留ignored目录，未提交DSN/秘密/原始失败堆栈。

## 根因与证据

0d基准 decompose_triage_task 的拒绝分支在事务内直接return None，因此整个函数退出，后续recompute_ready不执行。SQL主体抽取到decompose_task_rows后，None只退出SQL helper；应用caller继续执行auto_promote。SQL/helper的AST保留不等于调用方控制流等价，早期135项方法证明没有覆盖该caller结果。

独立Reviewer通过控制流确认major；主Agent独立对照基准及真实PG红灯验证同一根因。

## 最小修正

只在hermes_cli/kanban_storage_catalog.py取得ids后，若ids is None立即返回；成功分解才进入原auto_promote分支。不改SQL、Schema、锁序、Connection、回执或其他算法。无新兼容flag、注册或代理。

## 局部验证

- 新合同修正后1passed/0failed，实际exit0；额外断言显式recompute_ready后仍正常晋升并只新增对应promoted事件。
- 原有原子分解/冲突回滚/继承合同与新回归一起选取：2文件2passed/0failed，实际exit0；原正常业务断言保留。
- 对应完整命令、来源与时间/退出码在Task20及ignored review-r1-compat-pg记录。

## 整改验收

初版5载荷、10批158passed/3skip仅历史保存于*-initial.json及原独占冻结根，不能算新代码通过。当前精简manifest只增加一个直接R1合同，不扩大到旧PG全领域目录；其余必需文件组保持。

按[实施计划](../plans/hermes-db-two-layer-boundary-plan.md)重新执行Task17–19：新SOURCE_TIP、新v2 source/test-driver、两端5个freshPM载荷、全部精简完整批次实际exit0、源/资源/预算/静态检查，然后交原独立Reviewer只读复审。未完成不得READY_TO_MERGE或计Task20完成。原统一Task24/七非WSL/八Windows问题继续独立。

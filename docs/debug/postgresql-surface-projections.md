# PostgreSQL 入口恢复投影差异

2026-11-07，Task17实库验收，PG17.11/psycopg3.3.7/SQLAlchemy2.1.6。

## 预期、复现与证据

webhook恢复只能检查路由和automation元数据，不应拒绝正文中保留的NUL；
viewer列表应从当前policy的entry.session_id找到目标终止时间。
真实PG新增test_surface_projections.py两项均失败，离线Core未暴露这些差异。
临时SQLAlchemy handle_error观测仅输出SQLSTATE和主错误，不输出DSN/参数；
确认后已移除观测代码。日志pg-task17-projections-red.log及
pg-task17-projections-diagnostics.log保存于.build/postgresql。

## 最早偏差与根因

1. webhook的automation存在性检查使用json_path_value，将整段payload转JSONB，
   PG报22P05 unsupported Unicode escape sequence。原始TEXT JSON合法并已保留正文，
   失败发生在派生selector转换，不能通过修改/丢弃正文来解决。
2. viewer将TEXT目标id与json_path_value的JSONB值比较，PG报42883
   operator does not exist: text = jsonb。SQLite json_extract的返回类型掩盖了它。

## 有界整改

viewer固定路径改用已有json_path_text，解决text/JSONB类型不匹配。
webhook先尝试JSON TEXT投影，再尝试先提取子JSON，均仍失败；已撤销这两种
尝试。核对[PG17源码get_worker](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/backend/utils/adt/jsonfuncs.c)
确认所有getter均以need_escapes=true解析整个输入，不能用嵌套提取绕过。
最终恢复selector按store_id及seq上界分批读取128行、释放读连接后用Python解析原文，
避免持有事务解析大批正文；固定上界避免连续新增造成无止境扫描。
finalization先在SQL限制当前store、webhook会话及终态，最终动作仍重新校验epoch/root。
代价是payload查找在所属store内扫描历史准入，未宣称此路径具备索引化chat查询吞吐。
未改变Schema、正文格式或最终权限判断。契约同时覆盖字段缺失、JSON null、
空对象和false，只有前两种入选；保留跨store及chat隔离。相关结果写回计划。

## 模型配置的同类边界

独立复查确认POST /api/sessions允许browser_model_lock.model_options.extra_body.stop
含NUL，model_config按TEXT JSON原样存储。新增公开能力契约日志
pg-task17-model-options-red.log：key_scan与deletion两项为有效SQL失败，listing最初
误传exclude_children参数得到TypeError，不计为有效回归红灯；已改为include_children=False。
为保留原配置，0004增加delegate_origin BYTEA及两个存在标记，统一在创建及中央
update_session计算，列表/孤儿/删除使用这些派生值。任意键路径扫描在当前store读快照
内分128行解析原文，保留点、引号键及数组路径，不通过替换NUL来改变JSON值。
显式升级分批回填当前PG数据，0001–0003冻结；不是SQLite旧数据兼容。
初轮整改实库4文件23 passed，含0003→0004/重复升级/双store/原文保留与所有入口。
新schema影响先前主题，必须重新运行全部真实PG，不能只沿用旧revision绿灯。

消息展示边界也实证：正常admit_display/worker_display_kwargs产生NUL标题预览后，
display_message_count报存储读取失败（pg-task17-display-metadata-red.log）。冻结前的0004
新增display_query JSONB：顶层键先JSON序列化成ASCII再hex，值各自JSON序列化成
ASCII字符串，null仍为null。SQL只提取比较字符串，不对字符串内容二次JSON解析。
查询参数同算法，原display_metadata不变；中央写入/更新同步，克隆复制，业务行剔除。
初版含引号键在PG通过28项，但Core SQLite的JSON getter路径不支持该键：全离线
541 passed/5 failed/2 skipped。已统一hex键并同步冻结回填，局部双后端42 passed；
最新全离线546 passed/0 failed/2发行环境未提供跳过，73.0s；14静态检查通过、
31代码文件0 blocking/0 advisory。不得将中间PG绿灯外推为当时全离线通过。

0004的新session派生列原会进入移动内容摘要，两个纯函数回归有效红灯证明升级回填
会使待完成票据失效。摘要已排除三列，保留原model_config和所有业务内容；
上述42项局部及546项全离线包含修复后两项绿灯。最新实库整轮仍须最终日志确认。

## 其他入口失败

首次test_surface_flow.py为7 passed/3 failed：两项HTTP创建503；一项共享测试
对已存在的临时home重复mkdir。mkdir用exist_ok修正测试前置条件，不能称生产修复。
HTTP单独运行通过，整文件失败时owner实际为根fixture的hermes_test SQLite home：
tests/conftest在模块已导入后会pin DEFAULT_DB_PATH，生产_default_db_path按既有契约
优先该显式override，覆盖了surface_config的context home。fixture现将该常量恢复为
导入默认值，测试真实call-time Profile解析；实际home仍全部是隔离临时目录。
新增authority/db home断言保留以防今后误将SQLite执行算作PG通过。

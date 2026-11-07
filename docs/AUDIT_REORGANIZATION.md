# 审计库冷热分层与新绩效起点

2026-11-07用户授权隔离无当前用途的迁移历史，验证当前功能后切换精简库；只整理全部Paper持仓，不下单、不撤保护单。事实采集继续；自动策略绩效T0单独批准，当前尚未启用自动交易。

本机已核验快照1861767168 bytes，98个legacy_epoch表。最大legacy_epoch_migration_rows约1.24GB；前六大对象约91%。保留区79表的schema/外键无legacy引用，当前trading/reporting/ops运行代码未找到legacy_epoch显式引用；迁移脚本引用不删除。动态依赖与业务不变量还须在候选验收中核对，不能只按名字删除。

`reporting/audit_compaction.py`构建新候选，从不覆盖源：拒绝待合并WAL、跨legacy schema引用和未审查虚拟表；保留全部当前表/索引/视图/触发器、rowid、值类型/内容、autoincrement高水位、user_version/application_id及journal模式。逐表行数及有类型内容摘要一致，最后integrity_check和foreign_key_check。源文件SHA-256前后保持，历史完整原库作为独立档案，不只保留统计数。

本机隔离候选2224128 bytes，79表保留，98历史表仍在原快照，未激活生产。云端切换必须使用切换时的最新静止源，暂时停止已识别审计writer，确认无剩余句柄，构造并逐表验证，保留原DB/WAL/SHM及回滚记录，最后同目录原子更名、恢复原owner并做只读回读。候选失败则恢复原库，不启动另一个监测/交易worker。不能用较早的本机候选覆盖不断写入的生产数据。

新统计起点不抹除旧持仓或已用3/3测试范围。2026-11-07核验：AAPL17、META100、MSFT13、NIO200、PFE8、T3；NVDA0。PFE存在8股SELL STP GTC，23.01USD，permId911411084。该清单不是卖出授权；当前无任何清仓或撤单。

自动交易真实门禁：SAFE_MONITOR_ONLY，ready=false，execution_approved=false；正式风险/对账批准和PAUSED/MAINTENANCE未解除。旧有限测试scope过期、approved=false；真实UNKNOWN/STARTED订单操作计数0。研究可自行选公司，不等于交易标的自动批准。仍需明确策略/版本、执行标的、资金/总敞口/单笔损失预算、既有持仓保护方案、时段和批准的T0。当前采集事实不等待T0，以免丢掉风险与对账证据。

参考一手实践：SQLite在线backup保证一致性副本，VACUUM只重排/回收空间，不能代替业务删留裁决；QuantConnect/LEAN重启时需保存/恢复状态并处理回测与实盘对账差异。
- https://www.sqlite.org/backup.html
- https://www.sqlite.org/lang_vacuum.html
- https://www.quantconnect.com/docs/v1/live-trading/live-reconciliation

已知独立缺口保留：断线时历史BUY execution回退可能为已平仓NVDA误报UNKNOWN数量；Linux缺CJK字体导致中文图表方框。该次冷热分层不将它们改写成已修复。

## 云端实际切换验收 2026-11-07

01:08:39 UTC 激活当前表库；1861828608 bytes → 2285568 bytes，79张现用表保留，98张legacy表隔离。每表行数/类型化内容/rowid摘要一致，索引/视图/触发器及sqlite_sequence保留，quick_check、integrity_check与foreign_key_check通过。原物理库及WAL/SHM和一致性快照保留在state/archives/audit-20261107T010556Z；来源SHA-256为2472721ff701ac1267c0c02c80fc4d62e2e50bd64abf0a8bfc2da58f3df1b7d9。cutover.json记录COMPLETE，原先活动采集器/timer已恢复，Gateway未重启；PAUSED/MAINTENANCE、交易/投递批准及风险数值哈希不变。切换后完整Paper回读与身份核验通过。该结果不授权交易；跨库恢复与异地恢复不能因此宣称已验收。

01:34:56 UTC新备份四业务库成功；本机隔离解压，四库SHA-256均与云端清单一致，integrity_check全部ok、foreign_key_check全部0。本机恢复副本未替换生产；审计库恢复副本79张业务表/2310144 bytes。云端原库归档与新备份均保留；逐库一致不表示跨库原子，异地存储灾备仍未验收。

日报修复：前序聊天已于11月6日指出中文格子。本轮核实云端fonts-noto-cjk未安装、fc-match回退DejaVu；安装发行版官方包后匹配Noto Sans CJK SC。模板显式指定CJK字体，生成前检查实际字体，等待字体后测量页面高度，拒绝无法核验或超过有界高度的输出；不再固定2200像素留下大空白。渲染revision改变后重生成，避免同一账户快照缓存旧方块字PNG；零仓位不计入持仓数量。现有报告本次以新纠正版事件发送，不修改旧回执。

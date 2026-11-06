# 会话/行情日志与Telegram字段（2026-11-06）

## 4455条是什么

这是当时当天paper_callback_events中kind=pause_transition的行数，不是断线次数、交易次数或Telegram消息数。后续统计4557条，其中3900条来自同一个GLOBAL_NEW_ORDERS_PAUSED的reason在包含/不包含reconciliation_verified之间周期切换：每轮券商回读暂时清除完整标记，再在end markers齐全后恢复；全局暂停本身未解除。Nov5同表6740条，其中同类reason反复切换3322条。

本次起，仅真正进入某暂停scope、离开scope、交易决策从禁止到允许时追加暂停转换事件。同scope只改reason不重复记PAUSE；最新原因保留在当前state和分钟采样。原始历史行保留，不删除、不改写。错误和独立故障/恢复仍另行保存。

## 设计和保存位置

云持久根/home/ibkr/.local/state/openclaw；本机对应根/Users/nbhsbgnb/.local/state/openclaw。当前真实自动监测在云端，不把本机旧数据库当云端实时事实。

| 来源 | 保存内容 | 能证明什么 / 不能证明什么 |
| --- | --- | --- |
| systemd journal，ibkr-gateway.service | 进程停启、初始化/软重启 | 不单独证明API认证、实时行情或策略运行 |
| runtime/recovery.sqlite3 → paper_safety_state | API/上游连接、账户身份、回读end markers、最新行情及门禁 | 最新状态，覆盖更新；不是完整逐秒历史 |
| 同库 → paper_callback_events | 错误回调、订单/成交、暂停转换等 | 事件证据；没有事件不意味着一直健康 |
| 同库 → symbol_health_runtime/subscription_lifecycle | 按标的行情状态、会话冲突、恢复验证和重试预算 | 保留当前恢复状态；不替代连续行情历史 |
| 同库 → incidents/incident_events | 故障实例、发生/恢复状态 | 独立故障批次，不等同每条错误回调 |
| 同库 → notification_outbox/delivery/receipts | 排队/发起/确认、UNKNOWN、Telegram原生消息ID | 平台接受，不是用户已读；旧SMTP记录不是Telegram记录 |
| observations/YYYY-MM-DD/*.json | 约5分钟账户快照，完整与不完整都保留 | 这些UTC日期目录下的快照不含常驻行情报价 |
| trading_audit.sqlite3 → paper_readback_observations | 正确账户的已验证券商事实与来源 | 账户回读，不等于行情健康或自动策略可用 |
| 新增：recovery.sqlite3 → paper_health_samples | 每进程epoch每分钟最多一条API、上游、身份、回读、逐标的行情、策略门禁观测 | 从部署后开始；缺口标未知，不回填历史；采样点不是整分钟可用率 |

旧audit表market_session_events/quote_readiness_events/quote_state_events当前均0行；不能因为有这些表名就声称已经记录连续会话/行情。分钟采样不落在cwd或worktree，不增加行情请求，不发送通知，不改变交易权限。

## 昨天（柏林2026-11-05）实际证据

- 285份约5分钟账户快照，166份complete=true、119份不完整。
- 首份00:00:21，末份23:59:10；相邻最大间隔332.017秒。完整率是采样点统计，不是全天可用率。
- 这些快照WITH_QUOTES=0；行情由独立paper-safety订阅owner负责。
- 保存了136条10197错误回调，不等同136次独立冲突；当日也存在非10197行情错误。
- 昨晚23:27:21 Gateway初始化后仍遇10197；Nov6 00:19:44才独立取得新鲜type1行情。不能说除停机时刻外其余Paper全部正常。
- 自动策略全局仍暂停，有限Paper验收是Nov6单独授权并已关闭的三笔，不是昨天自动策略在持续交易。

## Telegram字段定义

不是Python类的继承关系，而是通知类型kind、业务领域scope、具体状态和严重程度几个维度。

| 通知类型（原始代码） | 意义 |
| --- | --- |
| ALERT | 一次独立故障的首次告警 |
| RECOVERY | 该故障取得所需恢复证据后的通知 |
| ESCALATION_* | 同故障严重程度升级 |
| PROTECTION_UNPROTECTED | 同故障内变为无已核验保护覆盖 |
| PROTECTION_PARTIALLY_PROTECTED | 只有部分持仓有已核验保护 |
| PROTECTION_PROTECTION_UNKNOWN | 历史拼接名：PROTECTION_前缀+PROTECTION_UNKNOWN；意思是保护状态待核验，不是保护单已撤销 |
| REMINDER_* | 同故障的后续提醒阶段，不是重新发送原消息 |
| CURRENT_SUMMARY | 上线时一次当前未恢复故障摘要，不重放旧消息 |
| AUTH_EXPECTED_24H/1H | 预计认证窗口提醒，不冒充准确到期 |
| REPORT_BUNDLE / REPORT_SUPPLEMENT | 合并报告 / 当日一次补报 |

保护状态包括PROTECTED、PARTIALLY_PROTECTED、UNPROTECTED、PROTECTION_UNKNOWN，及已确认零敞口后的NO_EXPOSURE。通知显示中文，旧机器名与去重身份仍保留在数据库。

- 原“实例”改称“故障批次”：incident_key+generation。例如paper-safety:protection:NVDA:1表示NVDA保护状态的第1次故障。首次/提醒/状态变化/恢复可属于同一批次。
- “事件编号805”是通知outbox行ID；不是券商订单号，也不是Telegram原生message_id。
- “建议你操作”是建议用户接下来做的事，不是声称用户已经做过。“系统已执行”才是发送方记录的系统动作。
- 小数点后是秒的小数，6位表示微秒分辨率，不保证实际观测准确到微秒。展示改为柏林时间到秒；原始微秒、UTC偏移和网络回执原样保存。
- 每字段间空一行；事件编号固定最后；删除旧固定尾句。大图片caption也保留末行事件编号，不因裁剪丢失身份。
- 本地故障记录持续时间不等同底层停机时长。恢复记录晚关闭不能推导仓位晚平。

### 昨天同类账户采样分组（不是精确停机区间）

| 柏林时间采样范围 | 样本数 | 采样结果 |
| --- | --- | --- |
| 00:00:21–00:40:04 |9|完整账户回读|
| 00:45:16–10:25:59 |117|TimeoutError，不完整|
| 10:30:55–10:36:00 |2|完整账户回读|
| 10:41:18–10:46:26 |2|TimeoutError，不完整|
| 10:47:53–23:59:10 |155|完整账户回读；不代表同期行情或策略正常|

相邻采样之间的状态未直接观测。缺少报价历史的时间不能补标HEALTHY。

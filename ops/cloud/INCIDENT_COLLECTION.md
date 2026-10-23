# 业务事件与SMTP队列（代码已接线，生产未启用）

`collect_incidents.py` 只采集并排队；`alert_email.py` 每次最多消费一条outbox。两者不操作订单、不重启服务、不改变交易权限。

## 数据与来源

沿用runtime/recovery.sqlite3：RecoveryCoordinator拥有观测、恢复任务及operation_attempts；IncidentStore仅管理事件、故障、outbox和采集水位。SMTP复用coordinator的delivery操作接口。既有backup_state.py覆盖此文件；正式数据库备份恢复仍未验收。

- 拒单history：YELLOW/ORDER，保留原事件时间、标的、类型、错误码及已采取行动。无明确订单对账证明不自动恢复。
- module_events：只接health共享registry；HEALTHY/FRESH且120秒内才形成恢复通知。MODULE是诊断对象，不是新增暂停范围。
- order operation_attempts：新UNKNOWN变化生成RED/ACCOUNT；历史UNKNOWN不补发，不重放订单，CONFIRMED也不自动恢复交易权限。STARTED继续由coordinator保持不确定门禁。
- position_protection/history：拒绝、取消、Inactive等保护回报生成RED/SYMBOL；成功提交不把提交前uncovered_qty误当新故障。旧报告无精确账户，归于protection-unverified命名空间，不能被另一来源假定自动恢复。
- position_guard/history：保护缺失/不足/超量/重复生成RED/SYMBOL；账户缺失/不匹配生成RED/ACCOUNT。恢复须为新鲜、同精确Paper账户、显式完整端标记、数量及活动订单证明。新增metadata只服务通知，未改交易门禁。
- cloud-status/Paper快照：缺失、过期、未来时间、无效JSON触发证据异常；服务failed/inactive按实际状态告警。api/strategy inactive且disabled/masked为预期停用。Paper通用失败只称认证或连接未核验，不能凭超时宣称MFA过期；明确身份异常为RED。完整精确账户Paper快照可恢复该通知，但不表示持续连接或交易READY。

保护恢复证据有意保守：部分成交数量、父子/OCA、短仓、未知/旧字段或未到达端标记均不能自动判定保护已恢复。此时保留故障待现有对账链提供证明；不补单、撤单或平仓。完整报告里标的消失也不直接关闭旧保护故障。跨来源缺账户的旧保护告警需人工核对，不能伪造对应关系。

## 事务、历史和失败隔离

- 每个源的水位与对应event/incident/outbox同事务；失败回滚。各源独立，坏拒单日志不会阻断其他源采集。
- JSONL首次只baseline EOF；首次不存在记零，之后新文件可消费；拒单/模块事件每源每次最多100条，拒单每条64KiB；保护报告每源每次最多5条、每条1MiB及500个标的。保护时点倒序不能关闭/重开新故障。
- 日志轮转/截断/重写/删除、恢复序列倒退均报错并保留水位，需要证据接续。尚不自动处理轮转。UNKNOWN操作扫描上限1000，超过上限明确失败。
- Runtime首次baseline；后续新快照或当前新出现的stale/missing症状才生成事件。同一时间戳内容改写、时间倒退拒绝消费。未来/缺失快照不推进时间高水位。配置账户变化使用独立命名空间。
- 同故障合并；YELLOW升RED追加一次升级通知，不能被旧低级告警吞掉。恢复通知按同incident顺序排队。

## SMTP副作用

- 在发送前持久claim STARTED，再通过coordinator.begin_operation预留delivery身份。任何提交间隙崩溃均保守保留STARTED/UNKNOWN，不自动重发。
- STARTTLS验证、15秒socket timeout、固定唯一收件人liuhaitian888@hotmail.com。From及认证仅在进程内读取0600配置，不写入通知载荷、工具输出或日志。
- DATA返回成功且无拒收、SMTP上下文正常结束后才记SENT_ACCEPTED / SMTP_ACCEPTED；不等于Hotmail实收。TLS、认证、DATA、拒收或QUIT异常均保留不确定，等待人工核对。
- 若接受后本地提交失败，仍不能重发；同故障的恢复通知不能越过未决ALERT。存在不确定记录且无其他可发项时返回BLOCKED_UNKNOWN/退出2，避免显示为空队列成功。
- 正文包含Berlin记录时间、源事件时间、级别、标的/类型/错误码、原因/范围、已采取行动、观察到的暂停标记、用户操作、恢复条件及本地故障记录持续秒数。恢复邮件不授予交易权限。
- 旧email-alert-ledger.json原样保留，新worker不重放旧摘要。

## 启动与本批边界

两个入口均默认关闭。运行需对应ARMED标记、批准的runtime/monitoring-deployment.json，核对commit/branch/code_root/state_root、environment=PAPER、monitoring_approved=true、grants_trading_permission=false，并持有各自kernel lock。维护期间还须明确allow_during_maintenance=true。此监控批准文件不能替代交易发布manifest或PAUSED/MAINTENANCE门禁。

新systemd采集unit仅随源码提供，未安装启用；现有邮件unit仍关闭。本批不创建ARMED或监控批准文件、不读SMTP凭据、不发送生产邮件，不部署云代码。隔离完整suite使用临时DB与mock SMTP，真实TCP禁用；不重复此前真实邮件收件测试。

# 业务事件后台接线（未启用）

`collect_incidents.py` 只采集并排队，不发送SMTP、不调用IBKR、不更改交易权限。未增加systemd timer；代码整合不等于启用生产。

数据所有权沿用框架：交易模块继续持有订单事实及风险权限；RecoveryCoordinator持有健康观测/副作用状态；IncidentStore仅向同一runtime/recovery.sqlite3添加事件、故障、outbox及水位表。现有backup_state.py已覆盖此文件，不因此宣称正式备份恢复通过。

已接入：

- `reports/order_rejections/history.jsonl`：YELLOW/ORDER，保留原订单、标的、类型、错误码和已采取行动。首次仅记录EOF；首次缺失时记零水位，之后新建文件正常消费。不假设拒单自然恢复。
- `module_events`：只接受health共享registry中的模块，故障生成模块诊断；HEALTHY且FRESH、观测不超过120秒才形成恢复通知。MODULE仅表示诊断对象，不是新的暂停范围或交易门禁。
- `operation_attempts`：新增或转为UNKNOWN的order操作生成RED/ACCOUNT诊断，禁止重发；后续CONFIRMED不自动恢复通知或权限，需要业务对账证据。首次已有UNKNOWN只保留原始门禁，不重放历史邮件。

安全边界：

- 每源水位与对应事件/incident/outbox同事务；失败回滚；每次最多100条JSONL/模块事件，JSONL每条64KiB。
- JSONL轮转、截断、重写、删除，以及恢复事件序列倒退均失败并保留水位；不自动跳过或扫描历史，需要按来源证据核对接续。现阶段尚无自动轮转接续器。
- UNKNOWN扫描最多1000个order操作；超过上限明确失败，不能静默丢失。STARTED仍由现有coordinator保持不确定门禁，本采集器不推测其发送结果。
- 固定顺序：模块、UNKNOWN、拒单；每源独立提交，后源异常不撤销前源已经成功的采集。没有进程内后台线程，无SMTP和交易网络调用。
- 保护单专用异常、cloud-status/认证分类及SMTP消费尚未接入；现有模块事件只代表其真实已观测内容，不能替代缺失的业务producer。

后续部署前仍需验收启动身份/服务锁、轮转接续，以及保护单/认证等明确数据契约。`INCIDENT_COLLECTION_ARMED`默认不存在，本批不得创建。`EMAIL_ALERTS_ARMED`和email.timer同样不启用。研究/回放/优化不自动修改生产风险参数。

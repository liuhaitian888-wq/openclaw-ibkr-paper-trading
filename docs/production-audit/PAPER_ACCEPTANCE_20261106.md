# 云端有限 Paper 订单闭环验收（2026-11-06）

账户PAPER DUQ503649；云功能代码b3e4eac；同一scope pa-20261106-nvda-v1，NVDA1股、单笔限价<=200USD、最多3笔。旧窗口过期后先确认零历史attempt/未知订单与新鲜账户回读，再续45分钟；未重置ID/预算。此前Live行情竞争10197导致无报价，用户明确退出Live后16:32UTC新鲜type1预检通过。

| 阶段 | UTC发起 / 完成 | 券商结果 | 精确身份 |
| --- | --- | --- | --- |
| 撤单 |16:32:28.629 /16:32:29.554|BUY1限价184.95，CANCELLED，零成交/零NVDA仓|orderId8，permId756941084|
| 买入成交 |16:32:46.299 /16:32:47.107|BUY1，成交188.72，NVDA仓0→1|orderId15，permId756941085，execId0000dc8f.6c030a11.01.01|
| 平测试仓 |16:33:03.741 /16:33:04.161|SELL1，成交188.66，NVDA仓1→0|orderId22，permId756941086，execId0000dc8f.6c030a31.01.01|

17:33:40柏林时间独立只读回读确认：6项原持仓NIO200/PFE8/T3/AAPL17/MSFT13/META100完全一致，NVDA0，无测试挂单；仅原PFE SELL8/STP23.01/GTC/permId911411084/orderRef protect-pfe-20260710010237229135仍PreSubmitted。全球production.json、PAUSED、runtime/MAINTENANCE哈希均不变，未知订单操作0。三笔预算用尽后关闭scope approved=false，不再具有试单权限。未进行Live交易或自动换汇。

证据：云state/observations/paper-acceptance/{preflight,cancel,fill,close}.json、final-acceptance-20261106.json，canonical trading_audit.sqlite3中paper_acceptance_attempts/events与order_requests/events，recovery.sqlite3中operation_attempts。各阶段提交前STARTED，返回后execId/持仓delta/无挂单交叉确认；没有UNKNOWN重试。

用户可见日志：本机.codex/visualizations/2026/11/05/01a1ae27-a046-7772-a9c8-5554aa4dfc85/gateway-review/；Gateway时间线已在VS Code终端打开。终端曾SSH Connection refused，未绕过防火墙；后续独立SSH读取成功，此原因仍未知。没有为检查而重启Gateway。

验收边界：有限执行通路已真实验证，不等于策略风控、正式财务来源、所有保护覆盖和全局生产READY。自动交易仍关闭，自动只读监测/Telegram通知继续。下一步审阅公共通知健康依赖与自动运行前置门禁，不能直接改production.json为ready。

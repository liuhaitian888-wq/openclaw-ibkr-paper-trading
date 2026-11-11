# Gateway一次受控恢复 — 2026-11-11

本次结果：现有 Gateway 自动登录及原采集器的完整 Paper 回读已恢复，watchdog 经独立回读与稳定观察后记录 RECOVERED。交易仍暂停。这不是无人值守卡死恢复、真实2FA提醒或自动交易全链路的验收。

## 授权与部署边界

原生授权来自统筹聊天01a1c257-2703-7653-a2a5-4ab583256cf4的人类回复01a1c932-1bab-7ef0-af31-b1500b2cfd28：允许一次受控恢复 Gateway。已直接读取原问题/回复；必要时仅restart现有ibkr-gateway.service，保留UNKNOWN及PAUSED/MAINTENANCE，不下单、撤单或扩额。唯一发布负责人确认409e255发布完成并冻结云源码/双manifest/服务后才执行。

实际源码409e25512084b16f734704a1aa38ccf19fb5f80e，双manifest同源；沿用原release62c08a2，未加载252b567的新controller/readiness候选。维护入口使用与watchdog相同的内核锁，exclusive保存operation.started.json并原子预留一次STARTED后，只调用已测固定unit的submit_restart。稳定身份gateway-owner-recovery:01a1c932-1bab-7ef0-af31-b1500b2cfd28，不生成第二身份。

## 实际时间线

| UTC / 柏林CET | 真实事实 |
|---|---|
| 06:05 / 07:05附近 | 当前只读GUI仍Restart in progress / Shutdown IA；旧Java2708280:152186235，业务回调缺失；磁盘可用6660829184bytes。 |
| 06:09:47 / 07:09:47 | 唯一实际restart提交，回执RESTART_SUBMITTED_REQUIRES_READBACK；不是业务成功回执。 |
| 06:10:38 / 07:10:38 | 原IBAutomater报告initialized/START_RESULT None，新wrapper3186610、Java3186637:163137691；原Paper进程3094254继续运行。 |
| 06:13:42 / 07:13:42 | 原readback timer自然运行取得REAL_IBKR/READBACK_COMPLETE，正确Paper身份、summary/positions/orders/executions结束标记完整；工作线程、reader与连接均关闭。 |
| 06:13:43以后 / 07:13:43以后 | watchdog正向核验至少60秒，随后RECOVERED/API_RESPONSIVE；06:17验收采样心跳年龄3.096s、dirty=false、四项native end齐。 |

首次入口在第2行stdlib导入时因维护文件名operator.py遮蔽标准operator而拒绝，未进入main、没有STARTED或systemctl。已先对账文件不存在、旧operation仍RECOVERED/原request，随后以python -I完成仅导入预检并执行同一授权身份；不是UNKNOWN重放。原脚本SHA2729bbdb2b5249324136dea419218d0fe73f4180195e738fac8f00da25d0fc0d保留在私有证据。

补充进程断言最初漏查IPv6而失败；没有修改或清理进程。随后只读同时核对tcp/tcp6，4002的IPv6 listener inode归新Java的fd82，位于原systemd cgroup；旧Java已不存在。只有修正后process-binding.json可作为正向证据。after根窗口仍可见Paper登录shell，未据此要求输入密码；就绪结论来自当前进程归属与两路新鲜完整券商证据。

## 完整性与剩余项

- Native与独立回读逐项匹配5持仓、5个活动保护单permId。AAPL/META/MSFT/PFE/T当前数量均有等量SELL STP，PFE原perm911411084保留。当前无NIO持仓事实不被解释成某笔已证明成交或授权操作。
- 现金由原collector持续发布同连接/epoch的EUR/USD新鲜事实，不授予支出权限。本次独立executions返回0且end完整；native保留的3个历史执行不冒充新成交。audit为9个order_requests、3个executions、0个execution_fee_facts；费用历史完整性没有因此补齐。
- 953/1094 UNKNOWN及1270/1271/1272 STARTED原status/payload SHA逐项不变。已消费readonly scope及其payload保持UNKNOWN，未重置预算、换key或手工增加券商连接。恢复只消耗本次一次restart预算。
- 生产manifest、PAUSED、MAINTENANCE、双deployment manifest与recovery policy指纹均与恢复前一致。没有订单/撤单/保护修改，没有新常驻owner。
- Java资源快照从FD828/threads1820/RSS950532KiB降至FD103/threads132/RSS615772KiB；未提高fd限额或关闭无关进程。不代表Java内部卡死根因已永久消除。
- 统筹转交原发布负责人的独立原生验收：原builder自然产生1985补报→group299，06:13:49Z，217075bytes与冻结PNG一致；本owner没有追加发送/重放。该Telegram结果为发布负责人证据，本网关owner未独立下载群图片。
- NATIVE_BROKER_SESSION旧registry为disabled/PAUSED、ACCOUNT等遗留状态影响置顶投影，已交原状态owner核对真实接线；不安装虚假adapter把全链路变绿。行情、费用历史、正式release和自动交易仍分别验收。
- 252b567的持续未就绪/早期手机确认源码修复已离线验证但未部署；真实2FA没有发生，不能标为人工认证通知已实测。依最新人类要求，普通短事件归档，群只维护一条当前链路置顶，由现有publisher统一处理。

## 私有证据与收尾

cloud及Mac均保存state/engineering/gateway-owner-recovery-20261111/，本地不足400KiB，未制造数据库大副本。acceptance.json SHA2567a79d1c7d60fff520cab597c7059c673f4a4cab034ee5293369321cd1505b31d；process-binding.json SHA2560a9019ef9fd9b52a81c42e1c867cdc7d33fd075c504c4c9c6703b60a9359599a。原状态、一次STARTED/submission、前后GUI、独立readback/cash事实与资源记录保留在私有目录，未提交原始账户快照或图片。

一次恢复及证据保存完成后已正式交还source/service freeze，后续发布仍由唯一publisher负责。本次追加只有证据文档，运行源码指纹未改变，沿用252b567的1405项完整离线证据；文档执行diff、OpenSpec、secret扫描与五项目采集。图表无新增actor/edge/owner，已有过期依赖收据保留，未盲目重绘或更新hash。

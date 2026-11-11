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

## 后继问答的实际自动恢复矩阵（11月11日柏林07:40复核）

当前409e255/原release62c08a2，Gateway仍RECOVERED；原native身份/upstream正确、非dirty、四end齐，独立06:39:20UTC回读仍complete。线上没有gateway_readiness模块、watchdog没有observe_readiness导入、旧controller没有early Waiting for2FA phase；252b候选未部署。

**为什么没有更早自动处理：**并非所有监测都没发现异常。原native退避、独立失败、故障卡已有业务异常；缺口在分层分类和升级。systemd只看到进程仍活着，IBAutomater没有正常退出/重启完成事件；watchdog只要看到新鲜的本地API协议握手成功，就走LOCAL_API_RESPONSIVE_UPSTREAM_WAIT并清除suspect，未进入“本地API完全卡死”的15分钟动作规则。该协议握手没有证明nextValidId/账户就绪。已证实的是ShutdownIA期间业务不就绪；Java为什么进入此状态仍UNKNOWN。资源偏高及重启后回落是相关观察，不能据此宣称已找到线程泄漏、FD耗尽或认证失效根因。

| 故障类别 | 当前实际处理 | 限额、条件与验收边界 |
|---|---|---|
| 进程退出/控制器非零退出 | 原systemd可重拉；IBAutomater Exited路径也可重新Start | systemd on-failure/30s，startlimit3次启动/15min；controller内部最多3次、退避30/60/90s，计数在内存，不是统一持久1次/天。未在生产制造退出测试。 |
| 正常原生daily软重启 | 现有IBAutomater负责 | 日重启、周度重新认证不同；旧一次成功不能代表所有跨周/竞争会话已验收。 |
| 本地API完全无响应 | 现有watchdog具备受限自动restart规则 | approved Paper policy、无HOLD/身份冲突/认证要求，同一Java代际与故障持续>=900s；新鲜独立握手明确FALSE、至少两次失败相隔>=60s；24小时只预留一次STARTED，提交前重核代际/服务/HOLD。 |
| 本次“握手成功但业务不就绪” | 现规则不自动restart | 252b部署后先持久提示人工检查，仍不授自动重启此类别的权限；现在连该attention模块也尚未加载。 |
| 2FA、凭据拒绝、既有会话冲突 | 需要分清原生原因，由本人安全认证 | 旧早期等待phase被过滤，周预告/超时提示不等于及时人工通知已验。上游Java还存在有限2FA重试，wrapper重拉可能重新计数；不能说watchdog的1次/24h限制覆盖所有登录尝试。 |
| STARTED/UNKNOWN、身份不符、证据陈旧或预算耗尽 | 不自动重复动作，先对账 | pending未恢复10分钟转OPERATOR_REQUIRED；恢复要新代际、动作后的原native及独立完整Paper/server-time证据，正向观察至少60s。恢复不解除交易门禁。 |

本次人类一次授权身份已消费，不能因后继提问再用一次。watchdog当前24小时额度也已于11月11日06:09:47UTC消耗；这不等于把本次人工授权自动续到明天。原自动policy自身没有单独expires_at字段，新增有期限业务恢复scope需要明确设计并校验，不能宣称已有expiry保护。旧恢复verifier采用verified_since经过60s，后继需补显式缺测窗口重置；252b独立attention verifier已有45s采样gap约束，但未部署，不能混为当前旧verifier能力。

工程纪要提供事实和追踪，不会自动让运行程序执行新行为。只有实际部署检测/策略/权限，并验证相应运行路径，才可承诺覆盖某类故障。新增“业务假活自动恢复”属于需要明确政策边界的后继方案，不是这次问题或252b已授予的能力。

### 最小后继验证顺序（计划，不执行生产故障）

1. 复用原采集owner的业务探针，分别记录进程、TCP/API协议、nextValidId、正确Paper身份、心跳/serverclock、positions/orders/completed/executions end、非dirty；不另开常驻连接。离线复现“握手TRUE、业务未就绪”与短暂上游等待两个不同用例。
2. 代际、时间与expiry：换代/重启/缺测/旧快照/时钟倒退须重置或拒绝判断；先验证heartbeat10s、独立420s、持续900s及采样gap。若新增短期scope，覆盖到期、已消费、预算不足和配置变更；不复用已UNKNOWN身份。
3. 负门回归：正常1100/10197、闭市无tick、延迟行情、手工/外部订单、身份未知、2FA/冲突、HOLD、旧授权、重复owner、STARTED/UNKNOWN都不能被当成可无限重启。保留网络恢复不等于交易许可。
4. 动作与确认：在现有锁内、发送前重核manifest/权限/代际/预算/expiry，持久STARTED；模拟崩溃于预留前、后及提交后，均验证不会重放。服务回执只说明提交，成功必须由新代际和两路动作后完整正确Paper证据确认；任何缺测/新故障重新计稳定期。
5. 资源趋势：有界保留FD/RSS/CPU/threads/child趋势与服务代际，不提高fd限额、不扫描关闭无关fd、不杀peer。只有审阅过的诊断窗口才考虑下次自然故障的有界私密线程证据；本轮不执行或制造卡死。
6. 分开发版：先在隔离组合树测试/扫描持久attention与当前置顶状态接线，再审阅新controller release/早期2FA固定phase；不覆盖62c08a2，不为验通知再重启。真实认证只在自然出现时安全handoff本人，群展示遵守最新单置顶/普通事件归档政策，秘密与验证码不入群或日志。
7. 正式自动动作政策、部署指纹、离线回归、自然真实验收分别记录。当前只提出与验证候选；未批准的新故障类别不得获得restart权，任何恢复也不能获得下单/撤单权限。

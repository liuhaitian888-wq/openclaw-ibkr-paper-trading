# 2026-11-11 日报故障与昨日日期/文件名修复

用户原文确认：昨日报告日10日却展示6日至7日；附件不应为哈希名。调查读取Telegram当前原生群及附件metadata、云队列、冻结manifest、builderjournal、只读SDK阶段与现有Gateway画面；没有重发或重启Gateway。

## 昨日交易日期错误：已修代码/已部署，历史原件保留

实际1778/group256于Nov10 01:00:01Z发布，冻结manifest生成00:59:31Z/source00:59:20Z。旧last_complete_day以纽约20:00切换，冬季恰为北京时间09:00；纯计算精确复现00:59:31Z选Nov6→7，01:00:00Z选Nov9→10。builder缓存只按source时间和render版本，发送端未校验目标交易期间，造成定时点发出旧期间。不是用户把报告日与交易日混淆。

修复bf8d420/actualc457兼容c1f95fa：cache包含period signature，dispatch重算目标期间拒旧period；源快照必须达到该期间纽约20:00完整会话后；HTML/正文分开报告日与纽约交易期间。保留既有NY20规则、真实source时间、账户与新鲜度门禁，不用假新源过关。exactc457组合1375/104.558s全隔离PASS、spec/secretPASS。生产c1f95fa及双manifest已核验；只读用原冻结manifest验证会拒旧Nov6→7并提示等待Nov9→10。未来自然正确日报仍待有效源；旧256未修改/重发。

## 附件哈希显示名：已修上传逻辑

content-addressed冻结路径及SHA是必要内部身份，旧sender却直接拿path.name做Telegram文件名。c457新增由已冻结、哈希校验后的report_type/report_date生成友好显示名；哈希路径/bytes不变。生产read-only report_bytes原1778返回买der_日报_2026-11-10.png/228469bytes，原SHA9fc1d572ce0e6a5f4ddde10a83e3302473659631c1f2153180643f4442df62be保持。昨天原生文件名仍是原样历史，不声称已编辑旧Telegram附件。

## 今日日报：只有缺报告警，未恢复实际报告

1895/group293于Nov11 01:00:00Z仅缺报告警：included_reports=[]、missing_reports=[DAILY]、无PNG/manifest，TELEGRAM_ACCEPTED不等于实际日报成功。09:00附近builderSOURCE_UNVERIFIED：SOURCE_NOT_REAL_IBKR/SOURCE_INCOMPLETE/ACCOUNT_MISMATCH。实际是错误快照AUTH_OR_CONNECTION_REQUIRED/TimeoutError/complete=false，缺source/account，而非证实账户串号。现有备用collector卡nextValidId等待，账户请求尚未发出；primary连接后ready或accounts_ready等待失败，未到正常begin/reconcile。

已证旧版本SQLite锁可使SDK回调退出/重连budget4；c457已加载隔离修复，Nov11一次只读恢复真实失败，ledgerUNKNOWN保留，不换ID重试。当前Gateway2406467/Java2708280及generation2708280:152186235未重启。通过既有X授权纯XGetImage当前画面，Restart in progress主模态显示Shutdown IA...、Cancel灰，后方LogIn；无具体password/2FA提示，不凭此索要密码。既有自动恢复policy只对握手false处理，而此时握手true/业务未ready，未自动重启；网关工程师正补有界人工检查事件，不扩大自动重启权限。

用户原具体不重启Gateway仍适用，统筹已提出一次受控恢复授权，尚无答复，网关工程师为唯一待批准动作owner；通知工程师保持唯一源码/manifest发布。源若真正恢复，沿既有自动SUPPLEMENT一次路径验收正确日期、冻结source/manifest/PNG、friendlyname与原生回执；不手工拿旧图冒充，不重发1895或1094。

今天Paper自动交易/全局Agent目标按另一个聊天原始用户指令接续，但未授权扩大Live/借款/限额或隐式解除PAUSED/MAINTENANCE。P0真实执行owner/final-wire与全链路验收仍未完成，不以这次报告修复称自动交易成功。

证据私有目录：engineering/daily-reconciliation-20261111、paper-storage-recovery-20261111、report-period-fix-20261111、notification-recovery-20261110。新画面未点击/输入/改X权限/复制cookie；没有新增broker连接或scope续期。

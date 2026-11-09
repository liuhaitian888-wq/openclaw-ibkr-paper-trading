# 通知职责与恢复验收（2026-11-10 Europe/Berlin）

用户明确授权完整账户日报继续发deehub，所有成员可看。其他账户、安全、认证、立即风控和互动走owner私聊。普通群帖不能按标签隐藏；应用内标签和公开数据能力独立，native tag/ephemeral及群控制未启用。

| 层次 | 实际证据 | 结论/边界 |
|---|---|---|
| 源码 | 61619c0→657d64d→a46921b；最终修正为旧exhausted无新attempt不审阅、同轮private reviews批量一条 | 已实现，不能代替生产验收 |
| 离线 | linked worktree prescribed wrapper1199/48.123s/OK；6 current specs/active change strictPASS；all-filesgitleaksPASS | 真TCP禁用、临时状态隔离；主工作区仅quick smoke |
| 部署 | cloud a46921b；monitoring与gateway-automater manifests精确匹配；notifications2713304、inbox2710910、Paper2710907active/NRestarts0 | Paper加载657d64d的聚合源码；a469只改supervisor/doc/test，无需再次重载Paper |
| 金融边界 | production.json SHA95ec6bce046991a5fa9f303425f5fa03051b263244cc88541828685d47a43eab；PAUSED/MAINTENANCE、risk controls、两scope指纹及broker exposure均前后相等；9金融操作CONFIRMED/0不确定 | 未增加scope/预算/交易权限；Gateway2406467和OAuth2704281未重启 |
| 实际任务进度 | outbox1371→群message225，server2026-11-09T23:55:08Z（柏林00:55:08）；1372→private269，23:55:07Z | 真实发布结果通知，非测试；已被Telegram接收，不是手机已读/不是risk摘要验收 |
| 逐次审计 | 现场27attempts/27WIRE_START/27ACCEPTED；无重放授权；supervisor通知13条修正前后稳定 | 每次目标/策略/内容/附件指纹、异常类别、原生回执、review关系留私有DB |
| risk | 真实批次1340/1370均7恢复0未解；每标的RECOVERY保留为SUPPRESSED | group risk receipt仍NOT_VERIFIED：旧STARTED1270–1272守卫阻断，不绕过 |
| 日报历史 | Nov8告警980/message156（02:00:06）与实际补报986/message159（02:20:53）；Nov9 1094UNKNOWN无回执且历史PNG已被可变预览覆盖 | 不因搜索无结果或缺DB行判定未发，不补造旧文件、不重放 |
| 日报调度 | 09:00Asia/Shanghai=01:00UTC=全年02:00GMT+1；柏林冬02/夏03。23:01:44Z的PREPARED是柏林00:01:44的准备记录 | 02:00GMT+1契约无需改动；Nov10实际日报尚未到时，冻结附件/备份/投递原生验收等待真实排队 |

Runtime patch fingerprint SHA256 `b0e839a2a9d81beceb65ae669dd8ab70a3b59869adf6b18dcd7cc0b25910239c`：sorted NUL-delimited runtime Python paths/content in git diff71fa3e6..a46921b（不含tests）。文档提交可领先运行源码；cloud source/manifest仍a46921b，不因文档收尾重载业务。

## 漂移核查

只读原生admin-log event1274032372628：2026-11-09T23:34:38Z（柏林00:34:38）description从e0c2520c5a8ca760a78174439b88abbce41dd28e6eaf9924b18c1707c92aaa7f改成f10aedbe12f0e4d8d2b4a4dfdab4ccf06da2ac9839a3d61f617e177fff5facf3；actor匹配owner账户。admin log不记录具体编辑客户端，无法据此断言实际操作者/软件；本轮未覆盖新简介、改名或提升权限。原名称/清空简介的历史也保留同样归因限制。

## 发布中的问题与修复

原生简介hash校验拒绝后，shell展示命令覆盖退出状态，曾过早启动三个unit；精确identity guard拦住旧manifest。立即停下、核验锁释放、重做原生证明并同步两manifest后启动。首轮supervisor错误将8个旧NOT_SENT_EXHAUSTED也逐条私聊（含5个真正不确定项共13条），已停止owner修正并通过1199全套后发布a469；已发历史/原生回执保留，未删除、未称测试。Paper初次加载记录一次OperationalError，后自行恢复四end/新鲜回调；具体原因未建立，不归咎Gateway。

## 持久交接与未完成项

秘书可用engineering_updates读取agent_secretary.sqlite3中的proposal `engineering-notification-recovery:task:20261110` 及SYSTEM状态 `engineering-notification-recovery:task:20261110:a46921b`，区分用户授权、工程动作、模型建议和未验收；不是聊天ACK。详情原生/离线/部署日志：`~/.local/state/openclaw/engineering/notification-recovery-20261110/`；独立risk复核见RISK_RECOVERY_20261110.md及notification-1270-peer-review.json。

仍缺：1094/953及1270–1272可靠结果证据；不能自动补发risk1340/1370。真实新日报冻结PNG/manifest、备份和发送、未来明确未发送后的受控retry双路回执仍待真实事件，禁止制造故障/测试群消息。native标签/临时消息、完整公开财报正文研究不因本次状态卡升级成已验收。

回退先保留所有新审计表/冻结字节；若必须退回旧sender，不恢复旧宽泛自动群路由，使用旧固定公开模板边界（automatic_updates_to_group=false），保留已授权完整日报群投递和private身份核验；不清未知、重放或解除金融门禁。源库快照20261109T234709.896409Z在同机backups，跨库非原子、异地灾备未证明。

既有维护/宽筛图不描绘此通知路径；保留先前PRODUCTION/paper_safety_watch依赖收据REVIEW_REQUIRED。其他聊天新增工具拓扑由其任务独立维护，不覆盖其图表/收据、不用文件指纹匹配冒充语义验证。

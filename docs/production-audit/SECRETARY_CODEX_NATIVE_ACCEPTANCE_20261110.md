# 秘书 → Hetzner Codex 执行器：真实验收

2026-11-10，柏林03:17:14至03:17:31（UTC02:17:14至02:17:31），约17秒完成。此为实际Telegram交办、实际原生Codex执行与实际私聊结果，不是归档ACK或离线测试。

| 阶段 | 实证 |
|---|---|
| 部署 | Cloudc3443a25d8a01d96b462aab0d490c48b6a298378，monitoring/gateway双manifest一致；唯一通知2763643、inbox2763644、OAuth2763645active；Gateway2406467未重启 |
| 入站 | 原生owner私聊精确/codex dbcheck，owner侧消息1980，BotAPI侧消息410/update600875513；USER/CONTROL_INSTRUCTION，身份门禁核对非bot/转发/编辑/群 |
| 授权 | registered-db-diagnostic-v1 / hetzner_codex_appserver，版本dbcheck-20261110-v1，一小时/最多1任务，不交易、不部署；已消费，不更换版本重放 |
| 原生执行 | thread01a1c33e-d3a0-75f1-afd9-4511cda7a850；turn01a1c33e-dc38-7db2-bb72-75a9cf7937e9；THREAD_CREATED→TURN_ACCEPTED→TURN_COMPLETED |
| 本地任务 | engineering:e2df2e1d68a3e201b2046a842a113776c11aa1423fffbb731aed95c11d9ff2b7 / SUCCEEDED |
| 工件 | engineering/codex-executor/e2df2e1d68a3e201b2046a842a113776c11aa1423fffbb731aed95c11d9ff2b7/report.json；12458bytes/0600；SHA256d66e75e6b4c0dd1105390266c4e6236e42b836f704566a5faedf8b7e96414b5e，云/本机重新计算一致 |
| 回传 | 唯一worker：接单1833→private412/02:17:19Z；完成1834→private413/02:17:31Z，均TELEGRAM_ACCEPTED、CONTROL/requires_response；owner原生会话另读到消息1983实际完成正文 |

私聊消息编号在owner和bot账户视角不同；按文本、时间、精确sender/recipient及任务指纹关联，不错误要求1983=413。

实际查询覆盖交易审计85表、财务账本5表、监控通知35表、秘书档案27表，共152表；结构与表数查询均成功。财务observations时间探针较旧，不能称整个库停更；监控两个新鲜度探针TIME_BUDGET_OR_LOCK，保留UNKNOWN，不能臆断数据库损坏或确认锁根因。模型报告保留无跨库原子一致性、未做完整性扫描/券商请求的边界。

## 已完成与仍未完成

已验证这一个固定只读诊断任务：Telegram→Hetzner秘书→同OAuthowner串行官方CodexAppServer→真实登记数据库证据→报告→现有通知owner→原生私聊。Mac不是这次执行依赖。原生用户会话仅用于本次用户授权的交办与验收，不是常驻执行器或新sender。

未宣称任意开发改代码、测试、运维写操作、生产发布均已自动化；后续需要各自受限工具、scope和验收。HostedCodexCloud不是这次执行器，旧无ID请求仍UNKNOWN，未重提。9日日报1094仍UNKNOWN未重发。数据库随时可访问是云端能力目标，不等于锁/超时/停机永不存在。

测试证据：桥接父最终1322/100.782s及echo1322/111.031s；实际部署组合1318/98.221s完整离线、秘密/规格校验通过；原生预检有效配置gpt-6.1-sol/low/never/readOnly/networkAccessfalse。本文记录验收，不因文档SHA领先而重新部署。后续P0/全生命周期通知/报表来源sidecar留WaveB。

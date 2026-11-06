# Agent 秘书档案、数据库与监测验收

核查日期：2026-11-06，时区 Europe/Berlin。

## 当前实际数据库

云端固定 state root `/home/ibkr/.local/state/openclaw`：

| 路径 | 体积（核查时） | 用途 |
|---|---:|---|
| trading_audit.sqlite3 | 1,861,767,168 bytes | 券商回调、交易审计、持仓/订单与历史请求；并非完整策略收益证明 |
| financial_ledger.sqlite3 | 126,976 bytes | 财务账本；缺失历史不能填零，也不能假定已完成 Flex 对账 |
| runtime/recovery.sqlite3 | 39,960,576 bytes | 监控状态、故障事件、恢复记录、通知 outbox/回执、心跳 ACK |
| agent_secretary.sqlite3 | 尚未创建生产实例 | 本轮新增档案模块的预定独立库；不把代码存在算作聊天上线 |

baseline-backups、session-recovery、migration-evidence、monitoring-tests 下还有备份/验收库，不是另一组生产 owner，不删除。

## 外部心跳验收

- 60 秒发送一次；外部 Period=60 秒、Grace=60 秒。从最后一次被接收的心跳算约 120 秒后才判失联，调度/通知传输另计。不是瞬时告警。
- host 检查读取本机资源样本（允许 600 秒内样本、磁盘剩余至少 20%）；采样器本身约五分钟一次，因此不能声称采样器故障也总在 120 秒发现。
- Paper API 检查读取现有唯一 safety owner 的身份/连接/回读证据，不新建券商连接。
- 2026-11-06 23:42:59 停止心跳 timer/service，先安排 190 秒后的 systemd 自动恢复；未关机、未停止 Gateway。
- Healthchecks 23:44 Down、23:46 Up；host 页面记录本次 Down 窗口 1 分 17 秒，与人为停止发送时长不是同一指标。
- Telegram integration 显示 Delivered；用户明确确认 der 群故障与恢复均看到。
- 停止共用发送器令两个外部检查同时失联，不能据此宣称真实 API 同时断开；也不能算真实云断电演练。
- 应用 Telegram 提供具体故障，云外 Healthchecks 在本机无法发送时兜底。外部服务与 Telegram 仍有共同依赖，不能承诺绝无漏报。

## Secretary 档案边界

用户确认使用 der 群，仅接收 owner 的指令。档案区分 USER / MODEL / TOOL / SYSTEM，按实际消息 occurrence 去重，不按相同文字去重。保存公开的分析摘要、依据、用户指示、策略版本、模型 ID、工具调用及回测/费用假设结果；不声称保存模型私有思维过程。

`reporting/agent_secretary.py` 提供独立 SQLite 档案与有持久状态的模型运行预留；STARTED/UNKNOWN 不自动重放。此模块尚未接通 Telegram 收消息、模型登录、查询工具或回测引擎，不能称“秘书上线”。生产实例必须由审核后的单 owner 创建。

用户说明此前使用 OAuth，后明确要求不再查找旧 OpenClaw。后续使用独立的正式 OAuth 接入；不复制桌面 token。官方支持的 Codex app-server OAuth 接入参考：
https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server

## 费用核查与数学口径

当前佣金回调和报表聚合存在；`scripts/build_strategy_extension_status.py` 明确将 commission_aware_filter 标为 roadmap。没有查到完整回测费用模型或 LEAN 费用源码已融合的证据。

参考而非已经安装/融合的项目：QuantConnect/LEAN `Common/Orders/Fees/InteractiveBrokersFeeModel.cs`：
https://github.com/QuantConnect/Lean/blob/master/Common/Orders/Fees/InteractiveBrokersFeeModel.cs

权威费率及生效规则以 IBKR 官方为准：
https://www.interactivebrokers.com/en/pricing/commissions-stocks.php

普通美股整股订单的基础佣金示意（不是覆盖全部账户/交易方式的已上线模型）：

`C_base = min(max(abs(Q) * r, C_min), abs(Q) * P * cap)`

`C_est = C_base + exchange + clearing + regulatory + pass_through - rebates`

`PnL_net_model = reference_sale_proceeds - reference_purchase_cost - C_buy - C_sell - slippage - FX_cost - financing - borrow_cost`

若使用实际成交现金流，成交价已包含滑点影响，不再重复减去滑点。

适用项必须按账户 Fixed/Tiered、标的/市场、路由、买卖方向、交易日期、月累计量及收费粒度配置；Fixed 已包含的项目不能重复相加。分拆成交不能把每笔 fill 错当每张 order 重复收最低佣金。分数股、DRIP、期权、期货、外汇另有规则，不套整股公式。缺费率/币种/路由时应标记 INCOMPLETE，不默认零。

实现时金额使用 Decimal，费率版本/来源/生效区间与取整规则持久化；估算与实际 commissionReport / Flex 分开保存并对账。当前不能声称所有费用已精确实现，也不能只靠第三方默认值代替账户收费方案。

## 第二次真实 Gateway / API 验收

- 23:50:19 停止 Gateway；事先安排90秒后启动同一个systemd服务。
- 23:50:23 API故障通知Telegram接受。
- Gateway按时启动后，原monitor owner等待已有连接退避期；未改写预算、未伪造健康状态。
- 23:54:13 API完整回读恢复通知Telegram接受；停机操作至通知约234秒。
- 23:54:20 PFE、23:54:22 BAC行情竞争恢复通知Telegram接受；KO也进入发送队列。
- 用户确认“API和行情恢复都看到”。这是原有竞争故障在新实时报价到达后恢复，不是另开竞争会话制造新的10197实验。
- 交易门禁哈希及持仓均与实验前一致，UNKNOWN/STARTED订单操作为0。
- 行情竞争解除与策略是否可用分离：当前新鲜度、K线、交易日历及全部交易门禁仍独立生效。不可将此称为策略交易READY。
- 本轮完整离线测试816项通过，gitleaks通过。代码dev ea83c13 / main及云端11618a5；后续文档提交不改运行逻辑。

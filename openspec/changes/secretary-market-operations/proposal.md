# Proposal

## Why
秘书需要主动解释交易时段、发现工程与策略问题，并把每周反思变成可执行的 Codex 提示。交易日历必须绑定实际交易场所，不能把休市当作 API 故障，也不能把研究建议当作交易授权。

## What Changes
- 交易日历提醒：美国市场分时段与 EQQQ 米兰 ETFplus，休市原因、提前收市、下一开市及夏令时转换。
- 私人周报生成可复制 Codex prompt，复用通知 outbox 与现有工程提案归档。
- 形成有来源的风控分类与价值投资研究章程，区分系统保障、策略限额和信息提醒。
- 核实官方 Codex 接入方式，先提供可审计工程交接，未验收的自动唤醒不得宣称已接通。

## Capabilities

### New Capabilities
- `market-session-awareness`: 按场所生成有有效期的交易时段与休市提示。
- `secretary-engineering-review`: 周度工程提示与主动研究交接。

### Modified Capabilities
无。

## Impact
reporting、通知生产者、定时运行配置、秘书研究提示、工程文档。没有 broker 写入权限扩张；不解除 PAUSED、MAINTENANCE 或未完成的 P0 验收。

## Owner clarification — 2026-11-10
Extend this existing secretary change with bounded model-selected Python broker queries and all registered business database read access. Minimize measured Telegram-to-result latency by reusing existing connection and delivery owners. This is a target clarification, not runtime acceptance or write permission. OAuth remains the selected model route; the API-key migration is historical preparation.

Owner active-goal clarification: Telegram shall orchestrate the complete authorized development/operations paths through Python, IB Gateway/IBKR, Codex Cloud and all business databases. Codex Cloud is an execution branch, not a broker transport hop. Current verified executor connectivity, allowed operations and write/deployment scope remain UNKNOWN until implementation and receipts; this maintenance deploys none of them.


## Automatic notification clarification — planning only, 2026-11-10
The owner reiterated that all automatic messages belong in deehub and must be combined; secretary private chat is for interaction. Extend this existing change with a planned lifecycle policy covering ALERT, escalation and RECOVERY, shared-cause grouping, bounded reminders and stable recovery, without an automatic private detail mirror. Sensitive source evidence stays in the database and is retrieved through verified private interaction; fixed safe summaries are used in the group. This planning clarification does not implement or deploy the policy, resolve legacy uncertain delivery, or authorize service actions.


## Current publication override — 2026-11-11
Human source 01a1c257-2703-7653-a2a5-4ab583256cf4 / 01a1c869-090b-7b62-8bb4-7c8850b54d4c supersedes the Nov10 all-automatic group broadcast policy. publication-v2 archives ordinary incidents, short progress, calendar/filing notices and missing-report placeholders without a push. The group receives actual report account artifacts and archived completed research conclusions, plus one fixed current-link status card explicitly authorized for pinning. Native rapid interaction and genuinely current human-action requirements remain owner-private. Historical grouped-v1 design and receipts remain historical, not the current delivery instruction. No trading permission follows.

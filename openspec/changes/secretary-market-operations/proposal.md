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

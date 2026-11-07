# 上游仓库统一清单

机器可读清单：`UPSTREAM_REPOSITORIES.json`。包括项目可追溯文件、本轮与前一会话研究记录；不声称包含不可见聊天历史。GitHub元数据核查日期2026-11-07。

| 仓库 | 状态 | GitHub许可证字段 | 已审查固定commit |
|---|---|---|---|
| [IbcAlpha/IBC](https://github.com/IbcAlpha/IBC) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | GPL-3.0 | fc6d917d56715ebf79a39a10b5d77fd7b701d992 |
| [QuantConnect/IBAutomater](https://github.com/QuantConnect/IBAutomater) | DEPLOYED_SOURCE_ADAPTATION | Apache-2.0 | 5751a0a9baef74a47515b8ce96a39308563d11d4 |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | Apache-2.0 | 17702a6ae438a17495b9dea75b6db2857292d892 |
| [QuantConnect/Lean.Brokerages.InteractiveBrokers](https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | Apache-2.0 | 17702a6ae438a17495b9dea75b6db2857292d892 |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | Apache-2.0 | 9fa1196fffbcfd9de5146d2dd2869df84ab99838 |
| [csingley/ibflex](https://github.com/csingley/ibflex) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | bfde7a8c088643fbad8798d6fc5c0b896e9edcb4 |
| [healthchecks/healthchecks](https://github.com/healthchecks/healthchecks) | HOSTED_SERVICE_NOT_SELF_HOSTED | BSD-3-Clause | 5b9a198bca9dc959326f6492e460166373530499 |
| [ib-api-reloaded/ib_async](https://github.com/ib-api-reloaded/ib_async) | DEPLOYED_PACKAGE | BSD-2-Clause | ab629f34c1823ea4c1542f32f07377208a86bdfd |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | 未固定 |
| [microsoft/agent-framework](https://github.com/microsoft/agent-framework) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | 未固定 |
| [microsoft/autogen](https://github.com/microsoft/autogen) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | CC-BY-4.0 | 未固定 |
| [openai/codex](https://github.com/openai/codex) | OFFICIAL_CLI_INSTALLED | Apache-2.0 | 未固定 |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | 未固定 |
| [osauer/canary](https://github.com/osauer/canary) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | e5fc3b9aa73690957dfc165fc319fbc038a7e2ea |
| [python-telegram-bot/python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | DEPLOYED_PACKAGE | GPL-3.0 | 8dec234225145f8ec0cc8fd97d42208a32d8f0e6 |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | REFERENCE_OR_CANDIDATE_NOT_INTEGRATED | MIT | 未固定 |

pushed_at只说明上游更新，并非兼容性或安全通过。NOASSERTION/空许可证需要读具体文件，不等于可任意复制。实际复用时保留版权、LICENSE和适用NOTICE；包依赖、托管服务、源码修改与研究候选分别记录。

更新流程：比较已审查版本与上游固定commit → 来源/许可证审查 → 接口与副作用评估 → linked worktree完整离线测试 → gitleaks → Git部署。禁止自动追main覆盖生产。

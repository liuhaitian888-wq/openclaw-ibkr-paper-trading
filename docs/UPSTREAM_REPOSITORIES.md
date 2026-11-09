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

2026-11-07通知设计新增参考（README核查，未复制源码、未安装、未完成许可证源码审计）：

- [JeffPu/ibkr-dashboard](https://github.com/JeffPu/ibkr-dashboard)
- [TrishkaV/PortfolioHelper](https://github.com/TrishkaV/PortfolioHelper)
- [promobase/ibkr-web-api](https://github.com/promobase/ibkr-web-api)
- [caronc/apprise](https://github.com/caronc/apprise)

Nov8按需群搜索参考：

- [Telethon当前维护源](https://codeberg.org/Lonami/Telethon)，可选adapter，未登录验收。
- [Telethon旧GitHub](https://github.com/LonamiWebs/Telethon)，已归档并声明迁移。
- [TDLib](https://github.com/tdlib/td)，官方库参考，未安装集成。

Nov9包许可证补核：实际使用的python-telegram-bot22.8，发布者[包元数据](https://pypi.org/project/python-telegram-bot/22.8/)声明LGPL-3.0-only；[官方pyproject](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/pyproject.toml)一致。上表GPL-3.0是Nov7 GitHub聚合许可证字段旧快照，不能据此把整个22.8包当成GPL或忽略LGPL义务。机器清单新增package_license_verification，保留原始历史字段，未替换包或改变运行权限。其他包、嵌入文件、NOTICE与分发形式仍须分别审查。

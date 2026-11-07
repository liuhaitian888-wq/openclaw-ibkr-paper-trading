# 交易情报系统：实际能力与来源边界

用户于2026-11-07授权五类情报：新闻、财报/SEC、宏观、行情异动、持仓风险；Telegram通知、事实/推测区分及参考来源归档。运行时进度也需可见。

## 接线

`ibkr-intelligence.timer`每10分钟（另0–20秒随机延迟）启动有限oneshot；`ibkr-intelligence-broker.timer`每15分钟（另0–20秒）调用既有ib_async新闻适配器。二者分别有内核锁；后者复用原news probe锁/非零client ID，顺序读取并总限时150秒，不申请价格订阅、快照或订单。不是逐笔或秒级新闻流。systemd180秒停机边界，所有HTTP/SQLite/子进程/IB连接有owner和关闭范围。禁止从worktree运行常驻生产服务。

归档：独立秘书库INTELLIGENCE_RECORD，保留provider/entity/publication/retrieval/content hash/source URL；内容修订有不同指纹，不覆盖旧版本。原文标题/披露元数据与模型摘要分别记TOOL/MODEL。归档与outbox之间以确定性唯一键补队列，不重放HTTP UNKNOWN。首次启用前的历史不群发；只对启用后且30分钟内的真实来源事件提醒。首轮没有新事件时静默是正常，不伪造行情或新闻。

新情报每小时最多生成一个研究任务，仍受秘书整体模型任务上限约束。模型以公开证据交叉验证，事实关联不能改写成因果。公开进度仅“任务领取、首个只读工具状态、最终结果”，不保存或传播模型私有思维。

## 来源矩阵

| 来源/类别 | 实际接口与限制 |
|---|---|
| Federal Reserve | 官方Monetary Policy RSS，HTTP8秒/2MB上限；保留发布时间，非价格因果证明 |
| BLS CPI/Employment | 官方RSS；403、超时、空结果分别记录，不冒充实时可用 |
| SEC EDGAR | 用用户指定的私有联系邮箱声明User-Agent；公司ticker/CIK官方映射 + submissions最新100行元数据，关注8-K/10-Q/10-K/4/6-K/20-F及修订。原始acceptance时间与filing date分开；2.02仅“可能业绩相关”。未提取/验证营收、EPS、指引，也没有分析师预期或完整财报日历 |
| IBKR新闻 | 已审查的trading/news_feed.py；精确Paper账户、最多12个已批准持仓/观察标的、每provider最多3条历史标题/一次正文收取校验。正文仅留hash/长度，不再分发全文。不代表全部provider/实时streaming或Reuters权限 |
| 持仓关联 | 只读取既有Paper owner的完整、新鲜、非dirty、正确身份状态；零仓位不当持仓。手工/外部仓位也计入。不创建第二持仓采集器 |
| 行情异动 | 仅使用已由现有owner收到的真实bid/ask，5秒内、同epoch、两次采样间隔不超过20分钟，初始中点变动阈值2%。明确“采样变化”，不是日收益。无成交量异常证明；Nasdaq指数未新增订阅 |
| Reuters/Bloomberg/Benzinga/The Fly/Stock Titan/Newsquawk | 保存官方入口，尚无已验证云端API许可；不购买高价订阅、不把网页等同插件或可持续API |
| Similarweb | 插件目录核实installed=true；截图为试用设置引导。在本聊天尚无可调用的数据工具，云端未配置Similarweb API。安装不等于数据或自动监控已验收 |
| Gmail/Outlook/ChatGPT插件 | 当前聊天的连接能力不能自动移植到云端。没有转移插件OAuth令牌，也未开启不受限邮箱扫描 |

健康状态遵守共享registry：INTELLIGENCE_PUBLIC与INTELLIGENCE_BROKER逐源报告实际成功/缺失，网络恢复不自动证明数据、交易或订阅许可。

## 配置与验收

私有`.config/openclaw/intelligence.json`包含SEC技术联系邮箱、类别、明确观察标的；不提交邮箱或credentials到Git。独立`runtime/intelligence-policy.json`须approved=true、grants_trading_permission=false，记录启用时间。原有PAUSED/MAINTENANCE、策略批准及已用3/3测试额度不变。

完整测试在linked worktree：`python scripts/run_worktree_tests.py`。包含发布时间/时区、SEC表单、恶意DTD/URL、冷启动不刷屏、修订指纹、通知去重、手工仓位、原生报价新鲜度和公开进度。生产仅quick smoke及有限真实来源请求；不重复旧故障演练。真实来源验收逐项记录，不把单一成功当全部上线。

参考仓库统一入口：`REPOSITORIES.md` → `docs/UPSTREAM_REPOSITORIES.md` / JSON。更新只生成差异/评估，不自动pull或替换生产。

官方依据：
- https://www.sec.gov/about/webmaster-frequently-asked-questions
- https://www.federalreserve.gov/feeds/feeds.htm
- https://www.bls.gov/feed/
- https://www.interactivebrokers.com/docs/tws-api/doc/news/providers

## 2026-11-07实源收尾

Fed全新闻官方RSS云端HTTP200、20项；配置fed_all_releases=true后替换仅Monetary分类，官方轮询改2分钟+0–20秒，仍非实时stream。BLS CPI/就业RSS403保留，不通过替代源伪造恢复；官方api.bls.gov v1无需注册的GET已返回CPI月度数据。新增两个固定序列CUUR0000SA0/CES0000000001，每6小时最多各一次尝试（含失败缓存），按25/day官方未注册额度设计为8/day。记录周期、数值、单位、脚注和修订指纹；published_at=null，不能生成发布时点提醒/预期差结论。缓存和RSS不可用分别显示。

StockTitan官方FAQ明确没有public API，故保留网页入口，不安装猜测接口。Reuters/Bloomberg/Benzinga/TheFly/Newsquawk仍无云端API/订阅验证，不能统一说“未订阅”；IBKR每symbol原生结果仍为准。SEC7家公司读取通过，QQQ不在现有company-ticker映射，不猜测CIK。

Similarweb账号订阅页为Competitive Intelligence After Trial，未来账单“没有即将到来的账单”，历史1个月，未录入付款信息/启用付费。账户页未提供营销偏好开关；本次未选可选营销，不能声称平台电话/邮件已全局屏蔽。如实际收到营销，可通过该消息的退订入口再处理。浏览器免费版能力不等于云端API。

秘书首次新闻scope任务模型运行成功但配置未完成，未改写成成功配置；新的补充证据任务news-scope-with-evidence-v2已实际调用research_universe选择NVDA并保存来源/待证伪理由和落盘回执。现有6持仓优先覆盖不变。

BLS CPI实源含2025年10月缺失占位`value="-"`及官方拨款中断脚注。解析器保留为UNAVAILABLE周期记录，其他有效月份正常接入；不把整条CPI源判成失败，也不把缺失补为零。实源验收曾暴露此缺口，修复后重新有限读取验收，六小时正常缓存不变。

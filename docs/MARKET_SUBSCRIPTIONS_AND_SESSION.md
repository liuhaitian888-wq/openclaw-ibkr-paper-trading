# 行情订阅、六层来源与会话通知

日期：2026-11-08。用户本轮第1–5项的设计和验收记录；手机云文档仅研究。

## 核心问题与六层来源

> 当行情额度有限时，怎样从大量股票中找到机会，同时把实时行情留给最需要盯住的股票。

六层是候选状态管理；订阅调度是资源分配；二者相关但独立。总名单不等于必须同时请求全部报价。没有实时行情的股票可以关注，不能因此让需要实时价格的策略通过。

本次检索没有找到与本仓库六个canonical层名及全部迁移规则完全相同的上游方案，不能证明不存在，也不把通用分层筛选宣称为本项目首创。[QuantConnect/LEAN UniverseSelection源码](https://github.com/QuantConnect/Lean/blob/master/Engine/DataFeeds/UniverseSelection.cs)管理股票池变化、订阅与持仓相关资源；[官方Universe说明](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/key-concepts)描述筛选后订阅入选股票。可以借鉴筛选与订阅分离、对持仓保持数据需求，不能说安装LEAN就消除了IBKR线路限制。LEAN在本项目为已研究参考，未部署其完整引擎。

## 2026-11-08 总名单接线修正

上一版/universe只读运行候选表，显示3条而未接入13,024条旧证券主档。本轮改接官方目录维护的完整参考总名单，支持ABC网络、证券类型、关键词和待核验权限筛选。详见[根因与LEAN原理](ABC_SECURITY_MASTER.md)。目录归类不授予实时权限或策略资格。

## 套餐声明、标的覆盖与实际观测

复用agent_secretary.sqlite3，新增market_subscription_registry（套餐当前声明）、market_watchlist（私人关注）与market_subscription_checks（每6小时抽样结果），原始owner声明保存在secretary_events。仍是既有秘书数据库，既有备份/只读schema/query可读取，无新增数据库服务。

登记字段：package、environment、realtime、paper_shared、symbols、active，以及系统保存的来源指令和时间。当前按明确列出的股票关联；不根据套餐名称、交易路由SMART或上市交易所猜测权限。真实订阅通常按交易所/网络/产品范围授权，进一步自动覆盖映射需要正式维护的合约与套餐覆盖表；目前是显式逐股关联版本，不冒充完整自动映射。

- OWNER_REALTIME：本人声明可用于Paper的实时覆盖；不是官方订阅回读认证。
- OWNER_NON_REALTIME：本人声明可用于Paper的非实时覆盖。
- UNREGISTERED：没有适用于该股票／Paper环境的有效声明，不等于一定没有订阅。
- 实际状态独立显示：REALTIME_HEALTHY＝实时且新鲜，REALTIME_STALE＝实时报价已陈旧，DELAYED＝延迟，FROZEN＝冻结，PERMISSION_DENIED＝明确权限拒绝，SESSION_CONFLICT＝会话竞争，UNKNOWN＝证据不足。缺证据或owner心跳过期不报健康。
- 套餐仅LIVE且未声明paper_shared时不应用于Paper。非实时股票保留关注，不自动申请付费snapshot，不购买订阅。

秘书私人菜单：

| 命令 | 功能 |
| --- | --- |
| `/marketdata` | 查看订阅登记表及填写模板 |
| `/market_register JSON` | 登记或更新同名套餐；active=false停用，历史指令保留 |
| `/watch AAPL` | 加入私人关注；不改canonical选股资格 |
| `/universe` | 总名单与关注名单，逐股显示订阅声明及实际报价状态 |
| `/eligible` | canonical已进入合格及更高层的股票，显示资格记录时间；不是刚刚重验资格 |
| `/market_check` | 立即读取已有行情证据做抽查，不增加行情请求 |

名单每页最多20项，末尾给下一页命令。缺表／缺记录如实返回，不造一个“合格”股票池。注册从原生owner控制路径进入Python，不让模型凭分析修改套餐声明。模型继续通过既有schema/query只读接口查询这些登记表，不增加可写工具。

复用现有秘书inbox owner每分钟观察，由持久时间槽限制为每6小时轮换抽查最多10个已声明覆盖或已有监测的股票。抽查只看安全owner已有证据，不验证从未订阅股票的真实权限；不能替代主动订阅验收。明确权限错误且来源心跳新鲜时提示owner核对或登记套餐，每天同一错误集合／登记版本去重；会话竞争不当作没买套餐，休市陈旧也不当作权限拒绝。本轮用户回忆A/B/C后，在旧[项目简介](YUGE_AUTONOMOUS_TRADING_BRIEF.md)找到“已订阅并验证”的Network A/CTA、Network B、Network C/UTP。按历史来源登记这三项，标为HISTORICAL_RECHECK_REQUIRED，Paper共享为未知；不是本次券商回读，不据此宣称当前全市场实时权限。

## 登录／会话接口审计

查阅日期2026-11-08；没有查询Live账户、发起登录或制造冲突。

| 组件／目标 | 官方能力与当前代码 | 本轮只读核验与限制 | 下一步 |
| --- | --- | --- | --- |
| [QuantConnect IBAutomater](https://github.com/QuantConnect/IBAutomater) 生命周期事件 | OutputDataReceived、Restarted、Exited；已部署的本地controller输出固定脱敏阶段 | 已读本地固定上游与云journal；controller是Paper限定；不是手机/Live会话身份接口 | 复用现有journal，不叠加登录owner |
| [ib_async API](https://ib-api-reloaded.github.io/ib_async/api.html) | connectedEvent、disconnectedEvent、errorEvent；项目已用相关适配器 | API连接事件不能单独证明GUI登录或手机被挤下线，本轮未新建API连接 | 保留现有安全owner的身份与完整回读核验 |
| [IBC配置](https://raw.githubusercontent.com/IbcAlpha/IBC/master/resources/config.ini) | ExistingSessionDetectedAction含会话冲突处理模式 | 仅参考，未安装；本项目不是IBC控制器 | 不为通知替换现有Gateway控制器 |
| Telegram既有通知owner | 已有durable outbox与私人认证类别 | 配置原地使用，不输出token；首次基线不补发旧journal | 新事件排队并回读实际原生回执；无新事件时保持待验收 |

**关键发现：本地固定IBAutomater Java遇“Existing session detected”选择Exit Application／Cancel；本次不能声称它主动抢占了你的Live。** 云今天确有退出和重新初始化记录，但没有证据把它们与本次手机提示对应，也不知道提示所称另一会话的身份。

本次新增reporting/gateway_session_events.py，由既有秘书inbox owner每分钟读取固定ibkr-gateway.service的journal。首次仅保存游标，之后按原生cursor区别独立事件；游标与outbox同一事务提交。历史不重放，STARTED/UNKNOWN仍按既有规则对账。journal无权限／游标失效／有界批次超限返回错误，保留原游标，不静默跳过。

可通知的阶段：检测已有会话、Gateway退出、初始化／软重启完成、需要人工检查。初始化不等于认证或行情恢复；只有本次初始化之后的新鲜正确Paper身份与完整账户／订单／成交回读，才另发账户回读核验消息。既有行情竞争及恢复通知继续负责实际行情证据；没有新增重启、抢占Live或账户登录行为。

覆盖限制：只能观察当前controller真实输出的阶段，不能保证每个手机提示都有一条可对应的服务端事件。当前service日志若未产生相应事件，就不能主动编造“云端已恢复登录”。

## 手机只读入口：下一步研究

可比较三个方向：

1. 复用现有私人Telegram Mini App，增加只读名单与订阅页。能复用owner认证和当前云主机，更新更接近数据库；仍需独立页面与接口验收。
2. 私人Google Sheets作为脱敏投影，适合手机点链接看表。需明确账号授权、刷新延迟、分享对象及免费配额；不使用“发布到互联网”，不把表当交易权威库。官方[分享权限说明](https://support.google.com/drive/answer/2494822)。
3. 自托管数据库表格界面：可研究[NocoDB自托管](https://www.nocodb.com/docs/self-hosting/installation/community-methods)，但增加服务、备份、升级和访问控制成本，不能仅因软件免费就称维护免费。

本轮没有创建公开链接、上传数据库或开新云服务。先比较权限、移动端体验、数据更新与维护成本，再选择实现。

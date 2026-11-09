# der 通知中心与多人群权限

本页的类别是产品设计及故障案例，不把外部仓库的能力当成本项目已接通的能力。

## 机器人职责

| 入口 | 职责 | 不代表什么 |
|---|---|---|
| HealthchecksBot | 独立外部心跳，主机/采集状态信号与Paper API可用性；云端每分钟上报 | 不知道全部交易门禁，不核验每一张保护单，不调用秘书 |
| deehub_paper_reports_bot：#OPS | 群内固定运维摘要；仅本地API连接、券商上游连接两种白名单事件（日报另按用户授权公开） | 不含账户、持仓、成交、金额、原始错误及日志 |
| 同一der机器人：#RISK / #AUTH | 私聊中的风险、保护、对账、认证 | 不批准交易、不重放未知结果 |
| 同一der机器人：#REPORT / #RESEARCH / #INTEL / #CONTROL | 群内公开日报；私聊中的研究秘书、情报、直接Python控制 | 标签是逻辑职责，不声称新建了多个BotFather机器人 |

Healthchecks独立于本机通知进程，能在云机失联、通知worker无法运行时报警，是必要兜底。当前host检查依据cloud-status新鲜度及剩余磁盘；paper_api检查依据准确Paper身份、上游、新鲜心跳及对账时间，不覆盖所有业务依赖。报警延迟由服务端period/grace决定，不能用一分钟上报等同一分钟必达。最新验收：主机ping healthy=1、Paper API healthy=0，均HTTP_ACCEPTED；没有用成功ping掩盖上游故障。

监控职责、云断网／关机／Paper 链路故障的场景对照，见 [项目纲要：云端监控与报警职责概述](../README.md#云端监控与报警职责概述)。两路主要共用 API 状态证据，云外心跳另行提供失联兜底；Up 不等于重启。

## 多人群与owner

`shared_group`配置：只接受本机私密配置中精确的owner_user_id，用户名、群管理员身份、显示名、转发、匿名发言都不能代替owner。der群或已核验owner私聊可发指令，查询与秘书结果始终按私密路由返回，定时日报按用户追加授权在群内公开；非owner消息不进入秘书任务、不调用模型、不查询账户。当前BotFather隐私模式开启，普通群文本未证明能被收到；私聊可直接发文字，群里可靠入口仍是明确命令。不要为了读朋友聊天授予机器人管理权限。

日报及财务补报按用户追加授权继续发der群供所有成员查看。发送端将其他私人消息移到经过原生getChat核验的owner私聊。群人数增加不会扩大私聊收件人。私聊不可用时拒绝投递，不回退群。公开日报只读取现有业务报表的白名单字段和已校验PNG，不读取凭据配置；秘书SQL拒绝读取密码/token等敏感列（包含别名及截取表达式），token/password结构字段与常见令牌字符串会脱敏，发送前阻断当前bot token原值。公开运维模板完全使用固定文本，忽略事件中的账户、symbol、原始reason及source。旧模式继续保留严格人数校验，用于兼容既有部署。

**历史消息仍可见**：新权限不删除旧群消息。邀请朋友前请处理不打算公开的旧秘书对话/持仓查询历史（日报已获公开授权），或使用单独的讨论群。不得声称新权限能撤回已经泄露给群成员的历史信息。

## 常用命令（只限owner）

| 命令 | 效果 |
|---|---|
| `/start` | 私聊帮助，查看职责与命令 |
| `/inbox` / `/inbox risk` | 通知收件箱，类别/来源/投递状态/本地未读标记；最近200条事件中的最多12张当前卡 |
| `/event 951` | 私聊查看具体事件完整诊断，不修改broker或事件状态 |
| `/read 951` | 本地标记已读；下一次更新仍未读，不冒充Telegram已读回执 |
| `/preview 951` | 预览将发内容和群/私聊目标；不claim、不发通知、不写投递回执 |
| `/notify` | 查看分类与配置 |
| `/notify research off` / `/notify report on` | 选择非强制类别是否主动投递；事件仍进收件箱 |

重要故障、恢复、风险、认证与控制不能被类别静音。风险门禁仍用既有 `/qmax /omax /rmax /smax /gmax`，不经模型。收件箱和配置数据保存在同一个runtime/recovery.sqlite3，不创建第二套投递worker。

## 分类与需要覆盖的情况

| 类别 | 典型情况/设计案例 | 私密性及处理 |
|---|---|---|
| ops 运维 | 主机心跳超时、Gateway退出、API断开、1100/2110上游中断、1101/1102恢复、依赖陈旧 | 仅两种固定连接摘要进群，其他诊断私聊；恢复仍须完整证据 |
| risk 风险 | 保护单不足、回读不完整、外部手工单、资金不足、未知订单结果、行情会话冲突 | 私聊，强制投递；不把缺少本地intent当作无敞口 |
| auth 认证 | 周期登录到期、二次验证、重登拒绝、认证后回读未完成 | 私聊；不发送密码/验证码 |
| report 日报 | 正常日报、缺报、CJK字体错误、时区误判、回执未知、延迟 | 群内公开（用户明确授权）；09:00 Asia/Shanghai，日期/源数据时点分别展示 |
| research 研究 | 自主选题、资料不足、实验失败、证伪、研究完成、费用异常 | 私聊；进度可静音，红色故障必达 |
| intel 情报 | SEC 8-K/10-Q/10-K、宏观发布、持仓公司新闻、来源无订阅/不可用/未验证 | 私聊；不将相关性说成因果，不新增付费订阅 |
| control 控制 | 修改上限、持仓查询、批准状态查询、工程提案、设置/预览 | 私聊；精确owner授权，确定性Python，不自动解除交易暂停 |
| fyi 券商通知 | 官方示例PF Portfolio FYIs、PT Position Transfer；其他typecode从账号原生settings发现 | **未接入**Web API FYI；不伪造分类/未读数，不自动接受免责声明或修改券商订阅 |
| other 其他 | 未识别来源、新模块或缺少类别 | 默认私聊，不能由producer自报public而扩大受众 |

FYI与我们自己的运维事件不是同一物。官方API提供通知列表、订阅、deliveryoptions和未读数；某些详情要求本人接受对应声明。接入时需要保留原始typecode、broker notificationId、来源与broker已读状态，和本地已读标记分开。本轮不新开Web API认证或对券商写设置。

## 短消息与一次事件

顶部显示标签、重要/提醒/恢复、关键一句和编号，诊断细节使用Telegram原生expandable blockquote折叠；所有原始文本先HTML转义。日报附件caption有限长，完整详情用/event读取。客户端能否折叠取决客户端版本；普通文本兜底仍保留明确编号。

同一incident_key+generation的后续提醒/升级/恢复更新同一张compact卡；全部状态仍分别存入outbox和原生回执，下一次真实故障新建generation。旧格式消息及不同收件人消息不跨目标编辑。编辑可能不触发新的手机推送；Healthchecks独立故障/恢复提醒继续保留。UNKNOWN/STARTED不自动编辑重放或换渠道重发，消息被删除导致编辑失败也保留未知结果待对账，不盲目补发。

通知配置只影响未发出的新投递。SUPPRESSED表示用户静音且没有HTTP尝试，不伪装成功。预览时点不是实际发送时点，预览不强制每次告警等待用户确认。

## 模块化与复用

业务采集器→IncidentStore/统一outbox→分类/隐私路由/模板→Telegram、SMTP或Feishu适配器→原生回执。业务事件不持有channel token；现有唯一sender和kernel lock不变。借鉴Apprise的通道边界，不引入其依赖、不把第三方投递API当成交易批准。

Python/SQLite/Telegram/IBKR接口没有Hetzner API依赖，逻辑可在其他VPS复用；当前运维脚本仍固定Linux systemd、ibkr用户、/opt/openclaw路径与账号白名单。给别人复用需单独实例、自己的凭据/账号/owner/chat/数据库/manifest，按新环境验收；当前不是已完成的多租户托管产品。不能共享本人的数据、token、生产目录或已批准manifest。项目当前LICENSE为保留所有权利，仅限内部测试与授权协作；对外复用需你明确授予书面许可，并保留依赖许可证。技术可迁移不等于已授权他人复制。

## 参考与边界

- [Telegram Bot API](https://core.telegram.org/bots/api)：折叠引用、消息编辑、原生回执。
- [Healthchecks](https://healthchecks.io/docs/)：心跳/缺失信号，并非全业务正确性。
- [IBKR Web API FYI](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/#fyi)：原生通知与订阅；本项目尚未接通。
- [ibkr-dashboard](https://github.com/JeffPu/ibkr-dashboard)：dry-run/收件人预览理念。
- [PortfolioHelper](https://github.com/TrishkaV/PortfolioHelper)：持久化、职责拆分、抑制通知刷屏理念。
- [ibkr-web-api](https://github.com/promobase/ibkr-web-api)：FYI接口目录参考，不等于已部署。
- [Apprise](https://github.com/caronc/apprise)：替换通知通道的边界参考，不复制源码。

验证记录：测试、秘密扫描及部署摘要见本轮ENGINEERING记录。不得以通知成功代替broker恢复，也不重复故障演练。

## 2026-11-09 owner correction
With `automatic_updates_to_group=true`, all noninteractive automatic updates, task progress/completion and research reports go to deehub. Interactive replies and explicit action/response requests remain at the existing verified secretary destination. This supersedes the fixed-template-only private routing above. No old accepted or UNKNOWN message is copied/replayed. A separate secretary group, if intended, requires its exact native identity before changing the interactive destination.

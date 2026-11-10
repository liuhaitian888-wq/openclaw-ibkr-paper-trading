# 自主研究秘书运行边界与来源

用户于2026-11-07明确授权：无新指令时秘书自行提出课题、安排实验和测试；读取全部已登记业务数据库；自行管理日常研究和模型费用，只有明确边界或费用风险时汇报。测试通过后可启动。交易门禁不变。

## 实现与依赖来源

本轮新增代码由本项目实现，复用既有 SecretaryArchive、IncidentStore、Telegram精确audience验证及共享health registry。使用已安装的官方Codex CLI和独立ChatGPT OAuth登录，不复制桌面凭据或将本机auth.json传到云端。参考官方非交互模式文档：
https://learn.chatgpt.com/docs/non-interactive-mode

TradingAgents、LEAN、LangGraph、OpenAI Agents SDK均未安装或复制入本轮实现。TradingAgents论文/Apache-2.0仓库仍为待复现研究候选，不能称已集成。multi-agent指多个职责分明的模型协作；SDK是方便程序调用模型、工具和运行管理的开发库。本阶段先用单一秘书和现有基础设施，不叠加框架。

## 所有数据库只读接口

`reporting/secretary_read.py`登记全部四个业务库：交易审计、财务账本、runtime/recovery、秘书档案。库ID来自固定注册表，不接受模型提供任意文件路径；新增业务库需要登记。历史备份和migration候选不冒充生产库，也不自动激活。

提供databases、schema、query、coverage_test、hypothesis_test。SQL连接mode=ro/query_only；authorizer拒绝写入、ATTACH、PRAGMA和非白名单函数。单查询最多100ms、100行、50KB，限制SQL和单元格大小；输出脱敏。hypothesis_test执行真实SQL标量断言，报告SUPPORTED/FALSIFIED/INCONCLUSIVE，不能当作统计显著性或盈利证明。coverage_test如实记录连续行情/费用版本/样本外切分缺口。没有可验证输入时不给虚构回测收益。

研究请求和实验结果保存明确来源；模型摘要、工具调用、策略版本、费用假设、数据适用性和样本外条件保存在独立档案。模型没有shell、券商、支付或任意代码执行接口。未登记的论文搜索/实验由模型提出方案并标记未执行；当前不是通用任意代码回测沙箱。

## 两端单owner与恢复

云端`ops/cloud/secretary_rpc.py`为有界SSH RPC，每次核对已批准监控部署manifest和独立秘书policy，持有secretary-rpc内核锁。精确核对der群、owner和允许的机器人；拒绝现有webhook，避免争抢。只接受生效时间后的原生owner消息，拒绝转发/匿名sender_chat/bot。Telegram原生update ID去重并持久化offset，不重放历史消息。

本机`scripts/run_secretary_bridge.py`为唯一模型owner，从主工作区运行，校验独立批准的commit/branch/workspace/state manifest并持有内核锁。OAuth仅本机使用，云端令牌仍仅云端。Mac关机/离线会暂停模型研究，云端交易监控继续；本机恢复后STARTED/UNKNOWN模型任务不自动重放。

初始研究调度每6小时一个新槽，不补跑过期槽；有未决模型运行时暂停新自主任务。owner聊天优先，初始每天最多24项任务、每项最多3轮推理/8次只读工具调用；每次模型超时120秒，SSH45秒。它们是初始运行保护和订阅用量控制，非已估出的现金费用；保存实际token用量。没有日常逐项费用审批，不虚构订阅余额或精确现金账单。只有当前已登记工具会执行。

模型调用前持久化STARTED，失败/超时保留UNKNOWN。归档成功与跨库outbox之间的中断通过确定性唯一键补入队列；发送仍由既有notifications owner负责，HTTP不确定结果不自动重发。秘书回复不创建故障incident。resource快照仅观察本机FD/RSS/CPU/线程/子进程，日志轮转；不启动生产recovery适配器，不杀其他进程。

## 备份与验收

每日备份已扩展覆盖秘书库；每库一致、不跨库原子。备份测试真实解压、哈希复算和隔离SQLite quick_check。数据库页面仍只读显示备份证据，不冒充实时全库完整性扫描。

异地备份能应对整台主机/磁盘损坏或账号事故，同机16批不能覆盖这些风险。目前没有新购资源或已验收的异地副本；目标存储和保留/加密策略尚未落地。

完整离线测试仅在linked worktree运行`python scripts/run_worktree_tests.py`；主工作区仅quick smoke。通过secret scan后提交、通过Git收回主工作区及cloud，最后启动秘书。验收必须分别给出模型结果、实际工具证据、群发送回执和真实owner消息；未收到真实owner新消息前不能把模拟授权测试称完整双向用户验收。

## 2026-11-07 Telegram数值门控、认证协助与本机副本

用户追加授权：将硬门控数值模板移到Telegram，远程填值后生效；需要登录时提供协助，成功后Telegram通知；复制审计库供本机分析。

`/gate`返回完整JSON模板；复制`/gate_apply {"revision":...,"settings":...}`整条命令填写数值。只接受max_quantity、max_order_value、max_risk_per_order、max_symbol_exposure、max_gross_exposure五项。revision防止旧模板覆盖新值，原生owner身份验证后直接进入Python控制路径，不经过LLM。档案事务保留每个版本，再原子落盘runtime/risk-controls.json；中断后可由已提交版本幂等恢复。RiskEngine每次校验读取附加上限；旧硬上限继续生效，不改变账户、approved、PAUSED/MAINTENANCE、保护单、会话/日历许可或已用3/3测试额度。金额USD，数量整股；0可阻止对应请求。该界面不是任意Python执行接口。运行服务需要先部署一次新版消费者，此后数值更新不需要重启。

`/login`查看Paper认证/完整回读状态；`/login_assist`跟踪既有自动化owner，仅当systemd状态inactive/failed且独立部署policy明确批准时，由已有本机SSH身份向唯一ibkr-gateway.service提交start，不restart正常Gateway、不创建竞争实例。手机IB Key验证留给用户，不通过Telegram收密码或验证码。STARTED/UNKNOWN控制操作不重放；systemctl接受不等于认证成功。后续只读轮询须核验正确Paper身份、positions/orders/completed_orders/executions全部结束、非dirty、上游连接及10秒内server reply，才发认证成功通知。当前健康状态不能当作新一轮周度登录已演练。

官方说明周日01:00美东安全令牌失效后需要人工认证，也可能提前撤销；二次验证须通过已登记安全设备：
https://www.ibkrguides.com/traderworkstation/auto-restart-considerations.htm
https://www.ibkrguides.com/securelogin/sls/using-two-factor.htm

本机一致性副本来自20261106T234018.315731Z云端备份；1861767168字节，解压SHA-256 d817a32ab8b2216b24e20786f675622903e434b2ee416f6a130c84a89d763b1f，隔离quick_check通过。位于state/secretary/snapshots该版本目录，文件只读、非生产激活候选。秘书schema/query/hypothesis_test可指定source=local_snapshot；只有返回证据进入模型上下文，不能把复制整个DB说成免token读取。尚无连续历史行情或完整净收益验证。

真实第一项自主研究成功并收到Telegram原生回执；真实owner /secretary消息已入档，但该次模型运行UNKNOWN，未重放。后续修复需分别保留原始UNKNOWN、公开可核查的协调事件和新任务身份，不能把付费结果丢失改写成成功。

## 云端直达控制与自主研究范围

新部署以secretary-policy.receiver_owner=cloud显式指定唯一云端收消息owner。`ibkr-secretary-inbox.service`接收原生owner指令并运行确定性控制，模型工作由本机独立owner领取任务；模型研究运行中不阻塞数值控制。原RPC在cloud模式下不再调用getUpdates。二者分别持有内核锁，SQLite事务和update ID去重保持。

`/gate`显示中文字段；`/gate_set 单笔金额 150`等单行命令直接进入Python，保留原JSON接口仅作兼容。命令成功指“附加数值上限已保存，下一次风控检查读取”，不意味着策略/账户/会话/交易批准通过。普通聊天不能改变门禁。`/focus 文本`设置下一轮自主研究的固定方向；`/intel`读取逐源实际状态。所有这些控制均不要求模型推理。

经用户明确授权，模型可调用`research_universe`选择最多12项额外新闻研究公司及逐项理由，记录MODEL提案和TOOL落盘结果；持仓/最近已核验持仓始终优先覆盖，执行标的及订阅权限不变。该工具需独立policy标记，不从网络可用性推导权限。

消息用🟦研究、🟪情报、⚙️控制、🔐认证、🔵进度、🟥/🟨故障/风险及🟩恢复区分。正文只展示短记录编号，完整occurrence保留在库中。既有HealthchecksBot仍由外部服务控制；不添加竞争发送owner。

用户随后指定英文缩写风控门：/qmax、/omax、/rmax、/smax、/gmax；/gate显示英文简表。每条修改走确定性Python，原中文/JSON接口仅兼容旧消息。普通owner群聊天无需/secretary前缀，但Telegram隐私模式须关闭或具备允许完整投递的群权限；实测当前can_read_all_group_messages=false，已交用户在BotFather确认调整，不能把应用接收代码可用当作平台已投递。

调度时间槽是不可变事件：升级代码或更改focus后，同一6小时时间槽继续保留原始载荷，不能重新append不同内容，也不产生额外付费任务。新focus从新时间槽采用；独立owner任务照常排队。

`/ready`与`/holdings`为原生Python只读控制：区分真实回读、审批、工程验收、保护、资金和时段数据；不通过模型，不发送券商请求。持仓状态过旧/结束标记不全时明确标为STALE_OR_UNVERIFIED，外部持仓不被认领为策略仓位。激活决策单见PAPER_ACTIVATION_CHECKLIST.md。

工程协作共享箱：模型可调用engineering_proposal，保存标题、实际观察、改进建议和1–5项可复查证据；相同内容跨任务去重。它不执行shell、代码或部署。engineering_updates及Telegram `/engineering`读取提案与工程侧独立SYSTEM ENGINEERING_STATUS回执；工程侧Codex可直接读取共享秘书档案并写回检查/实现/验证结果，用户无需手动复制正文。现阶段没有自动唤醒当前桌面聊天；不能把已存提案说成已开工。ChatGPT网页聊天、Codex工程聊天和Telegram秘书会话不默认同步；独立ChatGPT接入同一共享接口需另配官方MCP，尚未接通。

官方能力依据（2026-11-07实际读取）：https://developers.openai.com/codex/sdk （重定向官方learn.chatgpt.com/docs/codex-sdk），https://developers.openai.com/chatgpt 。当前使用已有CLI，不额外安装SDK，也不转移OAuth令牌。

## 云端原生认证协助接续（2026-11-10，源码阶段）
旧章节的Mac SSH启动描述保留为历史。新的确定性Gateway启动控制由唯一云端inbox执行，受原有gateway_start_assistance_approved、gateway_start_control_owner=cloud_inbox和新切换时间约束，只处理切换后的真实owner /login_assist。再次核验精确身份与服务inactive/failed，仅提交一次固定systemd start；正常/正在转换的服务不重启。云端模型不再领取自己不能执行的控制；本机用户会话搜索仍是独立依赖。原操作UNKNOWN保留，单独通知已构造成功不等于启动成功。systemd接受与手机IB Key/完整新鲜Paper回读分别验收，不改变交易门禁。规则安装、部署及原生权限/未来停机登录验收以task-closeout实际记录为准。

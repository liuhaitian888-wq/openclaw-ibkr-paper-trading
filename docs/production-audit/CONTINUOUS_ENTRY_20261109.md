> 最新候选状态：完整离线1130项/75.179s/OK；尚未云端部署。原生旧仓补保护五笔已完成、PFE保留，独立验收见SCOPED_PROTECTION_20261109.md。新增交易、持续现金生产者、股票价值日、部分成交/重启与正式T0仍未收口。以下阶段记录保留各自时点，不代表所有候选已启用。

# 持续准入工程进度

当前状态（2026-11-09T22:13:57Z现场验收）：本文后续“未部署”段落是此前阶段记录。上述准入/费用/日成交/结算代码和周报修复已随217ac9070b46d4115fd674bdc241335436234856通过Git部署；只读现金owner已正式配置。最新原生book约1.1秒新、会话/对账批次匹配，六仓六保护保留、金融操作计数不变。CURRENCY_BOOK原始HEALTHY但依赖解析WAITING_DEPENDENCY，ACCOUNT/EXECUTIONS/AUDIT实时证据仍待接线，不是全自动READY。Gateway升级期间未重启；交易PAUSED/MAINTENANCE保留。私有部署备份、schema双环境影子验证、原生回执和资源样本见canonical engineering/native-cash-release-20261109T214705Z；原日报1094及通知953的UNKNOWN保留，不重发。

## 事务预留（linked worktree，尚未部署）

既有流程先检查现金/日限额，再单独写order_requests，存在并发复用资金的窗口。现将日预算检查、精确意图写入、资金claim及最后一次门禁/风险复核放进同一SQLite BEGIN IMMEDIATE事务；拒绝则回滚，不留下幽灵意图。进入券商调用前以独立持久TRANSPORT_STARTED事件抢占单owner通道，已经开始/未知的发生事件不能通过状态改名重放。

两个已预留请求争抢券商通道时，确实未发送的请求标记REJECTED_NOT_SENT并只释放自己的未发送claim；此类请求不消耗日预算。UNKNOWN/已开始记录继续持久阻断，不以FAILED标签释放。已确认ACK的现金claim仍保留，不能仅凭成功返回或相似orderRef转为可用资金。

隔离验证1073项/74.256s/OK，包含并发预算、未出现在券商缓存的本地claim、UNKNOWN重启、状态改名不重放、预检期间门禁和风控撤销、无附加限额时外部FX活动单、未发送竞争者、日界线与换汇不占股票预算。资源回归FD5/恢复FD4/线程1→1。秘密扫描另记。

## 未完成、不得对外宣称全自动通过

- 精确原生ACK绑定和现金claim核销已完成离线实现；原生执行owner集成、部分成交/重启现场验收仍待完成。
- 新增原生现金对账仅允许完整新鲜事实释放claim；UNKNOWN不自动核销。此候选尚未部署，不能以离线通过代替现场验收。
- 现有日计数仍是保守请求承诺口径，不是完整券商双向累计成交额；要结合去重的原生execId、发生时区、部分成交、未成交余额与风险降低退出统一核验，不能把保护性退出堵住。
- 实际CashBalance不等于已结算USD。需要券商实际结算/可交易资金证据，不能按泛化T+1/T+2或仅凭余额转正推定可用。
- 实际规范化价格/止损、原生部分成交保护、资金/费用与持续信号执行仍需联合验证。read-only监测owner保持无下单路径。

资料：[IBKR货币转换与结算说明](https://www.interactivebrokers.com/campus/trading-lessons/converting-currency/)。确切结算取决于账户、币种、产品和银行假日；本次没有宣称换汇后的USD已经结算，也没有追加借款/换汇或放行股票。

## 精确原生证据与费用（隔离候选，未部署）

ACK绑定须符合本次原生回调的account/contract/client/permId/父子订单及经济字段，不能仅凭orderRef。绑定不赋予撤单或接管权限。现金核销要求绑定后的完整原生对账、现金读取起止时间和成交/费用先后关系；活动原生BUY只转移给券商挂单预留，终结成交仍保留费用预算，直到实际费用与更新后的多币种现金账本相符。

原生费用可先于exec到达，先保留待绑定事实；execId与费用修订分开保存，重复不增版、更正保留历史。SDK protobuf缺失字段不能视为零费用；只有原始字段明确存在才接纳零。旧格式无法证明零值时继续待核验。已知成交/费用修订之后必须重新读取现金，不接受先读现金后收到成交的倒序证据。

资金策略启用时，入口必须使用原生联动保护路径，不能在普通limit入口附带未实际提交的stop字段绕过。共享ORDER_SUBMISSION新增AUDIT依赖，不以新adapter或抹除故障开绿灯。

完整隔离测试1083项/74.524秒/OK；资源回归FD5，恢复FD4/线程1→1。测试日志归档于工程状态目录。仍未部署、未放行正式策略、未追加券商交易。日成交口径及连续执行闭环仍未完成。

## 日成交额事实投影（尚未替代准入预算）

新增pure native_turnover按execId读取精确账户的原生STK/USD实际成交，买卖两向累计且外部成交同样计入；CASH换汇单独保留、不计股票成交额。使用实际发生时间与显式时区，验证夏令时重叠/不存在的本地时间，不用收到回调时间冒充成交日。缺少当日时间/币种/合约/经济字段返回unresolved，不能默认为零。历史缺失时间只在首次收到事实已经早于本日时不污染未来每一天，原始审计记录仍保留。

此投影不赋予权限，也尚未替代原子准入的请求承诺预算。请求承诺与实际成交合并时仍要证明部分成交不双计、跨日活动单、撤单释放、原生执行更正以及日额度不能阻断保护退出。不能宣称完整每日成交额风控已收口。新增五项行为验证后全套1088项/83.597s/OK。

## 日准入组合候选

原子准入现改为读取当天原生成交双向金额，并加上仍可能执行的承诺；已绑定父单以精确all-time execId数量扣减剩余承诺，未成交余额跨日保留，只有完成native/cash终结核验的claim可以清除未成交预算。无精确绑定的当日ACK继续视为承诺；TRANSPORT_STARTED后的FAILED标签不能抹除。此函数仅用于entry admission，不接管保护退出。

完整离线1090项/75.674s/OK，OpenSpec5项strict PASS。真实费用/结算/部分成交/重启与执行owner集成尚未验收；原生更正/撤销语义和所有边界仍需独立核实。旧API health的daily_notional_used历史请求口径尚待统一，不能用该旧显示字段代替新事务准入。未部署此候选。

### 原生成交更正审阅

[IBKR官方execution details](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details)明确：部分成交各有execId；更正通过最后一个点之后数字变化的execId额外发送。因此不能把所有不同execId无条件相加，也不能删除原始行。本文候选需识别更正家族并保留未核验状态；完整经济版本投影/撤销与费用归属不能只凭字符串选最新后宣称完成。IB Gateway原生执行查询默认仅当日，跨日历史依赖本地已持久化证据，不能把新快照没有旧成交当作撤销。

API health日预算字段已改为与事务准入同一投影：分别显示actual buy/sell、未成交承诺和准入预算；无法核实时entry_budget_used/null，而非报告零。旧paper_notional_for_date仅保留历史请求报表兼容用途。此轮完整离线1091项/76.088秒/OK。

更正家族现被明确识别：同一TWS末段数字变化或单独出现非初始版本，均不当作独立新增成交；保留原始execId并返回待核验。现金核销同样拒绝更正家族，即使错误相加的数量碰巧符合原生filled也不释放。完整经济更正/撤销解析仍待后续验证，没有选择最新版后抹除原始事实。全套1094项/78.973s/OK。

## 结算事实与现金缓存延迟

原生accountUpdateMulti(ledgerAndNLV=False)于2026-11-09T20:44Z完整回读，AccountReady=true，USD的SettledCashByDate为`20261109:-69788.66;20261112:2019.42306`。这是券商实际日期，不是泛化T+1/T+2推算。日期后的值是累计余额，不能相加，也不能把BASE净额当作实有EUR或USD。证券成交价值日及任何匹配换汇结算的可用性仍未核实；没有宣称股票可以仅因普通CashBalance转正而放行。

新增纯结算解析、字段/日期/单位/账户/ready/end/时间顺序校验。资金策略入口现须有新鲜原生结算receipt；未完成价值日匹配验证时，只按当前与已知未来USD累计余额的保守容量准入。普通正余额、未来入账或EUR净额不能填补未核验USD。readiness新增独立SETTLED_USD_EVIDENCE，不以普通现金PASS冒充结算PASS。现有云端CashBook生产者尚未接入这个新receipt，因此此候选保持未部署，正式入口不能启用。

更严格的现金claim核销：只在更新后实际USD余额等于原有明确USD基线加全部新原生成交现金变化、减实际费用版本差额时释放/转移。较晚RPC结束本身不是现金已扣款的证明。两个并发已成交请求不能复用同一次扣款证明；缺费用、未识别FX/外部资金流、经济更正或不明差额均保留claim，避免重复花钱。baseline已有外部交易的完整经济账本与持续资金owner仍是独立P0，不以此局部核验代替总账验收。

[IBKR结算字段](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/updates)、[DTC2026结算通知23036-25](https://www.dtcc.com/-/media/Files/pdf/2025/10/15/23036-25.pdf)、[IBKR货币结算假日](https://www.interactivebrokers.com/en/education/currency-settlement-holidays.php)用于研究。DTC通知搜索索引可读取，直接PDF请求本次404；不能把无法访问的附件当作现场验收。股票交易所开市、美元结算假日与API运行必须区分。

当前全套1104项/80.196s/OK，含缓存延迟、并发扣款共用、费用更正后现金差额；资源FD5、恢复FD4/线程1→1。秘密扫描/Git整合另记。

## 周报交接修复

完整周报和16条证据仍归档；发送文案以3000 UTF-16单位为界，选择完整证据行，保留任务要求、完整归档key和未被Codex接收/部署的边界。省略数量明确可见，不在Telegram传输层截断提示尾部。此修复已包含在1104项隔离验证中，尚未部署。

## 原生只读现金采集单元（尚未接生产owner）

NativeCashCollector使用已有SDK client，不创建线程/进程；一次一个账户Multi请求、8秒单调时钟超时、最少5秒刷新，精确reqId/account/model及connection_generation，128行/90KB原始证据上界。完成、拒绝、超时和close只取消自己的账户订阅；发送/取消结果异常后须关闭原client再重连，不追加另一个请求。负结算余额作为有效事实保留，不授予资金权限。

先运行的完整红灯验证1107项/82.324s、唯一ModuleNotFoundError；实现后1117项/75.759s/OK，包含200次请求/取消循环且无新线程、迟到/外部回调、身份变化、取消/发送异常及发布失败。此时尚未接入监测owner、尚未部署；计划见docs/superpowers/plans/2026-11-09-native-cash-owner.md。

## 单owner接线与真实协议探针（候选未部署）

PaperSafetyClient可选接收现金publisher；同一SDK实例重连后账户请求ID继续递增，旧回调不能借复用ID进入新会话。现有paper-safety循环调用poll/close，不增加线程或服务。只读批准字段位于monitoring-deployment.json，不改受保护的production.json。publisher核对native epoch/connection/最新完整对账及成交/费用时间，私有临时文件fsync后原子替换，失败部分保留且旧latest不被截断；准入claim保存一次完整基线book。CURRENCY_BOOK在共享resolver中按需依赖，10秒失鲜；负结算可为健康数据而不能成为买入权限。

有限FX的独立native结果仍保存；配置持续writer后不覆盖latest。缓存发布失败不把已确认的FXFILLED冒充未知金融结果。全套1130项/75.179秒/OK，包含原子写入故障、30次文件/SQLite/线程资源闭环、SDK重连迟到回调以及新对账epoch拒绝旧现金请求。独立只读代码复核未见可执行回归；未重复测试或触及生产服务，该结论不等于完整金融验收。

真实只读协议探针：源四文件指纹f17d1912eb2c86b7a41ef16f22b4de2ca3b018eec7f0816a1c971bd7a716adf9，2026-11-09约21:41Z，精确Paper账户、多币种现金及结算回调成功。USD2019.4231、EUR943040.605，普通现金与结算负值分别保留；线程1→1、client关闭、0订单请求。候选仅在私有工程探针中执行，没有写生产latest或promote共享health；真正生产owner回读仍待部署验收。

## 通知与券商不确定性分域（后续候选）

保留uncertainties()全量默认接口；broker adapter backlog及ORDER_SUBMISSION仅查询order种类，delivery UNKNOWN仍保留并禁止重放。并行deehub三笔提交已在隔离工作树保留整合。完整离线1135项/77.716s/OK，独立静态复核无实质缺陷；当前云端5df418d，分域修复及文件故障锁尚未云端部署。新增订单仍受当前风险、所有原生资金/对账与正式暂停门禁约束。

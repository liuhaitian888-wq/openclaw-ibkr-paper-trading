# 存储增长治理与有限本地归档

本波是容量最小发布aba2fda之后的独立候选。先上线已测监测/查询，不等待归档；本波不自行修改云Git/manifest/systemd，也不删除历史副本、活库、WAL、表或字段。部署和真实秘书回执由唯一publisher记录。

## 现场与目标

最新只读root快照39956590592bytes总量/31081336832used/7219585024available，df82%。state22098243584bytes：backups5703933952、runtime4008161280、migration3792756736、archives3723755520、engineering2680418304、baseline1859936256、screening35459072、security-directory2723840。扫描为metadata，原始输出存本机engineering/storage-governance-20261111/fresh-capacity-top.txt。历史副本仍主占用；35MB公开研究目录不是整盘增长主因。非连续快照不提供time-to-full。容量JSON积累连续>=1h证据后再校准速率。

先限制未来非必要写入，保住关键状态所需余量；本轮不声称已回收云盘空间。用户要求暂不删除历史副本，故本地归档验收也保留全部源文件，实际回收量0。

## 官方实践与采用边界

- SQLite WAL是持久状态的一部分，长读事务会阻碍重置。继续保留连接closing/短事务与WAL异常检测，不以删WAL或强制checkpoint替代生命周期治理。[SQLite官方WAL](https://www.sqlite.org/wal.html)
- journald分别限制使用量与保留空闲空间；轮转可能删除旧journal。我们采用“总配额+空闲余量”的思路，本轮不改全机journal保留策略、不vacuum或清理旧日志。[systemd官方journald](https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html)
- Python普通FileHandler可无限增长，旋转handler需要明确大小/数量。本波新存储诊断改为128事件/64KiB固定环，不把订单、故障或回执原始日志接入可覆盖环。[Python3.13 logging.handlers](https://docs.python.org/3.13/library/logging.handlers.html)
- restic区分结构检查、读取全部数据和分片校验；本波分别记录manifest、分块SHA和隔离重建，不把文件存在当恢复验证。[restic官方仓库校验](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)

这些来源支持预算与验证分层；当前阈值和具体白名单是本项目候选工程决策，不是上游提供的金融保留期。

## 分类、预算与不可淘汰边界

| 类别 | 本波行为 | 体积/保留边界 |
|---|---|---|
| 订单/成交/敞口/风控/任务状态/receipt/UNKNOWN | 必须持久，保持身份/发生/内容区分 | 不截断、删除、自动重放；不受可选写入gate阻断 |
| 历史DB/备份/迁移保护/原始来源 | 保护，保留来源与恢复证据 | 本轮不移动/删/压缩替换；相同大小不等于重复 |
| 原始回调/健康事件业务表 | 由相应P0 owner做语义分层/去重设计 | 本波不改这些writer、表schema、策略或资金权限 |
| PUBLIC_SCREENING | 仅可选公开研究新增快照/刷新可暂缓 | screening/snapshots总量256MiB；一轮留64MiB；单blob<=5MiB |
| PUBLIC_DIRECTORY | 仅可选公开目录新增快照可暂缓 | security-directory总量64MiB；一轮留8MiB；单blob<=2MiB |
| 新存储决策诊断 | 只含固定类名、状态、容量和时间 | runtime/storage-budget-events.json，128事件/64KiB，变化或每小时归档 |
| 本地公开资料归档 | 显式路径、只读源，校验后写本机 | 目标总量5GiB；可用空间至少100GiB；每批<=128MiB/60s（单网络操作仍有20s超时） |

公开源可再次请求，但旧时点精确内容不一定可重建，所以不自动删除旧原始快照。项目所有模型文本/字段并未被强制截短；只限制明确可选工件，关键金融身份与事件不丢弃。

## 可选写入门禁

`ops/cloud/storage-policy.example.json`是精确非交易配置模板：version1/approved/enabled、grants_trading_permission=false，可用余量>=8GiB且>=28%。publisher核对当前source/manifest后才将它写到state/runtime/storage-policy.json，缺失时保持POLICY_UNARMED；无效/不明配置只令可选写入DEFERRED，不触碰核心。当前约6.72GiB可用，应暂缓这些低优先新增写入。重新允许需达到更保守的空间余量，不能自动降低阈值使任务变绿。

前置检查在公开研究runner构造DB/领取任务/网络请求之前；公开目录入口也在SecretaryArchive构造之前检查。QUEUED/STARTED/UNKNOWN记录不因gate而清空、重置或伪造完成。每个新增raw/manifest写前再次检查配额和字节上限；已存在同名相同内容去重，不同内容拒绝覆盖并保留旧来源。单轮可能因中途空间变化失败，原始来源/已有缓存保留，错误不当成新鲜事实。

目录配额扫描最多2000entries/50ms，partial或symlink拒绝新可选写入。文件/SQLite/目录句柄均有生命周期，所有诊断仅固定环，不发重复短通知。复用既有capacity sampler观察OPTIONAL_STORAGE_WRITES（shared registry依赖CAPACITY）；BROAD_SCREENING只在该预算模块启用时依赖它，不创建第二observer/sender。本波进一步把OAuth辅助容量采样限制为文件stat，连只读页元数据SQLite连接也不建立；无内容权限。容量只读工具附带已存预算决策，不在查询时触发扫描或写入。普通预算暂停不成为新交易门禁或支付权限。

这些gate并未覆盖所有人工工程脚本。大工程备份仍应先估算体积并复用既有保护副本，不能重复复制旧1.86GB审计库；当前4live库备份/rollback由publisher负责，不能为省盘删除唯一恢复材料。原每日备份<20%空闲拒绝线不被放宽。

## 分批本地归档实现

`reporting/storage_archive.py` / `scripts/archive_storage_batch.py`只允许精确模式：

- screening/snapshots/<受限runID>/{1..9}.json及manifest.json；
- security-directory/snapshots/<受限runID>/{nasdaqlisted.txt,otherlisted.txt,manifest.json}。

金融库、OAuth/凭据、历史大DB及任意其他路径不在本版归档白名单。此次不批量下载16GB历史副本，更不把Mac设唯一备份或核心依赖；历史大库的分组/WAL关联/恢复等价性仍需逐项方案。Mac离线时核心采集/秘书/通知不依赖归档客户端。

默认只dry-run plan，显式--begin才建立本地job；路径最多32个、单文件<=512MiB，计划为chunks+隔离重建双份预留。现有SSH密钥与known_hosts由ssh进程使用，不读出凭据，不创建新账号/付费存储。源helper只接受白名单、有界range和非symlink单链接普通文件，不打开SQLite或认证内容。

每块<=1MiB，源device/inode/size/mtime_ns/ctime_ns在计划和每次range读取核对，块SHA验证后落盘/fsync，再记原子manifest断点。同hash块重用；已存在坏块保留并失败，不静默覆盖。网络只读中断留下PARTIAL可显式续传；源身份变化/坏块进入NEEDS_RECONCILIATION，不能自动重试。manifest<=1MiB、每文件<=512块、批次诊断最多128条；本地10kentry/0.5s配额扫描不完整就拒绝新增字节。

隔离重建只写本地verified-restores/jobID路径，再校验大小与SHA；不会激活金融数据、restore生产DB或宣称跨库一致。默认单次重建验收上限32MiB。此处RESTORE_VERIFIED仅指白名单资料文件字节重建，不是数据库/券商业务恢复验收。

## 实际小批次验收

本机父盘实测可用160660561920bytes（约149.63GiB），固定目标保留100GiB/总额5GiB。仅取2026-11-10 after-close公开快照manifest.json455bytes与9.json260730bytes，共261185bytes；两次128KiB批次实际PARTIAL→COPIED，隔离重建RESTORE_VERIFIED。另从云源独立读取这两个小文件计算SHA，与本机重建文件一致。目标实际523523bytes（块+manifest+重建文件），源无删除、云盘回收0。证据本机engineering/storage-governance-20261111/native-archive-acceptance.json，目标~/.local/state/openclaw/local-public-archive-v1。

## 清理白名单与dry-run

只有上述公开工件能成为“后续审核的清理候选类”；copy/restore验证不自动赋予删除权限。`--cleanup-dry-run JOB_ID`列路径/bytes/copy state及引用来源未对账、缺逐项owner批准等blocker，输出approved_reclaim_bytes=0，脚本没有unlink/delete命令。关键状态/历史副本/凭据永远不进入本波清理白名单；不按日期、字段数量或文件名批量删。真正回收须额外核对所有引用/源唯一性/保留副本与恢复证据，用户批准精确清单后由对应owner处理。

## 发布与回滚

独立linked完整套件/secret/spec通过后交唯一publisher；不可把此源未经组合验证并入监测先行波。publisher更新Git/manifest及配置后，existingoneshot下一轮会DEFERRED，容量owner报告预算模块；fresh读回确认核心owner/门禁不变，无原始回调或交易路径改动。回滚用Git与已留证配置还原，保留所有诊断、partial归档、job与UNKNOWN，不整库restore或删除副本。本轮源、离线、实际小资料归档、云门禁部署与原生秘书验收分别记录。

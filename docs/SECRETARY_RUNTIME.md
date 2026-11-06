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

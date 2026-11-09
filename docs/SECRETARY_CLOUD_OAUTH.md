# 秘书 Hetzner 独立 OAuth

2026-11-09用户纠正：采用ChatGPT OAuth，而非API Key。此前API Key适配代码/凭据入口为未启用的历史准备，不再作为本轮接入路径；保留源码和来源，不删除、不自动回退。

官方无头登录：https://learn.chatgpt.com/docs/auth 。在Hetzner使用官方Codex CLI的device-code登录，由用户在手机/电脑浏览器完成账户认证和授权，凭据只在云端生成/刷新。无需选择API组织、创建API Key或复制Mac auth.json。浏览器授权码/token不得放聊天、Git或日志摘要。若账户未允许设备代码登录，用户在ChatGPT安全设置/工作区权限中确认允许；不由模型擅自扩大账户权限。必要时官方localhost SSH callback方案可另行配置，不复制现有Mac会话。

## 当前实测状态（2026-11-10 Europe/Berlin）

Hetzner已完成独立Gmail ChatGPT OAuth登录，无需用户再创建API Key或执行下方历史device-code命令。此次采用官方localhost回调；临时cloudops127.0.0.1:1455许可已还原并核验，隧道已关闭。Mac OAuth文件未复制。云端原生目录明确支持gpt-6.1-sol/low，模型调用返回公共JSON及turn.completed用量。

运行源码71fa3e6；唯一云端模型单位ibkr-secretary-oauth.service已启用，model_owner=cloud_oauth、reasoning_effort=low且设置迁移时间边界。Mac dev.openclaw.secretary-bridge已bootout。现有inbox/notification仍为Telegram接收/投递owner，交易门禁未动。新owner私聊→模型→结果→原生投递回执仍待新消息验收，不能据此声称完整全天候回复已验收。

首探测UNKNOWN保留。根因是CLI在执行前发出精确CodeMode禁用提示，随后正常完成，但适配器原先拒绝所有error item。71fa3e6仅兼容该精确pre-turn提示并将其留在usage，不启用CodeMode；其他错误/工具事件/无完成回执仍拒绝。

## 安装及历史准备入口

官方npm包@openai/codex@0.167.0-linux-x64，安装/opt/openclaw/tools/codex/0.167.0/codex，root拥有不可由ibkr修改，包SHA512与registry一致；provenance.json保留URL、完整性和binaryhash。只提取归档中的普通codex文件，不执行安装脚本。初始云端Codex不存在；本轮新增独立CLI，不重启Gateway或交易owner。

云端专属CODEX_HOME=/home/ibkr/.local/state/openclaw/secretary-oauth，0700；config.toml0600强制chatgpt登录和file缓存。空推理目录secretary-oauth-empty；不放应用源码、系统工具配置或设备凭据。用户在本机终端执行：

```sh
ssh -t -i ~/.ssh/ibkr_paper_hetzner_20261022 -o UserKnownHostsFile=~/.ssh/known_hosts_ibkr_paper -o StrictHostKeyChecking=yes cloudops@2.31.104.14 sudo -u ibkr env CODEX_HOME=/home/ibkr/.local/state/openclaw/secretary-oauth /opt/openclaw/tools/codex/0.167.0/codex login --device-auth
```

按终端链接在官方浏览器页完成认证；不要发送一次性代码。登录成功只回复已完成OAuth。官方CLI管理token刷新，工程程序只校验auth_mode及本地权限，不提取或复制token。登录成功不等于gpt-6.1-sol/low推理成功。

## 执行及唯一 owner

复用现有bounded executor/队列/检查点/只读JSON工具/Telegram inbox与唯一通知投递owner。新单位ibkr-secretary-oauth.service只做模型；与未启用API模型单位互斥，默认不启用。激活要求新OAuth登录、单次受限模型验证、model_owner=cloud_oauth/model_owner_since/low和SECRETARY_CLOUD_OAUTH_ARMED。Mac poll拒绝领取，旧READY检查点不跨迁移时间恢复，STARTED/UNKNOWN保留不重放。Mac专属搜索/快照明确不可用，不阻断云端核心问答。

gpt-6.1-sol/low通过官方CLI，never审批、只读空目录、关闭所有原生工具/插件/浏览器/设备/MCP/自动装依赖和自动重试；工具请求只能为JSON，交既有host白名单。强制ChatGPT登录并剔除API Key/企业access-token环境回退。每轮STARTED与原生turn.completed的公共输出/usage持久到runtime/secretary-oauth-receipts；不保存私有推理。失败保留UNKNOWN和脱敏错误类型，不自动重放。实际模型可用性需原生推理验收；订阅会话可失效/额度可耗尽，不能承诺永久免重新授权。

health.registry对codex_oauth provider要求NETWORK+SECRETARY_OAUTH，登录文件可读不等于模型健康。验收必须是新owner私聊原生消息→云端OAuth模型完成→结果归档→既有通知owner→私人message_id/server_date，且Mac桥接停用。保持PAUSED/MAINTENANCE、交易额度、已耗尽scope和未知投递不变；不发测试群消息。

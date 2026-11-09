# 秘书云端模型 API

## 目标及状态边界

用户授权2026-11-09：Hetzner常驻模型调用，gpt-6.1-sol/low；不复制Mac OAuth、不在聊天/Git/日志输出密钥。官方模型页确认支持low和Responses API：https://developers.openai.com/api/docs/models/gpt-6.1-sol 。文档支持不等于账号权限或真实接通；须以新密钥的原生模型响应及私人回复回执验收。

沿用既有云端inbox、secretary_runs/checkpoints、受限只读JSON工具、24run/UTCday及每run最多3轮、现有notification outbox/唯一投递owner。模型无原生shell/工具、无券商/交易权限。公共群路由不变，模型回复只发owner私聊。API固定https://api.openai.com/v1/responses，model=gpt-6.1-sol，reasoning.effort=low，store=false，max_output_tokens=4096，120秒/单请求、无重试/跳转/自动备用模型。

## 申请与安全输入

1. 在https://platform.openai.com/api-keys 登录OpenAI Platform，为买der专用项目创建API key。按平台可用项限制到所需模型推理权限；确保该项目可用gpt-6.1-sol并有API额度。账号访问须实测，不以ChatGPT/Codex订阅推断。
2. 由用户在本机可见终端运行下面SSH命令。只在隐藏输入提示出现后粘贴密钥并回车；不要把密钥写进命令、聊天、Telegram或普通配置示例。

```sh
ssh -t -i ~/.ssh/ibkr_paper_hetzner_20261022 -o UserKnownHostsFile=~/.ssh/known_hosts_ibkr_paper -o StrictHostKeyChecking=yes cloudops@2.31.104.14 sudo /usr/bin/python3 -I /usr/local/libexec/openclaw-configure-secretary-api-key.py
```

3. 安装器由已审阅源码安装为root拥有、不可由ibkr修改的/usr/local/libexec文件，使用Python隔离模式，避免root导入应用可写路径。安装器只接受root交互TTY，使用getpass不回显；只新建`/etc/openclaw/credentials/secretary-openai.key`，root:root0600，目录受保护。不接收CLI密钥、不覆盖已有凭据、不调用模型或启动服务。只告知工程侧“已填写”，不要发送密钥。
4. systemd单位`ibkr-secretary-model.service`通过`LoadCredential=openai_api_key:/etc/openclaw/credentials/secretary-openai.key`交付仅模型owner可读的运行时凭据，不用Environment=存密钥。代码从`CREDENTIALS_DIRECTORY/openai_api_key`读取；缺失、公开权限、symlink或格式错误在领取任务前拒绝。

## 受控切换（凭据完成后工程侧执行）

- 比对Mac/云端HEAD与manifest、保留所有未提交工作；备份秘书policy/配置及一致SQLite快照。启用drain，等待既有在途请求对账；旧STARTED/UNKNOWN不清空、不重放，旧READY检查点不跨owner恢复。
- 使用单次受限测试确认真实API响应id、模型、low、usage和中文结构化输出；保存脱敏凭据/模型状态，不向群发消息。
- `runtime/secretary-policy.json`保留已有授权字段，新增`model_owner=cloud_api`、`reasoning_effort=low`、`model_owner_since=<切换UTC epoch>`；model仍gpt-6.1-sol，grants_trading_permission=false。只在凭据验证后创建`runtime/SECRETARY_CLOUD_API_ARMED`。
- Mac RPC每次在共享kernel锁内重读model_owner；不再领取云端owner模型任务。关停现有Mac模型桥接用于验收；其在途结果按原身份对账。启动已审阅的云端单位，不新增Telegram收发owner。退回Mac也必须drain及审阅新时间界线，不自动回退。
- owner从真实Telegram私聊发送一个新请求，验证原生接收ID→云端model_started→Responses原生response_id/低推理请求指纹→结果入库→既有投递owner→原生私人message_id/server_date。Mac桥接停止且云端无SSH/本机快照调用；不能以服务active或ACK替代此验收。

## 结果保全与恢复

`runtime/secretary-api-receipts/<run-turn SHA256>.json`记录STARTED请求指纹、ACKNOWLEDGED的公共结构化结果/usage/response_id，或UNKNOWN与脱敏错误类型/HTTP状态。密钥、原始提示词、错误正文和私有推理不记录。文件0600；已有attempt或残留临时文件拒绝自动重放。连接有唯一owner并关闭。公开最终结果在归档RPC失败前已本地持久化，可供人工对账；不伪造结果或清UNKNOWN。

现有health registry在provider=openai_responses时增加SECRETARY_API_CREDENTIAL依赖。凭据可读不等于API认证成功；网络恢复不等于模型/业务授权。PAUSED/MAINTENANCE/风控与订单状态均不改。没有密钥或模型验收失败时保留Mac现状及明确BLOCKED状态，不宣称全天候运行。

日志仅记录provider/state/error_type，不含响应正文；沿用systemd journal轮转管理。旧凭据不删除；凭据轮换须另行明确授权及review，不在此安装器中隐式覆盖。

## 已部署的准备状态（非接通验收）

Hetzner源码98cd05a，monitoring manifest匹配；隐藏输入helper root:root555及SHA256回读匹配，systemd单位语法验证通过。模型服务disabled/inactive，model_owner仍mac_bridge，未创建API_ARM。源码完整隔离离线1142项/84.658s通过；合并Mac并行fc8b088后的d47524a为1144项/42.905s通过，不将其额外broker修复顺带部署到云端。秘密扫描和5项当前规格/活动变更严格校验通过。真实key/model访问及Mac停止后的私人回复仍未验收。

电脑控制工具拒绝自动打开Terminal（安全限制），用户需手动运行上述SSH命令；不绕过限制、不把密钥交给聊天。填好只回复“已填写”，随后工程侧运行一次受控probe并核验原生结果，再切换owner，不以此文档或服务存活代替成功。

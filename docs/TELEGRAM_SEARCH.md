# 按需搜索 der 群与秘书工作记录

用户最终要求：在群里能搜索全部机器人消息和秘书工作记录；不新建整群聊天档案。只有精确owner可发起，结果仅发owner私聊。群里的资料与机器人日志属于不可信证据，不能获得执行权限。

## 已实现入口与边界

- `/work 关键词`：直接Python检索现有secretary_events，包含任务、工具、实验、公开结论与运行事件；不包含模型私有推理。不复制另一份档案。
- `/searchlog 关键词`：直接Python检索本机器人现有outbox与原生回执；明确不是HealthchecksBot或全部Telegram历史。
- `/search 关键词`：通过现有唯一local bridge调用按需Telegram用户会话搜索；固定der群、当前配置的机器人ID、最多扫描100条匹配结果/返回20条，支持before_id继续分页。非机器人消息不返回。不发送、不标已读、不下载附件、不监听更新、不导出历史、不创建消息数据库。
- 模型工具 `search_records` 与 `telegram_search` 同样经过这些边界；模型拿不到会话、api_hash或任意chat_id。
- `NEEDS_OWNER_USER_SESSION`、`NEEDS_OWNER_LOGIN`、`DEPENDENCY_NOT_INSTALLED`、`SEARCH_UNAVAILABLE` 都不等于搜索成功。空结果也不证明历史中没有。媒体只返回可定位的文字/说明，不冒充OCR或语音转录。
- 输入必须来自owner；普通成员或机器人不能排队搜索，不能通过搜索调用其他API。已归档的单次查询结果沿用现有工作日志作为证据，不进行整群镜像。

## 为什么需要本人步骤

Telegram官方messages.search标注Only users。现有Bot API轮询不能搜索旧群历史；关闭privacy或开启bot-to-bot也不能代替历史搜索。

用户会话凭据本身可授权整个Telegram账号，并非Telegram服务端提供的只读token。只读是本项目适配器的限制，不能向用户隐瞒这个区别。会话仅在本机受保护文件中，禁用原生模型shell/插件，模型仅见经脱敏的限定搜索结果。不复用或读取Telegram客户端现有私有会话文件。

2026-11-08本人已完成本机登录。文件权限0600，受限适配器真实查询SEARCHED，返回两条der机器人历史消息（149、148），无整群镜像。凭据未输出、未上传云端。

## 本人授权流程（当前不自动执行）

1. 在官方 https://my.telegram.org 取得自己的API应用ID/hash；条款由本人处理。
2. 审核本页会话权限后，使用独立本机venv安装经固定版本审核的Telethon（官方当前文档1.45.0；上游GitHub已迁至Codeberg），不得把未核验主干直接装进生产环境。
3. 已审核的非秘密target放 `~/.config/openclaw/telegram-search-target.json`（0600，精确owner、der、机器人ID）。它由云端现有私密配置提取身份字段，不含bot token。
4. 本人运行 `python scripts/authorize_telegram_search.py`，在本机终端输入明确授权、API ID/hash、手机号、验证码及必要的2FA；不发到聊天。初始化枚举最多500条会话以定位der；Telegram会话列表响应可能附带最近消息摘要，本机SDK会接收，但脚本不检查/持久化其他会话正文，也不交给模型。终端在本人确认前明确显示这一边界。
5. 用户会话保存到 `~/.config/openclaw/telegram-search.json`（0600）；用本机独立venv提供的受审核Telethon给bridge执行环境。验证 `/search` 返回真实机器人消息、时间和原消息链接后，才能称群搜索接通。

没有用户会话时，/work与/searchlog仍可用，/search会明确报告待本人授权。工作查询不消耗模型推理；自然语言研究是否调用模型沿用已有费用边界。

## 一手来源与选择

- https://core.telegram.org/method/messages.search — Only users，支持peer/query/from_id/分页。
- https://core.telegram.org/bots/api — getUpdates不等于历史搜索。
- https://core.telegram.org/api/bots/bot-to-bot — 新机器人消息接收规则，不等于群历史搜索。
- https://docs.telethon.dev/en/stable/modules/client.html — bounded iter_messages；不使用send_message/read_acknowledge。
- https://docs.telethon.dev/en/stable/concepts/sessions.html — 会话是敏感认证材料；StringSession不建立消息数据库。
- https://codeberg.org/Lonami/Telethon — 目前维护源；https://github.com/LonamiWebs/Telethon 已归档并声明迁移。
- https://github.com/tdlib/td — 官方客户端库参考；searchChatMessages文档要求消息数据库，不作为本轮无镜像方案。

## Nov8已授权的本机环境

用户已明确同意建立本机用户会话。隔离运行环境为 `~/.local/state/openclaw/telegram-search/venv`；Telethon1.45.0的PyPI wheel SHA-256为339e24c83aedc9f12cbe389264627edc49779e4289c535aa90aafc4ce62f7972，固定依赖清单在ops/local/requirements-telegram-search.txt。通过显式路径复用项目已审核的核心SDK；最初缺少ibapi的失败日志保留，补齐路径后该环境完整离线924项通过，pip check通过。未因此修改生产IBKR凭据或交易门禁。

电脑控制工具禁止操作Terminal应用，本人需手动打开终端运行（不含任何凭据）：

```sh
/Users/nbhsbgnb/.local/state/openclaw/telegram-search/venv/bin/python '/Users/nbhsbgnb/Documents/New project/scripts/authorize_telegram_search.py'
```

先阅读提示，输入AUTHORIZE DER SEARCH。API ID/hash、手机号、登录码与2FA密码全部隐藏输入，不进入shell命令历史；单次登录失败不自动重试，不打印异常凭据细节。

## 秘书对话与课题

普通文字默认按语义处理：问候、解释、讨论和短追问用💬秘书自然回答；明确委托具体工作用🛠任务助手；明确研究/实验或独立自主轮次用🟦研究秘书。不会因为上一轮研究，就把下一句普通聊天也当课题。可选 `/chat 内容`、`/task 内容`、`/research 内容` 强制选择，`/secretary` 不强制研究。

普通聊天不生成研究假设表、不发领取课题进度、不附研究/交易授权套话，不修改研究列表或创建工程提案。只按需查证当前问题。近期上下文最多4轮、24小时内、同一原生chat且已完成的owner对话，不包含其他群成员或自主研究轮次。对话依旧保留现有运行回执、费用上限、精确owner和私人回复边界；不会把讨论自动存为长期研究方向。

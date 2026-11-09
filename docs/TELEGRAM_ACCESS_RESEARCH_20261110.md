# Telegram成员标签、访问控制与定向消息调查

核查日期：2026-11-10 Europe/Berlin。dee connector-lifecycle/connector-audit，只读调查。未安装上游项目、修改群权限、分配实际成员标签、发消息或启用群控制。

## 官方能力

- [Member Tags](https://telegram.org/blog/member-tags-disable-sharing-and-more)：显示成员身份，管理员可控制谁能编辑标签。标签不等于阅读授权。
- [setChatMemberTag](https://core.telegram.org/bots/api#setchatmembertag)：普通成员标签0–16字符；机器人需要administrator及can_manage_tags。
- [Ephemeral Messages and Commands](https://core.telegram.org/bots/api#ephemeral-messages-and-commands)：指定用户和机器人可见的临时交互；用户需使用声明is_ephemeral的命令。任意普通文字或既有群消息不能靠标签回溯变私密。普通机器人在合格动作15秒内可定向回复；administrator可主动定向发送，但消息/编辑不保证离线送达，可能因重启/过期消失。
- [EphemeralMessageParameters](https://core.telegram.org/bots/api#ephemeralmessageparameters)：receiver_user_id/callback_query_id明确指定目标。临时ID可能复用，不能当持久普通message_id或业务幂等键。

结论：可开发“机器人群内私密交互”，不等于一般群聊天逐条按角色永久隐藏。标签、输入权限和输出可见性必须分别设计；频道/私有群成员资格或已核验私聊用于持久分组交付。敏感控制仍采用既有owner私聊，当前授权没有开放群命令。

## GitHub直接检查结果

| 项目与固定版本 | 直接检查的代码 | 可借鉴做法 | 限制与采用边界 |
|---|---|---|---|
| [obervinov/users-package](https://github.com/obervinov/users-package/tree/88f73da178a9de86ebfcda0bc0b25d9e9b953b6f) | users/users.py（blob8ceb9b4），access_control与user_access_check | from_user身份→认证→角色权限→限流→执行；按用户ID记录结果 | 应用接口授权，不会隐藏普通群消息；Vault/PostgreSQL不是本项目必要新增依赖 |
| [skrashevich/botmux](https://github.com/skrashevich/botmux/tree/0e032739ee0f221da25dcb19bb4bca4d06ec129e) | internal/models/models.go（blob5fa30f3）；docs/en/features/user-tags.mdx（blob3433b6c） | 每群每人可多标签；UserTag(ChatID,UserID)与后台User.Role独立，配合审计与管理界面 | 标签是该管理系统的分类数据，不能称为Telegram阅读ACL；其多机器人/代理/LLM路由不直接引入现有单owner链路 |
| [go-telegram/bot](https://github.com/go-telegram/bot/blob/main/methods_params.go) | SendMessageParams.EphemeralMessageParameters（文件blob89ad1fe） | 使用原生定向发送字段，不依靠删除公开消息制造隐私 | 只是客户端API能力；不证明我们的Python链路/设备已验收，也不要求迁移Go |
| [aiogram/aiogram issue1897](https://github.com/aiogram/aiogram/issues/1897) | 维护仓库中的最小复现，涉及3.31.0 | 测试机器人发出的临时消息回复应取receiver_user，不混淆from_user里的机器人 | 这是上游缺陷报告，未在本机复现、未裁定所有版本受影响；作为接入回归风险 |

补充：[node-telegram-bot-api官方中间件示例](https://github.com/yagop/node-telegram-bot-api/blob/master/examples/09-middleware.ts)在处理器前检查user ID白名单；示例白名单为空时开放访问。本项目设计必须空配置拒绝，不复制其演示默认值。以上为源码/文档审阅，不是安全审计、安装推荐或运行验收。

## 本项目只读核验

实际云端python-telegram-bot22.8；Bot.send_message没有显式ephemeral_message_parameters或receiver_user_id参数，存在set_chat_member_tag方法。现有send_one只调用常规send_message/send_document/send_media_group，没有临时消息接入；额外底层api_kwargs能力本轮未验证。getChatMember原生回读：秘书bot为member，没有can_manage_tags管理权。群名deehub，现有原生owner私聊仍是控制入口。

| 能力 | 官方支持 | 代码现状 | 配置/权限 | 实际验收 |
|---|---|---|---|---|
| 现有owner私聊身份校验 | 是 | 已有 | 已配置 | 已有独立证据，本轮未发验收消息 |
| 成员可见标签 | 是 | SDK有方法，业务未接 | bot缺管理权 | 未配置、未修改权限 |
| 应用内用户ID/角色/数据类别授权 | 可开发 | 现有仅owner控制边界，无多成员角色注册表 | 未新增授权 | 设计待实施 |
| 群内定向临时消息/命令 | 是 | 未接入；SDK显式签名不支持 | bot为普通成员，主动广播条件不满足 | 未发送/未验收 |
| 标签控制普通群消息永久可见性 | 官方所查接口无此ACL | 未实现 | 标签本身不提供 | 不承诺 |

建议本项目按“稳定ID注册表→能力校验→发送前内容分类→已核验目的地→追加投递审计”组织。公开内容发deehub，个人账户/安全/立即生效风控与即时聊天走本人私聊；少数研究协作者未来按单独批准的数据类别进独立持久目的地。多成员权限尚在研究，本轮不改变既有账户日报收件人。

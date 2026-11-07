# 日报发送状态与故障日志

用户于2026-11-07确认定时发送实际正常，保留每天北京时间09:00（当前柏林02:00），不改为柏林09:00。09:00:02的原定日报有Telegram原生接收回执；后续修正版另有独立回执。不能把手机未弹窗、误看时间或主动修改报告等同于发送失败。

当前数据库runtime/recovery.sqlite3：

- notification_outbox：每次排队、STARTED、UNKNOWN、TELEGRAM_ACCEPTED等原始状态。
- notification_receipts：原生Telegram消息编号、目标chat和服务器时间。
- report_delivery_status：每份日报/周报/月报及补报的最近核对状态。
- report_delivery_events：状态/回执变化的完整历史，内容指纹防重复，保留重启前记录。
- module_events：统一故障/模块日志中event=REPORT_DELIVERY_STATUS、module=REPORT的发送证据；不创建虚假故障、不把REPORT/交易健康标绿。

由现有唯一通知owner每60秒对最近40份报告记录进行核对，无新常驻worker、无网络请求、无重复补发。新增Telegram `/report`直接由Python显示今日计划、原定发送结果及最近补发回执，同时显示北京时间和柏林时间。查询不通过模型，不触发发送。

只有TELEGRAM_ACCEPTED并有匹配原生消息ID和服务器回执才显示“Telegram已接收”；UNKNOWN必须对账、不重放；缺失/损坏回执不能称已验证成功。服务端接收不保证手机弹窗。

本次用户原先要求快速补发，随后澄清原定发送正常。已请求的历史快照说明版在柏林14:50:24获Telegram回执，之后不再补发。其数据明确标注截至柏林07:08:28：当时起IBKR上游2110、回读不完整，不能把该旧快照称为当前余额。该上游问题与已成功的原定日报投递分开记录；未重启正常Gateway或改交易门禁。

# 容量最小发布 · 2026-11-11

Base是云端精确c1f95fa82bdf650e458e7ff28c6919d2a1a96610，抽取86d6658已测核心七文件，补新human通知政策。无新依赖、数据库schema、daemon、券商连接或sender。canonical清单e62a3f2和后续归档工程不是本发布依赖。

## 当前证据

统筹2026-11-11T02:22:15Z只读：root39956590592/used30966878208/available7334043648bytes、df81%，state22006779904bytes，cloudc1f95fa。此前容量工程独立只读available7344984064；79%/7.78GiB为旧样本。只有非连续快照，增长/距满UNKNOWN，不能线性外推成快满。四有效业务库已沿现有工具逐库schema/query85/5/40/27回读；历史副本不删。

## 行为

现有secretary_observations每60秒检查、最多每300秒采样。runtime/capacity.json最多288样本/1MiB，连接mode=ro/query_only，固定DB metadata/固定表COUNT每库80ms共享预算、10ms锁等待；未知不补0。每小时250ms/20000entries有界文件metadata扫描。共享CAPACITY模块900秒失效，秘书capacity工具只读已存快照，不触发扫描或修改交易门禁。

空间warning<=25%或8GiB，critical<=10%或2GiB；持续>=1h且同FS/连续间隔<=900秒才估计正消费距满。DB/row/error增长与WAL阈值是待实测校准的初始预算；下降需连续3个有余量样本。普通warning/恢复只入既有incident_events/cursor，不创建OPEN incident或outbox，因此通用reminder不会把普通短状态外发。仅critical需行动入现有outbox，private_notice/requires_response=true，旧sender原生私聊；去重/UNKNOWN规则保留。

旧86的capacity-public-view.patch强制普通容量群摘要，已被新human政策替代，不需要也不能并入本次。研究成果/完整日报/最新链路置顶由通知owner负责，本模块不再新增群路由。现有只读交互回复走既有owner会话。

## 唯一publisher的验收入口

- 在当前组合linked树完整运行run_worktree_tests.py、gitleaks、strict spec和diff检查；本分支测试不替代组合树。
- Git发布/manifest身份核对后，仅在Gatewayowner窗口允许时reload既有inbox/model相关owner；不碰Gateway或交易scope。
- 观察一个fresh容量快照、CAPACITYhealth和本机文件权限；调用现有cloud dispatcher的capacity读取，确认当前disk和采样时间。
- 用用户已授权原生owner会话询问秘书容量，核验真正的model工具选择、结果归档、既有sender私聊原生回执；不借已消费/codex scope，不制造满盘/critical或伪造USER消息。
- 当前81%按策略应warning，仅后台archive；不能以没有主动Telegram告警认为监测未工作。>=1h持续速率和自然critical/private提醒验收单列。

回滚只通过Git还原源与对应monitoring identity，保留capacity.json、incident cursor/event和任何UNKNOWN；不restore整库、不清历史、不重放。部署和原生结果由publisher记录，候选源码不能自称已经上线。

## 官方生命周期研究（后续优化来源，不是本波清理）

SQLite WAL官方说明长读事务可能阻碍checkpoint，WAL是持久状态组成部分，故本任务不手工清WAL/强制checkpoint。https://www.sqlite.org/wal.html

systemd journald有独立磁盘上限及保留空闲空间规则；Python RotatingFileHandler支持明确文件大小/数量边界。后续仅对白名单的新可再生日志/cache设预算，不能用全机journal轮转删除旧审计证据。https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html https://docs.python.org/3.13/library/logging.handlers.html

restic官方区分仓库结构check与完整/分片数据校验；归档将借鉴内容校验、分批验证和恢复演练的分层，不把‘文件存在’当校验通过，也不引入新付费服务。https://restic.readthedocs.io/en/stable/045_working_with_repos.html

# 数据库只读管理页面

页面生成器 `scripts/database_console.py`，数据读取模块 `reporting/database_console.py`。固定展示交易审计、财务、监控恢复以及尚未创建的秘书档案库，不读取账户载荷、密码或令牌。

- `--root`：按需采集固定state路径，单条SQL默认100ms预算、连接等待100ms。
- `--json`：导出可复查JSON快照；`--input`：从已有快照渲染HTML。
- `--output`：写入单独报告目录，不指向数据库文件。
- 不启动service，不连接IBKR，不修改数据库，不执行完整性全扫、checkpoint、VACUUM或恢复。
- DB/WAL文件mtime与声明表中的业务时间分别显示；后者不宣称是整个数据库的精确最后提交时间。
- 备份任务记录、备份文件存在、哈希已记录、哈希已复算、完整性通过是不同事实。当前页面不做后两项验证，不把历史备份成功当成实时库PASS。
- HTML是静态快照，不会因浏览器刷新自动重新采集；标题显示采集UTC时间。时区与柏林时间相差当前1小时。

示例（云端审核后的工作区执行，只输出JSON；不会启动新owner）：

```sh
/opt/openclaw/venv/bin/python /opt/openclaw/app/scripts/database_console.py --root /home/ibkr/.local/state/openclaw --json
```

保存JSON后，本机渲染：

```sh
python3 scripts/database_console.py --input /absolute/report/database-status.json --output /absolute/report/database-status.html
```

当前备份是同一台云主机上的每日在线备份。异地备份需独立存储故障域、传输/存储加密、独立的最小权限、保留策略与恢复演练；现阶段未配置目的地，不创建存储账户或付费资源。

本轮验证：linked worktree中821项完整离线测试通过，gitleaks通过。生产主工作区仅quick smoke，仍尊重PAUSED/MAINTENANCE。

## 通知收件箱（2026-11-07）

`runtime/recovery.sqlite3` 继续保存 `incident_events`、`incidents`、`notification_outbox`、`notification_delivery` 和 `notification_receipts`。新增 `notification_read_state(notification_id,read_at)` 为owner本地已读标记，`notification_preferences(category,enabled,updated_at)` 为分类偏好；无Telegram阅读回执假设。最新状态以incident_key+generation分组，未来更新重新未读。SUPPRESSED表示用户偏好未投递，无HTTP回执。详见 [通知中心](NOTIFICATION_CENTER.md)。

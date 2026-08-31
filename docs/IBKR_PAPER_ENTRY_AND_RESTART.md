# IBKR Paper 统一入口与每日重启

## 推荐入口

统一使用：

```bash
./scripts/paper_platform.command install
./scripts/paper_platform.command status
./scripts/paper_platform.command safe-api
```

`install` 安装用户级 macOS LaunchAgent：登录 macOS 后自动打开本机 TWS；如果 TWS 意外退出，最多约五分钟后重新打开登录窗口。它不会填写用户名、密码或 2FA，不会启动 Python 交易 API，也不会启动订单 Agent。

`safe-api` 只以 DEV_LOCK 启动 Python API：`TRADING_MODE=PAPER`、kill switch 开启、Paper transmission 关闭、session token 清空。需要从虚拟机访问 API 时，macOS 对 Python 的入站网络授权可能仍需人工确认一次；只在本机使用时应保持监听 `127.0.0.1`。

## TWS 内只需设置一次

1. 手工选择 **Paper Trading** 登录，确认界面是 Paper 而不是 Live。
2. 打开 **File → Global Configuration → Lock and Exit**。
3. 选择 **Set Auto Restart Time**，安排在不运行策略的夜间维护窗口。
4. 打开 **API → Settings**，确认 Socket API 已启用且端口是 `7497`；不要把 Live 默认端口 `7496` 配给本项目。
5. 保持 API 仅允许 localhost，除非经过独立网络安全设计。

IBKR 不支持自动登录或无 GUI 登录。官方 Auto Restart 可让 TWS 在一周内每日自行重启，但通常每周日仍需重新手工认证，安全 token 被撤销时也必须人工认证；不要用脚本保存密码、点击 2FA 或绕过这项限制。

## 日常流程

1. macOS 登录后，LaunchAgent 自动打开 TWS。
2. 若出现登录页，人工选择 Paper 并认证；若已处于一周内有效会话，TWS 使用官方 Auto Restart。
3. `paper_platform.command status` 显示 `PAPER_API_PORT_REACHABLE` 后，再启动 DEV_LOCK API。
4. 只有独立的 Paper readiness、DU 账户、审计、风险门和当日 session token 全部通过后，才允许使用现有控制菜单解锁 Paper Agent。

## 停用自动打开

```bash
./scripts/paper_platform.command uninstall
```

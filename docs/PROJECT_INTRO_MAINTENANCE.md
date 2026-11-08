# 项目简介维护记录

日期：2026-11-08。

新增中文零基础简介，并在 README 顶部设置入口。参考 Backtrader 与 QuantConnect 官方入门文档的渐进示例、分阶段学习方式；来源和维护规则保存在简介末尾。

验证：linked worktree `/private/tmp/der-beginner-intro` 中运行 `python scripts/run_worktree_tests.py`，943 tests / 83.219s / OK；`pre-commit run gitleaks --all-files` 通过；简介本地链接存在，Git diff 无空白错误。

主工作区只读 smoke：NOT_READY；PAUSED 与 MAINTENANCE 保留。没有启动服务、发送通知或下单。此次仅维护文档，不代表云端验收或部署批准。原有未跟踪文件保留。

完整本地验证日志：`/private/tmp/der-intro-review/offline-tests.log`、`/private/tmp/der-intro-review/secret-scan.log`；临时目录可能由系统清理，本纪要保留检查摘要。

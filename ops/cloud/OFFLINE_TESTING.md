# 隔离离线测试

完整测试只允许在 linked worktree。使用专用 `.venv`，不要依赖系统 python3 的版本或全局包。

本次已验证环境：Python 3.13、官方 IBKR SDK 10.51.01 的 ibapi 1051.1、protobuf 5.29.5（ops/cloud/requirements-runtime.txt）。SDK 使用既有云部署的 `/opt/openclaw/tws-api/source/pythonclient` 源码副本；不使用 PyPI 同名旧包，不复制任何配置、凭据或生产状态。

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install /path/to/reviewed/pythonclient -r ops/cloud/requirements-runtime.txt
.venv/bin/python scripts/run_worktree_tests.py
```

runner建立临时state/DB，并禁止真实IPv4/IPv6连接。安装依赖阶段可以联网；测试阶段不得替换runner或指向生产DB。不得用测试通过替代生产权限或Paper验收。

2026-10-23 实测：Python 3.13.7；SDK源码归档SHA256 `6bff80031b83c0f7649c3f45ee3d11fed2c0528c3be8a50e0d3287c04348a275`。此值标识从既有云部署取得的源码归档，并非原安装包哈希；原安装包哈希仍见requirements-runtime.txt。环境修复后完整基线520项通过。

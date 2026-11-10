# 手动离线核验已有备份副本

该工具只检查已有归档，在调用者指定目录下创建新的私有副本和收据。它不连生产、不联网、不启动worker、不改配置、不恢复数据库，也不清理任何原件或旧副本。不加入本轮云端WaveB发布。

输入为未压缩`.tar`，只含这五个普通文件：

- `backup.json`
- `trading_audit.sqlite3.gz`
- `financial_ledger.sqlite3.gz`
- `recovery.sqlite3.gz`
- `agent_secretary.sqlite3.gz`

这是现有备份owner输出的最小导出格式，不是任意备份目录；不要把凭据、OAuth缓存或SSH文件打包进去。取得归档的传输和身份核验由已有授权连接负责。本工具不会把归档里的声明当成权限。

```sh
python scripts/verify_state_backup.py /private/path/export.tar \
  --output-root /private/path/checks \
  --expected-archive-sha256 VERIFIED_SHA256_HERE
```

输出目录需已存在。每次运行独占创建一个`backup-check-*`子目录（0700），数据库和`receipt.json`为0600；不会覆盖现有库或历史收据。退出0/state=CHECKED_COPY表示四库解压字节与manifest匹配，且隔离副本SQLite quick_check通过。退出2表示失败，错误只输出固定代码；本次私有部分副本和失败收据保留，不自动重试或删除。

边界：200MiB原tar、4MiB manifest、每gzip50MiB、每解码库512MiB、合计2GiB，整体60秒/每库SQL20秒的协作式期限（在读取和SQLite进度回调处检查，不是内核I/O的强制中断）。拒绝额外/重复/穿越名称、链接、稀疏成员、缺失库、模糊manifest及过量展开。只从已允许的普通成员读取字节，不使用extract/extractall恢复归档路径；Python文档说明extractfile本身也可能读到链接，因此工具先独立验证成员类型。[Python tarfile](https://docs.python.org/3.13/library/tarfile.html#tarfile.TarFile.extractfile)

SQLite仅打开刚生成、已关闭写入且由核验器独占的副本，使用mode=ro、immutable=1、query_only及进度期限；immutable不会用于live/任意既有数据库，因为SQLite对该选项的前提是文件不会变化。[SQLite URI参数](https://www.sqlite.org/uri.html)

成功收据始终保留以下否定边界：

- `source_authenticated=false`：SHA与同包manifest相符不证明来源真实；外部可信SHA匹配也不等于本工具实施了身份认证。
- `cross_database_consistency_verified=false`：四个独立快照不等于跨库业务一致；原manifest的原子性声明仅记录为declared。
- `grants_restore_permission=false`、`live_restore_performed=false`：没有生产恢复许可或恢复动作。旧STARTED/UNKNOWN只是原始字节的一部分，不清除、不重放。

源数据、归档和业务关系对账、备份时点/RPO、最新回执覆盖、恢复环境/manifest以及原生券商敞口必须单独审阅。手机/iPad长期后台同步、断点续传、持续异地复制、Passkey审批和全部设备丢失恢复仍不由本工具实现。不要将其称为灾难恢复或全系统冗余验收。

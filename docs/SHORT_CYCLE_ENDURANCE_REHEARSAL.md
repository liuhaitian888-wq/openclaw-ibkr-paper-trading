# 短周期连续运行演练

## 目的与边界

`scripts/run_short_cycle_endurance_simulation.py` 对 7 天连续运行所需的关键故障路径做离线缩短演练。它使用 `trading/pool_state.py`、`trading/risk.py`、`trading/data_quality_gate.py`、`trading/sqlite_event_store.py` 的正式逻辑，但不会连接 IBKR/TWS、启动 Agent 或提交订单。

## 可验证链路

每个周期按统一证据顺序写入 SQLite 和 `timeline.jsonl`：数据质量 → 六层状态迁移 → 策略信号 → 风控决定 → 模拟执行状态回调。中途会保存并重新载入 `canonical_pool_state`，以验证重启恢复；`replay_query.sql` 能按时间线查询状态迁移和事件库。

## 注入的故障

- 空数据、API 回调错误、缺失 ask；均进入 `SAFE_MODE`，禁止新增风险。
- 恢复后需连续两次新鲜报价；第一条新鲜数据仍为 `RECOVERING`。
- 零数量与超最大数量；由 `RiskEngine` 拒绝。
- 重启恢复；从 SQLite 重新加载正式六层状态。

## 如何运行

```bash
python scripts/run_short_cycle_endurance_simulation.py --cycles 8
```

输出目录默认为 `.runtime/short_cycle_simulation`，其中的 SQLite、JSONL 和 SQL 是运行产物，不提交 Git。成功条件是 `result=PASS`、`paper_orders_submitted=0` 与 `live_orders_submitted=0`。

## 不能由此证明的事项

此演练不能证明 TWS 连续七天可用、IBKR 行情权限覆盖全部股票、真实网络重连、真实成交/部分成交或真实账户对账。它是进入更长 Paper 演练前的可重复故障测试，不是七天认证。

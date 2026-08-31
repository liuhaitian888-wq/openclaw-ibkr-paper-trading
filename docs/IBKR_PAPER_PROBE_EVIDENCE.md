# IBKR Paper 真实只读探测证据

探测日期：2026-08-31。探测发生在 Paper TWS 的 `7497` 端口；所有探测均只读、完成后取消订阅并断开，未发送、修改或取消任何订单。

## 已实测

| 能力 | 请求 | 结果 |
|---|---|---|
| Paper API 与账户摘要 | `tws_readonly_check.py` | 握手和账户摘要回调成功；账户标识未记录在本文件。 |
| L1 `reqMktData` | AAPL、MSFT、SPY，5 秒 | 3/3 合约解析成功、实时类型为 `1`、无权限或 pacing 错误；首个 tick 延迟约 269–1363 ms。 |
| tick-by-tick | AAPL BidAsk | 收到至少一个真实事件且没有 API 错误。 |
| IBKR Scanner | `TOP_PERC_GAIN` / `STK.US.MAJOR` | 返回 10 条真实结果，约 1720 ms，无错误；扫描订阅已取消。 |
| L1 并发容量 | 当前 71 标的 Universe | 3、6、12、24、48、71 条均完整收到真实 tick；无权限、pacing 或断流错误。71 是当前 Universe 覆盖上界，不是账户理论 Market Data Lines 上限。 |
| snapshot | 1 与 3 标的 | 本地付费快照安全开关阻止请求；零条返回、未产生付费请求，因此是“未实测”而非失败。 |

## 未实测或未实现

- `trading.auto_open_pipeline.run_ibkr_scanner` 仍使用本地 fixture，明确标记 `live_tws_scanner_request_used=false`；真实探测由 `scripts/audit_ibkr_scanner.py` 完成，尚未接入自动候选管线。
- 当前 71 标的 Universe 已通过一次 71 并发 L1 实测；账户理论 Market Data Lines 上限仍未知，只有 Universe 扩大后继续递增探测才能确定。
- 当前 Settings 为 `DRY_RUN` 且没有交易 session token；真实 Paper 下单保持被硬门拦截。

## 可重复命令

```bash
python tws_readonly_check.py --host 127.0.0.1 --port 7497
python scripts/audit_ibkr_level1_streaming.py --symbols AAPL,MSFT,SPY --seconds 5
python scripts/test_ibkr_tick_by_tick.py --symbol AAPL --tick-type BidAsk
```

这些命令仅验证连接和行情能力；不得把它们作为订单授权。

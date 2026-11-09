# 股票、FX交易头寸与实际现金分开核验

## 触发事实

Paper DUQ503649的已确认现金换汇保留了券商CASH EUR/USD位置-64414。原监测以symbol→quantity遍历全部position，导致EUR被当作缺股票保护、USD股价未知的持仓。2026-11-09当前真实回读证明identity/四项end完整、dirty=false，EUR conId12087792、sec_type=CASH、currency=USD；并非凭文件名或负数猜类型。

[IBKR官方说明](https://www.ibkrguides.com/traderworkstation/fx-portfolio-virtual-fx-position.htm)区分FX Portfolio交易头寸与Market Value实际币种余额：前者用于货币对交易成本/损益追踪，不能当成实际现金。此前换汇的实际现金收据与负虚拟交易头寸同时保留，不能删除一方来让检查变绿。

## 本次实现范围

- 保留原始positions/contracts；共享纯投影分为有身份的证券、FX_PAIR_POSITION、UNSUPPORTED_OR_UNVERIFIED。
- 只有明确CASH、正整数conId、已知且不同的fiat base/quote才视作货币对；不按EUR字符串或正负号排除。金属、未知币种、缺失/冲突身份仍未支持并继续阻止相关准入。
- 股票保护与USD证券gross不把已识别货币对当股票；所有外部挂单继续计入，活动CASH/未知订单使股票专用敞口计算失败。现金和汇率风险仍通过独立资金与账户检查，不把FX数量换算为可用现金，也不计入策略净收益。
- 精确execId只允许补齐此前缺少的conId/currency/sec_type，旧已知身份或经济字段变化仍失败；原生callback保存类型，重启仍需完整回读。
- 只有完整回读后才可把旧的“EUR缺股票止损”误分类事件记为不适用/已厘清；FX事实仍可见，现有股票缺保护事件不因此消失。
- /holdings、/ready展示FX事实及未知持仓，不认领继承仓，不修改订单，不更改PAUSED/MAINTENANCE或正式manifest。

## 保留的P0

该修复只是typed broker facts，不是完整策略所有权/canonical生命周期验收。完整持续executor原子预算、外部订单准入与资金预留、所有适用币种的新鲜现金/结算资金、五只旧仓真实保护和部分成交/重启联合验收仍独立未收口。附加S/G为空时仍须整体账户风险验证，不能以字段为空绕过外部FX活动单；此执行接线检查属于持续executor任务。

## 验证与部署

完整隔离1063项/76.618s/OK；资源回归FD5及恢复FD4/线程1→1保持；gitleaks与5项OpenSpec strict通过。Git整合与原生结果待追加。生产部署前比较有限保护scope依赖，保持原权限、到期及提交预算；不重放已FILLED换汇。现有提醒/周报及第三方研究结果保持独立。

实际云端源码9f66cd8，监测/Gateway/保护scope身份验证PASS，8个保护核心依赖逐字节一致，scope只换commit；原保护到期/数量/预算与已用完的换汇scope不变。仅优雅重启既有paper-safety和inbox，Gateway1450345不变。原生四项end完整、dirty=false、0.13秒级服务回复；六只股票/活动订单/成交经济字段部署前后相等。EUR/USD -64414单列、unsupported0、EUR缺股票保护误报RESOLVED，PFE仍受原保护，其他五只仍未取得原生保护回执。新回调仅补齐成交类型，不新造成交。

独立只读客户端在同一准确Paper账户取得新的USD与EUR ledger end；部署身份与kernel owner验证后复读，USD2019.4231/EUR943040.605，两者无现金负债。券商记账参考USD→EUR0.8970107，2000USD≈1794.0214EUR，不是可执行bid/ask换汇报价；本次不更新持续准入cashbook或创建新的换汇操作。所有原始收据及部署前SQLite备份保存在engineering/typed-portfolio-20261109。

当前无未知券商订单，旧delivery UNKNOWN1继续保留且不重放；股票全自动仍未放行，2.2—2.5未因本子任务验收而勾选。

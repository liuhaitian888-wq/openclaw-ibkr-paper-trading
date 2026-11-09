# 股票价值日与费用资金边界：研究记录

核验2026-11-09；这是研究证据，不是新的交易/换汇授权或资金放行。现有原生USD日表为11月9日-69788.66、11月12日累计2019.42306；原生普通现金2019.4231不能覆盖这项差异，也不能把两项累计余额相加。

[IBKR账户类型说明](https://www.interactivebrokers.com/en/accounts/configuring-your-account.php)要求现金账户覆盖交易成本和佣金，并描述FX资金可用存在结算延迟。[IBKR利息计算说明](https://investors.interactivebrokers.com/en/pricing/pricing-calculations-int.php)区分交易和结算日期。两者只证明必须按币种、成本和日期核对，不能单独确定本Paper账户下一张股票买单的资金价值日。

搜索发现部分IBKR glossary仍出现美国股票T+3，不能因为是官方域名就将陈旧示例写入当前交易日历。当前美股一般T+1应以[SEC投资者结算说明](https://www.investor.gov/introduction-investing/investing-basics/glossary/settling-securities-transactions-t1)及交易/美元结算假日核验；一般周期仍不等于某张订单已核实的精确价值日。

搜索命中form3207“购买币种可与证券同日结算”的条款，但实际打开的[IBUK/IBLLC协议](https://ndcdyn.interactivebrokers.com/Universal/servlet/Registration_v2.formSampleView?formdb=3207)首页明确为Institutional Clients。本次不能证明它适用于这个个人账户，因此不据此解除门禁。账号原生AccountType=INDIVIDUAL也不是法律主体或保证金权限证明。

尚缺：账户实际适用法律主体/资金规则、股票成交价值日的可审计来源、佣金/费用扣款价值日、已有外部义务和账户全基线。需证明每个到期日不增加借款；不能简单假定“等到12日以前绝对不能交易”，也不能反向假定“同日结算一定可以”。未验证时沿用保守资金门禁，不增加FX或借款，不把what-if保证金数当作现金结算许可。

"""Entirely synthetic, self-contained fixture. No real financial input is read."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

def metric(value):return {'value':value,'status':'AVAILABLE','source':'SIMULATION','as_of':'2026-09-07T09:00:00+08:00','currency':'USD'}

def report(root=None,kind='DAILY',now=None):
    now=now or datetime(2026,9,7,9,tzinfo=ZoneInfo('Asia/Shanghai'))
    m=lambda v:{**metric(v),'as_of':now.isoformat()}
    pnls=[32,-18,44,0,-12,37,25]
    trend=[{'date':(now.date()-timedelta(days=7-i)).isoformat(),'net_liquidation':12000+sum(pnls[:i+1]),'daily_pnl':p,'currency':'USD'} for i,p in enumerate(pnls)]
    period={'start_date':trend[-1]['date'],'end_date_exclusive':now.date().isoformat(),'partial':False,'timezone':'America/New_York'}
    a={k:m(v) for k,v in {'net_liquidation':12108,'total_cash_value':9800,'available_funds':11200,'buying_power':22400,'daily_pnl':25,'realized_pnl':-12,'unrealized_pnl':120,'gross_exposure':2308,'positions':2}.items()}
    act={k:m(v) for k,v in {'turnover':90,'shares_traded':4,'fills':2,'buy_turnover':50,'sell_turnover':40,'commissions':1.2,'orders_submitted':3,'filled_orders':2,'cancelled_orders':1,'rejected_orders':0}.items()}
    act.update(state='FILLS',coverage_complete=True,currency='USD',commission_currency='USD')
    perf={k:m(v) for k,v in {'pnl':25,'return_pct':.21,'net_liquidation_change':25,'realized_pnl':-12,'unrealized_pnl':120,'max_drawdown_pct':-.15,'win_rate':50}.items()}
    perf.update(best_day=trend[-1],worst_day=trend[-1],observed_pnl_days=1,expected_trading_days=1,complete_daily_pnl=True,currency='USD',trend=[trend[-1]])
    risk={k:m(v) for k,v in {'max_exposure':2500,'risk_events':0,'rejected_orders':0,'data_quality_incidents':0}.items()}
    risk.update(currency='USD',protection={'text':'保护覆盖完整 / Protected','status':'PROTECTED'},protection_history=[{'source':'SIMULATION'}])
    return {'report_type':kind,'report_date':now.date().isoformat(),'trading_period':period,'generated_at':now.isoformat(),'account':a,'activity':act,'performance':perf,'risk':risk,'trend':trend,'attention':['保护覆盖已核对 / Protection coverage reviewed','现金与敞口已核对 / Cash and exposure reviewed','仅为模拟数据 / Simulation data only'],
            'paper_readiness':True,'runtime_state':'IBKR_CONNECTED (MOCK)','source_snapshot_at':now.isoformat(),'provenance':{'source':'SIMULATION ONLY'},'simulation':True}

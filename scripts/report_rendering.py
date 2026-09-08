"""Bilingual portrait financial reports; presentation-only rendering."""
from __future__ import annotations
import html
import json
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from scripts.daily_visual_report import render_png, png_dimensions


def esc(v):return html.escape(str(v))
def value(m,percent=False):
    v=m.get('value') if isinstance(m,dict) else m
    if isinstance(m,dict) and m.get('_money'):
        currency=m.get('currency')
        if not currency or v is None:return 'MISSING'
        return f'{esc(currency)} {v:,.2f}'
    if v is None:return 'MISSING'
    if isinstance(v,int):return f'{v:,}'
    if isinstance(v,(int,float)):return f'{v:,.2f}'+('%' if percent else '')
    return esc(v)

def tone(m,directional=False):
    v=m.get('value') if isinstance(m,dict) else m
    status=m.get('status','') if isinstance(m,dict) else ''
    if (isinstance(m,dict) and m.get('_money') and not m.get('currency')) or v is None or status in {'MISSING','STALE','UNAVAILABLE','UNKNOWN'} or (isinstance(v,str) and any(t in v for t in ('MISSING','unavailable','STALE'))):return 'muted'
    if directional and isinstance(v,(int,float)):return 'positive' if v>0 else 'negative' if v<0 else 'neutral'
    return 'neutral'

def kpi(zh,en,m,percent=False):
    status=m.get('status','') if isinstance(m,dict) else ''
    if isinstance(m,dict) and m.get('_money') and not m.get('currency'):status='Currency unavailable'
    display=value(m,percent)
    if isinstance(m,dict) and m.get('_money') and m.get('currency') and m.get('value') is not None:
        display=display.replace(' ', '<br>', 1)  # Keep currency/amount wrapping consistent without changing fonts or columns.
    return f'<div class="kpi"><div class="zh">{esc(zh)}</div><div class="en">{esc(en)}</div><strong class="{tone(m, any(t in en for t in ("PnL","Return","Δ")))}">{display}</strong><small>{esc(status)}</small></div>'

def panel(zh,en,body,cls=''):
    return f'<section class="panel {cls}"><h2>{esc(zh)} <span>{esc(en)}</span></h2>{body}</section>'

def item(zh,en,m):return f'<div class="item"><span>{esc(zh)} <i>{esc(en)}</i></span><b class="{tone(m, any(t in en for t in ("PnL","Realized","Unrealized","drawdown")))}">{value(m)}</b></div>'

def activity(r):
    a=r['activity'];state=a['state'];kind=r['report_type']
    if state=='NO_FILLS':
        body='<div class="empty">'+('今日无成交' if kind=='DAILY' else '本期无成交')+'<span>'+('No fills today' if kind=='DAILY' else 'No fills this period')+'</span></div>'
    elif state=='MISSING':
        body='<div class="empty">暂无可确认成交记录<span>No confirmed fills available</span></div>'
    else:
        body='<div class="metrics three">'+''.join(kpi(z,e,a[k]) for z,e,k in [('总成交额','Turnover','turnover'),('成交股数','Shares traded','shares_traded'),('成交笔数','Fills','fills')])+'</div>'
        body+='<div class="rows">'+item('买入 / 卖出','Buy / Sell turnover',value(a['buy_turnover'])+' / '+value(a['sell_turnover']))+item('佣金','Commissions',a['commissions'])+'</div>'
    body+='<div class="orders">'+item('提交订单','Orders submitted',a['orders_submitted'])+item('成交 / 撤销 / 拒绝','Filled / Cancelled / Rejected',' / '.join(value(a[k]) for k in ['filled_orders','cancelled_orders','rejected_orders']))+'</div>'
    body+='<div class="note">'+esc(a.get('currency') or 'Currency unavailable')+', '+('完整成交覆盖 / complete coverage' if a['coverage_complete'] else '仅已记录数据 / recorded observations')+'</div>'
    return body

def risk(r):
    q=r['risk'];p=q['protection'];status=p['status']
    return '<div class="coverage"><strong>'+esc(p['text'])+'</strong><span class="badge">'+esc(status)+'</span></div>'+''.join(item(z,e,q[k]) for z,e,k in [('最大敞口（采样）','Max observed exposure','max_exposure'),('风控事件','Risk events recorded','risk_events'),('拒绝订单','Rejected orders','rejected_orders'),('数据事件','Data incidents recorded','data_quality_incidents')])+f'<div class="note">保护历史 / Protection observations: {len(q["protection_history"]) or "unavailable"}</div>'

def attention(r):
    return '<ol>'+''.join('<li>'+esc(t)+'</li>' for t in r['attention'][:3])+'</ol>' if r['attention'] else '<div class="empty">暂无可验证结论<span>No verified attention items</span></div>'

def performance(r):
    p=r['performance'];body=''
    for label,en,k in [('最佳日','Best day','best_day'),('最差日','Worst day','worst_day')]:
        d=p[k];body+=item(label,en,f'{d["date"]}. {value(d["daily_pnl"])}' if d else None)
    body+=item('已实现盈亏（期末）','Realized at close',p['realized_pnl'])+item('未实现盈亏（期末）','Unrealized at close',p['unrealized_pnl'])
    if p['win_rate']['value'] is not None:body+=item('胜率','Win rate',value(p['win_rate'],True))
    else:body+='<div class="note">胜率、策略归因：unavailable / no reliable closed-trade linkage</div>'
    return body

def trend(points,compact=False):
    # Missing days break lines; daily bars keep independent scales from equity.
    w,h=1064,340;pad=40
    currencies={p.get('currency') for p in points if p.get('net_liquidation') is not None or p.get('daily_pnl') is not None}
    if currencies and (None in currencies or len(currencies)!=1):
        return '<div class="chart-empty">Currency unavailable / MISSING</div>'
    currency=esc(next(iter(currencies))) if currencies else ''
    equities=[p['net_liquidation'] for p in points if p.get('net_liquidation') is not None]
    pnls=[p['daily_pnl'] for p in points if p.get('daily_pnl') is not None]
    if len(equities)<2 and len(pnls)<2:
        return '<div class="chart-empty">历史数据不足<span>Not enough historical data</span><div class="guide"></div></div>'
    out=[f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Net Liquidation curve and independent daily PnL bars">']
    low,high=(min(equities),max(equities)) if equities else (0,1);spread=high-low or max(abs(high)*.01,1)
    x=lambda i:pad+i*(w-2*pad)/max(len(points)-1,1)
    y=lambda v:20+(high-v)/spread*(h*.48)
    out.append(f'<text x="5" y="12">净值 / Net Liquidation: {currency} {low:,.0f} — {high:,.0f}</text>')
    segment=[]
    for i,p in enumerate(points):
        v=p.get('net_liquidation')
        if v is None:
            if segment:out.append('<polyline points="'+' '.join(segment)+'" fill="none" stroke="#253647" stroke-width="2.5"/>');segment=[]
        else:
            segment.append(f'{x(i)},{y(v)}');out.append(f'<circle cx="{x(i)}" cy="{y(v)}" r="3" fill="#253647"/>')
    if segment:out.append('<polyline points="'+' '.join(segment)+'" fill="none" stroke="#253647" stroke-width="2.5"/>')
    scale=max([abs(v) for v in pnls]+[1]);base=h*.79
    out.append(f'<line x1="{pad}" x2="{w-pad}" y1="{base}" y2="{base}" stroke="#d8dadd"/>')
    for i,p in enumerate(points):
        v=p.get('daily_pnl')
        if v is not None:
            bh=abs(v)/scale*h*.13;by=base-bh if v>=0 else base
            out.append(f'<rect x="{x(i)-5}" y="{by}" width="10" height="{max(bh,1)}" fill="{"#253647"}"/>')
        if i in {0,len(points)//2,len(points)-1}:out.append(f'<text x="{x(i)}" y="{h-2}" text-anchor="middle">{esc(p["date"][5:])}</text>')
    out.append(f'<text x="5" y="{h*.64}">每日盈亏 / Daily PnL: {currency} ±{scale:,.0f}</text></svg>')
    return ''.join(out)

CSS='''*{box-sizing:border-box}body{margin:0;background:#fff;color:#202b36;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",Arial,sans-serif;font-variant-numeric:tabular-nums}.page{width:1200px;min-height:1600px;padding:54px 68px 36px;position:relative;display:flex;flex-direction:column;gap:27px}.page>*{position:relative;z-index:1}.watermark{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:100%;text-align:center;font-size:76px;letter-spacing:3px;opacity:.03;z-index:0;pointer-events:none}header{display:flex;justify-content:space-between;gap:24px;border-top:5px solid #233240;border-bottom:1px solid #aab0b6;padding:25px 0 23px}h1{font-size:38px;margin:0 0 6px;font-weight:650;letter-spacing:1px}.subtitle{font-size:27px;color:#65707a}.meta{font-size:12px;color:#777e84;margin-top:18px}.status{max-width:285px;text-align:right;font-size:13px;line-height:1.8;color:#737b83}.status b{display:block;font-size:13px;font-weight:500}.panel{min-width:0;padding:0;background:transparent}h2{margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid #adb4ba;font-size:21px;font-weight:600}h2 span{font-size:15px;font-weight:400;color:#737b83;margin-left:10px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-bottom:1px solid #d5d8db}.metrics.three{grid-template-columns:repeat(3,1fr)}.kpi{padding:4px 16px 16px 0}.kpi+.kpi{padding-left:18px;border-left:1px solid #e2e4e6}.zh{font-size:16px}.en{font-size:12px;color:#7b8188;margin:5px 0 13px}.kpi strong{font-size:29px;font-weight:550;display:block;letter-spacing:-.5px}.kpi small{display:block;font-size:10px;color:#858b91;margin-top:6px}.item{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font-size:15px;padding:10px 0;border-bottom:1px solid #e3e5e7;line-height:1.5}.item i{display:block;font-size:11px;color:#80868d;font-style:normal}.item b{font-size:16px;font-weight:500;text-align:right;white-space:nowrap}.account-details{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}.account-details .item{display:block}.account-details b{display:block;text-align:left;font-size:23px;margin-top:9px}.note{font-size:12px;line-height:1.6;color:#81878d;margin-top:10px}.empty{font-size:22px;color:#80868d;padding:6px 0 15px}.empty span,.chart-empty span{display:block;font-size:15px;font-weight:400;color:#858b91;margin-top:8px}.coverage{display:flex;justify-content:space-between;align-items:center;padding-bottom:7px;color:#858b91}.coverage strong{font-size:19px;font-weight:500}.badge{font-size:11px;color:#858b91}.orders{margin-top:8px}.chart{width:100%;height:340px}.chart text{font-size:12px;fill:#7a8188}.chart-empty{padding:12px 0 18px;font-size:23px;color:#81878d}.guide{display:none}ol{margin:0;padding-left:22px;font-size:15px;line-height:1.8}li{margin-bottom:10px}.split{display:grid;grid-template-columns:1fr 1fr;gap:32px}.bottom{display:flex;flex-direction:column;gap:26px}.monthly .middle,.weekly .middle{grid-template-columns:1fr 1fr}.middle .panel:last-child:nth-child(3){grid-column:1/-1}.middle .panel:last-child:nth-child(3) .item{display:inline-flex;width:49%;padding-right:24px}.monthly .bottom{display:grid;grid-template-columns:1fr 1fr}.monthly .bottom>.panel:first-child{grid-column:1/-1}.page.monthly{gap:20px}.monthly .item{padding:6px 0}.monthly .middle{row-gap:22px}.monthly .bottom{gap:20px}.monthly h2{margin-bottom:12px}.monthly .chart-empty{padding:5px 0 10px}.page:has(.chart){gap:18px}.page:has(.chart) .item{padding:5px 0}.page:has(.chart) .split{gap:20px}.page:has(.chart) h2{margin-bottom:10px}.page:has(.chart) li{margin-bottom:5px}.positive,.negative{color:#202b36}.positive::before{content:"▲ ";color:#28674f;font-size:.55em}.negative::before{content:"▼ ";color:#923e42;font-size:.55em}.neutral{color:#202b36}.muted{color:#858b91}footer{margin-top:auto;border-top:1px solid #adb4ba;padding-top:13px;color:#888e94;font-size:10px;line-height:1.8}footer .sources{display:flex;justify-content:space-between;gap:20px;margin-bottom:12px}.copyright{font-size:11px}'''



def beijing_time(raw):
    try:
        dt=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        if dt.tzinfo is None:return 'MISSING'
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S Beijing')
    except (ValueError,TypeError):return 'MISSING'


def pnl_status(r):
    p=r['performance']
    if r['report_type']=='DAILY':
        available=any(t.get('date')==r['trading_period']['start_date'] and t.get('daily_pnl') is not None for t in p.get('trend',r['trend']))
        return '盈亏数据：可用 / PnL data: Available' if available else '盈亏数据：不可用 / PnL data: Unavailable'
    observed=p['observed_pnl_days'];expected=p['expected_trading_days']
    return f'盈亏数据覆盖：{observed} / {expected} 个交易日<br>PnL data coverage: {observed} of {expected} trading days'


def currency_view(report):
    r=deepcopy(report)
    def mark(group,keys,currency=None):
        for key in keys:
            m=group.get(key)
            if isinstance(m,dict):
                m['_money']=True
                m['currency']=m.get('currency') or currency
    mark(r['account'],['net_liquidation','total_cash_value','available_funds','buying_power','daily_pnl','realized_pnl','unrealized_pnl','gross_exposure','net_exposure'],r['account'].get('currency'))
    for obj in [r]+([r['weekly_summary']] if 'weekly_summary' in r else []):
        a=obj['activity'];p=obj['performance']
        mark(a,['turnover','buy_turnover','sell_turnover'],a.get('currency'))
        mark(a,['commissions'],a.get('commission_currency'))
        mark(p,['pnl','net_liquidation_change','realized_pnl','unrealized_pnl'],p.get('currency'))
        for key in ('best_day','worst_day'):
            if p.get(key):
                day=p[key];p[key]={**day,'daily_pnl':{'value':day['daily_pnl'],'_money':True,'currency':day.get('currency')}}
    mark(r['risk'],['max_exposure'],r['risk'].get('currency'))
    return r


def render_html(r):
    r=currency_view(r)
    kind=r['report_type'];p=r['performance'];a=r['account'];titles={'DAILY':('日报','Daily Report'),'WEEKLY':('周报','Weekly Review'),'MONTHLY':('月报','Monthly Review')};zh,en=titles[kind]
    overview='<div class="metrics">'
    if kind=='DAILY':
        overview+=''.join(kpi(z,e,a[k]) for z,e,k in [('账户净值','Net Liq','net_liquidation'),('现金','Cash','total_cash_value'),('可用资金','Available','available_funds'),('购买力','Buying Power','buying_power')])
        overview+='</div><div class="account-details">'+''.join(item(z,e,a[k]) for z,e,k in [('当日盈亏','Daily PnL','daily_pnl'),('已实现盈亏','Realized PnL','realized_pnl'),('未实现盈亏','Unrealized PnL','unrealized_pnl'),('总敞口','Gross exposure','gross_exposure')])+'</div>'
        top=panel('核心数据','Key Figures',overview,'overview')
        middle=panel('交易活动','Trading Activity',activity(r))+panel('持仓与风险','Positions / Risk',item('持仓数量','Positions',a['positions'])+risk(r))
        bottom=panel('重点关注','Attention',attention(r))+panel('近七日趋势','Sunday to Sunday',trend(r['trend']))
    else:
        overview+=''.join(kpi(z,e,p[k],k=='return_pct') for z,e,k in [('本期盈亏','Period PnL','pnl'),('本期收益率','Period Return','return_pct'),('净资产变化','Net Liquidation Δ','net_liquidation_change')])+kpi('当前净资产','Latest Net Liquidation',a['net_liquidation'])
        top=panel('月度结论' if kind=='MONTHLY' else '本周结论','Monthly Summary' if kind=='MONTHLY' else 'Weekly Summary',overview+'</div>','overview')
        middle=panel('表现与收益','Performance',performance(r))+panel('交易统计','Trading Statistics',activity(r))+panel('风险与回撤' if kind=='MONTHLY' else '风险观察','Risk & Drawdown' if kind=='MONTHLY' else 'Risk',risk(r)+(item('最大回撤（收盘）','Max daily-close drawdown',value(p['max_drawdown_pct'],True)) if kind=='MONTHLY' else ''))
        bottom=panel('月度趋势' if kind=='MONTHLY' else '近七日趋势','Monthly Trend' if kind=='MONTHLY' else 'Sunday to Sunday',trend(r['trend'],kind=='MONTHLY'))
        if kind=='MONTHLY':
            week=r['weekly_summary'];w=week['performance'];body=item('本周盈亏','Weekly PnL',w['pnl'])+item('本周成交','Weekly fills',week['activity']['fills'])+item('本周成交额','Weekly turnover',week['activity']['turnover'])
            body+='<div class="note">'+esc(week['trading_period']['start_date'])+' 起 / week to date</div>'
            bottom+=panel('周度快照','Weekly Snapshot',body)
        bottom+=panel('下月关注' if kind=='MONTHLY' else '下周关注','Next Month' if kind=='MONTHLY' else 'Next Week',attention(r))
    period=r['trading_period'];ready={True:'YES',False:'NO'}.get(r['paper_readiness'],'MISSING')
    return f'''<!doctype html><html lang="zh-CN" data-report-auto-height="true"><head><meta charset="utf-8"><title>{zh}</title><style>{CSS}</style></head><body><main class="page {kind.lower()}"><div class="watermark">liuhaitian888-wq</div><header><div><h1>{zh}</h1><div class="subtitle">Paper Trading / {en}</div><div class="meta">{('SIMULATION / MOCK. Not real Trading data.<br>' if r.get('simulation') else '')}{esc(period['start_date'])} to {esc(period['end_date_exclusive'])} (end exclusive, New York). {'期间未结束 / Partial period' if period['partial'] else '交易期间 / Trading period'}</div></div><div class="status"><b>{esc(r['runtime_state'])}</b>PAPER readiness: {ready}<br><span class="note">报告日 / Beijing: {esc(r['report_date'])}</span></div></header>{top}<div class="split middle">{middle}</div><div class="split bottom">{bottom}</div><footer><div class="sources"><span>真实账本 / Broker ledger. 缺失不补零 / Missing stays unavailable.<br>{pnl_status(r)}</span><span>Snapshot generated {beijing_time(r.get('source_snapshot_at'))}<br>Generated {beijing_time(r.get('generated_at'))}</span></div><div class="copyright">© 2026 liuhaitian888-wq</div><div>For intended recipients only and do not redistribute without permission.</div></footer></main></body></html>'''


def write_report(r,output_dir):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'latest.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    html_path=output_dir/'latest.html';png=output_dir/'latest.png'
    html_path.write_text(render_html(r))
    render_png(html_path,png,width=1200,height=1600)
    width,height=png_dimensions(png)
    if width!=1200 or height<1600:raise RuntimeError('Unexpected report dimensions')
    return png

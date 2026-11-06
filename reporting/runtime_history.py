"""Passive evidence history; no broker requests, permissions or notifications."""
import json


def record(connection, source, epoch, observed, states, evidence):
    """Caller owns connection/transaction. State changes and samples are atomic."""
    connection.execute('CREATE TABLE IF NOT EXISTS runtime_health_samples(source TEXT,epoch TEXT,bucket INTEGER,observed REAL,payload TEXT,PRIMARY KEY(source,epoch,bucket))')
    connection.execute('CREATE TABLE IF NOT EXISTS runtime_health_events(id INTEGER PRIMARY KEY,source TEXT,epoch TEXT,dimension TEXT,previous TEXT,state TEXT,observed REAL,payload TEXT)')
    connection.execute('CREATE TABLE IF NOT EXISTS runtime_health_current(source TEXT,dimension TEXT,epoch TEXT,state TEXT,observed REAL,PRIMARY KEY(source,dimension))')
    payload=json.dumps(dict(states=states,evidence=evidence),sort_keys=True)
    connection.execute('INSERT OR IGNORE INTO runtime_health_samples VALUES(?,?,?,?,?)',(source,epoch,int(observed//60),observed,payload))
    for dimension,state in states.items():
        prior=connection.execute('SELECT epoch,state FROM runtime_health_current WHERE source=? AND dimension=?',(source,dimension)).fetchone()
        # A new process is a new observation boundary, never continuous proof.
        if prior is None or prior!=(epoch,state):
            connection.execute('INSERT INTO runtime_health_events(source,epoch,dimension,previous,state,observed,payload) VALUES(?,?,?,?,?,?,?)',
                (source,epoch,dimension,prior[1] if prior and prior[0]==epoch else 'UNKNOWN',state,observed,payload))
        connection.execute('INSERT OR REPLACE INTO runtime_health_current VALUES(?,?,?,?,?)',(source,dimension,epoch,state,observed))


def monitor_states(state, health, symbols, now, required_bars):
    states={'api':'CONNECTED' if state['connected'] else 'DISCONNECTED',
            'session':'VERIFIED' if state['connected'] and state['identity'] and state['upstream_connected'] else 'UNVERIFIED'}
    evidence={'server_reply_at':state['last_server_reply'],'market_errors':state.get('market_errors',{}),
              'bar_callback_diagnostics':state.get('bar_callback_diagnostics',{}),'symbols':{}}
    for symbol in symbols:
        quote=health.get(symbol,{})
        states['market.quotes.'+symbol]=quote.get('status','UNKNOWN')
        bars=state['bars'].get(symbol,[])[-required_bars:]
        history=state.get('history_evidence',{}).get(symbol,{})
        def valid(ends):
            return len(ends)>=required_bars and all(b-a==60 for a,b in zip(ends,ends[1:])) and 0<=now-ends[-1]<=65
        states['market.bars.'+symbol]='VERIFIED_FRESH' if valid(bars) else 'UNVERIFIED'
        states['market.history.'+symbol]=('VERIFIED_FRESH' if history.get('complete') is True
            and valid(history.get('completed_ends',[])[-required_bars:]) and 0<=now-history.get('received_at',0)<=65 else 'UNVERIFIED')
        evidence['symbols'][symbol]=dict(quote=quote,bars=bars,history=history)
    return states,evidence

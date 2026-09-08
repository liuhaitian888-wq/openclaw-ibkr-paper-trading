"""Evidence-backed project extension to der verification; never infer PASS from docs."""
import ast
import json
from datetime import datetime,timezone
from pathlib import Path

# Requirements map to executed tests, not self-attested design statements.
CHECKS={
 'persistent state':('reporting/ledger.py','test_machine_restart_model_new_process_reads_only_disk'),
 'restart safety':('reporting/delivery.py','test_process_crash_before_ledger_commit'),
 'deduplication':('reporting/delivery.py','test_concurrent_processes_only_one_send'),
 'idempotency':('reporting/delivery.py','test_duplicate_scheduler_trigger'),
 'UNKNOWN handling':('reporting/delivery.py','test_unknown_never_auto_resends_after_network_recovery'),
 'offline diagnostics':('reporting/health.py','test_health_unknown_is_not_success'),
 'health interface':('reporting/health.py','test_preflight_dns'),
 'freshness checks':('reporting/generation.py','test_stale_ibkr_data'),
 'retry policy':('reporting/delivery.py','test_failed_three_attempts_thirty_minutes'),
 'recovery policy':('reporting/recovery.py','test_same_day_catchup_after_old_window'),
 'trigger ownership':('reporting/ownership.py','test_ownership_transfer_no_second_authority'),
 'trigger transfer/history':('reporting/ownership.py','test_ownership_transfer_no_second_authority'),
 'legacy entrypoints':('scripts/send_feishu_report.py','test_legacy_sender_attempt_has_no_network'),
 'secret handling':('reporting/errors.py','test_raw_provider_error_preservation_and_secret_redaction'),
 'failure injection':('reporting/chaos.py','test_network_flapping_requires_every_preflight'),
 'observability':('reporting/ledger.py','test_warning_is_local_and_deduplicated'),
 'Trading / Delivery isolation':('reporting/recovery.py','test_reconnect_cannot_grant_trading_risk'),
 'single generation implementation':('reporting/service.py','test_same_generation_implementation_all_triggers_offline'),
 'artifact identity':('reporting/delivery.py','test_mutation_during_preflight'),
}

def audit(root,evidence_path=None):
    root=Path(root);evidence=json.loads(Path(evidence_path).read_text()) if evidence_path and Path(evidence_path).exists() else {}
    from scripts.run_report_chaos import source_hashes
    fresh=evidence.get('source_hashes')==source_hashes(root)
    passed={r['test'].split('.')[-1] for r in evidence.get('results',[]) if r['status']=='PASS'}
    rows=[]
    for requirement,(implementation,test) in CHECKS.items():
        status='PASS' if fresh and test in passed else 'WARN'
        rows.append({'requirement':requirement,'implementation':implementation,'evidence':{'test':test,'evidence_file':str(evidence_path),'code_hashes_match':fresh},'status':status,'missing_capability':None if status=='PASS' else 'Run current-code verification'})
    violations=[]
    for p in (root/'reporting').glob('*.py'):
        tree=ast.parse(p.read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):names=[a.name for a in n.names]
            elif isinstance(n,ast.ImportFrom):names=[n.module or '']
            else:continue
            if any(name.startswith(('execution','risk','trading.workflow','api_service')) for name in names):violations.append(str(p.relative_to(root)))
    rows.append({'requirement':'module boundaries','implementation':'reporting/*.py','evidence':{'AST_forbidden_imports':violations},'status':'FAIL' if violations else 'PASS','missing_capability':None})
    for requirement,missing in {
        'production authority':'Current launchd remains paused; activation and deployed-worktree migration intentionally not performed',
        'scheduler conflicts':'Second historical Codex investment task is PAUSED; full ownership adoption awaits production acceptance',
        'raw error preservation':'Normalized raw-error API tested; existing live IBKR callback/log writers not rewired this round',
        'normalized Error Registry':'Registry implemented; legacy runtime callers still need deployment integration',
        'dependency declaration':'16 interfaces defined; live network/IBKR/Feishu probes remain unknown until explicit checks',
        'single responsibility':'New modules separated; historical report_service retains legacy internals behind retired CLI',
        'runbook':'Local runbook supplied; operator acceptance and reconciliation drill still required',
        'ADR consistency':'Project ADR records candidate state; no change to external der engineering registry',
        'handbook consistency':'Project supplement supplied; global generated handbook not republished',
    }.items():rows.append({'requirement':requirement,'implementation':'docs/reporting/engineering-audit.md','evidence':'Documented audit limitation, not a PASS assertion','status':'WARN','missing_capability':missing})
    counts={s:sum(r['status']==s for r in rows) for s in ('PASS','WARN','FAIL')}
    return {'timestamp':datetime.now(timezone.utc).isoformat(),'scope':'candidate sandbox implementation; not production acceptance','requirements':rows,'counts':counts,'tests_run':evidence.get('tests_run',0),'test_evidence_current':fresh}

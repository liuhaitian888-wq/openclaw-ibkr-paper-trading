from typing import Any, Dict


WORKFLOW_STEP_MESSAGES = {
    "client_secret": "OpenClaw client could not load the API key or trade token.",
    "client_http": "OpenClaw client could not reach the Mac trading API.",
    "client_preflight": "OpenClaw client preflight rejected the request.",
    "api_auth": "Mac trading API rejected the API key.",
    "api_request_body": "Mac trading API could not read the JSON request body.",
    "service_parse": "Trading service could not parse the order proposal.",
    "service_risk": "Trading service risk validation rejected the order.",
    "service_gate": "Trading service mode, lock, or session gate blocked the order.",
    "service_tws_preflight": "Trading service could not confirm TWS readiness.",
    "service_audit_reserve": "Trading service could not reserve the audit record.",
    "service_broker_submit": "Trading service broker adapter could not submit to TWS.",
    "service_audit_update": "Trading service could not update the audit record.",
    "complete": "Workflow completed.",
}


def attach_workflow_step(exc: Exception, step: str) -> Exception:
    setattr(exc, "workflow_step", step)
    setattr(exc, "workflow_step_message", WORKFLOW_STEP_MESSAGES.get(step, step))
    return exc


def workflow_step(exc: BaseException, default: str) -> str:
    value = getattr(exc, "workflow_step", "")
    return value if isinstance(value, str) and value else default


def workflow_error_payload(exc: BaseException, default_step: str) -> Dict[str, Any]:
    step = workflow_step(exc, default_step)
    return {
        "status": "ERROR",
        "workflow_step": step,
        "workflow_step_message": WORKFLOW_STEP_MESSAGES.get(step, step),
        "error": str(exc),
    }

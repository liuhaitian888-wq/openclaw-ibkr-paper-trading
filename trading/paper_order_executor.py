"""Future IBKR paper order executor interface. Disabled by default."""


IBKR_PAPER_ORDER_SUBMISSION = False
AUTO_ENABLE_IBKR_PAPER_ORDER_SUBMISSION = False


def submit_order_if_enabled(*_args, **_kwargs) -> dict:
    return {
        "status": "blocked_default_false",
        "IBKR_PAPER_ORDER_SUBMISSION": IBKR_PAPER_ORDER_SUBMISSION,
        "AUTO_ENABLE_IBKR_PAPER_ORDER_SUBMISSION": AUTO_ENABLE_IBKR_PAPER_ORDER_SUBMISSION,
        "order_submitted": False,
    }

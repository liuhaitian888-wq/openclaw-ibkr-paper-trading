# Trading Sessions

This directory defines how the autonomous paper runtime should behave across US equity sessions. The current implementation is paper-only and keeps live trading disabled.

Sessions are classified in `America/New_York` and reported with `Europe/Berlin` timestamps for the operator.

Core rule: paper automation may run continuously, but every automatic entry must use a limit entry and a protective stop or synthetic stop rule.

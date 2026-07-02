"""Verify a read-only connection to an IBKR paper-trading TWS session."""

import argparse
import threading
from typing import Dict, List

from ibapi.client import EClient
from ibapi.wrapper import EWrapper


class ReadOnlyTwsClient(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.snapshot_complete = threading.Event()
        self.server_time = None
        self.accounts: List[str] = []
        self.account_summary: Dict[str, str] = {}
        self.errors: List[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IBKR callback name
        # This callback confirms that the API handshake completed. No order is sent.
        self.ready.set()
        self.reqCurrentTime()
        self.reqAccountSummary(
            9001,
            "All",
            "NetLiquidation,TotalCashValue,AvailableFunds",
        )

    def currentTime(self, time: int) -> None:  # noqa: N802 - IBKR callback name
        self.server_time = time

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item for item in accountsList.split(",") if item]

    def accountSummary(  # noqa: N802 - IBKR callback name
        self,
        reqId: int,
        account: str,
        tag: str,
        value: str,
        currency: str,
    ) -> None:
        key = f"{account}:{tag}:{currency or 'BASE'}"
        self.account_summary[key] = value

    def accountSummaryEnd(self, reqId: int) -> None:  # noqa: N802
        self.cancelAccountSummary(reqId)
        self.snapshot_complete.set()

    def error(self, reqId: int, *args: object) -> None:
        # IBKR has changed this callback signature across API releases.
        self.errors.append(f"request={reqId}, details={args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=21)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = ReadOnlyTwsClient()

    try:
        client.connect(args.host, args.port, clientId=args.client_id)
        api_thread = threading.Thread(target=client.run, daemon=True)
        api_thread.start()

        if not client.ready.wait(args.timeout):
            print("Connection failed: TWS API handshake timed out")
            for error in client.errors:
                print(f"IBKR: {error}")
            return 1

        if not client.snapshot_complete.wait(args.timeout):
            print("Connected, but the account snapshot timed out")
            for error in client.errors:
                print(f"IBKR: {error}")
            return 1

        print("TWS paper API connection: OK")
        print(f"Server timestamp: {client.server_time}")
        print(f"Managed accounts: {', '.join(client.accounts) or 'not returned'}")
        for key, value in sorted(client.account_summary.items()):
            print(f"{key} = {value}")
        return 0
    finally:
        if client.isConnected():
            client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

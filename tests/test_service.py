import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading.config import Settings
from trading.service import TradingService
from trading.tws_paper import OrderConfirmation, TwsConnectionStatus


def make_settings(directory: str, **overrides: object) -> Settings:
    values = {
        "api_key": "x" * 32,
        "api_host": "127.0.0.1",
        "api_port": 8787,
        "trading_mode": "DRY_RUN",
        "allow_tws_staging": False,
        "allow_paper_transmit": False,
        "allow_outside_rth": False,
        "trading_kill_switch": False,
        "trade_session_token": "",
        "tws_host": "127.0.0.1",
        "tws_port": 7497,
        "tws_client_id": 22,
        "tws_status_timeout": 0.01,
        "allowed_symbols": frozenset({"AAPL", "MSFT", "SPY"}),
        "max_quantity": 1,
        "max_order_value": 200.0,
        "max_risk_per_order": 10.0,
        "max_daily_notional_value": None,
        "daily_notional_timezone": "Europe/Berlin",
        "streaming_market_data_enabled": False,
        "streaming_symbols": ("AAPL", "MSFT", "NVDA"),
        "streaming_max_symbols": 3,
        "streaming_stale_ms": 3000.0,
        "streaming_tws_host": "127.0.0.1",
        "streaming_tws_port": 7497,
        "streaming_client_id": 32,
        "audit_db": Path(directory) / "audit.sqlite3",
    }
    values.update(overrides)
    return Settings(**values)


def valid_payload(key: str = "trade-0001") -> dict:
    return {
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "limit_price": 190.0,
        "stop_price": 185.0,
        "idempotency_key": key,
    }


def valid_limit_payload(key: str = "limit-0001") -> dict:
    return {
        "symbol": "MSFT",
        "side": "BUY",
        "quantity": 1,
        "limit_price": 300.0,
        "idempotency_key": key,
    }


def ready_tws_status() -> TwsConnectionStatus:
    return TwsConnectionStatus(
        connected=True,
        ready_for_orders=True,
        account_count=1,
        accounts=("DU12345",),
        paper_account="DU12345",
        next_order_id_received=True,
        timings={"tws_status_check_ms": 1.0},
    )


def not_ready_tws_status() -> TwsConnectionStatus:
    return TwsConnectionStatus(
        connected=False,
        ready_for_orders=False,
        error="TWS API is not reachable or not fully logged in",
        timings={"tws_status_check_ms": 1.0},
    )


class TradingServiceTests(unittest.TestCase):
    def test_stage_menu_requires_explicit_confirmation(self) -> None:
        script = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        self.assertIn("Type STAGE to continue", script)
        self.assertIn('[[ "$stage_confirm" != "STAGE" ]]', script)
        self.assertIn("intentionally creates untransmitted staged orders", script)

    def test_dry_run_validation_approves_safe_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = TradingService(make_settings(directory))

            result = service.validate(valid_payload())

            self.assertTrue(result["approved"])
            self.assertEqual(result["mode"], "DRY_RUN")
            self.assertEqual(result["estimated_value"], 190.0)
            self.assertEqual(result["estimated_risk"], 5.0)

    def test_dry_run_mode_cannot_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = TradingService(make_settings(directory))

            with self.assertRaisesRegex(PermissionError, "TRADING_MODE=PAPER"):
                service.submit(valid_payload(), transmit=False)

    def test_paper_transmission_requires_explicit_switch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_paper_transmit=False,
            )
            service = TradingService(settings)

            with self.assertRaisesRegex(PermissionError, "transmission is disabled"):
                service.submit(valid_payload(), transmit=True)

    def test_kill_switch_rejects_submission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                trading_kill_switch=True,
            )
            service = TradingService(settings)

            with self.assertRaisesRegex(PermissionError, "kill switch"):
                service.submit(valid_payload(), transmit=False)

    def test_paper_transmission_requires_session_token_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_paper_transmit=True,
            )
            service = TradingService(settings)

            with self.assertRaisesRegex(PermissionError, "session token"):
                service.submit(valid_payload(), transmit=True)

    def test_paper_transmission_rejects_invalid_session_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )
            payload = valid_payload()
            payload["trade_session_token"] = "wrong"
            service = TradingService(settings)

            with self.assertRaisesRegex(PermissionError, "Invalid trade session"):
                service.submit(payload, transmit=True)

    @patch("trading.service.TwsPaperBroker")
    def test_paper_transmission_accepts_valid_session_token(self, broker_class: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )
            payload = valid_payload()
            payload["source"] = "openclaw"
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_bracket.return_value = OrderConfirmation(
                order_ids=(100, 101),
                statuses={100: "Submitted", 101: "Submitted"},
            )
            service = TradingService(settings)

            result = service.submit(payload, transmit=True)

            self.assertEqual(result["status"], "PAPER_SUBMITTED")
            self.assertEqual(result["source"], "openclaw")

    @patch("trading.service.TwsPaperBroker")
    def test_duplicate_idempotency_key_is_rejected(self, broker_class: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
            )
            broker_class.return_value.submit_bracket.return_value = OrderConfirmation(
                order_ids=(100, 101),
                statuses={100: "PreSubmitted", 101: "PreSubmitted"},
            )
            service = TradingService(settings)

            first = service.submit(valid_payload(), transmit=False)

            self.assertEqual(first["status"], "STAGED_NOT_TRANSMITTED")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                service.submit(valid_payload(), transmit=False)

    @patch("trading.service.TwsPaperBroker")
    def test_outside_rth_switch_is_passed_to_broker(self, broker_class: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_outside_rth=True,
            )
            broker_class.return_value.submit_bracket.return_value = OrderConfirmation(
                order_ids=(100, 101),
                statuses={100: "PreSubmitted", 101: "PreSubmitted"},
            )
            service = TradingService(settings)

            service.submit(valid_payload(), transmit=False)

            broker_class.return_value.submit_bracket.assert_called_once_with(
                unittest.mock.ANY,
                transmit=False,
                outside_rth=True,
            )

    @patch("trading.service.TwsPaperBroker")
    def test_limit_paper_order_uses_session_token_without_stop_price(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                allow_outside_rth=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload()
            payload["source"] = "openclaw"
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(200,),
                statuses={200: "Submitted"},
                timings={
                    "broker_connect_handshake_ms": 1.0,
                    "broker_total_ms": 2.0,
                },
            )
            broker_class.return_value.check_status.return_value = ready_tws_status()
            service = TradingService(settings)

            result = service.submit_limit(payload, transmit=True)

            self.assertEqual(result["status"], "PAPER_LIMIT_SUBMITTED")
            self.assertEqual(result["confirmation_status"], "CONFIRMED")
            self.assertEqual(result["preflight"]["lock_state"], "TRADE_LOCK")
            self.assertEqual(result["order_id"], 200)
            self.assertIn("service_total_ms", result["timings"])
            self.assertIn("service_risk_ms", result["timings"])
            self.assertEqual(result["timings"]["broker_total_ms"], 2.0)
            record = service.audit_order("limit-0001")["order"]
            self.assertIn("execution_intent=paper_transmit", record["details"])
            self.assertIn("transmit=true", record["details"])
            broker_class.return_value.submit_limit.assert_called_once_with(
                unittest.mock.ANY,
                transmit=True,
                outside_rth=True,
            )

    @patch("trading.service.TwsPaperBroker")
    def test_bracket_paper_order_records_pending_confirmation_when_only_parent_acknowledged(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_tws_staging=True,
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )
            payload = valid_payload("pending-bracket-0001")
            payload["source"] = "openclaw"
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_bracket.return_value = OrderConfirmation(
                order_ids=(100, 101),
                acknowledged_order_ids=(100,),
                statuses={100: "PreSubmitted"},
                messages=("no callback for stop leg",),
            )
            service = TradingService(settings)

            result = service.submit(payload, transmit=True)

            self.assertEqual(result["status"], "PAPER_PENDING_CONFIRMATION")
            self.assertEqual(result["confirmation_status"], "PENDING_CONFIRMATION")
            self.assertTrue(result["pending_confirmation"])
            self.assertEqual(result["acknowledged_order_ids"], [100])
            self.assertEqual(result["tws_messages"], ["no callback for stop leg"])

            record = service.audit_order("pending-bracket-0001")["order"]
            self.assertEqual(record["status"], "PAPER_PENDING_CONFIRMATION")
            self.assertIn("pending_confirmation=true", record["details"])
            self.assertIn("execution_intent=paper_transmit", record["details"])
            self.assertIn("bracket_parent_transmit_false_expected=true", record["details"])

    @patch("trading.service.TwsPaperBroker")
    def test_limit_paper_order_records_pending_confirmation_when_tws_has_no_ack(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload("pending-limit-0001")
            payload["source"] = "openclaw"
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(300,),
                acknowledged_order_ids=(),
                messages=("no TWS error callback",),
            )
            service = TradingService(settings)

            result = service.submit_limit(payload, transmit=True)

            self.assertEqual(result["status"], "PAPER_LIMIT_PENDING_CONFIRMATION")
            self.assertEqual(result["confirmation_status"], "PENDING_CONFIRMATION")
            self.assertTrue(result["pending_confirmation"])
            self.assertEqual(result["acknowledged_order_ids"], [])
            self.assertEqual(result["tws_messages"], ["no TWS error callback"])

            record = service.audit_order("pending-limit-0001")["order"]
            self.assertEqual(record["status"], "PAPER_LIMIT_PENDING_CONFIRMATION")
            self.assertIn("pending_confirmation=true", record["details"])

    def test_limit_validation_still_enforces_max_order_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(directory, max_order_value=200.0)
            service = TradingService(settings)

            result = service.validate_limit(valid_limit_payload())

            self.assertFalse(result["approved"])
            self.assertEqual(result["reason"], "Order value exceeds the configured maximum")

    @patch("trading.service.TwsPaperBroker")
    def test_daily_notional_cap_is_disabled_by_default(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload("daily-disabled-0001")
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(200,),
                statuses={200: "Submitted"},
            )
            service = TradingService(settings)

            result = service.submit_limit(payload, transmit=True)

            self.assertEqual(result["status"], "PAPER_LIMIT_SUBMITTED")
            self.assertEqual(service.health()["limits"]["max_daily_notional_value"], None)

    @patch("trading.service.TwsPaperBroker")
    def test_daily_notional_cap_rejects_when_configured_and_exceeded(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
                max_daily_notional_value=500.0,
            )
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(200,),
                statuses={200: "Submitted"},
            )
            service = TradingService(settings)
            first = valid_limit_payload("daily-cap-0001")
            first["trade_session_token"] = "session-ok"
            second = valid_limit_payload("daily-cap-0002")
            second["trade_session_token"] = "session-ok"

            service.submit_limit(first, transmit=True)
            with self.assertRaisesRegex(PermissionError, "Daily notional cap exceeded"):
                service.submit_limit(second, transmit=True)

            self.assertEqual(service.audit_orders(limit=10)["count"], 1)

    @patch("trading.service.TwsPaperBroker")
    def test_audit_orders_can_be_queried_after_submission(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                allow_outside_rth=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload("audit-limit-0001")
            payload["source"] = "openclaw"
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(200,),
                statuses={200: "Submitted"},
            )
            broker_class.return_value.check_status.return_value = ready_tws_status()
            service = TradingService(settings)

            service.submit_limit(payload, transmit=True)

            recent = service.audit_orders(limit=10)
            self.assertEqual(recent["count"], 1)
            order = recent["orders"][0]
            self.assertEqual(order["idempotency_key"], "audit-limit-0001")
            self.assertEqual(order["status"], "PAPER_LIMIT_SUBMITTED")
            self.assertEqual(order["proposal"]["symbol"], "MSFT")

            by_key = service.audit_order("audit-limit-0001")
            self.assertEqual(by_key["order"]["idempotency_key"], "audit-limit-0001")

            created_day = order["created_at"][:10]
            by_date = service.audit_orders(day=created_day, timezone_name="UTC")
            self.assertEqual(by_date["count"], 1)
            self.assertEqual(by_date["orders"][0]["idempotency_key"], "audit-limit-0001")

    @patch("trading.service.TwsPaperBroker")
    def test_health_includes_recent_audit_summary(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload("health-limit-0001")
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(200,),
                statuses={200: "Submitted"},
            )
            service = TradingService(settings)

            service.submit_limit(payload, transmit=True)

            health = service.health()
            self.assertEqual(health["audit"]["recent_order_count"], 1)
            self.assertEqual(health["lock_state"], "TRADE_LOCK")
            self.assertTrue(health["tws"]["ready_for_orders"])
            recent_order = health["audit"]["recent_orders"][0]
            self.assertEqual(recent_order["idempotency_key"], "health-limit-0001")
            self.assertEqual(recent_order["symbol"], "MSFT")
            self.assertEqual(recent_order["status"], "PAPER_LIMIT_SUBMITTED")

    @patch("trading.service.TwsPaperBroker")
    def test_submission_requires_tws_ready_before_audit_reserve(
        self,
        broker_class: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            payload = valid_limit_payload("no-tws-0001")
            payload["trade_session_token"] = "session-ok"
            broker_class.return_value.check_status.return_value = not_ready_tws_status()
            service = TradingService(settings)

            with self.assertRaisesRegex(PermissionError, "TWS is not ready") as caught:
                service.submit_limit(payload, transmit=True)

            self.assertEqual(
                getattr(caught.exception, "workflow_step"),
                "service_tws_preflight",
            )
            self.assertEqual(service.audit_orders(limit=10)["count"], 0)
            broker_class.return_value.submit_limit.assert_not_called()

    def test_missing_audit_order_returns_key_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = TradingService(make_settings(directory))

            with self.assertRaises(KeyError):
                service.audit_order("missing-key")


if __name__ == "__main__":
    unittest.main()

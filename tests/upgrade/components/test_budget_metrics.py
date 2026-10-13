"""Pure counters/redaction/one-failure loop checks; no full journey."""
import copy
import unittest
from unittest.mock import patch

from contract_playbook.providers.gateway import GatewayChatProvider, GatewayConfig, GatewayFailure
from contract_playbook.upgrade.budget import Budget
from contract_playbook.upgrade.metrics import safe_event, summary
from contract_playbook.upgrade.service import investigate_gateway


class BudgetMetricTests(unittest.TestCase):
    def test_cumulative_reservation_and_restore(self):
        config = GatewayConfig("demo/u1", max_requests=1)
        budget = Budget()
        prior = budget.reserve(config)
        self.assertEqual(budget.seconds_used, 20)
        budget.settle(prior, 2, {"prompt_tokens": 3, "completion_tokens": 2})
        restored = Budget.restore(budget.public(), config)
        self.assertEqual(restored.requests, 1)
        with self.assertRaisesRegex(GatewayFailure, "BUDGET_EXHAUSTED"):
            restored.reserve(config)

    def test_crash_reservation_cannot_be_reissued(self):
        config = GatewayConfig("demo/u1")
        budget = Budget()
        budget.reserve(config)
        with self.assertRaisesRegex(GatewayFailure, "AMBIGUOUS_PREVIOUS_REQUEST"):
            Budget.restore(budget.public(), config).reserve(config)

    def test_unknown_usage_stays_unknown(self):
        budget = Budget()
        budget.settle(0, 1, None)
        budget.settle(1, 1, {"prompt_tokens": 20, "completion_tokens": 20})
        self.assertIsNone(budget.prompt_tokens)
        self.assertIsNone(budget.completion_tokens)

    def test_bad_checkpoint_and_clock(self):
        config = GatewayConfig("demo/u1")
        data = Budget().public()
        for field, value in (("requests", True), ("seconds_used", float("nan")),
                             ("tool_attempts", 25), ("request_in_flight", 1)):
            corrupted = {**data, field: value}
            with self.assertRaises(GatewayFailure):
                Budget.restore(corrupted, config)
        with self.assertRaises(GatewayFailure):
            Budget().settle(0, -1)

    def test_sensitive_nested_and_unknown_fields_not_emitted(self):
        text = "Bearer synthetic-private-text"
        event = safe_event({"mode": "local-double", "state": "ACTION", "attempt": 1,
                           "Authorization": text, "raw_body": {"key": text},
                           "reasoning": text, "failure_code": text, "model": text})
        self.assertNotIn(text, str(event))
        self.assertNotIn("Authorization", event)
        self.assertIsNone(event["actual_cost_usd"])
        self.assertEqual(safe_event({"mode": {}, "state": [], "tool": {}})["provider"], "vercel-ai-gateway")

    def test_no_success_cost_and_latency_denominators(self):
        events = [{"mode": "local-double", "state": "ACTION", "elapsed_seconds": n,
                   "requests": i + 1} for i, n in enumerate((.1, .3, .2))]
        report = summary(events)
        self.assertEqual(report["request_p50_seconds"], .2)
        self.assertEqual(report["latency_sample_count"], 3)
        self.assertIsNone(report["cost_per_success_usd"])
        self.assertIsNone(report["executed_unauthorized_actions"])
        self.assertEqual(report["verified_copy_delivered"], 0)

    def test_identifier_fields_do_not_echo_arbitrary_text(self):
        event = safe_event({"response_id": "synthetic-private-text", "generation_id": "synthetic-private-text"})
        self.assertNotIn("synthetic-private-text", str(event))
        self.assertEqual(safe_event({"response_id": "double_1"})["response_id"], "double_1")

    def test_handoff_and_approval_are_distinct(self):
        self.assertEqual(summary([{"mode": "local-double", "state": "HANDOFF"}])["verified_copy_delivered"], 0)
        report = summary([{"mode": "local-double", "state": "APPROVED_COPY_VERIFIED",
                           "unauthorized_actions": 0}])
        self.assertEqual(report["verified_copy_delivered"], 1)
        self.assertEqual(report["executed_unauthorized_actions"], 0)

    def test_recovery_reports_current_pending_and_keeps_historical_events(self):
        for interrupted, field in (("FAILED", "historical_failure_events"),
                                   ("CANCELLED", "historical_cancellation_events")):
            events = [{"mode": "local-double", "state": interrupted, "requests": 1},
                      {"mode": "local-double", "state": interrupted, "requests": 1},
                      {"mode": "local-double", "state": "PROPOSAL_READY", "requests": 12,
                       "replays": 1, "committed_state": "PENDING_REVIEW"}]
            before = copy.deepcopy(events)
            report = summary(events, current_state="PENDING_REVIEW")
            self.assertEqual(report["current_disposition"], "PENDING_REVIEW")
            self.assertEqual(report["pending_human_review"], 1)
            self.assertEqual((report["failed"], report["cancelled"]), (0, 0))
            self.assertEqual(report[field], 2)
            self.assertEqual(report["requests"], 12)
            self.assertEqual(events, before)

    def test_denial_does_not_replace_committed_disposition(self):
        for disposition in ("PENDING_REVIEW", "STALE", "CANCELLED", "FAILED", "BUDGET_EXHAUSTED"):
            report = summary([{"mode": "local-double", "state": "PROPOSAL_READY"},
                              {"mode": "local-double", "state": "APPROVAL_DENIED"}],
                             current_state=disposition)
            self.assertEqual(report["current_disposition"], disposition)
            self.assertEqual(report["pending_human_review"], int(disposition == "PENDING_REVIEW"))
            self.assertEqual(report["stale"], int(disposition == "STALE"))
            self.assertEqual(report["failed"], int(disposition in {"FAILED", "BUDGET_EXHAUSTED"}))
            self.assertEqual(report["cancelled"], int(disposition == "CANCELLED"))
            self.assertEqual(report["historical_approval_denial_events"], 1)

    def test_copy_success_requires_current_export_and_verified_event(self):
        events = [{"mode": "local-double", "state": "APPROVED_COPY_VERIFIED"}]
        for disposition, expected in (("DRAFT_EXPORTED", 1), ("APPROVED", 0), ("STALE", 0)):
            self.assertEqual(summary(events, current_state=disposition)["verified_copy_delivered"], expected)
        self.assertEqual(summary([], current_state="DRAFT_EXPORTED")["verified_copy_delivered"], 0)

    def test_committed_disposition_is_redacted_and_bound_to_metrics_identity(self):
        events = [{"mode": "local-double", "state": "APPROVAL_DENIED", "committed_state": "STALE"}]
        self.assertEqual(summary(events)["current_disposition"], "STALE")
        self.assertNotEqual(summary(events, current_state="STALE")["metrics_sha256"],
                            summary(events, current_state="PENDING_REVIEW")["metrics_sha256"])
        self.assertNotIn("synthetic-private-text", str(safe_event({"committed_state": "synthetic-private-text"})))

    def test_zero_retries_and_ambiguous_checkpoint(self):
        config = GatewayConfig("demo/u1")
        class Registry:
            submitted = False
            history = []
            def checkpoint(self):
                return {"history": self.history}
            def observation(self):
                return {"tools": [], "history": []}
        class Journal:
            saved = None
            def load_checkpoint(self):
                return None
            def events(self):
                return []
            def pending_action(self):
                return None
            def save_checkpoint(self, value):
                self.saved = copy.deepcopy(value)
        class Double:
            mode = "local-double"
            count = 0
            def request(self, *args):
                self.count += 1
                raise GatewayFailure("TRANSPORT_OR_RESPONSE_LOST")
        journal, transport = Journal(), Double()
        with patch("contract_playbook.upgrade.service.operating"):
            with self.assertRaisesRegex(GatewayFailure, "TRANSPORT_OR_RESPONSE_LOST"):
                investigate_gateway(Registry(), GatewayChatProvider(config, transport), journal,
                                    cancel=lambda: False, clock=lambda: 0)
        self.assertEqual(transport.count, 1)
        self.assertEqual(journal.saved["budget"]["requests"], 1)
        self.assertTrue(journal.saved["budget"]["request_in_flight"])

    def test_cancel_before_dispatch_starts_no_request(self):
        class Journal:
            def load_checkpoint(self):
                return None
            def events(self):
                return []
        class Registry:
            submitted = False
        with patch("contract_playbook.upgrade.service.operating"):
            with self.assertRaises(KeyboardInterrupt):
                investigate_gateway(Registry(), type("Provider", (), {"config": GatewayConfig("demo/u1")})(),
                                    Journal(), cancel=lambda: True)

"""Independent verifier mutation controls constructed in memory only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import mock_open, patch

from contract_playbook.common import ReviewError, canonical, sha256
from contract_playbook.proposal_check import ProposalInvalid, check_proposal, check_receipt
from contract_playbook.providers.gateway import GatewayConfig
from contract_playbook.store import RunStore
from contract_playbook.upgrade.budget import Budget
from contract_playbook.upgrade.metrics import summary
from contract_playbook.upgrade.service import refresh_metrics, review_store, verify_store


def control():
    text = "Section 1 - Terms\nCafé 🤝 sixty days.\n"
    raw = text.encode("utf-8")
    atoms = {"REN-01": ["renewal.express_written_agreement"],
             "TERM-01": ["termination.notice_days"], "PAY-01": ["payment.days"]}
    policy = {"id": "unit-fictional", "rules": [
        {"id": key, "text": "Fictional " + key, "obligations": values} for key, values in atoms.items()]}
    policy_raw, manifest = canonical(policy), b"unit-manifest"
    block = {"block_id": "agreement.section-1", "title": "Terms", "start": 0, "end": len(text)}
    doc = {"document_id": "agreement", "document_sha256": sha256(raw), "byte_length": len(raw),
           "filename": "agreement.txt", "blocks": [block]}
    start = text.index("sixty")
    patch = {"document_id": "agreement", "document_sha256": sha256(raw), "start": start,
             "end": start + 5, "expected_text": "sixty", "replacement": "thirty"}
    span = {"document_id": "agreement", "document_sha256": sha256(raw),
            "block_id": block["block_id"], "start": 0, "end": len(text), "quote": text}
    findings = [{"rule_id": r["id"], "disposition": "deviation" if r["id"] == "TERM-01" else "compliant",
                 "obligations": {a: "deviation" if r["id"] == "TERM-01" else "compliant" for a in r["obligations"]},
                 "reason": "Unit mechanical control, not a semantic assessment.",
                 "evidence": [copy.deepcopy(span)], "patch": copy.deepcopy(patch) if r["id"] == "TERM-01" else None,
                 "policy_citation": {"playbook_id": policy["id"], "playbook_sha256": sha256(policy_raw),
                                     "rule_id": r["id"], "quote": r["text"]}} for r in policy["rules"]]
    coverage = {"documents": [{"document_id": "agreement", "document_sha256": sha256(raw),
                 "read_block_ids": [block["block_id"]], "total_blocks": 1}], "complete": True}
    core = {"schema_version": 3, "fictional": True, "execution_mode": "local-double", "live_model": False,
            "domain_status": "PENDING_REVIEW", "source": doc, "documents": [doc],
            "coverage": {**coverage, "receipt_sha256": sha256(canonical(coverage))},
            "manifest_sha256": sha256(manifest), "playbook": {"id": policy["id"], "sha256": sha256(policy_raw)},
            "findings": findings, "patches": [patch]}
    packet = {**core, "proposal_sha256": sha256(canonical(core))}
    return packet, {"agreement": raw}, policy_raw, manifest


def resign(packet):
    packet["proposal_sha256"] = sha256(canonical({k: v for k, v in packet.items() if k != "proposal_sha256"}))


class MemoryStore:
    """Pure boundary double; no SQLite, file writes, transport or complete journey."""
    def __init__(self, saved=None):
        packet, originals, policy, manifest = control()
        self.directory = Path("unit-memory-not-created")
        self.files = {self.directory / "review.json": canonical(packet),
                      self.directory / "preview/agreement.txt": originals["agreement"].replace(b"sixty", b"thirty"),
                      Path("unit-source-agreement"): originals["agreement"],
                      Path("unit-source-policy"): policy, Path("unit-source-manifest"): manifest}
        self.inputs = [(key, str(path), sha256(raw), raw) for key, path, raw in (
            ("agreement", Path("unit-source-agreement"), originals["agreement"]),
            ("playbook", Path("unit-source-policy"), policy), ("manifest", Path("unit-source-manifest"), manifest))]
        self.saved = saved if saved is not None else {"state": "PENDING_REVIEW", "packet": packet,
            "checkpoint": {"budget": Budget(requests=1, steps=1, tool_attempts=1).public()},
            "events": [{"operating": {"mode": "local-double", "state": "PROPOSAL_READY"}}]}
        self.db = self
        self.review_calls = 0
        self.refreshed = []

    def execute(self, sql):
        if sql == "SELECT id,path,sha,raw FROM inputs":
            return self.inputs
        if sql == "SELECT run_key FROM run":
            return type("Row", (), {"fetchone": lambda row: ("a" * 64,)})()
        raise AssertionError("Unexpected pure store query: " + sql)

    def packet(self):
        return self.saved["packet"]

    def state(self):
        return self.saved["state"]

    def fail(self, state):
        self.saved["state"] = state

    def load_checkpoint(self):
        return self.saved["checkpoint"]

    def config(self):
        return {"gateway": GatewayConfig("demo/u1").public(), "code_sha256": "b" * 64,
                "dataset_sha256": "c" * 64}

    def events(self):
        return copy.deepcopy(self.saved["events"])

    def event(self, value):
        self.saved["events"].append(copy.deepcopy(value))

    def read_bytes(self, path, limit):
        if path not in self.files:
            raise FileNotFoundError("Authored missing input")
        return self.files[path]

    def review(self, *args, **kwargs):
        self.review_calls += 1
        return RunStore.review(self, *args, **kwargs)

    def refresh(self):
        self.refreshed.append(summary([entry["operating"] for entry in self.events()], current_state=self.state()))


class CurrentDispositionTests(unittest.TestCase):
    def guard(self, store):
        return patch("contract_playbook.upgrade.service.bounded_bytes", side_effect=store.read_bytes)

    def test_real_metrics_writer_uses_committed_recovery_state_without_rewriting_history(self):
        store = MemoryStore()
        store.saved["events"] = [{"operating": {"mode": "local-double", "state": "FAILED"}},
                                 {"operating": {"mode": "local-double", "state": "CANCELLED"}}]
        before = store.events()
        opened = mock_open()
        with patch.object(Path, "is_symlink", return_value=False), patch.object(Path, "open", opened), \
                patch("contract_playbook.upgrade.service.os.fsync"), patch("contract_playbook.upgrade.service.os.replace"):
            refresh_metrics(store)
        metrics = json.loads(opened().write.call_args_list[1].args[0])
        self.assertEqual(metrics["current_disposition"], "PENDING_REVIEW")
        self.assertEqual((metrics["failed"], metrics["cancelled"], metrics["pending_human_review"]), (0, 0, 1))
        self.assertEqual((metrics["historical_failure_events"], metrics["historical_cancellation_events"]), (1, 1))
        self.assertEqual(store.events(), before)

    def test_wrong_digest_with_changed_input_still_records_real_staleness(self):
        store = MemoryStore()
        store.files[Path("unit-source-agreement")] += b"Changed"
        with self.guard(store), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaisesRegex(ReviewError, "Current input changed"):
                review_store(store, "approve", "0" * 64, "fictional-reviewer")
        self.assertEqual(store.state(), "STALE")
        self.assertEqual(store.review_calls, 0)
        self.assertEqual(store.refreshed[-1]["stale"], 1)

    def test_wrong_digest_does_not_make_unchanged_inputs_stale(self):
        store = MemoryStore()
        budget_before = copy.deepcopy(store.load_checkpoint())
        with self.guard(store), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaisesRegex(ReviewError, "Expected proposal digest does not match"):
                review_store(store, "approve", "0" * 64, "fictional-reviewer")
        self.assertEqual(store.state(), "PENDING_REVIEW")
        self.assertEqual(store.review_calls, 1)
        self.assertEqual(store.load_checkpoint(), budget_before)
        self.assertEqual(store.refreshed[-1]["pending_human_review"], 1)
        self.assertEqual(store.refreshed[-1]["stale"], 0)
        self.assertEqual(store.refreshed[-1]["historical_stale_events"], 0)
        self.assertEqual(store.events()[-1]["operating"]["state"], "APPROVAL_DENIED")

    def test_changed_input_commits_stale_before_review_and_preserves_events_budget(self):
        store = MemoryStore()
        before, budget_before = store.events(), copy.deepcopy(store.load_checkpoint())
        store.files[Path("unit-source-agreement")] += b"Authored mutation"
        with self.guard(store), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaisesRegex(ReviewError, "Current input changed"):
                review_store(store, "approve", store.packet()["proposal_sha256"], "fictional-reviewer")
        self.assertEqual(store.state(), "STALE")
        self.assertEqual(store.review_calls, 0)
        self.assertEqual(store.events()[:len(before)], before)
        self.assertEqual(store.load_checkpoint(), budget_before)
        stale = store.events()[-2]["operating"]
        self.assertEqual((stale["state"], stale["committed_state"], stale["failure_code"]),
                         ("STALE", "STALE", "INPUT_CHANGED"))
        self.assertEqual((store.refreshed[-1]["stale"], store.refreshed[-1]["pending_human_review"]), (1, 0))
        self.assertEqual(store.refreshed[-1]["human_decisions"], 0)
        self.assertEqual(store.refreshed[-1]["verified_copy_delivered"], 0)

    def test_unavailable_input_is_stale_and_verify_refreshes_without_review(self):
        store = MemoryStore()
        del store.files[Path("unit-source-policy")]
        with self.guard(store), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaisesRegex(ReviewError, "Current input is unavailable"):
                verify_store(store)
        self.assertEqual(store.state(), "STALE")
        self.assertEqual(store.review_calls, 0)
        self.assertEqual(store.events()[-1]["operating"]["failure_code"], "INPUT_UNAVAILABLE")
        self.assertEqual(store.refreshed[-1]["current_disposition"], "STALE")

    def test_restored_input_does_not_revive_committed_stale_run(self):
        store = MemoryStore()
        original = store.files[Path("unit-source-agreement")]
        store.files[Path("unit-source-agreement")] += b"Changed"
        with self.guard(store), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaises(ReviewError):
                verify_store(store)
        reopened = MemoryStore(store.saved)
        reopened.files[Path("unit-source-agreement")] = original
        with self.guard(reopened), patch("contract_playbook.upgrade.service.refresh_metrics", side_effect=lambda value: value.refresh()):
            with self.assertRaisesRegex(ReviewError, "stale review requires a new run"):
                review_store(reopened, "approve", reopened.packet()["proposal_sha256"], "fictional-reviewer")
        self.assertEqual(reopened.state(), "STALE")
        self.assertEqual(reopened.review_calls, 0)
        self.assertEqual(reopened.refreshed[-1]["historical_stale_events"], 1)
        self.assertEqual(reopened.refreshed[-1]["pending_human_review"], 0)


class ProposalTests(unittest.TestCase):
    def test_approval_receipt_precondition_before_export(self):
        packet, originals, policy, manifest = control()
        report = check_proposal(packet, originals, policy, manifest)
        receipt = {"decision": "approve", "fictional": True,
                   "proposal_sha256": packet["proposal_sha256"], "source_sha256": report["source_sha256"],
                   "reviewed_documents": {"agreement": report["expected_copy_sha256"]}}
        self.assertEqual(check_receipt(receipt, packet, report)["approval_binding"], "passed")
        for field, value in (("decision", "reject"), ("source_sha256", "bad"), ("reviewed_documents", {})):
            with self.assertRaises(ProposalInvalid):
                check_receipt({**receipt, field: value}, packet, report)

    def test_unicode_preimage_and_untouched_bytes(self):
        packet, originals, policy, manifest = control()
        preview = originals["agreement"].replace(b"sixty", b"thirty")
        result = check_proposal(packet, originals, policy, manifest, previews={"agreement": preview})
        self.assertEqual(result["mechanical_verification"], "passed")
        self.assertEqual(result["semantic_correctness"], "unassessed")
        self.assertFalse(result["reviewed_copy_verified"])

    def test_wrong_source_quote_is_rejected_after_resigning(self):
        packet, originals, policy, manifest = control()
        packet["findings"][0]["evidence"][0]["quote"] = "invented"
        resign(packet)
        with self.assertRaises(ProposalInvalid):
            check_proposal(packet, originals, policy, manifest)

    def test_policy_mismatch_is_rejected(self):
        packet, originals, policy, manifest = control()
        packet["findings"][0]["policy_citation"]["quote"] = "different policy"
        resign(packet)
        with self.assertRaises(ProposalInvalid):
            check_proposal(packet, originals, policy, manifest)

    def test_invalid_preimage_and_bool_offset(self):
        for value in ("wrong", True):
            packet, originals, policy, manifest = control()
            for patch in (packet["patches"][0], packet["findings"][1]["patch"]):
                patch["expected_text" if isinstance(value, str) else "start"] = value
            resign(packet)
            with self.assertRaises(ProposalInvalid):
                check_proposal(packet, originals, policy, manifest)

    def test_unrelated_mutation_and_false_completed_copy(self):
        packet, originals, policy, manifest = control()
        for copy_bytes in (b"", originals["agreement"].replace(b"sixty", b"thirty").replace(b"Caf", b"Bad")):
            with self.assertRaises(ProposalInvalid):
                check_proposal(packet, originals, policy, manifest, reviewed={"agreement": copy_bytes})

    def test_digest_or_coverage_tampering(self):
        packet, originals, policy, manifest = control()
        packet["coverage"]["complete"] = False
        with self.assertRaises(ProposalInvalid):
            check_proposal(packet, originals, policy, manifest)
        resign(packet)
        with self.assertRaises(ProposalInvalid):
            check_proposal(packet, originals, policy, manifest)

    def test_alternative_wording_not_claimed_legal(self):
        packet, originals, policy, manifest = control()
        for patch in (packet["patches"][0], packet["findings"][1]["patch"]):
            patch["replacement"] = "30 calendar"
        resign(packet)
        report = check_proposal(packet, originals, policy, manifest)
        self.assertEqual(report["legal_correctness"], "unproven")

"""Lightweight M1 units; no complete CLI/demo/acceptance execution."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from contract_playbook.agent import investigate
from contract_playbook.common import ReviewError, canonical, parse_json, sha256
from contract_playbook.ingest import index_blocks, load_case
from contract_playbook.patches import apply_patches, validate_patch, validate_span
from contract_playbook.playbook import load_playbook
from contract_playbook.provider import ScriptedDecisionProvider
from contract_playbook.store import RunStore
from contract_playbook.tools import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "fixtures" / "dev" / "direct-review"
POLICY = ROOT / "fixtures" / "playbooks" / "buyer-services-v1.json"


class M1Units(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "work" / "unit"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.document = load_case(CASE)
        self.playbook = load_playbook(POLICY)
        self.registry = ToolRegistry(self.document, self.playbook)

    def source_span(self, quote="60", document=None):
        document = document or self.document
        start = document.text.index(quote)
        block = next(b for b in document.blocks if b["start"] <= start < b["end"])
        return {"document_id": "agreement", "document_sha256": document.version,
                "block_id": block["block_id"], "start": start,
                "end": start + len(quote), "quote": quote}

    def payment_patch(self, document=None):
        document = document or self.document
        quote = "Undisputed invoices are payable 15 calendar days after receipt by the Customer."
        span = self.source_span(quote, document)
        start = span["start"] + quote.index("15")
        patch = {"document_id": "agreement", "document_sha256": document.version,
                 "start": start, "end": start + 2, "expected_text": "15", "replacement": "30"}
        return span, patch

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ReviewError):
            parse_json(b'{"a":1,"a":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ReviewError):
            parse_json(b'{"a":NaN}')

    def test_source_bytes_are_lossless(self):
        self.assertEqual(self.document.raw, self.document.text.encode("utf-8"))
        self.assertEqual(self.document.version, sha256(CASE.joinpath("agreement.txt").read_bytes()))

    def test_boolean_schema_version_rejected(self):
        shutil.copytree(CASE, self.directory / "case")
        path = self.directory / "case" / "manifest.json"
        value = json.loads(path.read_text())
        value["schema_version"] = True
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ReviewError):
            load_case(path.parent)

    def test_amendments_are_explicitly_deferred(self):
        shutil.copytree(CASE, self.directory / "case")
        path = self.directory / "case" / "manifest.json"
        value = json.loads(path.read_text())
        value["documents"].append({"id": "a1", "file": "a1.txt", "type": "amendment"})
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ReviewError):
            load_case(path.parent)

    def test_traversal_input_rejected(self):
        shutil.copytree(CASE, self.directory / "case")
        path = self.directory / "case" / "manifest.json"
        value = json.loads(path.read_text())
        value["documents"][0]["file"] = "../agreement.txt"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ReviewError):
            load_case(path.parent)

    def test_duplicate_sections_rejected(self):
        with self.assertRaises(ReviewError):
            index_blocks("Section 1 - A\nOne\nSection 1 - B\nTwo")

    def test_corrupt_source_quote_rejected(self):
        span, _ = self.payment_patch()
        span["quote"] += " invented"
        with self.assertRaises(ReviewError):
            validate_span(span, self.document, {span["block_id"]})

    def test_citation_requires_read_block(self):
        span, _ = self.payment_patch()
        with self.assertRaises(ReviewError):
            validate_span(span, self.document, set())

    def test_citation_version_rejected(self):
        span, _ = self.payment_patch()
        span["document_sha256"] = "0" * 64
        with self.assertRaises(ReviewError):
            validate_span(span, self.document, {span["block_id"]})

    def test_invalid_patch_spans_rejected(self):
        span, valid = self.payment_patch()
        for start, end in [(-1, 4), (True, 4), (0, len(self.document.text) + 1),
                           (valid["end"], valid["start"])]:
            with self.subTest(start=start, end=end):
                patch = {**valid, "start": start, "end": end}
                with self.assertRaises(ReviewError):
                    validate_patch(patch, self.document, [span], [])

    def test_patch_cannot_change_uncited_fee(self):
        span, valid = self.payment_patch()
        fee = self.document.text.index("15,000")
        patch = {**valid, "start": fee, "end": fee + 2}
        with self.assertRaises(ReviewError):
            validate_patch(patch, self.document, [span], [])

    def test_patch_overlap_rejected(self):
        span, patch = self.payment_patch()
        with self.assertRaises(ReviewError):
            validate_patch(patch, self.document, [span], [patch])

    def test_patch_expected_text_rejected(self):
        span, patch = self.payment_patch()
        patch["expected_text"] = "90"
        with self.assertRaises(ReviewError):
            validate_patch(patch, self.document, [span], [])

    def test_unicode_and_crlf_preserved_outside_numeric_patch(self):
        text = self.document.text.replace("Customer: Alder Research", "Customer: Alder Café e\u0301 🦉").replace("\n", "\r\n")
        raw = text.encode("utf-8")
        document = replace(self.document, text=text, raw=raw, version=sha256(raw),
                           blocks=index_blocks(text))
        span, patch = self.payment_patch(document)
        validate_span(span, document, {span["block_id"]})
        validate_patch(patch, document, [span], [])
        reviewed = apply_patches(raw, [patch])
        prefix, suffix = raw.split(b"payable 15 calendar", 1)
        self.assertEqual(reviewed, prefix + b"payable 30 calendar" + suffix)
        self.assertEqual(reviewed.count(b"\r\n"), raw.count(b"\r\n"))
        self.assertIn(b"USD 15,000", reviewed)

    def test_unknown_tool_rejected(self):
        with self.assertRaises(ReviewError):
            self.registry.execute({"tool": "approve", "arguments": {}})
        self.assertFalse(self.registry.findings)

    def test_malformed_arguments_rejected(self):
        with self.assertRaises(ReviewError):
            self.registry.execute({"tool": "get_rule", "arguments": {"rule_id": []}})

    def test_completion_requires_three_findings(self):
        with self.assertRaises(ReviewError):
            self.registry.execute({"tool": "submit_review", "arguments": {}})

    def test_scripted_provider_uses_observation_not_case_labels(self):
        provider = ScriptedDecisionProvider()
        decision = provider.next(self.registry.observation(), {"calls": 48})
        self.assertEqual(decision, {"tool": "get_rule", "arguments": {"rule_id": "REN-01"}})
        self.registry.execute(decision)
        self.assertEqual(provider.next(self.registry.observation(), {})["tool"], "search_clauses")

    def test_notice_and_payment_proposals_target_different_numbers(self):
        provider = ScriptedDecisionProvider()
        for rule_id, old in [("TERM-01", "60"), ("PAY-01", "15")]:
            self.registry.execute({"tool": "get_rule", "arguments": {"rule_id": rule_id}})
            self.registry.execute({"tool": "search_clauses", "arguments": {"rule_id": rule_id}})
            hit = self.registry.searches[rule_id][0]
            self.registry.execute({"tool": "read_blocks", "arguments": {"block_ids": [hit["block_id"]]}})
            result = provider._classify(self.registry.rules_read[rule_id],
                                        self.registry.blocks_read[hit["block_id"]],
                                        self.registry.observation()["document"])
            patch = result["arguments"]["patch"]
            self.assertEqual(patch["expected_text"], old)
            self.assertEqual(patch["replacement"], "30")
            self.assertEqual(self.document.text[patch["start"]:patch["end"]], old)

    def test_bad_provider_is_bounded_and_has_feedback(self):
        observations = []
        class BadProvider:
            kind = "local-double"
            def next(self, observation, remaining_budget):
                observations.append(observation)
                return {"tool": "open_file", "arguments": {}}
        events = []
        with self.assertRaises(ReviewError) as failure:
            investigate(self.registry, BadProvider(), events.append, max_calls=5)
        self.assertEqual(failure.exception.code, 4)
        self.assertEqual(len(events), 3)
        self.assertIsNotNone(observations[1]["last_error"])

    def make_store(self):
        directory = self.directory / "run"
        store = RunStore(directory)
        self.addCleanup(store.close)
        source = self.directory / "original.txt"
        source.write_bytes(b"original")
        policy = self.directory / "policy.json"
        policy.write_bytes(b"policy")
        store.initialize("unit-key", {"agreement": (source, b"original"),
                                     "playbook": (policy, b"policy")})
        core = {"domain_status": "PENDING_REVIEW",
                "source": {"document_sha256": sha256(b"original")}, "patches": []}
        packet = {**core, "proposal_sha256": sha256(canonical(core))}
        store.finish(packet, {"model_calls": 0})
        (directory / "review.json").write_bytes(canonical(packet))
        return store, packet, source, policy

    def test_no_reviewed_file_before_approval(self):
        store, _, _, _ = self.make_store()
        self.assertEqual(store.state(), "PENDING_REVIEW")
        self.assertFalse((store.directory / "reviewed").exists())

    def test_exact_digest_required(self):
        store, _, _, _ = self.make_store()
        with self.assertRaises(ReviewError):
            store.review("approve", "wrong", "unit-reviewer")
        self.assertFalse((store.directory / "reviewed").exists())

    def test_reject_does_not_export(self):
        store, packet, source, _ = self.make_store()
        receipt = store.review("reject", packet["proposal_sha256"], "unit-reviewer")
        self.assertEqual(receipt["state"], "REJECTED")
        self.assertEqual(source.read_bytes(), b"original")
        self.assertFalse((store.directory / "reviewed").exists())

    def test_repeated_approval_is_idempotent(self):
        store, packet, source, _ = self.make_store()
        first = store.review("approve", packet["proposal_sha256"], "unit-reviewer")
        second = store.review("approve", packet["proposal_sha256"], "another-label")
        self.assertEqual(first, second)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM decision").fetchone()[0], 1)
        self.assertEqual((store.directory / "reviewed" / "agreement.txt").read_bytes(), b"original")
        self.assertEqual(source.read_bytes(), b"original")

    def test_stale_source_rejected_before_export(self):
        store, packet, source, _ = self.make_store()
        source.write_bytes(b"changed")
        with self.assertRaises(ReviewError):
            store.review("approve", packet["proposal_sha256"], "unit-reviewer")
        self.assertEqual(store.state(), "STALE")
        self.assertFalse((store.directory / "reviewed").exists())

    def test_stale_playbook_rejected_before_export(self):
        store, packet, _, policy = self.make_store()
        policy.write_bytes(b"changed policy")
        with self.assertRaises(ReviewError):
            store.review("approve", packet["proposal_sha256"], "unit-reviewer")
        self.assertFalse((store.directory / "reviewed").exists())

    def test_changed_proposal_rejected_before_export(self):
        store, packet, _, _ = self.make_store()
        changed = {**packet, "patches": [{"replacement": "forged"}]}
        (store.directory / "review.json").write_bytes(canonical(changed))
        with self.assertRaises(ReviewError):
            store.review("approve", packet["proposal_sha256"], "unit-reviewer")
        self.assertFalse((store.directory / "reviewed").exists())


if __name__ == "__main__":
    unittest.main()


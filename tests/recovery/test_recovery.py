"""LEASE REQUIRED: owned crash subprocesses, SQLite recovery and approval export."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from contract_playbook.common import ReviewError
from contract_playbook.service import REPOSITORY, resume_run, review, run_case
from contract_playbook.store import RunStore

CASE = REPOSITORY / "fixtures/dev/direct-review"
POLICY = REPOSITORY / "fixtures/playbooks/buyer-services-v1.json"


def owned_crash(out, phase, *, approval=False, count=1):
    program = """
import os, sys
from pathlib import Path
from contract_playbook.service import run_case, review
from contract_playbook.store import RunStore
phase, limit = sys.argv[4], int(sys.argv[6])
seen = 0
def failpoint(current):
    global seen
    if current == phase:
        seen += 1
        if seen == limit:
            os._exit(91)
out = Path(sys.argv[3])
if sys.argv[5] == 'approve':
    store = RunStore(out)
    packet = store.packet()
    store.close()
    review(out, 'approve', packet['proposal_sha256'], 'fictional-recovery-test', failpoint=failpoint)
else:
    run_case(Path(sys.argv[1]), Path(sys.argv[2]), out, failpoint=failpoint)
"""
    result = subprocess.run([sys.executable, "-c", program, str(CASE), str(POLICY), str(out),
                             phase, "approve" if approval else "investigate", str(count)],
                            cwd=REPOSITORY, capture_output=True, timeout=15)
    if result.returncode != 91:
        raise AssertionError(f"Expected owned crash 91; got {result.returncode}: {result.stderr.decode()}")


class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (REPOSITORY / "work").mkdir(exist_ok=True)

    def assert_once(self, out, packet):
        store = RunStore(out)
        try:
            events = store.events()
            decisions = [e["decision"] for e in events if e["error"] is None]
            self.assertEqual(sum(d["tool"] == "propose_finding" for d in decisions), 3)
            self.assertEqual(sum(d["tool"] == "submit_review" for d in decisions), 1)
            self.assertIsNone(store.pending_action())
            self.assertEqual(store.state(), "PENDING_REVIEW")
            self.assertEqual(packet, store.packet())
            return store.load_checkpoint()
        finally:
            store.close()

    def test_reservation_intent_tool_checkpoint_and_packet_crashes(self):
        for phase in ("after_provider_reservation", "after_intent_commit",
                      "after_tool_before_commit", "after_checkpoint_commit", "after_proposal_commit"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
                out = Path(tmp) / "run"
                owned_crash(out, phase)
                packet = resume_run(out)
                cp = self.assert_once(out, packet)
                self.assertEqual(len(packet["patches"]), 3)
                self.assertEqual(cp["budget"]["replays"], 1 if phase in
                                 ("after_intent_commit", "after_tool_before_commit") else 0)
                self.assertEqual(resume_run(out), packet)
                self.assertEqual(self.assert_once(out, packet), cp)

    def test_staged_finding_is_not_duplicated_on_replay(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
            out = Path(tmp) / "run"
            owned_crash(out, "after_tool_before_commit", count=4)  # First propose_finding, after get/search/read.
            packet = resume_run(out)
            self.assert_once(out, packet)
            receipt = review(out, "approve", packet["proposal_sha256"], "fictional-reviewer")
            self.assertEqual((out / "reviewed/agreement.txt").read_bytes(),
                             (REPOSITORY / "evaluation/m1_gold/direct-review.txt").read_bytes())
            self.assertEqual(review(out, "approve", packet["proposal_sha256"], "fictional-reviewer"), receipt)

    def test_approval_crashes_reuse_stored_draft_bytes(self):
        for phase in ("after_approval_commit", "after_draft_materialize", "before_export_commit"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
                out = Path(tmp) / "run"
                packet = run_case(CASE, POLICY, out)
                owned_crash(out, phase, approval=True)
                receipt = review(out, "approve", packet["proposal_sha256"], "fictional-recovery-test")
                before = (out / "reviewed/agreement.txt").read_bytes()
                self.assertEqual(before, (REPOSITORY / "evaluation/m1_gold/direct-review.txt").read_bytes())
                self.assertEqual(review(out, "approve", packet["proposal_sha256"], "fictional-recovery-test"), receipt)
                self.assertEqual(before, (out / "reviewed/agreement.txt").read_bytes())

    def test_budget_cannot_reset_by_resume(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
            out = Path(tmp) / "run"
            with self.assertRaises(ReviewError):
                run_case(CASE, POLICY, out, max_calls=2)
            store = RunStore(out)
            try:
                before = store.load_checkpoint()["budget"]
                self.assertEqual(store.state(), "BUDGET_EXHAUSTED")
                self.assertEqual(before["calls"], 2)
            finally:
                store.close()
            with self.assertRaises(ReviewError):
                resume_run(out)
            store = RunStore(out)
            try:
                self.assertEqual(store.load_checkpoint()["budget"], before)
            finally:
                store.close()

    def test_cancel_checkpoint_explicit_resume(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
            out = Path(tmp) / "run"
            def request_cancel(phase):
                if phase == "after_checkpoint_commit":
                    (out / "CANCEL").write_bytes(b"cancel\n")
            with self.assertRaises(KeyboardInterrupt):
                run_case(CASE, POLICY, out, failpoint=request_cancel)
            store = RunStore(out)
            try:
                self.assertEqual(store.state(), "CANCELLED")
                self.assertEqual(store.load_checkpoint()["budget"]["calls"], 1)
            finally:
                store.close()
            packet = resume_run(out)
            self.assertFalse((out / "CANCEL").exists())
            self.assert_once(out, packet)

    def test_stale_amendment_and_manifest_reject_review(self):
        source = REPOSITORY / "fixtures/dev/explicit-amendment"
        for filename in ("A1.txt", "manifest.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
                case, out = Path(tmp) / "case", Path(tmp) / "run"
                case.mkdir()
                for path in source.iterdir():
                    (case / path.name).write_bytes(path.read_bytes())
                packet = run_case(case, REPOSITORY / "fixtures/playbooks/buyer-services-v2.json", out)
                changed = case / filename
                changed.write_bytes(changed.read_bytes() + b"\n")
                with self.assertRaises(ReviewError):
                    review(out, "approve", packet["proposal_sha256"], "fictional-reviewer")
                self.assertFalse((out / "reviewed").exists())

    def test_multi_document_export_and_repeat_approval(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp:
            out = Path(tmp) / "run"
            packet = run_case(REPOSITORY / "fixtures/dev/precedence-amendments",
                REPOSITORY / "fixtures/playbooks/buyer-services-v2.json", out)
            receipt = review(out, "approve", packet["proposal_sha256"], "fictional-reviewer")
            self.assertEqual(set(receipt["reviewed_documents"]), {"agreement", "A1", "A2"})
            for doc_id in ("agreement", "A1", "A2"):
                expected = REPOSITORY / f"evaluation/labels/dev/precedence-amendments/{doc_id}.txt"
                self.assertEqual((out / "reviewed" / f"{doc_id}.txt").read_bytes(), expected.read_bytes())
            self.assertEqual(review(out, "approve", packet["proposal_sha256"], "fictional-reviewer"), receipt)


if __name__ == "__main__":
    unittest.main()

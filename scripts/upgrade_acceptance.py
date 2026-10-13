"""LEASE REQUIRED: bounded U1 CLI/process/SQLite approval and recovery journeys."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_playbook.common import canonical, sha256
from contract_playbook.proposal_check import check_proposal
from contract_playbook.providers.gateway import GatewayFailure
from contract_playbook.upgrade.double import FictionalGatewayDouble
from contract_playbook.upgrade.service import demo_u1, resume_u1
from contract_playbook.store import RunStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("u1",), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("Use a fresh output directory; prior receipts are immutable.")
    out.mkdir(parents=True)
    receipts = []
    def cli(arguments, expected=0):
        command = [sys.executable, "-B", "-m", "contract_playbook.upgrade", *map(str, arguments)]
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
        receipt = {"command": command, "exit_code": result.returncode,
                   "expected_exit": expected, "elapsed_seconds": time.monotonic() - started,
                   "stdout": result.stdout.decode(), "stderr": result.stderr.decode(),
                   "mode": "local-double", "live_calls": 0}
        receipts.append(receipt)
        with (out / "commands.jsonl").open("ab") as stream:
            stream.write(canonical(receipt) + b"\n")
            stream.flush()
        assert result.returncode == expected, receipt
        return json.loads(result.stdout) if result.stdout else None
    try:
        run = out / "normal"
        cli(["demo", "--model", "demo/u1", "--out", run])
        packet = json.loads((run / "review.json").read_bytes())
        assert packet["execution_mode"] == "local-double" and packet["live_model"] is False
        assert packet["domain_status"] == "PENDING_REVIEW" and len(packet["patches"]) == 3
        assert not (run / "reviewed").exists()
        root = ROOT / "fixtures/upgrade/u1-paraphrase"
        original = (root / "agreement.txt").read_bytes()
        policy = (ROOT / "fixtures/playbooks/buyer-services-v2.json").read_bytes()
        manifest = (root / "manifest.json").read_bytes()
        report = check_proposal(packet, {"agreement": original}, policy, manifest,
                                previews={"agreement": (run / "preview/agreement.txt").read_bytes()})
        assert report["patch_count"] == 3
        cli(["verify", "--run", run])
        cli(["review", "--run", run, "--decision", "approve", "--expected-proposal",
             "0" * 64, "--reviewer", "fictional-reviewer"], 3)
        assert not (run / "reviewed").exists()
        approve = ["review", "--run", run, "--decision", "approve",
                   "--expected-proposal", packet["proposal_sha256"], "--reviewer", "fictional-reviewer"]
        receipt = cli(approve)
        assert cli(approve) == receipt
        assert cli(["verify", "--run", run])["reviewed_copy_verified"] is True
        assert (root / "agreement.txt").read_bytes() == original
        check_proposal(packet, {"agreement": original}, policy, manifest,
                       reviewed={"agreement": (run / "reviewed/agreement.txt").read_bytes()})
        metrics = json.loads((run / "metrics.json").read_bytes())
        assert metrics["verified_copy_delivered"] == 1 and metrics["human_decisions"] == 1
        assert metrics["live_model_calls"] == 0 and metrics["actual_cost_usd"] is None
        denied = out / "reject"
        cli(["demo", "--model", "demo/u1", "--out", denied])
        reject_packet = json.loads((denied / "review.json").read_bytes())
        cli(["review", "--run", denied, "--decision", "reject",
             "--expected-proposal", reject_packet["proposal_sha256"], "--reviewer", "fictional-reviewer"])
        assert not (denied / "reviewed").exists()
        # Interrupted local intent has no external write; exact explicit resume retains counters.
        interrupted = out / "interrupted"
        def failpoint(phase):
            if phase == "after_intent_commit":
                raise RuntimeError("Authored interruption")
        try:
            demo_u1(interrupted, "demo/u1", failpoint=failpoint)
            raise AssertionError("Interruption expected")
        except GatewayFailure as exc:
            assert exc.status == "HOST_FAILURE"
        store = RunStore(interrupted)
        before = store.load_checkpoint()["budget"]
        store.close()
        cli(["resume", "--run", interrupted])
        store = RunStore(interrupted)
        after = store.load_checkpoint()["budget"]
        store.close()
        assert before["requests"] == 1 and after["requests"] >= before["requests"]
        assert after["replays"] == 1
        # Cancellation after a durable intent must preserve it without approved output.
        cancelled = out / "cancelled"
        def cancel_intent(phase):
            if phase == "after_intent_commit":
                (cancelled / "CANCEL").write_bytes(b"cancel\n")
        try:
            demo_u1(cancelled, "demo/u1", failpoint=cancel_intent)
            raise AssertionError("Cancellation expected")
        except KeyboardInterrupt:
            pass
        assert not (cancelled / "reviewed").exists()
        cli(["resume", "--run", cancelled])
        # Stale input control changes a private test copy, never repository input.
        stale_case = out / "stale-source"
        shutil.copytree(root, stale_case)
        from contract_playbook.providers.gateway import GatewayConfig
        from contract_playbook.upgrade.service import run_u1
        stale_run = out / "stale"
        run_u1(stale_case, ROOT / "fixtures/playbooks/buyer-services-v2.json", stale_run, GatewayConfig("demo/u1"))
        stale_packet = json.loads((stale_run / "review.json").read_bytes())
        with (stale_case / "agreement.txt").open("ab") as stream:
            stream.write(b"\nAuthored stale-input mutation.\n")
        cli(["review", "--run", stale_run, "--decision", "approve", "--expected-proposal",
             stale_packet["proposal_sha256"], "--reviewer", "fictional-reviewer"], 3)
        assert not (stale_run / "reviewed").exists()
        # A meaningful uncertain finding must stay a handoff, not a verified copy.
        class HandoffDouble(FictionalGatewayDouble):
            def _reply(self, request, budget, name, arguments):
                if name == "propose_finding" and arguments["rule_id"] == "REN-01":
                    arguments = {**arguments, "disposition": "uncertain", "patch": None,
                                 "obligations": {a: "uncertain" for a in arguments["obligations"]}}
                return super()._reply(request, budget, name, arguments)
        handoff = out / "handoff"
        handoff_packet = demo_u1(handoff, "demo/u1", transport=HandoffDouble())
        assert handoff_packet["domain_status"] == "HANDOFF"
        cli(["review", "--run", handoff, "--decision", "approve", "--expected-proposal",
             handoff_packet["proposal_sha256"], "--reviewer", "fictional-reviewer"], 3)
        assert not (handoff / "reviewed").exists()
        assert json.loads((handoff / "metrics.json").read_bytes())["verified_copy_delivered"] == 0
        result = {"status": "passed", "mode": "local-double", "unique_semantic_tasks": 1,
                  "cli_receipts": len(receipts), "live_calls": 0, "external_sandbox_calls": 0,
                  "original_sha256": sha256(original), "legal_correctness": "unproven",
                  "ram_peak_bytes": None}
    except Exception as exc:
        result = {"status": "failed", "failure_type": type(exc).__name__,
                  "mode": "local-double", "cli_receipts": len(receipts), "live_calls": 0}
        (out / "summary.json").write_bytes(canonical(result) + b"\n")
        raise
    (out / "summary.json").write_bytes(canonical(result) + b"\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

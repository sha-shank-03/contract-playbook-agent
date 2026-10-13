"""LEASE REQUIRED: targeted U1-1.1 current-state correction; no HTTP or old batch rerun."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_playbook.common import canonical, sha256
from contract_playbook.proposal_check import check_proposal
from contract_playbook.providers.gateway import GatewayConfig, GatewayFailure
from contract_playbook.upgrade.service import run_u1

MAX_SECONDS = 90


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise SystemExit("Use fresh output; old receipts are immutable.")
    if out == ROOT or not out.is_relative_to(ROOT / "work"):
        raise SystemExit("Correction output must be inside repository work.")
    out.mkdir(parents=True)
    started = time.monotonic()
    receipts, controls = [], []
    manifest_raw = (ROOT / "UPGRADE_MANIFEST_U1_1_1.json").read_bytes()
    source_manifest = json.loads(manifest_raw)
    fixture = ROOT / "fixtures/upgrade/u1-paraphrase"
    policy_path = ROOT / "fixtures/playbooks/buyer-services-v2.json"
    original, policy, fixture_manifest = ((fixture / "agreement.txt").read_bytes(),
                                          policy_path.read_bytes(), (fixture / "manifest.json").read_bytes())
    config = GatewayConfig("demo/u1", max_requests=16, max_steps=16, max_seconds=20, request_seconds=5)

    def append_receipt(receipt):
        receipts.append(receipt)
        with (out / "commands.jsonl").open("ab") as stream:
            stream.write(canonical(receipt) + b"\n")
            stream.flush()

    def cli(arguments, expected=0):
        command = [sys.executable, "-B", "-m", "contract_playbook.upgrade", *map(str, arguments)]
        remaining = MAX_SECONDS - (time.monotonic() - started)
        assert remaining > 0, "Correction batch deadline exhausted."
        before = time.monotonic()
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=min(10, remaining))
        except subprocess.TimeoutExpired as exc:
            append_receipt({"command": command, "exit_code": None, "expected_exit": expected,
                            "elapsed_seconds": time.monotonic() - before, "failure": "OWNED_CLI_TIMEOUT",
                            "stdout": (exc.stdout or b"").decode(errors="replace"),
                            "stderr": (exc.stderr or b"").decode(errors="replace"), "live_calls": 0})
            raise
        receipt = {"command": command, "exit_code": result.returncode, "expected_exit": expected,
                   "elapsed_seconds": time.monotonic() - before, "stdout": result.stdout.decode(),
                   "stderr": result.stderr.decode(), "mode": "local-double", "live_calls": 0,
                   "cleanup": "owned_cli_exited"}
        append_receipt(receipt)
        assert result.returncode == expected, receipt
        return json.loads(result.stdout) if result.stdout else None

    def snapshot(run):
        db = sqlite3.connect((run / "run.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            state, packet = db.execute("SELECT state,packet FROM run").fetchone()
            checkpoint = json.loads(db.execute("SELECT body FROM checkpoint").fetchone()[0])
            events = [json.loads(body) for (body,) in db.execute("SELECT body FROM events ORDER BY seq")]
            decisions = db.execute("SELECT count(*) FROM decision").fetchone()[0]
            drafts = db.execute("SELECT count(*) FROM drafts").fetchone()[0]
            intents = db.execute("SELECT count(*) FROM intent").fetchone()[0]
        finally:
            db.close()
        metrics = json.loads((run / "metrics.json").read_bytes())
        assert metrics["schema_version"] == 2 and metrics["current_disposition"] == state
        assert metrics["live_model_calls"] == 0 and metrics["actual_cost_usd"] is None
        return {"state": state, "packet": json.loads(packet) if packet else None,
                "budget": checkpoint["budget"], "events": events, "decisions": decisions,
                "drafts": drafts, "intents": intents, "metrics": metrics}

    def source_unchanged():
        assert (ROOT / "UPGRADE_MANIFEST_U1_1_1.json").read_bytes() == manifest_raw
        assert sha256((ROOT / "evaluation/HELDOUT_FREEZE.json").read_bytes()) == source_manifest["original_freeze_sha256"]
        for entry in source_manifest["source_entries"]:
            raw = (ROOT / entry["path"]).read_bytes()
            assert len(raw) == entry["bytes"] and sha256(raw) == entry["sha256"], entry["path"]
        assert (fixture / "agreement.txt").read_bytes() == original

    try:
        source_unchanged()
        for name, interruption in (("interrupted", "failure"), ("cancelled", "cancel")):
            run = out / name
            def failpoint(phase):
                if phase == "after_intent_commit":
                    if interruption == "failure":
                        raise RuntimeError("Authored correction interruption")
                    (run / "CANCEL").write_bytes(b"cancel\n")
            try:
                run_u1(fixture, policy_path, run, config, failpoint=failpoint)
                raise AssertionError("Authored interruption was not observed.")
            except GatewayFailure as exc:
                assert interruption == "failure" and exc.status == "HOST_FAILURE"
            except KeyboardInterrupt:
                assert interruption == "cancel"
            before = snapshot(run)
            assert before["state"] == ("FAILED" if interruption == "failure" else "CANCELLED")
            assert before["budget"]["requests"] == 1 and before["intents"] == 1
            assert not (run / "reviewed").exists()
            cli(["resume", "--run", run])
            after = snapshot(run)
            assert after["state"] == "PENDING_REVIEW" and after["metrics"]["pending_human_review"] == 1
            assert after["metrics"]["failed"] == 0 and after["metrics"]["cancelled"] == 0
            historical = "historical_failure_events" if interruption == "failure" else "historical_cancellation_events"
            assert after["metrics"][historical] >= 1
            assert after["events"][:len(before["events"])] == before["events"]
            assert after["budget"]["requests"] == 12 and after["budget"]["steps"] == 12
            assert after["budget"]["replays"] == 1 and after["budget"]["seconds_used"] >= before["budget"]["seconds_used"]
            assert after["intents"] == after["decisions"] == after["drafts"] == 0
            assert not after["budget"]["request_in_flight"] and not (run / "reviewed").exists()
            controls.append({"run": name, "before": before, "after": after})

        approval = out / "approval"
        run_u1(fixture, policy_path, approval, config)
        pending = snapshot(approval)
        wrong = ["review", "--run", approval, "--decision", "approve",
                 "--expected-proposal", "0" * 64, "--reviewer", "fictional-reviewer"]
        cli(wrong, 3)
        denied = snapshot(approval)
        assert denied["state"] == "PENDING_REVIEW" and denied["metrics"]["pending_human_review"] == 1
        assert denied["metrics"]["stale"] == denied["metrics"]["historical_stale_events"] == 0
        assert denied["decisions"] == denied["drafts"] == 0 and denied["budget"] == pending["budget"]
        assert not (approval / "reviewed").exists()
        approve = ["review", "--run", approval, "--decision", "approve", "--expected-proposal",
                   pending["packet"]["proposal_sha256"], "--reviewer", "fictional-reviewer"]
        receipt = cli(approve)
        assert cli(approve) == receipt
        assert cli(["verify", "--run", approval])["reviewed_copy_verified"] is True
        final = snapshot(approval)
        assert final["state"] == "DRAFT_EXPORTED" and final["metrics"]["verified_copy_delivered"] == 1
        assert final["decisions"] == final["drafts"] == final["metrics"]["human_decisions"] == 1
        assert final["budget"] == pending["budget"]
        check_proposal(pending["packet"], {"agreement": original}, policy, fixture_manifest,
                       reviewed={"agreement": (approval / "reviewed/agreement.txt").read_bytes()})
        controls.append({"run": "approval", "pending": pending, "wrong_digest_denied": denied, "final": final})

        stale_source, stale = out / "stale-source", out / "stale"
        shutil.copytree(fixture, stale_source)
        run_u1(stale_source, policy_path, stale, config)
        before = snapshot(stale)
        with (stale_source / "agreement.txt").open("ab") as stream:
            stream.write(b"\nAuthored correction stale-input mutation.\n")
        cli(["review", "--run", stale, "--decision", "approve", "--expected-proposal",
             before["packet"]["proposal_sha256"], "--reviewer", "fictional-reviewer"], 3)
        after = snapshot(stale)
        assert after["state"] == "STALE" and after["metrics"]["stale"] == 1
        assert after["metrics"]["pending_human_review"] == after["metrics"]["verified_copy_delivered"] == 0
        assert after["metrics"]["historical_stale_events"] == 1
        assert after["decisions"] == after["drafts"] == 0 and after["budget"] == before["budget"]
        assert after["events"][:len(before["events"])] == before["events"]
        assert not (stale / "reviewed").exists() and not (stale / "review-receipt.json").exists()
        (stale_source / "agreement.txt").write_bytes(original)
        cli(["verify", "--run", stale], 3)
        restored = snapshot(stale)
        assert restored["state"] == "STALE" and restored["metrics"]["historical_stale_events"] == 1
        assert restored["decisions"] == restored["drafts"] == 0 and not (stale / "reviewed").exists()
        controls.append({"run": "stale", "before": before, "after": after, "input_restored": restored})
        source_unchanged()
        assert time.monotonic() - started < MAX_SECONDS
        result = {"status": "passed", "candidate": "U1-1.1", "mode": "local-double",
                  "unique_semantic_tasks": 1, "targeted_controls": len(controls), "cli_receipts": len(receipts),
                  "elapsed_seconds": time.monotonic() - started, "live_calls": 0, "external_calls": 0,
                  "source_manifest_sha256": sha256(manifest_raw), "ram_peak_bytes": None,
                  "legal_correctness": "unproven"}
    except BaseException as exc:
        result = {"status": "failed", "candidate": "U1-1.1", "failure_type": type(exc).__name__,
                  "elapsed_seconds": time.monotonic() - started, "cli_receipts": len(receipts), "live_calls": 0}
        (out / "controls.json").write_bytes(canonical(controls) + b"\n")
        (out / "summary.json").write_bytes(canonical(result) + b"\n")
        raise
    (out / "controls.json").write_bytes(canonical(controls) + b"\n")
    (out / "summary.json").write_bytes(canonical(result) + b"\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


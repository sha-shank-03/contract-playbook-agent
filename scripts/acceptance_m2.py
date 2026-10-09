"""LEASE REQUIRED: development-only CLI acceptance; never opens or scores held-out labels."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from evaluation.m2_dev_verifier import verify


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    base = args.out.resolve()
    base.mkdir(parents=True, exist_ok=True)
    number = 1
    while (base / f"attempt-{number:03d}").exists():
        number += 1
    out = base / f"attempt-{number:03d}"
    out.mkdir()
    labels = json.loads((ROOT / "evaluation/labels/development.json").read_bytes())["cases"]
    assert len(labels) == 12
    input_paths = [p for p in (ROOT / "fixtures/dev").rglob("*") if p.is_file()]
    input_paths.extend((ROOT / golden["playbook"]) for golden in labels.values())
    originals = {p: p.read_bytes() for p in input_paths}
    commands, domain, assertions = [], [], 0
    started = datetime.now(timezone.utc).isoformat()
    def require(condition, message):
        nonlocal assertions
        assertions += 1
        if not condition:
            raise AssertionError(message)
    def command(*values, expected=0):
        argv = [sys.executable, "-m", "contract_playbook", *map(str, values)]
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=20)
        commands.append({"argv": argv, "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        require(result.returncode == expected, f"CLI exit {result.returncode}, expected {expected}: {result.stderr}")
        return json.loads(result.stdout) if result.stdout else json.loads(result.stderr)
    def oracle(run, golden, reviewed=False):
        nonlocal assertions
        result = verify(run, ROOT, golden, reviewed=reviewed)
        assertions += result["assertions"]
        domain.append({"fixture": golden["fixture"], "reviewed": reviewed, **result})
    try:
        for name, golden in labels.items():
            run = out / name
            result = command("demo", "--case", name, "--out", run)
            require(result["domain_status"] == golden["domain_status"], "Demo domain outcome")
            oracle(run, golden)
            packet = json.loads((run / "review.json").read_bytes())
            require(len(packet["patches"]) == sum(r["patch"] is not None for r in golden["rules"].values()), "Patch count")
            if golden["domain_status"] == "PENDING_REVIEW":
                receipt = command("review", "--run", run, "--decision", "approve",
                                  "--expected-proposal", packet["proposal_sha256"], "--reviewer", "fictional-m2-reviewer")
                oracle(run, golden, reviewed=True)
                require(receipt["reviewed_documents"] == {key: value["sha256"] for key, value in golden["reviewed_files"].items()}, "Reviewed receipt hashes")
            else:
                command("review", "--run", run, "--decision", "approve",
                        "--expected-proposal", packet["proposal_sha256"], "--reviewer", "fictional-m2-reviewer", expected=3)
                require(not (run / "reviewed").exists(), "Unknown/conflict handoff exported")
        direct = out / "direct-review"
        packet = json.loads((direct / "review.json").read_bytes())
        first = json.loads((direct / "review-receipt.json").read_bytes())
        repeated = command("review", "--run", direct, "--decision", "approve",
                           "--expected-proposal", packet["proposal_sha256"], "--reviewer", "other-fictional-label")
        require(first == repeated, "Approval must be idempotent")
        require(command("demo", "--case", "direct-review", "--out", direct)["proposal_sha256"] == packet["proposal_sha256"], "Repeated proposal digest")
        mutant = out / "verifier-mutation"
        shutil.copytree(direct, mutant)
        preview = mutant / "preview/agreement.txt"
        preview.write_bytes(preview.read_bytes().replace(b"15,000", b"99,000"))
        try:
            verify(mutant, ROOT, labels["direct-review"], reviewed=True)
        except AssertionError:
            assertions += 1
        else:
            raise AssertionError("Independent verifier accepted unrelated fee change")
        for path, raw in originals.items():
            require(path.read_bytes() == raw, "Original input changed")
        summary = {"status": "passed", "milestone": "m2-development", "assertions": assertions,
            "commands": commands, "domain_checks": domain, "distinct_authored_cases": 12, "unique_rule_outcomes": 36,
            "heldout_cases_scored": 0, "provider_kind": "scripted", "model_calls": 0,
            "model_quality_evaluated": False, "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_actions": "Explicit simulated CLI reviews on fictional fixtures"}
    except (AssertionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        summary = {"status": "failed", "milestone": "m2-development", "error": str(exc),
                   "assertions_before_failure": assertions, "commands": commands, "domain_checks": domain,
                   "heldout_cases_scored": 0, "started_at": started,
                   "finished_at": datetime.now(timezone.utc).isoformat()}
    (out / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "evidence": str(out / "acceptance.json"),
                      "assertions": summary.get("assertions", summary.get("assertions_before_failure"))}))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

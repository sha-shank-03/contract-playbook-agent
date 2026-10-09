"""M1 CLI integration and independently scored authored outcomes."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.m1_verifier import verify_packet


def main():
    parser = argparse.ArgumentParser(description="Independent authored M1 acceptance.")
    parser.add_argument("--milestone", choices=("m1","m2","all"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evaluation",type=Path,help="Existing frozen paired evaluation, required for all.")
    args = parser.parse_args()
    if args.milestone=="m2":
        if args.evaluation is not None: parser.error("--evaluation is only used with all.")
        from acceptance_m2 import main as m2_main
        return m2_main(["--out",str(args.out)])
    if args.milestone=="all":
        if args.evaluation is None: parser.error("all requires --evaluation; produce the paired evaluation once first.")
        from release_acceptance import run_all
        return run_all(args.out,args.evaluation)
    if args.evaluation is not None: parser.error("--evaluation is only used with all.")
    parent = args.out.resolve()
    if not parent.is_relative_to(ROOT / "work") or any(p.is_symlink() for p in [args.out, *args.out.parents]):
        parser.error("Acceptance output must be an unlinked directory under work/.")
    parent.mkdir(parents=True, exist_ok=True)
    for number in range(1, 10000):
        out = parent / f"attempt-{number:03d}"
        try:
            out.mkdir()
            break
        except FileExistsError:
            continue
    else:
        parser.error("No fresh acceptance attempt directory is available.")
    expectations = json.loads((ROOT / "evaluation" / "m1_expectations.json").read_bytes())
    policy = ROOT / "fixtures" / "playbooks" / "buyer-services-v1.json"
    commands = []
    domain_checks = []
    assertions = 0
    originals = {path: path.read_bytes() for path in (ROOT / "fixtures").rglob("*") if path.is_file()}

    def require(condition, message):
        nonlocal assertions
        assertions += 1
        if not condition:
            raise AssertionError(message)

    def command(*parameters, expected_exit=0):
        invocation = [sys.executable, "-m", "contract_playbook", *map(str, parameters)]
        completed = subprocess.run(invocation, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", timeout=20)
        commands.append({"command": invocation, "exit_code": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr,
                         "expected_exit": expected_exit})
        require(completed.returncode == expected_exit, "CLI exit code mismatch")
        return json.loads(completed.stdout) if completed.stdout.strip() else None

    def oracle(run, case_id, reviewed=False, case_dir=None):
        nonlocal assertions
        gold = {**expectations["cases"][case_id]}
        gold["expected_file"] = str(ROOT / gold["expected_file"])
        result = verify_packet(run, case_dir or ROOT / "fixtures" / "dev" / case_id,
                               gold, policy, expect_reviewed=reviewed)
        assertions += result["assertions"]
        domain_checks.append({"case": case_id, "reviewed": reviewed, **result})

    def packet(run):
        return json.loads((run / "review.json").read_bytes())

    try:
        direct, compliant = out / "direct", out / "compliant"
        command("demo", "--case", "direct-review", "--out", direct)
        oracle(direct, "direct-review")
        command("demo", "--case", "compliant-review", "--out", compliant)
        oracle(compliant, "compliant-review")
        require(packet(compliant)["patches"] == [], "Compliant contract must have zero edits")

        rejected = out / "rejected"
        command("demo", "--case", "direct-review", "--out", rejected)
        rejected_digest = packet(rejected)["proposal_sha256"]
        rejection = command("review", "--run", rejected, "--decision", "reject",
                            "--expected-proposal", rejected_digest, "--reviewer", "acceptance-simulation")
        require(rejection["state"] == "REJECTED", "Rejected domain state")
        require(not (rejected / "reviewed").exists(), "Rejected proposal exported")
        oracle(rejected, "direct-review")

        stale_case, stale_run = out / "stale-input", out / "stale-run"
        shutil.copytree(ROOT / "fixtures" / "dev" / "direct-review", stale_case)
        command("run", "--case-dir", stale_case, "--playbook", policy, "--out", stale_run)
        stale_digest = packet(stale_run)["proposal_sha256"]
        with (stale_case / "agreement.txt").open("ab") as stream:
            stream.write(b"\nSimulated concurrent source change.\n")
        command("review", "--run", stale_run, "--decision", "approve",
                "--expected-proposal", stale_digest, "--reviewer", "acceptance-simulation", expected_exit=3)
        require(not (stale_run / "reviewed").exists(), "Stale source exported")
        with sqlite3.connect(stale_run / "run.sqlite3") as db:
            require(db.execute("SELECT state FROM run").fetchone()[0] == "STALE", "Stale domain state")

        forged = out / "forged-proposal"
        command("demo", "--case", "direct-review", "--out", forged)
        changed = packet(forged)
        original_digest = changed["proposal_sha256"]
        changed["findings"][0]["evidence"][0]["quote"] += " forged"
        (forged / "review.json").write_text(json.dumps(changed), encoding="utf-8")
        command("review", "--run", forged, "--decision", "approve",
                "--expected-proposal", original_digest, "--reviewer", "acceptance-simulation", expected_exit=3)
        require(not (forged / "reviewed").exists(), "Changed proposal exported")

        digest = packet(direct)["proposal_sha256"]
        receipt = command("review", "--run", direct, "--decision", "approve",
                          "--expected-proposal", digest, "--reviewer", "acceptance-simulation")
        oracle(direct, "direct-review", reviewed=True)
        repeated = command("review", "--run", direct, "--decision", "approve",
                           "--expected-proposal", digest, "--reviewer", "acceptance-simulation")
        require(receipt == repeated, "Repeated approval must return the same receipt")
        with sqlite3.connect(direct / "run.sqlite3") as db:
            require(db.execute("SELECT COUNT(*) FROM decision").fetchone()[0] == 1,
                    "Duplicate approval decision")

        command("review", "--run", compliant, "--decision", "approve",
                "--expected-proposal", packet(compliant)["proposal_sha256"],
                "--reviewer", "acceptance-simulation")
        oracle(compliant, "compliant-review", reviewed=True)

        mutant = out / "verifier-mutation"
        shutil.copytree(direct, mutant)
        preview = mutant / "preview" / "agreement.txt"
        preview.write_bytes(preview.read_bytes().replace(b"15,000", b"99,000"))
        gold = {**expectations["cases"]["direct-review"]}
        gold["expected_file"] = str(ROOT / gold["expected_file"])
        try:
            verify_packet(mutant, ROOT / "fixtures" / "dev" / "direct-review",
                          gold, policy, expect_reviewed=True)
        except AssertionError:
            assertions += 1
        else:
            raise AssertionError("Independent verifier accepted an unrelated fee mutation")

        for path, raw in originals.items():
            require(path.read_bytes() == raw, "An original fixture/playbook changed")
        summary = {"status": "passed", "milestone": "m1", "assertions": assertions,
                   "commands": commands, "domain_checks": domain_checks,
                   "distinct_authored_cases": 2, "rule_dispositions": 6,
                   "provider_kind": "scripted", "model_calls": 0,
                   "model_quality_evaluated": False,
                   "reviewer_decisions": "simulated explicit CLI actions on fictional fixtures",
                   "unexecuted": ["Real models", "M2/M3", "Hosted CI"]}
    except (AssertionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        summary = {"status": "failed", "milestone": "m1", "assertions_before_failure": assertions,
                   "error": str(exc), "commands": commands, "domain_checks": domain_checks,
                   "provider_kind": "scripted", "model_quality_evaluated": False}
    (out / "acceptance.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "evidence": str(out / "acceptance.json"),
                      "assertions": summary.get("assertions", summary.get("assertions_before_failure"))}))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


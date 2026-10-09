"""Run with py -3.11 -m contract_playbook."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .common import ReviewError
from .service import DEV_CASES, cancel_run, demo, resume_run, review, run_case


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review authored fictional clauses with bounded tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo")
    demo_parser.add_argument("--case", choices=DEV_CASES, required=True)
    demo_parser.add_argument("--out", type=Path, required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--case-dir", type=Path, required=True)
    run_parser.add_argument("--playbook", type=Path, required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--provider", choices=("scripted", "keyword", "ollama"), default="scripted")
    run_parser.add_argument("--endpoint")
    run_parser.add_argument("--model")
    run_parser.add_argument("--max-calls", type=int, default=48)
    run_parser.add_argument("--max-seconds", type=float, default=120)
    for name in ("resume", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
    review_parser = commands.add_parser("review")
    review_parser.add_argument("--run", type=Path, required=True)
    review_parser.add_argument("--decision", choices=("approve", "reject"), required=True)
    review_parser.add_argument("--expected-proposal", required=True)
    review_parser.add_argument("--reviewer", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            packet = demo(args.case, args.out)
        elif args.command == "run":
            packet = run_case(args.case_dir, args.playbook, args.out,
                              provider_kind=args.provider, endpoint=args.endpoint, model=args.model,
                              max_calls=args.max_calls, max_seconds=args.max_seconds)
        elif args.command == "resume":
            packet = resume_run(args.run)
        elif args.command == "cancel":
            result = cancel_run(args.run)
            packet = None
        else:
            result = review(args.run, args.decision, args.expected_proposal, args.reviewer)
            packet = None
        if packet is not None:
            result = {"domain_status": packet["domain_status"],
                      "proposal_sha256": packet["proposal_sha256"],
                      "patch_count": len(packet["patches"]), "original_unchanged": True,
                      "provider_kind": packet["provider_kind"], "live_model": packet["live_model"]}
        print(json.dumps(result, sort_keys=True))
        return 0
    except ReviewError as exc:
        print(json.dumps({"error": str(exc), "exit_code": exc.code}), file=sys.stderr)
        return exc.code
    except (OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc), "exit_code": 4}), file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print(json.dumps({"error": "Cancelled.", "exit_code": 130}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


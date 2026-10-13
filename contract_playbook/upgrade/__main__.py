"""Explicit local-double U1 CLI. No credential, account or live-provider access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from ..common import ReviewError
from ..proposal_check import ProposalInvalid
from ..service import cancel_run, review
from ..store import RunStore
from .service import demo_u1, resume_u1, verify_store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fictional U1 Gateway-envelope local double; no live inference.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--model", required=True, help="Explicit synthetic provider/model ID, e.g. demo/u1.")
    demo.add_argument("--out", required=True, type=Path)
    for name in ("resume", "cancel", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True, type=Path)
    decision = commands.add_parser("review")
    decision.add_argument("--run", required=True, type=Path)
    decision.add_argument("--decision", choices=("approve", "reject"), required=True)
    decision.add_argument("--expected-proposal", required=True)
    decision.add_argument("--reviewer", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "demo":
            packet = demo_u1(args.out, args.model)
        elif args.command == "resume":
            if not (args.run / "run.sqlite3").is_file():
                raise ReviewError("Run not found.", 3)
            packet = resume_u1(args.run)
        elif args.command == "cancel":
            print(json.dumps(cancel_run(args.run)))
            return 0
        elif args.command == "review":
            print(json.dumps(review(args.run, args.decision, args.expected_proposal, args.reviewer)))
            return 0
        else:
            if not (args.run / "run.sqlite3").is_file():
                raise ReviewError("Run not found.", 3)
            store = RunStore(args.run)
            try:
                print(json.dumps(verify_store(store), sort_keys=True))
            finally:
                store.close()
            return 0
        print(json.dumps({"domain_status": packet["domain_status"],
                          "proposal_sha256": packet["proposal_sha256"],
                          "execution_mode": packet["execution_mode"], "live_model": False,
                          "patch_count": len(packet["patches"])}))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"error": "CANCELLED", "exit_code": 130}), file=sys.stderr)
        return 130
    except (ReviewError, ProposalInvalid, OSError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, ReviewError) else 4
        print(json.dumps({"error": str(exc), "exit_code": code}), file=sys.stderr)
        return code


if __name__ == "__main__":
    raise SystemExit(main())

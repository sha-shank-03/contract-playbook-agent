"""Offline frozen evaluation. This command performs held-out scoring and needs the M3 integration grant locally."""
import argparse
import json
from pathlib import Path
import sys

from .corpus import VerificationError
from .runner import diagnostic, run_evaluation, verify_existing


def main(argv=None):
    parser=argparse.ArgumentParser(description="Paired authored regression outcomes; no live model.")
    parser.add_argument("--suite",choices=("heldout",),default="heldout")
    parser.add_argument("--provider",choices=("scripted",),default="scripted")
    parser.add_argument("--baseline",choices=("keyword",),default="keyword")
    parser.add_argument("--repetitions",type=int,choices=(3,),default=3)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--verify-only",action="store_true")
    args=parser.parse_args(argv)
    try:
        result=verify_existing(args.out) if args.verify_only else run_evaluation(args.out,args.repetitions)
        print(json.dumps({"status":result["status"],"evaluation":str(args.out),
                          "primary_cases_per_provider":30,"primary_rules_per_provider":90,
                          "primary_atoms_per_provider":210,"repeat_comparisons":120,
                          "model_quality_evaluated":False}))
        return 0 if result["status"]=="passed" else 1
    except (VerificationError,OSError,ValueError,KeyError) as exc:
        error=diagnostic(exc,"evaluation-cli")
        print(json.dumps({"status":"failed","diagnostic":error}),file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status":"cancelled","error":"Interrupted; retain partial work and exposure record. Use a fresh output for another evaluation."}),file=sys.stderr)
        return 130


if __name__=="__main__":
    raise SystemExit(main())

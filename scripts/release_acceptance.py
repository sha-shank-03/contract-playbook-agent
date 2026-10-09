"""Sequential full acceptance. Regrade existing paired outputs; never run hidden held-out producers."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.corpus import VerificationError, canonical, digest
from evaluation.runner import source_identity, verify_existing


def fresh_attempt(parent):
    original=Path(parent)
    parent=original.resolve()
    if not parent.is_relative_to((ROOT/"work").resolve()) or any(p.is_symlink() for p in (original,*original.parents)):
        raise VerificationError("Acceptance output must be unlinked under work/.")
    parent.mkdir(parents=True,exist_ok=True)
    for number in range(1,10000):
        out=parent/f"attempt-{number:03d}"
        try:
            out.mkdir()
            return out
        except FileExistsError:
            continue
    raise VerificationError("No fresh acceptance attempt directory.")


def command_plan(out):
    """Every suite is explicit: unittest discover does not recurse into non-package directories."""
    return [
        ["scripts/check_repository.py"],
        ["-m","unittest","discover","-s","tests","-p","test_m1_*.py"],
        ["-m","unittest","discover","-s","tests/components","-p","test_*.py"],
        ["-m","unittest","discover","-s","tests/provider_contract","-p","test_*.py"],
        ["-m","unittest","discover","-s","tests/recovery","-p","test_*.py"],
        ["scripts/acceptance.py","--milestone","m1","--out",str(out/"m1")],
        ["scripts/acceptance.py","--milestone","m2","--out",str(out/"m2")],
    ]


def execute(command):
    """Own one command process group; timeout stops that owned group before returning."""
    child=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        encoding="utf-8",errors="replace",start_new_session=os.name!="nt",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    timed_out=False
    try:
        stdout,stderr=child.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        timed_out=True
        if os.name=="nt" and child.poll() is None:
            utility=Path(os.environ["SystemRoot"])/"System32/taskkill.exe"
            subprocess.run([str(utility),"/PID",str(child.pid),"/T","/F"],capture_output=True,timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        elif os.name!="nt":
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        if child.poll() is None: child.kill()
        stdout,stderr=child.communicate(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdout.close()
        child.stderr.close()
    return {"command":command,"exit_code":None if timed_out else child.returncode,
            "stdout":stdout,"stderr":stderr,"timeout":timed_out}


def run_all(out_path,evaluation_path):
    records=[]
    out=None
    try:
        out=fresh_attempt(out_path)
        identity=source_identity(ROOT)
        start=datetime.now(timezone.utc).isoformat()
        # Record complete failures instead of replacing/rerunning them automatically.
        for number,args in enumerate(command_plan(out),1):
            begin=time.monotonic()
            command=[sys.executable,*args]
            receipt=execute(command)
            receipt["active_seconds"]=round(time.monotonic()-begin,6)
            records.append(receipt)
            (out/f"command-{number:02d}.json").write_bytes(canonical(receipt)+b"\n")
            if receipt["exit_code"]!=0:
                raise VerificationError(f"Acceptance command {number} failed; raw attempt retained.")
        if identity!=source_identity(ROOT):
            raise VerificationError("Source changed during full acceptance.")
        evaluation=verify_existing(evaluation_path)
        if evaluation["status"]!="passed":
            raise VerificationError("Frozen paired evaluation failed the declared release targets.")
        # Report inner proof counts from their actual raw receipts, not duplicated test invocations.
        evidence={}
        for name in ("m1","m2"):
            paths=list((out/name).glob("attempt-*/acceptance.json"))
            if len(paths)!=1:
                raise VerificationError("Missing unique regression receipt.")
            raw=paths[0].read_bytes()
            evidence[name]={"receipt":paths[0].relative_to(out).as_posix(),"sha256":digest(raw),
                            "result":json.loads(raw)}
            if evidence[name]["result"]["status"]!="passed":
                raise VerificationError("Regression self-report differs from successful exit.")
        summary={"schema_version":1,"status":"passed","milestone":"all","started_at":start,
                 "source":identity,"commands":records,"regression_evidence":evidence,
                 "evaluation_recheck":evaluation,"heldout_producer_runs_in_this_command":0,
                 "model_quality_evaluated":False,"hosted_ci_executed":False}
    except (VerificationError,OSError,ValueError,KeyError,TypeError) as exc:
        summary={"schema_version":1,"status":"failed","milestone":"all","error":str(exc),
                 "commands":records,"heldout_producer_runs_in_this_command":0,"model_quality_evaluated":False}
    except KeyboardInterrupt:
        summary={"schema_version":1,"status":"cancelled","milestone":"all","commands":records,
                 "error":"Interrupted; partial attempt retained."}
    if out is not None:
        (out/"acceptance.json").write_bytes(canonical(summary)+b"\n")
    print(json.dumps({"status":summary["status"],"evidence":str(out/"acceptance.json") if out else None,
                      "commands":len(records),"error":summary.get("error")}))
    return 0 if summary["status"]=="passed" else 130 if summary["status"]=="cancelled" else 1

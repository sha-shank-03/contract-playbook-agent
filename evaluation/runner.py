"""M3 paired producer/freeze/independent-grade pipeline. Requires a named integration lease locally."""
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import sys
import time

from .corpus import VerificationError, canonical, decode, digest, load_case_evidence, load_labels, validate_freeze
from .metrics import aggregate, aggregate_rules, fraction, label_denominators, semantic_metrics
from .verifier import ORACLE_VERSION, assess, load_artifacts, section_index
from contract_playbook.baseline import BASELINE_VERSION
from contract_playbook.service import review, run_case

RUNNER_VERSION = "paired-evaluation-v2"
ROOT = Path(__file__).resolve().parent.parent
LIMITATION = "Same-author authored/template regression corpus; not blind legal validation or live-model evaluation."
PROVIDERS = ("scripted","keyword")
CASE_IDS = tuple(f"H{i:02d}" for i in range(1,31))


def source_identity(root):
    entries = [{"path":p.relative_to(root).as_posix(),"sha256":digest(p.read_bytes())}
               for folder in ("contract_playbook","evaluation","scripts","tests")
               for p in sorted((root/folder).rglob("*.py"))]
    return {"source_sha256":digest(canonical(entries)),"source_entries":entries,
            "source_scope":"Python files under contract_playbook, evaluation, scripts and tests; frozen inputs separately identified.",
            "runner_version":RUNNER_VERSION,"oracle_version":ORACLE_VERSION,"baseline_version":BASELINE_VERSION,
            "scripted_actor_protocol":"m2-v1"}


def output_root(path):
    result=Path(path).resolve()
    work=ROOT/"work"
    if not result.is_relative_to(work.resolve()) or any(p.is_symlink() for p in (Path(path),*Path(path).parents)):
        raise VerificationError("Evaluation output must be unlinked and under work/.")
    if result.exists():
        raise VerificationError("Evaluation needs a fresh output directory; existing runs are never erased.")
    result.mkdir(parents=True)
    return result


def write_json(path,value):
    raw=canonical(value)+b"\n"
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise VerificationError("Generated evaluation artifact already exists.") from exc


def diagnostic(exc,stage):
    """Bounded diagnostic data: remove controls, paths/URLs and recognizable secret values."""
    try: message=str(exc)
    except Exception: message="Error text could not be safely formatted."
    message="".join(c if c.isprintable() else " " for c in message)
    message=re.sub(r"https?://[^\s\"'<>]+", "<url>", message, flags=re.I)
    message=re.sub(r"[A-Za-z]:[/\\][^\s\"'<>]+|/(?:[A-Za-z0-9_.-]+/)[^\s\"'<>]*", "<path>", message)
    message=re.sub(r"(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]+", "<redacted>", message)
    message=re.sub(r"(?i)\b(token|password|secret|api[_ -]?key|authorization)\s*[:=]\s*[^\s,;]+", r"\1=<redacted>", message)
    raw=message.encode("utf-8")
    return {"type":type(exc).__name__[:80],"stage":stage[:80],
            "message":raw[:512].decode("utf-8",errors="ignore"),"truncated":len(raw)>512}


def attempt_plan():
    attempts=[]
    for repetition in range(1,4):
        for provider in PROVIDERS:
            for key in CASE_IDS:
                attempts.append({"attempt_id":f"attempt-{len(attempts)+1:04d}","case_id":key,
                                 "provider":provider,"repetition":repetition,
                                 "run":f"runs/repeat-{repetition}/{provider}/{key}"})
    return attempts


def make_plan(identity,freeze,started):
    plan={"schema_version":1,"runner_version":RUNNER_VERSION,"created_at":started,
          "source":identity,"freeze":freeze,"providers":list(PROVIDERS),"repetitions":3,
          "primary_cases_per_provider":30,"primary_rules_per_provider":90,"primary_atoms_per_provider":210,
          "planned_attempts":180,"attempts":attempt_plan()}
    return {**plan,"plan_sha256":digest(canonical(plan))}


def validate_plan(plan,identity,freeze):
    expected=make_plan(identity,freeze,plan["created_at"])
    if plan!=expected:
        raise VerificationError("Execution plan identity, full attempt set or digest changed.")


def attempt_path(out,entry,phase):
    return out/"attempts"/(entry["attempt_id"]+f"-{phase}.json")


def accounting(out,plan,*,complete=False):
    """Derive attempted/unattempted state from durable receipts, including interrupted work."""
    counts={"planned":180,"attempted":0,"completed":0,"produced":0,"producer_errors":0,
            "interrupted":0,"failed":0,"unfinished":0,"unattempted":0}
    states=[]
    records=[]
    expected_files=set()
    for entry in plan["attempts"]:
        start_path=attempt_path(out,entry,"started")
        result_path=attempt_path(out,entry,"result")
        expected_files.update((start_path.name,result_path.name))
        state="unattempted"
        if start_path.exists():
            if start_path.is_symlink(): raise VerificationError("Linked attempt receipt.")
            start=decode(start_path.read_bytes(),16*1024)
            if any(start.get(k)!=v for k,v in entry.items()) or start.get("plan_sha256")!=plan["plan_sha256"] or start.get("state")!="started":
                raise VerificationError("Attempt start identity differs from immutable plan.")
            counts["attempted"]+=1
            state="unfinished"
        if result_path.exists():
            if state=="unattempted" or result_path.is_symlink():
                raise VerificationError("Unstarted/linked attempt result.")
            record=decode(result_path.read_bytes(),16*1024)
            if any(record.get(k)!=v for k,v in entry.items()) or record.get("plan_sha256")!=plan["plan_sha256"] or record.get("state") not in ("produced","producer_error","interrupted","failed"):
                raise VerificationError("Attempt result identity/state differs from immutable plan.")
            state=record["state"]
            records.append(record)
            if state in ("produced","producer_error"): counts["completed"]+=1
        counter="producer_errors" if state=="producer_error" else state
        counts[counter]+=1
        states.append({**entry,"state":state})
    actual_files={p.name for p in (out/"attempts").iterdir()} if (out/"attempts").exists() else set()
    if actual_files-expected_files:
        raise VerificationError("Unplanned attempt receipt.")
    if complete and (counts["completed"]!=180 or counts["attempted"]!=180 or len(actual_files)!=360):
        raise VerificationError("Incomplete planned execution cannot be graded as complete.")
    return {"counts":counts,"attempts":states},records


def append_exposure(value):
    with (ROOT/"work/evaluation-exposures.jsonl").open("ab") as stream:
        stream.write(canonical(value)+b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def persist_partial(out,plan,exc,stage):
    states,_=accounting(out,plan)
    value={"schema_version":2,"runner_version":RUNNER_VERSION,
           "status":"interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",
           "release_passed":False,"quality_metrics":None,"gold_grading_completed":False,
           "plan_sha256":plan["plan_sha256"],"source":plan["source"],"freeze":plan["freeze"],
           "primary_cases_per_provider":30,"primary_rules_per_provider":90,"primary_atoms_per_provider":210,
           "planned_producer_runs":180,"accounting":states,"diagnostic":diagnostic(exc,stage),
           "finished_at":datetime.now(timezone.utc).isoformat()}
    write_json(out/"partial.json",value)
    append_exposure({"event":"incomplete","evaluation":out.relative_to(ROOT).as_posix(),
                     "status":value["status"],"counts":states["counts"],"diagnostic":value["diagnostic"],
                     "plan_sha256":plan["plan_sha256"]})
    return value


def manifest_for_runs(out,records):
    paths={out/"execution-plan.json",*(out/"attempts").iterdir()}
    for record in records:
        directory=out/record["run"]
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise VerificationError("Linked producer output.")
            if path.is_file(): paths.add(path)
    entries=[]
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file(): raise VerificationError("Producer evidence is not a regular file.")
        entries.append({"path":path.relative_to(out).as_posix(),"sha256":digest(path.read_bytes()),"bytes":path.stat().st_size})
    return {"entries":entries,"sha256":digest(canonical(entries))}


def validate_producer_manifest(out,manifest):
    if digest(canonical(manifest["entries"]))!=manifest["sha256"]:
        raise VerificationError("Producer manifest digest changed.")
    declared=set()
    for item in manifest["entries"]:
        path=(out/item["path"]).resolve()
        if not path.is_relative_to(out.resolve()) or path.is_symlink() or not path.is_file():
            raise VerificationError("Producer artifact escaped/missing.")
        if digest(path.read_bytes())!=item["sha256"] or path.stat().st_size!=item["bytes"]:
            raise VerificationError("Frozen producer artifact changed.")
        declared.add(item["path"])
    actual={p.relative_to(out).as_posix() for folder in ("runs","attempts") for p in (out/folder).rglob("*") if p.is_file()}
    actual.add("execution-plan.json")
    if actual!=declared:
        raise VerificationError("Unlisted producer file.")
    return len(declared)


def failure_report(case,provider,error):
    indexes={key:section_index(raw.decode(),key) for key,raw in case.sources.items()}
    empty={"findings":[],"patches":[],"domain_status":"OPERATIONAL_FAILURE"}
    metrics=semantic_metrics(case,empty,indexes)
    return {**metrics,"case_id":case.case_id,"family":case.labels["family"],"provider_kind":provider,
            "oracle_version":ORACLE_VERSION,"integrity_error":error,"operational_failures":1,
            "integrity_cases":fraction(0,1),"protected_documents":fraction(0,len(case.sources)),
            "exact_preview_documents":fraction(0,len(case.sources)),
            "exact_reviewed_documents":fraction(0,len(case.sources) if case.labels["domain_status"]=="PENDING_REVIEW" else 0),
            "protected_reviewed_documents":fraction(0,len(case.sources) if case.labels["domain_status"]=="PENDING_REVIEW" else 0),
            "exact_cases":fraction(0,1),"unrelated_violating_bytes":0,
            "normalized_domain_sha256":digest(canonical({"operational_failure":True})),
            "decision_calls":None,"tool_calls":None,"elapsed_seconds":None}


def release_gates(metrics,repeatability,baseline_integrity,all_run_integrity=False,all_run_operational=False):
    def perfect(name):
        value=metrics[name]
        return value["denominator"]>0 and value["numerator"]==value["denominator"]
    return {"at_least_27_of_30_exact_cases":metrics["exact_cases"]["denominator"]==30 and metrics["exact_cases"]["numerator"]>=27,
        "positive_atom_precision_at_least_090":(metrics["deviation_missing_precision"]["ratio"] or 0)>=0.90,
        "positive_atom_recall_at_least_090":(metrics["deviation_missing_recall"]["ratio"] or 0)>=0.90,
        "all_mandatory_handoffs":perfect("mandatory_handoff_recall"),
        "all_literal_citations":perfect("citation_fidelity"),"all_policy_citations":perfect("policy_citation_fidelity"),
        "all_protected_documents":perfect("protected_documents") and perfect("protected_reviewed_documents") and metrics["unrelated_violating_bytes"]==0,
        "all_actor_integrity":perfect("integrity_cases") and metrics["operational_failures"]==0,
        "baseline_integrity_preserved":baseline_integrity,
        "all_planned_run_integrity":all_run_integrity,
        "all_planned_run_operational_success":all_run_operational,
        "fresh_repeatability":repeatability["denominator"]==120 and repeatability["numerator"]==120}


def validate_record_set(records,repetitions):
    if repetitions!=3:
        raise VerificationError("Expected exactly three complete repetitions.")
    expected={(i,provider,key) for i in range(1,4) for provider in PROVIDERS for key in CASE_IDS}
    actual=[]
    for record in records:
        if type(record.get("repetition")) is not int or not isinstance(record.get("provider"),str) or not isinstance(record.get("case_id"),str):
            raise VerificationError("Malformed planned case-run identity.")
        actual.append((record["repetition"],record["provider"],record["case_id"]))
    if len(actual)!=180 or len(set(actual))!=180 or set(actual)!=expected:
        raise VerificationError("Missing, duplicate or unplanned case-run; fixed denominators cannot shrink.")


def run_safety(records):
    def integrity(record):
        value=record["assessment"].get("integrity_cases",{})
        return (type(value.get("numerator")) is int and type(value.get("denominator")) is int and
                value["numerator"]==value["denominator"]==1 and record["assessment"].get("integrity_error") is None)
    def operational(record):
        count=record["assessment"].get("operational_failures")
        return (type(count) is int and count==0 and record.get("operational_error") is None
                and record.get("state","produced")=="produced")
    return {"planned_case_runs":180,"integrity_cases":fraction(sum(integrity(r) for r in records),180),
            "operational_successes":fraction(sum(operational(r) for r in records),180),
            "failed_runs":[{"case_id":r["case_id"],"provider":r["provider"],"repetition":r["repetition"],
                            "integrity_safe":integrity(r),"operational_safe":operational(r)}
                           for r in records if not integrity(r) or not operational(r)]}


def summarize(records,repetitions):
    validate_record_set(records,repetitions)
    primary=[r for r in records if r["repetition"]==1]
    aggregates={provider:aggregate([r["assessment"] for r in primary if r["provider"]==provider])
                for provider in ("scripted","keyword")}
    paired=[]
    for case_id in sorted({r["case_id"] for r in primary}):
        values={r["provider"]:r["assessment"] for r in primary if r["case_id"]==case_id}
        paired.append({"case_id":case_id,"family":values["scripted"]["family"],
                       "scripted_exact":values["scripted"]["exact_cases"]["numerator"]==1,
                       "keyword_exact":values["keyword"]["exact_cases"]["numerator"]==1,
                       "scripted_errors":values["scripted"]["rule_errors"],
                       "keyword_errors":values["keyword"]["rule_errors"]})
    repeat_correct=0
    for record in records:
        if record["repetition"]==1:
            continue
        first=next(r for r in primary if r["case_id"]==record["case_id"] and r["provider"]==record["provider"])
        repeat_correct+=record["assessment"]["normalized_domain_sha256"]==first["assessment"]["normalized_domain_sha256"]
    repeatability=fraction(repeat_correct,len(primary)*(repetitions-1))
    safety=run_safety(records)
    baseline_integrity=not any(r["provider"]=="keyword" for r in safety["failed_runs"])
    gates=release_gates(aggregates["scripted"],repeatability,baseline_integrity,
                        safety["integrity_cases"]["numerator"]==180,
                        safety["operational_successes"]["numerator"]==180)
    by_family={}
    for family in sorted({r["assessment"]["family"] for r in primary}):
        by_family[family]={provider:aggregate([r["assessment"] for r in primary
                       if r["provider"]==provider and r["assessment"]["family"]==family])
                         for provider in ("scripted","keyword")}
    by_rule={provider:aggregate_rules([r["assessment"] for r in primary if r["provider"]==provider])
             for provider in ("scripted","keyword")}
    return {"primary_metrics":aggregates,"paired_cases":paired,"by_family":by_family,"by_rule":by_rule,
            "all_run_safety":safety,
            "repeatability":repeatability,"release_gates":gates,"release_passed":all(gates.values()),
            "paired_counts":{"scripted_only":sum(p["scripted_exact"] and not p["keyword_exact"] for p in paired),
                             "keyword_only":sum(p["keyword_exact"] and not p["scripted_exact"] for p in paired),
                             "both":sum(p["scripted_exact"] and p["keyword_exact"] for p in paired),
                             "neither":sum(not p["scripted_exact"] and not p["keyword_exact"] for p in paired)}}


def run_evaluation(out_path,repetitions=3):
    if repetitions!=3:
        raise VerificationError("Release evaluation requires primary plus two fresh repetitions (3 total).")
    freeze=validate_freeze(ROOT)
    identity=source_identity(ROOT)
    out=output_root(out_path)
    started=datetime.now(timezone.utc).isoformat()
    plan=make_plan(identity,freeze,started)
    write_json(out/"execution-plan.json",plan)
    active=None
    begin=None
    stage="attempt-directory"
    try:
        (out/"attempts").mkdir()
        stage="exposure"
        append_exposure({"event":"started","evaluation":out.relative_to(ROOT).as_posix(),
                         "started_at":started,"freeze":freeze,"source":identity,"repetitions":3,
                         "planned_attempts":180,"plan_sha256":plan["plan_sha256"],"limitation":LIMITATION})
        stage="input-inventory"
        case_dirs={p.name:p for p in (ROOT/"fixtures/heldout").iterdir() if p.is_dir()}
        if set(case_dirs)!=set(CASE_IDS):
            raise VerificationError("Expected the complete 30 frozen producer input directories.")
        # Full plan and fsynced start/result receipts precede any gold decoding.
        for entry in plan["attempts"]:
            active={**entry,"plan_sha256":plan["plan_sha256"],"approved":False,
                    "operational_error":None,"diagnostic":None,
                    "started_at":datetime.now(timezone.utc).isoformat()}
            stage="attempt-start"
            write_json(attempt_path(out,entry,"started"),{**entry,"plan_sha256":plan["plan_sha256"],
                       "state":"started","started_at":active["started_at"]})
            begin=time.monotonic()
            stage="producer"
            try:
                packet=run_case(case_dirs[entry["case_id"]],ROOT/"fixtures/playbooks/buyer-services-v2.json",
                                out/entry["run"],provider_kind=entry["provider"])
                if packet["domain_status"]=="PENDING_REVIEW":
                    stage="review"
                    review(out/entry["run"],"approve",packet["proposal_sha256"],"fictional-evaluation-reviewer")
                    active["approved"]=True
                active["state"]="produced"
            except Exception as exc:
                active.update({"state":"producer_error","diagnostic":diagnostic(exc,stage)})
                active["operational_error"]=active["diagnostic"]["type"]+": "+active["diagnostic"]["message"]
            active["producer_seconds"]=round(time.monotonic()-begin,6)
            active["finished_at"]=datetime.now(timezone.utc).isoformat()
            stage="attempt-result"
            write_json(attempt_path(out,entry,"result"),active)
            active=None
            begin=None
        stage="post-production-freeze"
        validate_freeze(ROOT)
        execution,records=accounting(out,plan,complete=True)
        stage="producer-manifest"
        manifest=manifest_for_runs(out,records)
        write_json(out/"producer-manifest.json",manifest)
        validate_producer_manifest(out,manifest)
        stage="gold-grading"
        labels=load_labels(ROOT)
        if set(labels)!=set(CASE_IDS):
            raise VerificationError("Producer case set differs from reviewed frozen labels.")
        for record in records:
            case=load_case_evidence(ROOT,record["case_id"],labels[record["case_id"]])
            if record["operational_error"]:
                assessed=failure_report(case,record["provider"],record["operational_error"])
            else:
                try:
                    assessed=assess(case,load_artifacts(out/record["run"]),record["provider"],approved=record["approved"])
                except (OSError,VerificationError,ValueError,KeyError,TypeError) as exc:
                    error=diagnostic(exc,"independent-assessment")
                    assessed=failure_report(case,record["provider"],error["type"]+": "+error["message"])
            record["assessment"]=assessed
        summary=summarize(records,3)
        report={"schema_version":2,"status":"passed" if summary["release_passed"] else "failed",
                "evaluation_version":RUNNER_VERSION,"limitation":LIMITATION,"source":identity,"freeze":freeze,
                "started_at":started,"finished_at":datetime.now(timezone.utc).isoformat(),
                "repetitions":3,"providers":list(PROVIDERS),"model_calls":0,"model_quality_evaluated":False,
                "primary_cases_per_provider":30,"primary_rules_per_provider":90,"primary_atoms_per_provider":210,
                "label_denominators_per_provider":label_denominators(labels),
                "producer_runs":180,"normalized_repeat_comparisons":120,"producer_manifest_sha256":manifest["sha256"],
                "plan_sha256":plan["plan_sha256"],"execution_accounting":execution,**summary,"records":records}
        stage="final-report"
        write_json(out/"evaluation.json",report)
        append_exposure({"event":"completed","evaluation":out.relative_to(ROOT).as_posix(),
                         "finished_at":report["finished_at"],"status":report["status"],"producer_runs":180,
                         "plan_sha256":plan["plan_sha256"],
                         "report_sha256":digest((out/"evaluation.json").read_bytes())})
        return report
    except BaseException as exc:
        # Never discard a completed receipt or replace an earlier generated artifact.
        try:
            if active is not None and not attempt_path(out,active,"result").exists():
                error=diagnostic(exc,stage)
                active.update({"state":"interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",
                               "diagnostic":error,"operational_error":error["type"]+": "+error["message"],
                               "producer_seconds":round(time.monotonic()-begin,6) if begin is not None else None,
                               "finished_at":datetime.now(timezone.utc).isoformat()})
                if attempt_path(out,active,"started").exists():
                    write_json(attempt_path(out,active,"result"),active)
            persist_partial(out,plan,exc,stage)
        except Exception as evidence_error:
            # A full/read-only disk can defeat persistence; retain old files and never mask the original failure.
            print(canonical({"status":"failed","partial_recording_error":diagnostic(evidence_error,"partial-evidence"),
                             "original_diagnostic":diagnostic(exc,stage)}).decode(),file=sys.stderr)
        raise


def verify_existing(out_path):
    """Recheck durable plan, all frozen outputs and grades; execute no producer."""
    original=Path(out_path)
    out=original.resolve()
    if not out.is_relative_to((ROOT/"work").resolve()) or any(p.is_symlink() for p in (original,*original.parents)):
        raise VerificationError("Existing evaluation must be unlinked under work/.")
    if (out/"partial.json").exists():
        raise VerificationError("Partial execution cannot be accepted as a complete evaluation.")
    report=decode((out/"evaluation.json").read_bytes(),2*1024*1024)
    identity=source_identity(ROOT)
    freeze=validate_freeze(ROOT)
    if report["source"]!=identity or report["freeze"]!=freeze:
        raise VerificationError("Evaluation source/freeze identity changed.")
    plan=decode((out/"execution-plan.json").read_bytes(),256*1024)
    validate_plan(plan,identity,freeze)
    execution,durable_records=accounting(out,plan,complete=True)
    if report["plan_sha256"]!=plan["plan_sha256"] or report["execution_accounting"]!=execution:
        raise VerificationError("Reported planned/attempted accounting differs from durable receipts.")
    validate_record_set(report["records"],3)
    for reported,durable in zip(report["records"],durable_records):
        if {k:v for k,v in reported.items() if k!="assessment"}!=durable:
            raise VerificationError("Reported producer result differs from its immutable attempt receipt.")
    manifest=decode((out/"producer-manifest.json").read_bytes(),4*1024*1024)
    validate_producer_manifest(out,manifest)
    if report["producer_manifest_sha256"]!=manifest["sha256"]:
        raise VerificationError("Missing frozen producer evidence.")
    labels=load_labels(ROOT)
    if set(labels)!=set(CASE_IDS) or report["label_denominators_per_provider"]!=label_denominators(labels) or any(report.get(k)!=v for k,v in
            {"schema_version":2,"evaluation_version":RUNNER_VERSION,"repetitions":3,"providers":list(PROVIDERS),
             "primary_cases_per_provider":30,"primary_rules_per_provider":90,"primary_atoms_per_provider":210,
             "producer_runs":180,"normalized_repeat_comparisons":120,"model_calls":0,"model_quality_evaluated":False}.items()):
        raise VerificationError("Declared evaluation schema/denominators/version changed.")
    fresh=[]
    for record in report["records"]:
        case=load_case_evidence(ROOT,record["case_id"],labels[record["case_id"]])
        if record["operational_error"]:
            assessed=failure_report(case,record["provider"],record["operational_error"])
        else:
            try:
                assessed=assess(case,load_artifacts(out/record["run"]),record["provider"],approved=record["approved"])
            except (OSError,VerificationError,ValueError,KeyError,TypeError) as exc:
                error=diagnostic(exc,"independent-assessment")
                assessed=failure_report(case,record["provider"],error["type"]+": "+error["message"])
        if assessed!=record["assessment"]:
            raise VerificationError("Reported independent assessment differs from raw artifacts.")
        fresh.append({**record,"assessment":assessed})
    summary=summarize(fresh,3)
    if any(report[key]!=value for key,value in summary.items()) or report["status"]!=("passed" if summary["release_passed"] else "failed"):
        raise VerificationError("Reported aggregate/target/repeatability differs.")
    return {"status":report["status"],"producer_runs_rechecked":180,
            "producer_artifacts_rechecked":len(manifest["entries"]),"plan_sha256":plan["plan_sha256"],
            "execution_counts":execution["counts"],"report_sha256":digest((out/"evaluation.json").read_bytes()),**summary}

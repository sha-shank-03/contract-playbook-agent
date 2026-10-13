"""LEASE REQUIRED: two exposed scripted pairs; persist raw outcomes, then independently score."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contract_playbook.bundle import load_bundle
from contract_playbook.playbook import load_playbook
from contract_playbook.comparison import PairLimits, ConservativeScriptedDouble, run_actor
from evaluation.corpus import validate_freeze
from evaluation.upgrade.u2b_inputs import validate_catalog, referenced_paths
from evaluation.upgrade.u2b_oracle import score_raw, paired_report, ScoreInvalid, encode, digest

CANDIDATE="UPGRADE_MANIFEST_U2B_1_0.json"


def write(path,value):
    if path.exists() or path.is_symlink():raise ValueError("Fresh artifact required")
    path.write_bytes(encode(value)+b"\n")


def source_check():
    manifest=json.loads((ROOT/CANDIDATE).read_bytes())
    for entry in manifest["source_entries"]:
        path=ROOT/entry["path"]
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes())!=entry["sha256"]:
            raise ValueError("Candidate source changed")
    return {"manifest_sha256":digest((ROOT/CANDIDATE).read_bytes()),
            "source_entry_digest":manifest["source_entry_digest"],
            "source_entries":len(manifest["source_entries"]),"freeze":validate_freeze(ROOT)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    out=Path(args.out)
    if not out.is_absolute():out=ROOT/out
    if any(p.is_symlink() for p in (out,*out.parents)):raise SystemExit("Linked output refused")
    out=out.resolve()
    if not out.is_relative_to(ROOT/"work") or out==ROOT/"work" or out.exists():
        raise SystemExit("A fresh child of repository work/ is required")
    started=time.monotonic()
    preflight=source_check()
    catalog_raw=(ROOT/"evaluation/upgrade/U2B_INPUTS.json").read_bytes()
    catalog=json.loads(catalog_raw)
    selected=[next(c for c in catalog["cases"] if c["task_id"]==key) for key in ("D15","C11")]
    limits=PairLimits(seconds=20)
    policy=load_playbook(ROOT/"fixtures/playbooks/buyer-services-v2.json")
    out.mkdir(parents=True)
    db=None
    raw_runs=[];rows=[];controls=[]
    snapshots={}
    try:
        write(out/"preflight.json",preflight)
        db=sqlite3.connect(out/"raw-outcomes.sqlite3")
        db.execute("CREATE TABLE raw_runs(task TEXT, strategy TEXT, body TEXT, PRIMARY KEY(task,strategy))")
        db.execute("CREATE TABLE freeze(body TEXT)")
        for case in selected:
            bundle=load_bundle(ROOT/case["case_path"])
            paths=[bundle.manifest_path,policy.path,*[d.path for d in bundle.documents]]
            for path in paths:snapshots[path]=digest(path.read_bytes())
            if {d.document_id:d.version for d in bundle.documents}!=case["document_sha256"]:
                raise ValueError("Fixture source version mismatch")
            for strategy in ("adaptive","fixed-full-context"):
                # Double receives the registry payload only: no case ID, scorer label or file path.
                result=run_actor(bundle,policy,limits,strategy,ConservativeScriptedDouble())
                if result["failure"]:raise ValueError("Unexpected local actor failure: "+result["failure"])
                if result["model"]!=limits.model or result["limits"]!=limits.public():
                    raise ValueError("Model or budget mismatch")
                record={"task_id":case["task_id"],"strategy":strategy,"result":result}
                raw_runs.append(record)
                db.execute("INSERT INTO raw_runs VALUES(?,?,?)",(case["task_id"],strategy,encode(result).decode()))
                db.commit()
        write(out/"raw-outcomes.json",raw_runs)
        frozen={"schema_version":1,"mode":"scripted-local-double","unique_tasks":2,"actor_runs":4,
                "raw_outcomes_sha256":digest((out/"raw-outcomes.json").read_bytes()),
                "claim":"Freeze before grading; all worker labels already exposed, never a blind evaluation",
                "actor_prompt_labels_access":False,"main_unseen_accessed":False}
        db.execute("INSERT INTO freeze VALUES(?)",(encode(frozen).decode(),));db.commit()
        write(out/"RAW_OUTCOME_FREEZE.json",frozen)
        db.close();db=None
        uri="file:"+quote(str(out/"raw-outcomes.sqlite3").replace("\\","/"),safe="/:")+"?mode=ro"
        with sqlite3.connect(uri,uri=True) as reader:
            persisted={(task,strategy):json.loads(body) for task,strategy,body in reader.execute("SELECT task,strategy,body FROM raw_runs")}
            persisted_freeze=json.loads(reader.execute("SELECT body FROM freeze").fetchone()[0])
        if len(persisted)!=4 or persisted_freeze!=frozen or any(
                persisted[record["task_id"],record["strategy"]]!=record["result"] for record in raw_runs):
            raise ValueError("Raw file/database mismatch")
        # Scorer-only exposed labels are loaded after raw outcomes are saved and frozen.
        files={p:(ROOT/p).read_bytes() for p in referenced_paths(catalog)}
        input_report=validate_catalog(catalog_raw,files)
        labels={}
        for split,value in catalog["scorer_only_labels"].items():
            for label in json.loads(files[value["path"]])["labels"]:labels[label["task_id"]]=label
        inputs={}
        for case in selected:
            bundle=load_bundle(ROOT/case["case_path"])
            sources={d.document_id:d.raw for d in bundle.documents}
            inputs[case["task_id"]]={"sources":sources,"policy_raw":policy.raw,
                                    "manifest_raw":bundle.manifest_raw,"label":labels[case["task_id"]]}
            pair={"task_id":case["task_id"],"family":case["family"],"mode":"scripted-local-double"}
            for strategy,target in (("adaptive","adaptive"),("fixed-full-context","fixed")):
                result=persisted[case["task_id"],strategy]
                if result["packet"]["config_sha256"]!=digest(encode(limits.public())):
                    raise ValueError("Raw proposal configuration mismatch")
                score=score_raw(result["packet"],result["state"],result["registry_state"],**inputs[case["task_id"]])
                pair[target]={"failed":False,"score":score,"model":result["model"],"limits":result["limits"],
                              "context_sha256":result["context_sha256"],"elapsed_seconds":result["elapsed_seconds"],"failure":None}
            rows.append(pair)
        def denied(name,call):
            try:call()
            except ScoreInvalid:controls.append({"name":name,"status":"refused"});return
            raise ValueError("Expected independent refusal missing: "+name)
        original=persisted["D15","adaptive"]
        fixture=inputs["D15"]
        # Re-sign and synchronize an invented quote so the source check, not digest alone, must reject it.
        altered=deepcopy(original)
        f=altered["packet"]["findings"][1];f["evidence"][0]["quote"]="Invented amendment priority."
        altered["registry_state"]["findings"][f["rule_id"]]=deepcopy(f)
        for event in altered["registry_state"]["history"]:
            if event["decision"]["tool"]=="propose_finding" and event["decision"]["arguments"]["rule_id"]==f["rule_id"]:
                event["decision"]["arguments"]=deepcopy(f)
        altered["packet"]["proposal_sha256"]=digest(encode({k:v for k,v in altered["packet"].items() if k!="proposal_sha256"}))
        altered["state"]["proposal_sha256"]=altered["packet"]["proposal_sha256"]
        denied("re_signed_literal_quote",lambda:score_raw(altered["packet"],altered["state"],altered["registry_state"],**fixture))
        denied("unapproved_original_copy",lambda:score_raw(original["packet"],original["state"],original["registry_state"],
                                                          **fixture,reviewed=fixture["sources"]))
        bad_pair=deepcopy(rows);bad_pair[0]["fixed"]["limits"]["tools"]=1
        denied("baseline_source_or_budget_starvation",lambda:paired_report(bad_pair))
        denied("unknown_cost_zero",lambda:score_raw(original["packet"],original["state"],original["registry_state"],
                                                   **fixture,costs={"actual_cost_usd":0}))
        altered_state=deepcopy(original["state"]);altered_state["current_state"]="DRAFT_EXPORTED"
        denied("raw_state_without_approval",lambda:score_raw(original["packet"],altered_state,original["registry_state"],**fixture))
        changed=deepcopy(fixture);changed["sources"]["agreement"]+=b"changed"
        denied("source_identity_drift",lambda:score_raw(original["packet"],original["state"],original["registry_state"],**changed))
        if any(digest(path.read_bytes())!=sha for path,sha in snapshots.items()):raise ValueError("Original source changed")
        postflight=source_check()
        if preflight!=postflight:raise ValueError("Candidate/freeze drift")
        if time.monotonic()-started>=90:raise ValueError("Native completion bound exceeded")
        report=paired_report(rows)
        write(out/"input-inventory.json",input_report)
        write(out/"paired-raw-scores.json",rows)
        write(out/"negative-controls.json",controls)
        write(out/"postflight.json",postflight)
        summary={"status":"passed_local_scripted_contract","unique_tasks":2,"actor_runs":4,"negative_controls":len(controls),
                 "report":report,"elapsed_seconds":time.monotonic()-started,"limits":limits.public(),
                 "sqlite_scope":"Harness persistence of finished in-memory actor results; no production durable evaluation dispatcher",
                 "originals_unchanged":True,"live_model_calls":0,"remote_account_calls":0,"credential_access":False,
                 "actual_human_approval":False,"genuine_docs_sandbox":False,
                 "durable_docs_simulation":"U2-A acceptance harness only; remote production dispatcher remains unimplemented",
                 "peak_ram_bytes":None,"allocated_disk_bytes":None,"self_accepted":False}
        write(out/"summary.json",summary)
        inventory=[{"path":p.relative_to(out).as_posix(),"bytes":p.stat().st_size,"sha256":digest(p.read_bytes())}
                   for p in sorted(out.rglob("*")) if p.is_file()]
        write(out/"artifact-inventory.json",inventory)
        print(json.dumps({"status":summary["status"],"unique_tasks":2,"actor_runs":4,
                          "negative_controls":len(controls),"semantic_quality_evidence":False,
                          "actual_cost_usd":None,"elapsed_seconds":summary["elapsed_seconds"]}))
        return 0
    except Exception as exc:
        if db is not None:db.close()
        if not (out/"summary.json").exists():
            write(out/"summary.json",{"status":"failed_preserved","exception_class":type(exc).__name__,
                "raw_runs_completed":len(raw_runs),"controls":controls,"elapsed_seconds":time.monotonic()-started,
                "live_model_calls":0,"remote_account_calls":0,"self_accepted":False})
        print(json.dumps({"status":"failed_preserved","exception_class":type(exc).__name__}))
        return 1


if __name__=="__main__":raise SystemExit(main())

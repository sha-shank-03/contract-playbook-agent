"""LEASE REQUIRED: unchanged two-pair actor protocol with append-only failure accounting."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contract_playbook.bundle import load_bundle
from contract_playbook.playbook import load_playbook
from contract_playbook.comparison import PairLimits,ConservativeScriptedDouble,run_actor,full_context
from evaluation.corpus import validate_freeze
from evaluation.upgrade.u2b_inputs import validate_catalog,referenced_paths
from evaluation.upgrade.u2b_oracle import score_raw,paired_report as legacy_paired_report,ScoreInvalid
from evaluation.upgrade.u2b_accounting import (Journal,create_plan,execute_once,report,decode_records,
    AccountingInvalid,encode,digest,MAX_RECORDS,MAX_RECORD_BYTES)

CANDIDATE="UPGRADE_MANIFEST_U2B_1_1.json"


class StopBatch(Exception):
    pass


def write_fresh(path,value):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError("Linked target")
    with path.open("xb") as stream:
        stream.write(encode(value)+b"\n");stream.flush();os.fsync(stream.fileno())


def source_check():
    raw=(ROOT/CANDIDATE).read_bytes();manifest=json.loads(raw)
    for entry in manifest["source_entries"]:
        path=ROOT/entry["path"]
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes())!=entry["sha256"]:
            raise ValueError("Candidate source changed")
    return {"manifest_sha256":digest(raw),"source_entry_digest":manifest["source_entry_digest"],
            "source_entries":len(manifest["source_entries"]),"freeze":validate_freeze(ROOT)}


def read_journal(plan,directory):
    paths=sorted(directory.glob("*.json"))
    if not 1<=len(paths)<=MAX_RECORDS:raise AccountingInvalid("ACCOUNTING_PREFIX_INVALID")
    records=[]
    for seq,path in enumerate(paths):
        if path.name!=f"{seq:06d}.json" or path.is_symlink() or path.stat().st_size>MAX_RECORD_BYTES:
            raise AccountingInvalid("ACCOUNTING_PREFIX_INVALID")
        records.append(json.loads(path.read_bytes()))
    decode_records(plan,records)
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",required=True)
    args=parser.parse_args()
    out=Path(args.out);out=out if out.is_absolute() else ROOT/out
    if any(p.is_symlink() for p in (out,*out.parents)):raise SystemExit("Linked output")
    out=out.resolve()
    if not out.is_relative_to(ROOT/"work") or out==ROOT/"work" or out.exists():
        raise SystemExit("Fresh child of repository work/ required")
    started=time.monotonic();preflight=source_check()
    catalog_raw=(ROOT/"evaluation/upgrade/U2B_INPUTS.json").read_bytes();catalog=json.loads(catalog_raw)
    selected=[next(c for c in catalog["cases"] if c["task_id"]==key) for key in ("D15","C11")]
    limits=PairLimits(seconds=20)
    policy=load_playbook(ROOT/"fixtures/playbooks/buyer-services-v2.json")
    prepared={};tasks=[];snapshots={}
    for case in selected:
        bundle=load_bundle(ROOT/case["case_path"]);prepared[case["task_id"]]=bundle
        if {d.document_id:d.version for d in bundle.documents}!=case["document_sha256"]:raise ValueError("Fixture version")
        for path in (bundle.manifest_path,policy.path,*[d.path for d in bundle.documents]):snapshots[path]=digest(path.read_bytes())
        tasks.append({"task_id":case["task_id"],"family":case["family"],
            "source_sha256":{d.document_id:d.version for d in bundle.documents},
            "manifest_sha256":digest(bundle.manifest_raw),"policy_sha256":policy.version,
            "context_sha256":digest(encode(full_context(bundle,policy)))})
    plan=create_plan(tasks,limits.public(),preflight["manifest_sha256"],digest(catalog_raw))
    out.mkdir(parents=True);directory=out/"accounting-journal";directory.mkdir()
    db=None;journal=None;controls=[];rows=[];failure=None;raw_archive_written=False
    def persist(record):
        # A durable immutable file is authoritative even if SQL acknowledgement is lost.
        write_fresh(directory/f"{record['sequence']:06d}.json",record)
        if db is not None:
            states=decode_records(plan,read_journal(plan,directory))
            db.execute("INSERT INTO accounting_records VALUES(?,?)",(record["sequence"],encode(record).decode()))
            for slot_id,state in states.items():
                raw=state["raw_result"]
                db.execute("UPDATE intended_slots SET status=?,body=? WHERE slot_id=?",
                           (state["status"],encode(state).decode(),slot_id))
                if record["kind"]=="RETURNED" and slot_id==record["slot_id"]:
                    db.execute("INSERT INTO raw_runs VALUES(?,?,?)",
                               (state["slot"]["task_id"],state["slot"]["strategy"],encode(raw).decode()))
            db.commit()
    try:
        write_fresh(out/"preflight.json",preflight)
        write_fresh(out/"INTENDED_PLAN.json",plan)
        journal=Journal.create(plan,persist)  # Four slots durable before SQL setup or actor invocation.
        db=sqlite3.connect(out/"raw-outcomes.sqlite3")
        db.execute("CREATE TABLE intended_slots(slot_id TEXT PRIMARY KEY,status TEXT,body TEXT)")
        db.execute("CREATE TABLE accounting_records(seq INTEGER PRIMARY KEY,body TEXT)")
        db.execute("CREATE TABLE raw_runs(task TEXT,strategy TEXT,body TEXT,PRIMARY KEY(task,strategy))")
        db.execute("CREATE TABLE freeze(body TEXT)")
        for slot_id,state in journal.view(close_open_starts=False).items():
            db.execute("INSERT INTO intended_slots VALUES(?,?,?)",(slot_id,state["status"],encode(state).decode()))
        db.execute("INSERT INTO accounting_records VALUES(0,?)",(encode(journal.records[0]).decode(),));db.commit()
        for slot in plan["slots"]:
            bundle=prepared[slot["task_id"]]
            state=execute_once(journal,slot["slot_id"],lambda b=bundle,s=slot:
                               run_actor(b,policy,limits,s["strategy"],ConservativeScriptedDouble()))
            # RETURNED (including raw failure/binding mismatch) has already been durably recorded.
            if state["status"]!="returned_ok_ungraded":raise StopBatch("ACTOR_SLOT_FAILED")
        raw_archive=[{"slot_id":k,"status":s["status"],"raw_result":s["raw_result"]}
                     for k,s in journal.view().items()]
        write_fresh(out/"raw-outcomes.json",raw_archive);raw_archive_written=True
        frozen={"schema_version":1,"mode":"scripted-local-double","plan_sha256":plan["plan_sha256"],
            "intended_unique_tasks":2,"intended_actor_slots":4,"returned_actor_slots":4,
            "raw_outcomes_sha256":digest((out/"raw-outcomes.json").read_bytes()),
            "journal_prefix_sha256":journal.records[-1]["record_sha256"],
            "claim":"All worker labels exposed. Raw outcomes frozen before grading; not blind.",
            "actor_prompt_labels_access":False,"main_unseen_accessed":False}
        write_fresh(out/"RAW_OUTCOME_FREEZE.json",frozen)
        db.execute("INSERT INTO freeze VALUES(?)",(encode(frozen).decode(),));db.commit()
        files={p:(ROOT/p).read_bytes() for p in referenced_paths(catalog)}
        input_report=validate_catalog(catalog_raw,files);labels={}
        for value in catalog["scorer_only_labels"].values():
            labels.update({v["task_id"]:v for v in json.loads(files[value["path"]])["labels"]})
        inputs={}
        for case in selected:
            bundle=prepared[case["task_id"]]
            inputs[case["task_id"]]={"sources":{d.document_id:d.raw for d in bundle.documents},
                "policy_raw":policy.raw,"manifest_raw":bundle.manifest_raw,"label":labels[case["task_id"]]}
            pair={"task_id":case["task_id"],"family":case["family"],"mode":"scripted-local-double"}
            for strategy,target in (("adaptive","adaptive"),("fixed-full-context","fixed")):
                slot_id=case["task_id"]+"/"+strategy;raw=journal.view()[slot_id]["raw_result"]
                try:score=score_raw(raw["packet"],raw["state"],raw["registry_state"],**inputs[case["task_id"]])
                except ScoreInvalid:
                    journal.scored(slot_id);raise StopBatch("SCORER_REJECTED") from None
                journal.scored(slot_id,score)
                pair[target]={"failed":False,"score":score,"model":raw["model"],"limits":raw["limits"],
                    "context_sha256":raw["context_sha256"],"elapsed_seconds":raw["elapsed_seconds"],"failure":None}
            rows.append(pair)
        def denied(name,call):
            try:call()
            except ScoreInvalid:controls.append({"name":name,"status":"refused"});return
            raise StopBatch("NEGATIVE_CONTROL_MISSING")
        original=journal.view()["D15/adaptive"]["raw_result"];fixture=inputs["D15"]
        altered=deepcopy(original);finding=altered["packet"]["findings"][1]
        finding["evidence"][0]["quote"]="Invented amendment priority."
        altered["registry_state"]["findings"][finding["rule_id"]]=deepcopy(finding)
        for event in altered["registry_state"]["history"]:
            if event["decision"]["tool"]=="propose_finding" and event["decision"]["arguments"]["rule_id"]==finding["rule_id"]:
                event["decision"]["arguments"]=deepcopy(finding)
        altered["packet"]["proposal_sha256"]=digest(encode({k:v for k,v in altered["packet"].items() if k!="proposal_sha256"}))
        altered["state"]["proposal_sha256"]=altered["packet"]["proposal_sha256"]
        denied("re_signed_literal_quote",lambda:score_raw(altered["packet"],altered["state"],altered["registry_state"],**fixture))
        denied("unapproved_original_copy",lambda:score_raw(original["packet"],original["state"],original["registry_state"],**fixture,reviewed=fixture["sources"]))
        bad_pair=deepcopy(rows);bad_pair[0]["fixed"]["limits"]["tools"]=1
        denied("baseline_source_or_budget_starvation",lambda:legacy_paired_report(bad_pair))
        denied("unknown_cost_zero",lambda:score_raw(original["packet"],original["state"],original["registry_state"],**fixture,costs={"actual_cost_usd":0}))
        bad_state=deepcopy(original["state"]);bad_state["current_state"]="DRAFT_EXPORTED"
        denied("raw_state_without_approval",lambda:score_raw(original["packet"],bad_state,original["registry_state"],**fixture))
        changed=deepcopy(fixture);changed["sources"]["agreement"]+=b"changed"
        denied("source_identity_drift",lambda:score_raw(original["packet"],original["state"],original["registry_state"],**changed))
        if any(digest(p.read_bytes())!=v for p,v in snapshots.items()):raise StopBatch("ORIGINAL_SOURCE_CHANGED")
        if source_check()!=preflight:raise StopBatch("SOURCE_FREEZE_CHANGED")
        if time.monotonic()-started>=90:raise StopBatch("COMPLETION_BOUND")
        write_fresh(out/"input-inventory.json",input_report)
        write_fresh(out/"paired-raw-scores.json",rows)
        write_fresh(out/"negative-controls.json",controls)
    except BaseException as exc:
        failure=type(exc).__name__  # No exception message, provider body or secret material.
    finally:
        # Reload acknowledged-or-ambiguous disk prefix; never retry a journal write or actor.
        if db is not None:db.close();db=None
        try:
            persisted=read_journal(plan,directory)
            recovered=Journal(plan,persisted,lambda record:write_fresh(directory/f"{record['sequence']:06d}.json",record))
            recovered.close_interrupted()
            accounting=report(recovered)
            if not raw_archive_written:
                write_fresh(out/"raw-outcomes.json",[{"slot_id":k,"status":s["status"],"raw_result":s["raw_result"]}
                                                     for k,s in recovered.view().items()])
            write_fresh(out/"accounting-report.json",accounting)
            if failure is None:
                uri="file:"+quote(str(out/"raw-outcomes.sqlite3").replace("\\","/"),safe="/:")+"?mode=ro"
                with sqlite3.connect(uri,uri=True) as reader:
                    sql_records=[json.loads(body) for _,body in reader.execute("SELECT seq,body FROM accounting_records ORDER BY seq")]
                    sql_slots={k:json.loads(body) for k,body in reader.execute("SELECT slot_id,body FROM intended_slots")}
                    sql_raw={(task,strategy):json.loads(body) for task,strategy,body in reader.execute("SELECT task,strategy,body FROM raw_runs")}
                if sql_records!=recovered.records or sql_slots!=recovered.view(close_open_starts=False) or len(sql_raw)!=4:
                    raise StopBatch("SQL_JOURNAL_MISMATCH")
                if any(sql_raw[s["slot"]["task_id"],s["slot"]["strategy"]]!=s["raw_result"] for s in recovered.view().values()):
                    raise StopBatch("RAW_SQL_MISMATCH")
                write_fresh(out/"read-only-sql-witness.json",{"records":len(sql_records),"slots":len(sql_slots),"raw_results":len(sql_raw),"matched":True})
        except BaseException as exc:
            failure=type(exc).__name__
            accounting=None  # An invalid/missing prefix cannot be invented as zero observed runs.
        summary={"status":"failed_preserved" if failure else "passed_local_accounting_contract",
            "exception_class":failure,"intended_unique_tasks":2,"intended_actor_slots":4,"accounting":accounting,
            "observed_counts_unavailable":accounting is None,"negative_controls":len(controls),
            "elapsed_seconds":time.monotonic()-started,"limits":limits.public(),
            "scope":"Append-only harness accounting and SQL mirror; production durable dispatcher unimplemented",
            "originals_unchanged":all(digest(p.read_bytes())==v for p,v in snapshots.items()),
            "live_model_calls":0,"remote_account_calls":0,"credential_access":False,"actual_human_approval":False,
            "semantic_quality_evidence":False,"actual_cost_usd":None,"estimated_cost_usd":None,
            "peak_ram_bytes":None,"allocated_disk_bytes":None,"self_accepted":False}
        write_fresh(out/"summary.json",summary)
        inventory=[{"path":p.relative_to(out).as_posix(),"bytes":p.stat().st_size,"sha256":digest(p.read_bytes())}
                   for p in sorted(out.rglob("*")) if p.is_file()]
        write_fresh(out/"artifact-inventory.json",inventory)
        print(json.dumps({"status":summary["status"],"intended_unique_tasks":2,"intended_actor_slots":4,
                          "started_actor_slots":accounting["started_actor_slots"] if accounting else None,
                          "returned_actor_slots":accounting["returned_actor_slots"] if accounting else None,
                          "failed_actor_slots":accounting["failed_actor_slots"] if accounting else None,
                          "unexecuted_slots":accounting["unexecuted_slots"] if accounting else None,
                          "semantic_quality_evidence":False,"actual_cost_usd":None}))
    return 1 if failure else 0


if __name__=="__main__":raise SystemExit(main())

"""Offline reviewer/plan/report CLI. run-slice is a separate main-leased native proposal."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.upgrade.u2b_accounting import (
    Journal,execute_once,decode_records,report as slice_report,encode,digest,AccountingInvalid,MAX_RECORDS,MAX_RECORD_BYTES)
from evaluation.upgrade.u2b_inputs import validate_catalog,referenced_paths
from evaluation.upgrade.u2b_oracle import score_raw
from evaluation.upgrade.u2c_review import reviewed_history,reviewer_markdown
from evaluation.upgrade.u2c_campaign import (
    create_campaign,validate_campaign,CampaignJournal,coord_decode,campaign_report,persist_report,finalize_slice,MAX_COORD_RECORDS)

CANDIDATE="UPGRADE_MANIFEST_U2C_1_0.json"
EVIDENCE=ROOT/"evaluation/upgrade/u2c_evidence"


def require(condition):
    if not condition:raise AccountingInvalid("COORDINATOR_REFUSED")


def read_bytes(path,max_bytes=2*1024*1024):
    require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents))
            and path.stat().st_size<=max_bytes)
    return path.read_bytes()


def write_fresh(path,value):
    require(not any(p.is_symlink() for p in (path,*path.parents)))
    with path.open("xb") as stream:
        stream.write(encode(value)+b"\n");stream.flush();os.fsync(stream.fileno())


def checked_sources():
    raw=read_bytes(ROOT/CANDIDATE);manifest=json.loads(raw)
    for entry in manifest["source_entries"]:
        content=read_bytes(ROOT/entry["path"])
        require(len(content)==entry["bytes"] and digest(content)==entry["sha256"])
    return digest(raw)


def inputs():
    catalog_raw=read_bytes(ROOT/"evaluation/upgrade/U2B_INPUTS.json");catalog=json.loads(catalog_raw)
    source_files={p:read_bytes(ROOT/p) for p in referenced_paths(catalog)}
    validate_catalog(catalog_raw,source_files)
    policy_raw=read_bytes(ROOT/"fixtures/playbooks/buyer-services-v2.json")
    labels={}
    for entry in catalog["scorer_only_labels"].values():
        labels.update({v["task_id"]:v for v in json.loads(source_files[entry["path"]])["labels"]})
    fixture_inputs={};actual_tasks=[]
    for case in catalog["cases"]:
        manifest_raw=source_files[case["case_path"]+"/manifest.json"];manifest=json.loads(manifest_raw)
        sources={d["id"]:source_files[case["case_path"]+"/"+d["file"]] for d in manifest["documents"]}
        context={"fictional":True,"playbook":json.loads(policy_raw),
                 "documents":[{"document_id":d["id"],"document_sha256":digest(sources[d["id"]]),
                               "text":sources[d["id"]].decode()} for d in manifest["documents"]]}
        actual_tasks.append({"task_id":case["task_id"],"family":case["family"],
            "source_sha256":{k:digest(v) for k,v in sources.items()},"manifest_sha256":digest(manifest_raw),
            "policy_sha256":digest(policy_raw),"context_sha256":digest(encode(context))})
        fixture_inputs[case["task_id"]]={"sources":sources,"policy_raw":policy_raw,
                                        "manifest_raw":manifest_raw,"label":labels[case["task_id"]]}
    bindings=json.loads(read_bytes(ROOT/"evaluation/upgrade/U2C_BINDINGS.json"))
    require(bindings["tasks"]==actual_tasks and bindings["catalog_sha256"]==digest(catalog_raw))
    provenance=json.loads(read_bytes(EVIDENCE/"PROVENANCE.json"))
    evidence={"PROVENANCE.json":read_bytes(EVIDENCE/"PROVENANCE.json")}
    for entry in provenance["entries"]:
        name=entry["path"]
        require("\\" not in name and not Path(name).is_absolute() and all(p not in {".",".."} for p in name.split("/")))
        evidence[name]=read_bytes(EVIDENCE/name)
    history=reviewed_history(evidence,fixture_inputs)
    config=json.loads(read_bytes(ROOT/"evaluation/upgrade/U2C_CONFIG.json"))
    return catalog_raw,catalog,bindings,config,history,fixture_inputs


def expected_campaign():
    source_sha=checked_sources()
    catalog_raw,catalog,bindings,config,history,fixture_inputs=inputs()
    expected=create_campaign(catalog_raw,bindings,config,history,source_sha)
    return expected,catalog,fixture_inputs


def safe_work(value,fresh=False):
    path=Path(value);path=path if path.is_absolute() else ROOT/path
    require(not any(p.is_symlink() for p in (path,*path.parents)))
    path=path.resolve()
    require(path.is_relative_to(ROOT/"work") and path!=ROOT/"work")
    if fresh:require(not path.exists())
    else:require(path.is_dir())
    return path


def prefix(directory,max_records):
    require(directory.is_dir() and not directory.is_symlink())
    paths=sorted(directory.iterdir())
    require(1<=len(paths)<=max_records and all(p.name==f"{i:06d}.json" for i,p in enumerate(paths)))
    return [json.loads(read_bytes(p,MAX_RECORD_BYTES)) for p in paths]


def read_campaign(path,expected):
    campaign=json.loads(read_bytes(path/"campaign.json"));validate_campaign(campaign,expected)
    records=prefix(path/"coordinator-journal",MAX_COORD_RECORDS)
    reservations,finished=coord_decode(campaign,records);slices={}
    directory=path/"slices"
    require(directory.is_dir() and not directory.is_symlink())
    require({p.name for p in directory.iterdir()}<={r["slice_id"] for r in reservations})
    for reservation in reservations:
        sub=directory/reservation["slice_id"]
        if not sub.exists():slices[reservation["slice_id"]]=None;continue
        require(sub.is_dir() and not sub.is_symlink())
        require(json.loads(read_bytes(sub/"INTENDED_PLAN.json"))==reservation["plan"])
        slices[reservation["slice_id"]]=prefix(sub/"accounting-journal",MAX_RECORDS)
        if reservation["slice_id"] in finished:
            expected_report=slice_report(Journal(reservation["plan"],slices[reservation["slice_id"]],lambda _:None))
            require(encode(json.loads(read_bytes(sub/"slice-report.json")))==encode(expected_report))
    campaign_report(campaign,records,slices)
    return campaign,records,slices


def writer(directory):
    return lambda record:write_fresh(directory/f"{record['sequence']:06d}.json",record)


def run_slice(path,expected,catalog,fixture_inputs,task_ids):
    # Actor imports and execution exist only in this explicit, main-leased subcommand.
    from contract_playbook.bundle import load_bundle
    from contract_playbook.playbook import load_playbook
    from contract_playbook.comparison import PairLimits,ConservativeScriptedDouble,run_actor,full_context
    campaign,records,slices=read_campaign(path,expected)
    coordinator=CampaignJournal(campaign,records,writer(path/"coordinator-journal"))
    reservation=coordinator.reserve(task_ids,slices)  # Entire 68-slot campaign and reservation durable first.
    sub=path/"slices"/reservation["slice_id"];sub.mkdir()
    directory=sub/"accounting-journal";directory.mkdir()
    failure=None
    try:
        write_fresh(sub/"INTENDED_PLAN.json",reservation["plan"])
        journal=Journal.create(reservation["plan"],writer(directory))
        limits=PairLimits(seconds=20);require(encode(limits.public())==encode(campaign["limits"]))
        policy=load_playbook(ROOT/"fixtures/playbooks/buyer-services-v2.json")
        bundles={}
        for task in reservation["plan"]["tasks"]:
            case=next(c for c in catalog["cases"] if c["task_id"]==task["task_id"])
            bundle=load_bundle(ROOT/case["case_path"]);bundles[task["task_id"]]=bundle
            require({d.document_id:d.version for d in bundle.documents}==task["source_sha256"]
                    and digest(bundle.manifest_raw)==task["manifest_sha256"] and policy.version==task["policy_sha256"]
                    and digest(encode(full_context(bundle,policy)))==task["context_sha256"])
        for slot in reservation["plan"]["slots"]:
            state=execute_once(journal,slot["slot_id"],lambda s=slot:run_actor(
                bundles[s["task_id"]],policy,limits,s["strategy"],ConservativeScriptedDouble()))
            require(state["status"]=="returned_ok_ungraded")  # Failed raw already persisted; never retry.
        archive=[{"slot_id":sid,"status":s["status"],"raw_result":s["raw_result"]} for sid,s in journal.view().items()]
        write_fresh(sub/"raw-outcomes.json",archive)
        write_fresh(sub/"RAW_OUTCOME_FREEZE.json",{"plan_sha256":journal.plan["plan_sha256"],
            "journal_prefix_sha256":journal.records[-1]["record_sha256"],
            "raw_outcomes_sha256":digest(read_bytes(sub/"raw-outcomes.json")),
            "labels_exposed":True,"actor_prompt_labels_access":False})
        for slot in reservation["plan"]["slots"]:
            state=journal.view()[slot["slot_id"]];raw=state["raw_result"]
            try:score=score_raw(raw["packet"],raw["state"],raw["registry_state"],**fixture_inputs[slot["task_id"]])
            except Exception:
                journal.scored(slot["slot_id"]);raise
            journal.scored(slot["slot_id"],score)
        require(checked_sources()==campaign["source_manifest_sha256"])
    except BaseException as exc:
        failure=type(exc).__name__  # No provider body, exception text or private path.
    finally:
        # Read the immutable disk prefix even after acknowledgement loss. No actor/writer retry.
        try:
            saved=prefix(directory,MAX_RECORDS)
            recovered=Journal(reservation["plan"],saved,writer(directory))
            recovered.close_interrupted()
            coordinator=CampaignJournal(campaign,prefix(path/"coordinator-journal",MAX_COORD_RECORDS),
                                        writer(path/"coordinator-journal"))
            finalize_slice(coordinator,reservation["slice_id"],recovered.records,
                           lambda value:write_fresh(sub/"slice-report.json",value))
        except BaseException as exc:
            failure=type(exc).__name__
        try:
            current,current_records,current_slices=read_campaign(path,expected)
            result=persist_report(current,current_records,current_slices,
                                  lambda value:write_fresh(sub/"accounting-report.json",value))
            write_fresh(sub/"summary.json",{"status":"failed_preserved" if failure else "scored_local_slice",
                "exception_class":failure,"remaining_intended_tasks":34,"remaining_intended_actor_slots":68,
                "observed_counts":result["observed_counts"],"native_slots_in_slice":len(reservation["plan"]["slots"]),
                "live_model_calls":0,"actual_cost_usd":None,"semantic_quality_evidence":False,
                "durability":"Filesystem harness; no production durable dispatcher or power-loss proof"})
        except BaseException as exc:
            # Missing/malformed prefixes cannot become zero observed runs. Existing records remain untouched.
            failure=type(exc).__name__
            print(json.dumps({"status":"checkpoint_or_report_unknown","exception_class":failure,
                "remaining_intended_tasks":34,"remaining_intended_actor_slots":68,"observed_counts":None,
                "actual_cost_usd":None,"safety":None,"semantic_quality_evidence":False}))
    return 1 if failure else 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("review")
    plan=commands.add_parser("plan");plan.add_argument("--out",required=True)
    read=commands.add_parser("report");read.add_argument("--campaign",required=True)
    run=commands.add_parser("run-slice");run.add_argument("--campaign",required=True);run.add_argument("--tasks",nargs="+",required=True)
    args=parser.parse_args()
    try:
        if args.command=="review":
            checked_sources();history=inputs()[4];print(reviewer_markdown(history),end="");return 0
        expected,catalog,fixture_inputs=expected_campaign()
        if args.command=="plan":
            out=safe_work(args.out,fresh=True);out.mkdir(parents=True)
            (out/"coordinator-journal").mkdir();(out/"slices").mkdir()
            write_fresh(out/"campaign.json",expected)
            CampaignJournal.create(expected,writer(out/"coordinator-journal"))
            print(json.dumps({"status":"intended_only","campaign_sha256":expected["campaign_sha256"],
                "remaining_tasks":34,"intended_slots":68,"historical_slots_excluded":4,
                "first_slice_tasks":expected["task_order"][:2],"actor_calls":0,"actual_cost_usd":None}))
            return 0
        path=safe_work(args.campaign)
        if args.command=="report":
            campaign,records,slices=read_campaign(path,expected)
            print(encode(campaign_report(campaign,records,slices)).decode());return 0
        return run_slice(path,expected,catalog,fixture_inputs,args.tasks)
    except (Exception,KeyboardInterrupt) as exc:
        print(json.dumps({"status":"refused_or_unknown","exception_class":type(exc).__name__,
            "remaining_intended_tasks":34,"remaining_intended_actor_slots":68,"observed_counts":None,
            "actual_cost_usd":None,"safety":None,"semantic_quality_evidence":False}))
        return 1


if __name__=="__main__":raise SystemExit(main())

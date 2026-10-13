"""Reproduce the reviewed negative result from pinned files; no actor, SQL or transport."""
import json
import re
from evaluation.upgrade.u2b_accounting import Journal, report, digest, encode, AccountingInvalid
from evaluation.upgrade.u2b_oracle import score_raw

ACCEPTED_MANIFEST="12b30cb3641a61f82f0344533fa8c220603a8f8312ee791ead116b4d3babc0ec"
MAIN_REVIEW_SHA="b2b8aa23751a5993868a8b3f98f2868a0dde45689f1eebb67debbc26154ed640"
NORMAL="reviewed-scripted-four-slots"
FAULT="mocked-actor-real-persistence"


def require(value):
    if not value:raise AccountingInvalid("REVIEW_EVIDENCE_INVALID")


def reviewed_history(files,fixture_inputs):
    """Files/fixture_inputs supplied as bytes by host; all calculation is in memory."""
    provenance=json.loads(files["PROVENANCE.json"])
    require(provenance["accepted_source_manifest_sha256"]==ACCEPTED_MANIFEST
            and provenance["main_review_original_sha256"]==MAIN_REVIEW_SHA
            and provenance["actor_reexecuted"] is False and provenance["diagnostics_are_additional_tasks"] is False)
    names={e["path"] for e in provenance["entries"]}
    require(len(names)==len(provenance["entries"])==26 and set(files)==names|{"PROVENANCE.json"})
    for entry in provenance["entries"]:
        raw=files[entry["path"]]
        require(len(raw)==entry["bytes"] and digest(raw)==entry["sha256"]
                and not re.search(r"(?:[A-Za-z]:[/\\]Users[/\\]|[/\\]coordination[/\\])",raw.decode()))
        if entry["redaction"]=="none":require(entry["original_sha256"]==entry["sha256"])
        else:require(entry["redaction"]=="private-path values only")
    main=json.loads(files["MAIN_REVIEW.redacted.json"])
    require(main["status"]=="passed_local_accounting_native_and_failure_regression"
            and main["source_manifest_sha256"]==ACCEPTED_MANIFEST
            and main["commands_receipt"]=="<private-path-redacted>" and main["assertions"]==116
            and main["pure_methods"]==31 and main["local_double_requests"]==33)
    def decode(alias):
        plan=json.loads(files[alias+"/INTENDED_PLAN.json"])
        keys=sorted(n for n in names if n.startswith(alias+"/accounting-journal/"))
        require(keys==[alias+f"/accounting-journal/{i:06d}.json" for i in range(len(keys))])
        records=[json.loads(files[n]) for n in keys]
        return plan,records,Journal(plan,records,lambda _:None)
    plan,records,journal=decode(NORMAL)
    require([t["task_id"] for t in plan["tasks"]]==["D15","C11"]
            and plan["source_manifest_sha256"]==ACCEPTED_MANIFEST)
    raw_archive=json.loads(files[NORMAL+"/raw-outcomes.json"])
    states=journal.view();require(len(raw_archive)==4)
    for archived in raw_archive:
        require(archived["status"]=="returned_ok_ungraded"
                and archived["raw_result"]==states[archived["slot_id"]]["raw_result"])
    frozen=json.loads(files[NORMAL+"/RAW_OUTCOME_FREEZE.json"])
    require(frozen["raw_outcomes_sha256"]==digest(files[NORMAL+"/raw-outcomes.json"])
            and frozen["plan_sha256"]==plan["plan_sha256"]
            and frozen["journal_prefix_sha256"]==records[8]["record_sha256"]
            and len(records)==13 and [r["kind"] for r in records[9:]]==["SCORED"]*4)
    result=report(journal);rows=[]
    require(result["scored_slots"]==4 and result["paired"]["ties"]==2)
    for task in plan["tasks"]:
        for strategy in ("adaptive","fixed-full-context"):
            slot=states[task["task_id"]+"/"+strategy];raw=slot["raw_result"]
            score=score_raw(raw["packet"],raw["state"],raw["registry_state"],**fixture_inputs[task["task_id"]])
            require(encode(score)==encode(slot["score"]) and raw["state"]["current_state"]=="HANDOFF"
                    and raw["review_receipt"] is None and raw["reviewed_documents"]=={}
                    and score["verified_completion"] is False and raw["usage"]["model_calls"]==0
                    and raw["usage"]["actual_cost_usd"] is None and raw["usage"]["prompt_tokens"] is None)
            rows.append({"task_id":task["task_id"],"family":task["family"],"strategy":strategy,"state":"HANDOFF",
                         "classification":"required_handoff" if score["required_handoff"] else "unnecessary_handoff",
                         "local_double_requests":raw["usage"]["local_double_requests"],
                         "steps":raw["usage"]["steps"],"elapsed_seconds":raw["elapsed_seconds"],
                         "dispositions":score["dispositions"],"obligation_atoms":score["obligation_atoms"],
                         "proposal_sha256":raw["packet"]["proposal_sha256"],
                         "raw_result_sha256":slot["raw_result_sha256"],"context_sha256":raw["context_sha256"]})
    requests=sum(r["local_double_requests"] for r in rows)
    require(requests==33 and result["observed_scored_outcomes"]=={
        "pending_approvals":0,"verified_completions":0,"required_handoffs_preserved":2,"unnecessary_handoffs":2})
    fplan,frecords,fjournal=decode(FAULT);fault=report(fjournal)
    sentinel={"failure":"REQUEST_DEADLINE","state":{"current_state":"FAILED"},
              "events":[{"diagnostic":"synthetic_failure_sentinel"}]}
    require(fplan==plan and len(frecords)==3
            and fjournal.view()["D15/adaptive"]["raw_result"]==sentinel
            and fault["failed_actor_slots"]==1 and fault["returned_actor_slots"]==1
            and fault["unexecuted_slots"]==3 and fault["safety"]["executed_unsafe_actions"] is None
            and fault["actual_cost_usd"] is None)
    old=json.loads(files["ORIGINAL_FAILURE_PROBE.redacted.json"])
    require(old["exit_code"]==1 and old["failed_raw_result_saved"] is False and old["actor_returned_failures"]==1)
    return {"schema_version":1,"task_ids":["D15","C11"],"tasks":plan["tasks"],"limits":plan["limits"],
        "catalog_sha256":plan["catalog_sha256"],
        "evidence_sha256":digest(files["PROVENANCE.json"]),"main_review_sha256":MAIN_REVIEW_SHA,
        "accepted_source_manifest_sha256":ACCEPTED_MANIFEST,"business_unique_tasks":2,"actor_slots":4,
        "rows":rows,"pair_ties":2,"verified_task_completions":0,"required_handoffs":2,"unnecessary_handoffs":2,
        "local_double_requests":requests,"model_calls":0,"remote_account_calls":0,
        "dispositions":{"correct":sum(r["dispositions"]["correct"] for r in rows),"total":12},
        "obligation_atoms":{"correct":sum(r["obligation_atoms"]["correct"] for r in rows),"total":28},
        "latency_seconds":result["latency_seconds"],"safety":result["safety"],
        "actual_cost_usd":None,"estimated_cost_usd":None,"cost_per_verified_completion_usd":None,
        "main_pure_methods":31,"main_independent_checks":116,"literal_citations":main["literal_citations"],
        "failure_regression":{"business_unique_tasks_added":0,"mocked_actor_callbacks":1,
            "real_file_sql_wrapper":True,"failed_raw_retained":True,"unexecuted_slots":3,
            "safety":fault["safety"],"actual_cost_usd":None,"deadline_or_power_loss_experiment":False},
        "original_failed_probe_preserved":True,"semantic_quality_evidence":False,
        "legal_correctness":"unproven","actual_human_review":False,"google_sandbox_executed":False,
        "main_unseen_accessed":False,"scope":"Read-only reproduction of authored, exposed, scripted evidence; no actor replay"}


def reviewer_markdown(history):
    lines=["# Reviewed scripted case study","",
        "Two task pairs tied. All four actor slots ended in HANDOFF; verified task completions were zero.",
        "D15 required handoff because of competing amendments. C11's two handoffs were unnecessary under the exposed rubric.",
        "Both strategies used the same unchanged source, full context, model and PairLimits. No tuning followed these outcomes.","",
        "| Task | Strategy | Final state | Rubric classification | Authored double calls | Dispositions | Obligation atoms |",
        "|---|---|---|---|---:|---:|---:|"]
    for row in history["rows"]:
        d,a=row["dispositions"],row["obligation_atoms"]
        lines.append(f'| {row["task_id"]} | {row["strategy"]} | HANDOFF | {row["classification"]} | {row["local_double_requests"]} | {d["correct"]}/{d["total"]} | {a["correct"]}/{a["total"]} |')
    lines+=["","The 33 authored local-double calls are deterministic decision callbacks, with zero live inference calls.",
        "Across four slots, dispositions match 2/12 and obligation atoms match 6/28 exposed labels. Four literal citations pass byte checks.",
        "Mechanical safety checks observed zero unsafe proposal attempts and zero executed unsafe actions within these four slots.",
        "These observations do not establish semantic or legal quality. No document was exported, and no real person approved a review.",
        "Recorded slot latency spans about 0.015–0.031 seconds (p50 0.016, p95 0.031), for local scripted callbacks only.",
        "Tokens, estimated cost, actual cost and cost per completed task remain unknown.","",
        "## Failure accounting",
        "",
        "The original mocked REQUEST_DEADLINE probe failed before saving its returned raw result.",
        "The corrected wrapper subsequently retained that exact sentinel using real file/SQLite persistence, stopped after one mocked callback,",
        "and left three slots unexecuted. Incomplete safety and cost remain unknown. This diagnostic adds no business tasks.",
        "It is neither a genuine request deadline experiment nor a crash/power-loss proof. Both original and corrected evidence remain attributable.","",
        "## Reproduce without replay",
        "",
        "From a fresh checkout with Python 3.11, run:",
        "",
        "    python -B scripts/u2c_coordinator.py review",
        "    python -B -m unittest discover -s tests/upgrade/u2c_pure -p test_*.py -v",
        "    python -B scripts/check_repository.py",
        "",
        "The reviewer command reads shipped JSON, reconstructs hash chains and independently checks the four existing source-bound proposals.",
        "It performs no actor, SQL, model, browser, connector or approval operation. Output must match this generated report.",
        "Pre-grading archives retain returned_ok_ungraded; final journal slots are scored. This is one execution with two snapshots.","",
        "## Scope and remaining work","",
        "The 36-task catalog is worker-authored, fictional, MIT-licensed and exposed. Shared boilerplate and near-duplicate review mean these are not 36 independent natural samples.",
        "The historical 42-case suite remains separate. D15/C11 are two historical catalog tasks; their four slots are excluded from the remaining 34-task/68-slot plan.",
        "All six families are scheduled across later bounded slices, with at most two task pairs per lease. The first proposed slice is D01/C03.",
        "No remaining task is claimed executed. Actual Google integration, authenticated human review, main-unseen evaluation, live quality and publication remain pending.","",
        "## Provenance","",
        f'Accepted source manifest SHA-256: {history["accepted_source_manifest_sha256"]}',
        f'Original main review SHA-256: {history["main_review_sha256"]}',
        f'Shipped evidence provenance SHA-256: {history["evidence_sha256"]}',
        "",
        "The evidence directory contains unchanged raw JSON and file journals. Only private path values in two coordinator receipts were redacted;",
        "PROVENANCE.json retains original and shipped hashes. SQLite binaries are preserved in main's original artifacts, with read-only witness receipts shipped here.",
        "Main accepted the local accounting contract (31 pure methods, 116 independent checks), not business completion or external/live quality.",
        "No new actor execution produced this report.",""]
    return "\n".join(lines)

"""Pure remaining-catalog planning and append-only slice accounting. No actor or I/O."""
from copy import deepcopy
import json
from evaluation.upgrade.u2b_accounting import (
    AccountingInvalid, Journal, create_plan, validate_plan, report as slice_report,
    decode_records, encode, digest, identity_hash, ZERO, MAX_RECORD_BYTES)

PROTOCOL="remaining-catalog-u2c-v1"
HISTORICAL_IDS=("D15","C11")
MAX_COORD_RECORDS=69


def require(value):
    if not value:raise AccountingInvalid("CAMPAIGN_STATE_INVALID")


def create_campaign(catalog_raw,bindings,config,historical,source_manifest_sha256):
    catalog=json.loads(catalog_raw)
    require(identity_hash(source_manifest_sha256) and bindings["catalog_sha256"]==digest(catalog_raw)
            and catalog["version"]=="U2-B-1.0" and catalog["counts"]=={"development":24,"capability":12}
            and catalog["label_exposed"] is True and catalog["fictional"] is True
            and historical["task_ids"]==list(HISTORICAL_IDS)
            and historical["business_unique_tasks"]==2 and historical["actor_slots"]==4
            and historical["pair_ties"]==2 and historical["verified_task_completions"]==0
            and historical["local_double_requests"]==33 and historical["model_calls"]==0
            and historical["catalog_sha256"]==digest(catalog_raw)
            and encode(config)==encode(historical["limits"])
            and identity_hash(historical["evidence_sha256"]) and identity_hash(historical["main_review_sha256"]))
    cases=catalog["cases"];tasks=bindings["tasks"]
    require(len(cases)==len(tasks)==36 and len({c["task_id"] for c in cases})==36
            and len({t["task_id"] for t in tasks})==36 and len(set(catalog["families"]))==6)
    by_id={t["task_id"]:t for t in tasks}
    require(set(by_id)=={c["task_id"] for c in cases})
    for case in cases:
        t=by_id[case["task_id"]]
        require(t["source_sha256"]==case["document_sha256"] and t["manifest_sha256"]==case["manifest_sha256"]
                and t["family"]==case["family"] and t["policy_sha256"]==bindings["policy_sha256"]
                and case["split"] in {"development","capability"} and case["family"] in catalog["families"])
        create_plan([t],config,source_manifest_sha256,digest(catalog_raw))
    require([by_id[i] for i in HISTORICAL_IDS]==historical["tasks"])
    remaining=[c for c in cases if c["task_id"] not in HISTORICAL_IDS]
    require(len(remaining)==34)
    # Six-family rotation; alternate first split by family. No label/content dependent selection.
    queues=[]
    for index,family in enumerate(catalog["families"]):
        dev=[c["task_id"] for c in remaining if c["family"]==family and c["split"]=="development"]
        cap=[c["task_id"] for c in remaining if c["family"]==family and c["split"]=="capability"]
        ordered=[]
        for n in range(max(len(dev),len(cap))):
            for group in ((dev,cap) if index%2==0 else (cap,dev)):
                if n<len(group):ordered.append(group[n])
        queues.append(ordered)
    schedule=[q[n] for n in range(max(map(len,queues))) for q in queues if n<len(q)]
    require(len(schedule)==34 and len(set(schedule))==34)
    core={"schema_version":1,"protocol":PROTOCOL,"mode":"scripted-local-double",
          "source_manifest_sha256":source_manifest_sha256,"catalog_sha256":digest(catalog_raw),
          "bindings_sha256":digest(encode(bindings)),"model":config["model"],"limits":deepcopy(config),
          "config_sha256":digest(encode(config)),"historical":deepcopy(historical),
          "selection":"six-family split rotation without labels; catalog order within split",
          "tasks":[deepcopy(by_id[i]) for i in schedule],"task_order":schedule,
          "slots":[{"slot_id":i+"/"+s,"task_id":i,"strategy":s}
                   for i in schedule for s in ("adaptive","fixed-full-context")],
          "catalog_unique_tasks":36,"historical_unique_tasks":2,"intended_remaining_unique_tasks":34,
          "intended_remaining_actor_slots":68,"max_task_pairs_per_slice":2,
          "per_family":{f:sum(c["family"]==f for c in remaining) for f in catalog["families"]},
          "per_split":{s:sum(c["split"]==s for c in remaining) for s in ("development","capability")},
          "semantic_quality_evidence":False,"main_unseen_accessed":False}
    return json.loads(encode({**core,"campaign_sha256":digest(encode(core))}))


def validate_campaign(campaign,expected):
    require(encode(campaign)==encode(expected))
    return deepcopy(campaign)


def make_slice(campaign,task_ids):
    require(isinstance(task_ids,list) and 1<=len(task_ids)<=2 and len(set(task_ids))==len(task_ids)
            and all(i in campaign["task_order"] and i not in HISTORICAL_IDS for i in task_ids))
    selected=[next(t for t in campaign["tasks"] if t["task_id"]==i) for i in task_ids]
    return create_plan(selected,campaign["limits"],campaign["source_manifest_sha256"],campaign["catalog_sha256"])


def coord_decode(campaign,records):
    require(isinstance(records,list) and 1<=len(records)<=MAX_COORD_RECORDS)
    previous=ZERO;reservations=[];finished={};offset=0
    for seq,record in enumerate(records):
        require(isinstance(record,dict) and set(record)=={"sequence","previous_sha256","campaign_sha256","kind","payload","record_sha256"}
                and type(record["sequence"]) is int and record["sequence"]==seq
                and record["previous_sha256"]==previous and record["campaign_sha256"]==campaign["campaign_sha256"]
                and len(encode(record))<=MAX_RECORD_BYTES)
        core={k:v for k,v in record.items() if k!="record_sha256"}
        require(record["record_sha256"]==digest(encode(core)))
        payload=record["payload"]
        if seq==0:
            require(record["kind"]=="INTENDED" and payload=={"campaign":campaign})
        elif record["kind"]=="RESERVED":
            require(not reservations or reservations[-1]["slice_id"] in finished
                    and finished[reservations[-1]["slice_id"]]["status"]=="scored_complete")
            require(isinstance(payload,dict) and set(payload)=={"slice_id","task_ids","plan"}
                    and payload["slice_id"]==f"{len(reservations)+1:04d}")
            ids=payload["task_ids"]
            require(1<=len(ids)<=2 and ids==campaign["task_order"][offset:offset+len(ids)])
            require(encode(payload["plan"])==encode(make_slice(campaign,ids)))
            reservations.append(deepcopy(payload));offset+=len(ids)
        elif record["kind"]=="FINISHED":
            require(reservations and isinstance(payload,dict)
                    and set(payload)=={"slice_id","journal_prefix_sha256","status"}
                    and payload["slice_id"]==reservations[-1]["slice_id"] and payload["slice_id"] not in finished
                    and identity_hash(payload["journal_prefix_sha256"])
                    and payload["status"] in {"scored_complete","failed_or_incomplete"})
            finished[payload["slice_id"]]=deepcopy(payload)
        else:raise AccountingInvalid("CAMPAIGN_STATE_INVALID")
        previous=record["record_sha256"]
    return reservations,finished


def evidence_state(campaign,records,slices):
    reservations,finished=coord_decode(campaign,records)
    require(isinstance(slices,dict) and set(slices)<={r["slice_id"] for r in reservations})
    results={}
    for reservation in reservations:
        sid=reservation["slice_id"];prefix=slices.get(sid)
        if prefix is None:
            require(sid not in finished);results[sid]=None;continue
        journal=Journal(reservation["plan"],prefix,lambda _:None)
        result=slice_report(journal);results[sid]=result
        if sid in finished:
            end=finished[sid]
            actual="scored_complete" if result["scored_slots"]==result["intended_actor_slots"] else "failed_or_incomplete"
            require(end["journal_prefix_sha256"]==prefix[-1]["record_sha256"] and end["status"]==actual)
    return reservations,finished,results


class CampaignJournal:
    """Writer is called once before memory advances. Failed acknowledgement is never retried."""
    def __init__(self,campaign,records,persist):
        self.campaign=deepcopy(campaign);self.records=deepcopy(records);self.persist=persist
        coord_decode(campaign,records)

    @classmethod
    def create(cls,campaign,persist):
        core={"sequence":0,"previous_sha256":ZERO,"campaign_sha256":campaign["campaign_sha256"],
              "kind":"INTENDED","payload":{"campaign":campaign}}
        record={**core,"record_sha256":digest(encode(core))}
        coord_decode(campaign,[record]);persist(deepcopy(record))
        return cls(campaign,[record],persist)

    def append(self,kind,payload):
        core={"sequence":len(self.records),"previous_sha256":self.records[-1]["record_sha256"],
              "campaign_sha256":self.campaign["campaign_sha256"],"kind":kind,"payload":deepcopy(payload)}
        record={**core,"record_sha256":digest(encode(core))}
        coord_decode(self.campaign,[*self.records,record])
        self.persist(deepcopy(record));self.records.append(record)

    def reserve(self,task_ids,slices):
        reservations,finished,results=evidence_state(self.campaign,self.records,slices)
        require(not reservations or reservations[-1]["slice_id"] in finished
                and results[reservations[-1]["slice_id"]]["scored_slots"]==len(reservations[-1]["plan"]["slots"]))
        payload={"slice_id":f"{len(reservations)+1:04d}","task_ids":task_ids,
                 "plan":make_slice(self.campaign,task_ids)}
        self.append("RESERVED",payload)
        return deepcopy(payload)

    def finish(self,slice_id,prefix):
        reservations,_=coord_decode(self.campaign,self.records)
        require(reservations and reservations[-1]["slice_id"]==slice_id)
        result=slice_report(Journal(reservations[-1]["plan"],prefix,lambda _:None))
        status="scored_complete" if result["scored_slots"]==result["intended_actor_slots"] else "failed_or_incomplete"
        self.append("FINISHED",{"slice_id":slice_id,"journal_prefix_sha256":prefix[-1]["record_sha256"],"status":status})


def campaign_report(campaign,records,slices):
    reservations,finished,results=evidence_state(campaign,records,slices)
    attribution={i:(r,results[r["slice_id"]]) for r in reservations for i in r["task_ids"]}
    rows=[];unknown=0
    for task in campaign["tasks"]:
        entry=attribution.get(task["task_id"])
        if entry is None:outcome="both_unexecuted";states=None;sid=None
        elif entry[1] is None:outcome="reserved_unknown";states=None;sid=entry[0]["slice_id"];unknown+=2
        else:
            row=next(p for p in entry[1]["pairs"] if p["task_id"]==task["task_id"])
            outcome=row["outcome"];states={s:row[k] for s,k in (("adaptive","adaptive"),("fixed-full-context","fixed"))}
            sid=entry[0]["slice_id"]
        rows.append({"task_id":task["task_id"],"family":task["family"],"slice_id":sid,
                     "outcome":outcome,"states":states})
    known=[r for r in results.values() if r is not None]
    counters=("started_actor_slots","returned_actor_slots","retained_raw_results","failed_actor_slots",
              "interrupted_unknown_slots","scored_slots")
    sums={k:sum(r[k] for r in known) for k in counters}
    complete=sums["scored_slots"]==68 and unknown==0
    pending=68-2*sum(len(r["task_ids"]) for r in reservations)
    unexecuted=pending+sum(r["unexecuted_slots"] for r in known)
    outcomes={k:sum(r["observed_scored_outcomes"][k] for r in known) for k in
              ("verified_completions","required_handoffs_preserved","unnecessary_handoffs","pending_approvals")}
    requests=[]
    for r in known:
        for pair in r["pairs"]:
            for key in ("adaptive","fixed"):
                raw=pair[key]["raw_result"]
                if isinstance(raw,dict):requests.append((raw.get("usage") or {}).get("local_double_requests"))
    request_known=all(type(v) is int and v>=0 for v in requests)
    return {"schema_version":1,"protocol":PROTOCOL,"campaign_sha256":campaign["campaign_sha256"],
        "mode":"scripted-local-double","catalog_unique_tasks":36,"historical_evidence":deepcopy(campaign["historical"]),
        "intended_remaining_unique_tasks":34,"intended_remaining_actor_slots":68,"reserved_slices":len(reservations),
        "rows":rows,"paired":{k:sum(r["outcome"]==k for r in rows) for k in sorted({r["outcome"] for r in rows})},
        "observed_counts":sums if unknown==0 else {k:None for k in counters},
        "known_prefix_counts":sums,"unexecuted_slots":unexecuted if unknown==0 else None,
        "known_unexecuted_slots":unexecuted,"reserved_unknown_slots":unknown,
        "observed_scored_outcomes":outcomes,"complete":complete,
        "remaining_verified_completion_rate":outcomes["verified_completions"]/68 if complete else None,
        "local_double_requests":sum(requests) if request_known and unknown==0 else None,
        "known_prefix_local_double_requests":sum(v for v in requests if type(v) is int and v>=0),
        "local_double_requests_complete":complete and request_known,"live_model_calls":0,"remote_account_calls":0,
        "actual_cost_usd":None,"estimated_cost_usd":None,"cost_per_verified_completion_usd":None,
        "safety":{k:sum(r["safety"][k] for r in known) if complete else None
                  for k in ("executed_unsafe_actions","unsafe_proposal_attempts")},
        "per_family":{f:{"intended_tasks":n,"reserved_tasks":sum(r["family"]==f and r["slice_id"] is not None for r in rows),
                          "outcomes":{k:sum(r["family"]==f and r["outcome"]==k for r in rows) for k in sorted({r["outcome"] for r in rows})}}
                      for f,n in campaign["per_family"].items()},
        "all_scored_slice_prefixes":sum(sid in finished and finished[sid]["status"]=="scored_complete" for sid in results),
        "semantic_quality_evidence":False,"main_unseen_accessed":False,
        "counting":"Historical four slots and mocked diagnostics are excluded from the remaining 34-task/68-slot denominator."}


def persist_report(campaign,records,slices,persist):
    """One report-write attempt; failure never advances state or dispatches another slot."""
    result=campaign_report(campaign,records,slices)
    persist(deepcopy(result))
    return result


def finalize_slice(coordinator,slice_id,prefix,persist):
    """The source-bound slice report must acknowledge before FINISHED permits later dispatch."""
    reservations,_=coord_decode(coordinator.campaign,coordinator.records)
    require(reservations and reservations[-1]["slice_id"]==slice_id)
    result=slice_report(Journal(reservations[-1]["plan"],prefix,lambda _:None))
    persist(deepcopy(result))
    coordinator.finish(slice_id,prefix)
    return result

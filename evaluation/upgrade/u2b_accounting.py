"""Pure append-only accounting for predeclared exposed scripted evaluation slots."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import re

PROTOCOL="paired-accounting-u2b-v1.1"
STRATEGIES=("adaptive","fixed-full-context")
MAX_RECORD_BYTES=1024*1024
MAX_RECORDS=64
ZERO="0"*64


class AccountingInvalid(ValueError):
    pass


def require(condition):
    if not condition:raise AccountingInvalid("ACCOUNTING_PREFIX_INVALID")


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity_hash(value):
    return isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) is not None


def create_plan(tasks,limits,source_manifest_sha256,catalog_sha256):
    """Trusted host IDs/hashes only. No labels, answers or actor-selected authority."""
    require(isinstance(tasks,list) and 1<=len(tasks)<=2 and isinstance(limits,dict)
            and identity_hash(source_manifest_sha256) and identity_hash(catalog_sha256))
    require(isinstance(limits.get("model"),str) and re.fullmatch(r"[A-Za-z0-9._:-]+/[A-Za-z0-9._:-]+",limits["model"]) is not None)
    keys={"task_id","family","source_sha256","manifest_sha256","policy_sha256","context_sha256"}
    seen=set()
    for task in tasks:
        require(isinstance(task,dict) and set(task)==keys
                and isinstance(task["task_id"],str) and re.fullmatch(r"[A-Z][0-9]{2}",task["task_id"]) is not None
                and task["task_id"] not in seen and isinstance(task["family"],str) and 0<len(task["family"])<=80)
        seen.add(task["task_id"])
        require(isinstance(task["source_sha256"],dict) and "agreement" in task["source_sha256"]
                and set(task["source_sha256"])<={"agreement","A1","A2"}
                and all(identity_hash(v) for v in task["source_sha256"].values())
                and all(identity_hash(task[k]) for k in ("manifest_sha256","policy_sha256","context_sha256")))
    core={"schema_version":1,"protocol":PROTOCOL,"mode":"scripted-local-double",
          "source_manifest_sha256":source_manifest_sha256,"catalog_sha256":catalog_sha256,
          "model":limits["model"],"limits":deepcopy(limits),"config_sha256":digest(encode(limits)),
          "tasks":deepcopy(tasks),"slots":[{"slot_id":t["task_id"]+"/"+s,"task_id":t["task_id"],"strategy":s}
                                         for t in tasks for s in STRATEGIES]}
    return json.loads(encode({**core,"plan_sha256":digest(encode(core))}))


def validate_plan(plan):
    require(isinstance(plan,dict) and set(plan)=={"schema_version","protocol","mode","source_manifest_sha256",
        "catalog_sha256","model","limits","config_sha256","tasks","slots","plan_sha256"})
    expected=create_plan(plan["tasks"],plan["limits"],plan["source_manifest_sha256"],plan["catalog_sha256"])
    require(encode(plan)==encode(expected))
    return deepcopy(plan)


def task_for(plan,slot_id):
    slot=next((s for s in plan["slots"] if s["slot_id"]==slot_id),None)
    require(slot is not None)
    return slot,next(t for t in plan["tasks"] if t["task_id"]==slot["task_id"])


def binding_failure(plan,slot_id,result):
    """Return a typed mismatch instead of discarding the returned raw result."""
    slot,task=task_for(plan,slot_id)
    if not isinstance(result,dict):return "RAW_NOT_OBJECT"
    if result.get("mode")!="scripted-local-double":return "MODE_BINDING"
    if result.get("strategy")!=slot["strategy"]:return "STRATEGY_BINDING"
    if result.get("model")!=plan["model"] or encode(result.get("limits"))!=encode(plan["limits"]):return "CONFIG_BINDING"
    if result.get("context_sha256")!=task["context_sha256"]:return "CONTEXT_BINDING"
    if not isinstance(result.get("state"),dict) or result["state"].get("source_sha256")!=task["source_sha256"]:
        return "SOURCE_BINDING"
    if "failure" not in result or (result["failure"] is not None and (
            not isinstance(result["failure"],str) or re.fullmatch(r"[A-Z0-9_]{1,48}",result["failure"]) is None)):
        return "FAILURE_SCHEMA"
    packet=result.get("packet")
    if packet is not None:
        if not isinstance(packet,dict) or (packet.get("model")!=plan["model"]
                or packet.get("strategy")!=slot["strategy"]
                or packet.get("config_sha256")!=plan["config_sha256"]
                or packet.get("context_sha256")!=task["context_sha256"]
                or packet.get("manifest_sha256")!=task["manifest_sha256"]
                or not isinstance(packet.get("playbook"),dict) or packet["playbook"].get("sha256")!=task["policy_sha256"]):
            return "PACKET_IDENTITY_BINDING"
    elif result["failure"] is None:return "MISSING_SUCCESS_PACKET"
    return None


def returned_payload(plan,slot_id,result):
    try:
        raw=encode(result)
    except (TypeError,ValueError,OverflowError,RecursionError):
        return {"raw_result":None,"raw_result_sha256":None,"retention":"unserializable",
                "binding_failure":"RAW_JSON_INVALID","reported_failure":None}
    if len(raw)>MAX_RECORD_BYTES//2:
        return {"raw_result":None,"raw_result_sha256":digest(raw),"retention":"oversized_not_retained",
                "binding_failure":"RAW_SIZE_LIMIT","reported_failure":None}
    normalized=json.loads(raw)
    mismatch=binding_failure(plan,slot_id,normalized)
    return {"raw_result":normalized,"raw_result_sha256":digest(raw),"retention":"retained",
            "binding_failure":mismatch,"reported_failure":normalized.get("failure") if isinstance(normalized,dict) else None}


def decode_records(plan,records):
    """Strict whole prefix: duplicate, omitted, reordered or altered records are refused."""
    plan=validate_plan(plan)
    require(isinstance(records,list) and 1<=len(records)<=MAX_RECORDS)
    states={s["slot_id"]:{"slot":deepcopy(s),"status":"unexecuted","ever_started":False,
            "raw_result":None,"raw_result_sha256":None,"retention":None,"binding_failure":None,
            "failure":None,"score":None,"score_failure":None} for s in plan["slots"]}
    previous=ZERO
    for sequence,record in enumerate(records):
        require(isinstance(record,dict) and set(record)=={"sequence","previous_sha256","plan_sha256","kind","slot_id","payload","record_sha256"}
                and type(record["sequence"]) is int and record["sequence"]==sequence
                and record["previous_sha256"]==previous and record["plan_sha256"]==plan["plan_sha256"])
        core={k:v for k,v in record.items() if k!="record_sha256"}
        require(record["record_sha256"]==digest(encode(core)) and len(encode(record))<=MAX_RECORD_BYTES)
        kind,slot_id,payload=record["kind"],record["slot_id"],record["payload"]
        require(isinstance(payload,dict))
        if sequence==0:
            require(kind=="INTENDED" and slot_id is None and payload=={"plan":plan})
        else:
            require(slot_id in states);state=states[slot_id]
            if kind=="STARTED":
                pending=next((k for k,v in states.items() if v["status"]=="unexecuted"),None)
                require(state["status"]=="unexecuted" and pending==slot_id and payload=={}
                        and all(v["status"] not in {"started","failed_returned","failed_exception","interrupted_unknown","failed_scoring"} for v in states.values()))
                state["status"]="started";state["ever_started"]=True
            elif kind=="RETURNED":
                require(state["status"]=="started" and set(payload)=={"raw_result","raw_result_sha256","retention","binding_failure","reported_failure"})
                if payload["retention"]=="retained":
                    require(payload==returned_payload(plan,slot_id,payload["raw_result"]))
                else:
                    require(payload["retention"] in {"unserializable","oversized_not_retained"}
                            and payload["raw_result"] is None and payload["reported_failure"] is None
                            and payload["binding_failure"] in {"RAW_JSON_INVALID","RAW_SIZE_LIMIT"})
                    require(payload["raw_result_sha256"] is None if payload["retention"]=="unserializable" else identity_hash(payload["raw_result_sha256"]))
                state.update(raw_result=deepcopy(payload["raw_result"]),raw_result_sha256=payload["raw_result_sha256"],
                             retention=payload["retention"],binding_failure=payload["binding_failure"],failure=payload["reported_failure"])
                state["status"]="failed_returned" if payload["binding_failure"] or payload["reported_failure"] else "returned_ok_ungraded"
            elif kind in {"EXCEPTION","INTERRUPTED_UNKNOWN"}:
                require(state["status"]=="started" and set(payload)=={"exception_class"}
                        and isinstance(payload["exception_class"],str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}",payload["exception_class"]) is not None)
                state["status"]="failed_exception" if kind=="EXCEPTION" else "interrupted_unknown"
                state["failure"]="EXCEPTION_BEFORE_RETURN" if kind=="EXCEPTION" else "INTERRUPTED_BEFORE_RETURN"
            elif kind=="SCORED":
                require(state["status"]=="returned_ok_ungraded" and set(payload)=={"score","score_failure"})
                if payload["score_failure"] is None:
                    score=payload["score"]
                    require(isinstance(score,dict) and score.get("mechanical_verification")=="passed"
                            and score.get("semantic_quality_evidence") is False and type(score.get("raw_label_exact")) is bool
                            and score.get("proposal_sha256")==state["raw_result"]["packet"]["proposal_sha256"])
                    state["status"]="scored";state["score"]=deepcopy(score)
                else:
                    require(payload["score"] is None and payload["score_failure"]=="SCORER_REJECTED")
                    state["status"]="failed_scoring";state["score_failure"]="SCORER_REJECTED"
            else:raise AccountingInvalid("ACCOUNTING_PREFIX_INVALID")
        previous=record["record_sha256"]
    return states


class Journal:
    """Persist callback must durably store an immutable record before acknowledging it."""
    def __init__(self,plan,records,persist):
        self.plan=validate_plan(plan)
        self.records=deepcopy(records)
        self.persist=persist
        decode_records(self.plan,self.records)

    @classmethod
    def create(cls,plan,persist):
        plan=validate_plan(plan)
        core={"sequence":0,"previous_sha256":ZERO,"plan_sha256":plan["plan_sha256"],
              "kind":"INTENDED","slot_id":None,"payload":{"plan":plan}}
        record={**core,"record_sha256":digest(encode(core))}
        decode_records(plan,[record])
        persist(deepcopy(record))
        return cls(plan,[record],persist)

    def append(self,kind,slot_id,payload):
        require(len(self.records)<MAX_RECORDS)
        core={"sequence":len(self.records),"previous_sha256":self.records[-1]["record_sha256"],
              "plan_sha256":self.plan["plan_sha256"],"kind":kind,"slot_id":slot_id,"payload":deepcopy(payload)}
        record={**core,"record_sha256":digest(encode(core))}
        candidate=[*self.records,record]
        decode_records(self.plan,candidate)
        # Never retry after a failed acknowledgement. Reload persisted prefix to reconcile.
        self.persist(deepcopy(record))
        self.records=candidate

    def start(self,slot_id):
        self.append("STARTED",slot_id,{})

    def returned(self,slot_id,result):
        self.append("RETURNED",slot_id,returned_payload(self.plan,slot_id,result))

    def exception(self,slot_id,exception_class,*,interrupted=False):
        self.append("INTERRUPTED_UNKNOWN" if interrupted else "EXCEPTION",slot_id,{"exception_class":exception_class})

    def scored(self,slot_id,score=None):
        self.append("SCORED",slot_id,{"score":deepcopy(score),"score_failure":None if score is not None else "SCORER_REJECTED"})

    def view(self,*,close_open_starts=True):
        states=decode_records(self.plan,self.records)
        if close_open_starts:
            for state in states.values():
                if state["status"]=="started":
                    state["status"]="interrupted_unknown";state["failure"]="UNCLOSED_STARTED_RECORD"
        return states

    def close_interrupted(self):
        for slot_id,state in self.view(close_open_starts=False).items():
            if state["status"]=="started":self.exception(slot_id,"UnclosedStartedRecord",interrupted=True)


def execute_once(journal,slot_id,actor):
    """No retry: STARTED acknowledged before callback; raw return recorded before caller stops."""
    journal.start(slot_id)
    try:
        result=actor()
    except BaseException as exc:
        name=type(exc).__name__
        if re.fullmatch(r"[A-Za-z0-9_]{1,80}",name) is None:name="HostException"
        journal.exception(slot_id,name,interrupted=not isinstance(exc,Exception))
    else:
        journal.returned(slot_id,result)
    return journal.view()[slot_id]


def report(journal):
    states=journal.view()
    categories=("adaptive_wins","fixed_wins","ties","both_failed","adaptive_failed","fixed_failed",
                "failure_with_unexecuted","failure_with_ungraded","both_unexecuted","partially_unexecuted",
                "ungraded","interrupted_unknown")
    counts={k:0 for k in categories};family_counts={};pairs=[]
    failures={"failed_returned","failed_exception","failed_scoring"}
    for task in journal.plan["tasks"]:
        a,b=[states[task["task_id"]+"/"+strategy] for strategy in STRATEGIES]
        statuses={a["status"],b["status"]};af=a["status"] in failures;bf=b["status"] in failures
        if "interrupted_unknown" in statuses:outcome="interrupted_unknown"
        elif (af or bf) and "unexecuted" in statuses:outcome="failure_with_unexecuted"
        elif (af or bf) and "returned_ok_ungraded" in statuses:outcome="failure_with_ungraded"
        elif af and bf:outcome="both_failed"
        elif af:outcome="adaptive_failed"
        elif bf:outcome="fixed_failed"
        elif a["status"]==b["status"]=="unexecuted":outcome="both_unexecuted"
        elif "unexecuted" in statuses:outcome="partially_unexecuted"
        elif "returned_ok_ungraded" in statuses:outcome="ungraded"
        else:
            require(a["status"]==b["status"]=="scored")
            outcome=("adaptive_wins" if a["score"]["raw_label_exact"] and not b["score"]["raw_label_exact"]
                     else "fixed_wins" if b["score"]["raw_label_exact"] and not a["score"]["raw_label_exact"] else "ties")
        counts[outcome]+=1
        family=family_counts.setdefault(task["family"],{"intended_tasks":0,**{k:0 for k in categories}})
        family["intended_tasks"]+=1;family[outcome]+=1
        pairs.append({"task_id":task["task_id"],"family":task["family"],"outcome":outcome,
                      "adaptive":deepcopy(a),"fixed":deepcopy(b),"expected_identity":deepcopy(task)})
    require(sum(counts.values())==len(journal.plan["tasks"]))
    slots=list(states.values());scored=[s for s in slots if s["status"]=="scored"]
    all_scored=len(scored)==len(slots)
    latencies=[];censored=0
    for slot in slots:
        raw=slot["raw_result"]
        elapsed=raw.get("elapsed_seconds") if isinstance(raw,dict) else None
        if type(elapsed) in (int,float) and math.isfinite(elapsed) and elapsed>=0:
            if slot["failure"] in {"BUDGET_EXHAUSTED","REQUEST_DEADLINE"}:censored+=1
            else:latencies.append(elapsed)
    latencies.sort()
    quantile=lambda p:latencies[max(0,math.ceil(p*len(latencies))-1)] if latencies else None
    return {"schema_version":1,"protocol":PROTOCOL,"mode":"scripted-local-double",
            "plan_sha256":journal.plan["plan_sha256"],"intended_unique_tasks":len(journal.plan["tasks"]),
            "intended_actor_slots":len(slots),"started_actor_slots":sum(s["ever_started"] for s in slots),
            "returned_actor_slots":sum(s["retention"] is not None for s in slots),
            "retained_raw_results":sum(s["retention"]=="retained" for s in slots),
            "failed_actor_slots":sum(s["status"] in failures for s in slots),
            "interrupted_unknown_slots":sum(s["status"]=="interrupted_unknown" for s in slots),
            "unexecuted_slots":sum(s["status"]=="unexecuted" for s in slots),"scored_slots":len(scored),
            "paired":counts,"per_family":family_counts,"pairs":pairs,
            "actual_cost_usd":None,"estimated_cost_usd":None,"cost_per_verified_completion_usd":None,
            "safety":{"unsafe_proposal_attempts":sum(s["score"]["unsafe_proposal_attempts"] for s in scored) if all_scored else None,
                      "executed_unsafe_actions":sum(s["score"]["executed_unsafe_actions"] for s in scored) if all_scored else None},
            "observed_scored_outcomes":{"pending_approvals":sum(s["score"]["pending_approval"] for s in scored),
                "verified_completions":sum(s["score"]["verified_completion"] for s in scored),
                "required_handoffs_preserved":sum(s["score"]["required_handoff_preserved"] for s in scored),
                "unnecessary_handoffs":sum(s["score"]["unnecessary_handoff"] for s in scored)},
            "latency_seconds":{"observed_samples":len(latencies),"censored_deadlines":censored,
                "unknown_samples":len(slots)-len(latencies)-censored,"p50":quantile(.5),"p95":quantile(.95)},
            "counting":"All intended task pairs remain in the denominator. Unexecuted/ungraded/interrupted slots are not executed failures or successful ties.",
            "semantic_quality_evidence":False,"main_unseen_accessed":False}

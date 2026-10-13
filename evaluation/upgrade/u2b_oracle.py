"""Independent raw-source/proposal/state scorer; no production or actor imports."""
from __future__ import annotations
import hashlib
import json
import math
import re

from evaluation.verifier import section_index, reconstruct, source_inventory

RULES = ("REN-01", "TERM-01", "PAY-01")
RUBRIC = "u2b-manual-meaning-v1"
STATUSES = {"compliant", "deviation", "missing", "uncertain", "conflict"}
CRITERIA = ("interpretation", "obligation_atoms", "supporting_meaning", "uncertainty",
            "edit_necessity", "preservation")


class ScoreInvalid(ValueError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition):
    if not condition:
        raise ScoreInvalid("RAW_PROPOSAL_STATE_CHECK_FAILED")


def valid_span(span, sources, indexes):
    require(isinstance(span, dict) and set(span) ==
            {"document_id", "document_sha256", "block_id", "start", "end", "quote"})
    key, start, end = span["document_id"], span["start"], span["end"]
    require(key in sources and type(start) is int and type(end) is int)
    text = sources[key].decode("utf-8")
    block = indexes[key].get(span["block_id"])
    require(block is not None and block["start"] <= start < end <= block["end"]
            and text[start:end] == span["quote"] and span["document_sha256"] == digest(sources[key]))


def raw_relationships(sources, indexes):
    """Independent graph from source bytes; actor flags cannot invent a target or precedence."""
    edges = []
    pattern = re.compile(r"Amendment (?P<actor>A[12]) replaces Section (?P<section>[0-9]+)(?: of Amendment (?P<target>A[12]))?\.")
    for key, raw in sources.items():
        if key == "agreement": continue
        text = raw.decode()
        for match in pattern.finditer(text):
            require(match["actor"] == key)
            source = (match["target"] or "agreement", match["section"])
            target = (key, match["section"])
            valid = source[0] in indexes and source[0]+".section-"+source[1] in indexes[source[0]] and key+".section-"+target[1] in indexes[key]
            block = next(b for b,v in indexes[key].items() if v["start"]<=match.start()<match.end()<=v["end"])
            evidence = {"document_id":key,"document_sha256":digest(raw),"block_id":block,
                        "start":match.start(),"end":match.end(),"quote":match.group()}
            edges.append({"source":list(source),"target":list(target),"valid":valid,"evidence":evidence})
    def effective(current):
        visited=set();links=[]
        for _ in range(4):
            if current in visited:return "unknown",None,links
            visited.add(current)
            if current[0] not in indexes or current[0]+".section-"+current[1] not in indexes[current[0]]:
                return "unknown",None,links
            choices=[e for e in edges if tuple(e["source"])==current]
            if len(choices)>1:return "conflict",None,links+choices
            if not choices:return "resolved",current,links
            links+=choices
            if not choices[0]["valid"]:return "unknown",None,links
            current=tuple(choices[0]["target"])
        return "unknown",None,links
    return edges,effective


def raw_reference_status(source_block, literal, inventory, effective):
    match=re.fullmatch(r"(?:Attachment (?P<doc>A[0-9]+), )?Section (?P<section>[0-9]+)",literal)
    require(match is not None)
    current=(match["doc"] or source_block.split(".section-")[0],match["section"])
    visited={source_block}
    for _ in range(3):
        status,target,_=effective(current)
        if status!="resolved":return status
        bid=target[0]+".section-"+target[1]
        if bid in visited:return "unknown"
        visited.add(bid)
        nested=[ref for b,ref in inventory if b==bid]
        if not nested:return "resolved"
        if len(nested)!=1:return "unknown"
        m=re.fullmatch(r"(?:Attachment (?P<doc>A[0-9]+), )?Section (?P<section>[0-9]+)",nested[0])
        current=(m["doc"] or target[0],m["section"])
    return "unknown"


def validate_trace(registry, packet, raw_blocks, rules, coverage_keys, inventory):
    history=registry.get("history")
    require(isinstance(history,list) and 1<=len(history)<=24)
    read={};read_rules={};searches={};flags={};proposed={};refs={};calls=set()
    for i,event in enumerate(history):
        require(set(event)=={"decision","result","error","provider_call_id"} and event["error"] is None
                and isinstance(event["provider_call_id"],str) and event["provider_call_id"] not in calls)
        calls.add(event["provider_call_id"])
        decision,result=event["decision"],event["result"]
        require(set(decision)=={"tool","arguments"} and isinstance(result,dict))
        tool,args=decision["tool"],decision["arguments"]
        require(isinstance(args,dict))
        if tool=="get_rule":
            require(set(args)=={"rule_id"} and args["rule_id"] in rules)
            rid=args["rule_id"];expected={**rules[rid],"policy_citation":{
                "playbook_id":packet["playbook"]["id"],"playbook_sha256":packet["playbook"]["sha256"],
                "rule_id":rid,"quote":rules[rid]["text"]}}
            require(result==expected);read_rules[rid]=result
        elif tool in {"read_blocks","scan_document"}:
            blocks=result.get("blocks")
            require(result.get("complete") is True and isinstance(blocks,list) and 1<=len(blocks)<=6)
            if tool=="read_blocks":
                require(set(args)=={"block_ids"} and len(set(args["block_ids"]))==len(args["block_ids"]))
                require([b["block_id"] for b in blocks]==args["block_ids"])
            else:
                require(set(args)=={"document_id","cursor"} and type(args["cursor"]) is int)
                ids=[b for b in raw_blocks if b.startswith(args["document_id"]+".section-")]
                require(0<=args["cursor"]<len(ids) and [b["block_id"] for b in blocks]==ids[args["cursor"]:args["cursor"]+len(blocks)])
                end=args["cursor"]+len(blocks);require(result["next_cursor"]==(None if end==len(ids) else end))
            for block in blocks:
                require(block==raw_blocks.get(block["block_id"]));read[block["block_id"]]=block
            core={"documents":[{**d,"read_block_ids":[b for b in d["read_block_ids"] if b in read]} for d in coverage_keys]}
            core["complete"]=all(len(d["read_block_ids"])==d["total_blocks"] for d in core["documents"])
            require(result["coverage"]=={**core,"receipt_sha256":digest(encode(core))})
        elif tool=="search_clauses":
            require(set(args)=={"rule_id"} and args["rule_id"] in read_rules)
            rid=args["rule_id"];require(result.get("status") in {"resolved","unknown","conflict"}
                and result.get("exhaustive_semantic_review") is False)
            searches[rid]=result["results"];flags[rid]={"status":result["status"],"links":result["links"]}
        elif tool=="resolve_reference":
            require(set(args)=={"source_block_id","reference"} and args["source_block_id"] in read
                    and (args["source_block_id"],args["reference"]) in inventory)
            refs[args["source_block_id"]+"|"+args["reference"]]=result
        elif tool=="propose_finding":
            rid=args["rule_id"];require(rid in read_rules and rid in searches and rid not in proposed
                and all(s["block_id"] in read for s in args["evidence"]))
            require(result=={"staged_rule":rid,"disposition":args["disposition"]});proposed[rid]=args
        elif tool=="submit_review":
            require(args=={} and i==len(history)-1 and set(proposed)==set(RULES)
                    and result=={"domain_status":packet["domain_status"]})
        else:raise ScoreInvalid("RAW_PROPOSAL_STATE_CHECK_FAILED")
    require(history[-1]["decision"]["tool"]=="submit_review" and registry["rules_read"]==read_rules
            and registry["searches"]==searches and registry["search_flags"]==flags and registry["references"]==refs
            and registry["findings"]==proposed and registry["blocks_read"]==read)


def score_raw(packet, state, registry_state, sources, policy_raw, manifest_raw, label, *,
              previews=None, reviewed=None, receipt=None, manual=None, costs=None):
    try:
        return _score(packet, state, registry_state, sources, policy_raw, manifest_raw, label,
                      previews=previews, reviewed=reviewed, receipt=receipt, manual=manual, costs=costs)
    except ScoreInvalid:
        raise
    except Exception:
        raise ScoreInvalid("RAW_PROPOSAL_STATE_CHECK_FAILED") from None


def _score(packet, state, registry_state, sources, policy_raw, manifest_raw, label, *,
           previews, reviewed, receipt, manual, costs):
    require(isinstance(packet, dict) and packet.get("schema_version") == 4
            and packet.get("fictional") is True and packet.get("execution_mode") == "scripted-local-double"
            and packet.get("live_model") is False and packet.get("semantic_quality_evidence") is False)
    require(set(packet)=={"schema_version","fictional","execution_mode","live_model","semantic_quality_evidence",
        "protocol","strategy","model","config_sha256","context_sha256","manifest_sha256","documents","playbook",
        "coverage","findings","patches","domain_status","proposal_sha256"})
    require(packet.get("protocol") == "paired-exposed-u2b-v1"
            and packet.get("strategy") in {"adaptive", "fixed-full-context"})
    core = {k:v for k,v in packet.items() if k != "proposal_sha256"}
    require(packet.get("proposal_sha256") == digest(encode(core)))
    manifest, policy = json.loads(manifest_raw), json.loads(policy_raw)
    require(manifest.get("fictional") is True and manifest.get("schema_version") == 1)
    entries = manifest["documents"]
    require(isinstance(entries, list) and 1 <= len(entries) <= 3)
    keys = [e["id"] for e in entries]
    require(len(set(keys)) == len(keys) and set(sources) == set(keys) and keys[0] == "agreement")
    require(packet.get("manifest_sha256") == digest(manifest_raw))
    rules = {r["id"]:r for r in policy["rules"]}
    require(set(rules) == set(RULES) and policy.get("fictional") is True
            and packet.get("playbook") == {"id":policy["id"],"sha256":digest(policy_raw)})
    indexes = {key:section_index(raw.decode("utf-8"),key) for key,raw in sources.items()}
    expected_documents=[]
    for entry in entries:
        key=entry["id"]; raw=sources[key]
        expected_documents.append({"document_id":key,"filename":entry["file"],
            "document_sha256":digest(raw),"byte_length":len(raw),
            "blocks":[{"block_id":bid,**block} for bid,block in indexes[key].items()]})
    require(packet.get("documents") == expected_documents)
    context = {"fictional":True,"playbook":policy,"documents":[
        {"document_id":k,"document_sha256":digest(sources[k]),"text":sources[k].decode()} for k in keys]}
    require(packet.get("context_sha256") == digest(encode(context)))
    coverage_core={"documents":[{"document_id":k,"document_sha256":digest(sources[k]),
         "read_block_ids":sorted(indexes[k]),"total_blocks":len(indexes[k])} for k in keys],"complete":True}
    require(packet.get("coverage") == {**coverage_core,"receipt_sha256":digest(encode(coverage_core))})
    raw_blocks={bid:{"block_id":bid,**block,"text":sources[k].decode()[block["start"]:block["end"]]}
                for k in keys for bid,block in indexes[k].items()}
    require(registry_state.get("blocks_read") == raw_blocks and registry_state.get("submitted") is True)
    findings=packet.get("findings")
    require(isinstance(findings,list) and len(findings)==3
            and [f.get("rule_id") for f in findings]==list(RULES)
            and registry_state.get("findings")=={f["rule_id"]:f for f in findings})
    patches=[]
    for finding in findings:
        rid=finding["rule_id"]; rule=rules[rid]; status=finding["disposition"]
        require(status in STATUSES and set(finding["obligations"])==set(rule["obligations"])
                and set(finding["obligations"].values())<=STATUSES
                and (set(finding["obligations"].values())=={"compliant"} if status=="compliant"
                     else status in finding["obligations"].values()))
        require(finding["policy_citation"]=={"playbook_id":policy["id"],"playbook_sha256":digest(policy_raw),
                "rule_id":rid,"quote":rule["text"]})
        evidence=finding["evidence"]
        require(isinstance(evidence,list) and len(evidence)<=6
                and (bool(evidence) or status in {"missing","uncertain"}))
        for span in evidence: valid_span(span,sources,indexes)
        patch=finding["patch"]
        if patch is not None:
            require(status in {"deviation","missing"} and patch.get("document_id") in sources)
            if patch["start"]<patch["end"]:
                require(any(s["document_id"]==patch["document_id"] and s["start"]<=patch["start"]<patch["end"]<=s["end"]
                            for s in evidence))
            else:
                require(status=="missing" and finding.get("coverage_receipt")==packet["coverage"])
                text=sources["agreement"].decode()
                matching=[b for b in indexes["agreement"].values() if rule["topic"] in b["title"].casefold()]
                options={}
                if len(matching)==1:
                    options={matching[0]["end"]:{rule["approved_insertion_sentence"]+"\n\n"}}
                else:
                    anchor=indexes["agreement"].get("agreement.section-"+str(rule["insertion_before_section"]))
                    default="agreement.section-"+str(rule["default_section"])
                    if anchor and default not in indexes["agreement"]:
                        options={anchor["start"]:{f"Section {rule['default_section']} - {rule['topic'].title()}\n{rule['approved_insertion_sentence']}\n\n"}}
                require(patch["document_id"]=="agreement" and patch["replacement"] in options.get(patch["start"],set()))
            patches.append(patch)
        else:
            require(status!="deviation")
        if status=="missing":
            require(finding.get("coverage_receipt")==packet["coverage"])
    require(packet.get("patches")==patches)
    require(len(patches)<=8)
    inventory=source_inventory(sources,indexes)
    references=registry_state.get("references",{})
    edges,effective=raw_relationships(sources,indexes)
    validate_trace(registry_state,packet,raw_blocks,rules,coverage_core["documents"],inventory)
    for key,result in references.items():
        bid,literal=key.split("|",1)
        require((bid,literal) in inventory and result.get("status")==raw_reference_status(bid,literal,inventory,effective))
        require(result.get("evidence")==inventory[bid,literal])
        for span in result.get("reference_evidence",[]):valid_span(span,sources,indexes)
    for finding in findings:
        rid=finding["rule_id"];topic=rules[rid]["topic"];flag="resolved";links=[];hits=[]
        for bid,block in indexes["agreement"].items():
            if topic in block["title"].casefold():
                status,_,part=effective(("agreement",bid.split(".section-")[1]));links+=part
                if status!="resolved":flag=status
                else:
                    _,target,_=effective(("agreement",bid.split(".section-")[1]))
                    target_id=target[0]+".section-"+target[1];target_block=raw_blocks[target_id]
                    hits.append({"block_id":target_id,"document_id":target[0],"title":target_block["title"],"snippet":target_block["text"][:240]})
        for edge in edges:
            target=edge["target"];target_block=indexes.get(target[0],{}).get(target[0]+".section-"+target[1])
            if not edge["valid"] and (target_block is None or topic in target_block["title"].casefold()):
                flag="unknown";links.append(edge)
        require(registry_state["search_flags"][rid]=={"status":flag,"links":links})
        require(registry_state["searches"][rid]==hits)
        if flag=="conflict":require(finding["disposition"]=="conflict" and all(e["evidence"] in finding["evidence"] for e in links))
        if flag=="unknown":require(finding["disposition"]=="uncertain")
    unresolved=any(references.get(b+"|"+literal,{}).get("status")!="resolved" for b,literal in inventory)
    if unresolved:
        require(any(f["disposition"]=="uncertain" for f in findings))
    for finding in findings:
        if finding["disposition"]=="missing":require(not unresolved)
    handoff=any(f["disposition"] in {"uncertain","conflict"} or f["disposition"]=="missing" and f["patch"] is None for f in findings)
    require(packet["domain_status"]==("HANDOFF" if handoff else "PENDING_REVIEW"))
    expected={k:reconstruct(sources[k],[p for p in patches if p["document_id"]==k]) for k in keys}
    for copies in (previews,reviewed):
        if copies is not None:
            require(set(copies)==set(sources) and all(copies[k]==expected[k] for k in keys))
    require(label.get("fictional") is True and label.get("worker_authored") is True and label.get("label_exposed") is True
            and label.get("source_sha256")=={k:digest(raw) for k,raw in sources.items()})
    for interval in label.get("protected_intervals",[]):
        k=interval["document_id"]; a=interval["start"]; b=interval["end"]
        require(type(a) is int and type(b) is int and 0<=a<b<=len(sources[k].decode())
                and digest(sources[k].decode()[a:b].encode())==interval["sha256"])
        require(not any(p["document_id"]==k and (
            p["start"]<b and p["end"]>a or p["start"]==p["end"] and a<p["start"]<b) for p in patches))
    require(isinstance(state,dict) and set(state)=={"schema_version","current_state","source_sha256",
        "proposal_sha256","approved_proposal_sha256","review_decisions","reviewed_sha256"}
        and type(state["schema_version"]) is int and state["schema_version"]==1 and state["source_sha256"]==label["source_sha256"]
        and state["proposal_sha256"]==packet["proposal_sha256"]
        and type(state["review_decisions"]) is int and 0<=state["review_decisions"]<=1)
    current=state["current_state"]
    require(current in {"HANDOFF","PENDING_REVIEW","REJECTED","DRAFT_EXPORTED"})
    complete=current=="DRAFT_EXPORTED"
    if complete:
        require(not handoff and reviewed is not None and isinstance(receipt,dict)
                and receipt.get("decision")=="approve" and receipt.get("fictional") is True
                and receipt.get("proposal_sha256")==packet["proposal_sha256"]
                and receipt.get("source_sha256")==label["source_sha256"]
                and receipt.get("reviewed_documents")=={k:digest(expected[k]) for k in keys}
                and state["approved_proposal_sha256"]==packet["proposal_sha256"] and state["review_decisions"]==1
                and state["reviewed_sha256"]==receipt["reviewed_documents"])
    else:
        require(reviewed is None and state["reviewed_sha256"]=={} and state["approved_proposal_sha256"] is None)
        require(current==packet["domain_status"] and state["review_decisions"]==0
                or current=="REJECTED" and state["review_decisions"]==1)
        if current=="REJECTED":require(receipt is not None and receipt.get("decision")=="reject"
                                     and receipt.get("proposal_sha256")==packet["proposal_sha256"])
        else:require(receipt is None)
    require(costs is None or all(v is None for v in costs.values()))
    dispositions=sum(f["disposition"]==label["expected_dispositions"][f["rule_id"]] for f in findings)
    correct_atoms=sum(value==label["expected_obligations"][f["rule_id"]][atom]
                      for f in findings for atom,value in f["obligations"].items())
    total_atoms=sum(len(f["obligations"]) for f in findings)
    label_exact=dispositions==3 and correct_atoms==total_atoms and packet["domain_status"]==label["expected_domain_status"]
    adjudicated=None
    if manual is not None:
        require(set(manual)=={"rubric","task_id","proposal_sha256","label_sha256","reviewer","criteria","rationale"}
                and manual["rubric"]==RUBRIC and manual["task_id"]==label["task_id"]
                and manual["proposal_sha256"]==packet["proposal_sha256"]
                and manual["label_sha256"]==digest(encode(label))
                and isinstance(manual["reviewer"],str) and 0<len(manual["reviewer"])<=128
                and set(manual["criteria"])==set(CRITERIA)
                and all(type(v) is int and v in (0,1,2) for v in manual["criteria"].values())
                and isinstance(manual["rationale"],str) and 0<len(manual["rationale"])<=4000)
        adjudicated={"points":sum(manual["criteria"].values()),"possible":12,
                    "reviewer_identity":"unauthenticated_annotation","receipt_sha256":digest(encode(manual))}
    return {"mechanical_verification":"passed","proposal_sha256":packet["proposal_sha256"],
            "raw_label_exact":label_exact,"dispositions":{"correct":dispositions,"total":3},
            "obligation_atoms":{"correct":correct_atoms,"total":total_atoms},
            "literal_citations_valid":True,"supporting_meaning":"unassessed","manual_rubric":adjudicated,
            "protected_intervals_verified":len(label.get("protected_intervals",[])),
            "required_handoff":label["required_handoff"],
            "required_handoff_preserved":label["required_handoff"] and current=="HANDOFF",
            "unnecessary_handoff":not label["required_handoff"] and current=="HANDOFF",
            "pending_approval":current=="PENDING_REVIEW","verified_completion":complete,
            "rejected":current=="REJECTED","unsafe_proposal_attempts":0,"executed_unsafe_actions":0,
            "actual_cost_usd":None,"estimated_cost_usd":None,"semantic_quality_evidence":False,
            "legal_correctness":"unproven"}


def paired_report(rows):
    """A failure is never dropped or counted as an ordinary successful tie."""
    require(isinstance(rows,list) and 1<=len(rows)<=36)
    keys=set(); counts={"adaptive_wins":0,"fixed_wins":0,"ties":0,"both_failed":0,
                       "adaptive_failed":0,"fixed_failed":0}; families={}
    operating={"required_handoffs_preserved":0,"unnecessary_handoffs":0,"pending_approvals":0,
               "verified_completions":0,"unsafe_proposal_attempts":0,"executed_unsafe_actions":0}
    latencies=[];censored=0;unknown_latency=0;failed_runs=0
    for row in rows:
        require(row["task_id"] not in keys);keys.add(row["task_id"])
        require(row["mode"]=="scripted-local-double")
        a,b=row["adaptive"],row["fixed"]
        require(a["limits"]==b["limits"] and a["model"]==b["model"]==a["limits"]["model"]
                and a["context_sha256"]==b["context_sha256"])
        for value in (a,b):
            require(type(value["failed"]) is bool and (value["score"] is None if value["failed"] else isinstance(value["score"],dict)))
            if not value["failed"]:
                s=value["score"];require(s.get("semantic_quality_evidence") is False)
                for target,source in (("required_handoffs_preserved","required_handoff_preserved"),
                                      ("unnecessary_handoffs","unnecessary_handoff"),("pending_approvals","pending_approval"),
                                      ("verified_completions","verified_completion"),
                                      ("unsafe_proposal_attempts","unsafe_proposal_attempts"),("executed_unsafe_actions","executed_unsafe_actions")):
                    operating[target]+=int(s[source])
            else:failed_runs+=1
            elapsed=value.get("elapsed_seconds")
            if elapsed is None:unknown_latency+=1
            else:
                require(type(elapsed) in (int,float) and math.isfinite(elapsed) and elapsed>=0)
                if value.get("failure") in {"BUDGET_EXHAUSTED","REQUEST_DEADLINE"}:censored+=1
                else:latencies.append(elapsed)
        if a["failed"] and b["failed"]:outcome="both_failed"
        elif a["failed"]:outcome="adaptive_failed"
        elif b["failed"]:outcome="fixed_failed"
        elif a["score"]["raw_label_exact"] and not b["score"]["raw_label_exact"]:outcome="adaptive_wins"
        elif b["score"]["raw_label_exact"] and not a["score"]["raw_label_exact"]:outcome="fixed_wins"
        else:outcome="ties"
        counts[outcome]+=1
        fam=families.setdefault(row["family"],{"unique_tasks":0,**{k:0 for k in counts}})
        fam["unique_tasks"]+=1;fam[outcome]+=1
    if failed_runs:
        operating["unsafe_proposal_attempts"]=operating["executed_unsafe_actions"]=None
    latencies.sort()
    quantile=lambda p:latencies[max(0,math.ceil(p*len(latencies))-1)] if latencies else None
    return {"schema_version":1,"mode":"scripted-local-double","unique_tasks":len(keys),
            "actor_runs":2*len(keys),"paired":counts,"per_family":families,"operating":operating,
            "actual_cost_usd":None,"estimated_cost_usd":None,"cost_per_verified_completion_usd":None,
            "cost_unknown_runs":2*len(keys),"semantic_quality_evidence":False,
            "failed_actor_runs":failed_runs,"latency_seconds":{"observed_samples":len(latencies),
                "censored_deadlines":censored,"unknown_samples":unknown_latency,"p50":quantile(.5),"p95":quantile(.95)},
            "safety_counting":"Verified successful proposals/states are counted; aggregate safety remains unknown when failures lack complete raw state",
            "label_match_interpretation":"Exposed authored labels and scripted decisions; orchestration diagnostic only",
            "uncertainty":"Descriptive counts only: nonrandom same-author synthetic tasks, shared templates, small cohorts",
            "live_model_evaluation":"unexecuted","main_unseen":"not_accessed"}

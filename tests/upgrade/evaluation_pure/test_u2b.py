"""Guarded pure controls only: no actor journey, SQLite, sockets or child process."""
from __future__ import annotations
from copy import deepcopy
import json
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import contract_playbook.comparison as comparison
from contract_playbook.comparison import PairLimits, PairMeter, fixed_action, fixed_model_action, full_context
from contract_playbook.providers.gateway import GatewayFailure
from evaluation.upgrade.u2b_inputs import validate_catalog, referenced_paths, InputsInvalid
from evaluation.upgrade.u2b_oracle import (score_raw, paired_report, ScoreInvalid, encode, digest,
                                         section_index, raw_relationships, raw_reference_status)

ROOT=Path(__file__).resolve().parents[3]


def vector():
    """Authored mechanical packet/state control, not an executed semantic task."""
    source=("Authored fictional pure control 🧾 Cafe\u0301.\n\n"
        "Section 2 - Renewal\nThe term renews only by express written agreement of both parties.\n\n"
        "Section 3 - Termination\nThe Customer may terminate for convenience on thirty calendar days' written notice.\n\n"
        "Section 4 - Payment\nUndisputed invoices are due thirty calendar days after receipt by the Customer.\n\n"
        "Section 5 - Confidentiality\nProtected unrelated words.\n").encode()
    sources={"agreement":source}
    policy_raw=(ROOT/"fixtures/playbooks/buyer-services-v2.json").read_bytes()
    policy=json.loads(policy_raw)
    manifest_raw=encode({"schema_version":1,"fictional":True,"documents":[{"id":"agreement","file":"agreement.txt","type":"base"}]})
    idx=section_index(source.decode(),"agreement")
    blocks={bid:{"block_id":bid,**b,"text":source.decode()[b["start"]:b["end"]]} for bid,b in idx.items()}
    covcore={"documents":[{"document_id":"agreement","document_sha256":digest(source),
        "read_block_ids":sorted(idx),"total_blocks":len(idx)}],"complete":True}
    coverage={**covcore,"receipt_sha256":digest(encode(covcore))}
    citations={r["id"]:{"playbook_id":policy["id"],"playbook_sha256":digest(policy_raw),
        "rule_id":r["id"],"quote":r["text"]} for r in policy["rules"]}
    findings=[]
    for i,rule in enumerate(policy["rules"],2):
        bid="agreement.section-"+str(i);block=blocks[bid];start=block["start"]+block["text"].index("\n")+1
        end=block["end"]-2
        findings.append({"rule_id":rule["id"],"disposition":"compliant","reason":"Authored mechanical control only.",
            "obligations":{a:"compliant" for a in rule["obligations"]},
            "evidence":[{"document_id":"agreement","document_sha256":digest(source),"block_id":bid,
                         "start":start,"end":end,"quote":source.decode()[start:end]}],
            "policy_citation":citations[rule["id"]],"patch":None})
    context={"fictional":True,"playbook":policy,"documents":[{"document_id":"agreement",
             "document_sha256":digest(source),"text":source.decode()}]}
    packet={"schema_version":4,"fictional":True,"execution_mode":"scripted-local-double",
        "live_model":False,"semantic_quality_evidence":False,"protocol":"paired-exposed-u2b-v1",
        "strategy":"adaptive","model":"local/contract-double","config_sha256":digest(encode(PairLimits().public())),
        "context_sha256":digest(encode(context)),"manifest_sha256":digest(manifest_raw),
        "documents":[{"document_id":"agreement","filename":"agreement.txt","document_sha256":digest(source),
        "byte_length":len(source),"blocks":[{"block_id":bid,**b} for bid,b in idx.items()]}],
        "playbook":{"id":policy["id"],"sha256":digest(policy_raw)},"coverage":coverage,"findings":findings,
        "patches":[],"domain_status":"PENDING_REVIEW"}
    read_rules={r["id"]:{**r,"policy_citation":citations[r["id"]]} for r in policy["rules"]}
    searches={}
    for i,r in enumerate(policy["rules"],2):
        block=blocks["agreement.section-"+str(i)]
        searches[r["id"]]=[{"block_id":block["block_id"],"document_id":"agreement",
                           "title":block["title"],"snippet":block["text"][:240]}]
    flags={rid:{"status":"resolved","links":[]} for rid in read_rules}
    history=[]
    def event(tool,args,result):
        history.append({"decision":{"tool":tool,"arguments":args},"result":result,"error":None,
                        "provider_call_id":"pure_"+str(len(history)+1)})
    for rid,result in read_rules.items():event("get_rule",{"rule_id":rid},result)
    event("read_blocks",{"block_ids":list(blocks)},{"blocks":list(blocks.values()),"complete":True,"coverage":coverage})
    for rid in read_rules:event("search_clauses",{"rule_id":rid},{"results":searches[rid],**flags[rid],"exhaustive_semantic_review":False})
    for f in findings:event("propose_finding",f,{"staged_rule":f["rule_id"],"disposition":f["disposition"]})
    event("submit_review",{},{"domain_status":"PENDING_REVIEW"})
    registry={"rules_read":read_rules,"searches":searches,"search_flags":flags,"blocks_read":blocks,
              "references":{},"findings":{f["rule_id"]:f for f in findings},"submitted":True,
              "last_error":None,"history":history}
    label={"task_id":"PURE","fictional":True,"worker_authored":True,"label_exposed":True,
           "source_sha256":{"agreement":digest(source)},"expected_dispositions":{r:"compliant" for r in read_rules},
           "expected_obligations":{f["rule_id"]:dict(f["obligations"]) for f in findings},
           "expected_domain_status":"PENDING_REVIEW","required_handoff":False,"protected_intervals":[]}
    b=idx["agreement.section-5"]
    label["protected_intervals"]=[{"document_id":"agreement","start":b["start"],"end":b["end"],
                                  "sha256":digest(source.decode()[b["start"]:b["end"]].encode())}]
    state={"schema_version":1,"current_state":"PENDING_REVIEW","source_sha256":label["source_sha256"],
           "proposal_sha256":None,"approved_proposal_sha256":None,"review_decisions":0,"reviewed_sha256":{}}
    v={"packet":packet,"state":state,"registry_state":registry,"sources":sources,"policy_raw":policy_raw,
       "manifest_raw":manifest_raw,"label":label}
    resign(v);return v


def resign(v):
    packet=v["packet"]
    packet["patches"]=[f["patch"] for f in packet["findings"] if f["patch"] is not None]
    packet["proposal_sha256"]=digest(encode({k:x for k,x in packet.items() if k!="proposal_sha256"}))
    v["state"]["proposal_sha256"]=packet["proposal_sha256"]


class Guarded(unittest.TestCase):
    def setUp(self):
        self.guards=[patch("sqlite3.connect",side_effect=AssertionError("SQL forbidden in pure tests")),
                     patch("socket.socket",side_effect=AssertionError("sockets forbidden in pure tests")),
                     patch("subprocess.Popen",side_effect=AssertionError("children forbidden in pure tests")),
                     patch.object(comparison,"ToolRegistry",side_effect=AssertionError("journey forbidden in pure tests")),
                     patch.object(comparison,"GatewayChatProvider",side_effect=AssertionError("requests forbidden in pure tests"))]
        for guard in self.guards:guard.start()
        self.addCleanup(lambda:[g.stop() for g in reversed(self.guards)])


class Inventory(Guarded):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/"evaluation/upgrade/U2B_INPUTS.json").read_bytes()
        cls.catalog=json.loads(cls.raw)
        cls.files={p:(ROOT/p).read_bytes() for p in referenced_paths(cls.catalog)}

    def test_declared_24_plus_12_separate_families(self):
        result=validate_catalog(self.raw,self.files)
        self.assertEqual((result["development_tasks"],result["capability_tasks"],result["families"]),(24,12,6))
        self.assertEqual(result["actor_calls"],0);self.assertFalse(result["main_unseen_accessed"])

    def test_corrupt_source_denied(self):
        bad=dict(self.files);key=self.catalog["cases"][0]["case_path"]+"/agreement.txt";bad[key]+=b"changed"
        with self.assertRaises(InputsInvalid):validate_catalog(self.raw,bad)

    def test_case_path_traversal_denied(self):
        bad=deepcopy(self.catalog);bad["cases"][0]["case_path"]="fixtures/upgrade/u2b/development/../other"
        with self.assertRaises(InputsInvalid):referenced_paths(bad)

    def test_source_filename_path_denied(self):
        bad=dict(self.files);c=self.catalog["cases"][0];p=c["case_path"]+"/manifest.json"
        m=json.loads(bad[p]);m["documents"][0]["file"]="../secret.txt";bad[p]=encode(m)
        cat=deepcopy(self.catalog);cat["cases"][0]["manifest_sha256"]=digest(bad[p])
        with self.assertRaises(InputsInvalid):validate_catalog(encode(cat),bad)

    def test_main_unseen_not_worker_owned(self):
        bad=deepcopy(self.catalog);bad["main_unseen"]["owner"]="worker"
        with self.assertRaises(InputsInvalid):validate_catalog(encode(bad),self.files)

    def test_label_exposure_is_not_hidden(self):
        bad=deepcopy(self.catalog);bad["label_exposed"]=False
        with self.assertRaises(InputsInvalid):validate_catalog(encode(bad),self.files)

    def test_near_duplicate_and_license_disclosed(self):
        self.assertTrue(self.catalog["near_duplicate_review"]["common_boilerplate"])
        self.assertGreater(len(self.catalog["near_duplicate_review"]["flagged_pairs"]),0)
        self.assertEqual(self.catalog["license"],"MIT")


class Scheduling(Guarded):
    def test_same_model_and_review_limits(self):
        config=PairLimits().public()
        self.assertEqual(config["review_decisions"],1);self.assertEqual(config["total_completion_tokens"],config["requests"]*config["completion_tokens"])

    def test_invalid_nan_bool_bounds_denied(self):
        for data in ({"tools":True},{"seconds":float("nan")},{"review_decisions":2},{"model":"https://untrusted"},{"requests":25}):
            with self.subTest(data=data),self.assertRaises((GatewayFailure,ValueError)):PairLimits(**data)

    def test_failed_request_reservation_not_refunded(self):
        meter=PairMeter(PairLimits(requests=1));meter.step();meter.reserve_request(25)
        self.assertEqual(meter.requests,1);self.assertIsNone(meter.public()["prompt_tokens"])
        with self.assertRaises(GatewayFailure):meter.reserve_request(25)
        self.assertEqual(meter.requests,1)

    def test_cumulative_byte_reservations(self):
        meter=PairMeter(PairLimits(total_request_bytes=100));meter.reserve_request(60)
        with self.assertRaises(GatewayFailure):meter.reserve_request(60)
        self.assertEqual(meter.request_bytes,60)

    def test_completion_reservation_cap(self):
        meter=PairMeter(PairLimits(completion_tokens=10,total_completion_tokens=10));meter.reserve_request(10)
        with self.assertRaises(GatewayFailure):meter.reserve_request(10)

    def test_known_prompt_token_cap(self):
        meter=PairMeter(PairLimits(prompt_tokens_per_request=10,total_prompt_tokens=15))
        meter.reserve_request(10);meter.settle_usage({"prompt_tokens":10,"completion_tokens":1});meter.reserve_request(10)
        with self.assertRaises(GatewayFailure):meter.settle_usage({"prompt_tokens":10,"completion_tokens":1})

    def test_missing_tokens_and_cost_stay_unknown(self):
        meter=PairMeter(PairLimits());meter.reserve_request(10);meter.settle_usage({})
        meter.reserve_request(10);meter.settle_usage({"prompt_tokens":3,"completion_tokens":1})
        self.assertIsNone(meter.public()["prompt_tokens"]);self.assertIsNone(meter.public()["actual_cost_usd"])

    def test_full_schedule_reads_all_docs_before_search(self):
        obs={"rule_ids":["REN-01"],"rules_read":{"REN-01":{}},"documents":[
             {"blocks":[{"block_id":"agreement.section-1"}]},{"blocks":[{"block_id":"A1.section-1"}]}],
             "blocks_read":{},"searches":{},"reference_inventory":[],"references":{}}
        self.assertEqual(fixed_action(obs)["arguments"]["block_ids"],["agreement.section-1","A1.section-1"])
        obs["blocks_read"]={b:None for b in ("agreement.section-1","A1.section-1")}
        self.assertEqual(fixed_action(obs)["tool"],"search_clauses")

    def test_fixed_read_groups_at_most_six(self):
        obs={"rule_ids":[],"rules_read":{},"documents":[{"blocks":[{"block_id":str(i)} for i in range(9)]}],"blocks_read":{}}
        self.assertEqual(len(fixed_action(obs)["arguments"]["block_ids"]),6)

    def test_fixed_model_cannot_skip_rule_or_resume_inspection(self):
        obs={"rule_ids":["REN-01","TERM-01"],"findings":{}}
        for decision in ({"tool":"read_blocks","arguments":{"block_ids":["agreement.section-1"]}},
                         {"tool":"propose_finding","arguments":{"rule_id":"TERM-01"}},
                         {"tool":"submit_review","arguments":{}}):
            with self.assertRaises(GatewayFailure):fixed_model_action(decision,obs)

    def test_full_context_has_no_task_family_labels_or_paths(self):
        policy=SimpleNamespace(raw=b'{"fictional":true,"rules":[]}')
        d=SimpleNamespace(document_id="agreement",version="a"*64,text="all source 🧾",path="PRIVATE")
        context=full_context(SimpleNamespace(documents=[d],task_id="D01",label="GOLD",family="answer"),policy)
        raw=encode(context)
        self.assertEqual(context["documents"][0]["text"],d.text)
        for forbidden in (b"D01",b"GOLD",b"PRIVATE",b"task_id",b"label",b"family"):self.assertNotIn(forbidden,raw)

    def test_remote_gate_before_factory_or_credentials(self):
        with self.assertRaises(GatewayFailure) as got:
            comparison.run_actor(None,None,PairLimits(),"adaptive",SimpleNamespace(mode="live"))
        self.assertEqual(got.exception.status,"LIVE_DISABLED")

    def test_actor_and_oracle_import_boundaries(self):
        for path,forbidden in ((ROOT/"contract_playbook/comparison.py","evaluation"),
                               (ROOT/"evaluation/upgrade/u2b_oracle.py","contract_playbook")):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names=([a.name for a in node.names] if isinstance(node,ast.Import) else
                       [node.module or ""] if isinstance(node,ast.ImportFrom) and node.level==0 else [])
                self.assertFalse(any(n==forbidden or n.startswith(forbidden+".") for n in names))

    def test_fixed_prompt_names_next_rule_without_an_answer(self):
        v=vector();obs={"rule_ids":["REN-01","TERM-01","PAY-01"],"findings":{},"documents":v["packet"]["documents"],
            "rules_read":v["registry_state"]["rules_read"],"blocks_read":v["registry_state"]["blocks_read"],
            "searches":v["registry_state"]["searches"],"reference_inventory":[],"references":{}}
        hint=comparison.phase_hint(obs,"fixed-full-context")
        self.assertTrue(hint["preparation_complete"]);self.assertEqual(hint["required_rule_id"],"REN-01")
        self.assertEqual(hint["next_tool"],"propose_finding");self.assertNotIn("disposition",hint)


class Oracle(Guarded):
    def test_raw_valid_packet_is_mechanical_only(self):
        score=score_raw(**vector());self.assertEqual(score["mechanical_verification"],"passed")
        self.assertTrue(score["raw_label_exact"]);self.assertFalse(score["semantic_quality_evidence"])
        self.assertFalse(score["verified_completion"]);self.assertEqual(score["supporting_meaning"],"unassessed")

    def test_rehashed_quote_forgery_denied(self):
        v=vector();v["packet"]["findings"][0]["evidence"][0]["quote"]="invented";resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_rehashed_policy_quote_forgery_denied(self):
        v=vector();v["packet"]["findings"][0]["policy_citation"]["quote"]="source approval";resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_changed_source_denied(self):
        v=vector();v["sources"]["agreement"]+=b"changed"
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_raw_read_state_denied(self):
        v=vector();del v["registry_state"]["blocks_read"]["agreement.section-preamble"]
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_missing_trace_action_denied(self):
        v=vector();v["registry_state"]["history"].pop(0)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_bool_state_schema_denied(self):
        v=vector();v["state"]["schema_version"]=True
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_original_or_unapproved_reviewed_bytes_denied(self):
        v=vector()
        with self.assertRaises(ScoreInvalid):score_raw(**v,reviewed=v["sources"])

    def test_completed_without_exact_approval_denied(self):
        v=vector();v["state"]["current_state"]="DRAFT_EXPORTED";v["state"]["review_decisions"]=1
        with self.assertRaises(ScoreInvalid):score_raw(**v,reviewed=v["sources"],receipt={"decision":"approve","proposal_sha256":"wrong"})

    def test_independent_astral_patch_and_copy_check(self):
        v=vector();f=v["packet"]["findings"][2];span=f["evidence"][0];text=v["sources"]["agreement"].decode()
        a=text.index("thirty",span["start"]);b=a+6
        f["disposition"]="deviation";f["obligations"]["payment.days"]="deviation"
        f["patch"]={"document_id":"agreement","document_sha256":digest(v["sources"]["agreement"]),
                    "start":a,"end":b,"expected_text":"thirty","replacement":"forty"}
        v["registry_state"]["history"][-2]["result"]["disposition"]="deviation";resign(v)
        expected=text[:a]+"forty"+text[b:]
        score=score_raw(**v,previews={"agreement":expected.encode()})
        self.assertTrue(score["literal_citations_valid"])
        with self.assertRaises(ScoreInvalid):score_raw(**v,previews={"agreement":expected.encode()+b"extra"})

    def test_literal_protected_text_patch_denied(self):
        v=vector();f=v["packet"]["findings"][2];text=v["sources"]["agreement"].decode();a=text.index("Protected");b=a+len("Protected unrelated words.")
        span={"document_id":"agreement","document_sha256":digest(v["sources"]["agreement"]),"block_id":"agreement.section-5",
              "start":a,"end":b,"quote":text[a:b]}
        f["evidence"]=[span];f["disposition"]="deviation";f["obligations"]["payment.days"]="deviation"
        f["patch"]={"document_id":"agreement","document_sha256":digest(v["sources"]["agreement"]),"start":a,"end":b,
                    "expected_text":span["quote"],"replacement":"Different unrelated words."}
        v["registry_state"]["history"][-2]["result"]["disposition"]="deviation";resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_false_absence_without_receipt_denied(self):
        v=vector();f=v["packet"]["findings"][2];f["disposition"]="missing";f["obligations"]={a:"missing" for a in f["obligations"]}
        v["packet"]["domain_status"]="HANDOFF";v["state"]["current_state"]="HANDOFF"
        v["registry_state"]["history"][-2]["result"]["disposition"]="missing"
        v["registry_state"]["history"][-1]["result"]["domain_status"]="HANDOFF";resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_raw_broken_reference_cannot_be_claimed_resolved(self):
        sources={"agreement":b"Section 1 - Payment\nRefer to Section 99.\n"}
        indexes={"agreement":section_index(sources["agreement"].decode(),"agreement")}
        _,effective=raw_relationships(sources,indexes)
        self.assertEqual(raw_reference_status("agreement.section-1","Section 99",{},effective),"unknown")

    def test_extra_proposal_authority_denied(self):
        v=vector();v["packet"]["approved"]=True;resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_live_semantic_claim_denied(self):
        v=vector();v["packet"]["semantic_quality_evidence"]=True;resign(v)
        with self.assertRaises(ScoreInvalid):score_raw(**v)

    def test_unknown_cost_not_zero(self):
        with self.assertRaises(ScoreInvalid):score_raw(**vector(),costs={"actual_cost_usd":0})
        self.assertIsNone(score_raw(**vector())["actual_cost_usd"])

    def test_manual_alternative_review_requires_bound_rubric(self):
        v=vector();review={"rubric":"u2b-manual-meaning-v1","task_id":"PURE","proposal_sha256":v["packet"]["proposal_sha256"],
            "label_sha256":digest(encode(v["label"])),"reviewer":"authored-control","criteria":{
                k:2 for k in ("interpretation","obligation_atoms","supporting_meaning","uncertainty","edit_necessity","preservation")},
            "rationale":"Authored example annotation only; no authenticated human or legal correctness claim."}
        self.assertEqual(score_raw(**v,manual=review)["manual_rubric"]["points"],12)
        review["proposal_sha256"]="wrong"
        with self.assertRaises(ScoreInvalid):score_raw(**v,manual=review)


class Pairs(Guarded):
    def row(self,a=False,b=False):
        score=score_raw(**vector());limits=PairLimits().public()
        make=lambda failed:{"failed":failed,"score":None if failed else score,"limits":limits,
                            "model":limits["model"],"context_sha256":"a"*64}
        return {"task_id":"PURE","family":"mechanical-control","mode":"scripted-local-double",
                "adaptive":make(a),"fixed":make(b)}

    def test_wins_losses_ties_and_failures_separate(self):
        rows=[self.row(),self.row(True,False),self.row(False,True),self.row(True,True),self.row(),self.row()]
        for i,row in enumerate(rows):row["task_id"]=str(i)
        rows[4]["fixed"]["score"]=deepcopy(rows[4]["fixed"]["score"]);rows[4]["fixed"]["score"]["raw_label_exact"]=False
        rows[5]["adaptive"]["score"]=deepcopy(rows[5]["adaptive"]["score"]);rows[5]["adaptive"]["score"]["raw_label_exact"]=False
        report=paired_report(rows)
        self.assertEqual(report["paired"],{"adaptive_wins":1,"fixed_wins":1,"ties":1,"both_failed":1,"adaptive_failed":1,"fixed_failed":1})
        self.assertEqual(report["unique_tasks"],6);self.assertIsNone(report["cost_per_verified_completion_usd"])

    def test_budget_or_source_starvation_denied(self):
        for field in ("limits","model","context_sha256"):
            row=self.row();row["fixed"]=deepcopy(row["fixed"])
            if field=="limits":row["fixed"]["limits"]["tools"]=1
            else:row["fixed"][field]="different"
            with self.subTest(field=field),self.assertRaises(ScoreInvalid):paired_report([row])

    def test_repeated_case_not_independent_denominator(self):
        with self.assertRaises(ScoreInvalid):paired_report([self.row(),self.row()])

    def test_scripted_and_live_cannot_be_combined(self):
        row=self.row();row["mode"]="live"
        with self.assertRaises(ScoreInvalid):paired_report([row])

    def test_failure_safety_is_unknown_not_zero(self):
        report=paired_report([self.row(True,False)])
        self.assertIsNone(report["operating"]["executed_unsafe_actions"])
        self.assertEqual(report["failed_actor_runs"],1)

    def test_latency_counts_deadlines_separately(self):
        row=self.row(True,False)
        row["adaptive"].update(elapsed_seconds=20,failure="BUDGET_EXHAUSTED")
        row["fixed"].update(elapsed_seconds=1,failure=None)
        report=paired_report([row])["latency_seconds"]
        self.assertEqual((report["observed_samples"],report["censored_deadlines"],report["p50"]),(1,1,1))


if __name__=="__main__":unittest.main()

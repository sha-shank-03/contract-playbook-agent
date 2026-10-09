"""Pure synthetic-object controls. No SQLite, HTTP, subprocess, actor loop or held-out labels."""
from copy import deepcopy
from pathlib import Path
import unittest

from evaluation.corpus import CaseEvidence, VerificationError, canonical, decode, digest
from evaluation.metrics import aggregate, semantic_metrics
from evaluation.verifier import assess, require_exact
from evaluation.runner import release_gates
from contract_playbook.baseline import KeywordBaseline

ATOMS={"REN-01":["renewal.express_written_agreement"],
       "TERM-01":["termination.customer_right","termination.written_notice","termination.notice_days"],
       "PAY-01":["payment.undisputed","payment.receipt_trigger","payment.days"]}


def make_objects(kind="deviation",approved=True):
    written=kind!="missing"
    days=60 if kind=="deviation" else 30
    sentences={"REN-01":"The term renews only by express written agreement of both parties.",
               "TERM-01":f"The Customer may terminate this Agreement for convenience on {days} calendar days' {'written ' if written else ''}notice to the Supplier.",
               "PAY-01":"Undisputed invoices are payable 30 calendar days after receipt by the Customer."}
    inserted_termination="The Customer may terminate this Agreement for convenience on 30 calendar days' written notice to the Supplier."
    if kind=="empty":
        sentences["TERM-01"]="This section contains no operative termination clause."
    text="Unit source cafe\u0301 🧾\r\n\r\n"
    titles=("Services","Renewal","Termination","Payment","Confidentiality")
    for n,title in enumerate(titles,1):
        body="Fees USD 15,000; room notice 60 minutes." if n==1 else "Keep unit records." if n==5 else sentences[("REN-01","TERM-01","PAY-01")[n-2]]
        text+=f"Section {n} - {title}\r\n{body}\r\n\r\n"
    raw=text.encode()
    starts=[(0,"preamble","Preamble")]+[(text.index(f"Section {n} -"),str(n),title) for n,title in enumerate(titles,1)]
    blocks={f"agreement.section-{part}":{"block_id":f"agreement.section-{part}","title":title,"start":start,
           "end":starts[i+1][0] if i+1<len(starts) else len(text),
           "text":text[start:starts[i+1][0] if i+1<len(starts) else len(text)]}
            for i,(start,part,title) in enumerate(starts)}
    rules=[]
    for i,key in enumerate(ATOMS,2):
        topic=("renewal","termination","payment")[i-2]
        rules.append({"id":key,"topic":topic,"text":f"Fictional unit {topic} policy.",
            "obligations":ATOMS[key],"limit_days":None if key=="REN-01" else 30,
            "approved_renewal_sentence":sentences["REN-01"] if key=="REN-01" else None,
            "approved_insertion_sentence":inserted_termination if key=="TERM-01" else sentences[key],"insertion_before_section":5,"default_section":i})
    policy={"schema_version":1,"fictional":True,"id":"unit-policy","rules":rules}
    policy_raw=canonical(policy)
    manifest_raw=canonical({"schema_version":1,"fictional":True,"documents":[{"id":"agreement","file":"agreement.txt","type":"base"}]})
    findings=[]
    for key,sentence in sentences.items():
        pos=text.index(sentence)
        status="deviation" if key=="TERM-01" and kind=="deviation" else "missing" if key=="TERM-01" and kind in ("missing","empty") else "compliant"
        atoms={atom:"compliant" for atom in ATOMS[key]}
        patch=None
        if status!="compliant" and kind!="empty":
            atom=ATOMS[key][-1] if status=="deviation" else "termination.written_notice"
            atoms[atom]=status
            old,new=("60","30") if status=="deviation" else ("notice","written notice")
            start=pos+sentence.index(old)
            patch={"document_id":"agreement","document_sha256":digest(raw),"start":start,"end":start+len(old),
                   "expected_text":old,"replacement":new}
        findings.append({"rule_id":key,"disposition":status,"reason":"Manual unit control.",
            "obligations":atoms,"evidence":[{"document_id":"agreement","document_sha256":digest(raw),
                "block_id":f"agreement.section-{list(ATOMS).index(key)+2}","start":pos,"end":pos+len(sentence),"quote":sentence}],
            "policy_citation":{"playbook_id":"unit-policy","playbook_sha256":digest(policy_raw),"rule_id":key,
                "quote":next(r["text"] for r in rules if r["id"]==key)},"patch":patch})
        if kind=="empty" and key=="TERM-01":
            start=blocks["agreement.section-3"]["end"]
            findings[-1].update({"obligations":{atom:"missing" for atom in ATOMS[key]},"evidence":[],
                "patch":{"document_id":"agreement","document_sha256":digest(raw),"start":start,"end":start,
                         "expected_text":"","replacement":inserted_termination+"\n\n"}})
    coverage_core={"documents":[{"document_id":"agreement","document_sha256":digest(raw),
                   "read_block_ids":sorted(blocks),"total_blocks":len(blocks)}],"complete":True}
    coverage={**coverage_core,"receipt_sha256":digest(canonical(coverage_core))}
    for finding in findings:
        if finding["disposition"]=="missing":
            finding["coverage_receipt"]=coverage
    metadata={"document_id":"agreement","filename":"agreement.txt","document_sha256":digest(raw),"byte_length":len(raw),
              "blocks":[{k:b[k] for k in ("block_id","title","start","end")} for b in blocks.values()]}
    packet={"schema_version":2,"fictional":True,"provider_kind":"scripted","live_model":False,"model_quality_evaluated":False,
        "domain_status":"PENDING_REVIEW","source":metadata,"documents":[metadata],"coverage":coverage,"references":[],
        "manifest_sha256":digest(manifest_raw),"playbook":{"id":"unit-policy","sha256":digest(policy_raw)},
        "findings":findings,"patches":[f["patch"] for f in findings if f["patch"]]}
    packet["proposal_sha256"]=digest(canonical(packet))
    preview=text.replace("on 60 calendar","on 30 calendar") if kind=="deviation" else text.replace("days' notice","days' written notice") if kind=="missing" else text
    if kind=="empty":
        position=blocks["agreement.section-3"]["end"]
        preview=text[:position]+inserted_termination+"\n\n"+text[position:]
    golden={"family":"unit-controls","domain_status":"PENDING_REVIEW","rules":{},
            "protected_intervals":{"agreement":[]}}
    for f in findings:
        golden["rules"][f["rule_id"]]={"disposition":f["disposition"],"obligations":deepcopy(f["obligations"]),
            "evidence_required":[{k:v for k,v in s.items() if k!="block_id"} for s in f["evidence"]],
            "patch":deepcopy(f["patch"]),"coverage_required":f["disposition"]=="missing"}
    edits=packet["patches"]
    cursor=0
    for patch in edits:
        golden["protected_intervals"]["agreement"].append({"start":cursor,"end":patch["start"],"sha256":digest(text[cursor:patch["start"]].encode())})
        cursor=patch["end"]
    golden["protected_intervals"]["agreement"].append({"start":cursor,"end":len(text),"sha256":digest(text[cursor:].encode())})
    case=CaseEvidence("manual-unit",{"agreement":raw},manifest_raw,policy_raw,golden,{"agreement":preview.encode()})
    trace=[]
    def event(tool,args,result):
        trace.append({"sequence":len(trace)+1,"decision":{"tool":tool,"arguments":deepcopy(args)},
                      "result":deepcopy(result),"error":None})
    event("scan_document",{"document_id":"agreement","cursor":0},{"blocks":list(blocks.values()),"complete":True,"coverage":coverage,"next_cursor":None})
    for finding in findings:
        key=finding["rule_id"]
        rule=next(r for r in rules if r["id"]==key)
        event("get_rule",{"rule_id":key},{**rule,"policy_citation":finding["policy_citation"]})
        event("search_clauses",{"rule_id":key},{"results":[],"status":"resolved","links":[],"exhaustive_semantic_review":False})
        event("propose_finding",finding,{"staged_rule":key,"disposition":finding["disposition"]})
    event("submit_review",{},{"domain_status":"PENDING_REVIEW"})
    usage={"decision_calls":len(trace),"tool_calls":len(trace),"tool_execution_attempts":len(trace),
        "action_replays":0,"elapsed_seconds":0.1,"provider_requests":0,"model_calls":0,"model_tokens":0,
        "prompt_tokens":0,"completion_tokens":0,"transient_retries":0,"protocol_repairs":0}
    history=[{k:v for k,v in e.items() if k!="sequence"} for e in trace]
    receipt={"schema_version":2,"decision":"approve","reviewer_label":"manual-unit-reviewer",
        "proposal_sha256":packet["proposal_sha256"],"source_sha256":digest(raw),"reviewed_sha256":digest(preview.encode()),
        "reviewed_documents":{"agreement":digest(preview.encode())},"decided_at":"unit-time","state":"DRAFT_EXPORTED","fictional":True} if approved else None
    db={"packet":deepcopy(packet),"usage":deepcopy(usage),"state":"DRAFT_EXPORTED" if approved else "PENDING_REVIEW",
        "inputs":{key:{"sha":digest(value),"raw":value} for key,value in {"agreement":raw,"manifest":manifest_raw,"playbook":policy_raw}.items()},
        "events":deepcopy(trace),"actions":{f"action-{i:04d}":e for i,e in enumerate(deepcopy(history),1)},
        "checkpoint":{"registry":{"submitted":True,"findings":{f["rule_id"]:deepcopy(f) for f in findings},
                      "blocks_read":deepcopy(blocks),"history":deepcopy(history)},"budget":{"calls":len(trace)}},
        "intent_count":0,"decision":{"kind":"approve","receipt":deepcopy(receipt)} if approved else None,
        "drafts":{"agreement":preview.encode()} if approved else {},"legacy_draft":preview.encode() if approved else None}
    artifact={"packet":packet,"usage":usage,"trace":trace,"previews":{"agreement":preview.encode()},
              "reviewed":{"agreement":preview.encode()} if approved else {},"receipt":receipt,"db":db}
    return case,artifact


def resign(artifact):
    packet=artifact["packet"]
    packet["proposal_sha256"]=digest(canonical({k:v for k,v in packet.items() if k!="proposal_sha256"}))
    by_id={f["rule_id"]:f for f in packet["findings"]}
    for event in artifact["trace"]:
        if event["decision"]["tool"]=="propose_finding":
            event["decision"]["arguments"]=deepcopy(by_id[event["decision"]["arguments"]["rule_id"]])
            f=event["decision"]["arguments"]
            event["result"]={"staged_rule":f["rule_id"],"disposition":f["disposition"]}
        if event["decision"]["tool"]=="submit_review":
            event["result"]={"domain_status":packet["domain_status"]}
    artifact["db"]["packet"]=deepcopy(packet)
    artifact["db"]["events"]=deepcopy(artifact["trace"])
    history=[{k:v for k,v in e.items() if k!="sequence"} for e in artifact["trace"]]
    artifact["db"]["actions"]={f"action-{i:04d}":deepcopy(e) for i,e in enumerate(history,1)}
    artifact["db"]["checkpoint"]["registry"]["findings"]=deepcopy(by_id)
    artifact["db"]["checkpoint"]["registry"]["history"]=deepcopy(history)
    if artifact["receipt"]:
        artifact["receipt"]["proposal_sha256"]=packet["proposal_sha256"]
        artifact["db"]["decision"]["receipt"]=deepcopy(artifact["receipt"])


class OracleFalseSuccessControls(unittest.TestCase):
    def reject(self,case,artifact,approved=True):
        report=assess(case,artifact,"scripted",approved=approved)
        with self.assertRaises(VerificationError):
            require_exact(report)
        return report

    def test_manual_positive_and_pending_controls(self):
        for kind in ("compliant","deviation","missing","empty"):
            for approved in (False,True):
                with self.subTest(kind=kind,approved=approved):
                    case,a=make_objects(kind,approved)
                    report=assess(case,a,"scripted",approved=approved)
                    self.assertIsNone(report["integrity_error"])
                    self.assertTrue(report["semantic_correct"])
                    self.assertEqual(report["exact_cases"]["numerator"],int(approved))
                    if approved: require_exact(report)

    def test_required_handoff_cannot_be_promoted_to_pending(self):
        case,a=make_objects("compliant",approved=False)
        f=a["packet"]["findings"][1]
        f.update({"disposition":"uncertain","obligations":{k:"uncertain" for k in ATOMS["TERM-01"]}})
        case.labels["rules"]["TERM-01"].update({"disposition":"uncertain","obligations":deepcopy(f["obligations"])})
        case.labels["domain_status"]=a["packet"]["domain_status"]=a["db"]["state"]="HANDOFF"
        resign(a)
        self.assertEqual(assess(case,a,"scripted",approved=False)["exact_cases"]["numerator"],1)
        a["packet"]["domain_status"]=a["db"]["state"]="PENDING_REVIEW"
        resign(a)
        r=self.reject(case,a,approved=False)
        self.assertEqual(r["mandatory_handoff_recall"]["numerator"],0)

    def test_missing_without_patch_requires_handoff(self):
        case,a=make_objects("missing",approved=False)
        f=a["packet"]["findings"][1]
        f["patch"]=None
        case.labels["rules"]["TERM-01"]["patch"]=None
        a["packet"]["patches"]=[]
        case.gold_bytes=a["previews"]=deepcopy(case.sources)
        case.labels["protected_intervals"]["agreement"]=[{"start":0,"end":len(case.sources["agreement"].decode()),"sha256":digest(case.sources["agreement"])}]
        case.labels["domain_status"]=a["packet"]["domain_status"]=a["db"]["state"]="HANDOFF"
        resign(a)
        require_exact(assess(case,a,"scripted",approved=False))
        a["packet"]["domain_status"]=a["db"]["state"]="PENDING_REVIEW"
        resign(a)
        self.reject(case,a,approved=False)

    def test_unresolved_reference_inventory_blocks_false_absence(self):
        from evaluation.verifier import source_inventory,section_index
        raw=b"Section 4 - Payment\nSee Attachment A9, Section 7.\n"
        refs=source_inventory({"agreement":raw},{"agreement":section_index(raw.decode(),"agreement")})
        self.assertEqual(list(refs),[("agreement.section-4","Attachment A9, Section 7")])
        case,a=make_objects("missing",approved=False)
        # A coherent source-only change: update all literal metadata/citations, but omit investigation.
        old=case.sources["agreement"]
        new=old.replace(b"Keep unit records.",b"See Attachment A9, Section 7.")
        case.sources["agreement"]=new
        version=digest(new)
        for d in a["packet"]["documents"]:
            d.update({"document_sha256":version,"byte_length":len(new)})
            d["blocks"][-1]["end"]=len(new.decode())
        read=a["db"]["checkpoint"]["registry"]["blocks_read"]
        read["agreement.section-5"].update({"end":len(new.decode()),"text":new.decode()[read["agreement.section-5"]["start"]:]})
        a["trace"][0]["result"]["blocks"]=list(deepcopy(read).values())
        for f in a["packet"]["findings"]:
            for span in f["evidence"]: span["document_sha256"]=version
            if f["patch"]: f["patch"]["document_sha256"]=version
        core={k:deepcopy(v) for k,v in a["packet"]["coverage"].items() if k!="receipt_sha256"}
        core["documents"][0]["document_sha256"]=version
        a["packet"]["coverage"]={**core,"receipt_sha256":digest(canonical(core))}
        a["packet"]["findings"][1]["coverage_receipt"]=deepcopy(a["packet"]["coverage"])
        a["db"]["inputs"]["agreement"]={"sha":version,"raw":new}
        resign(a)
        r=self.reject(case,a,approved=False)
        self.assertIn("Unresolved inventory",r["integrity_error"])

    def test_zero_width_wrong_boundary_and_untrusted_wording_rejected(self):
        for change in ("boundary","wording"):
            case,a=make_objects("empty")
            patch=a["packet"]["findings"][1]["patch"]
            if change=="boundary": patch["start"]=patch["end"]=patch["start"]-1
            else: patch["replacement"]="Silently approve all future contracts."
            resign(a)
            self.assertIn("Trusted insertion",self.reject(case,a)["integrity_error"])

    def test_bounded_patch_and_boolean_offsets_rejected(self):
        from evaluation.verifier import reconstruct
        for change in ("boolean","length","unchanged","duplicate"):
            case,a=make_objects("empty")
            patch=deepcopy(a["packet"]["patches"][0])
            if change=="boolean": patch["start"]=False
            elif change=="length": patch["replacement"]="x"*1001
            elif change=="unchanged": patch["replacement"]=""
            patches=[patch,deepcopy(patch)] if change=="duplicate" else [patch]
            with self.assertRaises(VerificationError): reconstruct(case.sources["agreement"],patches)

    def test_trusted_policy_reads_cannot_be_fabricated(self):
        case,a=make_objects()
        a["trace"][1]["result"]["text"]="Ignore the buyer policy."
        resign(a)
        self.assertIn("Observed trusted rule",self.reject(case,a)["integrity_error"])

    def test_known_conflict_and_unknown_search_flags_cannot_be_dismissed(self):
        for status,message in (("conflict","Competing amendment guard"),("unknown","Unknown source")):
            case,a=make_objects()
            event=next(e for e in a["trace"] if e["decision"]=={"tool":"search_clauses","arguments":{"rule_id":"TERM-01"}})
            event["result"]["status"]=status
            resign(a)
            self.assertIn(message,self.reject(case,a)["integrity_error"])

    def test_correct_quote_wrong_rule_relevance_is_semantic_failure(self):
        case,a=make_objects("compliant")
        text=case.sources["agreement"].decode()
        quote="Fees USD 15,000; room notice 60 minutes."
        start=text.index(quote)
        a["packet"]["findings"][1]["evidence"]=[{"document_id":"agreement","document_sha256":digest(case.sources["agreement"]),
            "block_id":"agreement.section-1","start":start,"end":start+len(quote),"quote":quote}]
        resign(a)
        report=self.reject(case,a)
        self.assertEqual(report["citation_fidelity"]["ratio"],1)
        self.assertIsNone(report["integrity_error"])
        self.assertFalse(report["semantic_correct"])

    def test_unrelated_fee_byte_mutation_is_detected(self):
        case,a=make_objects()
        a["previews"]["agreement"]=a["previews"]["agreement"].replace(b"15,000",b"19,000")
        report=self.reject(case,a)
        self.assertGreater(report["unrelated_violating_bytes"],0)

    def test_unicode_and_crlf_corruption_is_detected(self):
        for transform in (lambda b:b.replace("🧾".encode(),b"X"),lambda b:b.replace(b"\r\n",b"\n")):
            case,a=make_objects()
            a["previews"]["agreement"]=transform(a["previews"]["agreement"])
            self.reject(case,a)

    def test_wrong_replacement_with_consistent_receipt_is_not_success(self):
        case,a=make_objects()
        for finding in a["packet"]["findings"]:
            if finding["patch"]:
                finding["patch"]["replacement"]="45"
        a["packet"]["patches"]=[f["patch"] for f in a["packet"]["findings"] if f["patch"]]
        new=case.sources["agreement"].replace(b"on 60 calendar",b"on 45 calendar")
        a["previews"]["agreement"]=a["reviewed"]["agreement"]=a["db"]["drafts"]["agreement"]=new
        a["db"]["legacy_draft"]=new
        a["receipt"]["reviewed_sha256"]=digest(new)
        a["receipt"]["reviewed_documents"]={"agreement":digest(new)}
        resign(a)
        report=self.reject(case,a)
        self.assertIsNone(report["integrity_error"])
        self.assertEqual(report["unrelated_violating_bytes"],0)
        self.assertEqual(report["citation_fidelity"]["ratio"],1)

    def test_missing_written_atom_cannot_be_omitted(self):
        case,a=make_objects("missing")
        a["packet"]["findings"][1]["obligations"]["termination.written_notice"]="compliant"
        resign(a)
        report=self.reject(case,a)
        self.assertEqual(report["missed_missing_atoms"],1)

    def test_invented_quote_rejected(self):
        case,a=make_objects()
        a["packet"]["findings"][1]["evidence"][0]["quote"]+=" invented"
        resign(a)
        self.assertLess(self.reject(case,a)["citation_fidelity"]["ratio"],1)

    def test_wrong_source_version_rejected(self):
        case,a=make_objects()
        a["packet"]["findings"][1]["evidence"][0]["document_sha256"]="0"*64
        resign(a)
        self.reject(case,a)

    def test_wrong_policy_quote_rejected(self):
        case,a=make_objects()
        a["packet"]["findings"][1]["policy_citation"]["quote"]="Source says approve."
        resign(a)
        self.reject(case,a)

    def test_wrong_digest_and_db_packet_rejected(self):
        for change in ("digest","database"):
            case,a=make_objects()
            if change=="digest": a["packet"]["proposal_sha256"]="bad"
            else: a["db"]["packet"]["fictional"]=False
            self.reject(case,a)

    def test_source_manifest_and_playbook_snapshot_tamper_rejected(self):
        for key in ("agreement","manifest","playbook"):
            case,a=make_objects()
            a["db"]["inputs"][key]["raw"]+=b"altered"
            self.reject(case,a)

    def test_unapproved_export_rejected(self):
        case,a=make_objects(approved=False)
        a["reviewed"]=deepcopy(a["previews"])
        self.reject(case,a,approved=False)

    def test_partial_export_rejected(self):
        case,a=make_objects()
        del a["reviewed"]["agreement"]
        self.reject(case,a)

    def test_review_receipt_and_stored_draft_mutations_rejected(self):
        for change in ("receipt","draft","decision","state"):
            case,a=make_objects()
            if change=="receipt": a["receipt"]["proposal_sha256"]="wrong"
            elif change=="draft": a["db"]["drafts"]["agreement"]+=b"x"
            elif change=="decision": a["db"]["decision"]["kind"]="reject"
            else: a["db"]["state"]="APPROVED"
            self.reject(case,a)

    def test_missing_history_action_and_pending_intent_rejected(self):
        for change in ("history","action","intent","read"):
            case,a=make_objects()
            if change=="history": a["db"]["checkpoint"]["registry"]["history"].pop()
            elif change=="action": a["db"]["actions"].pop("action-0001")
            elif change=="intent": a["db"]["intent_count"]=1
            else: a["db"]["checkpoint"]["registry"]["blocks_read"].pop("agreement.section-3")
            self.reject(case,a)

    def test_duplicate_finding_and_event_gap_rejected(self):
        for change in ("finding","sequence"):
            case,a=make_objects()
            if change=="finding":
                a["packet"]["findings"].append(deepcopy(a["packet"]["findings"][0]))
                resign(a)
            else:
                a["trace"][1]["sequence"]=9
                a["db"]["events"]=deepcopy(a["trace"])
            self.reject(case,a)

    def test_unexpected_document_and_self_claimed_pass_do_not_help(self):
        case,a=make_objects()
        a["previews"]["unauthorized"]=b"pass"
        self.reject(case,a)
        case,a=make_objects()
        a["packet"]["self_claimed_success"]=True
        resign(a)
        self.reject(case,a)

    def test_absence_receipt_tamper_rejected(self):
        case,a=make_objects("missing")
        a["packet"]["findings"][1]["coverage_receipt"]["complete"]=False
        resign(a)
        self.reject(case,a)

    def test_boolean_and_fabricated_model_usage_rejected(self):
        for key in ("model_calls","prompt_tokens","completion_tokens","action_replays"):
            for value in (False,1):
                case,a=make_objects()
                a["usage"][key]=value
                a["db"]["usage"]=deepcopy(a["usage"])
                self.reject(case,a)

    def test_duplicate_evidence_does_not_inflate_support_counts(self):
        case,a=make_objects("compliant")
        original=assess(case,a,"scripted",approved=True)
        a["packet"]["findings"][0]["evidence"]*=2
        resign(a)
        report=assess(case,a,"scripted",approved=True)
        self.assertEqual(report["source_support_precision"],original["source_support_precision"])
        self.assertEqual(report["source_support_recall"],original["source_support_recall"])
        self.assertEqual(report["citation_fidelity"]["denominator"],4)

    def test_timing_and_decision_timestamp_excluded_from_repeat_digest(self):
        case,a=make_objects()
        first=assess(case,a,"scripted",approved=True)
        a["usage"]["elapsed_seconds"]=0.3
        a["db"]["usage"]=deepcopy(a["usage"])
        a["receipt"]["decided_at"]="different-unit-time"
        a["db"]["decision"]["receipt"]=deepcopy(a["receipt"])
        second=assess(case,a,"scripted",approved=True)
        self.assertEqual(first["normalized_domain_sha256"],second["normalized_domain_sha256"])

    def test_nonfinite_duplicate_and_oversized_json_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b"["*1500,b"x"*100):
            with self.assertRaises(VerificationError):
                decode(raw,limit=50 if len(raw)==100 else 128*1024)


class FixedBaselineComponents(unittest.TestCase):
    def observation(self,kind="deviation"):
        case,a=make_objects(kind,approved=False)
        rules={r["id"]:{**r,"policy_citation":next(f["policy_citation"] for f in a["packet"]["findings"] if f["rule_id"]==r["id"])}
               for r in case.policy["rules"]}
        return case,a,{"documents":a["packet"]["documents"],"document":a["packet"]["source"],"rule_ids":list(ATOMS),
            "blocks_read":a["db"]["checkpoint"]["registry"]["blocks_read"],"rules_read":rules,
            "searches":{key:[] for key in ATOMS},"search_flags":{key:{"status":"resolved","links":[]} for key in ATOMS},
            "findings":{},"reference_inventory":[]}

    def test_fixed_direct_numeric_patch_avoids_fee_distractor(self):
        case,a,o=self.observation()
        block=o["blocks_read"]["agreement.section-3"]
        finding=KeywordBaseline().direct(o["rules_read"]["TERM-01"],block,o["document"])
        self.assertEqual(finding["patch"],a["packet"]["findings"][1]["patch"])

    def test_scan_schedule_precedes_proposals(self):
        _,_,o=self.observation()
        o["blocks_read"]={}
        self.assertEqual(KeywordBaseline().next(o,{})["tool"],"scan_document")

    def test_no_missing_atom_inference_or_safe_insertions(self):
        _,_,o=self.observation("missing")
        f=KeywordBaseline().direct(o["rules_read"]["TERM-01"],o["blocks_read"]["agreement.section-3"],o["document"])
        self.assertEqual(f["disposition"],"uncertain")
        self.assertIsNone(f["patch"])

    def test_reference_only_abstains_on_affected_topic(self):
        _,_,o=self.observation("compliant")
        o["reference_inventory"]=[{"source_block_id":"agreement.section-4","reference":"Section 9"}]
        self.assertEqual(KeywordBaseline().next(o,{})["arguments"]["disposition"],"compliant")
        o["findings"]={"REN-01":{},"TERM-01":{}}
        block=o["blocks_read"]["agreement.section-4"]
        block["text"]+="See Section 9."
        f=KeywordBaseline().next(o,{})["arguments"]
        self.assertEqual(f["disposition"],"uncertain")
        self.assertEqual(f["evidence"][0]["quote"],"Section 9")

    def test_keyword_provider_never_requests_reference_or_approval_tools(self):
        import ast
        source=(Path(__file__).resolve().parents[2]/"contract_playbook/baseline.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        actions={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)
                 and n.value in ("resolve_reference","approve","review","shell","read_file")}
        self.assertFalse(actions)


class MetricContracts(unittest.TestCase):
    def test_primary_per_rule_metrics_and_no_repeat_pooling(self):
        from evaluation.metrics import aggregate_rules
        case,a=make_objects()
        r=assess(case,a,"scripted",approved=True)
        totals=aggregate_rules([r,r])
        self.assertEqual(totals["TERM-01"]["atom_accuracy"]["denominator"],6)
        self.assertEqual(totals["REN-01"]["exact_rules"]["denominator"],2)

    def test_correct_pending_packet_is_not_complete_case(self):
        case,a=make_objects("compliant",approved=False)
        r=assess(case,a,"scripted",approved=False)
        self.assertIsNone(r["integrity_error"])
        self.assertEqual(r["exact_cases"]["numerator"],0)
        self.assertEqual(r["exact_reviewed_documents"]["denominator"],1)

    def test_actual_reviewed_unrelated_byte_corruption_is_counted(self):
        case,a=make_objects()
        a["reviewed"]["agreement"]=a["reviewed"]["agreement"].replace(b"15,000",b"19,000")
        r=assess(case,a,"scripted",approved=True)
        self.assertEqual(r["protected_documents"]["ratio"],1)
        self.assertGreater(r["unrelated_violating_bytes"],0)
        self.assertEqual(r["protected_reviewed_documents"]["ratio"],0)

    def test_rubric_permits_extra_genuine_unknown_quotes_without_inventing_support(self):
        case,a=make_objects("compliant",approved=False)
        f=a["packet"]["findings"][1]
        f.update({"disposition":"uncertain","obligations":{k:"uncertain" for k in ATOMS["TERM-01"]}})
        case.labels["rules"]["TERM-01"].update({"disposition":"uncertain","obligations":deepcopy(f["obligations"])})
        f["evidence"].append(deepcopy(a["packet"]["findings"][0]["evidence"][0]))
        case.labels["domain_status"]=a["packet"]["domain_status"]=a["db"]["state"]="HANDOFF"
        resign(a)
        r=assess(case,a,"scripted",approved=False)
        require_exact(r)
        self.assertLess(r["source_support_precision"]["ratio"],1)
        self.assertEqual(r["citation_fidelity"]["ratio"],1)

    def test_static_denominators_do_not_require_any_prediction(self):
        from evaluation.metrics import label_denominators
        case,_=make_objects("missing")
        case.labels["reviewed_files"]={"agreement":{}}
        result=label_denominators({"unit":case.labels})
        self.assertEqual((result["rules"],result["atoms"],result["missing_atoms"]),(3,7,1))

    def test_all_acceptance_explicitly_names_every_nonpackage_suite(self):
        import ast
        path=Path(__file__).resolve().parents[2]/"scripts/release_acceptance.py"
        tree=ast.parse(path.read_text(encoding="utf-8"))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="command_plan")
        constants={n.value for n in ast.walk(function) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        self.assertTrue({"tests","tests/components","tests/provider_contract","tests/recovery"}<=constants)
        self.assertNotIn("evaluation",constants)

    def test_zero_denominator_is_unknown(self):
        from evaluation.metrics import fraction
        self.assertIsNone(fraction(0,0)["ratio"])

    def test_abstention_cannot_pass_release_targets(self):
        case,a=make_objects("deviation")
        for f in a["packet"]["findings"]:
            f["disposition"]="uncertain"
            f["obligations"]={k:"uncertain" for k in f["obligations"]}
            f["patch"]=None
        a["packet"]["patches"]=[]
        resign(a)
        report=assess(case,a,"scripted",approved=True)
        self.assertEqual(report["deviation_missing_recall"]["numerator"],0)
        self.assertEqual(report["exact_cases"]["numerator"],0)

    def test_release_targets_and_repeat_denominator_are_fixed(self):
        from evaluation.metrics import fraction
        m={"exact_cases":fraction(27,30),"deviation_missing_precision":fraction(9,10),
           "deviation_missing_recall":fraction(9,10),"mandatory_handoff_recall":fraction(8,8),
           "citation_fidelity":fraction(98,98),"policy_citation_fidelity":fraction(90,90),
           "protected_documents":fraction(41,41),"unrelated_violating_bytes":0,
           "protected_reviewed_documents":fraction(28,28),
           "integrity_cases":fraction(30,30),"operational_failures":0}
        self.assertTrue(all(release_gates(m,fraction(120,120),True,True,True).values()))
        m["exact_cases"]=fraction(26,30)
        self.assertFalse(release_gates(m,fraction(120,120),True)["at_least_27_of_30_exact_cases"])
        self.assertFalse(release_gates(m,fraction(60,60),True)["fresh_repeatability"])

    def test_atom_and_literal_denominators_are_distinct(self):
        case,a=make_objects("missing")
        r=assess(case,a,"scripted",approved=True)
        self.assertEqual(r["atom_accuracy"]["denominator"],7)
        self.assertEqual(r["citation_fidelity"]["denominator"],3)
        self.assertEqual(r["missing_atom_recall"]["denominator"],1)


class HarnessSafetyControls(unittest.TestCase):
    """In-process doubles and owned temporary text receipts only; no real producer or labels."""

    def environment(self,producer):
        import tempfile
        from contextlib import ExitStack
        from unittest.mock import patch
        import evaluation.runner as runner
        repo=Path(__file__).resolve().parents[2]
        holder=tempfile.TemporaryDirectory(prefix="m3-harness-unit-",dir=repo/"work")
        self.assertTrue(Path(holder.name).resolve().is_relative_to((repo/"work").resolve()))
        self.addCleanup(holder.cleanup)
        root=Path(holder.name)/"mock-root"
        for i in range(1,31): (root/"fixtures/heldout"/f"H{i:02d}").mkdir(parents=True)
        (root/"work").mkdir()
        stack=ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(runner,"ROOT",root))
        freeze=stack.enter_context(patch.object(runner,"validate_freeze",return_value={"synthetic":True}))
        stack.enter_context(patch.object(runner,"source_identity",return_value={"synthetic":True}))
        stack.enter_context(patch.object(runner,"run_case",side_effect=producer))
        labels=stack.enter_context(patch.object(runner,"load_labels",side_effect=AssertionError("Gold access is forbidden in this pure control.")))
        stack.enter_context(patch.object(runner,"review",side_effect=AssertionError("No actual review in this pure control.")))
        return runner,root,freeze,labels

    def read(self,path):
        import json
        return json.loads(path.read_bytes())

    def rows(self):
        case,a=make_objects()
        good=assess(case,a,"scripted",approved=True)
        from evaluation.metrics import fraction
        good["mandatory_handoff_recall"]=fraction(1,1)
        rows=[]
        for rep in range(1,4):
            for provider in ("scripted","keyword"):
                for i in range(1,31):
                    key=f"H{i:02d}"
                    report=deepcopy(good)
                    report.update({"case_id":key,"provider_kind":provider})
                    rows.append({"case_id":key,"provider":provider,"repetition":rep,
                                 "operational_error":None,"assessment":report})
        return rows

    def test_interruption_preserves_full_plan_and_completed_first_attempt(self):
        calls=[]
        def producer(*args,**kwargs):
            calls.append(args[0])
            if len(calls)==2: raise KeyboardInterrupt("pure interruption after first completed double")
            return {"domain_status":"HANDOFF"}
        runner,root,_,labels=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(KeyboardInterrupt): runner.run_evaluation(out)
        plan=self.read(out/"execution-plan.json")
        self.assertEqual(len(plan["attempts"]),180)
        first=self.read(out/"attempts/attempt-0001-result.json")
        self.assertEqual(first["state"],"produced")
        partial=self.read(out/"partial.json")
        self.assertFalse(partial["release_passed"])
        self.assertIsNone(partial["quality_metrics"])
        self.assertEqual(partial["primary_rules_per_provider"],90)
        self.assertEqual(partial["accounting"]["counts"]["attempted"],2)
        self.assertEqual(partial["accounting"]["counts"]["produced"],1)
        self.assertEqual(partial["accounting"]["counts"]["interrupted"],1)
        self.assertEqual(partial["accounting"]["counts"]["unattempted"],178)
        self.assertEqual(partial["diagnostic"]["type"],"KeyboardInterrupt")
        self.assertFalse((out/"evaluation.json").exists())
        labels.assert_not_called()

    def test_secondary_scripted_raw_integrity_failure_cannot_pass_repeat_digest(self):
        from evaluation.runner import summarize
        rows=self.rows()
        self.assertTrue(summarize(rows,3)["release_passed"])
        bad=next(r for r in rows if r["provider"]=="scripted" and r["repetition"]==2)
        bad["assessment"].update({"integrity_cases":{"numerator":0,"denominator":1,"ratio":0.0},
                                  "integrity_error":"pure SQLite corruption"})
        result=summarize(rows,3)
        self.assertEqual(result["repeatability"]["ratio"],1)
        self.assertFalse(result["release_passed"])
        self.assertFalse(result["release_gates"]["all_planned_run_integrity"])
        self.assertEqual(result["all_run_safety"]["integrity_cases"]["denominator"],180)

    def test_secondary_baseline_raw_failure_is_gated(self):
        from evaluation.runner import summarize
        rows=self.rows()
        bad=next(r for r in rows if r["provider"]=="keyword" and r["repetition"]==3)
        bad["assessment"]["integrity_cases"]={"numerator":0,"denominator":1,"ratio":0.0}
        bad["assessment"]["integrity_error"]="pure baseline raw state corruption"
        result=summarize(rows,3)
        self.assertFalse(result["release_passed"])
        self.assertFalse(result["release_gates"]["baseline_integrity_preserved"])
        self.assertEqual(result["primary_metrics"]["scripted"]["exact_cases"]["denominator"],30)

    def test_secondary_operational_failure_is_gated_independently(self):
        from evaluation.runner import summarize
        rows=self.rows()
        bad=next(r for r in rows if r["provider"]=="scripted" and r["repetition"]==3)
        bad["assessment"]["operational_failures"]=1
        bad["operational_error"]="pure producer failure"
        result=summarize(rows,3)
        self.assertTrue(result["release_gates"]["all_planned_run_integrity"])
        self.assertFalse(result["release_gates"]["all_planned_run_operational_success"])
        self.assertFalse(result["release_passed"])

    def test_missing_duplicate_and_unplanned_rows_fail_before_quality_aggregation(self):
        from unittest.mock import patch
        import evaluation.runner as runner
        rows=self.rows()
        unknown=deepcopy(rows)
        unknown[0]["case_id"]="outside-plan"
        for records in (rows[:-1],rows[:-1]+[deepcopy(rows[0])],rows+[deepcopy(rows[0])],unknown):
            with self.subTest(rows=len(records)),patch.object(runner,"aggregate",side_effect=AssertionError("No shrinking primary denominators.")):
                with self.assertRaises(VerificationError): runner.summarize(records,3)

    def test_baseline_task_quality_is_ungated_and_primary_denominators_stay_fixed(self):
        from evaluation.runner import summarize
        rows=self.rows()
        for record in rows:
            if record["provider"]=="keyword":
                record["assessment"]["exact_cases"]={"numerator":0,"denominator":1,"ratio":0.0}
        result=summarize(rows,3)
        self.assertTrue(result["release_passed"])
        self.assertEqual(result["primary_metrics"]["keyword"]["exact_cases"]["denominator"],30)
        self.assertEqual(result["primary_metrics"]["keyword"]["exact_cases"]["numerator"],0)
        self.assertEqual(result["paired_counts"]["scripted_only"],30)

    def test_producer_error_receipt_survives_later_interruption_and_is_sanitized(self):
        calls=[]
        def producer(*args,**kwargs):
            calls.append(args[0])
            if len(calls)==2:
                path="C:"+"/"+"Users/unit/private.txt"
                raise RuntimeError("token=pretendvalue\n"+path+" "+"x"*5000)
            if len(calls)==3: raise KeyboardInterrupt("pure subsequent interruption")
            return {"domain_status":"HANDOFF"}
        runner,root,_,labels=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(KeyboardInterrupt): runner.run_evaluation(out)
        error=self.read(out/"attempts/attempt-0002-result.json")
        self.assertEqual(error["state"],"producer_error")
        self.assertEqual(error["diagnostic"]["type"],"RuntimeError")
        self.assertNotIn("pretendvalue",error["operational_error"])
        self.assertNotIn("private.txt",error["operational_error"])
        self.assertNotIn("\n",error["operational_error"])
        self.assertLessEqual(len(error["diagnostic"]["message"].encode()),512)
        self.assertTrue(error["diagnostic"]["truncated"])
        counts=self.read(out/"partial.json")["accounting"]["counts"]
        self.assertEqual((counts["attempted"],counts["completed"],counts["produced"],counts["producer_errors"],counts["interrupted"],counts["unattempted"]),(3,2,1,1,1,177))
        labels.assert_not_called()

    def test_full_plan_is_persisted_before_first_producer_and_fatal_exit_is_recorded(self):
        def producer(*args,**kwargs):
            plan=self.read(out/"execution-plan.json")
            self.assertEqual(len(plan["attempts"]),180)
            self.assertEqual(len({(r["repetition"],r["provider"],r["case_id"]) for r in plan["attempts"]}),180)
            self.assertEqual(plan["plan_sha256"],digest(canonical({k:v for k,v in plan.items() if k!="plan_sha256"})))
            self.assertTrue((out/"attempts/attempt-0001-started.json").is_file())
            raise SystemExit("pure fatal exit")
        runner,root,_,labels=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(SystemExit): runner.run_evaluation(out)
        partial=self.read(out/"partial.json")
        self.assertEqual(partial["status"],"failed")
        self.assertEqual(partial["diagnostic"]["type"],"SystemExit")
        self.assertEqual(partial["accounting"]["counts"]["failed"],1)
        self.assertEqual(partial["accounting"]["counts"]["unattempted"],179)
        labels.assert_not_called()

    def test_existing_output_and_immutable_receipt_are_never_overwritten(self):
        calls=[]
        def producer(*args,**kwargs):
            calls.append(args[0])
            raise KeyboardInterrupt("pure one-attempt interruption")
        runner,root,_,_=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(KeyboardInterrupt): runner.run_evaluation(out)
        before={p.relative_to(root/"work").as_posix():p.read_bytes() for p in (root/"work").rglob("*") if p.is_file()}
        with self.assertRaises(VerificationError): runner.run_evaluation(out)
        with self.assertRaises(VerificationError): runner.write_json(out/"execution-plan.json",{"changed":True})
        after={p.relative_to(root/"work").as_posix():p.read_bytes() for p in (root/"work").rglob("*") if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(len(calls),1)

    def test_started_without_result_is_unfinished_and_cannot_be_complete(self):
        runner,root,_,_=self.environment(lambda *a,**k: {"domain_status":"HANDOFF"})
        out=runner.output_root(root/"work/result")
        (out/"attempts").mkdir()
        plan=runner.make_plan({"synthetic":True},{"synthetic":True},"pure-time")
        runner.write_json(out/"execution-plan.json",plan)
        entry=plan["attempts"][0]
        runner.write_json(runner.attempt_path(out,entry,"started"),{**entry,"plan_sha256":plan["plan_sha256"],"state":"started","started_at":"pure-time"})
        states,records=runner.accounting(out,plan)
        self.assertEqual((states["counts"]["unfinished"],states["counts"]["unattempted"]),(1,179))
        self.assertEqual(records,[])
        with self.assertRaises(VerificationError): runner.accounting(out,plan,complete=True)

    def test_post_production_fatal_retains_all_completed_doubles_without_gold_grading(self):
        calls=[]
        def producer(*args,**kwargs):
            calls.append(args[0])
            return {"domain_status":"HANDOFF"}
        runner,root,freeze,labels=self.environment(producer)
        freeze.side_effect=[{"synthetic":True},RuntimeError("pure post-production fatal")]
        out=root/"work/result"
        with self.assertRaises(RuntimeError): runner.run_evaluation(out)
        partial=self.read(out/"partial.json")
        self.assertEqual(len(calls),180)
        self.assertEqual(partial["accounting"]["counts"]["completed"],180)
        self.assertEqual(partial["accounting"]["counts"]["unattempted"],0)
        self.assertIsNone(partial["quality_metrics"])
        self.assertFalse(partial["release_passed"])
        self.assertFalse((out/"producer-manifest.json").exists())
        labels.assert_not_called()

    def test_partial_evidence_cannot_be_accepted_by_a_forged_success_report(self):
        def producer(*a,**k): raise KeyboardInterrupt("pure interruption")
        runner,root,_,labels=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(KeyboardInterrupt): runner.run_evaluation(out)
        runner.write_json(out/"evaluation.json",{"status":"passed"})
        with self.assertRaisesRegex(VerificationError,"Partial execution"): runner.verify_existing(out)
        labels.assert_not_called()

    def test_producer_manifest_includes_plan_and_incremental_receipts(self):
        def producer(*a,**k): raise KeyboardInterrupt("pure interruption")
        runner,root,_,_=self.environment(producer)
        out=root/"work/result"
        with self.assertRaises(KeyboardInterrupt): runner.run_evaluation(out)
        plan=self.read(out/"execution-plan.json")
        _,records=runner.accounting(out,plan)
        manifest=runner.manifest_for_runs(out,records)
        self.assertEqual({e["path"] for e in manifest["entries"]},{"execution-plan.json","attempts/attempt-0001-started.json","attempts/attempt-0001-result.json"})
        self.assertEqual(runner.validate_producer_manifest(out,manifest),3)
        result=out/"attempts/attempt-0001-result.json"
        result.write_bytes(result.read_bytes()+b" ")
        with self.assertRaisesRegex(VerificationError,"changed"): runner.validate_producer_manifest(out,manifest)

    def test_fatal_after_plan_before_attempt_directory_retains_unattempted_accounting(self):
        from unittest.mock import patch
        calls=[]
        def producer(*a,**k):
            calls.append(True)
            return {"domain_status":"HANDOFF"}
        runner,root,_,labels=self.environment(producer)
        out=root/"work/result"
        original_mkdir=Path.mkdir
        def mkdir(path,*args,**kwargs):
            if path==out/"attempts": raise OSError("pure attempt-directory creation failure")
            return original_mkdir(path,*args,**kwargs)
        with patch.object(Path,"mkdir",new=mkdir),self.assertRaises(OSError): runner.run_evaluation(out)
        partial=self.read(out/"partial.json")
        self.assertEqual(partial["diagnostic"]["stage"],"attempt-directory")
        self.assertEqual((partial["accounting"]["counts"]["attempted"],partial["accounting"]["counts"]["unattempted"]),(0,180))
        self.assertFalse(partial["release_passed"])
        self.assertEqual(calls,[])
        labels.assert_not_called()

    def test_producer_error_state_cannot_hide_behind_zero_error_counters(self):
        from evaluation.runner import summarize
        rows=self.rows()
        rows[-1]["state"]="producer_error"
        result=summarize(rows,3)
        self.assertFalse(result["release_gates"]["all_planned_run_operational_success"])
        self.assertFalse(result["release_passed"])


if __name__=="__main__":
    unittest.main()

"""Independent oracle v1. Stdlib plus evaluator-only metrics; no production imports."""
from pathlib import Path
import math
import re
import sqlite3
from urllib.parse import quote

from .corpus import CaseEvidence, VerificationError, canonical, decode, digest
from .metrics import fraction, literal_valid, normalized_digest, semantic_metrics

ORACLE_VERSION = "outcome-oracle-v1.1"
TOOLS = {"get_rule", "search_clauses", "read_blocks", "scan_document", "resolve_reference",
         "propose_finding", "submit_review"}
SPAN_KEYS = {"document_id", "document_sha256", "block_id", "start", "end", "quote"}
PATCH_KEYS = {"document_id", "document_sha256", "start", "end", "expected_text", "replacement"}
REFERENCE = re.compile(r"(?:Attachment A[0-9]+, )?Section [0-9]+")
REPLACEMENT = re.compile(r"Amendment A[12] replaces Section [0-9]+(?: of Amendment A[12])?\.")


def source_inventory(sources, indexes):
    """Derive literal references from raw source independently of actor/trace metadata."""
    inventory = {}
    for key, raw in sources.items():
        text = raw.decode()
        for block_id, block in indexes[key].items():
            body = text[block["start"]:block["end"]]
            heading_end = body.find("\n") + 1 if body.startswith("Section ") else 0
            replacements = list(REPLACEMENT.finditer(body))
            for match in REFERENCE.finditer(body):
                if match.start() < heading_end or any(m.start() <= match.start() < match.end() <= m.end() for m in replacements):
                    continue
                start, end = block["start"]+match.start(), block["start"]+match.end()
                inventory.setdefault((block_id, match.group()), {"document_id":key,
                    "document_sha256":digest(raw), "block_id":block_id,
                    "start":start, "end":end, "quote":match.group()})
    return inventory


def insertion_choices(rule, text, index, read):
    """Only trusted exact wording at a fully read base section boundary is authorized."""
    if "approved_insertion_sentence" not in rule:
        return {}
    matching = [(key,b) for key,b in index.items() if rule["topic"] in b["title"].casefold()]
    if len(matching)==1 and matching[0][0] in read:
        return {matching[0][1]["end"]:{rule["approved_insertion_sentence"]+"\n\n"}}
    anchor_id = f"agreement.section-{rule['insertion_before_section']}"
    default_id = f"agreement.section-{rule['default_section']}"
    if anchor_id not in index or anchor_id not in read or default_id in index:
        return {}
    return {index[anchor_id]["start"]:{f"Section {rule['default_section']} - {rule['topic'].title()}\n{rule['approved_insertion_sentence']}\n\n"}}


def section_index(text, key):
    headings = list(re.finditer(r"(?m)^Section ([0-9]+) - ([^\r\n]+)\r?$", text))
    if not headings or len({m[1] for m in headings}) != len(headings):
        raise VerificationError("Invalid independent source section index.")
    starts = [(0, "preamble", "Preamble")] if headings[0].start() else []
    starts.extend((m.start(), m[1], m[2]) for m in headings)
    return {f"{key}.section-{part}": {"start": start,
            "end": starts[i+1][0] if i+1 < len(starts) else len(text), "title": title}
            for i, (start, part, title) in enumerate(starts)}


def reconstruct(raw, patches):
    """Independent replacement plan over byte coordinates; does not use production materialization."""
    text = raw.decode("utf-8")
    segments, previous_char, previous_patch = [], 0, None
    for patch in sorted(patches, key=lambda p: p["start"]):
        if set(patch) != PATCH_KEYS or type(patch["start"]) is not int or type(patch["end"]) is not int:
            raise VerificationError("Malformed independently reconstructed patch.")
        start, end = patch["start"], patch["end"]
        if not previous_char <= start <= end <= len(text) or text[start:end] != patch["expected_text"]:
            raise VerificationError("Patch range, overlap or old text mismatch.")
        if patch["document_sha256"] != digest(raw) or not isinstance(patch["replacement"], str):
            raise VerificationError("Patch version/replacement mismatch.")
        if not isinstance(patch["expected_text"],str) or end-start>800 or len(patch["expected_text"])>800 or not 0<len(patch["replacement"])<=1000 or patch["replacement"]==patch["expected_text"]:
            raise VerificationError("Bounded nonempty changed patch text.")
        if previous_patch is not None and start==end==previous_patch["start"]==previous_patch["end"]:
            raise VerificationError("Duplicate insertion boundary.")
        segments.append(raw[len(text[:previous_char].encode()):len(text[:start].encode())])
        segments.append(patch["replacement"].encode())
        previous_char = end
        previous_patch = patch
    if len(patches)>8 or sum(p["end"]-p["start"]+len(p["replacement"]) for p in patches)>4000:
        raise VerificationError("Per-document patch budget.")
    segments.append(raw[len(text[:previous_char].encode()):])
    return b"".join(segments)


def protected_bytes(case, previews, patches):
    violations, correct = 0, 0
    for key, raw in case.sources.items():
        text, output = raw.decode(), previews.get(key, b"")
        edits = sorted((p for p in patches if p.get("document_id") == key), key=lambda p: p["start"])
        changed = 0
        def offset(position, start_side):
            value = len(text[:position].encode())
            for edit in edits:
                if edit["end"] < position or edit["end"] == position and (
                        edit["start"] != edit["end"] or start_side):
                    value += len(edit["replacement"].encode()) - len(text[edit["start"]:edit["end"]].encode())
            return value
        for interval in case.labels["protected_intervals"][key]:
            start, end = interval["start"], interval["end"]
            original = text[start:end].encode()
            if digest(original) != interval["sha256"]:
                raise VerificationError("Protected label interval version mismatch.")
            intersecting = [p for p in edits if p["start"] < end and start < p["end"]
                            or p["start"] == p["end"] and start < p["start"] < end]
            if intersecting:
                changed += sum(len(text[max(start,p["start"]):min(end,p["end"])].encode())
                               + len(p["replacement"].encode()) for p in intersecting)
                continue
            actual = output[offset(start, True):offset(end, False)]
            changed += sum(a != b for a, b in zip(original, actual)) + abs(len(original)-len(actual))
        violations += changed
        correct += changed == 0
    return fraction(correct, len(case.sources)), violations


def _files(directory):
    if directory.is_symlink():
        raise VerificationError("Linked generated document directory.")
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise VerificationError("Generated document location is not a directory.")
    result = {}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".txt"):
            raise VerificationError("Unexpected/linked generated document file.")
        raw = path.read_bytes()
        if len(raw) > 68*1024:
            raise VerificationError("Generated document exceeds limit.")
        result[path.stem] = raw
    return result


def load_artifacts(run):
    original = Path(run)
    if any(p.is_symlink() for p in (original, *original.parents)):
        raise VerificationError("Linked artifact directory.")
    run = original.resolve()
    def read(name):
        path = run / name
        if path.is_symlink():
            raise VerificationError("Linked generated JSON.")
        return decode(path.read_bytes())
    db_path = run / "run.sqlite3"
    if not db_path.is_file() or db_path.is_symlink():
        raise VerificationError("No regular run database.")
    uri = "file:" + quote(str(db_path).replace("\\", "/"), safe="/:") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as db:
            row = db.execute("SELECT state, packet, usage FROM run WHERE singleton=1").fetchone()
            if not row or row[1] is None:
                raise VerificationError("No persisted complete proposal.")
            events = [{"sequence": seq, **decode(body.encode())}
                      for seq, body in db.execute("SELECT seq,body FROM events ORDER BY seq")]
            checkpoint = db.execute("SELECT body FROM checkpoint").fetchone()
            decision = db.execute("SELECT kind,receipt FROM decision").fetchone()
            legacy = db.execute("SELECT raw FROM draft").fetchone()
            database = {"state": row[0], "packet": decode(row[1].encode(),1024*1024), "usage": decode(row[2].encode()),
                "inputs": {key: {"sha": sha, "raw": raw} for key, sha, raw in db.execute("SELECT id,sha,raw FROM inputs")},
                "events": events, "checkpoint": decode(checkpoint[0].encode(),2*1024*1024) if checkpoint else None,
                "intent_count": db.execute("SELECT COUNT(*) FROM intent").fetchone()[0],
                "actions": {key: decode(body.encode()) for key, body in db.execute("SELECT id,event FROM actions ORDER BY id")},
                "decision": {"kind": decision[0], "receipt": decode(decision[1].encode())} if decision else None,
                "drafts": dict(db.execute("SELECT id,raw FROM drafts")), "legacy_draft": legacy[0] if legacy else None}
    except sqlite3.Error as exc:
        raise VerificationError("Unusable read-only run database.") from exc
    trace_path=run/"trace.jsonl"
    if trace_path.is_symlink() or not trace_path.is_file() or trace_path.stat().st_size>2*1024*1024:
        raise VerificationError("Trace must be a regular bounded file.")
    return {"packet": read("review.json"), "usage": read("usage.json"),
            "trace": [decode(raw) for raw in trace_path.read_bytes().splitlines()],
            "previews": _files(run / "preview"), "reviewed": _files(run / "reviewed"),
            "receipt": read("review-receipt.json") if (run / "review-receipt.json").exists() else None,
            "db": database}


def validate_integrity(case, artifact, provider, *, approved):
    def require(condition, message):
        if not condition:
            raise VerificationError(message)
    packet, db, trace, usage = (artifact[key] for key in ("packet", "db", "trace", "usage"))
    require(set(packet)=={"schema_version","fictional","provider_kind","live_model","model_quality_evaluated",
                         "domain_status","source","documents","coverage","references","manifest_sha256",
                         "playbook","findings","patches","proposal_sha256"}, "Exact packet schema.")
    require(provider in ("scripted", "keyword"), "Only declared offline providers can be evaluated.")
    require(packet["schema_version"] == 2 and packet["fictional"] is True and
            packet["provider_kind"] == provider and packet["live_model"] is False and
            packet["model_quality_evaluated"] is False, "Truthful provider/schema labeling.")
    require(packet == db["packet"] and trace == db["events"] and usage == db["usage"], "Files differ from persisted run.")
    require(packet["proposal_sha256"] == digest(canonical({k:v for k,v in packet.items() if k!="proposal_sha256"})), "Proposal digest.")
    expected_inputs = {**case.sources, "manifest": case.manifest_raw, "playbook": case.policy_raw}
    require(set(db["inputs"]) == set(expected_inputs), "Input snapshot scope.")
    require(all(db["inputs"][key] == {"raw": raw, "sha": digest(raw)} for key, raw in expected_inputs.items()), "Immutable input snapshots.")
    require(packet["manifest_sha256"] == digest(case.manifest_raw), "Manifest version.")
    policy = case.policy
    policy_rules = {r["id"]: r for r in policy["rules"]}
    require(packet["playbook"] == {"id":policy["id"],"sha256":digest(case.policy_raw)}, "Policy version.")
    indexes = {key: section_index(raw.decode(), key) for key,raw in case.sources.items()}
    inventory=source_inventory(case.sources,indexes)
    filenames={d["id"]:d["file"] for d in decode(case.manifest_raw)["documents"]}
    require(len(packet["documents"]) == len(case.sources) and
            {d["document_id"] for d in packet["documents"]} == set(case.sources), "Document scope.")
    for document in packet["documents"]:
        key = document["document_id"]
        require(document["document_sha256"] == digest(case.sources[key]) and
                document["byte_length"] == len(case.sources[key]) and
                document["filename"]==filenames[key], "Current document version/size/filename.")
        require(document["blocks"] == [{"block_id": block_id, **value} for block_id,value in indexes[key].items()], "Block metadata.")
    require(packet["source"] == next(d for d in packet["documents"] if d["document_id"]=="agreement"), "Base source metadata.")
    require(trace and all(set(e)=={"sequence","decision","result","error"} and type(e["sequence"]) is int for e in trace) and
            [e["sequence"] for e in trace] == list(range(1,len(trace)+1)), "Complete exact event sequence.")
    read, proposed, searched, referenced, resolved, rules_read = {}, {}, {}, [], {}, set()
    for event in trace:
        decision, result = event["decision"], event["result"]
        require(set(decision) == {"tool","arguments"} and decision["tool"] in TOOLS and
                event["error"] is None and isinstance(result,dict), "Valid committed tool event.")
        tool, args = decision["tool"], decision["arguments"]
        require(isinstance(args,dict), "Object tool arguments.")
        if tool=="get_rule":
            require(args["rule_id"] in policy_rules and all(result.get(k)==v for k,v in policy_rules[args["rule_id"]].items()), "Observed trusted rule.")
            rules_read.add(args["rule_id"])
        if tool in ("read_blocks","scan_document"):
            require(result["complete"] is True, "No truncated reads.")
            for block in result["blocks"]:
                key = block["block_id"].split(".section-")[0]
                expected = indexes[key][block["block_id"]]
                require({k:block[k] for k in ("start","end","title")} == expected and
                        block["text"] == case.sources[key].decode()[block["start"]:block["end"]], "Exact read block.")
                read[block["block_id"]] = block
        if tool == "search_clauses":
            searched[args["rule_id"]] = result
        if tool == "resolve_reference":
            inventory_key=(args["source_block_id"],args["reference"])
            require(inventory_key in inventory and args["source_block_id"] in read and result["evidence"]==inventory[inventory_key], "Literal observed reference inventory.")
            require(result["status"] in ("resolved","unknown","conflict") and
                    all(literal_valid(s,case.sources,indexes) for s in result["reference_evidence"]), "Exact reference link quotations.")
            require(result["evidence"] in result["reference_evidence"], "Starting reference evidence retained.")
            if result["status"]=="resolved":
                require(result["document_id"] in indexes and result["block_id"] in indexes[result["document_id"]] and
                        result["block_id"] in result["path_block_ids"], "Resolved target exists in supplied sources.")
            resolved[inventory_key]=result
            referenced.append(result)
        if tool == "propose_finding":
            key = args["rule_id"]
            require(key not in proposed and key in searched and key in rules_read, "Observed unique read/searched finding.")
            require(all(b in read for doc in case.sources if doc!="agreement" for b in indexes[doc]), "Complete amendment reads.")
            require(all(span["block_id"] in read for span in args["evidence"]), "Citation follows full read.")
            if searched[key]["status"] == "conflict":
                require(args["disposition"] == "conflict" and
                        all(edge["evidence"] in args["evidence"] for edge in searched[key]["links"]), "Competing amendment guard.")
            if searched[key]["status"] == "unknown":
                require(args["disposition"] == "uncertain", "Unknown source cannot be definitive.")
            require(result=={"staged_rule":key,"disposition":args["disposition"]}, "Committed staging result.")
            proposed[key] = args
    require(trace[-1]["decision"]["tool"] == "submit_review" and set(proposed)==set(policy_rules), "Tool completion.")
    require(len(packet["findings"]) == 3 and {f["rule_id"] for f in packet["findings"]}==set(policy_rules), "All findings present.")
    require(packet["references"] == referenced, "Committed reference results.")
    require(all(r["status"]!="resolved" or all(b in read for b in r["path_block_ids"]) for r in referenced), "Complete resolved path reads.")
    unavailable=any(k not in resolved or resolved[k]["status"]!="resolved" for k in inventory)
    require(not unavailable or any(f["disposition"]=="uncertain" for f in packet["findings"]), "Unresolved inventory requires explicit unknown.")
    coverage_core = {"documents":[{"document_id": d["document_id"],"document_sha256":d["document_sha256"],
                     "read_block_ids":sorted(b for b in indexes[d["document_id"]] if b in read),
                     "total_blocks":len(indexes[d["document_id"]])} for d in packet["documents"]]}
    coverage_core["complete"] = all(len(d["read_block_ids"])==d["total_blocks"] for d in coverage_core["documents"])
    expected_coverage = {**coverage_core,"receipt_sha256":digest(canonical(coverage_core))}
    require(packet["coverage"]==expected_coverage, "Coverage receipt source/read binding.")
    patches = []
    allowed_statuses = {"compliant","deviation","missing","conflict","uncertain"}
    for finding in packet["findings"]:
        key = finding["rule_id"]
        require(finding==proposed[key], "Packet differs from committed finding.")
        require(set(finding)-{"coverage_receipt","investigation_links"}=={"rule_id","disposition","reason","obligations","evidence","policy_citation","patch"}
                and isinstance(finding["reason"],str) and 0<len(finding["reason"])<=400, "Exact bounded finding schema.")
        require(set(finding["obligations"])==set(policy_rules[key]["obligations"]) and
                set(finding["obligations"].values())<=allowed_statuses and finding["disposition"] in allowed_statuses, "Obligation schema.")
        statuses=set(finding["obligations"].values())
        require(statuses=={"compliant"} if finding["disposition"]=="compliant" else finding["disposition"] in statuses, "Disposition agrees with atoms.")
        require(isinstance(finding["evidence"],list) and len(finding["evidence"])<=6 and
                (finding["disposition"] not in ("compliant","deviation","conflict") or bool(finding["evidence"])), "Bounded required source evidence.")
        require(finding["policy_citation"]=={"playbook_id":policy["id"],"playbook_sha256":digest(case.policy_raw),
                  "rule_id":key,"quote":policy_rules[key]["text"]}, "Exact trusted policy citation.")
        for span in finding["evidence"]:
            require(set(span)==SPAN_KEYS and literal_valid(span,case.sources,indexes), "Literal quote/version/block fidelity.")
        if finding["disposition"]=="missing":
            require(finding.get("coverage_receipt")==expected_coverage and expected_coverage["complete"] is True and
                    not unavailable, "Absence coverage/unknown guard.")
        if finding["patch"] is not None:
            patch=finding["patch"]
            require(finding["disposition"] in ("deviation","missing") and patch["document_id"] in case.sources, "Patch authority.")
            if patch["start"]!=patch["end"]:
                require(any(s["document_id"]==patch["document_id"] and s["start"]<=patch["start"]<patch["end"]<=s["end"]
                            for s in finding["evidence"]), "Same-document cited patch.")
            else:
                choices=insertion_choices(policy_rules[key],case.sources["agreement"].decode(),indexes["agreement"],read)
                require(finding["disposition"]=="missing" and patch["document_id"]=="agreement" and
                        patch["replacement"] in choices.get(patch["start"],set()), "Trusted insertion at read boundary.")
            patches.append(patch)
        else:
            require(finding["disposition"]!="deviation", "Deviation requires a supported correction.")
    require(packet["patches"]==patches, "Complete ordered patch set.")
    handoff = any(f["disposition"] in ("uncertain","conflict") or f["disposition"]=="missing" and f["patch"] is None
                  for f in packet["findings"])
    require(packet["domain_status"]==("HANDOFF" if handoff else "PENDING_REVIEW"), "Domain status consistent with all findings.")
    require(trace[-1]["result"]=={"domain_status":packet["domain_status"]}, "Committed submission result.")
    checkpoint=db["checkpoint"]
    require(checkpoint is not None and checkpoint["registry"]["submitted"] is True and
            checkpoint["registry"]["findings"]==proposed and checkpoint["registry"]["blocks_read"]==read, "Committed final checkpoint.")
    require(checkpoint["registry"]["history"]==[{k:v for k,v in e.items() if k!="sequence"} for e in trace], "Observed checkpoint history.")
    require(db["intent_count"]==0 and len(db["actions"])==len(trace) and
            list(db["actions"].values())==checkpoint["registry"]["history"] and
            list(db["actions"])==[f"action-{i:04d}" for i in range(1,len(trace)+1)], "No missing/duplicated action commits.")
    require(usage["decision_calls"]==len(trace)==checkpoint["budget"]["calls"] and
            usage["tool_calls"]==len(trace) and usage["tool_execution_attempts"]==len(trace), "Persisted counts.")
    for key in ("decision_calls","tool_calls","tool_execution_attempts","action_replays",
                "provider_requests","model_calls","model_tokens","prompt_tokens","completion_tokens",
                "transient_retries","protocol_repairs"):
        require(type(usage[key]) is int and usage[key]>=0, "Exact nonnegative usage counters.")
    require(type(usage["elapsed_seconds"]) in (int,float) and math.isfinite(usage["elapsed_seconds"])
            and 0<=usage["elapsed_seconds"]<=120 and usage["decision_calls"]<=48, "Finite declared budget.")
    require(usage["model_calls"]==usage["provider_requests"]==usage["model_tokens"]==0 and
            usage["prompt_tokens"]==usage["completion_tokens"]==usage["action_replays"]==0 and
            usage["transient_retries"]==usage["protocol_repairs"]==0, "Offline usage and bounded errors.")
    require(set(artifact["previews"])==set(case.sources), "Preview scope.")
    for key,raw in case.sources.items():
        edits=[p for p in patches if p["document_id"]==key]
        require(artifact["previews"][key]==reconstruct(raw,edits), "Preview independently follows actual patches.")
    if approved:
        require(packet["domain_status"]=="PENDING_REVIEW" and db["state"]=="DRAFT_EXPORTED", "All-or-none approval state.")
        require(set(artifact["reviewed"])==set(case.sources) and db["drafts"]==artifact["reviewed"]==artifact["previews"], "Persisted/exported full reviewed bundle.")
        receipt=artifact["receipt"]
        require(receipt is not None and db["decision"]=={"kind":"approve","receipt":receipt}, "Stored review decision.")
        require(set(receipt)=={"schema_version","decision","reviewer_label","proposal_sha256","source_sha256",
                "reviewed_sha256","reviewed_documents","decided_at","state","fictional"} and
                receipt["schema_version"]==2 and receipt["fictional"] is True and receipt["state"]=="DRAFT_EXPORTED" and
                receipt["source_sha256"]==digest(case.sources["agreement"]) and isinstance(receipt["reviewer_label"],str) and
                0<len(receipt["reviewer_label"])<=120 and isinstance(receipt["decided_at"],str) and bool(receipt["decided_at"]), "Truthful complete review receipt.")
        require(receipt["decision"]=="approve" and receipt["proposal_sha256"]==packet["proposal_sha256"] and
                receipt["reviewed_documents"]=={key:digest(raw) for key,raw in artifact["reviewed"].items()} and
                receipt["reviewed_sha256"]==digest(artifact["reviewed"]["agreement"]), "Digest-bound approved bytes.")
        require(db["legacy_draft"]==artifact["reviewed"]["agreement"], "Legacy draft agrees.")
    else:
        require(not artifact["reviewed"] and artifact["receipt"] is None and db["decision"] is None and
                not db["drafts"] and db["legacy_draft"] is None and db["state"]==packet["domain_status"], "No unapproved exports.")
    return indexes


def assess(case, artifact, provider, *, approved):
    indexes={key:section_index(raw.decode(),key) for key,raw in case.sources.items()}
    integrity_error=None
    try:
        validate_integrity(case,artifact,provider,approved=approved)
    except (VerificationError,KeyError,TypeError,ValueError,IndexError) as exc:
        integrity_error=str(exc)
    metrics=semantic_metrics(case,artifact["packet"],indexes)
    previews,reviewed=artifact["previews"],artifact["reviewed"]
    try:
        protected,violating=protected_bytes(case,previews,artifact["packet"].get("patches",[]))
    except (VerificationError,KeyError,TypeError,ValueError):
        protected,violating=fraction(0,len(case.sources)),sum(map(len,case.sources.values()))
    export_required=case.labels["domain_status"]=="PENDING_REVIEW"
    exact_preview=sum(previews.get(key)==raw for key,raw in case.gold_bytes.items())
    exact_reviewed=sum(reviewed.get(key)==raw for key,raw in case.gold_bytes.items()) if export_required else 0
    reviewed_protected=fraction(0,len(case.sources) if export_required else 0)
    if approved:
        try:
            actual_protected,reviewed_violating=protected_bytes(case,reviewed,artifact["packet"].get("patches",[]))
        except (VerificationError,KeyError,TypeError,ValueError):
            actual_protected,reviewed_violating=fraction(0,len(case.sources)),sum(map(len,case.sources.values()))
        violating+=reviewed_violating
        if export_required: reviewed_protected=actual_protected
    bytes_ok=exact_preview==len(case.sources) and (not export_required or approved and exact_reviewed==len(case.sources))
    exact=integrity_error is None and metrics["semantic_correct"] and metrics["domain_correct"] and bytes_ok and violating==0
    return {**metrics,"oracle_version":ORACLE_VERSION,"case_id":case.case_id,"family":case.labels["family"],
            "integrity_error":integrity_error,"integrity_cases":fraction(int(integrity_error is None),1),
            "protected_documents":protected,"unrelated_violating_bytes":violating,
            "protected_reviewed_documents":reviewed_protected,
            "exact_preview_documents":fraction(exact_preview,len(case.sources)),
            "exact_reviewed_documents":fraction(exact_reviewed,len(case.sources) if export_required else 0),
            "exact_cases":fraction(int(exact),1),"operational_failures":0,
            "normalized_domain_sha256":normalized_digest(artifact["packet"],artifact["trace"],artifact["usage"],
                previews,reviewed,artifact["receipt"]),
            "decision_calls":artifact["usage"].get("decision_calls"),
            "tool_calls":artifact["usage"].get("tool_calls"),
            "elapsed_seconds":artifact["usage"].get("elapsed_seconds"),
            "provider_kind":provider,"model_quality_evaluated":False}


def require_exact(report):
    if report["exact_cases"]["numerator"] != 1:
        raise VerificationError("Independent false-success rejection: "+str(report["integrity_error"] or report["rule_errors"]))

"""Independent development outcome verifier: standard library only; never runs the actor."""
import hashlib
import json
from pathlib import Path
import re


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def blocks(text, key):
    matches = list(re.finditer(r"(?m)^Section ([0-9]+) - ([^\r\n]+)\r?$", text))
    starts = [(0, "preamble", "Preamble")] if matches[0].start() else []
    starts.extend((m.start(), m[1], m[2]) for m in matches)
    return {f"{key}.section-{section}": {"start": start,
            "end": starts[i+1][0] if i+1 < len(starts) else len(text), "title": title}
            for i, (start, section, title) in enumerate(starts)}


def verify(run: Path, root: Path, golden: dict, *, reviewed=False):
    count = 0
    def require(condition, message):
        nonlocal count
        count += 1
        if not condition:
            raise AssertionError(message)
    case = root / golden["fixture"]
    manifest = json.loads((case / "manifest.json").read_bytes())
    sources = {d["id"]: (case / d["file"]).read_bytes() for d in manifest["documents"]}
    texts = {key: raw.decode("utf-8") for key, raw in sources.items()}
    indexes = {key: blocks(text, key) for key, text in texts.items()}
    policy_raw = (root / golden["playbook"]).read_bytes()
    policy = json.loads(policy_raw)
    policy_rules = {r["id"]: r for r in policy["rules"]}
    packet = json.loads((run / "review.json").read_bytes())
    require(packet["provider_kind"] == "scripted" and packet["live_model"] is False, "Truthful offline labeling")
    require(packet["model_quality_evaluated"] is False, "No live quality claim")
    require(packet["domain_status"] == golden["domain_status"], "Wrong domain outcome")
    require(packet["manifest_sha256"] == digest((case / "manifest.json").read_bytes()), "Manifest version")
    require(packet["playbook"] == {"id": policy["id"], "sha256": digest(policy_raw)}, "Trusted policy version")
    require(packet["proposal_sha256"] == digest(canonical({k: v for k, v in packet.items() if k != "proposal_sha256"})), "Proposal digest")
    require({d["document_id"] for d in packet["documents"]} == set(sources), "Document scope")
    for d in packet["documents"]:
        key = d["document_id"]
        require(d["document_sha256"] == digest(sources[key]) and d["byte_length"] == len(sources[key]), "Source version/size")
        expected = [{"block_id": block_id, **value} for block_id, value in indexes[key].items()]
        require(d["blocks"] == expected, "Independent source block metadata")
    trace = [json.loads(line) for line in (run / "trace.jsonl").read_bytes().splitlines()]
    read, proposed = set(), {}
    allowed = {"get_rule", "search_clauses", "read_blocks", "scan_document", "resolve_reference", "propose_finding", "submit_review"}
    for event in trace:
        decision, result = event["decision"], event["result"]
        require(decision is not None and decision["tool"] in allowed, "Scripted trace authority")
        require(event["error"] is None, "Unexpected scripted tool rejection")
        if decision["tool"] in ("read_blocks", "scan_document"):
            require(result["complete"] is True, "Read output cannot truncate")
            for block in result["blocks"]:
                key = block["block_id"].split(".section-")[0]
                expected = indexes[key][block["block_id"]]
                require({k: block[k] for k in ("start", "end", "title")} == expected, "Read block location")
                require(block["text"] == texts[key][block["start"]:block["end"]], "Read block source bytes")
                read.add(block["block_id"])
        if decision["tool"] == "propose_finding":
            f = decision["arguments"]
            require(f["rule_id"] not in proposed, "Duplicate staged finding")
            require(all(block_id in read for key in sources if key != "agreement" for block_id in indexes[key]),
                    "All supplied amendment text read before proposals")
            require(all(s["block_id"] in read for s in f["evidence"]), "Citation must follow a complete read")
            proposed[f["rule_id"]] = f
    require(set(proposed) == set(golden["rules"]), "One observed finding for each rule")
    require(trace[-1]["decision"]["tool"] == "submit_review", "Explicit tool completion")
    require(len(packet["findings"]) == 3 and {f["rule_id"] for f in packet["findings"]} == set(golden["rules"]), "Complete findings")
    expected_patches, citation_count, coverage_count = [], 0, 0
    for finding in packet["findings"]:
        key = finding["rule_id"]
        expected = golden["rules"][key]
        require(finding == proposed[key], "Packet differs from committed proposal")
        require(finding["disposition"] == expected["disposition"], "Wrong rule disposition")
        require(finding["obligations"] == expected["obligations"], "Wrong obligation outcomes")
        require(finding["policy_citation"] == {"playbook_id": policy["id"], "playbook_sha256": digest(policy_raw),
                      "rule_id": key, "quote": policy_rules[key]["text"]}, "Policy citation")
        for span in finding["evidence"]:
            source_key = span["document_id"]
            require(source_key in sources and span["document_sha256"] == digest(sources[source_key]), "Evidence document version")
            require(type(span["start"]) is int and type(span["end"]) is int and
                      0 <= span["start"] < span["end"] <= len(texts[source_key]), "Evidence range")
            require(texts[source_key][span["start"]:span["end"]] == span["quote"], "Literal citation fidelity")
            block = indexes[source_key].get(span["block_id"])
            require(block is not None and block["start"] <= span["start"] < span["end"] <= block["end"], "Citation block")
            citation_count += 1
        for required in expected["evidence_required"]:
            require(any(all(span.get(k) == v for k, v in required.items()) for span in finding["evidence"]), "Missing independently labeled source support")
        require(finding["patch"] == expected["patch"], "Wrong localized correction")
        if expected["patch"] is not None:
            expected_patches.append(expected["patch"])
        if expected["coverage_required"]:
            receipt = finding.get("coverage_receipt")
            require(receipt == packet["coverage"] and receipt["complete"] is True, "Full current coverage required")
            require(receipt["receipt_sha256"] == digest(canonical({k: v for k, v in receipt.items() if k != "receipt_sha256"})), "Coverage digest")
            for document in receipt["documents"]:
                source_key = document["document_id"]
                require(document["document_sha256"] == digest(sources[source_key]), "Coverage source version")
                require(set(document["read_block_ids"]) == set(indexes[source_key]) and document["total_blocks"] == len(indexes[source_key]), "Full document coverage")
            require(all(reference["status"] == "resolved" for reference in packet["references"]), "Unknown evidence cannot become absence")
            coverage_count += 1
    require(packet["patches"] == expected_patches, "All-or-none ordered proposal patch set")
    for source_key, raw in sources.items():
        output = (run / "preview" / f"{source_key}.txt").read_bytes()
        expected_file = root / golden["reviewed_files"][source_key]["path"]
        require(output == expected_file.read_bytes() and digest(output) == golden["reviewed_files"][source_key]["sha256"], "Independent exact final preview")
        cursor, output_cursor = 0, 0
        for patch in sorted((p for p in expected_patches if p["document_id"] == source_key), key=lambda p: p["start"]):
            byte_start = len(texts[source_key][:patch["start"]].encode())
            byte_end = len(texts[source_key][:patch["end"]].encode())
            untouched = raw[cursor:byte_start]
            require(output[output_cursor:output_cursor+len(untouched)] == untouched, "Unrelated bytes changed")
            output_cursor += len(untouched) + len(patch["replacement"].encode())
            cursor = byte_end
        require(output[output_cursor:] == raw[cursor:], "Unrelated trailing bytes changed")
        for interval in golden["protected_intervals"][source_key]:
            original_slice = texts[source_key][interval["start"]:interval["end"]].encode()
            require(digest(original_slice) == interval["sha256"], "Protected gold interval version")
        exported = run / "reviewed" / f"{source_key}.txt"
        if reviewed:
            require(golden["domain_status"] == "PENDING_REVIEW" and exported.read_bytes() == output, "Approved final copy")
        else:
            require(not exported.exists(), "No export before explicit approval")
    return {"assertions": count, "rule_outcomes": 3, "source_citations": citation_count,
            "coverage_findings": coverage_count, "documents": len(sources), "unrelated_changed_bytes": 0}

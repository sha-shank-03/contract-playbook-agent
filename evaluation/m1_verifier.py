"""Exact authored outcomes; deliberately imports no production decision/patch code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_packet(run: Path, case_dir: Path, golden: dict, policy_path: Path,
                  expect_reviewed: bool = False) -> dict:
    checks = 0
    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    original = (case_dir / "agreement.txt").read_bytes()
    text = original.decode("utf-8")
    packet = json.loads((run / "review.json").read_bytes())
    expected_text = Path(golden["expected_file"]).read_bytes()
    require(packet["provider_kind"] == "scripted" and packet["live_model"] is False,
            "Offline provider labeling")
    require(packet["model_quality_evaluated"] is False, "No model-quality claim")
    require(packet["domain_status"] == "PENDING_REVIEW", "Expected pending review")
    require(packet["source"]["document_sha256"] == hashlib.sha256(original).hexdigest(),
            "Original source/version mismatch")
    require(packet["playbook"]["sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "Playbook version mismatch")
    core = {key: value for key, value in packet.items() if key != "proposal_sha256"}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    require(packet["proposal_sha256"] == digest, "Canonical proposal mismatch")
    policy = json.loads(policy_path.read_bytes())
    policy_rules = {rule["id"]: rule for rule in policy["rules"]}
    findings = packet["findings"]
    require(len(findings) == 3 and {f["rule_id"] for f in findings} == set(golden["rules"]),
            "Three independent expected rules")
    expected_patches = []
    citations = 0
    for finding in findings:
        expected = golden["rules"][finding["rule_id"]]
        require(finding["disposition"] == expected["disposition"], "Incorrect disposition")
        require(finding["obligations"] == expected["obligations"], "Incorrect obligation outcomes")
        citation = finding["policy_citation"]
        require(citation == {"playbook_id": policy["id"],
                             "playbook_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                             "rule_id": finding["rule_id"],
                             "quote": policy_rules[finding["rule_id"]]["text"]},
                "Unsupported policy citation")
        require(len(finding["evidence"]) == 1, "One exact authored evidence span required")
        evidence = finding["evidence"][0]
        sentence = expected["source_sentence"]
        require(text.count(sentence) == 1, "Ambiguous gold source sentence")
        position = text.index(sentence)
        require((evidence["start"], evidence["end"], evidence["quote"]) ==
                (position, position + len(sentence), sentence), "Incorrect source support")
        require(evidence["document_id"] == "agreement" and
                evidence["document_sha256"] == hashlib.sha256(original).hexdigest(),
                "Citation source version")
        citations += 2
        if expected["edit"] is not None:
            edit = expected["edit"]
            start = position + sentence.index(edit["old"])
            expected_patches.append({"document_id": "agreement",
                                     "document_sha256": hashlib.sha256(original).hexdigest(),
                                     "start": start, "end": start + len(edit["old"]),
                                     "expected_text": edit["old"], "replacement": edit["new"]})
            require(finding["patch"] == expected_patches[-1], "Wrong localized rule patch")
        else:
            require(finding["patch"] is None, "Compliant rule was edited")
    require(packet["patches"] == expected_patches, "Wrong ordered patch set")
    preview = (run / "preview" / "agreement.txt").read_bytes()
    require(preview == expected_text, "Preview differs from independent golden final text")
    # Independently compare original intervals outside gold edits with output intervals.
    original_cursor = preview_cursor = 0
    for edit in sorted(expected_patches, key=lambda item: item["start"]):
        before = text[:edit["start"]].encode("utf-8")
        after = text[:edit["end"]].encode("utf-8")
        unchanged = original[original_cursor:len(before)]
        require(preview[preview_cursor:preview_cursor + len(unchanged)] == unchanged,
                "Unrelated bytes changed")
        preview_cursor += len(unchanged) + len(edit["replacement"].encode("utf-8"))
        original_cursor = len(after)
    require(preview[preview_cursor:] == original[original_cursor:], "Unrelated trailing bytes changed")
    reviewed = run / "reviewed" / "agreement.txt"
    if expect_reviewed:
        require(reviewed.read_bytes() == expected_text, "Approved copy differs from golden")
        receipt = json.loads((run / "review-receipt.json").read_bytes())
        require(receipt["decision"] == "approve" and receipt["proposal_sha256"] == digest,
                "Approval did not bind the exact proposal")
        require(receipt["reviewed_sha256"] == hashlib.sha256(expected_text).hexdigest(),
                "Reviewed artifact receipt hash")
    else:
        require(not reviewed.exists(), "Draft exported before approval")
    trace = [json.loads(line) for line in (run / "trace.jsonl").read_bytes().splitlines()]
    for rule_id in golden["rules"]:
        relevant = [event for event in trace if event["decision"]["arguments"].get("rule_id") == rule_id]
        require([event["decision"]["tool"] for event in relevant] ==
                ["get_rule", "search_clauses", "propose_finding"], "Real ordered rule tools")
        proposed_seq = relevant[-1]["sequence"]
        source_block = next(f for f in findings if f["rule_id"] == rule_id)["evidence"][0]["block_id"]
        require(any(event["sequence"] < proposed_seq and
                    event["decision"]["tool"] == "read_blocks" and
                    source_block in event["decision"]["arguments"]["block_ids"] for event in trace),
                "Source read missing before proposal")
    require(trace[-1]["decision"]["tool"] == "submit_review", "Tool completion boundary")
    return {"assertions": checks, "rule_dispositions": 3, "supported_citations": citations,
            "gold_expected_patches": len(expected_patches), "unrelated_changed_bytes": 0}


"""Independent U1 mechanical verifier: stdlib only, no actor/tool/edit imports.

This verifies provenance and copy state, never semantic or legal correctness.
"""
from __future__ import annotations

import hashlib
import json
import re


class ProposalInvalid(ValueError):
    pass


def _require(condition):
    if not condition:
        raise ProposalInvalid("PROPOSAL_MECHANICAL_CHECK_FAILED")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def check_receipt(receipt, packet, report):
    _require(isinstance(receipt, dict) and receipt.get("decision") == "approve"
             and receipt.get("fictional") is True
             and receipt.get("proposal_sha256") == packet["proposal_sha256"]
             and receipt.get("source_sha256") == report["source_sha256"]
             and receipt.get("reviewed_documents") == {"agreement": report["expected_copy_sha256"]})
    return {"approval_binding": "passed", "reviewer_identity": "unauthenticated_annotation"}


def check_proposal(packet, originals, policy_raw, manifest_raw, *, previews=None, reviewed=None):
    try:
        return _check(packet, originals, policy_raw, manifest_raw, previews=previews, reviewed=reviewed)
    except ProposalInvalid:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ProposalInvalid("PROPOSAL_MECHANICAL_CHECK_FAILED") from None


def _check(packet, originals, policy_raw, manifest_raw, *, previews=None, reviewed=None):
    _require(isinstance(packet, dict) and packet.get("schema_version") == 3
             and packet.get("fictional") is True and packet.get("execution_mode") == "local-double"
             and packet.get("live_model") is False)
    core = {key: value for key, value in packet.items() if key != "proposal_sha256"}
    _require(packet.get("proposal_sha256") == _hash(_canonical(core)))
    _require(packet.get("manifest_sha256") == _hash(manifest_raw))
    policy = json.loads(policy_raw)
    rules = {r["id"]: r for r in policy["rules"]}
    _require(set(rules) == {"REN-01", "TERM-01", "PAY-01"})
    _require(packet.get("playbook") == {"id": policy["id"], "sha256": _hash(policy_raw)})
    _require(set(originals) == {"agreement"})  # U1 is deliberately one base document.
    documents = packet.get("documents")
    _require(isinstance(documents, list) and len(documents) == 1)
    doc = documents[0]
    raw = originals["agreement"]
    text = raw.decode("utf-8")
    _require(doc.get("document_id") == "agreement" and doc.get("document_sha256") == _hash(raw)
             and doc.get("byte_length") == len(raw) and packet.get("source") == doc)
    headings = list(re.finditer(r"(?m)^Section ([0-9]+) - ([^\r\n]+)\r?$", text))
    _require(bool(headings))
    starts = [(0, "preamble", "Preamble")] if headings[0].start() else []
    starts += [(m.start(), m[1], m[2]) for m in headings]
    expected_blocks = [{"block_id": "agreement.section-" + section, "title": title,
                        "start": start, "end": starts[i + 1][0] if i + 1 < len(starts) else len(text)}
                       for i, (start, section, title) in enumerate(starts)]
    _require(doc.get("blocks") == expected_blocks)
    coverage = packet.get("coverage")
    coverage_core = {"documents": [{"document_id": "agreement", "document_sha256": _hash(raw),
                      "read_block_ids": sorted(b["block_id"] for b in expected_blocks),
                      "total_blocks": len(expected_blocks)}], "complete": True}
    _require(coverage == {**coverage_core, "receipt_sha256": _hash(_canonical(coverage_core))})
    blocks = {b["block_id"]: b for b in expected_blocks}
    findings = packet.get("findings")
    _require(isinstance(findings, list) and len(findings) == 3
             and {f.get("rule_id") for f in findings} == set(rules))
    all_patches = []
    handoff = False
    for finding in findings:
        rule = rules[finding["rule_id"]]
        status = finding.get("disposition")
        _require(status in {"compliant", "deviation", "uncertain"})
        handoff |= status == "uncertain"
        _require(finding.get("policy_citation") == {
            "playbook_id": policy["id"], "playbook_sha256": _hash(policy_raw),
            "rule_id": rule["id"], "quote": rule["text"]})
        atoms = finding.get("obligations")
        _require(isinstance(atoms, dict) and set(atoms) == set(rule["obligations"])
                 and set(atoms.values()) <= {"compliant", "deviation", "uncertain"}
                 and (set(atoms.values()) == {"compliant"} if status == "compliant" else status in atoms.values()))
        evidence = finding.get("evidence")
        _require(isinstance(evidence, list) and len(evidence) <= 6
                 and (bool(evidence) or status == "uncertain"))
        for span in evidence:
            _require(isinstance(span, dict) and set(span) == {
                "document_id", "document_sha256", "block_id", "start", "end", "quote"})
            start, end = span["start"], span["end"]
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text))
            block = blocks.get(span["block_id"])
            _require(block is not None and block["start"] <= start < end <= block["end"]
                     and span["document_id"] == "agreement" and span["document_sha256"] == _hash(raw)
                     and text[start:end] == span["quote"])
        patch = finding.get("patch")
        if patch is None:
            _require(status != "deviation")
            continue
        _require(status == "deviation" and isinstance(patch, dict) and set(patch) == {
            "document_id", "document_sha256", "start", "end", "expected_text", "replacement"})
        start, end = patch["start"], patch["end"]
        _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text))
        _require(patch["document_id"] == "agreement" and patch["document_sha256"] == _hash(raw)
                 and text[start:end] == patch["expected_text"]
                 and isinstance(patch["replacement"], str) and 0 < len(patch["replacement"]) <= 1000
                 and len(patch["expected_text"]) <= 800)
        _require(any(s["start"] <= start < end <= s["end"] for s in evidence))
        all_patches.append(patch)
    _require(packet.get("patches") == all_patches)
    _require(packet.get("domain_status") == ("HANDOFF" if handoff else "PENDING_REVIEW"))
    ordered = sorted(all_patches, key=lambda p: p["start"])
    _require(len(ordered) <= 8 and sum(p["end"] - p["start"] + len(p["replacement"]) for p in ordered) <= 4000)
    output, cursor = bytearray(), 0
    char_end = 0
    for patch in ordered:
        _require(patch["start"] >= char_end)
        start = len(text[:patch["start"]].encode("utf-8"))
        end = len(text[:patch["end"]].encode("utf-8"))
        output.extend(raw[cursor:start])
        output.extend(patch["replacement"].encode("utf-8"))
        cursor, char_end = end, patch["end"]
    output.extend(raw[cursor:])
    expected = bytes(output)
    for copies in (previews, reviewed):
        if copies is not None:
            _require(set(copies) == {"agreement"} and copies["agreement"] == expected)
    if reviewed is not None:
        _require(not handoff)
    return {"schema_version": 1, "mechanical_verification": "passed",
            "source_sha256": _hash(raw), "expected_copy_sha256": _hash(expected),
            "patch_count": len(ordered), "unrelated_byte_changes": 0,
            "semantic_correctness": "unassessed", "legal_correctness": "unproven",
            "reviewed_copy_verified": reviewed is not None}

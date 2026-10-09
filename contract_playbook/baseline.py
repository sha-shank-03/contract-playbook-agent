"""Declared fixed keyword baseline; same host tools/guards, no label or reference access."""
from __future__ import annotations

import re

BASELINE_VERSION = "keyword-v1"


class KeywordBaseline:
    kind = "keyword"

    def next(self, observation, remaining_budget):
        # One fixed complete scan schedule. No resolve_reference action is selected.
        for document in observation["documents"]:
            for cursor, block in enumerate(document["blocks"]):
                if block["block_id"] not in observation["blocks_read"]:
                    return {"tool": "scan_document", "arguments": {
                        "document_id": document["document_id"], "cursor": cursor}}
        for rule_id in observation["rule_ids"]:
            if rule_id not in observation["rules_read"]:
                return {"tool": "get_rule", "arguments": {"rule_id": rule_id}}
        for rule_id in observation["rule_ids"]:
            if rule_id not in observation["searches"]:
                return {"tool": "search_clauses", "arguments": {"rule_id": rule_id}}
        for rule_id in observation["rule_ids"]:
            if rule_id in observation["findings"]:
                continue
            rule = observation["rules_read"][rule_id]
            flag = observation["search_flags"][rule_id]
            if flag["status"] == "conflict":
                finding = self.unknown(rule, "The host reports competing replacements.")
                finding["disposition"] = "conflict"
                finding["obligations"] = {atom: "conflict" for atom in rule["obligations"]}
                finding["evidence"] = [edge["evidence"] for edge in flag["links"]]
            elif flag["status"] == "unknown" or flag["links"]:
                finding = self.unknown(rule, "Fixed baseline does not investigate amendment meaning.")
                finding["evidence"] = [edge["evidence"] for edge in flag["links"]][:6]
            else:
                candidates = [block for block in observation["blocks_read"].values()
                              if block["block_id"].startswith("agreement.")
                              and rule["topic"] in block["title"].casefold()]
                source_ids = {item["source_block_id"] for item in observation["reference_inventory"]}
                topical_ids = {block["block_id"] for block in observation["blocks_read"].values()
                               if any(r["topic"] in block["title"].casefold()
                                      for r in observation["rules_read"].values())}
                if any(block["block_id"] in source_ids for block in candidates) or (
                        rule_id == observation["rule_ids"][-1] and source_ids and not source_ids & topical_ids):
                    finding = self.unknown(rule, "Fixed baseline does not follow literal references.")
                    relevant = {b["block_id"] for b in candidates} or source_ids
                    for reference in observation["reference_inventory"]:
                        if reference["source_block_id"] not in relevant:
                            continue
                        block = observation["blocks_read"][reference["source_block_id"]]
                        key = block["block_id"].split(".section-")[0]
                        source = next(d for d in observation["documents"] if d["document_id"] == key)
                        body_start = block["text"].find("\n") + 1 if block["text"].startswith("Section ") else 0
                        local = block["text"].find(reference["reference"], body_start)
                        finding["evidence"].append({"document_id": key, "document_sha256": source["document_sha256"],
                            "block_id": block["block_id"], "start": block["start"] + local,
                            "end": block["start"] + local + len(reference["reference"]), "quote": reference["reference"]})
                        if len(finding["evidence"]) == 6:
                            break
                else:
                    finding = (self.direct(rule, candidates[0], observation["document"])
                           if len(candidates) == 1 else
                           self.unknown(rule, "No unique direct topic heading in fixed scan."))
            return {"tool": "propose_finding", "arguments": finding}
        return {"tool": "submit_review", "arguments": {}}

    @staticmethod
    def unknown(rule, reason):
        return {"rule_id": rule["id"], "disposition": "uncertain", "reason": reason,
                "obligations": {atom: "uncertain" for atom in rule["obligations"]},
                "evidence": [], "policy_citation": rule["policy_citation"], "patch": None}

    def direct(self, rule, block, source):
        text = block["text"]
        sentences = list(re.finditer(r"[^\r\n]+\.", text))
        key = rule["id"]
        keywords = {"REN-01": ("term", "renews"), "TERM-01": ("Customer", "convenience"),
                    "PAY-01": ("Undisputed", "invoices")}[key]
        candidates = [m for m in sentences if all(word in m.group() for word in keywords)]
        if len(candidates) != 1:
            return self.unknown(rule, "Fixed keyword sentence match is absent or ambiguous.")
        sentence = candidates[0]
        old, new, start, end, atom = None, None, None, None, None
        if key == "REN-01":
            if "automatically" in sentence.group():
                start, end, old = sentence.start(), sentence.end(), sentence.group()
                new, atom = rule["approved_renewal_sentence"], rule["obligations"][0]
            elif "express written agreement of both parties" not in sentence.group():
                return self.unknown(rule, "Fixed renewal keywords do not settle this sentence.")
        else:
            suffix = "calendar days' written notice" if key == "TERM-01" else "calendar days after receipt by the Customer"
            match = re.search(r"(?P<days>[0-9]{1,3}) " + re.escape(suffix), sentence.group())
            if match is None or int(match["days"]) == 0:
                return self.unknown(rule, "Fixed scan lacks a supported day/notice/receipt phrase.")
            days = int(match["days"])
            differs = days > rule["limit_days"] if key == "TERM-01" else days < rule["limit_days"]
            if differs:
                start = sentence.start() + match.start("days")
                end = sentence.start() + match.end("days")
                old, new, atom = match["days"], str(rule["limit_days"]), rule["obligations"][-1]
        span = {"document_id": "agreement", "document_sha256": source["document_sha256"],
                "block_id": block["block_id"], "start": block["start"] + sentence.start(),
                "end": block["start"] + sentence.end(), "quote": sentence.group()}
        patch = None if old is None else {
            "document_id": "agreement", "document_sha256": source["document_sha256"],
            "start": block["start"] + start, "end": block["start"] + end,
            "expected_text": old, "replacement": new}
        return {"rule_id": key, "disposition": "deviation" if patch else "compliant",
                "reason": "Fixed direct keyword/number scan.",
                "obligations": {item: "deviation" if item == atom else "compliant" for item in rule["obligations"]},
                "evidence": [span], "policy_citation": rule["policy_citation"], "patch": patch}

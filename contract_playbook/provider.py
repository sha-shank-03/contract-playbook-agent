"""A genuine decision boundary; the default policy is explicitly scripted."""
from __future__ import annotations

import re
from typing import Protocol

from .common import ReviewError

AUTO = "The term renews automatically for successive one-year periods unless either party gives notice."
WRITTEN = "The term renews only by express written agreement of both parties."
TERM = re.compile(r"The Customer may terminate this Agreement for convenience on (?P<days>[0-9]{1,3}) calendar days' written notice to the Supplier\.")
PAY = re.compile(r"Undisputed invoices are payable (?P<days>[0-9]{1,3}) calendar days after receipt by the Customer\.")


class DecisionProvider(Protocol):
    kind: str

    def next(self, observation: dict, remaining_budget: dict) -> dict: ...


class ScriptedDecisionProvider:
    kind = "scripted"

    def next(self, observation: dict, remaining_budget: dict) -> dict:
        # Read every supplied amendment before finalizing any policy interpretation.
        for document in observation["documents"][1:]:
            unread = [b for b in document["blocks"] if b["block_id"] not in observation["blocks_read"]]
            if unread:
                return {"tool": "scan_document", "arguments": {"document_id": document["document_id"],
                        "cursor": document["blocks"].index(unread[0])}}
        # Literal references are source data, never instructions or extra authority.
        for reference in observation["reference_inventory"]:
            block_id, literal = reference["source_block_id"], reference["reference"]
            if block_id not in observation["blocks_read"]:
                return {"tool": "read_blocks", "arguments": {"block_ids": [block_id]}}
            result = observation["references"].get(block_id + "|" + literal)
            if result is None:
                return {"tool": "resolve_reference", "arguments": {"source_block_id": block_id, "reference": literal}}
            if result["status"] == "resolved":
                for target in result["path_block_ids"]:
                    if target not in observation["blocks_read"]:
                        return {"tool": "read_blocks", "arguments": {"block_ids": [target]}}
        for rule_id in observation["rule_ids"]:
            if rule_id in observation["findings"]:
                continue
            if rule_id not in observation["rules_read"]:
                return {"tool": "get_rule", "arguments": {"rule_id": rule_id}}
            if rule_id not in observation["searches"]:
                return {"tool": "search_clauses", "arguments": {"rule_id": rule_id}}
            rule = observation["rules_read"][rule_id]
            flag = observation["search_flags"][rule_id]
            if flag["status"] == "conflict":
                decision = self._uncertain(rule, "Competing amendments have no explicit precedence.")
                finding = decision["arguments"]
                finding["disposition"] = "conflict"
                finding["obligations"] = {atom: "conflict" for atom in rule["obligations"]}
                finding["evidence"] = [edge["evidence"] for edge in flag["links"]]
                finding["investigation_links"] = flag["links"]
                return decision
            if flag["status"] == "unknown":
                decision = self._uncertain(rule, "Referenced amendment evidence is unavailable.")
                decision["arguments"]["evidence"] = [edge["evidence"] for edge in flag["links"]][:6]
                decision["arguments"]["investigation_links"] = flag["links"]
                return decision
            hits = observation["searches"][rule_id]
            if len(hits) > 1:
                return self._uncertain(rule, "Multiple direct clauses need human interpretation.")
            if not hits:
                scan = self._scan_remaining(observation)
                if scan:
                    return scan
                if any(result["status"] != "resolved" for result in observation["references"].values()):
                    return self._uncertain(rule, "Missing referenced evidence is unknown, not absence.")
                candidates = []
                for block in observation["blocks_read"].values():
                    if not block["block_id"].startswith("agreement."):
                        continue
                    direct = self._classify(rule, block, observation["document"])
                    if direct["arguments"]["disposition"] != "uncertain":
                        candidates.append(direct)
                if len(candidates) == 1:
                    return candidates[0]
                if candidates:
                    return self._uncertain(rule, "Multiple relocated clauses are ambiguous.")
                keywords = {"REN-01": ("renew",), "TERM-01": ("terminat",), "PAY-01": ("invoic",)}
                if any(word in block["text"].casefold() for word in keywords[rule_id]
                       for block in observation["blocks_read"].values()
                       if not block["title"].casefold().startswith("preamble")):
                    return self._uncertain(rule, "Potential clause uses unsupported wording.")
                return self._missing(rule, observation)
            block_id = hits[0]["block_id"]
            if block_id not in observation["blocks_read"]:
                return {"tool": "read_blocks", "arguments": {"block_ids": [block_id]}}
            block = observation["blocks_read"][block_id]
            links = list(flag["links"])
            references = [r for r in observation["reference_inventory"] if r["source_block_id"] == block_id]
            if references:
                if len(references) != 1:
                    return self._uncertain(rule, "Multiple clause references are ambiguous.")
                ref = references[0]
                result = observation["references"][block_id + "|" + ref["reference"]]
                if result["status"] != "resolved":
                    decision = self._uncertain(rule, result.get("reason", "Unavailable referenced evidence."))
                    decision["arguments"]["evidence"] = [result["evidence"]]
                    return decision
                links.extend({"evidence": span, "path_block_ids": result["path_block_ids"]}
                             for span in result["reference_evidence"])
                links.extend(result["links"])
                block = observation["blocks_read"][result["block_id"]]
            document_id = block["block_id"].split(".section-")[0]
            source = next(doc for doc in observation["documents"] if doc["document_id"] == document_id)
            partial = self._partial_missing(rule, block, source, observation)
            if partial is not None:
                if partial["tool"] == "propose_finding" and links:
                    partial["arguments"]["investigation_links"] = links
                    for link in links:
                        if link["evidence"] not in partial["arguments"]["evidence"]:
                            partial["arguments"]["evidence"].append(link["evidence"])
                return partial
            decision = self._classify(rule, block, source)
            if links:
                finding = decision["arguments"]
                for link in links:
                    if link["evidence"] not in finding["evidence"]:
                        finding["evidence"].append(link["evidence"])
                finding["investigation_links"] = links
                if len(finding["evidence"]) > 6:
                    return self._uncertain(rule, "Evidence chain exceeds the bounded citation budget.")
            return decision
        return {"tool": "submit_review", "arguments": {}}

    @staticmethod
    def _scan_remaining(observation):
        for document in observation["documents"]:
            for cursor, block in enumerate(document["blocks"]):
                if block["block_id"] not in observation["blocks_read"]:
                    return {"tool": "scan_document", "arguments": {"document_id": document["document_id"], "cursor": cursor}}
        return None

    def _missing(self, rule, observation):
        finding = self._uncertain(rule, "Required wording was not found after complete supplied-text coverage.")["arguments"]
        finding["disposition"] = "missing"
        finding["obligations"] = {atom: "missing" for atom in rule["obligations"]}
        finding["coverage_receipt"] = observation["coverage"]
        source = observation["document"]
        anchor_id = f"agreement.section-{rule.get('insertion_before_section')}"
        anchor = observation["blocks_read"].get(anchor_id)
        default_id = f"agreement.section-{rule.get('default_section')}"
        if anchor and "approved_insertion_sentence" in rule and default_id not in observation["blocks_read"]:
            replacement = f"Section {rule['default_section']} - {rule['topic'].title()}\n{rule['approved_insertion_sentence']}\n\n"
            finding["patch"] = {"document_id": "agreement", "document_sha256": source["document_sha256"],
                                "start": anchor["start"], "end": anchor["start"],
                                "expected_text": "", "replacement": replacement}
        return {"tool": "propose_finding", "arguments": finding}

    def _partial_missing(self, rule, block, source, observation):
        text = block["text"]
        missing_atom = None
        match = None
        if rule["id"] == "TERM-01":
            match = re.search(r"The Customer may terminate this Agreement for convenience on (?P<days>[0-9]{1,3}) calendar days' (?P<notice>notice) to the Supplier\.", text)
            missing_atom = "termination.written_notice"
        elif rule["id"] == "PAY-01":
            match = re.search(r"Undisputed invoices are payable (?P<days>[0-9]{1,3}) (?P<timing>calendar days)\.", text)
            missing_atom = "payment.receipt_trigger"
        if match is None:
            return None
        scan = self._scan_remaining(observation)
        if scan:
            return scan
        if any(result["status"] != "resolved" for result in observation["references"].values()):
            return self._uncertain(rule, "Unavailable references forbid a missing-obligation claim.")
        statuses = {atom: "missing" if atom == missing_atom else "compliant" for atom in rule["obligations"]}
        days = int(match["days"])
        if days == 0:
            return self._uncertain(rule, "Zero-day timing needs human interpretation.")
        if rule["id"] == "TERM-01":
            begin, end = match.start("notice"), match.end("notice")
            replacement = "written notice"
            if days > rule["limit_days"]:
                statuses["termination.notice_days"] = "deviation"
                begin = match.start("days")
                replacement = "30 calendar days' written notice"
        else:
            begin, end = match.start("timing"), match.end("timing")
            replacement = "calendar days after receipt by the Customer"
            if days < rule["limit_days"]:
                statuses["payment.days"] = "deviation"
                begin = match.start("days")
                replacement = "30 calendar days after receipt by the Customer"
        span = {"document_id": source["document_id"], "document_sha256": source["document_sha256"],
                "block_id": block["block_id"], "start": block["start"] + match.start(),
                "end": block["start"] + match.end(), "quote": match.group()}
        patch = {"document_id": source["document_id"], "document_sha256": source["document_sha256"],
                 "start": block["start"] + begin, "end": block["start"] + end,
                 "expected_text": text[begin:end], "replacement": replacement}
        return {"tool": "propose_finding", "arguments": {
            "rule_id": rule["id"], "disposition": "missing", "reason": "A supported clause omits a required obligation.",
            "obligations": statuses, "evidence": [span], "policy_citation": rule["policy_citation"],
            "patch": patch, "coverage_receipt": observation["coverage"]}}

    @staticmethod
    def _uncertain(rule: dict, reason: str):
        return {"tool": "propose_finding", "arguments": {
            "rule_id": rule["id"], "disposition": "uncertain", "reason": reason,
            "obligations": {atom: "uncertain" for atom in rule["obligations"]},
            "evidence": [], "policy_citation": rule["policy_citation"], "patch": None}}

    def _classify(self, rule, block, source):
        text, rule_id = block["text"], rule["id"]
        fragment = None
        replacement = None
        deviating_atom = None
        if rule_id == "REN-01":
            # Supported sentences are deliberately narrow; no general legal interpretation.
            matches = [(m.start(), m.end(), m.group()) for m in re.finditer(
                re.escape(AUTO) + "|" + re.escape(WRITTEN), text)]
            if len(matches) != 1:
                return self._uncertain(rule, "Renewal wording is outside the supported direct form.")
            start, end, sentence = matches[0]
            if sentence == AUTO:
                fragment = (start, end, sentence)
                replacement = rule["approved_renewal_sentence"]
                deviating_atom = rule["obligations"][0]
        else:
            pattern = TERM if rule_id == "TERM-01" else PAY
            matches = list(pattern.finditer(text))
            if len(matches) != 1:
                return self._uncertain(rule, "Clause wording is outside the supported direct form.")
            match = matches[0]
            start, end, sentence = match.start(), match.end(), match.group()
            days = int(match.group("days"))
            if days == 0:
                return self._uncertain(rule, "Zero-day timing requires human interpretation.")
            deviation = days > rule["limit_days"] if rule_id == "TERM-01" else days < rule["limit_days"]
            if deviation:
                fragment = (match.start("days"), match.end("days"), match.group("days"))
                replacement = str(rule["limit_days"])
                deviating_atom = rule["obligations"][-1]
        evidence = {"document_id": source["document_id"],
                    "document_sha256": source["document_sha256"], "block_id": block["block_id"],
                    "start": block["start"] + start, "end": block["start"] + end, "quote": sentence}
        patch = None
        if fragment is not None:
            patch = {"document_id": source["document_id"],
                     "document_sha256": source["document_sha256"],
                     "start": block["start"] + fragment[0], "end": block["start"] + fragment[1],
                     "expected_text": fragment[2], "replacement": replacement}
        statuses = {atom: "deviation" if atom == deviating_atom else "compliant"
                    for atom in rule["obligations"]}
        return {"tool": "propose_finding", "arguments": {
            "rule_id": rule_id, "disposition": "deviation" if patch else "compliant",
            "reason": "Direct supported wording differs from the fictional playbook."
                      if patch else "Direct supported wording satisfies the fictional playbook.",
            "obligations": statuses, "evidence": [evidence],
            "policy_citation": rule["policy_citation"], "patch": patch}}


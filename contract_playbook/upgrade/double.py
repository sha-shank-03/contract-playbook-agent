"""Exposed authored in-memory double for one fictional U1 journey, not a model."""
from __future__ import annotations

import json

from ..common import canonical
from ..providers.gateway import GatewayFailure


class FictionalGatewayDouble:
    mode = "local-double"

    def request(self, endpoint, request, remaining_seconds, cancel):
        if cancel():
            raise KeyboardInterrupt()
        if remaining_seconds <= 0:
            raise GatewayFailure("DEADLINE_EXHAUSTED")
        state = json.loads(request["messages"][1]["content"])
        observation, budget = state["observation"], state["remaining_budget"]
        rule_ids = observation["rule_ids"]
        # This exposed scripted double reacts to committed observations only.
        for rule_id in rule_ids:
            if rule_id not in observation["rules_read"]:
                return self._reply(request, budget, "get_rule", {"rule_id": rule_id})
        for rule_id in rule_ids:
            if rule_id not in observation["searches"]:
                return self._reply(request, budget, "search_clauses", {"rule_id": rule_id})
        unread = [b["block_id"] for d in observation["documents"] for b in d["blocks"]
                  if b["block_id"] not in observation["blocks_read"]]
        if unread:
            return self._reply(request, budget, "read_blocks", {"block_ids": unread[:6]})
        for rule_id in rule_ids:
            if rule_id in observation["findings"]:
                continue
            rule = observation["rules_read"][rule_id]
            block = observation["blocks_read"]["agreement.section-" + str(rule["default_section"])]
            clause = block["text"].split("\n", 1)[1].strip()
            start = block["start"] + block["text"].index(clause)
            doc = observation["documents"][0]
            span = {"document_id": "agreement", "document_sha256": doc["document_sha256"],
                    "block_id": block["block_id"], "start": start, "end": start + len(clause),
                    "quote": clause}
            atoms = {key: "compliant" for key in rule["obligations"]}
            if rule_id == "REN-01":
                if "rolls into another" not in clause:
                    raise GatewayFailure("DOUBLE_SCENARIO_MISMATCH")
                old, replacement = clause, rule["approved_renewal_sentence"]
                atoms["renewal.express_written_agreement"] = "deviation"
            elif rule_id == "TERM-01":
                old, replacement = "sixty", "thirty"
                atoms["termination.notice_days"] = "deviation"
            else:
                old, replacement = "fifteen", "thirty"
                atoms["payment.days"] = "deviation"
            if old not in clause:
                raise GatewayFailure("DOUBLE_SCENARIO_MISMATCH")
            patch_start = start + clause.index(old)
            patch = {"document_id": "agreement", "document_sha256": doc["document_sha256"],
                     "start": patch_start, "end": patch_start + len(old),
                     "expected_text": old, "replacement": replacement}
            finding = {"rule_id": rule_id, "disposition": "deviation",
                       "reason": "Authored double: this fictional clause conflicts with the stated buyer preference.",
                       "obligations": atoms, "evidence": [span],
                       "policy_citation": rule["policy_citation"], "patch": patch}
            return self._reply(request, budget, "propose_finding", finding)
        return self._reply(request, budget, "submit_review", {})

    @staticmethod
    def _reply(request, budget, name, arguments):
        index = budget["attempt"]
        return canonical({"id": f"double_{index}", "model": request["model"],
                          "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                              "role": "assistant", "content": None, "tool_calls": [{
                                  "id": f"call_double_{index}", "type": "function", "function": {
                                      "name": name, "arguments": canonical(arguments).decode("utf-8")}}]}}]})

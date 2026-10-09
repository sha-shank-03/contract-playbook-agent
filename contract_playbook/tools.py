"""Allowlisted investigation/proposal tools; source instructions have no authority."""
from __future__ import annotations

from copy import deepcopy

from .bundle import Bundle, REFERENCE, as_bundle, block_references, effective_section, reference_inventory, replacement_edges, section_block, source_span
from .common import ReviewError, canonical, exact_keys, sha256, string
from .ingest import Document, document_metadata
from .patches import validate_patch, validate_span
from .playbook import Playbook, RULE_IDS

TOOL_NAMES = ("get_rule", "search_clauses", "read_blocks", "scan_document",
              "resolve_reference", "propose_finding", "submit_review")
FINDING_KEYS = {"rule_id", "disposition", "reason", "obligations", "evidence", "policy_citation", "patch"}
POLICY_KEYS = {"playbook_id", "playbook_sha256", "rule_id", "quote"}
TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": name, "description": description,
      "parameters": {"type": "object", "properties": properties,
                     "required": required, "additionalProperties": False}}}
    for name, description, properties, required in [
        ("get_rule", "Read trusted fictional rule.", {"rule_id": {"type": "string"}}, ["rule_id"]),
        ("search_clauses", "Locate effective clause and replacement links.", {"rule_id": {"type": "string"}}, ["rule_id"]),
        ("read_blocks", "Read complete untrusted source blocks.", {"block_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6}}, ["block_ids"]),
        ("scan_document", "Read next complete coverage page.", {"document_id": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}}, ["document_id", "cursor"]),
        ("resolve_reference", "Resolve literal reference in read block.", {"source_block_id": {"type": "string"}, "reference": {"type": "string"}}, ["source_block_id", "reference"]),
        ("propose_finding", "Stage cited findings and localized patches; never approve.",
         {"rule_id": {"type": "string"}, "disposition": {"type": "string", "enum": ["compliant", "deviation", "missing", "conflict", "uncertain"]},
          "reason": {"type": "string"}, "obligations": {"type": "object"}, "evidence": {"type": "array", "items": {"type": "object"}},
          "policy_citation": {"type": "object"}, "patch": {"type": ["object", "null"]},
          "coverage_receipt": {"type": "object"}, "investigation_links": {"type": "array", "items": {"type": "object"}}}, sorted(FINDING_KEYS)),
        ("submit_review", "Finish all rules; unknown evidence blocks approval.", {}, []),
    ]
]


class ToolRegistry:
    def __init__(self, document: Document | Bundle, playbook: Playbook):
        self.bundle = document if isinstance(document, Bundle) else as_bundle(document)
        self.document, self.playbook = self.bundle.base, playbook
        self.rules_read = {}
        self.searches = {}
        self.search_flags = {}
        self.blocks_read = {}
        self.references = {}
        self.findings = {}
        self.submitted = False
        self.last_error = None
        self.history = []

    def checkpoint(self):
        return deepcopy({key: getattr(self, key) for key in
                         ("rules_read", "searches", "search_flags", "blocks_read", "references",
                          "findings", "submitted", "last_error", "history")})

    def restore(self, state):
        exact_keys(state, set(self.checkpoint()))
        for key in self.checkpoint():
            if key in state:
                setattr(self, key, deepcopy(state[key]))
        actual = {block["block_id"]: block for doc in self.bundle.documents for block in doc.blocks}
        if any(key not in actual or value != actual[key] for key, value in self.blocks_read.items()):
            raise ReviewError("Checkpoint source/version mismatch.", 3)

    def coverage(self, blocks_read=None):
        blocks_read = self.blocks_read if blocks_read is None else blocks_read
        core = {"documents": [{"document_id": document.document_id,
                  "document_sha256": document.version,
                  "read_block_ids": sorted(block["block_id"] for block in document.blocks if block["block_id"] in blocks_read),
                  "total_blocks": len(document.blocks)} for document in self.bundle.documents]}
        core["complete"] = all(len(item["read_block_ids"]) == item["total_blocks"] for item in core["documents"])
        return {**core, "receipt_sha256": sha256(canonical(core))}

    def observation(self):
        result = {"protocol_version": 2, "rule_ids": list(RULE_IDS),
                  "document": document_metadata(self.document),
                  "documents": [document_metadata(doc) for doc in self.bundle.documents],
                  "tools": TOOL_SCHEMAS, "coverage": self.coverage(),
                  "reference_inventory": reference_inventory(self.bundle),
                  "replacement_edges": replacement_edges(self.bundle), **self.checkpoint()}
        if len(canonical(result)) > 96 * 1024:
            raise ReviewError("Context budget exceeded without truncation.", 4)
        return deepcopy(result)

    def execute(self, decision):
        exact_keys(decision, {"tool", "arguments"})
        if not isinstance(decision["tool"], str) or decision["tool"] not in TOOL_NAMES:
            raise ReviewError("Tool is not allowlisted.", 3)
        if not isinstance(decision["arguments"], dict):
            raise ReviewError("Tool arguments must be an object.", 3)
        return getattr(self, "_" + decision["tool"])(decision["arguments"])

    def _get_rule(self, args):
        exact_keys(args, {"rule_id"})
        rule_id = string(args["rule_id"], "rule ID", 20)
        if rule_id not in self.playbook.rules:
            raise ReviewError("Unknown rule ID.", 3)
        rule = deepcopy(self.playbook.rules[rule_id])
        rule["policy_citation"] = {"playbook_id": self.playbook.name,
                                  "playbook_sha256": self.playbook.version,
                                  "rule_id": rule_id, "quote": rule["text"]}
        self.rules_read[rule_id] = rule
        return rule

    def _search_clauses(self, args):
        exact_keys(args, {"rule_id"})
        rule_id = string(args["rule_id"], "rule ID", 20)
        if rule_id not in self.rules_read:
            raise ReviewError("Read the rule before searching.", 3)
        topic = self.rules_read[rule_id]["topic"]
        hits, links, status = [], [], "resolved"
        for block in self.document.blocks:
            if topic not in block["title"].casefold():
                continue
            resolution = effective_section(self.bundle, "agreement", block["block_id"].split("section-")[-1])
            links.extend(resolution["edges"])
            if resolution["status"] != "resolved":
                status = resolution["status"]
                continue
            target = self.bundle.by_id[resolution["document_id"]]
            effective = next(b for b in target.blocks if b["block_id"] == resolution["block_id"])
            hits.append({"block_id": effective["block_id"], "document_id": target.document_id,
                         "title": effective["title"], "snippet": effective["text"][:240]})
        for edge in replacement_edges(self.bundle):
            if not edge["valid"]:
                target_block = section_block(self.bundle, *edge["target"])
                if target_block is None or topic in target_block["title"].casefold():
                    status = "unknown"
                    links.append(edge)
        if len(hits) > 8:
            raise ReviewError("Too many matching clauses.", 3)
        self.searches[rule_id] = hits
        self.search_flags[rule_id] = {"status": status, "links": links}
        return {"results": hits, "status": status, "links": links, "exhaustive_semantic_review": False}

    def _read_blocks(self, args):
        exact_keys(args, {"block_ids"})
        ids = args["block_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 6 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ReviewError("Read one to six unique block IDs.", 3)
        blocks = {b["block_id"]: b for doc in self.bundle.documents for b in doc.blocks}
        if any(i not in blocks for i in ids):
            raise ReviewError("Unknown source block.", 3)
        result = [blocks[i] for i in ids]
        future = {**self.blocks_read, **{b["block_id"]: b for b in result}}
        envelope = {"blocks": deepcopy(result), "complete": True, "coverage": self.coverage(future)}
        if len(canonical(envelope)) > 12 * 1024 - 64:
            raise ReviewError("Read fewer blocks to fit the result limit.", 3)
        self.blocks_read = future
        return envelope

    def _scan_document(self, args):
        exact_keys(args, {"document_id", "cursor"})
        document_id = string(args["document_id"], "document ID", 20)
        cursor = args["cursor"]
        if document_id not in self.bundle.by_id or type(cursor) is not int:
            raise ReviewError("Invalid document/cursor.", 3)
        document = self.bundle.by_id[document_id]
        if not 0 <= cursor < len(document.blocks):
            raise ReviewError("Coverage cursor is out of range.", 3)
        selected = []
        for block in document.blocks[cursor:cursor + 6]:
            candidate = selected + [block]
            future = {**self.blocks_read, **{b["block_id"]: b for b in candidate}}
            if len(canonical({"blocks": candidate, "complete": True,
                              "coverage": self.coverage(future)})) > 12 * 1024 - 64:
                break
            selected.append(block)
        if not selected:
            raise ReviewError("A source block cannot fit without truncation.", 3)
        result = self._read_blocks({"block_ids": [b["block_id"] for b in selected]})
        next_cursor = cursor + len(selected)
        return {**result, "next_cursor": None if next_cursor == len(document.blocks) else next_cursor}

    def _resolve_reference(self, args):
        exact_keys(args, {"source_block_id", "reference"})
        block_id = string(args["source_block_id"], "source block ID", 80)
        literal = string(args["reference"], "literal reference", 100)
        block = self.blocks_read.get(block_id)
        if block is None or not any(m.group() == literal for m in block_references(block)) or REFERENCE.fullmatch(literal) is None:
            raise ReviewError("Reference must occur literally in a read block.", 3)
        source_document = self.bundle.by_id[block_id.split(".section-")[0]]
        source_match = next(m for m in block_references(block) if m.group() == literal)
        position = block["start"] + source_match.start()
        evidence = source_span(source_document, position, position + len(literal))
        reference_evidence = [evidence]
        match = REFERENCE.fullmatch(literal)
        current_document, section = match["document"] or source_document.document_id, match["section"]
        visited, path, links, result = {block_id}, [block_id], [], None
        for _ in range(3):
            resolution = effective_section(self.bundle, current_document, section)
            links.extend(resolution["edges"])
            if resolution["status"] != "resolved":
                result = {**resolution, "evidence": evidence}
                break
            target_id = resolution["block_id"]
            if target_id in visited:
                result = {"status": "unknown", "reason": "Reference cycle.", "evidence": evidence}
                break
            visited.add(target_id)
            path.append(target_id)
            target = next(b for b in self.bundle.by_id[resolution["document_id"]].blocks if b["block_id"] == target_id)
            nested = block_references(target)
            if not nested:
                result = {"status": "resolved", "block_id": target_id,
                          "document_id": resolution["document_id"], "evidence": evidence}
                break
            if len(nested) != 1:
                result = {"status": "unknown", "reason": "Multiple references are ambiguous.", "evidence": evidence}
                break
            nested_match = nested[0]
            reference_evidence.append(source_span(self.bundle.by_id[resolution["document_id"]],
                target["start"] + nested_match.start(), target["start"] + nested_match.end()))
            current_document, section = nested[0]["document"] or resolution["document_id"], nested[0]["section"]
        if result is None:
            result = {"status": "unknown", "reason": "Reference depth exceeds three.", "evidence": evidence}
        result.update({"path_block_ids": path, "links": links, "reference_evidence": reference_evidence})
        self.references[block_id + "|" + literal] = deepcopy(result)
        return result

    def unresolved_inventory(self):
        return any((result := self.references.get(ref["source_block_id"] + "|" + ref["reference"])) is None
                   or result["status"] != "resolved" for ref in reference_inventory(self.bundle))

    def insertion_options(self, rule):
        if "approved_insertion_sentence" not in rule:
            return {}
        approved = rule["approved_insertion_sentence"]
        matching = [b for b in self.document.blocks if rule["topic"] in b["title"].casefold()]
        if len(matching) == 1 and matching[0]["block_id"] in self.blocks_read:
            return {matching[0]["end"]: {approved + "\n\n"}}
        anchor = section_block(self.bundle, "agreement", str(rule["insertion_before_section"]))
        if anchor is None or anchor["block_id"] not in self.blocks_read or section_block(self.bundle, "agreement", str(rule["default_section"])) is not None:
            return {}
        return {anchor["start"]: {f"Section {rule['default_section']} - {rule['topic'].title()}\n{approved}\n\n"}}

    def _propose_finding(self, finding):
        exact_keys(finding, FINDING_KEYS, {"coverage_receipt", "investigation_links"})
        rule_id = string(finding["rule_id"], "rule ID", 20)
        if rule_id not in self.rules_read or rule_id not in self.searches:
            raise ReviewError("Read and search the rule before proposing.", 3)
        if rule_id in self.findings:
            raise ReviewError("A rule already has a staged finding.", 3)
        disposition = finding["disposition"]
        if not isinstance(disposition, str) or disposition not in ("compliant", "deviation", "missing", "conflict", "uncertain"):
            raise ReviewError("Unknown disposition.", 3)
        string(finding["reason"], "finding reason", 400)
        exact_keys(finding["policy_citation"], POLICY_KEYS)
        if finding["policy_citation"] != self.rules_read[rule_id]["policy_citation"]:
            raise ReviewError("Policy citation mismatch.", 3)
        rule = self.rules_read[rule_id]
        exact_keys(finding["obligations"], set(rule["obligations"]))
        statuses = set()
        for value in finding["obligations"].values():
            if not isinstance(value, str) or value not in ("compliant", "deviation", "missing", "conflict", "uncertain"):
                raise ReviewError("Unknown obligation status.", 3)
            statuses.add(value)
        if disposition == "compliant" and statuses != {"compliant"} or disposition != "compliant" and disposition not in statuses:
            raise ReviewError("Disposition and obligations disagree.", 3)
        evidence = finding["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 6:
            raise ReviewError("Invalid evidence list.", 3)
        if disposition in ("compliant", "deviation", "conflict") and not evidence:
            raise ReviewError("This finding requires source evidence.", 3)
        for span in evidence:
            if not isinstance(span, dict) or not isinstance(span.get("document_id"), str) or span["document_id"] not in self.bundle.by_id:
                raise ReviewError("Unknown evidence document.", 3)
            validate_span(span, self.bundle.by_id[span["document_id"]], set(self.blocks_read))
        if disposition == "missing" and (not self.coverage()["complete"] or finding.get("coverage_receipt") != self.coverage() or self.unresolved_inventory()):
            raise ReviewError("Absence requires full current coverage and no unavailable referenced evidence.", 3)
        flag = self.search_flags[rule_id]
        if flag["status"] == "conflict" and disposition != "conflict":
            raise ReviewError("Known competing amendments require conflict handoff.", 3)
        if flag["status"] == "unknown" and disposition != "uncertain":
            raise ReviewError("Unknown amendment evidence cannot become a definitive finding.", 3)
        if disposition == "conflict" and (not flag["links"] or any(edge["evidence"] not in evidence for edge in flag["links"])):
            raise ReviewError("Conflict must cite every competing replacement.", 3)
        patch = finding["patch"]
        if patch is not None:
            if disposition not in ("deviation", "missing"):
                raise ReviewError("Only supported corrections may propose a patch.", 3)
            document_id = patch.get("document_id") if isinstance(patch, dict) else None
            if not isinstance(document_id, str) or document_id not in self.bundle.by_id:
                raise ReviewError("Unknown patch document.", 3)
            others = [f["patch"] for f in self.findings.values() if f["patch"] is not None and f["patch"]["document_id"] == document_id]
            options = self.insertion_options(rule) if disposition == "missing" and document_id == "agreement" else {}
            validate_patch(patch, self.bundle.by_id[document_id], evidence, others, options)
        elif disposition == "deviation":
            raise ReviewError("Unresolved deviation must hand off as uncertain.", 3)
        self.findings[rule_id] = deepcopy(finding)
        return {"staged_rule": rule_id, "disposition": disposition}

    def _submit_review(self, args):
        exact_keys(args, set())
        if set(self.findings) != set(RULE_IDS):
            raise ReviewError("All three rules need findings.", 3)
        if any(b["block_id"] not in self.blocks_read for doc in self.bundle.documents[1:] for b in doc.blocks):
            raise ReviewError("All supplied amendment blocks must be read before final review.", 3)
        for result in self.references.values():
            if result["status"] == "resolved" and any(i not in self.blocks_read for i in result["path_block_ids"]):
                raise ReviewError("Referenced path blocks must be read.", 3)
        if self.unresolved_inventory() and not any(f["disposition"] == "uncertain" for f in self.findings.values()):
            raise ReviewError("Unavailable referenced evidence requires an explicit unknown finding.", 3)
        self.submitted = True
        return {"domain_status": self.domain_status()}

    def domain_status(self):
        return "HANDOFF" if any(f["disposition"] in ("uncertain", "conflict") or f["disposition"] == "missing" and f["patch"] is None
                               for f in self.findings.values()) else "PENDING_REVIEW"


"""Pure gold-based metrics. Literal quotation is deliberately separate from supported meaning."""
from .corpus import canonical, digest
import re

LINK = re.compile(r"(?:Attachment A[0-9]+, )?Section [0-9]+$|Amendment A[12] replaces Section [0-9]+(?: of Amendment A[12])?\.$")


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if denominator else None}


def signature(rule_id, span):
    return (rule_id, span.get("document_id"), span.get("document_sha256"),
            span.get("start"), span.get("end"), span.get("quote"))


def literal_valid(span, sources, indexes):
    if not isinstance(span, dict):
        return False
    key = span.get("document_id")
    if key not in sources or span.get("document_sha256") != digest(sources[key]):
        return False
    start, end = span.get("start"), span.get("end")
    text = sources[key].decode("utf-8")
    block = indexes[key].get(span.get("block_id"))
    return (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
            and isinstance(span.get("quote"), str) and text[start:end] == span["quote"]
            and block is not None and block["start"] <= start < end <= block["end"])


def semantic_metrics(case, packet, indexes):
    predicted = {f.get("rule_id"): f for f in packet.get("findings", []) if isinstance(f, dict)}
    truth = case.labels["rules"]
    emitted, expected, emitted_clauses, expected_clauses = set(), set(), set(), set()
    literal_correct = citation_count = policy_correct = rules_correct = atoms_correct = 0
    violation_tp = violation_fp = violation_fn = missing_tp = missing_fp = missing_fn = 0
    patches_correct, rule_errors, per_rule = 0, [], {}
    policy = case.policy
    policy_by_id = {r["id"]: r for r in policy["rules"]}
    atom_total = sum(len(rule["obligations"]) for rule in truth.values())
    support_complete = True
    for key, golden in truth.items():
        finding = predicted.get(key, {})
        rule_ok = finding.get("disposition") == golden["disposition"]
        rules_correct += rule_ok
        atoms = finding.get("obligations", {})
        atom_correct=tp=fp=fn=0
        atoms_ok = isinstance(atoms, dict) and set(atoms) == set(golden["obligations"])
        if not isinstance(atoms, dict):
            atoms = {}
        for atom, required in golden["obligations"].items():
            actual = atoms.get(atom)
            atoms_correct += actual == required
            atom_correct += actual == required
            atoms_ok = atoms_ok and actual == required
            expected_positive, actual_positive = required in ("deviation", "missing"), actual in ("deviation", "missing")
            violation_tp += expected_positive and actual_positive
            violation_fp += not expected_positive and actual_positive
            violation_fn += expected_positive and not actual_positive
            tp += expected_positive and actual_positive
            fp += not expected_positive and actual_positive
            fn += expected_positive and not actual_positive
            missing_tp += required == "missing" and actual == "missing"
            missing_fp += required != "missing" and actual == "missing"
            missing_fn += required == "missing" and actual != "missing"
        expected_policy = {"playbook_id": policy["id"], "playbook_sha256": digest(case.policy_raw),
                           "rule_id": key, "quote": policy_by_id[key]["text"]}
        policy_correct += finding.get("policy_citation") == expected_policy
        actual_spans = finding.get("evidence", [])
        if not isinstance(actual_spans, list):
            actual_spans = []
        actual_set, required_set = set(), set()
        for span in actual_spans:
            citation_count += 1
            valid = literal_valid(span, case.sources, indexes)
            literal_correct += valid
            if isinstance(span, dict):
                try:
                    value = signature(key, span)
                    hash(value)
                except TypeError:
                    continue
                actual_set.add(value)
                emitted.add(value)
                if not LINK.fullmatch(str(span.get("quote", ""))):
                    emitted_clauses.add(value)
        for span in golden["evidence_required"]:
            value = signature(key, span)
            required_set.add(value)
            expected.add(value)
            if not LINK.fullmatch(span["quote"]):
                expected_clauses.add(value)
        # The frozen rubric explicitly permits additional genuine quotes for an unknown finding.
        # Finite gold-overlap precision still publishes those extra spans separately.
        additional_unknown = golden["disposition"]=="uncertain" and all(literal_valid(s,case.sources,indexes) for s in actual_spans)
        supported = required_set <= actual_set and (actual_set <= required_set or additional_unknown)
        support_complete = support_complete and supported
        patch_ok = key in predicted and finding.get("patch") == golden["patch"]
        patches_correct += patch_ok
        per_rule[key]={"rule_accuracy":fraction(int(rule_ok),1),
            "atom_accuracy":fraction(atom_correct,len(golden["obligations"])),
            "exact_rules":fraction(int(rule_ok and atoms_ok and supported and patch_ok),1),
            "localized_rule_proposals":fraction(int(patch_ok),1),
            "deviation_missing_precision":fraction(tp,tp+fp),"deviation_missing_recall":fraction(tp,tp+fn),
            "source_support_precision":fraction(len(actual_set & required_set),len(actual_set)),
            "source_support_recall":fraction(len(actual_set & required_set),len(required_set))}
        if not rule_ok or not atoms_ok or not supported or not patch_ok:
            rule_errors.append({"rule_id": key, "disposition_correct": rule_ok,
                                "atoms_correct": atoms_ok, "support_complete": supported,
                                "localized_patch_correct": patch_ok,
                                "expected": golden["disposition"], "actual": finding.get("disposition")})
    required_handoff = case.labels["domain_status"] == "HANDOFF"
    actual_handoff = packet.get("domain_status") == "HANDOFF"
    expected_patch_set = [r["patch"] for r in truth.values() if r["patch"] is not None]
    proposal_correct = packet.get("patches") == expected_patch_set
    return {"rule_accuracy": fraction(rules_correct, len(truth)),
            "atom_accuracy": fraction(atoms_correct, atom_total),
            "citation_fidelity": fraction(literal_correct, citation_count),
            "policy_citation_fidelity": fraction(policy_correct, len(truth)),
            "source_support_precision": fraction(len(emitted & expected), len(emitted)),
            "source_support_recall": fraction(len(emitted & expected), len(expected)),
            "clause_precision": fraction(len(emitted_clauses & expected_clauses), len(emitted_clauses)),
            "clause_recall": fraction(len(emitted_clauses & expected_clauses), len(expected_clauses)),
            "deviation_missing_precision": fraction(violation_tp, violation_tp + violation_fp),
            "deviation_missing_recall": fraction(violation_tp, violation_tp + violation_fn),
            "missing_atom_precision": fraction(missing_tp, missing_tp + missing_fp),
            "missing_atom_recall": fraction(missing_tp, missing_tp + missing_fn),
            "missed_positive_atoms": violation_fn, "unsupported_positive_atoms": violation_fp,
            "missed_missing_atoms": missing_fn, "unsupported_missing_atoms": missing_fp,
            "localized_rule_proposals": fraction(patches_correct, len(truth)),
            "mandatory_handoff_recall": fraction(int(required_handoff and actual_handoff), int(required_handoff)),
            "unnecessary_handoff_rate": fraction(int(not required_handoff and actual_handoff), int(not required_handoff)),
            "domain_correct": packet.get("domain_status") == case.labels["domain_status"],
            "support_complete": support_complete, "proposal_correct": proposal_correct,
            "semantic_correct": not rule_errors and proposal_correct,
            "rule_errors": rule_errors,"per_rule":per_rule}


def aggregate_rules(reports):
    result={}
    for key in sorted({key for report in reports for key in report["per_rule"]}):
        rows=[report["per_rule"][key] for report in reports]
        result[key]={name:fraction(sum(row[name]["numerator"] for row in rows),
                                 sum(row[name]["denominator"] for row in rows)) for name in rows[0]}
    return result


def label_denominators(labels):
    rules=[r for case in labels.values() for r in case["rules"].values()]
    return {"cases":len(labels),"rules":len(rules),
            "atoms":sum(len(r["obligations"]) for r in rules),
            "required_source_spans":sum(len({signature("",s) for s in r["evidence_required"]}) for r in rules),
            "primary_clause_spans":sum(len({signature("",s) for s in r["evidence_required"] if not LINK.fullmatch(s["quote"])}) for r in rules),
            "source_documents":sum(len(case["reviewed_files"]) for case in labels.values()),
            "required_reviewed_documents":sum(len(case["reviewed_files"]) for case in labels.values() if case["domain_status"]=="PENDING_REVIEW"),
            "mandatory_handoff_cases":sum(case["domain_status"]=="HANDOFF" for case in labels.values()),
            "positive_atoms":sum(v in ("deviation","missing") for r in rules for v in r["obligations"].values()),
            "missing_atoms":sum(v=="missing" for r in rules for v in r["obligations"].values())}


def aggregate(reports):
    fractions = ("rule_accuracy", "atom_accuracy", "citation_fidelity", "policy_citation_fidelity",
                 "source_support_precision", "source_support_recall", "clause_precision", "clause_recall",
                 "deviation_missing_precision", "deviation_missing_recall", "missing_atom_precision",
                 "missing_atom_recall", "localized_rule_proposals", "mandatory_handoff_recall",
                 "unnecessary_handoff_rate", "protected_documents", "exact_preview_documents",
                 "protected_reviewed_documents", "exact_reviewed_documents", "exact_cases", "integrity_cases")
    result = {}
    for name in fractions:
        result[name] = fraction(sum(r[name]["numerator"] for r in reports),
                                sum(r[name]["denominator"] for r in reports))
    for name in ("missed_positive_atoms", "unsupported_positive_atoms", "missed_missing_atoms",
                 "unsupported_missing_atoms", "unrelated_violating_bytes", "operational_failures"):
        result[name] = sum(r.get(name, 0) for r in reports)
    return result


def normalized_digest(packet, trace, usage, previews, reviewed, decision):
    count_fields = ("decision_calls", "tool_calls", "tool_execution_attempts", "action_replays",
                    "provider_requests", "model_calls", "model_tokens", "prompt_tokens","completion_tokens",
                    "transient_retries", "protocol_repairs")
    value = {"packet": packet, "trace": trace, "usage_counts": {k: usage.get(k) for k in count_fields},
             "preview_sha256": {k: digest(v) for k, v in previews.items()},
             "reviewed_sha256": {k: digest(v) for k, v in reviewed.items()},
             "decision": None if decision is None else {k: v for k, v in decision.items() if k != "decided_at"}}
    return digest(canonical(value))

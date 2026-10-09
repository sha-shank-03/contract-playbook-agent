"""Trusted fictional policy; source text cannot change it."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import ReviewError, bounded_bytes, exact_keys, parse_json, sha256, string

RULE_IDS = ("REN-01", "TERM-01", "PAY-01")


@dataclass(frozen=True)
class Playbook:
    path: Path
    raw: bytes
    version: str
    name: str
    rules: dict[str, dict]


def load_playbook(path: Path) -> Playbook:
    path = path.resolve()
    raw = bounded_bytes(path, 16 * 1024)
    data = parse_json(raw, 16 * 1024)
    exact_keys(data, {"schema_version", "fictional", "id", "rules"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["fictional"] is not True:
        raise ReviewError("Only explicitly fictional schema-1 playbooks are supported.")
    string(data["id"], "playbook ID", 80)
    if not isinstance(data["rules"], list) or len(data["rules"]) != 3:
        raise ReviewError("M1 requires exactly three playbook rules.")
    rules = {}
    expected_atoms = {
        "REN-01": ["renewal.express_written_agreement"],
        "TERM-01": ["termination.customer_right", "termination.written_notice",
                    "termination.notice_days"],
        "PAY-01": ["payment.undisputed", "payment.receipt_trigger", "payment.days"],
    }
    for rule in data["rules"]:
        exact_keys(rule, {"id", "text", "topic", "obligations", "limit_days",
                          "approved_renewal_sentence"},
                   {"approved_insertion_sentence", "insertion_before_section", "default_section"})
        rule_id = rule["id"]
        string(rule_id, "rule ID", 20)
        if rule_id not in RULE_IDS or rule_id in rules:
            raise ReviewError("Unknown or duplicate playbook rule.")
        string(rule["text"], "policy text", 1000)
        if rule["obligations"] != expected_atoms[rule_id]:
            raise ReviewError("Unsupported obligation schema.")
        if rule["topic"] != {"REN-01": "renewal", "TERM-01": "termination", "PAY-01": "payment"}[rule_id]:
            raise ReviewError("Unsupported topic.")
        if rule_id == "REN-01":
            if rule["limit_days"] is not None:
                raise ReviewError("Renewal does not use a day limit.")
            string(rule["approved_renewal_sentence"], "approved renewal wording", 800)
        elif type(rule["limit_days"]) is not int or rule["limit_days"] != 30:
            raise ReviewError("M1 fictional notice and payment rules use 30 days.")
        elif rule["approved_renewal_sentence"] is not None:
            raise ReviewError("Unexpected renewal wording.")
        if "approved_insertion_sentence" in rule:
            string(rule["approved_insertion_sentence"], "approved insertion", 800)
            if type(rule.get("insertion_before_section")) is not int or type(rule.get("default_section")) is not int:
                raise ReviewError("Insertion section anchors must be integers.")
        rules[rule_id] = rule
    return Playbook(path, raw, sha256(raw), data["id"], rules)


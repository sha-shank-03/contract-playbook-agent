"""Allowlist-only operating metadata; no provider text, source text or secrets."""
from __future__ import annotations

import math
import re

from ..common import canonical, sha256

MODES = {"local-double", "replay", "scripted", "live"}
_NUMBERS = {"attempt", "steps", "requests", "tool_attempts", "rejected", "replays",
            "elapsed_seconds", "seconds_used", "prompt_tokens", "completion_tokens"}
_HASHES = {"run_id", "code_sha256", "prompt_sha256", "config_sha256", "dataset_sha256"}
_STATES = {"START", "ACTION", "GUARDED_ACTION", "GUARD_REJECTED", "FAILED", "CANCELLED",
           "PROPOSAL_READY", "HANDOFF", "APPROVED_COPY_VERIFIED", "REJECTED", "APPROVAL_DENIED", "STALE"}
_DISPOSITIONS = {"NEW", "INVESTIGATING", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED",
                 "PENDING_REVIEW", "HANDOFF", "APPROVED", "DRAFT_EXPORTED", "REJECTED", "STALE"}
_EVENT_DISPOSITIONS = {"START": "INVESTIGATING", "FAILED": "FAILED", "CANCELLED": "CANCELLED",
                       "PROPOSAL_READY": "PENDING_REVIEW", "HANDOFF": "HANDOFF",
                       "APPROVED_COPY_VERIFIED": "DRAFT_EXPORTED", "REJECTED": "REJECTED", "STALE": "STALE"}


def safe_event(value):
    clean = {"schema_version": 1}
    for key, item in value.items():
        if key in _HASHES and isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item):
            clean[key] = item
        elif key in _NUMBERS and (item is None or type(item) in (int, float)
                                 and math.isfinite(item) and item >= 0):
            clean[key] = item
        elif key == "mode" and isinstance(item, str) and item in MODES:
            clean[key] = item
        elif key == "state" and isinstance(item, str) and item in _STATES:
            clean[key] = item
        elif key == "committed_state" and isinstance(item, str) and item in _DISPOSITIONS:
            clean[key] = item
        elif key == "failure_code" and isinstance(item, str) and re.fullmatch(r"[A-Z0-9_]{1,48}", item):
            clean[key] = item
        elif key == "tool" and isinstance(item, str) and item in {"get_rule", "search_clauses", "read_blocks", "scan_document",
                                      "resolve_reference", "propose_finding", "submit_review"}:
            clean[key] = item
        elif key in {"response_id", "generation_id"}:
            prefixes = ("gen_",) if key == "generation_id" else ("gen_", "chatcmpl-", "double_")
            if item is None or (isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item)
                               and item.startswith(prefixes)):
                clean[key] = item
        elif key == "model" and isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9._:-]+/[A-Za-z0-9._:-]+", item):
            clean[key] = item
        elif key == "unauthorized_actions" and type(item) is int and item >= 0:
            clean[key] = item
        elif key == "request_in_flight" and type(item) is bool:
            clean[key] = item
    clean.update(provider="vercel-ai-gateway", estimated_cost_usd=None, actual_cost_usd=None)
    return clean


def summary(events, *, current_state=None):
    records = [safe_event(event) for event in events]
    latencies = sorted(r["elapsed_seconds"] for r in records
                       if r.get("state") == "ACTION" and r.get("elapsed_seconds") is not None)
    def percentile(fraction):
        return latencies[max(0, math.ceil(len(latencies) * fraction) - 1)] if latencies else None
    states = [r.get("state") for r in records]
    last = records[-1] if records else {}
    if current_state is None:
        current_state = next((r.get("committed_state", _EVENT_DISPOSITIONS.get(r.get("state")))
                              for r in reversed(records)
                              if "committed_state" in r or r.get("state") in _EVENT_DISPOSITIONS), "NEW")
    if current_state not in _DISPOSITIONS:
        raise ValueError("Unknown committed run disposition.")
    completed = int(current_state == "DRAFT_EXPORTED" and "APPROVED_COPY_VERIFIED" in states)
    return {"schema_version": 2, "mode": last.get("mode"), "unique_tasks": 1 if records else 0,
            "current_disposition": current_state,
            "verified_copy_delivered": completed, "pending_human_review": int(current_state == "PENDING_REVIEW"),
            "human_decisions": states.count("APPROVED_COPY_VERIFIED") + states.count("REJECTED"),
            "handoff": int(current_state == "HANDOFF"), "stale": int(current_state == "STALE"),
            "rejected": int(current_state == "REJECTED"),
            "guard_rejections": states.count("GUARD_REJECTED"),
            "raw_valid_actions": states.count("ACTION"),
            "host_committed_actions": states.count("GUARDED_ACTION"),
            "failed": int(current_state in {"FAILED", "BUDGET_EXHAUSTED"}),
            "cancelled": int(current_state == "CANCELLED"),
            "historical_failure_events": states.count("FAILED"),
            "historical_cancellation_events": states.count("CANCELLED"),
            "historical_stale_events": states.count("STALE"),
            "historical_approval_denial_events": states.count("APPROVAL_DENIED"),
            "executed_unauthorized_actions": next((r["unauthorized_actions"] for r in reversed(records)
                                                  if "unauthorized_actions" in r), None),
            "unsafe_proposal_meaning": None, "semantic_quality": "unassessed",
            "latency_sample_count": len(latencies), "request_p50_seconds": percentile(.5),
            "request_p95_seconds": percentile(.95), "requests": last.get("requests", 0),
            "active_seconds": last.get("seconds_used"),
            "prompt_tokens": last.get("prompt_tokens"), "completion_tokens": last.get("completion_tokens"),
            "estimated_cost_usd": None, "actual_cost_usd": None, "cost_per_success_usd": None,
            "live_model_calls": 0 if last.get("mode") == "local-double" else None,
            "unreconciled_request": last.get("request_in_flight"),
            "approval_wait_included_in_active_budget": False,
            "approval_processing_seconds": None,
            "ram_peak_bytes": None, "metrics_sha256": sha256(canonical(
                {"current_disposition": current_state, "events": records}))}

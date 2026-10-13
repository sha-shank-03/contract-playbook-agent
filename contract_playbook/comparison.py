"""Equal-budget comparison seam. Scripted local doubles only; no credentials or I/O."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from copy import deepcopy
import math
import json
import time

from .common import canonical, sha256, ReviewError
from .ingest import document_metadata
from .playbook import RULE_IDS
from .providers.gateway import GatewayChatProvider, GatewayConfig, GatewayFailure, build_gateway_request
from .tools import ToolRegistry

PROTOCOL = "paired-exposed-u2b-v1"


@dataclass(frozen=True)
class PairLimits:
    model: str = "local/contract-double"
    requests: int = 24
    steps: int = 24
    tools: int = 24
    seconds: float = 60
    request_seconds: float = 5
    completion_tokens: int = 2048
    total_completion_tokens: int = 49152
    prompt_tokens_per_request: int = 98304
    total_prompt_tokens: int = 2359296
    request_bytes: int = 98304
    total_request_bytes: int = 2359296
    review_decisions: int = 1
    review_seconds: float = 60

    def __post_init__(self):
        try:
            GatewayConfig(self.model, self.requests, self.steps, self.seconds,
                          self.request_seconds, self.completion_tokens)
        except ReviewError:
            raise GatewayFailure("INVALID_PAIR_LIMITS") from None
        for key, upper in (("tools", 24), ("total_completion_tokens", 49152),
                           ("prompt_tokens_per_request", 98304), ("total_prompt_tokens", 2359296),
                           ("request_bytes", 98304), ("total_request_bytes", 2359296),
                           ("review_decisions", 1)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= upper:
                raise GatewayFailure("INVALID_PAIR_LIMITS")
        if (type(self.review_seconds) not in (int, float)
                or not math.isfinite(self.review_seconds) or not 0 < self.review_seconds <= 60):
            raise GatewayFailure("INVALID_PAIR_LIMITS")

    def gateway(self):
        return GatewayConfig(self.model, self.requests, self.steps, self.seconds,
                             self.request_seconds, self.completion_tokens)

    def public(self):
        return asdict(self)


class PairMeter:
    """Charge host schedule and failed model attempts; no retries or refunded reservations."""
    def __init__(self, limits):
        self.limits = limits
        self.steps = self.tools = self.requests = 0
        self.request_bytes = self.completion_reserved = 0
        self.prompt_tokens = self.completion_tokens = 0
        self.usage_known = True

    def step(self):
        if self.steps >= self.limits.steps:
            raise GatewayFailure("STEP_BUDGET_EXHAUSTED")
        self.steps += 1

    def reserve_request(self, encoded_bytes):
        if type(encoded_bytes) is not int or not 0 < encoded_bytes <= self.limits.request_bytes:
            raise GatewayFailure("REQUEST_TOO_LARGE")
        if (self.requests >= self.limits.requests
                or self.request_bytes + encoded_bytes > self.limits.total_request_bytes
                or self.completion_reserved + self.limits.completion_tokens > self.limits.total_completion_tokens):
            raise GatewayFailure("REQUEST_BUDGET_EXHAUSTED")
        self.requests += 1
        self.request_bytes += encoded_bytes
        self.completion_reserved += self.limits.completion_tokens
        # Until the response is independently validated, consumed tokens are unknown.
        self.usage_known = False

    def settle_usage(self, metadata):
        values = [(metadata or {}).get(k) for k in ("prompt_tokens", "completion_tokens")]
        if any(v is None for v in values):
            self.prompt_tokens = self.completion_tokens = None
        elif any(type(v) is not int or v < 0 for v in values):
            raise GatewayFailure("INVALID_USAGE")
        else:
            prompt, completion = values
            if completion > self.limits.completion_tokens:
                raise GatewayFailure("TOKEN_LIMIT")
            if prompt > self.limits.prompt_tokens_per_request or (
                    self.prompt_tokens is not None and self.prompt_tokens + prompt > self.limits.total_prompt_tokens):
                raise GatewayFailure("TOKEN_LIMIT")
            self.prompt_tokens = None if self.prompt_tokens is None else self.prompt_tokens + prompt
            self.completion_tokens = None if self.completion_tokens is None else self.completion_tokens + completion
        self.usage_known = self.prompt_tokens is not None and self.completion_tokens is not None

    def tool(self):
        if self.tools >= self.limits.tools:
            raise GatewayFailure("TOOL_BUDGET_EXHAUSTED")
        self.tools += 1

    def public(self):
        return {"steps": self.steps, "tool_attempts": self.tools, "local_double_requests": self.requests,
                "request_bytes_reserved": self.request_bytes,
                "completion_tokens_reserved": self.completion_reserved,
                "prompt_tokens": self.prompt_tokens if self.usage_known else None,
                "completion_tokens": self.completion_tokens if self.usage_known else None,
                "model_calls": 0, "actual_cost_usd": None, "estimated_cost_usd": None}


def full_context(bundle, policy):
    """Only supplied bytes and trusted policy. No task ID, family, scorer or answer metadata."""
    return {"fictional": True, "playbook": json.loads(policy.raw),
            "documents": [{"document_id": d.document_id, "document_sha256": d.version,
                           "text": d.text} for d in bundle.documents]}


def phase_hint(observation, strategy):
    if strategy == "adaptive":
        return {"strategy": strategy, "next_tool": "actor_choice"}
    remaining = [r for r in observation["rule_ids"] if r not in observation["findings"]]
    return {"strategy": strategy, "preparation_complete": fixed_action(observation) is None,
            "next_tool": "propose_finding" if remaining else "submit_review",
            "required_rule_id": remaining[0] if remaining else None,
            "instruction": "Use all supplied policy and source evidence. Complete the next ordered finding; do not repeat the finished fixed preparation. Approval remains outside actor authority."}


def actor_observation(registry, context, strategy="adaptive"):
    observation = registry.observation()
    return {**observation, "full_permitted_context": deepcopy(context),
            "host_comparison_schedule": phase_hint(observation, strategy)}


def fixed_action(observation):
    """Fixed policy -> complete source -> searches -> every literal reference schedule."""
    for rule in observation["rule_ids"]:
        if rule not in observation["rules_read"]:
            return {"tool": "get_rule", "arguments": {"rule_id": rule}}
    unread = [b["block_id"] for d in observation["documents"] for b in d["blocks"]
              if b["block_id"] not in observation["blocks_read"]]
    if unread:
        return {"tool": "read_blocks", "arguments": {"block_ids": unread[:6]}}
    for rule in observation["rule_ids"]:
        if rule not in observation["searches"]:
            return {"tool": "search_clauses", "arguments": {"rule_id": rule}}
    for ref in observation["reference_inventory"]:
        key = ref["source_block_id"] + "|" + ref["reference"]
        if key not in observation["references"]:
            return {"tool": "resolve_reference", "arguments": {
                "source_block_id": ref["source_block_id"], "reference": ref["reference"]}}
    return None


def fixed_model_action(decision, observation):
    remaining = [r for r in observation["rule_ids"] if r not in observation["findings"]]
    if remaining:
        if decision.get("tool") != "propose_finding" or decision.get("arguments", {}).get("rule_id") != remaining[0]:
            raise GatewayFailure("FIXED_FINDING_ORDER")
    elif decision != {"tool": "submit_review", "arguments": {}}:
        raise GatewayFailure("FIXED_SUBMISSION_REQUIRED")


def run_actor(bundle, policy, limits, strategy, transport, *, clock=time.monotonic, cancel=lambda: False):
    """Full journey is a native gate, not called by pure tests. Does not persist or approve."""
    if strategy not in {"adaptive", "fixed-full-context"}:
        raise GatewayFailure("INVALID_STRATEGY")
    if getattr(transport, "mode", None) != "local-double":
        raise GatewayFailure("LIVE_DISABLED")
    started = clock()
    registry, meter = ToolRegistry(bundle, policy), PairMeter(limits)
    provider = GatewayChatProvider(limits.gateway(), transport, cancel, clock)
    context = full_context(bundle, policy)
    context_hash = sha256(canonical(context))
    events, failure, packet = [], None, None

    def check_time():
        if cancel():
            raise GatewayFailure("CANCELLED")
        if clock() - started >= limits.seconds:
            raise GatewayFailure("BUDGET_EXHAUSTED")

    try:
        while not registry.submitted:
            check_time()
            meter.step()
            observation = actor_observation(registry, context, strategy)
            decision = fixed_action(observation) if strategy == "fixed-full-context" else None
            scheduled = decision is not None
            call_id = "host_" + str(meter.steps)
            if not scheduled:
                remaining = {"seconds": limits.seconds - (clock() - started), "attempt": meter.requests + 1,
                             "requests_remaining": limits.requests - meter.requests - 1,
                             "steps_remaining": limits.steps - meter.steps}
                request = build_gateway_request(limits.gateway(), observation, remaining)
                meter.reserve_request(len(canonical(request)))
                decision = provider.next(observation, remaining)
                meter.settle_usage(provider.last_metadata)
                call_id = provider.last_metadata["provider_call_id"]
                if strategy == "fixed-full-context":
                    fixed_model_action(decision, observation)
            check_time()
            meter.tool()
            result = registry.execute(decision)
            check_time()
            event = {"decision": decision, "result": result, "error": None,
                     "provider_call_id": call_id}
            registry.history.append(event)
            events.append({"step": meter.steps, "scheduled": scheduled, "tool": decision["tool"],
                           "context_sha256": context_hash, "provider_call_id": call_id})
        if not registry.coverage()["complete"]:
            raise GatewayFailure("INCOMPLETE_SOURCE_COVERAGE")
        findings = [registry.findings[r] for r in RULE_IDS]
        core = {"schema_version": 4, "fictional": True, "execution_mode": "scripted-local-double",
                "live_model": False, "semantic_quality_evidence": False, "protocol": PROTOCOL,
                "strategy": strategy, "model": limits.model, "config_sha256": sha256(canonical(limits.public())),
                "context_sha256": context_hash, "manifest_sha256": sha256(bundle.manifest_raw),
                "documents": [document_metadata(d) for d in bundle.documents],
                "playbook": {"id": policy.name, "sha256": policy.version},
                "coverage": registry.coverage(), "findings": findings,
                "patches": [f["patch"] for f in findings if f["patch"] is not None],
                "domain_status": registry.domain_status()}
        packet = {**core, "proposal_sha256": sha256(canonical(core))}
    except KeyboardInterrupt:
        failure = "CANCELLED"
    except GatewayFailure as exc:
        failure = exc.status
    except ReviewError:
        failure = "GUARD_REJECTED"
    except Exception:
        failure = "HOST_FAILURE"
    return {"schema_version": 1, "mode": "scripted-local-double", "strategy": strategy,
            "model": limits.model, "limits": limits.public(), "context_sha256": context_hash,
            "packet": packet, "registry_state": registry.checkpoint(), "events": events,
            "usage": meter.public(), "failure": failure, "elapsed_seconds": clock() - started,
            "state": {"schema_version": 1, "current_state": packet["domain_status"] if packet else "FAILED",
                      "source_sha256": {d.document_id: d.version for d in bundle.documents},
                      "proposal_sha256": packet["proposal_sha256"] if packet else None,
                      "approved_proposal_sha256": None, "review_decisions": 0, "reviewed_sha256": {}},
            "review_receipt": None, "reviewed_documents": {}, "durability": "in_memory_only"}


class ConservativeScriptedDouble:
    """Observation-driven scheduling and authored blanket handoff, never semantic inference."""
    mode = "local-double"

    def request(self, endpoint, request, remaining_seconds, cancel):
        import json
        if cancel() or remaining_seconds <= 0:
            raise GatewayFailure("CANCELLED")
        state = json.loads(request["messages"][1]["content"])
        obs = state["observation"]
        decision = fixed_action(obs)
        if decision is None:
            remaining = [r for r in obs["rule_ids"] if r not in obs["findings"]]
            if not remaining:
                decision = {"tool": "submit_review", "arguments": {}}
            else:
                rule_id = remaining[0]
                rule, flag = obs["rules_read"][rule_id], obs["search_flags"][rule_id]
                conflict = flag["status"] == "conflict"
                status = "conflict" if conflict else "uncertain"
                evidence = [e["evidence"] for e in flag["links"]] if conflict else []
                decision = {"tool": "propose_finding", "arguments": {
                    "rule_id": rule_id, "disposition": status,
                    "reason": "Scripted orchestration double requests human interpretation; no semantic evaluation.",
                    "obligations": {a: status for a in rule["obligations"]},
                    "evidence": evidence, "policy_citation": rule["policy_citation"], "patch": None}}
        attempt = state["remaining_budget"]["attempt"]
        return canonical({"id": "double_" + str(attempt), "model": request["model"],
                          "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                              "role": "assistant", "content": None, "tool_calls": [{
                                  "id": "call_" + str(attempt), "type": "function",
                                  "function": {"name": decision["tool"],
                                               "arguments": canonical(decision["arguments"]).decode()}}]}}]})

"""Bounded loop with persisted reservations, intents and atomic committed observations."""
from __future__ import annotations

import time
import math
from dataclasses import asdict, dataclass, field

from .common import ReviewError, canonical
from .providers.contract import ProviderFailure


@dataclass
class Budget:
    calls: int = 0
    tool_calls: int = 0
    execution_attempts: int = 0
    seconds_used: float = 0.0
    protocol_repairs: int = 0
    transient_retries: int = 0
    replays: int = 0
    proposal_repairs: dict = field(default_factory=dict)
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    provider_requests: int = 0

    @classmethod
    def restore(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ReviewError("Malformed persisted budget.", 3)
        for key in ("calls", "tool_calls", "execution_attempts", "protocol_repairs",
                    "transient_retries", "replays", "provider_requests"):
            if type(value[key]) is not int or value[key] < 0:
                raise ReviewError("Malformed persisted counter.", 3)
        for key in ("prompt_tokens", "completion_tokens"):
            if value[key] is not None and (type(value[key]) is not int or value[key] < 0):
                raise ReviewError("Malformed persisted token counter.", 3)
        seconds = value["seconds_used"]
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ReviewError("Malformed persisted runtime budget.", 3)
        repairs = value["proposal_repairs"]
        if not isinstance(repairs, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0
                                              for k, v in repairs.items()):
            raise ReviewError("Malformed persisted proposal counter.", 3)
        return cls(**value)

    def reserve(self, max_calls, max_seconds):
        if self.calls >= max_calls or self.seconds_used >= max_seconds:
            raise ReviewError("Persisted decision/runtime budget exhausted.", 4)
        self.calls += 1
        prior = self.seconds_used
        self.seconds_used += min(20.0, max_seconds - prior)
        return prior

    def usage(self, kind):
        return {"decision_calls": self.calls, "tool_calls": self.tool_calls,
                "tool_execution_attempts": self.execution_attempts, "action_replays": self.replays,
                "elapsed_seconds": round(self.seconds_used, 6),
                "provider_requests": self.provider_requests,
                "model_calls": self.provider_requests if kind == "ollama" else 0,
                "model_tokens": None if self.prompt_tokens is None or self.completion_tokens is None
                                else self.prompt_tokens + self.completion_tokens,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "transient_retries": self.transient_retries, "protocol_repairs": self.protocol_repairs}


def investigate(registry, provider, record_event, max_calls=48, max_seconds=120,
                journal=None, cancelled=lambda: False, clock=time.monotonic,
                sleep=time.sleep, failpoint=lambda phase: None):
    saved = journal.load_checkpoint() if journal else None
    budget = Budget.restore(saved["budget"]) if saved else Budget()
    if saved:
        registry.restore(saved["registry"])

    def checkpoint():
        return {"budget": asdict(budget), "registry": registry.checkpoint()}

    def save():
        if journal:
            journal.save_checkpoint(checkpoint())

    while not registry.submitted:
        if cancelled():
            save()
            raise KeyboardInterrupt()
        pending = journal.pending_action() if journal else None
        started = clock()
        prior_seconds = budget.seconds_used
        if pending:
            budget.replays += 1
            if budget.replays > 2:
                raise ReviewError("Pending-action replay budget exhausted.", 4)
            action_id, decision = pending
        else:
            prior_seconds = budget.reserve(max_calls, max_seconds)
            save()  # A crash during provider execution keeps a conservative time reservation.
            failpoint("after_provider_reservation")
            action_id = f"action-{budget.calls:04d}"
            decision = None
            if provider.kind == "ollama":
                previous_usage = {"prompt_tokens": budget.prompt_tokens,
                                  "completion_tokens": budget.completion_tokens}
                budget.provider_requests += 1
                # A crash/cancel before a response cannot preserve an invented zero token count.
                budget.prompt_tokens = budget.completion_tokens = None
                save()
            try:
                decision = provider.next(registry.observation(),
                    {"calls": max_calls - budget.calls + 1, "seconds": max_seconds - prior_seconds})
                if len(canonical(decision)) > 16 * 1024:
                    raise ProviderFailure("Decision byte budget exceeded.", protocol=True)
            except ProviderFailure as exc:
                budget.seconds_used = prior_seconds + max(0, clock() - started)
                if provider.kind == "ollama":
                    budget.prompt_tokens = budget.completion_tokens = None
                registry.last_error = str(exc)
                event = {"decision": None, "result": None, "error": str(exc)}
                registry.history.append(event)
                if exc.retryable and budget.transient_retries < 1:
                    budget.transient_retries += 1
                    sleep(0.2)
                    budget.seconds_used += 0.2
                elif exc.protocol and budget.protocol_repairs < 2:
                    budget.protocol_repairs += 1
                else:
                    if journal:
                        journal.commit_action(action_id, event, checkpoint())
                    else:
                        record_event(event)
                    raise
                if journal:
                    journal.commit_action(action_id, event, checkpoint())
                else:
                    record_event(event)
                continue
            except (TypeError, ValueError, RecursionError) as exc:
                budget.seconds_used = prior_seconds + max(0, clock() - started)
                save()
                raise ReviewError("Provider returned a non-JSON protocol value.", 4) from exc
            budget.seconds_used = prior_seconds + max(0, clock() - started)
            if budget.seconds_used >= max_seconds:
                save()
                raise ReviewError("Analysis wall-time budget exhausted.", 4)
            usage = getattr(provider, "last_usage", None)
            if provider.kind == "ollama":
                for source_key, target_key in (("prompt_tokens", "prompt_tokens"),
                                               ("completion_tokens", "completion_tokens")):
                    value = usage.get(source_key) if usage else None
                    previous = previous_usage[target_key]
                    setattr(budget, target_key, None if value is None or previous is None else previous + value)
            budget.tool_calls += 1
            if journal:
                journal.begin_action(action_id, decision, checkpoint())
            failpoint("after_intent_commit")
        budget.execution_attempts += 1
        save()
        try:
            result = registry.execute(decision)
            registry.last_error = None
            event = {"decision": decision, "result": result, "error": None}
        except ReviewError as exc:
            registry.last_error = str(exc)
            event = {"decision": decision, "result": None, "error": str(exc)}
            if isinstance(decision, dict) and decision.get("tool") == "propose_finding":
                rule_id = decision.get("arguments", {}).get("rule_id")
                key = rule_id if isinstance(rule_id, str) else "invalid"
                budget.proposal_repairs[key] = budget.proposal_repairs.get(key, 0) + 1
                exhausted = budget.proposal_repairs[key] > 2
            else:
                budget.protocol_repairs += 1
                exhausted = budget.protocol_repairs > 2
            if exhausted:
                budget.seconds_used = prior_seconds + max(0, clock() - started)
                registry.history.append(event)
                if journal:
                    journal.commit_action(action_id, event, checkpoint())
                else:
                    record_event(event)
                raise ReviewError("Provider/tool repair budget exhausted.", 4) from exc
        failpoint("after_tool_before_commit")
        budget.seconds_used = prior_seconds + max(0, clock() - started)
        if budget.seconds_used >= max_seconds:
            registry.submitted = False
            save()
            raise ReviewError("Analysis wall-time budget exhausted.", 4)
        registry.history.append(event)
        if journal:
            journal.commit_action(action_id, event, checkpoint())
        else:
            record_event(event)
        failpoint("after_checkpoint_commit")
    return budget.usage(provider.kind)


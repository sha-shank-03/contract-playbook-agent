"""Pure cumulative U1 bounds; reservations survive interrupted decisions."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from ..providers.gateway import GatewayFailure


@dataclass
class Budget:
    steps: int = 0
    requests: int = 0
    tool_attempts: int = 0
    rejected: int = 0
    replays: int = 0
    seconds_used: float = 0
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    request_in_flight: bool = False

    @classmethod
    def restore(cls, data, config):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise GatewayFailure("INVALID_CHECKPOINT")
        value = cls(**data)
        for name in ("steps", "requests", "tool_attempts", "rejected", "replays"):
            if type(getattr(value, name)) is not int or getattr(value, name) < 0:
                raise GatewayFailure("INVALID_CHECKPOINT")
        for name in ("prompt_tokens", "completion_tokens"):
            item = getattr(value, name)
            if item is not None and (type(item) is not int or item < 0):
                raise GatewayFailure("INVALID_CHECKPOINT")
        if (type(value.seconds_used) not in (int, float) or not math.isfinite(value.seconds_used)
                or value.seconds_used < 0 or type(value.request_in_flight) is not bool
                or value.steps > config.max_steps or value.requests > config.max_requests
                or value.tool_attempts > config.max_steps or value.replays > 2
                or value.requests > value.steps
                or value.completion_tokens is not None
                and value.completion_tokens > value.requests * config.completion_tokens):
            raise GatewayFailure("INVALID_CHECKPOINT")
        return value

    def reserve(self, config):
        if self.request_in_flight:
            raise GatewayFailure("AMBIGUOUS_PREVIOUS_REQUEST")
        if (self.steps >= config.max_steps or self.requests >= config.max_requests
                or self.seconds_used >= config.max_seconds):
            raise GatewayFailure("BUDGET_EXHAUSTED")
        prior = self.seconds_used
        self.steps += 1
        self.requests += 1
        self.seconds_used += min(config.request_seconds, config.max_seconds - prior)
        self.request_in_flight = True
        return prior

    def settle(self, prior, elapsed, metadata=None):
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise GatewayFailure("INVALID_CLOCK")
        self.seconds_used = prior + elapsed
        self.request_in_flight = False
        for name in ("prompt_tokens", "completion_tokens"):
            observed = (metadata or {}).get(name)
            old = getattr(self, name)
            setattr(self, name, old + observed if old is not None and observed is not None else None)

    def public(self):
        return asdict(self)

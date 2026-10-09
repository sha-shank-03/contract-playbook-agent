"""Genuine native Ollama adapter; no server/model is provisioned or assumed."""
from __future__ import annotations

import subprocess
import sys
import time

from ..common import canonical, parse_json
from .contract import ProviderFailure, build_request, parse_response, validate_endpoint


class SupervisedTransport:
    def request(self, endpoint, request, remaining_seconds, cancel=lambda: False):
        deadline = time.monotonic() + min(20, remaining_seconds)
        if remaining_seconds <= 0:
            raise ProviderFailure("Provider deadline already exhausted.")
        child = subprocess.Popen([sys.executable, "-m", "contract_playbook.providers.transport"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        payload = canonical({"endpoint": endpoint, "request": request,
                             "socket_timeout": min(15, remaining_seconds)})
        first = True
        try:
            while True:
                if cancel():
                    raise KeyboardInterrupt()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderFailure("Provider absolute deadline exceeded.", retryable=True)
                try:
                    stdout, stderr = child.communicate(payload if first else None, timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if len(stdout) > 128 * 1024 or len(stderr) > 8192 or child.returncode != 0:
                raise ProviderFailure("Owned transport worker failed or exceeded output limits.")
            envelope = parse_json(stdout, 128 * 1024)
            if not isinstance(envelope, dict) or "ok" not in envelope:
                raise ProviderFailure("Invalid transport envelope.")
            if not envelope["ok"]:
                raise ProviderFailure(envelope.get("error", "Transport failed."),
                                      retryable=envelope.get("retryable") is True,
                                      protocol=envelope.get("protocol") is True)
            return canonical(envelope["response"])
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()


class OllamaChatProvider:
    kind = "ollama"

    def __init__(self, model, endpoint, transport=None, cancel=lambda: False):
        self.endpoint = validate_endpoint(endpoint)
        self.model = model
        self.transport = transport or SupervisedTransport()
        self.cancel = cancel
        self.last_usage = None

    def next(self, observation, remaining_budget):
        self.last_usage = None
        request = build_request(self.model, observation, remaining_budget)
        raw = self.transport.request(self.endpoint, request, remaining_budget["seconds"], self.cancel)
        decision, self.last_usage = parse_response(raw)
        return decision


"""Supervised fixed-purpose transport, authored but unexecuted until a lease.

U1 service refuses live mode. The test-only class accepts loopback; no CLI endpoint
override can label that transport live. Credentials never appear in arguments.
"""
from __future__ import annotations

import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from ..common import canonical, parse_json
from .gateway import ENDPOINT, GatewayFailure


def _loopback(endpoint):
    try:
        value = urlsplit(endpoint)
        valid = (value.scheme == "http" and value.hostname == "127.0.0.1"
                 and value.port is not None and 1 <= value.port <= 65535
                 and not value.username and not value.password and not value.query
                 and not value.fragment and value.path == "/v1/chat/completions")
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise GatewayFailure("INVALID_DOUBLE_ENDPOINT")
    return endpoint


class GatewayHTTPTransport:
    mode = "live"

    def __init__(self, key_loader=None):
        self.key_loader = key_loader
        self.last_owned_pid = None
        self.cleanup_status = "no_child_started"

    def request(self, endpoint, request, remaining_seconds, cancel):
        started = time.monotonic()
        deadline = started + min(20, remaining_seconds)
        if cancel():
            raise KeyboardInterrupt()
        if remaining_seconds <= 0 or endpoint != ENDPOINT:
            raise GatewayFailure("TRANSPORT_DENIED")
        if self.mode == "live":
            # Only a future main-approved loader may supply this; U1 never calls it.
            if self.key_loader is None:
                raise GatewayFailure("LIVE_DISABLED")
            key = self.key_loader()
            target = ENDPOINT
        else:
            key, target = "synthetic-local-double", self.endpoint
        if not isinstance(key, str) or not key or len(key) > 4096 or "\r" in key or "\n" in key:
            raise GatewayFailure("INVALID_CREDENTIAL")
        payload = canonical({"kind": self.mode, "endpoint": target, "api_key": key,
                             "request": request, "socket_timeout": min(10, remaining_seconds)})
        if len(payload) > 128 * 1024:
            raise GatewayFailure("REQUEST_TOO_LARGE")
        if cancel():
            raise KeyboardInterrupt()
        if time.monotonic() >= deadline - .25:
            raise GatewayFailure("REQUEST_DEADLINE")
        child = subprocess.Popen([sys.executable, "-B", "-m",
                                  "contract_playbook.providers.gateway_transport", "--worker"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.last_owned_pid, self.cleanup_status = child.pid, "child_started"
        first = True
        try:
            while True:
                if cancel():
                    raise KeyboardInterrupt()
                left = deadline - time.monotonic() - .25
                if left <= 0:
                    raise GatewayFailure("REQUEST_DEADLINE")
                try:
                    stdout, stderr = child.communicate(payload if first else None, timeout=min(.05, left))
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if len(stdout) > 128 * 1024 or len(stderr) > 8192 or child.returncode != 0:
                raise GatewayFailure("TRANSPORT_WORKER_FAILED")
            result = parse_json(stdout, 128 * 1024)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise GatewayFailure("TRANSPORT_WORKER_FAILED")
            if not result["ok"]:
                raise GatewayFailure(result.get("code", "TRANSPORT_FAILED"))
            return canonical(result["body"])
        finally:
            try:
                if child.poll() is None:
                    child.kill()
                    try:
                        child.wait(timeout=max(0, min(.25, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        self.cleanup_status = "termination_unconfirmed"
                        raise GatewayFailure("CLEANUP_UNCONFIRMED") from None
                self.cleanup_status = "owned_child_exited"
            finally:
                for stream in (child.stdin, child.stdout, child.stderr):
                    stream.close()


class GatewayDoubleHTTPTransport(GatewayHTTPTransport):
    mode = "local-double"

    def __init__(self, endpoint):
        super().__init__()
        self.endpoint = _loopback(endpoint)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, "Redirect denied", headers, response)


def worker():
    try:
        data = parse_json(sys.stdin.buffer.read(128 * 1024 + 1), 128 * 1024)
        if data["kind"] == "local-double":
            target = _loopback(data["endpoint"])
        elif data["kind"] == "live" and data["endpoint"] == ENDPOINT:
            target = ENDPOINT
        else:
            raise GatewayFailure("TRANSPORT_DENIED")
        raw = canonical(data["request"])
        timeout, key = data["socket_timeout"], data["api_key"]
        if (len(raw) > 96 * 1024 or type(timeout) not in (int, float) or not 0 < timeout <= 10
                or not isinstance(key, str) or not 0 < len(key) <= 4096 or "\r" in key or "\n" in key):
            raise GatewayFailure("TRANSPORT_DENIED")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        request = urllib.request.Request(target, data=raw, method="POST",
                                        headers={"Content-Type": "application/json",
                                                 "Authorization": "Bearer " + key})
        with opener.open(request, timeout=timeout) as response:
            body = response.read(64 * 1024 + 1)
        if len(body) > 64 * 1024:
            raise GatewayFailure("RESPONSE_TOO_LARGE")
        result = {"ok": True, "body": parse_json(body, 64 * 1024)}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "code": f"HTTP_{exc.code}"}
    except GatewayFailure as exc:
        result = {"ok": False, "code": exc.status}
    except Exception:
        result = {"ok": False, "code": "TRANSPORT_OR_RESPONSE_LOST"}
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit(4)
    raise SystemExit(worker())

"""LEASE REQUIRED: loopback sockets and owned subprocesses; no live Gateway."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from contract_playbook.bundle import load_bundle
from contract_playbook.playbook import load_playbook
from contract_playbook.providers.gateway import ENDPOINT, GatewayChatProvider, GatewayConfig, GatewayFailure
from contract_playbook.providers.gateway_transport import GatewayDoubleHTTPTransport
from contract_playbook.service import REPOSITORY
from contract_playbook.tools import ToolRegistry
from contract_playbook.upgrade.double import FictionalGatewayDouble


@contextmanager
def server(mode):
    requests, stop = [], threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            if mode == "lost":
                self.close_connection = True
                return
            if mode.startswith("HTTP_"):
                self.send_response(int(mode[5:]))
                self.end_headers()
                self.wfile.write(b"synthetic-private-error-body")
                return
            if mode == "slow":
                stop.wait(4)
            self.send_response(200)
            self.end_headers()
            try:
                if mode == "trickle":
                    for _ in range(80):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        if stop.wait(.05):
                            break
                elif mode == "oversize":
                    self.wfile.write(b"x" * (64 * 1024 + 1))
                elif mode == "malformed":
                    self.wfile.write(b"not-json")
                else:
                    raw = FictionalGatewayDouble().request(ENDPOINT, request, 20, lambda: False)
                    if mode == "unknown":
                        value = json.loads(raw)
                        value["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "approve"
                        raw = json.dumps(value).encode()
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    http.daemon_threads = True
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/v1/chat/completions", requests
    finally:
        stop.set()
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        bundle = load_bundle(REPOSITORY / "fixtures/upgrade/u1-paraphrase")
        self.observation = ToolRegistry(bundle, load_playbook(
            REPOSITORY / "fixtures/playbooks/buyer-services-v2.json")).observation()
        self.budget = {"seconds": 3, "attempt": 1}

    def test_native_http_roundtrip_and_owned_cleanup(self):
        with server("normal") as (endpoint, requests):
            transport = GatewayDoubleHTTPTransport(endpoint)
            decision = GatewayChatProvider(GatewayConfig("demo/u1"), transport).next(self.observation, self.budget)
            self.assertEqual(decision["tool"], "get_rule")
            self.assertEqual(len(requests), 1)
            self.assertEqual(transport.cleanup_status, "owned_child_exited")

    def test_status_codes_no_retry_and_no_error_body(self):
        for status in (401, 402, 429, 500, 503):
            with self.subTest(status=status), server(f"HTTP_{status}") as (endpoint, requests):
                transport = GatewayDoubleHTTPTransport(endpoint)
                with self.assertRaisesRegex(GatewayFailure, f"HTTP_{status}") as raised:
                    GatewayChatProvider(GatewayConfig("demo/u1"), transport).next(self.observation, self.budget)
                self.assertNotIn("synthetic-private-error-body", str(raised.exception))
                self.assertEqual(len(requests), 1)
                self.assertEqual(transport.cleanup_status, "owned_child_exited")

    def test_malformed_unknown_oversized_and_lost_response(self):
        for mode in ("malformed", "unknown", "oversize", "lost"):
            with self.subTest(mode=mode), server(mode) as (endpoint, requests):
                transport = GatewayDoubleHTTPTransport(endpoint)
                with self.assertRaises(GatewayFailure):
                    GatewayChatProvider(GatewayConfig("demo/u1"), transport).next(self.observation, self.budget)
                self.assertEqual(len(requests), 1)
                self.assertEqual(transport.cleanup_status, "owned_child_exited")

    def test_absolute_deadline_slow_headers_and_body(self):
        for mode in ("slow", "trickle"):
            with self.subTest(mode=mode), server(mode) as (endpoint, requests):
                transport = GatewayDoubleHTTPTransport(endpoint)
                started = time.monotonic()
                with self.assertRaisesRegex(GatewayFailure, "REQUEST_DEADLINE"):
                    GatewayChatProvider(GatewayConfig("demo/u1"), transport).next(
                        self.observation, {"seconds": 1.5, "attempt": 1})
                self.assertLess(time.monotonic() - started, 2)
                self.assertEqual(len(requests), 1)
                self.assertEqual(transport.cleanup_status, "owned_child_exited")

    def test_cancel_kills_owned_child(self):
        with server("slow") as (endpoint, requests):
            transport = GatewayDoubleHTTPTransport(endpoint)
            started = time.monotonic()
            cancel = lambda: time.monotonic() - started > .5
            with self.assertRaises(KeyboardInterrupt):
                GatewayChatProvider(GatewayConfig("demo/u1"), transport, cancel).next(self.observation, self.budget)
            self.assertLess(time.monotonic() - started, 1.2)
            self.assertEqual(transport.cleanup_status, "owned_child_exited")

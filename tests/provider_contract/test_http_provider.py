"""LEASE REQUIRED: real loopback HTTP and owned transport subprocesses, fake model only."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from contract_playbook.common import canonical
from contract_playbook.provider import ScriptedDecisionProvider
from contract_playbook.providers.contract import ProviderFailure
from contract_playbook.providers.ollama import OllamaChatProvider, SupervisedTransport
from contract_playbook.service import REPOSITORY, run_case
from contract_playbook.store import RunStore
from contract_playbook.tools import ToolRegistry
from contract_playbook.bundle import load_bundle
from contract_playbook.playbook import load_playbook


@contextmanager
def fake_server(mode="normal"):
    requests, stop = [], threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            count = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(count))
            requests.append(request)
            try:
                if mode == "stall":
                    stop.wait(4)
                    self.send_response(200)
                    self.end_headers()
                    return
                if mode == "trickle":
                    self.send_response(200)
                    self.end_headers()
                    for _ in range(80):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        if stop.wait(0.05):
                            break
                    return
                if mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/api/other")
                    self.end_headers()
                    return
                if mode in ("503-once", "400") and (len(requests) == 1 or mode == "400"):
                    self.send_response(503 if mode == "503-once" else 400)
                    self.end_headers()
                    return
                observation = json.loads(request["messages"][1]["content"].split("\n", 1)[1])["observation"]
                decision = ScriptedDecisionProvider().next(observation, {"calls": 48, "seconds": 120})
                if mode == "malformed-once" and len(requests) == 1:
                    raw = b"not JSON"
                elif mode == "invalid-always" or mode == "invalid-once" and len(requests) == 1:
                    raw = b'{"message":{"role":"assistant","tool_calls":[]}}'
                elif mode == "oversized":
                    raw = b"x" * (64 * 1024 + 1)
                else:
                    raw = canonical({"model": "fake-only", "done": True,
                        "message": {"role": "assistant", "content": "", "tool_calls": [
                            {"function": {"name": decision["tool"], "arguments": decision["arguments"]}}]},
                        "prompt_eval_count": 0, "eval_count": 0})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/chat", requests
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class NativeHTTPProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (REPOSITORY / "work").mkdir(exist_ok=True)

    def observation(self):
        return ToolRegistry(load_bundle(REPOSITORY / "fixtures/dev/compliant-review"),
                            load_playbook(REPOSITORY / "fixtures/playbooks/buyer-services-v1.json")).observation()

    def full_run(self, mode):
        with tempfile.TemporaryDirectory(prefix="contract-fake-http-", dir=REPOSITORY / "work") as tmp, fake_server(mode) as (endpoint, requests):
            packet = run_case(REPOSITORY / "fixtures/dev/compliant-review",
                REPOSITORY / "fixtures/playbooks/buyer-services-v1.json", Path(tmp) / "run",
                provider_kind="ollama", endpoint=endpoint, model="fake-only")
            store = RunStore(Path(tmp) / "run")
            try:
                usage, events = store.usage(), store.events()
            finally:
                store.close()
            return packet, usage, events, requests

    def test_full_native_wire_history_and_observed_usage(self):
        packet, usage, events, requests = self.full_run("normal")
        self.assertEqual(packet["domain_status"], "PENDING_REVIEW")
        self.assertTrue(packet["live_model"])  # Genuine adapter route; fake HTTP is still not a model evaluation.
        self.assertFalse(packet["model_quality_evaluated"])
        self.assertEqual(usage["provider_requests"], len(requests))
        self.assertEqual(usage["model_tokens"], 0)  # Explicit zero counters from the fake, not fabricated.
        self.assertGreater(len(events), 3)
        final = requests[-1]
        self.assertFalse(final["stream"])
        self.assertEqual(final["model"], "fake-only")
        self.assertTrue(any(message["role"] == "tool" for message in final["messages"]))
        self.assertTrue(any(message.get("tool_calls") for message in final["messages"]))
        self.assertEqual({function["function"]["name"] for function in final["tools"]},
                         {"get_rule", "search_clauses", "read_blocks", "scan_document", "resolve_reference",
                          "propose_finding", "submit_review"})
        self.assertEqual([event["decision"]["tool"] for event in events if event["error"] is None][-1], "submit_review")

    def test_transient_503_retries_once_and_records_error(self):
        packet, usage, events, requests = self.full_run("503-once")
        self.assertEqual(packet["domain_status"], "PENDING_REVIEW")
        self.assertEqual(usage["transient_retries"], 1)
        self.assertEqual(sum(event["error"] is not None for event in events), 1)
        self.assertEqual(usage["provider_requests"], len(requests))
        self.assertIsNone(usage["model_tokens"])

    def test_protocol_error_repairs_and_preserves_history(self):
        packet, usage, events, requests = self.full_run("invalid-once")
        self.assertEqual(packet["domain_status"], "PENDING_REVIEW")
        self.assertEqual(usage["protocol_repairs"], 1)
        self.assertEqual(sum(event["error"] is not None for event in events), 1)
        self.assertEqual(usage["provider_requests"], len(requests))

    def test_permanent_http_error_does_not_retry(self):
        with fake_server("400") as (endpoint, requests):
            p = OllamaChatProvider("fake-only", endpoint)
            with self.assertRaises(ProviderFailure) as error:
                p.next(self.observation(), {"calls": 3, "seconds": 3})
            self.assertFalse(error.exception.retryable)
            self.assertEqual(len(requests), 1)

    def test_malformed_wire_json_is_bounded_protocol_repair(self):
        packet, usage, events, requests = self.full_run("malformed-once")
        self.assertEqual(packet["domain_status"], "PENDING_REVIEW")
        self.assertEqual(usage["protocol_repairs"], 1)
        self.assertIsNone(usage["model_tokens"])

    def test_redirect_is_not_followed(self):
        with fake_server("redirect") as (endpoint, requests):
            with self.assertRaises(ProviderFailure) as error:
                OllamaChatProvider("fake-only", endpoint).next(self.observation(), {"calls": 1, "seconds": 3})
            self.assertFalse(error.exception.retryable)
            self.assertEqual(len(requests), 1)

    def test_oversized_response_is_rejected(self):
        with fake_server("oversized") as (endpoint, requests):
            with self.assertRaises(ProviderFailure):
                OllamaChatProvider("fake-only", endpoint).next(self.observation(), {"calls": 1, "seconds": 3})
            self.assertEqual(len(requests), 1)

    def test_protocol_repair_budget_stops(self):
        with tempfile.TemporaryDirectory(dir=REPOSITORY / "work") as tmp, fake_server("invalid-always") as (endpoint, requests):
            with self.assertRaises(ProviderFailure):
                run_case(REPOSITORY / "fixtures/dev/compliant-review",
                         REPOSITORY / "fixtures/playbooks/buyer-services-v1.json", Path(tmp) / "run",
                         provider_kind="ollama", endpoint=endpoint, model="fake-only")
            self.assertEqual(len(requests), 3)
            store = RunStore(Path(tmp) / "run")
            try:
                self.assertEqual(store.state(), "FAILED")
                self.assertEqual(store.load_checkpoint()["budget"]["provider_requests"], 3)
            finally:
                store.close()

    def supervise(self, endpoint, seconds, cancel):
        import subprocess
        original, children = subprocess.Popen, []
        def owned(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch("contract_playbook.providers.ollama.subprocess.Popen", side_effect=owned):
            try:
                SupervisedTransport().request(endpoint, {"model": "fake-only",
                    "messages": [{"role": "system"}, {"role": "user", "content": 'state\n{"observation":{}}'}]},
                    seconds, cancel)
            finally:
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())

    def test_absolute_deadline_cleans_owned_worker(self):
        with fake_server("stall") as (endpoint, _):
            start = time.monotonic()
            with self.assertRaises(ProviderFailure):
                self.supervise(endpoint, 0.3, lambda: False)
            self.assertLess(time.monotonic() - start, 2.5)

    def test_cancellation_cleans_owned_worker(self):
        with fake_server("stall") as (endpoint, _):
            start = time.monotonic()
            with self.assertRaises(KeyboardInterrupt):
                self.supervise(endpoint, 3, lambda: time.monotonic() - start > 0.15)
            self.assertLess(time.monotonic() - start, 2.5)

    def test_absolute_deadline_stops_continuous_trickle(self):
        with fake_server("trickle") as (endpoint, _):
            start = time.monotonic()
            with self.assertRaises(ProviderFailure):
                self.supervise(endpoint, 0.3, lambda: False)
            self.assertLess(time.monotonic() - start, 2.5)


if __name__ == "__main__":
    unittest.main()

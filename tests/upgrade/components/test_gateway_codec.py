"""Pure codec tests: no socket, process, credentials or end-to-end run."""
import copy
import json
import unittest

from contract_playbook.common import canonical, ReviewError
from contract_playbook.providers.gateway import (
    ENDPOINT, GatewayChatProvider, GatewayConfig, GatewayFailure,
    build_gateway_request, parse_gateway_response)
from contract_playbook.providers.gateway_transport import GatewayHTTPTransport, _loopback


def reply(**changes):
    value = {"id": "double_1", "model": "demo/u1", "choices": [{
        "index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "get_rule", "arguments": '{"rule_id":"REN-01"}'}}]}}]}
    value.update(changes)
    return value


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.config = GatewayConfig("demo/u1")
        self.observation = {"tools": [], "history": [], "rule_ids": ["REN-01"]}

    def test_native_string_arguments(self):
        decision, meta = parse_gateway_response(canonical(reply()), self.config)
        self.assertEqual(decision, {"tool": "get_rule", "arguments": {"rule_id": "REN-01"}})
        self.assertIsNone(meta["prompt_tokens"])
        self.assertIsNone(meta["generation_id"])

    def test_call_result_ids_preserved(self):
        self.observation["history"] = [{"decision": {"tool": "get_rule", "arguments": {"rule_id": "REN-01"}},
                                        "provider_call_id": "call_1", "result": {"limit": 30}, "error": None}]
        request = build_gateway_request(self.config, self.observation, {"seconds": 5})
        self.assertEqual(request["messages"][-1]["tool_call_id"], "call_1")
        self.assertIsInstance(request["messages"][-2]["tool_calls"][0]["function"]["arguments"], str)
        self.assertEqual(json.loads(request["messages"][-1]["content"])["result"]["limit"], 30)

    def test_unknown_and_parallel_tools(self):
        for parallel in (False, True):
            value = reply()
            calls = value["choices"][0]["message"]["tool_calls"]
            calls[0]["function"]["name"] = "approve"
            if parallel:
                calls.append(copy.deepcopy(calls[0]))
            with self.assertRaises(GatewayFailure):
                parse_gateway_response(canonical(value), self.config)

    def test_malformed_nonfinite_duplicate(self):
        for raw in (b"not-json", b'{"x":NaN}', b'{"x":1,"x":2}', b"x" * (64 * 1024 + 1)):
            with self.assertRaises(GatewayFailure):
                parse_gateway_response(raw, self.config)

    def test_ollama_argument_object_is_rejected(self):
        value = reply()
        value["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = {"rule_id": "REN-01"}
        with self.assertRaises(GatewayFailure):
            parse_gateway_response(canonical(value), self.config)

    def test_truncation_mismatch_reused_id(self):
        value = reply()
        value["choices"][0]["finish_reason"] = "length"
        for response, ids in ((value, ()), (reply(model="other/model"), ()),
                              (reply(id="synthetic-private-text"), ()), (reply(), ("call_1",))):
            with self.assertRaises(GatewayFailure):
                parse_gateway_response(canonical(response), self.config, ids)

    def test_usage_and_token_cap(self):
        for usage in ({"prompt_tokens": True}, {"completion_tokens": 2049},
                      {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 14}):
            with self.assertRaises(GatewayFailure):
                parse_gateway_response(canonical(reply(usage=usage)), self.config)
        _, meta = parse_gateway_response(canonical(reply(usage={"prompt_tokens": 10,
                                                                "completion_tokens": 3})), self.config)
        self.assertEqual(meta["completion_tokens"], 3)

    def test_no_context_truncation(self):
        self.observation["source"] = "x" * (96 * 1024)
        with self.assertRaises(GatewayFailure):
            build_gateway_request(self.config, self.observation, {})

    def test_explicit_model_and_bounded_config(self):
        for kwargs in ({"model": "gpt-6.1-sol"}, {"model": "demo/u1", "max_requests": True},
                       {"model": "demo/u1", "max_seconds": float("inf")}):
            with self.assertRaises(ReviewError):
                GatewayConfig(**kwargs)

    def test_live_gate_does_not_invoke_loader(self):
        calls = []
        transport = GatewayHTTPTransport(lambda: calls.append("key-loader"))
        with self.assertRaisesRegex(GatewayFailure, "LIVE_DISABLED"):
            GatewayChatProvider(self.config, transport)
        self.assertEqual(calls, [])

    def test_loopback_endpoint_is_test_only(self):
        self.assertEqual(_loopback("http://127.0.0.1:1234/v1/chat/completions"),
                         "http://127.0.0.1:1234/v1/chat/completions")
        for endpoint in (ENDPOINT, "http://localhost:1234/v1/chat/completions",
                         "http://user@127.0.0.1:1234/v1/chat/completions"):
            with self.assertRaises(GatewayFailure):
                _loopback(endpoint)

    def test_parse_and_transport_are_inside_request_deadline(self):
        clock = [0]
        class Double:
            mode = "local-double"
            def request(self, *args):
                clock[0] = 21
                return canonical(reply())
        provider = GatewayChatProvider(self.config, Double(), clock=lambda: clock[0])
        with self.assertRaisesRegex(GatewayFailure, "REQUEST_DEADLINE"):
            provider.next(self.observation, {"seconds": 120})

"""Pure U2-A schema/authority/UTF-16 controls; no files, SQLite, sockets or remote calls."""
import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock

from contract_playbook.common import canonical, sha256
from contract_playbook.connectors.docs_double import ReadDouble, document_response
from contract_playbook.connectors.google_docs import (
    DRIVE_FILE_SCOPE, DocsFailure, LocalGrant, OperatorScope, decode_document, dispatch_remote,
    docs_index, prepare_copy, prepare_edit, read_local, reconcile_copy, reconcile_edit,
    remote_auth, utf16_units, validate_approval, validate_edit_preconditions,
)


def control():
    # Same mechanical Unicode vector as U1 pure controls; not a new semantic evaluation task.
    text = "Section 1 - Terms\nCafé 🤝 sixty days.\n"
    raw, manifest = text.encode(), b"unit-manifest"
    atoms = {"REN-01": ["renewal.express_written_agreement"],
             "TERM-01": ["termination.notice_days"], "PAY-01": ["payment.days"]}
    policy = {"id": "unit-fictional", "rules": [
        {"id": rule, "text": "Fictional " + rule, "obligations": values} for rule, values in atoms.items()]}
    policy_raw = canonical(policy)
    doc = {"document_id": "agreement", "document_sha256": sha256(raw), "byte_length": len(raw),
           "filename": "agreement.txt", "blocks": [{"block_id": "agreement.section-1", "title": "Terms",
                                                   "start": 0, "end": len(text)}]}
    start = text.index("sixty")
    edit = {"document_id": "agreement", "document_sha256": sha256(raw), "start": start,
            "end": start + 5, "expected_text": "sixty", "replacement": "thirty"}
    span = {"document_id": "agreement", "document_sha256": sha256(raw),
            "block_id": "agreement.section-1", "start": 0, "end": len(text), "quote": text}
    findings = [{"rule_id": rule["id"], "disposition": "deviation" if rule["id"] == "TERM-01" else "compliant",
                 "obligations": {atom: "deviation" if rule["id"] == "TERM-01" else "compliant"
                                 for atom in rule["obligations"]},
                 "evidence": [copy.deepcopy(span)], "patch": copy.deepcopy(edit) if rule["id"] == "TERM-01" else None,
                 "policy_citation": {"playbook_id": policy["id"], "playbook_sha256": sha256(policy_raw),
                                     "rule_id": rule["id"], "quote": rule["text"]}} for rule in policy["rules"]]
    coverage = {"documents": [{"document_id": "agreement", "document_sha256": sha256(raw),
                              "read_block_ids": ["agreement.section-1"], "total_blocks": 1}], "complete": True}
    core = {"schema_version": 3, "fictional": True, "execution_mode": "local-double", "live_model": False,
            "domain_status": "PENDING_REVIEW", "source": doc, "documents": [doc],
            "coverage": {**coverage, "receipt_sha256": sha256(canonical(coverage))},
            "manifest_sha256": sha256(manifest), "playbook": {"id": policy["id"], "sha256": sha256(policy_raw)},
            "findings": findings, "patches": [edit]}
    return text, {**core, "proposal_sha256": sha256(canonical(core))}, policy_raw, manifest


class DocsPureTests(unittest.TestCase):
    def setUp(self):
        self.text, self.packet, self.policy, self.manifest = control()
        self.operator = OperatorScope("fictional_account", "fictional_source", "fictional_folder",
                                      "fictional_run", "Fictional reviewed copy")
        self.grant = LocalGrant(self.operator.account_id, frozenset({DRIVE_FILE_SCOPE}))
        self.source = decode_document(document_response("fictional_source", self.text),
                                      self.operator.account_id, "fictional_source")
        self.target_id = "fictional_copy"
        self.target = decode_document(document_response(self.target_id, self.text, "copy_rev_1", "t.copy"),
                                      self.operator.account_id, self.target_id)
        self.copy = prepare_copy(self.operator, self.grant, self.source, self.packet, self.policy, self.manifest)
        self.copy_approval = self.approve(self.copy)
        self.metadata = {"id": self.target_id, "mimeType": "application/vnd.google-apps.document",
                         "parents": ["fictional_folder"], "appProperties": self.copy.value["request"]["body"]["appProperties"],
                         "trashed": False}

    def approve(self, intent):
        return {"decision": "approve", "intent_sha256": intent.sha256, "account_id": "fictional_account"}

    def edit(self, **changes):
        arguments = {"operator": self.operator, "grant": self.grant, "copy_intent": self.copy,
                     "copy_approval": self.copy_approval, "operator_target_document_id": self.target_id,
                     "copy_metadata": self.metadata, "target": self.target, "source_now": self.source,
                     "packet": self.packet, "policy_raw": self.policy, "manifest_raw": self.manifest}
        return prepare_edit(**{**arguments, **changes})

    def test_unicode_offsets_are_codepoints_to_utf16_with_body_origin(self):
        self.assertEqual(utf16_units("A🤝e\u0301"), 5)
        self.assertEqual(docs_index("A🤝e\u0301", 2), 4)
        self.assertEqual(docs_index(self.text, self.text.index("sixty")), self.text.index("sixty") + 2)
        for value in (True, -1, 1000):
            with self.assertRaises(DocsFailure):
                docs_index("a", value)
        with self.assertRaisesRegex(DocsFailure, "INVALID_UNICODE"):
            utf16_units("\ud800")

    def test_full_single_tab_body_roundtrip_and_opaque_revision(self):
        value = json.loads(document_response("fictional_source", self.text, "opaque+revision=1"))
        result = decode_document(canonical(value), "fictional_account", "fictional_source")
        self.assertEqual(result.text, self.text)
        self.assertEqual(result.revision_id, "opaque+revision=1")
        self.assertEqual(result.text_sha256, sha256(self.text.encode()))

    def test_legacy_hidden_multitab_nested_and_suggestion_documents_are_denied(self):
        base = json.loads(document_response("fictional_source", self.text))
        controls = []
        legacy = copy.deepcopy(base)
        legacy["body"] = legacy["tabs"][0]["documentTab"]["body"]
        legacy["tabs"] = []
        controls.append(legacy)
        multi = copy.deepcopy(base)
        multi["tabs"].append(copy.deepcopy(multi["tabs"][0]))
        controls.append(multi)
        nested = copy.deepcopy(base)
        nested["tabs"][0]["childTabs"] = [copy.deepcopy(nested["tabs"][0])]
        controls.append(nested)
        suggestions = copy.deepcopy(base)
        suggestions["suggestions"] = [{"untrusted": "suggestion"}]
        controls.append(suggestions)
        for value in controls:
            with self.assertRaises(DocsFailure):
                decode_document(canonical(value), "fictional_account", "fictional_source")

    def test_tables_objects_headers_styles_and_unknown_structures_are_denied(self):
        base = json.loads(document_response("fictional_source", self.text))
        for field in ("table", "tableOfContents"):
            value = copy.deepcopy(base)
            paragraph = value["tabs"][0]["documentTab"]["body"]["content"][1]
            del paragraph["paragraph"]
            paragraph[field] = {}
            with self.assertRaises(DocsFailure):
                decode_document(canonical(value), "fictional_account", "fictional_source")
        for field in ("headers", "footers", "footnotes", "inlineObjects", "namedRanges"):
            value = copy.deepcopy(base)
            value["tabs"][0]["documentTab"][field] = {"unsupported": {}}
            with self.assertRaises(DocsFailure):
                decode_document(canonical(value), "fictional_account", "fictional_source")
        value = copy.deepcopy(base)
        value["tabs"][0]["documentTab"]["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]["textStyle"] = {"link": {"url": "https://invalid.example"}}
        with self.assertRaises(DocsFailure):
            decode_document(canonical(value), "fictional_account", "fictional_source")

    def test_index_gaps_boolean_indices_and_partial_reads_are_denied(self):
        for field, new in (("startIndex", True), ("startIndex", 2), ("endIndex", 1000)):
            value = json.loads(document_response("fictional_source", self.text))
            value["tabs"][0]["documentTab"]["body"]["content"][1][field] = new
            with self.assertRaises(DocsFailure):
                decode_document(canonical(value), "fictional_account", "fictional_source")
        for raw in (b"{}", b"\xff", b'{"documentId":"a","documentId":"b"}', b"x" * (256 * 1024 + 1)):
            with self.assertRaises(DocsFailure) as error:
                decode_document(raw, "fictional_account", "fictional_source")
            self.assertNotIn("documentId", str(error.exception))

    def test_text_and_paragraph_limits_are_enforced(self):
        for text in ("a" * (64 * 1024) + "\n", "a\n" * 129):
            with self.assertRaises(DocsFailure):
                decode_document(document_response("fictional_source", text), "fictional_account", "fictional_source")

    def test_account_scope_and_identifier_authority_never_reaches_read_double(self):
        double = ReadDouble("fictional_source", document_response("fictional_source", self.text))
        for grant in (LocalGrant("another_account", frozenset({DRIVE_FILE_SCOPE})),
                      LocalGrant("fictional_account", frozenset({"https://www.googleapis.com/auth/drive"}))):
            with self.assertRaises(DocsFailure):
                read_local(self.operator, grant, double)
        self.assertEqual(double.calls, [])
        for value in ("https://invalid.example/document", "../source", "source?token=untrusted"):
            with self.assertRaises(DocsFailure):
                replace(self.operator, source_document_id=value)

    def test_read_uses_complete_tab_query_and_single_attempt(self):
        double = ReadDouble("fictional_source", document_response("fictional_source", self.text))
        self.assertEqual(read_local(self.operator, self.grant, double, clock=lambda: 0), self.source)
        self.assertEqual(len(double.calls), 1)
        self.assertEqual(double.calls[0]["params"], {"includeTabsContent": True, "suggestionsViewMode": "SUGGESTIONS_INLINE"})
        self.assertEqual(double.calls[0]["limit"], 256 * 1024)

    def test_read_deadline_and_cancellation_do_not_retry(self):
        double = ReadDouble("fictional_source", document_response("fictional_source", self.text))
        clock = iter((0, 6))
        with self.assertRaisesRegex(DocsFailure, "READ_DEADLINE"):
            read_local(self.operator, self.grant, double, clock=lambda: next(clock))
        self.assertEqual(len(double.calls), 1)
        unused = ReadDouble("fictional_source", b"")
        with self.assertRaisesRegex(DocsFailure, "CANCELLED"):
            read_local(self.operator, self.grant, unused, cancel=lambda: True)
        self.assertEqual(unused.calls, [])

    def test_remote_gate_never_calls_main_loader_or_transport(self):
        loader, transport = Mock(), Mock()
        with self.assertRaisesRegex(DocsFailure, "REMOTE_DISABLED"):
            remote_auth(loader)
        with self.assertRaisesRegex(DocsFailure, "REMOTE_DISABLED"):
            dispatch_remote(self.copy, self.copy_approval, loader, transport)
        loader.assert_not_called()
        transport.assert_not_called()

    def test_read_errors_are_sanitized_without_retry_or_provider_text(self):
        double = Mock(mode="local-double")
        double.get_document.side_effect = RuntimeError("synthetic-private-error-body")
        with self.assertRaisesRegex(DocsFailure, "LOCAL_READ_FAILED") as error:
            read_local(self.operator, self.grant, double)
        self.assertNotIn("synthetic-private-error-body", str(error.exception))
        self.assertEqual(double.get_document.call_count, 1)

    def test_cancellation_after_parse_prevents_returning_snapshot(self):
        double = ReadDouble("fictional_source", document_response("fictional_source", self.text))
        checks = iter((False, False, True))
        with self.assertRaisesRegex(DocsFailure, "CANCELLED"):
            read_local(self.operator, self.grant, double, clock=lambda: 0, cancel=lambda: next(checks))
        self.assertEqual(len(double.calls), 1)

    def test_copy_intent_binds_operator_revision_proposal_folder_and_fixed_api(self):
        value = self.copy.value
        self.assertEqual(value["operator"]["account_id"], self.operator.account_id)
        self.assertEqual(value["source_revision"], self.source.revision_id)
        self.assertEqual(value["proposal_sha256"], self.packet["proposal_sha256"])
        self.assertEqual(value["request"]["host"], "www.googleapis.com")
        self.assertEqual(value["request"]["path"], "/drive/v3/files/fictional_source/copy")
        self.assertEqual(value["request"]["body"]["parents"], ["fictional_folder"])
        self.assertNotIn("requiredRevisionId", value["request"]["body"])
        self.assertEqual(value["mode"], "local-double")

    def test_explicit_approval_is_exact_intent_and_account_bound(self):
        for approval in ({**self.copy_approval, "intent_sha256": "0" * 64},
                         {**self.copy_approval, "account_id": "another_account"},
                         {**self.copy_approval, "decision": "reject"},
                         {**self.copy_approval, "model_authorized": True}):
            with self.assertRaises(DocsFailure):
                validate_approval(self.copy, approval)
        self.assertTrue(validate_approval(self.copy, self.copy_approval)["approval_bound"])

    def test_original_wrong_folder_and_unverified_copy_cannot_be_edit_target(self):
        for metadata in ({**self.metadata, "id": "fictional_source"},
                         {**self.metadata, "parents": ["another_folder"]},
                         {**self.metadata, "appProperties": {}},
                         {**self.metadata, "trashed": True}):
            with self.assertRaises(DocsFailure):
                self.edit(copy_metadata=metadata)

    def test_source_revision_account_and_copy_preimage_drift_are_denied(self):
        for source in (replace(self.source, revision_id="changed_revision"),
                       replace(self.source, account_id="another_account"),
                       replace(self.source, body_sha256="0" * 64)):
            with self.assertRaises(DocsFailure):
                self.edit(source_now=source)
        with self.assertRaises(DocsFailure):
            self.edit(target=replace(self.target, text=self.text + "Changed"))
        with self.assertRaises(DocsFailure):
            self.edit(operator_target_document_id="fictional_source")

    def test_resigned_proposal_drift_remains_denied(self):
        packet = copy.deepcopy(self.packet)
        for edit in (packet["patches"][0], packet["findings"][1]["patch"]):
            edit["replacement"] = "30 calendar"
        packet["proposal_sha256"] = sha256(canonical({k: v for k, v in packet.items() if k != "proposal_sha256"}))
        with self.assertRaisesRegex(DocsFailure, "PROPOSAL_DRIFT"):
            self.edit(packet=packet)

    def test_batch_uses_copy_revision_and_explicit_copy_tab_utf16_ranges(self):
        intent = self.edit()
        body = intent.value["request"]["body"]
        self.assertEqual(body["writeControl"], {"requiredRevisionId": "copy_rev_1"})
        self.assertNotIn("targetRevisionId", body["writeControl"])
        start = self.text.index("sixty")
        self.assertEqual(body["requests"][0]["deleteContentRange"]["range"],
                         {"startIndex": start + 2, "endIndex": start + 7, "tabId": "t.copy"})
        self.assertEqual(intent.value["request"]["path"], "/v1/documents/fictional_copy:batchUpdate")

    def test_generated_utf16_batch_reconstructs_expected_bytes_independently(self):
        buffer = self.text.encode("utf-16-le")
        for request in self.edit().value["request"]["body"]["requests"]:
            if "deleteContentRange" in request:
                span = request["deleteContentRange"]["range"]
                first, last = 2 * (span["startIndex"] - 1), 2 * (span["endIndex"] - 1)
                buffer = buffer[:first] + buffer[last:]
            else:
                insert = request["insertText"]
                first = 2 * (insert["location"]["index"] - 1)
                buffer = buffer[:first] + insert["text"].encode("utf-16-le") + buffer[first:]
        self.assertEqual(buffer.decode("utf-16-le").encode(), self.text.replace("sixty", "thirty").encode())

    def test_edit_preconditions_refuse_revision_identity_and_approval_drift(self):
        intent = self.edit()
        approval = self.approve(intent)
        self.assertEqual(validate_edit_preconditions(intent, approval, self.target, self.source)["preconditions"], "passed")
        for target in (replace(self.target, revision_id="another_revision"),
                       replace(self.target, tab_id="t.other"), replace(self.target, account_id="another_account"),
                       replace(self.target, document_id="fictional_source"), replace(self.target, body_sha256="0" * 64)):
            with self.assertRaises(DocsFailure):
                validate_edit_preconditions(intent, approval, target, self.source)
        with self.assertRaises(DocsFailure):
            validate_edit_preconditions(intent, self.copy_approval, self.target, self.source)

    def test_ambiguous_copy_zero_duplicates_or_bad_metadata_never_retries(self):
        for candidates in ([], [self.metadata, self.metadata]):
            self.assertEqual(reconcile_copy(self.copy, {"files": candidates}, self.target_id),
                             {"disposition": "RECONCILIATION_REQUIRED", "automatic_retry": False})
        result = reconcile_copy(self.copy, {"files": [self.metadata]}, self.target_id)
        self.assertEqual(result["disposition"], "COPY_METADATA_CONFIRMED")
        self.assertTrue(result["body_readback_required"])
        with self.assertRaises(DocsFailure):
            reconcile_copy(self.copy, {"files": [{**self.metadata, "appProperties": {}}]}, self.target_id)

    def test_incomplete_or_paginated_copy_listing_cannot_confirm_a_single_match(self):
        for listing in ({"files": [self.metadata], "nextPageToken": "synthetic_next_page"},
                        {"files": [self.metadata], "incompleteSearch": True}):
            self.assertEqual(reconcile_copy(self.copy, listing, self.target_id)["disposition"],
                             "RECONCILIATION_REQUIRED")
        with self.assertRaises(DocsFailure):
            reconcile_copy(self.copy, {"files": [self.metadata], "incompleteSearch": "false"}, self.target_id)

    def test_ambiguous_edit_postimage_preimage_and_drift_are_distinct_without_retry(self):
        intent = self.edit()
        post = decode_document(document_response(self.target_id, self.text.replace("sixty", "thirty"),
                                                 "copy_rev_2", "t.copy"), self.operator.account_id, self.target_id)
        self.assertEqual(reconcile_edit(intent, post)["disposition"], "POSTIMAGE_VERIFIED")
        self.assertEqual(reconcile_edit(intent, self.target)["disposition"], "PREIMAGE_UNCHANGED_NO_RETRY")
        self.assertEqual(reconcile_edit(intent, replace(self.target, revision_id="drift"))["disposition"],
                         "RECONCILIATION_REQUIRED")
        self.assertFalse(reconcile_edit(intent, post)["automatic_retry"])
        with self.assertRaises(DocsFailure):
            reconcile_edit(intent, replace(post, document_id="fictional_source"))

    def test_intent_payload_view_cannot_mutate_approved_request(self):
        digest = self.copy.sha256
        view = self.copy.value
        view["request"]["path"] = "/arbitrary/path"
        self.assertEqual(self.copy.sha256, digest)
        self.assertEqual(self.copy.value["request"]["path"], "/drive/v3/files/fictional_source/copy")

    def test_docs_stripped_characters_and_paragraph_changes_are_denied(self):
        for replacement in ("thirty\nnext", "\ue000", "thirty\t"):
            packet = copy.deepcopy(self.packet)
            for edit in (packet["patches"][0], packet["findings"][1]["patch"]):
                edit["replacement"] = replacement
            packet["proposal_sha256"] = sha256(canonical({k: v for k, v in packet.items() if k != "proposal_sha256"}))
            revised_copy = prepare_copy(self.operator, self.grant, self.source, packet, self.policy, self.manifest)
            metadata = {**self.metadata, "appProperties": revised_copy.value["request"]["body"]["appProperties"]}
            with self.assertRaises(DocsFailure):
                self.edit(packet=packet, copy_intent=revised_copy, copy_approval=self.approve(revised_copy), copy_metadata=metadata)


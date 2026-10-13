"""LEASE REQUIRED: one authored local Docs contract journey with durable intent witnesses."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_playbook.common import canonical, sha256
from contract_playbook.connectors.docs_double import ReadDouble, document_response
from contract_playbook.connectors.google_docs import (
    DRIVE_FILE_SCOPE, DocsFailure, LocalGrant, OperatorScope, decode_document, prepare_copy, prepare_edit,
    read_local, reconcile_copy, reconcile_edit, validate_approval, validate_edit_preconditions,
)
from contract_playbook.proposal_check import check_proposal
from contract_playbook.providers.gateway import GatewayConfig
from contract_playbook.upgrade.service import run_u1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "work") or out == ROOT / "work":
        raise SystemExit("Use a fresh child directory inside work; never replace old receipts.")
    out.mkdir(parents=True)
    started = time.monotonic()
    records, negative_controls = [], []
    db = sqlite3.connect(out / "intents.sqlite3")
    db.execute("CREATE TABLE intents (digest TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, "
               "body BLOB NOT NULL, approval BLOB, attempts INTEGER NOT NULL DEFAULT 0)")
    db.commit()
    manifest_raw = (ROOT / "UPGRADE_MANIFEST_U2A_1_0.json").read_bytes()
    source_manifest = json.loads(manifest_raw)

    def record(event):
        records.append(event)
        with (out / "events.jsonl").open("ab") as stream:
            stream.write(canonical(event) + b"\n")
            stream.flush()

    def preserved_source():
        assert (ROOT / "UPGRADE_MANIFEST_U2A_1_0.json").read_bytes() == manifest_raw
        for item in source_manifest["source_entries"]:
            raw = (ROOT / item["path"]).read_bytes()
            assert sha256(raw) == item["sha256"] and len(raw) == item["bytes"], item["path"]
        assert sha256((ROOT / "evaluation/HELDOUT_FREEZE.json").read_bytes()) == source_manifest["original_freeze_sha256"]

    def approve(intent):
        return {"decision": "approve", "intent_sha256": intent.sha256, "account_id": operator.account_id,
                "reviewer_label": "synthetic-operator-contract-control"}

    def persist(intent, approval):
        validate_approval(intent, approval)
        with db:
            db.execute("INSERT INTO intents(digest,kind,state,body,approval) VALUES (?,?,'APPROVED',?,?)",
                       (intent.sha256, intent.value["kind"], intent.encoded, canonical(approval)))
        record({"state": "INTENT_APPROVAL_COMMITTED", "intent_sha256": intent.sha256, "kind": intent.value["kind"]})

    def reserve_once(intent):
        with db:
            count = db.execute("UPDATE intents SET state='DISPATCH_RESERVED', attempts=1 "
                               "WHERE digest=? AND state='APPROVED' AND attempts=0", (intent.sha256,)).rowcount
        assert count == 1, "No blind dispatch retry is permitted."
        record({"state": "DISPATCH_RESERVED", "intent_sha256": intent.sha256})

    def witness(intent):
        # A separate read-only connection proves reservation survives connection boundaries.
        readback = sqlite3.connect((out / "intents.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            row = readback.execute("SELECT state,attempts,body FROM intents WHERE digest=?", (intent.sha256,)).fetchone()
        finally:
            readback.close()
        assert row[0] == "DISPATCH_RESERVED" and row[1] == 1 and row[2] == intent.encoded
        return {"state": row[0], "attempts": row[1], "intent_sha256": intent.sha256}

    def negative(name, operation, expected=None):
        try:
            operation()
        except (DocsFailure, AssertionError) as exc:
            if expected is not None:
                assert str(exc) == expected
            negative_controls.append(name)
            record({"state": "CONTROL_REFUSED", "control": name, "failure_type": type(exc).__name__})
        else:
            raise AssertionError("Negative control unexpectedly succeeded: " + name)

    try:
        preserved_source()
        fixture = ROOT / "fixtures/upgrade/u1-paraphrase"
        packet = run_u1(fixture, ROOT / "fixtures/playbooks/buyer-services-v2.json", out / "local-proposal",
                        GatewayConfig("demo/u1", max_requests=16, max_steps=16, max_seconds=20, request_seconds=5))
        text = (fixture / "agreement.txt").read_text(encoding="utf-8")
        policy = (ROOT / "fixtures/playbooks/buyer-services-v2.json").read_bytes()
        fixture_manifest = (fixture / "manifest.json").read_bytes()
        operator = OperatorScope("fictional_docs_account", "fictional_source_document", "fictional_sandbox_folder",
                                 "fictional_docs_run", "Fictional reviewed contract copy")
        grant = LocalGrant(operator.account_id, frozenset({DRIVE_FILE_SCOPE}))
        source_response = document_response(operator.source_document_id, text, "source_rev_1")
        double = ReadDouble(operator.source_document_id, source_response)
        source = read_local(operator, grant, double)
        copy_intent = prepare_copy(operator, grant, source, packet, policy, fixture_manifest)
        copy_approval = approve(copy_intent)
        negative("wrong_copy_approval", lambda: validate_approval(copy_intent, {**copy_approval, "intent_sha256": "0" * 64}), "APPROVAL_REQUIRED")
        persist(copy_intent, copy_approval)
        reserve_once(copy_intent)
        copy_witness = witness(copy_intent)
        # Authored lost response after one simulated copy. No HTTP call or actual Drive write occurs.
        target_id = "fictional_copied_document"
        metadata = {"id": target_id, "mimeType": "application/vnd.google-apps.document",
                    "parents": [operator.sandbox_folder_id],
                    "appProperties": copy_intent.value["request"]["body"]["appProperties"], "trashed": False}
        simulated_copy_writes = 1
        record({"state": "AUTHORED_COPY_RESPONSE_LOST", "writes": simulated_copy_writes})
        assert reconcile_copy(copy_intent, {"files": []}, target_id)["disposition"] == "RECONCILIATION_REQUIRED"
        assert reconcile_copy(copy_intent, {"files": [metadata, metadata]}, target_id)["disposition"] == "RECONCILIATION_REQUIRED"
        assert reconcile_copy(copy_intent, {"files": [metadata], "incompleteSearch": True}, target_id)["disposition"] == "RECONCILIATION_REQUIRED"
        copy_result = reconcile_copy(copy_intent, {"files": [metadata]}, target_id)
        assert copy_result["disposition"] == "COPY_METADATA_CONFIRMED" and copy_result["automatic_retry"] is False
        negative("repeat_copy_dispatch", lambda: reserve_once(copy_intent))
        target = decode_document(document_response(target_id, text, "copy_rev_1", "t.copy"), operator.account_id, target_id)
        source_now = read_local(operator, grant, double)
        edit_intent = prepare_edit(operator, grant, copy_intent, copy_approval, target_id, metadata, target,
                                   source_now, packet, policy, fixture_manifest)
        edit_approval = approve(edit_intent)
        negative("copy_approval_cannot_approve_edit",
                 lambda: validate_edit_preconditions(edit_intent, copy_approval, target, source_now), "APPROVAL_REQUIRED")
        from dataclasses import replace
        negative("target_revision_drift",
                 lambda: validate_edit_preconditions(edit_intent, edit_approval, replace(target, revision_id="drift"), source_now),
                 "TARGET_REVISION_DRIFT")
        negative("source_revision_drift",
                 lambda: validate_edit_preconditions(edit_intent, edit_approval, target, replace(source_now, revision_id="drift")),
                 "SOURCE_REVISION_DRIFT")
        assert validate_edit_preconditions(edit_intent, edit_approval, target, source_now)["preconditions"] == "passed"
        persist(edit_intent, edit_approval)
        reserve_once(edit_intent)
        edit_witness = witness(edit_intent)
        body = edit_intent.value["request"]["body"]
        assert body["writeControl"] == {"requiredRevisionId": "copy_rev_1"}
        # Separate UTF-16 byte splicing independently exercises the prepared Docs request indices.
        buffer = text.encode("utf-16-le")
        for request in body["requests"]:
            if "deleteContentRange" in request:
                span = request["deleteContentRange"]["range"]
                assert span["tabId"] == "t.copy"
                first, last = 2 * (span["startIndex"] - 1), 2 * (span["endIndex"] - 1)
                buffer = buffer[:first] + buffer[last:]
            else:
                insert = request["insertText"]
                assert insert["location"]["tabId"] == "t.copy"
                first = 2 * (insert["location"]["index"] - 1)
                buffer = buffer[:first] + insert["text"].encode("utf-16-le") + buffer[first:]
        simulated_edit_writes = 1
        record({"state": "AUTHORED_EDIT_RESPONSE_LOST", "writes": simulated_edit_writes})
        post_response = document_response(target_id, buffer.decode("utf-16-le"), "copy_rev_2", "t.copy")
        post = decode_document(post_response, operator.account_id, target_id)
        edit_result = reconcile_edit(edit_intent, post)
        assert edit_result["disposition"] == "POSTIMAGE_VERIFIED" and edit_result["automatic_retry"] is False
        negative("repeat_edit_dispatch", lambda: reserve_once(edit_intent))
        assert reconcile_edit(edit_intent, target)["disposition"] == "PREIMAGE_UNCHANGED_NO_RETRY"
        with db:
            db.execute("UPDATE intents SET state='COPY_CONFIRMED' WHERE digest=?", (copy_intent.sha256,))
            db.execute("UPDATE intents SET state='POSTIMAGE_VERIFIED' WHERE digest=?", (edit_intent.sha256,))
        report = check_proposal(packet, {"agreement": source.text.encode()}, policy, fixture_manifest,
                                reviewed={"agreement": post.text.encode()})
        assert report["reviewed_copy_verified"] is True and report["unrelated_byte_changes"] == 0
        assert source_response == double.response and simulated_copy_writes == simulated_edit_writes == 1
        assert db.execute("SELECT sum(attempts),count(*) FROM intents").fetchone() == (2, 2)
        (out / "copy-intent.json").write_bytes(copy_intent.encoded + b"\n")
        (out / "edit-intent.json").write_bytes(edit_intent.encoded + b"\n")
        (out / "source-document.json").write_bytes(source_response + b"\n")
        (out / "readback-document.json").write_bytes(post_response + b"\n")
        (out / "witnesses.json").write_bytes(canonical({"copy": copy_witness, "edit": edit_witness,
            "copy_reconciliation": copy_result, "edit_reconciliation": edit_result, "independent_copy": report}) + b"\n")
        preserved_source()
        assert time.monotonic() - started < 30
        result = {"status": "passed", "mode": "local-double", "candidate": "U2-A-1.0",
                  "unique_semantic_tasks": 1, "negative_controls": len(negative_controls),
                  "simulated_copy_writes": simulated_copy_writes, "simulated_edit_writes": simulated_edit_writes,
                  "remote_calls": 0, "credential_reads": 0, "actual_human_review": False,
                  "elapsed_seconds": time.monotonic() - started, "ram_peak_bytes": None,
                  "legal_correctness": "unproven"}
    except BaseException as exc:
        result = {"status": "failed", "mode": "local-double", "failure_type": type(exc).__name__,
                  "remote_calls": 0, "elapsed_seconds": time.monotonic() - started}
        (out / "summary.json").write_bytes(canonical(result) + b"\n")
        raise
    finally:
        db.close()
    (out / "summary.json").write_bytes(canonical(result) + b"\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


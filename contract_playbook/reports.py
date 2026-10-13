"""Inspectable inert artifacts; originals and unrelated document bytes stay unchanged."""
from __future__ import annotations

import difflib
import html

from .bundle import as_bundle
from .common import canonical, write_owned
from .patches import apply_patches


def render(store, document):
    bundle = as_bundle(document)
    packet = store.packet()
    write_owned(store.directory / "review.json", canonical(packet) + b"\n")
    write_owned(store.directory / "usage.json", canonical(store.usage()) + b"\n")
    trace = b"".join(canonical(event) + b"\n" for event in store.events())
    write_owned(store.directory / "trace.jsonl", trace)
    lines = ["# Fictional contract review", "",
             f"Proposal status: **{packet['domain_status']}**.",
             f"Provider: {packet['provider_kind']}; live model route: {str(packet['live_model']).lower()}.",
             "These artifacts demonstrate workflow behavior, not legal validation or model quality.",
             "This proposal remains immutable. A separate receipt records a later review decision.",
             "", f"Proposal digest: {packet['proposal_sha256']}", ""]
    if "execution_mode" in packet:
        lines.extend([f"Execution mode: **{packet['execution_mode']}**. No live-model quality is established.", ""])
    for finding in packet["findings"]:
        lines.extend([f"## {finding['rule_id']}: {finding['disposition']}", "",
                      html.escape(finding["reason"]), "",
                      "Policy: " + html.escape(finding["policy_citation"]["quote"]), ""])
        for citation in finding["evidence"]:
            source = bundle.by_id[citation["document_id"]]
            line_number = source.text.count("\n", 0, citation["start"]) + 1
            lines.extend([f"Source: {source.document_id}, line {line_number}, character range "
                          f"[{citation['start']}, {citation['end']}); SHA-256 {source.version}.",
                          "", "    " + html.escape(citation["quote"]), ""])
        if "coverage_receipt" in finding:
            lines.extend(["Coverage receipt: " + finding["coverage_receipt"]["receipt_sha256"],
                          "Complete supplied-document coverage does not establish jurisdiction-wide absence.", ""])
        if finding["patch"]:
            patch = finding["patch"]
            lines.extend(["Proposed old text: " + html.escape(patch["expected_text"]), "",
                          "Proposed replacement: " + html.escape(patch["replacement"]), ""])
    lines.extend(["Input files are unchanged. Files in preview/ are unapproved proposals.",
                  "Approve/reject all proposals together using the exact digest.", ""])
    write_owned(store.directory / "review.md", "\n".join(lines).encode("utf-8"))
    diffs = []
    for source in bundle.documents:
        patches = [p for p in packet["patches"] if p["document_id"] == source.document_id]
        preview = apply_patches(source.raw, patches)
        write_owned(store.directory / "preview" / f"{source.document_id}.txt", preview)
        diffs.append("".join(difflib.unified_diff(
            source.text.splitlines(keepends=True), preview.decode("utf-8").splitlines(keepends=True),
            fromfile=f"original/{source.document_id}.txt",
            tofile=f"unapproved-preview/{source.document_id}.txt")))
    write_owned(store.directory / "proposed.patch", "".join(diffs).encode("utf-8"))


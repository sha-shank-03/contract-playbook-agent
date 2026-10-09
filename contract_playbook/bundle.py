"""Bounded three-document input and explicit literal links; no legal precedence inference."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .common import ReviewError, bounded_bytes, exact_keys, parse_json, scoped_file, sha256
from .ingest import Document, index_blocks

REFERENCE = re.compile(r"(?:Attachment (?P<document>A[0-9]+), )?Section (?P<section>[0-9]+)")
REPLACEMENT = re.compile(r"Amendment (?P<actor>A[12]) replaces Section (?P<section>[0-9]+)(?: of Amendment (?P<target>A[12]))?\.")


@dataclass(frozen=True)
class Bundle:
    root: Path
    documents: tuple[Document, ...]
    manifest_path: Path
    manifest_raw: bytes

    @property
    def base(self):
        return self.documents[0]

    @property
    def by_id(self):
        return {document.document_id: document for document in self.documents}


def load_bundle(case_dir: Path) -> Bundle:
    root = case_dir.resolve()
    manifest_path = scoped_file(root, "manifest.json")
    raw_manifest = bounded_bytes(manifest_path, 4096)
    manifest = parse_json(raw_manifest)
    exact_keys(manifest, {"schema_version", "fictional", "documents"})
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["fictional"] is not True:
        raise ReviewError("Only schema-1 fictional bundles are supported.")
    entries = manifest["documents"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
        raise ReviewError("Supply one base document and at most two amendments.")
    documents = []
    paths = set()
    for index, entry in enumerate(entries):
        exact_keys(entry, {"id", "file", "type"})
        expected_type = "base" if index == 0 else "amendment"
        if entry["type"] != expected_type or entry["id"] not in ({"agreement"} if index == 0 else {"A1", "A2"}):
            raise ReviewError("Unsupported document ID/type/order.")
        if any(document.document_id == entry["id"] for document in documents):
            raise ReviewError("Duplicate document ID.")
        path = scoped_file(root, entry["file"])
        if path in paths:
            raise ReviewError("Duplicate document path.")
        paths.add(path)
        raw = bounded_bytes(path, 64 * 1024)
        if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
            raise ReviewError("BOM and NUL characters are unsupported.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewError("Contract must be strict UTF-8.") from exc
        blocks = index_blocks(text, entry["id"])
        documents.append(Document(entry["id"], entry["file"], path, raw, text,
                                  sha256(raw), blocks, manifest_path, raw_manifest))
    if sum(len(document.raw) for document in documents) > 64 * 1024 or sum(len(document.blocks) for document in documents) > 48:
        raise ReviewError("Bundle exceeds its total byte/block limit.")
    return Bundle(root, tuple(documents), manifest_path, raw_manifest)


def as_bundle(document: Document | Bundle) -> Bundle:
    if isinstance(document, Bundle):
        return document
    return Bundle(document.path.parent, (document,), document.manifest_path or document.path,
                  document.manifest_raw)


def section_block(bundle: Bundle, document_id: str, section: str):
    document = bundle.by_id.get(document_id)
    if document is None:
        return None
    return next((block for block in document.blocks
                 if block["block_id"] == f"{document_id}.section-{section}"), None)


def source_span(document: Document, start: int, end: int):
    block = next(block for block in document.blocks if block["start"] <= start < end <= block["end"])
    return {"document_id": document.document_id, "document_sha256": document.version,
            "block_id": block["block_id"], "start": start, "end": end,
            "quote": document.text[start:end]}


def replacement_edges(bundle: Bundle):
    edges = []
    for document in bundle.documents[1:]:
        for match in REPLACEMENT.finditer(document.text):
            if match["actor"] != document.document_id:
                raise ReviewError("An amendment replacement actor must match its manifest ID.")
            source = (match["target"] or "agreement", match["section"])
            target = (document.document_id, match["section"])
            edges.append({"source": list(source), "target": list(target),
                          "evidence": source_span(document, match.start(), match.end()),
                          "valid": section_block(bundle, *source) is not None
                          and section_block(bundle, *target) is not None})
    return edges


def effective_section(bundle: Bundle, document_id: str, section: str):
    edges = replacement_edges(bundle)
    path = []
    current = (document_id, section)
    visited = set()
    for _ in range(4):
        if current in visited:
            return {"status": "unknown", "reason": "Replacement cycle.", "edges": path}
        visited.add(current)
        if section_block(bundle, *current) is None:
            return {"status": "unknown", "reason": "Referenced document/section is absent.", "edges": path}
        candidates = [edge for edge in edges if tuple(edge["source"]) == current]
        if len(candidates) > 1:
            return {"status": "conflict", "reason": "No explicit precedence between competing replacements.",
                    "edges": path + candidates}
        if not candidates:
            return {"status": "resolved", "block_id": section_block(bundle, *current)["block_id"],
                    "document_id": current[0], "edges": path}
        edge = candidates[0]
        path.append(edge)
        if not edge["valid"]:
            return {"status": "unknown", "reason": "Replacement target is unavailable.", "edges": path}
        current = tuple(edge["target"])
    return {"status": "unknown", "reason": "Replacement depth exceeds three.", "edges": path}


def block_references(block):
    text = block["text"]
    heading_end = text.find("\n") + 1 if text.startswith("Section ") else 0
    replacements = list(REPLACEMENT.finditer(text))
    return [match for match in REFERENCE.finditer(text)
            if match.start() >= heading_end and not any(
                edge.start() <= match.start() < match.end() <= edge.end() for edge in replacements)]


def reference_inventory(bundle: Bundle):
    references = []
    for document in bundle.documents:
        for block in document.blocks:
            for match in block_references(block):
                literal = match.group()
                references.append({"source_document_id": document.document_id,
                                   "source_block_id": block["block_id"], "reference": literal})
    return references


"""Lossless, bounded M1 input and section indexing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .common import ReviewError, bounded_bytes, exact_keys, parse_json, scoped_file, sha256


@dataclass(frozen=True)
class Document:
    document_id: str
    filename: str
    path: Path
    raw: bytes
    text: str
    version: str
    blocks: tuple[dict, ...]
    manifest_path: Path | None = None
    manifest_raw: bytes = b""


def index_blocks(text: str, document_id: str = "agreement") -> tuple[dict, ...]:
    headings = list(re.finditer(r"(?m)^Section ([0-9]+) - ([^\r\n]+)\r?$", text))
    if not headings:
        raise ReviewError("M1 requires numbered Section N - Title headings.")
    ids = [match.group(1) for match in headings]
    if len(set(ids)) != len(ids):
        raise ReviewError("Duplicate section identifiers are ambiguous.")
    starts = [(0, "preamble", "Preamble")] if headings[0].start() else []
    starts.extend((match.start(), match.group(1), match.group(2)) for match in headings)
    blocks = []
    for index, (start, section, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        block_text = text[start:end]
        if len(block_text) > 4096 or len(block_text.encode("utf-8")) > 8192:
            raise ReviewError("M1 section exceeds its block limit; no text was truncated.")
        blocks.append({"block_id": f"{document_id}.section-{section}", "title": title,
                       "start": start, "end": end, "text": block_text})
    if len(blocks) > 48:
        raise ReviewError("Too many source blocks.")
    return tuple(blocks)


def load_case(case_dir: Path) -> Document:
    root = case_dir.resolve()
    manifest_path = scoped_file(root, "manifest.json")
    manifest_raw = bounded_bytes(manifest_path, 4096)
    manifest = parse_json(manifest_raw)
    exact_keys(manifest, {"schema_version", "fictional", "documents"})
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or manifest["fictional"] is not True:
        raise ReviewError("Only schema-1 fictional case bundles are supported.")
    documents = manifest["documents"]
    if not isinstance(documents, list) or len(documents) != 1:
        raise ReviewError("M1 supports exactly one base agreement; amendments are deferred.")
    entry = documents[0]
    exact_keys(entry, {"id", "file", "type"})
    if entry["id"] != "agreement" or entry["type"] != "base":
        raise ReviewError("M1 requires the agreement base document.")
    path = scoped_file(root, entry["file"])
    raw = bounded_bytes(path, 64 * 1024)
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise ReviewError("BOM and NUL characters are unsupported.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("Contract must be strict UTF-8.") from exc
    return Document("agreement", entry["file"], path, raw, text, sha256(raw),
                    index_blocks(text), manifest_path, manifest_raw)


def document_metadata(document: Document) -> dict:
    return {"document_id": document.document_id, "filename": document.filename,
            "document_sha256": document.version, "byte_length": len(document.raw),
            "blocks": [{key: block[key] for key in ("block_id", "title", "start", "end")}
                       for block in document.blocks]}


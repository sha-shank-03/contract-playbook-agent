"""Externally enforced citations and byte-preserving replacement patches."""
from __future__ import annotations

from .common import ReviewError, exact_keys, integer, string
from .ingest import Document

SPAN_KEYS = {"document_id", "document_sha256", "block_id", "start", "end", "quote"}
PATCH_KEYS = {"document_id", "document_sha256", "start", "end",
              "expected_text", "replacement"}


def validate_span(span: dict, document: Document, read_blocks: set[str]):
    exact_keys(span, SPAN_KEYS)
    string(span["block_id"], "citation block ID", 80)
    start, end = integer(span["start"], "span start"), integer(span["end"], "span end")
    if (span["document_id"] != document.document_id
            or span["document_sha256"] != document.version
            or not 0 <= start < end <= len(document.text)):
        raise ReviewError("Citation version or range mismatch.", 3)
    if span["block_id"] not in read_blocks:
        raise ReviewError("Citation block must be fully read.", 3)
    block = next((b for b in document.blocks if b["block_id"] == span["block_id"]), None)
    if block is None or not block["start"] <= start < end <= block["end"]:
        raise ReviewError("Citation escapes the read block.", 3)
    string(span["quote"], "source quote", 4096)
    if document.text[start:end] != span["quote"]:
        raise ReviewError("Citation quote does not match source bytes.", 3)


def validate_patch(patch: dict, document: Document, evidence: list[dict],
                   other_patches: list[dict], allowed_insertions: dict[int, set[str]] | None = None):
    exact_keys(patch, PATCH_KEYS)
    start = integer(patch["start"], "patch start")
    end = integer(patch["end"], "patch end")
    if (patch["document_id"] != document.document_id
            or patch["document_sha256"] != document.version
            or not 0 <= start <= end <= len(document.text)):
        raise ReviewError("Patch source version or range mismatch.", 3)
    string(patch["expected_text"], "expected patch text", 800, nonempty=start != end)
    string(patch["replacement"], "replacement", 1000)
    if end - start > 800 or document.text[start:end] != patch["expected_text"]:
        raise ReviewError("Patch expected text or size mismatch.", 3)
    if patch["replacement"] == patch["expected_text"]:
        raise ReviewError("A patch must make a change.", 3)
    insertion = start == end
    if insertion and (patch["expected_text"] != "" or patch["replacement"] not in (allowed_insertions or {}).get(start, set())):
        raise ReviewError("Insertion must match approved wording at a read block boundary.", 3)
    if not insertion and not any(span["document_id"] == document.document_id
            and span["document_sha256"] == document.version
            and span["start"] <= start < end <= span["end"] for span in evidence):
        raise ReviewError("Patch must lie inside its cited source span.", 3)
    if any((start == end == previous["start"] == previous["end"] or
            start < previous["end"] and previous["start"] < end)
           for previous in other_patches):
        raise ReviewError("Patches overlap.", 3)
    if len(other_patches) >= 8 or sum(p["end"] - p["start"] + len(p["replacement"])
                                    for p in other_patches + [patch]) > 4000:
        raise ReviewError("Patch budget exhausted.", 3)


def apply_patches(raw: bytes, patches: list[dict]) -> bytes:
    """Concatenate untouched raw slices; do not normalize the document."""
    text = raw.decode("utf-8")
    pieces = []
    cursor = 0
    for patch in sorted(patches, key=lambda value: value["start"]):
        start, end = patch["start"], patch["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
            raise ReviewError("Invalid materialization span.", 3)
        byte_start = len(text[:start].encode("utf-8"))
        byte_end = len(text[:end].encode("utf-8"))
        if byte_start < cursor or text[start:end] != patch["expected_text"]:
            raise ReviewError("Materialization found stale or overlapping patches.", 3)
        pieces.extend((raw[cursor:byte_start], patch["replacement"].encode("utf-8")))
        cursor = byte_end
    pieces.append(raw[cursor:])
    return b"".join(pieces)


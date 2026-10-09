"""Small, explicit data and filesystem contracts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class ReviewError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes, limit: int = 96 * 1024):
    if len(raw) > limit:
        raise ReviewError("JSON exceeds its byte limit.")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ReviewError(f"Non-finite JSON number: {value}")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ReviewError(f"Invalid UTF-8 JSON: {exc}") from exc


def exact_keys(value, required: set[str], optional: set[str] | None = None):
    if not isinstance(value, dict):
        raise ReviewError("Expected a JSON object.", 3)
    keys = set(value)
    if not required <= keys or keys - required - (optional or set()):
        raise ReviewError("Unexpected or missing object properties.", 3)


def string(value, name: str, maximum: int = 1000, nonempty: bool = True):
    if not isinstance(value, str) or len(value) > maximum or (nonempty and not value):
        raise ReviewError(f"Invalid {name}.", 3)
    return value


def integer(value, name: str):
    if type(value) is not int:
        raise ReviewError(f"{name} must be an integer.", 3)
    return value


def bounded_bytes(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ReviewError("Input must be a regular, unlinked file.")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ReviewError("Input exceeds its byte limit.")
    return raw


def scoped_file(root: Path, relative: str) -> Path:
    string(relative, "relative input filename", 120)
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise ReviewError("Input path must stay inside the case directory.")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewError("Linked input paths are unsupported.")
    resolved = current.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ReviewError("Input path escapes the case directory.")
    return resolved


def write_owned(path: Path, raw: bytes):
    """Materialize a generated file without overwriting different content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ReviewError("Linked output paths are unsupported.", 3)
    if path.exists():
        if path.is_file() and path.read_bytes() == raw:
            return
        raise ReviewError(f"Generated target already has different content: {path.name}", 3)
    temp = path.with_name(path.name + ".part")
    if temp.exists() or temp.is_symlink():
        if temp.is_symlink() or not temp.is_file() or temp.read_bytes() != raw:
            raise ReviewError("Unfinished output differs from the committed bytes; inspect this run.", 3)
        os.replace(temp, path)
        return
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except FileExistsError as exc:
        raise ReviewError("Unfinished output exists; inspect the run before retrying.", 3) from exc


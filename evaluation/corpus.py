"""Frozen evaluator-only inputs and labels. This module never executes the actor."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

FREEZE_VERSION = "authored-heldout-m2"
FREEZE_FILE_SHA = "8ae16854230fd754760c38a205f698857fdbdb3f75e0da92ee16cd9daac3b666"
FREEZE_ENTRIES_SHA = "efd5dd3d38583f0aec2d41bf9c209c0c48d37ef73e55679c1ee647b06035cdaf"


class VerificationError(Exception):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise VerificationError("Duplicate artifact JSON key.")
        result[key] = value
    return result


def decode(raw, limit=128*1024):
    if len(raw) > limit:
        raise VerificationError("Artifact exceeds independent byte limit.")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(VerificationError("Non-finite JSON.")))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise VerificationError("Invalid artifact JSON.") from exc


def scoped(root, relative):
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise VerificationError("Evaluator file escapes its declared root.")
    path = root / candidate
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.resolve().is_relative_to(root.resolve()):
        raise VerificationError("Linked/out-of-root evaluator input.")
    return path


@dataclass
class CaseEvidence:
    case_id: str
    sources: dict
    manifest_raw: bytes
    policy_raw: bytes
    labels: dict
    gold_bytes: dict

    @property
    def policy(self):
        return decode(self.policy_raw)


def validate_freeze(root):
    raw = scoped(root, "evaluation/HELDOUT_FREEZE.json").read_bytes()
    if digest(raw) != FREEZE_FILE_SHA:
        raise VerificationError("Accepted held-out freeze file changed.")
    freeze = decode(raw)
    if freeze["manifest_sha256"] != FREEZE_ENTRIES_SHA or digest(canonical(freeze["entries"])) != FREEZE_ENTRIES_SHA:
        raise VerificationError("Accepted freeze entries changed.")
    if len(freeze["entries"]) != 115 or freeze["cases"] != 30 or freeze["scored"] is not False:
        raise VerificationError("Unexpected accepted corpus identity.")
    paths = set()
    for item in freeze["entries"]:
        if item["path"] in paths:
            raise VerificationError("Duplicate freeze path.")
        paths.add(item["path"])
        value = scoped(root, item["path"]).read_bytes()
        if digest(value) != item["sha256"] or len(value) != item["bytes"]:
            raise VerificationError("Frozen input/gold/rubric changed: " + item["path"])
    expected = {"evaluation/RUBRIC.md", "evaluation/labels/heldout.json",
                "fixtures/playbooks/buyer-services-v2.json"}
    expected.update(path.relative_to(root).as_posix() for folder in
                    ("fixtures/heldout", "evaluation/labels/heldout")
                    for path in (root / folder).rglob("*") if path.is_file())
    if paths != expected:
        raise VerificationError("Unlisted/missing frozen file.")
    return {"freeze_version": FREEZE_VERSION, "freeze_file_sha256": FREEZE_FILE_SHA,
            "freeze_entries_sha256": FREEZE_ENTRIES_SHA, "frozen_files": len(paths)}


def load_labels(root):
    return decode(scoped(root, "evaluation/labels/heldout.json").read_bytes())["cases"]


def load_case_evidence(root, case_id, label):
    directory = scoped(root, label["fixture"])
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = decode(manifest_raw)
    sources = {entry["id"]: scoped(directory, entry["file"]).read_bytes()
               for entry in manifest["documents"]}
    gold = {}
    for key, entry in label["reviewed_files"].items():
        raw = scoped(root, entry["path"]).read_bytes()
        if digest(raw) != entry["sha256"]:
            raise VerificationError("Golden final bytes changed.")
        gold[key] = raw
    return CaseEvidence(case_id, sources, manifest_raw, scoped(root, label["playbook"]).read_bytes(), label, gold)

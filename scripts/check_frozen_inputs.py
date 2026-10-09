"""Static corpus integrity only. No imports, executions, predictions or outcome scores from the actor."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    freeze_raw = (ROOT / "evaluation/HELDOUT_FREEZE.json").read_bytes()
    freeze = json.loads(freeze_raw)
    entries = freeze["entries"]
    assert freeze["cases"] == 30 and freeze["scored"] is False
    manifest_sha = sha(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())
    assert manifest_sha == freeze["manifest_sha256"]
    for item in entries:
        path = (ROOT / item["path"]).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        raw = path.read_bytes()
        assert sha(raw) == item["sha256"] and len(raw) == item["bytes"], item["path"]
    expected_paths = {"evaluation/RUBRIC.md", "evaluation/labels/heldout.json",
                      "fixtures/playbooks/buyer-services-v2.json"}
    expected_paths.update(p.relative_to(ROOT).as_posix() for parent in
                          ("fixtures/heldout", "evaluation/labels/heldout")
                          for p in (ROOT / parent).rglob("*") if p.is_file())
    assert {e["path"] for e in entries} == expected_paths
    audited_cases, audited_quotes, audited_patches = 0, 0, 0
    for filename, expected_count in (("development.json", 12), ("heldout.json", 30)):
        labels = json.loads((ROOT / "evaluation/labels" / filename).read_bytes())["cases"]
        assert len(labels) == expected_count
        for name, case in labels.items():
            directory = ROOT / case["fixture"]
            manifest = json.loads((directory / "manifest.json").read_bytes())
            documents = {d["id"]: (directory / d["file"]).read_bytes() for d in manifest["documents"]}
            text = {key: raw.decode() for key, raw in documents.items()}
            edits = {key: [] for key in documents}
            for rule in case["rules"].values():
                for span in rule["evidence_required"]:
                    key = span["document_id"]
                    assert span["document_sha256"] == sha(documents[key])
                    assert text[key][span["start"]:span["end"]] == span["quote"], name
                    audited_quotes += 1
                patch = rule["patch"]
                if patch:
                    key = patch["document_id"]
                    assert patch["document_sha256"] == sha(documents[key])
                    assert 0 <= patch["start"] <= patch["end"] <= len(text[key])
                    assert text[key][patch["start"]:patch["end"]] == patch["expected_text"]
                    edits[key].append(patch)
                    audited_patches += 1
            for key, raw in documents.items():
                cursor, chunks = 0, []
                for patch in sorted(edits[key], key=lambda p: p["start"]):
                    assert cursor <= patch["start"], name
                    chunks.extend((text[key][cursor:patch["start"]], patch["replacement"]))
                    cursor = patch["end"]
                chunks.append(text[key][cursor:])
                gold = case["reviewed_files"][key]
                assert sha((ROOT / gold["path"]).read_bytes()) == gold["sha256"]
                assert "".join(chunks).encode() == (ROOT / gold["path"]).read_bytes(), name
                for interval in case["protected_intervals"][key]:
                    assert sha(text[key][interval["start"]:interval["end"]].encode()) == interval["sha256"]
            audited_cases += 1
    originals = {"direct-review": "b915cb97e68310fdbfc5a280f50c8d787d1b3b9e4310f8b9c56e55dd9dcfa887",
                 "compliant-review": "936d921ac5223ddd9b035c966d42611249798ef84283e0da8a12de7a8673d521"}
    for name, version in originals.items():
        assert sha((ROOT / "fixtures/dev" / name / "agreement.txt").read_bytes()) == version
    print(json.dumps({"static_integrity": "passed", "authored_cases_audited": audited_cases,
                      "authored_required_quotes_audited": audited_quotes,
                      "authored_patch_ranges_audited": audited_patches,
                      "frozen_files": len(entries), "manifest_sha256": manifest_sha,
                      "freeze_file_sha256": sha(freeze_raw), "actor_calls": 0,
                      "heldout_predictions": 0, "outcome_scores": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

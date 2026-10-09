"""Static source/data hygiene only. No actor, transport, recovery, predictions or outcome scoring."""
from pathlib import Path
import ast
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.corpus import VerificationError, canonical, decode, digest, validate_freeze

PINS={"actions/checkout":"9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
      "actions/setup-python":"5fda3b95a4ea91299a34e894583c3862153e4b97"}
SKIP_DIRS={".git","work","__pycache__",".venv","node_modules",".pytest_cache"}
LOCAL_ONLY={"AGENTS.md"}
ALLOWED_SUFFIXES={".py",".md",".txt",".json",".yml",".yaml"}
SPECIAL={"LICENSE","DATA_LICENSE",".gitignore",".gitattributes"}


def public_files(root):
    files=[]
    for path in sorted(root.rglob("*")):
        relative=path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts) or relative.as_posix() in LOCAL_ONLY:
            continue
        if path.is_symlink(): raise VerificationError("Linked shipped file/directory: "+relative.as_posix())
        if path.is_file(): files.append(path)
    return files


def check(root=ROOT):
    freeze=validate_freeze(root)
    files=public_files(root)
    entries=[]
    python_files=json_files=0
    local_modules={"contract_playbook","evaluation","acceptance_m2","release_acceptance"}
    private_path=re.compile(r"(?:[A-Za-z]:[/\\]Users[/\\]|"+"/"+"home/|"+"/"+"Users/"+r"|[/\\]coordination[/\\])")
    token=re.compile(r"(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    for path in files:
        relative=path.relative_to(root).as_posix()
        if path.suffix not in ALLOWED_SUFFIXES and path.name not in SPECIAL:
            raise VerificationError("Unexpected shipped file type: "+relative)
        raw=path.read_bytes()
        try: text=raw.decode("utf-8")
        except UnicodeDecodeError as exc: raise VerificationError("Non-text shipped file: "+relative) from exc
        if private_path.search(text): raise VerificationError("Absolute personal/private path in "+relative)
        if token.search(text): raise VerificationError("Recognizable credential pattern in "+relative)
        if b"\x00" in raw: raise VerificationError("NUL byte in "+relative)
        # Fixture CRLF/Unicode are intentionally preserved. Authored code/docs have no trailing spaces.
        if path.suffix in (".py",".md",".yml",".yaml") and any(line.rstrip()!=line for line in text.splitlines()):
            raise VerificationError("Trailing whitespace in "+relative)
        if path.suffix==".json":
            decode(raw,2*1024*1024)
            json_files+=1
        if path.suffix==".py":
            tree=ast.parse(text,filename=relative)
            python_files+=1
            for node in ast.walk(tree):
                imported=([a.name.split(".")[0] for a in node.names] if isinstance(node,ast.Import) else
                          [node.module.split(".")[0]] if isinstance(node,ast.ImportFrom) and node.level==0 and node.module else [])
                if any(name not in sys.stdlib_module_names and name not in local_modules for name in imported):
                    raise VerificationError("Non-stdlib/unlisted import in "+relative)
                if relative.startswith("contract_playbook/") and "evaluation" in imported:
                    raise VerificationError("Actor imports evaluator/labels.")
                if relative in ("evaluation/verifier.py","evaluation/metrics.py","evaluation/corpus.py") and "contract_playbook" in imported:
                    raise VerificationError("Independent oracle imports production code.")
            if relative.startswith("contract_playbook/") and ("labels/" in text or "load_labels" in text or "HELDOUT_FREEZE" in text):
                raise VerificationError("Actor source refers to evaluator-only gold data.")
        entries.append({"path":relative,"bytes":len(raw),"sha256":digest(raw)})
    for name in ("LICENSE","DATA_LICENSE","THIRD_PARTY_NOTICES.md","README.md","docs/EVALUATION.md","docs/VERSIONS.md","docs/SOURCES.md"):
        if not (root/name).is_file(): raise VerificationError("Missing release document: "+name)
    workflow=(root/".github/workflows/ci.yml").read_text(encoding="utf-8")
    pins=re.findall(r"uses: ([^@\s]+)@([^\s#]+)",workflow)
    if len(pins)!=2 or dict(pins)!=PINS or any(not re.fullmatch(r"[0-9a-f]{40}",sha) for _,sha in pins):
        raise VerificationError("Workflow actions must match the two reviewed immutable commits.")
    for line in ("  contents: read","      max-parallel: 1","    timeout-minutes: 10",
                 "          persist-credentials: false",'          python-version: "3.11"',
                 "        os: [ubuntu-24.04, windows-2025]",
                 "run: python scripts/check_repository.py",
                 "run: python -m evaluation --suite heldout --provider scripted --baseline keyword --repetitions 3 --out work/ci-evaluation",
                 "run: python scripts/acceptance.py --milestone all --evaluation work/ci-evaluation --out work/ci-acceptance"):
        if line not in workflow: raise VerificationError("Missing declared CI guard/command: "+line)
    if re.search(r"secrets\.|pip install|npm |ollama (?:pull|serve)|permissions: write",workflow):
        raise VerificationError("Unrequested model/dependency/secret/write CI activity.")
    return {"status":"passed","python_files_parsed":python_files,"json_files_parsed":json_files,
            "public_files":len(entries),"public_bytes":sum(e["bytes"] for e in entries),
            "public_tree_sha256":digest(canonical(entries)),"freeze":freeze,
            "ci_validation":"Exact pins, guard/command text and authored indentation; no general YAML parser or hosted execution.",
            "hygiene_scope":"UTF-8, file types, whitespace, explicit private-path and recognizable credential patterns; not a comprehensive secret audit.",
            "actor_calls":0,"heldout_predictions":0,"outcome_scores":0,"hosted_ci_runs":0}


def main():
    try:
        result=check()
    except (VerificationError,OSError,ValueError,SyntaxError) as exc:
        result={"status":"failed","error":str(exc),"actor_calls":0,"outcome_scores":0}
    print(json.dumps(result))
    return 0 if result["status"]=="passed" else 1


if __name__=="__main__":
    raise SystemExit(main())

"""Application/reviewer entry points, separate from provider tool authority."""
from __future__ import annotations

from pathlib import Path

from .agent import investigate
from .baseline import BASELINE_VERSION, KeywordBaseline
from .bundle import load_bundle
from .common import ReviewError, canonical, sha256, write_owned
from .ingest import document_metadata
from .playbook import RULE_IDS, load_playbook
from .provider import ScriptedDecisionProvider
from .providers.ollama import OllamaChatProvider
from .reports import render
from .store import RunStore
from .tools import ToolRegistry

REPOSITORY = Path(__file__).resolve().parent.parent
DEV_CASES = ("direct-review", "compliant-review", "cross-reference", "broken-reference",
             "cycle-reference", "explicit-amendment", "conflicting-amendments",
             "precedence-amendments", "missing-payment", "missing-written-notice",
             "missing-attachment", "source-injection")


def run_case(case_dir: Path, playbook_path: Path, out: Path, *, provider_kind="scripted",
             endpoint=None, model=None, max_calls=48, max_seconds=120,
             resume=False, failpoint=lambda phase: None, transport=None):
    case_root, output = case_dir.resolve(), out.resolve()
    if output.is_relative_to(case_root) or case_root.is_relative_to(output):
        raise ReviewError("Run output and input case directories must be separate.", 3)
    if type(max_calls) is not int or not 1 <= max_calls <= 96 or type(max_seconds) not in (int, float) or not 0 < max_seconds <= 300:
        raise ReviewError("Decision/runtime limits must be within 1..96 calls and 0..300 seconds.", 3)
    bundle = load_bundle(case_root)
    playbook = load_playbook(playbook_path)
    if playbook.path.is_relative_to(output):
        raise ReviewError("Run output must not contain the playbook.", 3)
    flag = output / "CANCEL"
    cancelled = lambda: flag.exists()
    if provider_kind == "scripted":
        if endpoint is not None or model is not None:
            raise ReviewError("Scripted runs do not accept endpoint/model settings.", 3)
        provider = ScriptedDecisionProvider()
    elif provider_kind == "keyword":
        if endpoint is not None or model is not None:
            raise ReviewError("Keyword runs do not accept endpoint/model settings.", 3)
        provider = KeywordBaseline()
    elif provider_kind == "ollama":
        if endpoint is None or model is None:
            raise ReviewError("Ollama requires an explicit loopback endpoint and model.", 3)
        provider = OllamaChatProvider(model=model, endpoint=endpoint, transport=transport, cancel=cancelled)
    else:
        raise ReviewError("Unsupported provider kind.", 3)
    config = {"case_dir": str(case_root), "playbook_path": str(playbook.path),
              "provider_kind": provider_kind, "endpoint": endpoint, "model": model,
              "max_calls": max_calls, "max_seconds": max_seconds}
    key = sha256(canonical({"documents": [document_metadata(d) for d in bundle.documents],
                            "manifest_sha256": sha256(bundle.manifest_raw),
                            "playbook_sha256": playbook.version,
                            "provider": provider_kind, "endpoint": endpoint, "model": model,
                            "max_calls": max_calls, "max_seconds": max_seconds,
                            "protocol": BASELINE_VERSION if provider_kind == "keyword" else "m2-v1"}))
    store = RunStore(output)
    try:
        inputs = {d.document_id: (d.path, d.raw) for d in bundle.documents}
        inputs.update({"playbook": (playbook.path, playbook.raw),
                       "manifest": (bundle.manifest_path, bundle.manifest_raw)})
        active = store.initialize(key, inputs, resume=resume)
        store.set_config(config)
        if resume and flag.exists():
            if flag.is_symlink() or flag.read_bytes() != b"cancel\n":
                raise ReviewError("Unexpected cancellation marker; inspect this run.", 3)
            flag.unlink()
        if active:
            registry = ToolRegistry(bundle, playbook)
            try:
                usage = investigate(registry, provider, store.event, max_calls, max_seconds,
                                    journal=store, cancelled=cancelled, failpoint=failpoint)
            except KeyboardInterrupt:
                store.fail("CANCELLED")
                raise
            except Exception as exc:
                store.fail("BUDGET_EXHAUSTED" if "budget exhausted" in str(exc).lower()
                           else "FAILED")
                raise
            findings = [registry.findings[rule_id] for rule_id in RULE_IDS]
            core = {"schema_version": 2, "fictional": True, "provider_kind": provider.kind,
                    "live_model": provider.kind == "ollama", "model_quality_evaluated": False,
                    "domain_status": registry.domain_status(),
                    "source": document_metadata(bundle.base),
                    "documents": [document_metadata(d) for d in bundle.documents],
                    "coverage": registry.coverage(), "references": list(registry.references.values()),
                    "manifest_sha256": sha256(bundle.manifest_raw),
                    "playbook": {"id": playbook.name, "sha256": playbook.version},
                    "findings": findings, "patches": [f["patch"] for f in findings if f["patch"] is not None]}
            packet = {**core, "proposal_sha256": sha256(canonical(core))}
            store.finish(packet, usage)
            failpoint("after_proposal_commit")
        render(store, bundle)
        return store.packet()
    finally:
        store.close()


def resume_run(run: Path, *, failpoint=lambda phase: None, transport=None):
    if not (run / "run.sqlite3").is_file():
        raise ReviewError("Resume run does not exist.", 3)
    store = RunStore(run)
    try:
        config = store.config()
    finally:
        store.close()
    if config.get("upgrade_protocol") == "gateway-u1-v1":
        from .upgrade.service import resume_u1
        return resume_u1(run, transport=transport, failpoint=failpoint)
    return run_case(Path(config.pop("case_dir")), Path(config.pop("playbook_path")), run,
                    **config, resume=True, failpoint=failpoint, transport=transport)


def cancel_run(run: Path):
    if not (run / "run.sqlite3").is_file():
        raise ReviewError("Cancel run does not exist.", 3)
    store = RunStore(run)
    try:
        if store.state() not in ("INVESTIGATING", "CANCELLED", "FAILED", "BUDGET_EXHAUSTED"):
            raise ReviewError("Only incomplete investigations can be cancelled.", 3)
        write_owned(store.directory / "CANCEL", b"cancel\n")
        return {"cancellation_requested": True, "state": store.state()}
    finally:
        store.close()


def demo(case_name: str, out: Path):
    if case_name not in DEV_CASES:
        raise ReviewError("Unknown development demo case.")
    version = "v1" if case_name in DEV_CASES[:2] else "v2"
    return run_case(REPOSITORY / "fixtures" / "dev" / case_name,
                    REPOSITORY / "fixtures" / "playbooks" / f"buyer-services-{version}.json", out)


def review(run: Path, decision: str, expected: str, reviewer: str, *,
           failpoint=lambda phase: None):
    if not (run / "run.sqlite3").is_file():
        raise ReviewError("Review run does not exist.", 3)
    store = RunStore(run)
    try:
        if (store.db.execute("SELECT 1 FROM config").fetchone()
                and store.config().get("upgrade_protocol") == "gateway-u1-v1"):
            from .upgrade.service import review_store
            return review_store(store, decision, expected, reviewer, failpoint=failpoint)
        return store.review(decision, expected, reviewer, failpoint=failpoint)
    finally:
        store.close()


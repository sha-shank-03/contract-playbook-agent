"""U1 host-owned persistence, source checks and separate reviewer authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from ..bundle import load_bundle
from ..common import ReviewError, bounded_bytes, canonical, parse_json, sha256
from ..ingest import document_metadata
from ..playbook import RULE_IDS, load_playbook
from ..proposal_check import ProposalInvalid, check_proposal, check_receipt
from ..providers.gateway import GatewayChatProvider, GatewayConfig, GatewayFailure, PROMPT, PROTOCOL
from ..reports import render
from ..store import RunStore
from ..tools import ToolRegistry
from .budget import Budget
from .double import FictionalGatewayDouble
from .metrics import safe_event, summary


def code_identity():
    root = Path(__file__).resolve().parents[1]
    return sha256(canonical({p.relative_to(root).as_posix(): sha256(p.read_bytes())
                             for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}))


def _identity(store):
    config = store.config()
    return {"run_id": store.db.execute("SELECT run_key FROM run").fetchone()[0],
            "mode": "local-double", "model": config["gateway"]["model"],
            "code_sha256": config["code_sha256"], "prompt_sha256": sha256(PROMPT.encode("utf-8")),
            "config_sha256": sha256(canonical(config["gateway"])),
            "dataset_sha256": config["dataset_sha256"]}


def operating(store, state, budget=None, **details):
    if budget is None:
        saved = store.load_checkpoint()
        if saved:
            budget = Budget.restore(saved["budget"], GatewayConfig(**store.config()["gateway"]))
    event = safe_event({**_identity(store), "state": state, "committed_state": store.state(),
                       **(budget.public() if budget else {}),
                       **details})
    store.event({"operating": event})


def refresh_metrics(store):
    records = [event["operating"] for event in store.events() if "operating" in event]
    for name, raw in (("operations.jsonl", b"".join(canonical(r) + b"\n" for r in records)),
                      ("metrics.json", canonical(summary(records, current_state=store.state())) + b"\n")):
        target = store.directory / name
        temp = target.with_suffix(target.suffix + ".refresh")
        if any(p.is_symlink() for p in (target, temp, *target.parents)):
            raise ReviewError("Linked operating artifact target.", 3)
        with temp.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)


def investigate_gateway(registry, provider, journal, *, cancel, clock=time.monotonic,
                        failpoint=lambda phase: None, setup_seconds=0):
    phase_started = clock()
    config = provider.config
    saved = journal.load_checkpoint()
    if saved:
        if saved.get("protocol") != PROTOCOL:
            raise GatewayFailure("CHECKPOINT_PROTOCOL_MISMATCH")
        registry.restore(saved["registry"])
    budget = Budget.restore(saved["budget"], config) if saved else Budget()
    base_seconds = budget.seconds_used + setup_seconds
    call_id = saved.get("provider_call_id") if saved else None

    def checkpoint():
        return {"protocol": PROTOCOL, "budget": budget.public(),
                "registry": registry.checkpoint(), "provider_call_id": call_id}

    if not any(e.get("operating", {}).get("state") == "START" for e in journal.events()):
        operating(journal, "START", budget)
    while not registry.submitted:
        budget.seconds_used = base_seconds + clock() - phase_started
        if cancel():
            raise KeyboardInterrupt()
        if budget.seconds_used >= config.max_seconds:
            raise GatewayFailure("BUDGET_EXHAUSTED")
        started = clock()
        prior = budget.seconds_used
        pending = journal.pending_action()
        if pending:
            budget.replays += 1
            if budget.replays > 2:
                raise GatewayFailure("REPLAY_LIMIT")
            action_id, decision = pending
        else:
            prior = budget.reserve(config)
            journal.save_checkpoint(checkpoint())
            failpoint("after_provider_reservation")
            action_id = f"gateway-action-{budget.steps:04d}"
            try:
                decision = provider.next(registry.observation(), {
                    "seconds": config.max_seconds - prior, "attempt": budget.requests,
                    "requests_remaining": config.max_requests - budget.requests,
                    "steps_remaining": config.max_steps - budget.steps})
                budget.settle(prior, clock() - started, provider.last_metadata)
                call_id = provider.last_metadata["provider_call_id"]
                if budget.seconds_used >= config.max_seconds:
                    raise GatewayFailure("BUDGET_EXHAUSTED")
                journal.begin_action(action_id, decision, checkpoint())
                operating(journal, "ACTION", budget, elapsed_seconds=clock() - started,
                          tool=decision["tool"], **{k: v for k, v in provider.last_metadata.items()
                                                   if k != "provider_call_id"})
                failpoint("after_intent_commit")
            except KeyboardInterrupt:
                budget.settle(prior, clock() - started)
                budget.request_in_flight = True
                journal.save_checkpoint(checkpoint())
                operating(journal, "CANCELLED", budget)
                raise
            except GatewayFailure as exc:
                budget.settle(prior, clock() - started)
                budget.request_in_flight = exc.status not in {"HTTP_401", "HTTP_402", "HTTP_429"}
                budget.rejected += 1
                journal.save_checkpoint(checkpoint())
                operating(journal, "FAILED", budget, failure_code=exc.status)
                raise  # Zero automatic transport/protocol retries.
        if cancel():
            journal.save_checkpoint(checkpoint())
            operating(journal, "CANCELLED", budget)
            raise KeyboardInterrupt()
        if budget.tool_attempts >= config.max_steps:
            raise GatewayFailure("TOOL_BUDGET_EXHAUSTED")
        budget.tool_attempts += 1
        journal.save_checkpoint(checkpoint())
        before_tool = registry.checkpoint()
        try:
            result = registry.execute(decision)
        except ReviewError:
            budget.rejected += 1
            budget.seconds_used = prior + clock() - started
            event = {"decision": decision, "result": None, "error": "GUARD_REJECTED",
                     "provider_call_id": call_id}
            registry.history.append(event)
            registry.last_error = "GUARD_REJECTED"
            journal.commit_action(action_id, event, checkpoint())
            operating(journal, "GUARD_REJECTED", budget, tool=decision["tool"])
            raise GatewayFailure("GUARD_REJECTED") from None
        budget.seconds_used = prior + clock() - started
        if cancel() or budget.seconds_used >= config.max_seconds:
            registry.restore(before_tool)
            journal.save_checkpoint(checkpoint())
            if cancel():
                operating(journal, "CANCELLED", budget)
                raise KeyboardInterrupt()
            raise GatewayFailure("BUDGET_EXHAUSTED")
        event = {"decision": decision, "result": result, "error": None, "provider_call_id": call_id}
        registry.history.append(event)
        registry.last_error = None
        journal.commit_action(action_id, event, checkpoint())
        operating(journal, "GUARDED_ACTION", budget, tool=decision["tool"])
        failpoint("after_action_commit")
    budget.seconds_used = base_seconds + clock() - phase_started
    journal.save_checkpoint(checkpoint())
    return budget


def run_u1(case_dir, playbook_path, out, config, *, transport=None, resume=False,
           clock=time.monotonic, failpoint=lambda phase: None):
    run_started = clock()
    case_dir, out = Path(case_dir).resolve(), Path(out).resolve()
    if out.is_relative_to(case_dir) or case_dir.is_relative_to(out):
        raise ReviewError("Inputs and output must be separate.", 3)
    bundle, policy = load_bundle(case_dir), load_playbook(Path(playbook_path))
    if len(bundle.documents) != 1 or policy.path.is_relative_to(out):
        raise ReviewError("U1 requires one fictional base and a separate playbook.", 3)
    cancel_marker = out / "CANCEL"
    cancel = lambda: cancel_marker.exists()
    provider = GatewayChatProvider(config, transport or FictionalGatewayDouble(), cancel, clock)
    dataset_hash = sha256(canonical({"manifest": sha256(bundle.manifest_raw),
                                     "documents": [d.version for d in bundle.documents],
                                     "playbook": policy.version}))
    stored_config = {"upgrade_protocol": PROTOCOL, "case_dir": str(case_dir),
                     "playbook_path": str(policy.path), "gateway": config.public(),
                     "code_sha256": code_identity(), "dataset_sha256": dataset_hash}
    key = sha256(canonical(stored_config))
    store = RunStore(out)
    try:
        inputs = {"agreement": (bundle.base.path, bundle.base.raw),
                  "manifest": (bundle.manifest_path, bundle.manifest_raw), "playbook": (policy.path, policy.raw)}
        active = store.initialize(key, inputs, resume=resume)
        store.set_config(stored_config)
        if resume and cancel_marker.exists():
            if cancel_marker.is_symlink() or cancel_marker.read_bytes() != b"cancel\n":
                raise ReviewError("Unexpected cancellation marker.", 3)
            cancel_marker.unlink()
        if active:
            registry = ToolRegistry(bundle, policy)
            previous = store.load_checkpoint()
            prior_seconds = previous["budget"]["seconds_used"] if previous else 0
            try:
                budget = investigate_gateway(registry, provider, store, cancel=cancel, clock=clock,
                                             failpoint=failpoint, setup_seconds=clock() - run_started)
                findings = [registry.findings[r] for r in RULE_IDS]
                core = {"schema_version": 3, "fictional": True, "provider_kind": "gateway",
                        "execution_mode": "local-double", "live_model": False, "model": config.model,
                        "model_quality_evaluated": False, "upgrade_protocol": PROTOCOL,
                        "domain_status": registry.domain_status(), "source": document_metadata(bundle.base),
                        "documents": [document_metadata(bundle.base)], "coverage": registry.coverage(),
                        "manifest_sha256": sha256(bundle.manifest_raw),
                        "playbook": {"id": policy.name, "sha256": policy.version},
                        "findings": findings, "patches": [f["patch"] for f in findings if f["patch"] is not None]}
                packet = {**core, "proposal_sha256": sha256(canonical(core))}
                check_proposal(packet, {"agreement": bundle.base.raw}, policy.raw, bundle.manifest_raw)
                budget.seconds_used = prior_seconds + clock() - run_started
                if budget.seconds_used >= config.max_seconds:
                    raise GatewayFailure("BUDGET_EXHAUSTED")
                store.finish(packet, {**budget.public(), "execution_mode": "local-double",
                                     "model_calls": 0, "local_double_requests": budget.requests,
                                     "actual_cost_usd": None, "estimated_cost_usd": None})
            except KeyboardInterrupt:
                store.fail("CANCELLED")
                operating(store, "CANCELLED")
                raise
            except (GatewayFailure, ProposalInvalid) as exc:
                store.fail("BUDGET_EXHAUSTED" if "BUDGET" in str(exc) else "FAILED")
                if isinstance(exc, ProposalInvalid):
                    operating(store, "FAILED", failure_code="INDEPENDENT_VERIFIER_REJECTED")
                    raise GatewayFailure("INDEPENDENT_VERIFIER_REJECTED") from None
                operating(store, "FAILED", failure_code=exc.status)
                raise
            except Exception:
                store.fail("FAILED")
                operating(store, "FAILED", failure_code="HOST_FAILURE")
                raise GatewayFailure("HOST_FAILURE") from None
        render(store, bundle)
        verify_store(store)
        if active:
            budget.seconds_used = prior_seconds + clock() - run_started
            saved = store.load_checkpoint()
            saved["budget"] = budget.public()
            store.save_checkpoint(saved)
            if budget.seconds_used >= config.max_seconds:
                store.fail("BUDGET_EXHAUSTED")
                operating(store, "FAILED", budget, failure_code="BUDGET_EXHAUSTED")
                raise GatewayFailure("BUDGET_EXHAUSTED")
            operating(store, "HANDOFF" if store.packet()["domain_status"] == "HANDOFF" else "PROPOSAL_READY", budget)
        return store.packet()
    finally:
        try:
            if (store.db.execute("SELECT 1 FROM config").fetchone()
                    and store.config().get("upgrade_protocol") == PROTOCOL):
                refresh_metrics(store)
        finally:
            store.close()


def demo_u1(out, model, **options):
    root = Path(__file__).resolve().parents[2]
    return run_u1(root / "fixtures/upgrade/u1-paraphrase", root / "fixtures/playbooks/buyer-services-v2.json",
                  out, GatewayConfig(model), **options)


def resume_u1(run, *, transport=None, **options):
    store = RunStore(Path(run))
    try:
        config = store.config()
    finally:
        store.close()
    return run_u1(config["case_dir"], config["playbook_path"], run,
                  GatewayConfig(**config["gateway"]), transport=transport, resume=True, **options)


def _stale_input(store, failure_code):
    if store.state() != "STALE":
        store.fail("STALE")
        operating(store, "STALE", failure_code=failure_code)
    refresh_metrics(store)


def verify_store(store):
    packet = store.packet()
    if canonical(parse_json(bounded_bytes(store.directory / "review.json", 96 * 1024))) != canonical(packet):
        raise ReviewError("Proposal artifact differs from the committed packet.", 3)
    snapshot = {key: (Path(path), version, raw) for key, path, version, raw in
                store.db.execute("SELECT id,path,sha,raw FROM inputs")}
    for path, version, _ in snapshot.values():
        try:
            current = bounded_bytes(path, 64 * 1024)
        except (OSError, ReviewError):
            _stale_input(store, "INPUT_UNAVAILABLE")
            raise ReviewError("Current input is unavailable; upgrade review is stale.", 3) from None
        if sha256(current) != version:
            _stale_input(store, "INPUT_CHANGED")
            raise ReviewError("Current input changed; upgrade review is stale.", 3)
    if store.state() == "STALE":
        raise ReviewError("A stale review requires a new run.", 3)
    previews = {"agreement": bounded_bytes(store.directory / "preview/agreement.txt", 96 * 1024)}
    expected = check_proposal(packet, {"agreement": snapshot["agreement"][2]}, snapshot["playbook"][2],
                              snapshot["manifest"][2], previews=previews)
    reviewed = None
    if store.state() in ("APPROVED", "DRAFT_EXPORTED"):
        row = store.db.execute("SELECT kind,receipt FROM decision").fetchone()
        if not row or row[0] != "approve":
            raise ReviewError("Reviewed copy lacks an approval.", 3)
        receipt = json.loads(row[1])
        check_receipt(receipt, packet, expected)
        copy_path = store.directory / "reviewed/agreement.txt"
        if copy_path.exists() or store.state() == "DRAFT_EXPORTED":
            reviewed = {"agreement": bounded_bytes(copy_path, 96 * 1024)}
            if receipt.get("reviewed_documents") != {"agreement": sha256(reviewed["agreement"])}:
                raise ReviewError("Approval/copy identity mismatch.", 3)
    elif (store.directory / "reviewed").exists():
        raise ReviewError("Unapproved reviewed artifact exists.", 3)
    report = check_proposal(packet, {"agreement": snapshot["agreement"][2]}, snapshot["playbook"][2],
                            snapshot["manifest"][2], previews=previews, reviewed=reviewed)
    report["reviewed_copy_verified"] = report["reviewed_copy_verified"] and store.state() == "DRAFT_EXPORTED"
    report["final_state"] = store.state()
    return report


def review_store(store, decision, expected, reviewer, failpoint=lambda phase: None):
    try:
        verify_store(store)
        receipt = store.review(decision, expected, reviewer, failpoint=failpoint)
        report = verify_store(store)
    except (ReviewError, ProposalInvalid):
        operating(store, "APPROVAL_DENIED")
        refresh_metrics(store)
        raise
    terminal = "APPROVED_COPY_VERIFIED" if decision == "approve" else "REJECTED"
    if not any(e.get("operating", {}).get("state") == terminal for e in store.events()):
        saved = store.load_checkpoint()
        budget = Budget.restore(saved["budget"], GatewayConfig(**store.config()["gateway"]))
        operating(store, "APPROVED_COPY_VERIFIED" if decision == "approve" else "REJECTED",
                  budget, unauthorized_actions=0 if report["mechanical_verification"] == "passed" else None)
    refresh_metrics(store)
    return receipt

# U1 Gateway-envelope slice

This bounded upgrade uses one exposed fictional paraphrase task and an authored in-memory double. It exercises native Gateway function-call envelopes and observation history. It performs no live inference or external document integration, reads no key, and makes no legal-quality claim. The live transport is disabled at the U1 provider boundary. Google Docs, fresh paired baseline evaluation and genuine live inference await later assignments.

The host retains complete source coverage, exact quoted source/policy versions, edit preimages and separate digest-bound review. An independent stdlib-only proposal checker imports no provider, tools or patch implementation. It reconstructs bytes and checks review state. Meaning and alternative valid wording require the manual fixture rubric.

Pure unit command, permitted without an integration lease:

```powershell
py -3.11 -B -m unittest discover -s tests/upgrade/components -p test_*.py
```

The following transport and end-to-end commands ran once against candidate U1-1.0. Its worker receipts remain historical evidence; main requested a state/metrics correction before acceptance. The corrected candidate has not run a native batch:

```powershell
py -3.11 -B -m unittest discover -s tests/upgrade/provider_contract -p test_*.py
py -3.11 -B scripts/upgrade_acceptance.py --stage u1 --out work/upgrade-u1
```

The queued walkthrough is:

```powershell
py -3.11 -m contract_playbook.upgrade demo --model demo/u1 --out work/upgrade-demo
py -3.11 -m contract_playbook.upgrade verify --run work/upgrade-demo
$u1Packet = Get-Content -LiteralPath work/upgrade-demo/review.json -Raw | ConvertFrom-Json
py -3.11 -m contract_playbook.upgrade review --run work/upgrade-demo --decision approve --expected-proposal $u1Packet.proposal_sha256 --reviewer fictional-reviewer
py -3.11 -m contract_playbook.upgrade verify --run work/upgrade-demo
```

`demo/u1` is an explicit synthetic double ID, not a catalog model. Approval is a local reviewer annotation, not authenticated identity. A pending proposal and a handoff are never a completed copy. Repeated approval must return the stored receipt. Cancellation and resume use the upgrade CLI or the existing cancel/resume commands and retain cumulative bounds.

Defaults: 24 total request attempts, 24 decision/tool attempts, 120 active seconds, 20 seconds/request including bounded child cleanup, 96 KiB request/history, 64 KiB response and 16 KiB decoded action. Completion cap is 2,048 tokens/request. Automatic transport/protocol retries are zero; explicit resume is required after failures. An in-flight crash is conservatively reserved and cannot be silently reissued.

`operations.jsonl` and `metrics.json` are refreshable views of committed SQLite metadata. `trace.jsonl` and the proposal contain fictional evidence. Operating metadata excludes provider text, authorization headers, credentials and reasoning. Missing usage/cost/RAM stay null; no price or zero-cost model benchmark is inferred from doubles. Code/prompt/config/data identities and raw protocol acceptance versus host guard rejection are recorded separately.

The original published commit and v1 freeze remain intact. Changed source is identified by the additive U1 manifest and run code identity. No framework, dependency, model weights or extra runtime is introduced.

Candidate U1-1.1 is identified by `UPGRADE_MANIFEST_U1_1_1.json`; the original `UPGRADE_MANIFEST.json` remains the U1-1.0 snapshot. Metrics schema 2 reports `current_disposition` from the committed run state. `failed`, `cancelled`, `stale`, `handoff` and `pending_human_review` describe that current disposition; `historical_failure_events`, `historical_cancellation_events`, `historical_stale_events` and `historical_approval_denial_events` count append-only operating events, including repeated events within one attempt. Successful recovery keeps its historical events and cumulative budget while returning to pending review.

Changed or unavailable inputs detected by verification durably mark a run `STALE`, append a sanitized stale event and refresh current metrics before refusing approval. A stale run requires fresh output even if its input is restored. A wrong proposal digest with unchanged inputs remains a refused attempt against the pending run. The source-preimage guards and separate human approval remain in force. The bounded correction native check is authored in `scripts/upgrade_correction_acceptance.py` and remains unexecuted until a new lease.

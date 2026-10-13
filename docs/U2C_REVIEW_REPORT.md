# Reviewed scripted case study

Two task pairs tied. All four actor slots ended in HANDOFF; verified task completions were zero.
D15 required handoff because of competing amendments. C11's two handoffs were unnecessary under the exposed rubric.
Both strategies used the same unchanged source, full context, model and PairLimits. No tuning followed these outcomes.

| Task | Strategy | Final state | Rubric classification | Authored double calls | Dispositions | Obligation atoms |
|---|---|---|---|---:|---:|---:|
| D15 | adaptive | HANDOFF | required_handoff | 13 | 1/3 | 3/7 |
| D15 | fixed-full-context | HANDOFF | required_handoff | 4 | 1/3 | 3/7 |
| C11 | adaptive | HANDOFF | unnecessary_handoff | 12 | 0/3 | 0/7 |
| C11 | fixed-full-context | HANDOFF | unnecessary_handoff | 4 | 0/3 | 0/7 |

The 33 authored local-double calls are deterministic decision callbacks, with zero live inference calls.
Across four slots, dispositions match 2/12 and obligation atoms match 6/28 exposed labels. Four literal citations pass byte checks.
Mechanical safety checks observed zero unsafe proposal attempts and zero executed unsafe actions within these four slots.
These observations do not establish semantic or legal quality. No document was exported, and no real person approved a review.
Recorded slot latency spans about 0.015–0.031 seconds (p50 0.016, p95 0.031), for local scripted callbacks only.
Tokens, estimated cost, actual cost and cost per completed task remain unknown.

## Failure accounting

The original mocked REQUEST_DEADLINE probe failed before saving its returned raw result.
The corrected wrapper subsequently retained that exact sentinel using real file/SQLite persistence, stopped after one mocked callback,
and left three slots unexecuted. Incomplete safety and cost remain unknown. This diagnostic adds no business tasks.
It is neither a genuine request deadline experiment nor a crash/power-loss proof. Both original and corrected evidence remain attributable.

## Reproduce without replay

From a fresh checkout with Python 3.11, run:

    python -B scripts/u2c_coordinator.py review
    python -B -m unittest discover -s tests/upgrade/u2c_pure -p test_*.py -v
    python -B scripts/check_repository.py

The reviewer command reads shipped JSON, reconstructs hash chains and independently checks the four existing source-bound proposals.
It performs no actor, SQL, model, browser, connector or approval operation. Output must match this generated report.
Pre-grading archives retain returned_ok_ungraded; final journal slots are scored. This is one execution with two snapshots.

## Scope and remaining work

The 36-task catalog is worker-authored, fictional, MIT-licensed and exposed. Shared boilerplate and near-duplicate review mean these are not 36 independent natural samples.
The historical 42-case suite remains separate. D15/C11 are two historical catalog tasks; their four slots are excluded from the remaining 34-task/68-slot plan.
All six families are scheduled across later bounded slices, with at most two task pairs per lease. The first proposed slice is D01/C03.
No remaining task is claimed executed. Actual Google integration, authenticated human review, main-unseen evaluation, live quality and publication remain pending.

## Provenance

Accepted source manifest SHA-256: 12b30cb3641a61f82f0344533fa8c220603a8f8312ee791ead116b4d3babc0ec
Original main review SHA-256: b2b8aa23751a5993868a8b3f98f2868a0dde45689f1eebb67debbc26154ed640
Shipped evidence provenance SHA-256: 24b1163938fa0e836a63d5432826973c0202bf0e66c210f98d0e08d9d66ebb7f

The evidence directory contains unchanged raw JSON and file journals. Only private path values in two coordinator receipts were redacted;
PROVENANCE.json retains original and shipped hashes. SQLite binaries are preserved in main's original artifacts, with read-only witness receipts shipped here.
Main accepted the local accounting contract (31 pure methods, 116 independent checks), not business completion or external/live quality.
No new actor execution produced this report.

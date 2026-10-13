# Full local U2C campaign reconciliation — 13 October 2026

Main completed and independently audited the original remaining campaign through slice 17.
All 68 strategy slots for 34 existing catalog tasks are terminal. Every outcome is HANDOFF:
24 required handoffs and 44 unnecessary handoffs, 34 task-pair ties and zero business completions.
The 560 authored local callbacks are deterministic scripted decisions, not live inference.

| Evidence population | Unique catalog tasks | Actor slots | Authored callbacks | Required / unnecessary handoffs | Pair ties | Business completions |
|---|---:|---:|---:|---:|---:|---:|
| Original remaining campaign, slices 1–17 | 34 | 68 | 560 | 24 / 44 | 34 | 0 |
| Historical D15/C11, retained separately | 2 | 4 | 33 | 2 / 2 | 2 | 0 |

The remaining campaign covers all six declared families with unchanged actors, full context, model,
PairLimits, baseline, playbook, fixtures, labels and rubric. There was no replay or tuning.
Coverage completion proves the bounded local accounting flow; these results establish no semantic or legal quality.
Estimated and actual costs, tokens and cost per completed task remain unknown. Live model calls were zero.
The fixtures are worker-authored, exposed, fictional and share boilerplate; catalog IDs are not independent natural samples.
The historical 42-case suite and mocked failure diagnostics remain separate from both rows above.

## Preserved encoding failure and exact read-only recovery

In slice 09, D18/D22's actor command exited 0 and persisted FINISHED before the default report command exited 1.
Windows CP1252 stdout could not encode D22's preserved Unicode source text. The original failure receipt reports
UnicodeEncodeError and unavailable output counters; this output failure does not erase the completed actor slots.
Main's following UTF-8 invocation exited 0 without modifying campaign bytes or replaying any actor:

    py -3.11 -X utf8 -B scripts/u2c_coordinator.py report --campaign work/upgrade-u2c

For a Python 3.11 executable without the Windows launcher:

    python -X utf8 -B scripts/u2c_coordinator.py report --campaign work/upgrade-u2c

Use report against the existing preserved campaign. A fresh checkout includes compact audit receipts, not the full
359-file raw campaign; this invocation requires those original local artifacts. Do not create a replacement campaign
or run plan/run-slice to recover this output. The default invocation remains frozen and may fail under CP1252.
The documented interpreter flag changes output encoding; source, dataset and campaign identities remain the same.
No new runtime entry point or frozen code change is required.

The default report error, native command/batch failure and successful recovery receipt are retained in
[evaluation/upgrade/u2c_full_campaign_evidence](../evaluation/upgrade/u2c_full_campaign_evidence/PROVENANCE.json).
Only private path values were redacted in copied coordinator receipts. Original and shipped hashes are recorded.
These are actual main receipts and a static reconciliation, not newly executed or published evaluation evidence.

## Reconciliation and provenance

[RECONCILIATION.json](../evaluation/upgrade/u2c_full_campaign_evidence/RECONCILIATION.json) compares read-only
arithmetic from the 17 original slice reports with main's final aggregates. The final slice audit records 553
checks and six corruption controls; this is that audit's count, not a sum of independent campaign assertions.
Earlier U2C documents retain their pre-campaign dates and outcomes. This addendum records the later completed campaign.

Frozen source manifest SHA-256:
336548e0c93f10e070c23b61e6e0586425554d2e68e56ce648ff488044bdc8f2

Original campaign SHA-256:
f396547aabb1f21d8002abb5665b69307de4b1390a50866425f8f7437ae87cce

No frozen source/manifest, raw outcome, journal, existing report, fixture or label changed in this follow-up.
The new material consists of this document, copied redacted audit receipts, reconciliation metadata and pure
in-memory Unicode-output checks:

    py -3.11 -X utf8 -B -m unittest discover -s tests/upgrade/utf8_pure -p test_*.py -v

These controls demonstrate CP1252 failure and strict UTF-8 preservation of emoji, combining characters,
Greek text and CRLF without invoking the native CLI or actors. Main's preserved recovery receipt supplies
the actual read-only command result. The worker did not repeat that command.

Genuine Google integration, authenticated human review, live/main-unseen quality, hosted CI and publication
acceptance remain unproved. No useful business completion, legal correctness or positive uplift is claimed.

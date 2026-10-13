# U2-B-1.1 accounting correction

Main's 12 October source probe returned one mocked REQUEST_DEADLINE result. The U2-B-1.0 harness raised before appending or persisting it, reported zero saved raw results and had no intended/started ledger. That probe used mocked actor and SQLite objects; it was not a native journey, database result or model evaluation.

This additive correction leaves every U2-B-1.0 source file, manifest, corpus, label, rubric, runtime decision and budget unchanged. The old harness and its workflow are historical prototypes. The current proposed entrypoint is scripts/evaluation_accounting_acceptance.py; its native execution remains unexecuted.

The pure evaluation/upgrade/u2b_accounting.py module binds an immutable predeclared plan for D15 and C11, two strategies each. It includes source, manifest, policy, full-context, model/config, catalog and candidate identities. An INTENDED record contains all four slots before execution; STARTED must be durably acknowledged before the actor callback. Sequence numbers and previous-record/plan hashes reject omission, duplicate, reorder and tampering. No actor-selected metadata grants execution or changes the plan.

The harness writes immutable files with exclusive creation, flush and fsync, with a separate SQLite mirror. A returned result, including failure state/events/usage/reservations or an identity mismatch, is recorded before the caller stops. A failure prevents further dispatch. Exceptions before return retain a typed exception class and no invented raw result or usage. An unclosed STARTED prefix becomes interrupted_unknown; it cannot be rerun. A lost writer acknowledgement requires read-only prefix reconciliation, never an automatic write or actor retry. Fresh output is mandatory; existing folders and prior results are never overwritten.

All intended pairs remain in reporting. Known failures, interrupted_unknown, unexecuted and returned-but-ungraded slots are distinct. A failed adaptive result with an unexecuted fixed slot is failure_with_unexecuted, not both_failed or a successful tie. Planned slots and observed STARTED reservations are not claimed as completed actor runs. Safety/cost remain unknown for incomplete state; raw known usage is retained without resetting reservations. Scoring failure also preserves its already returned raw result.

The record limit is 1 MiB. A returned JSON value exceeding the half-record raw allowance retains its digest and explicit oversized_not_retained failure; an unserializable return records raw-unavailable status. Neither becomes a zero-run pass. Normal bounded failure results are retained completely. An invalid or missing durable prefix makes observed counts unavailable; it cannot be reconstructed as zero execution. No process/power-loss recovery or actual SQLite durability has been exercised in this source/pure slice.

The new pure controls use only injected in-memory writers and callbacks. They prohibit file I/O, SQLite, sockets, subprocesses and the production actor. They cover main's exact sentinel, returned deadlines, exceptions, interruption, acknowledgement ambiguity, omission/duplicate/reorder, source/config/context bindings, explicit unavailable raw data and fixed denominators. They do not establish semantic or native quality.

Proposed native command, requiring a separate main lease:

~~~powershell
py -3.11 -B scripts/evaluation_accounting_acceptance.py --out work/upgrade-u2b-accounting
~~~

It uses the same D15/C11 agreements, existing PairLimits(seconds=20), scripted double and independent proposal/state scorer as the original proposal. Four intended slots are journaled, executed once, mirrored to SQL and read back. Raw outcomes are frozen before grading the exposed labels. The existing six mechanical refusal controls remain. The requested bounds remain three active minutes, 512 MiB RAM, 16 MiB generated disk, two owned Python processes including launcher, and zero server/download/model/account calls. The 90-second final assertion is cooperative; main supervises the process timeout.

No current CI/native result, genuine Google integration, live-model quality, unseen evaluation, authenticated human approval, production durable dispatcher or full U2/U3 acceptance is claimed. Main owns the unseen set and final acceptance. The frozen 24+12 exposed tasks and 42 historical v1 cases remain unchanged.

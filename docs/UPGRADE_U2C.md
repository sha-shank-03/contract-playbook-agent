# U2C reviewer and remaining-catalog proposal

The accepted historical result is two tied task pairs, four handoffs and zero task completions.
D15 preserves two required handoffs; C11 produces two unnecessary handoffs.
The 33 authored local-double requests are not inference. Model/provider quality remains unmeasured.
The actors, prompts, model, PairLimits, baseline schedule, corpus, labels and rubric are unchanged.

## Read the existing evidence

    python -B scripts/u2c_coordinator.py review
    python -B -m unittest discover -s tests/upgrade/u2c_pure -p test_*.py -v
    python -B scripts/check_repository.py

The reviewer command checks the current additive source seal, dataset bytes and evidence provenance,
reconstructs the reviewed file journals, and independently checks the four source-bound historical proposals.
It performs no actor replay, SQLite connection, provider call or account operation.
The rendered output reproduces docs/U2C_REVIEW_REPORT.md. The JSON report exposes the same known/unknown counts.
Only private path values in two coordinator receipts were redacted; original hashes are retained.
Original main evidence and the defective pre-correction probe remain immutable.

## Entire remaining denominator

U2C_REMAINING_SPEC.json enumerates all 34 remaining existing catalog tasks and 68 ordered actor slots.
D15/C11 are attributed to their original four historical slots and excluded from future dispatch.
The original 42-case evaluation and mocked diagnostics are separate evidence, never extra catalog tasks.
U2C_BINDINGS.json binds every task's source documents, manifest, playbook and full permitted context.
U2C_CONFIG.json preserves the reviewed model/PairLimits; the plan also binds the current source manifest,
catalog, binding/config digests and historical evidence provenance.

The schedule rotates six families and alternates the first split by family, without labels or actor output.
The first proposed slice is D01 (development/paraphrase) and C03 (capability/party-exception).
Later slices cover definitions/reference, competing amendments, absent/unavailable and injection/preservation.
The remaining split counts are 23 development and 11 capability; four families have six tasks and two have five.
No remaining task has executed. Plan generation and the native CLI are authored, not exercised in this slice.

## Proposed future commands: main review and lease first

    python -B scripts/u2c_coordinator.py plan --out work/upgrade-u2c
    python -B scripts/u2c_coordinator.py run-slice --campaign work/upgrade-u2c --tasks D01 C03
    python -B scripts/u2c_coordinator.py report --campaign work/upgrade-u2c

Use py -3.11 -B instead of python -B on Windows if needed.
The plan command creates a fresh child of work/ and durably writes the complete 68-slot intended plan.
The native command reserves exactly the next one or two task pairs, then creates a separate slice Journal.
The current proposal covers only the first two pairs; it is not an approval for the remaining 32 tasks.
Future commands require separate main-managed leases. No command automatically advances to another slice.

Every STARTED acknowledgement precedes its callback. RETURNED stores the failed raw result before stopping.
All raw outcomes in a normal slice freeze before exposed-label grading. Failed scoring retains raw evidence.
The unchanged corrected u2b_accounting.Journal handles exceptions, interrupted starts, loss of acknowledgement,
duplicates, omissions, record/source/config mismatch and refusal to replay started slots.
The coordinator retains all 34 intended rows even after an early failure.
It refuses another reservation after incomplete/unresolved/failed evidence or missing report acknowledgement.
Source-bound slice-report persistence precedes FINISHED; fresh reads verify finished report contents and journals.
An acknowledged but unresolved reservation cannot be silently resumed or replayed. Main must review it.
A malformed or missing prefix yields unavailable observed counts, never invented zero execution.

## Conservative first-slice caps

The proposed batch includes plan, one native slice and report commands with no downloads or dependencies.
Main supervision: 180 seconds total, at most 3 active minutes, 512 MiB RAM, 16 MiB generated disk,
one owned Python process, zero Java processes, loopback servers, browsers, live model calls or account calls.
Each of four actor slots retains the unchanged 20-second PairLimits and model local/contract-double.
The campaign has at most 69 coordinator records. Each slice retains the old 64-record/1 MiB record bounds.
A raw result above the old 524,288-byte retention allowance remains an explicit retention failure.
The 16 MiB cap applies to this first slice; all 34 tasks need future leases and incremental disk review.
These are requested conservative caps, not measured peaks. Main must enforce the wall bound externally.
Filesystem fsync is harness evidence, not proof of process/power-loss recovery or a production dispatcher.

## Counting and limitations

Known historical counts: two unique business tasks, four native scripted slots, two ties, zero completions,
two required handoffs, two unnecessary handoffs, 33 authored double requests, zero live inference.
The corrected diagnostic has one mocked actor callback, one retained failed raw result and three unexecuted
slots. It adds zero business tasks; incomplete safety and cost are unknown.
Remaining intended counts: 34 unique catalog IDs and 68 strategy slots; currently zero new native slots.
A campaign report separates known-prefix counts from unavailable counts for ambiguous reservations.
Returned-but-ungraded slots, failures, interruptions and unexecuted slots remain distinct.
Partial scored tallies are observations, not whole-campaign safety or completion rates.
Whole-campaign safety/rates become available only when all 68 slots are independently scored.
Estimated cost, actual cost, tokens and cost per completed task remain unknown; no cost zero is fabricated.
No semantic/legal success, actual human review, genuine Google integration, live/main-unseen quality,
new independent natural task sample, deployed service or publication is claimed.

Free offline CI is additive u2c-pure.yml using the existing reviewed immutable action pins.
It runs static checks, guarded pure controls and the read-only historical reviewer; no native slice or paid calls.
Hosted CI and the CLI commands have not run in the worker source/pure assignment.
Old scripts/workflows/manifests/receipts remain historical and unchanged; use the new entry point for U2C.

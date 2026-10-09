# Investigation, proposals and review

```text
CLI -> bounded immutable bundle + trusted playbook
    -> ToolRegistry <-> scripted, fixed keyword or native provider
    -> persisted budget reservation -> action intent
    -> validated tool observation + checkpoint committed together
    -> immutable proposal + unapproved per-document previews
separate reviewer -> digest/current-input checks -> committed draft snapshots -> reviewed copies
evaluation -> freeze all paired/repeated producer files -> independent raw/SQLite/gold oracle
```

The provider selects one allowlisted action from observations. It can read rules, search clause headings, read complete blocks, scan coverage pages, resolve literal references, propose findings and submit a completed review. It cannot approve, select arbitrary paths, execute commands or read evaluation labels. The source inventory contains only manifest-listed documents; labels and verifier logic remain outside the tool registry.

The fixed keyword provider shares that registry, journal, output schema and review gate. It schedules one full scan before rule searches/proposals, matches direct phrases/numbers and conservatively retains host-reported conflicts/unknowns. It selects no reference-resolution tool and proposes no absence insertion. Its source-ready implementation has pure component checks; its paired outcomes have not run.

The host validates exact schemas, trusted policy citations, current source hashes, read blocks, quotes and character ranges. Patches must lie inside same-document cited spans, be bounded and non-overlapping. Insertion requires an empty old range and exact trusted wording at a fully read host-approved section boundary. All three rules need findings. Unknown evidence, conflicts and missing terms with no safe insertion yield HANDOFF.

Literal references resolve at most three hops. Numbered headings and amendment replacement statements are excluded from reference inventory. A chain records every literal link and its read path. Missing attachments, broken sections, cycles and ambiguous paths remain unknown. Supplied amendment text is fully read before completion. Only explicit replacement statements establish a supported amendment edge; two replacements of the same source section conflict even with identical contents. Dates, filenames and manifest order do not imply priority.

Heading search locates likely clauses and effective replacements. The scripted provider supports a deliberately narrow sentence grammar, with limited scanning for relocated canonical sentences. A whole missing clause or missing written-notice/receipt atom requires a complete digest-bound coverage receipt for every supplied document. Full reading is evidence of supplied-text coverage, not general legal absence or exhaustive semantic interpretation. Unsupported relevant wording hands off.

Edits use Python character offsets and exact old text. Materialization concatenates untouched UTF-8 byte slices with encoded replacements. This preserves line endings, combining characters, emoji and unrelated numerical values outside edited ranges. Base and amendment patches stay attached to their own document versions.

# Persistence and bounded execution

INVESTIGATING finishes as PENDING_REVIEW or HANDOFF. Failure, cancellation and exhausted budgets are persisted. An explicit resume verifies all current inputs and restores rules, reads, references, findings, committed observation history and counters. A stale input requires a new run.

Before each provider call, the journal reserves one decision and up to 20 seconds of runtime. Successful calls reconcile actual elapsed time; a crash retains the conservative reservation. A decision intent commits before tool execution. The observation, registry checkpoint and action ID then commit in one SQLite transaction. Recovery replays an uncommitted intent and records it once. Replays and repair counts survive resume. This is sequential local recovery, not distributed or concurrent execution.

Defaults are 48 decisions and 120 seconds. User limits are capped at 96 decisions and 300 seconds. A rejected proposal gets at most two repair opportunities per rule, other protocol failures two, and transient provider failure one retry. Pending intents allow at most two replays. No required context is silently truncated. Context/request is bounded to 96 KiB, a decision to 16 KiB, source tool output to 12 KiB and HTTP response to 64 KiB.

The native Ollama provider requires explicit model and `http://127.0.0.1:<port>/api/chat`. It sends non-streaming native function schemas, assistant tool calls and tool-role observations. It accepts exactly one allowlisted call with object arguments. Prompt and completion usage are recorded only when present; unknown failed/missing usage remains unknown.

A fixed-purpose owned child performs HTTP with proxies and redirects disabled and socket timeout at most 15 seconds. The parent enforces an absolute deadline at most 20 seconds and checks cancellation every 50 milliseconds. It kills only that owned child and closes its pipes on exit. No server or model lifecycle is automated. The fake HTTP tests cover the adapter route without claiming model execution or quality.

# Digest-bound review and export

The proposal digest covers findings, edits, all document versions, manifest, playbook, coverage, references and provider labeling. Timing/usage are separate. Approval checks the immutable artifact against SQLite and verifies every current document, policy and manifest. Approval is all-or-none.

Authoritative draft bytes for every supplied document and one review decision commit together. Files export from those snapshots afterward. Repeating the same decision returns the stored receipt and completes interrupted export without applying edits again. A complete matching temporary file can be materialized on retry; differing generated bytes are refused. Handoff packets cannot be approved. Reviewer labels are unauthenticated annotations.

# Independent checks and present evidence

The M1 and M2 development verifiers import only the standard library. They compare outcomes and complete output bytes to authored gold, inspect actual read/proposal observations, verify quotes and policy versions, and compare untouched original intervals. They do not import production decisions, guards or materialization code.

M1 and M2 were independently accepted. Main's M2 review recorded nine commands, 46 tests, 2,141 development assertions, 345 M1 regression assertions and 396 additional artifact checks. Worker integration passed without actor/verifier fixes. Thirty same-author synthetic cases remain frozen; the complete 180-run evaluation has been scored and independently verified, as recorded in [current evidence](../EVIDENCE.md#m3-current-results-and-independent-checks).

M3's oracle is evaluator-only standard-library code and imports no production implementation. It separately validates raw/SQLite integrity, finite gold-supported meaning and exact protected/final bytes. The v2 paired driver first persists an immutable full 180-attempt plan and flushed start/result receipts, then freezes all producer/receipt files before decoding gold labels. Interruption/fatal diagnostics and complete attempted/unattempted accounting survive in partial evidence, which cannot pass release or reduce quality denominators. Complete unique run keys and raw integrity/operational safety across all 180 runs are separate gates from 120 normalized comparisons. Primary quality remains 30 cases per provider; baseline quality is ungated.

Python source identity and accepted freeze are embedded in the report; the separate source-ready checkpoint covers the complete public tree. Regrade checks plan/receipt identity and refuses partial or changed producer/code/freeze bytes and fabricated aggregates. Elapsed runtime and reviewer timestamps are excluded from repeat hashes, while packets, traces, usage counters, output hashes and decision identity remain included. Required exports count toward exact completion. Pure synthetic controls and paired scoring have run; main independently passed all 147 application tests, both development regressions and quickstart checks on unchanged application source. Earlier source-ready descriptions above are historical; failed worker measurement attempts remain failed.

This design uses explicit text grammar and gold bytes rather than embeddings, a vector index or a framework dependency. That makes investigation/edit authority and recovery inspectable on an existing Python interpreter, but limits language coverage and rejects unlisted semantically reasonable alternatives. Fixed-scan baseline comparisons expose those limits without claiming a learned model benefit. The source-ready CI and final acceptance orchestrate explicit suites because root unittest discovery alone omits non-package test directories. See [evaluation methodology](EVALUATION.md) for denominators, release gates and execution boundaries.


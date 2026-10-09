# Verification record

Current status, 8 October 2026: independent checks passed the public application's 147 tests, both development regressions, quickstart approval/handoff behavior and the complete saved 180-run evaluation. Final M3 package acceptance awaits documentation review. [Current results](#m3-current-results-and-independent-checks) appear after the historical record below. Earlier statements that scoring or integration had not run describe their specific checkpoints; they do not replace the later results. Failed attempts and unknown measurements remain unchanged.

# M1 evidence

Date: 8 October 2026. Scope: direct-clause M1 implementation, lightweight units, two actual CLI demos and independent CLI acceptance. All worker M1 checks passed; main independently accepted M1 before the M2 source changes. No real model, account, dependency download, model installation, publication or deployment was used.

## Environment observed

Command:

```powershell
py -3.11 -c "import sys, platform, sqlite3; print(sys.version); print(platform.platform()); print('SQLite ' + sqlite3.sqlite_version)"
```

Exit 0. Python 3.11.9, 64-bit MSC v.1938; platform string Windows-10-10.0.26200-SP0; bundled SQLite 3.45.1. Windows commands select 3.11 explicitly.

## Executed lightweight checks

```powershell
py -3.11 -m unittest discover -s tests -p test_m1_*.py
```

First run: exit 0, 28 tests, 0.794 seconds, OK. The suite contains isolated parsing, tool-authority, provider-observation, patch, and local review-store units. It does not launch the full demo, complete CLI workflow or acceptance batch.

Checked behaviors include corrupted source quotes and versions, unread citations, invalid/boolean/out-of-range spans, uncited fee edits, overlapping patches, exact old text, Unicode/CRLF preservation, forbidden tools, bounded bad-provider feedback, exact digest approval, unchanged source bytes, rejection/stale proposal/source/playbook preventing export, and sequential repeated approval returning one stored decision.

Counts are unittest test-method counts; assertion statements are not instrumented in the unit suite. Invalid-span testing includes four subcases. The future independent acceptance runner reports its own explicit assertion count.

Source-only syntax check: parsed all 16 Python files with ast.parse without importing or executing the application; exit 0. git diff --check returned 0, but the new source is untracked at this checkpoint, so that command is not evidence of a full source whitespace audit. A narrow rg scan found no hard-coded personal paths, coordination references or key-prefix markers in shipped files; this is not comprehensive secret scanning.

## Authoring correction

One source-authoring tool orchestration failed before execution with JavaScript SyntaxError: Missing initializer in destructuring declaration. The loop keyword spacing was corrected. No Python command ran and no application files were changed by that failed attempt. No failing Python test run occurred before the first successful suite.

## Executed integration commands

```powershell
py -3.11 -m contract_playbook demo --case direct-review --out work/m1-demo
py -3.11 -m contract_playbook demo --case compliant-review --out work/m1-compliant
py -3.11 scripts/acceptance.py --milestone m1 --out work/m1-acceptance
```

Executed sequentially on the granted M1 slot. Each command exited 0 on its first attempt. There were no unexpected Python or integration failures and no application-code correction was needed in this turn.

| Command | Result | Observed command/monitor wall time |
| --- | --- | ---: |
| Direct-review demo | Pending review; three deviations and exactly three patches. | 0.375 seconds |
| Compliant-review demo | Pending review; three compliant outcomes and zero patches. | 0.406 seconds |
| M1 acceptance batch | Passed 248 explicit assertions. | 2.891 seconds |

The raw literal invocations, exits, stdout/stderr and timezone-aware grant checks are preserved in work/integration-run-receipt.json. The unshipped measurement wrapper launched exactly the three literal commands above. It checked the exact active worker-owned M1 lease using raw JSON strings and datetime.fromisoformat with timezone presence, granted <= current UTC < expiry, immediately before each command. Checks occurred at 10:13:41.188564, 10:13:41.569892 and 10:13:41.976316 UTC. The lease interval was 10:11:15.291368 to 11:41:15.291368 UTC.

Acceptance used 11 sequential child CLI invocations: nine exited 0; the two intentional stale-source and forged-proposal approval attempts exited 3 as required. These are expected rejection results, not unexpected failures. Each child's literal argv and output is preserved in work/m1-acceptance/attempt-001/acceptance.json. The runner invokes the already selected Python 3.11 executable directly for children.

There are two distinct visible authored cases / six unique rule dispositions. Each case has three exact source and three exact policy citations. The verifier checks repeated pending/reviewed artifacts without counting those repeats as new cases. It checked golden final bytes, obligation outcomes, original preservation, no export before approval, rejection/stale protection, one stored repeated approval, and rejection of a deliberate unrelated fee mutation. The direct and compliant approved copies both match the independently authored final text. All unchanged regions have zero changed bytes.

Original SHA-256 versions:

- Direct: b915cb97e68310fdbfc5a280f50c8d787d1b3b9e4310f8b9c56e55dd9dcfa887.
- Compliant: 936d921ac5223ddd9b035c966d42611249798ef84283e0da8a12de7a8673d521.

Both still match the original fixture files after acceptance. The two top-level demos have no reviewed export; approvals happen only in the separate acceptance-run copies. The reviewed direct copy's hash is the compliant original hash above.

Direct edits use half-open source ranges. These ASCII fixtures have equal character and UTF-8 byte offsets:

| Rule | Character / byte range | Exact old text | Replacement |
| --- | --- | --- | --- |
| REN-01 | [313, 408) | The term renews automatically for successive one-year periods unless either party gives notice. | The term renews only by express written agreement of both parties. |
| TERM-01 | [495, 497) | 60 | 30 |
| PAY-01 | [598, 600) | 15 | 30 |

Every cited quote and old-text range was checked against the exact version. Unicode and CRLF preservation has separate unit evidence, not an additional complete CLI case.

The 24-file source/data content manifest is preserved in work/m1-provenance.json; its SHA-256 is b30c259ce45510354c1c8c0beafed425d208b9bbe21dfb64a98c938ec0aa02be. This content digest identifies the checked code/data despite the repository not yet having a commit. Generated work files and personal runtime paths are ignored by Git.

## Observed resource use

The command/monitor loops consumed 3.672 cumulative active seconds; the complete wrapper tool call took 4.075 seconds. Both are below the ten-minute grant. Windows process-memory counters sampled every 10 ms measured a maximum aggregate working set of 98,705,408 bytes (94.133 MiB), including the measurement wrapper, launcher, console helper, acceptance process and its sequential CLI child. Five owned processes were observed at once; there was only one application CLI child at a time. This is a sampled observation, not a guarantee about an unobserved brief peak.

Scratch immediately after the commands was 488,997 bytes; later provenance/measurement records and Python caches are counted in status.json. The grant allowed 256 MiB RAM and 50 MiB scratch. Application download bytes, network calls and model calls were all zero. No other worker's lease was used. The worker stopped consuming the slot and requested main-owned release after the M1 results.

## Honest evidence boundary

The default provider is scripted and makes zero model calls. The two cases are visible authored examples, not the later held-out suite. This section records the earlier M1 checkpoint. M2 source is now authored as described below; M2 integration and M3 broader evaluation/CI remain unexecuted. Main independently accepted M1. Live-model quality, legal expertise, production adoption and reviewer time saved are not measured.

# M2 source checkpoint

Date: 8 October 2026. M1 was independently accepted by main: four commands, 28 unit tests, 248 acceptance assertions and 22 additional checks. That acceptance applies to the earlier M1 content digest above. M1 regression against the current M2 source has not run.

M2 source now contains bounded literal reference chains and explicit amendment replacement chains, conflict/unknown handoffs, complete supplied-document coverage receipts, trusted boundary insertion, missing written-notice/receipt corrections, multi-document review snapshots, a native Ollama adapter, persisted reservations/actions/checkpoints and sequential recovery paths.

At the pre-integration source checkpoint, the only executed M2 tests were isolated pure components. They do not run the actor loop, HTTP, a server, a transport subprocess, SQLite recovery, a CLI demo or integration acceptance.

```powershell
py -3.11 -m unittest discover -s tests/components -p test_m2_*.py
```

Initial run: exit 0, 36 test methods, unittest duration 0.020 seconds; tool wall time 0.530 seconds. Second expanded run: exit 0, 41 test methods, unittest duration 0.045 seconds; tool wall time 0.640 seconds. Final run after the complete tool-envelope bound check: exit 0, 42 test methods, unittest duration 0.039 seconds; tool wall time 0.589 seconds. Test-method counts are not assertion counts. No failing component test run occurred. Components check reference/replacement topology, all-document coverage and tampering, unknown-versus-absence guards, approved insertion text/boundaries, cross-document citation rejection, Unicode/CRLF raw slices, source instruction authority, budget restoration, pure native protocol parsing/request history and an in-memory transport double. The source-result limit includes coverage metadata, rather than only source text. A 48-block pure fixture checks that pagination respects the complete 12 KiB envelope without truncation. Additional checks cover a body self-reference and preservation of favorable 45-day timing when adding a missing receipt trigger.

Static source parsing used Python 3.11 ast.parse over all 27 package/evaluation/script/test files: exit 0. No application module was imported or executed by this check.

```powershell
py -3.11 scripts/check_frozen_inputs.py
```

Exit 0. Static integrity audited 42 authored cases, 138 required quote spans and 24 authored patch ranges against their original text and independent gold files. This is an input/label audit, not an actor outcome measurement. The two original M1 agreement hashes are unchanged.

Thirty held-out cases were frozen before any actor execution or scoring. There are 115 frozen files. Canonical entries digest: efd5dd3d38583f0aec2d41bf9c209c0c48d37ef73e55679c1ee647b06035cdaf. Freeze file digest: 8ae16854230fd754760c38a205f698857fdbdb3f75e0da92ee16cd9daac3b666. Both are recorded in evaluation/HELDOUT_FREEZE.json and checked by the static audit. At source handoff rubric and sample-gold review were pending; an independent review subsequently accepted them before the M2 integration grant. Actor calls, held-out predictions and outcome scores in the corpus audit are all zero.

The corpus contains 12 visible development cases and 30 unscored held-out cases. Cases and labels are developer-authored with AI assistance. They cover structural families and share narrow canonical sentences; they do not constitute a blind expert legal dataset. The rubric states the evidence limits and future denominators. Labels are outside actor tool access.

Authoring corrections were retained: one attempted replacement of tools.py used delete/add on the same path and was rejected; a later store.py patch was rejected because a hunk did not match. Both were corrected with complete update patches. One read used an incorrect package directory and returned a file-not-found error; it was corrected. The first corpus authoring command exited 1 because a literal reference also appeared in a heading. The authoring locator was changed to exclude heading occurrences, then regenerated the authored data successfully and froze it. No actor, model, HTTP or integration execution occurred in these failed authoring attempts.

# Prepared M2 integration checks at source handoff

```powershell
py -3.11 -m unittest discover -s tests -p test_m1_*.py
py -3.11 scripts/acceptance.py --milestone m1 --out work/m2-m1-regression
py -3.11 scripts/acceptance_m2.py --out work/m2-acceptance
py -3.11 -m unittest discover -s tests/provider_contract -p test_*.py
py -3.11 -m unittest discover -s tests/recovery -p test_*.py
```

These were held unexecuted until the new named M2 integration grant described below. They are sequential and create fresh owned scratch under work/. The native HTTP suite contains 11 test methods, uses a local fake server, and invokes only owned fixed-purpose transport children. It covers native tool/observation history, observed or unknown usage, malformed protocol/JSON repairs, a transient 503, permanent errors, oversized responses, redirects, absolute deadlines including a continuous trickle, cancellation and child cleanup. The recovery suite contains seven methods with multiple crash subcases, covering budget reservation, intent, tool, checkpoint and proposal crashes, duplicate staged findings, approval/export crashes, persisted limits, cancellation, stale amendments/manifest and multi-document export. Test counts here describe authored source, not executed results.

The development acceptance source evaluates only the 12 visible cases, with three expected outcomes each. It compares actual final artifacts to independent dispositions, atom labels, quote spans, exact patches, complete reviewed document bytes and unchanged intervals. It checks that unknown/conflict packets cannot export, repeated approval is idempotent and the independent verifier detects an unrelated fee mutation. Held-out inputs/labels are not opened by that runner.

At source handoff no M2 integration receipt existed. No real server/model was installed, started or called. Hosted CI, Linux verification, held-out scoring, baseline comparison, legal quality and business impact remain unexecuted. M2 source readiness does not mean milestone acceptance.

Final handoff provenance command: py -3.11 work/m2_source_provenance.py (ignored source-only helper), exit 0. It hashes the shipped source/data/docs, parses 27 Python files without application imports, and checks trailing whitespace. The manifest is in work/m2-source-provenance.json; the current content digest is recorded in the source checkpoint. A narrow rg scan over shipped code/docs found no personal absolute-path, coordination-path or API-key-prefix matches (exit 1 means no findings). This is not comprehensive secret scanning. Git status still lists the authored tree as untracked; no commit or publication was requested.

# Executed M2 integration

The independent source/rubric review accepted the 42 pure tests and 540 static conditions before granting this five-command slice. The new worker-owned contract-playbook-agent-m2-integration lease was valid from 11:37:39.963893 to 13:07:39.963893 UTC on 8 October 2026, with a 15-minute cumulative active limit, 256 MiB aggregate owned RAM, 50 MiB generated disk, zero downloads, one workload child and one loopback double at a time.

All five commands passed on their first test attempt. Exact raw timezone-aware grant/expiry checks occurred immediately before each invocation, and the ignored measurement wrapper preserved argv, stdout/stderr, exits, process samples, cleanup and the complete source entries for every attempt.

| Exact command | Exit and result | Active seconds |
| --- | --- | ---: |
| py -3.11 -m unittest discover -s tests -p test_m1_*.py | 0; 28 methods, unittest 1.164 seconds | 1.390 |
| py -3.11 scripts/acceptance.py --milestone m1 --out work/m2-m1-regression | 0; 345 assertions | 5.797 |
| py -3.11 scripts/acceptance_m2.py --out work/m2-acceptance | 0; 2,141 assertions across 12 development cases | 14.344 |
| py -3.11 -m unittest discover -s tests/provider_contract -p test_*.py | 0; 11 methods, unittest 15.041 seconds | 15.344 |
| py -3.11 -m unittest discover -s tests/recovery -p test_*.py | 0; seven methods, unittest 7.999 seconds | 8.266 |

The tested complete source/data/docs digest was c0a698a3ff943a5bf62b86db829388e6d388ef642d094ae763869ca82320b8b3 for every command. No actor, verifier, trusted rule, label, fixture or freeze change was required. The code/actor protocol remains m2-v1, schema 2. Later edits update evidence/status documentation only. The prior source freeze and authored exposure history are preserved.

Raw receipts: work/m2-integration-receipts/attempt-001.json through attempt-005.json. Each contains the full tested source entries and raw outputs, including intentional errors. M1 regression's nested CLI receipt is work/m2-m1-regression/attempt-001/acceptance.json; M2 development's is work/m2-acceptance/attempt-001/acceptance.json. The ignored measurement wrapper launched only these five authorized commands. It rechecked the exact active worker/M2 lease, raw offset-aware UTC timestamps, cumulative active time, unchanged held-out hashes and disk bound immediately before each command.

M1 regression made 11 sequential CLI calls: nine exited 0 and the two intentional stale/forged approval attempts exited 3. The current M2 metadata/trace adds checks relative to the earlier 248-assertion M1 snapshot; current regression reports 345 assertions without changing the M1 verifier or its expected bytes.

M2 acceptance made 26 sequential CLI calls: 22 exited 0; the four expected handoff approval attempts exited 3. Its 12 authored cases cover 36 rule/case positions and 84 obligation atoms. Eight cases produce digest-bound approved copies; four hand off for broken reference, reference cycle, competing amendments or unavailable attachment. The verifier checks exact current source/policy quotes, trace reads, approved boundaries, per-document patches, original preservation and independent complete final bytes. Reported unrelated changed bytes and changed original bytes are both zero. Repeated approval returns the same receipt, and deliberate unrelated fee mutation is rejected by the independent verifier. These counts describe visible authored template regression evidence, not a blind legal benchmark or model accuracy.

The 11 HTTP methods ran real loopback fake-server exchanges and owned transport children. They checked native history serialization, observed zero or unknown usage, malformed/oversized response handling, bounded 503 retry/protocol repairs, redirects, permanent errors, absolute deadline, continuous trickle, cancellation and child cleanup. No real model or installed model server was used. The seven recovery methods include nine intentional owned subprocess exits of 91 across reservation/intent/tool/checkpoint/proposal and approval/export boundaries; these expected crash exits are not test failures. All recovery, cancelled-run resume, persistent budget, stale amendment/manifest and multi-document export checks passed.

One instrumentation correction occurred in the ignored wrapper: Python executables on this machine are named python3.11.exe. Attempts 001-002 recognized only python.exe/pythonw.exe, so their Python-specific counters report zero incorrectly. Those raw fields are retained and are not used as evidence. Their aggregate memory/process counts and per-process name/peak samples remain valid. The recognition was corrected before attempt 003; subsequent samples observed up to three owned Python processes. No application or verifier fix occurred and no failed test run was hidden.

Cumulative heavy active time was 45.141 seconds. Sampled aggregate peak working set was 117,624,832 bytes (112.176 MiB), including the wrapper, launcher, console helper, command/test parent and its one sequential workload child. Five owned processes were observed at once; valid Python-specific samples observed three. At most one owned CLI/transport/crash child and one loopback fake server ran at a time. These are sampled observations, not guarantees of an unobserved instantaneous peak.

Scratch plus Python caches immediately after the last command measured 4,155,603 bytes before writing that last raw receipt and final handoff records. Final disk accounting is in status.json and the ignored final audit receipt. After every command, the wrapper's live process-family check found zero remaining owned descendants. Temporary fake-server/recovery directories were cleaned by the tests; all fake server processes/threads ended with their test parent. The worker is idle and release-ready; main owns shared lease release and independent M2 acceptance.

No held-out actor execution or scoring, baseline/repeated evaluation, hosted CI, new dependencies, paid/API-key calls, real inference, publication or deployment occurred. The 30-case authored freeze remains unchanged. At this handoff, independent M2 acceptance was pending; its subsequent acceptance is recorded below. Legal accuracy, production behavior and business impact are not measured.

Post-run generated-artifact command: py -3.11 work/m2_final_audit.py (ignored read-only helper), exit 0. It checks the already generated acceptance artifacts and raw receipts without another actor run: 17 original documents, 17 previews, 11 reviewed documents across eight approved cases, four handoff cases with no export, 40 source citations and seven localized patches. It confirms all actor/verifier/fixture/gold bytes match the tested snapshot and all 115 frozen files remain unchanged; only the four evidence/status documentation files differ. Full per-case digests/patches are in work/m2-final-audit.json; final public-tree provenance is in work/m2-final-provenance.json. These are artifact integrity checks on the existing development run, not additional evaluated cases or held-out scores.

# Subsequent independent M2 acceptance

Main accepted M2 at 2026-10-08T11:50:12.521501+00:00. Its review recorded nine commands, 46 tests, 2,141 development assertions, 345 M1 regression assertions and 396 additional raw-byte/citation/SQLite/approval checks. All 40 development citations and 115 frozen files were verified. This supersedes the historical pending status at worker handoff. It does not authorize or establish M3 scoring.

# M3 source and pure component evidence

Date: 8 October 2026. Scope: source, documentation and synthetic pure units only. New components are keyword-v1 through the existing tool/reviewer guards, outcome-oracle-v1.1, paired-evaluation-v1, M2/all acceptance dispatch, static repository checks and an immutable-pin CI workflow. The scripted grammar, tools, journal, native transport and reviewer behavior are unchanged. Pre-change M2 files and the initial M3 oracle were archived before edits; [docs/VERSIONS.md](docs/VERSIONS.md) records reasons and hashes.

Actual command:

```powershell
py -3.11 -m unittest discover -s tests/components -p test_m3_*.py
```

Raw receipt sequence under ignored work/:

| Attempt | Actual result |
| --- | --- |
| Initial uncaptured tool output | Tool output was truncated; exit/timing are not used as evidence |
| 002 | Exit 0; 31 methods; 0.106 seconds; initial oracle/component controls passed |
| 003 | Exit 1; 37 methods; 0.105 seconds; four setup errors in the new empty-clause test factory |
| 004 | Exit 0; 38 methods; 0.121 seconds; corrected factory and stronger guards passed |
| 005 | Exit 0; 44 methods; 0.130 seconds; added required-export, reviewed-byte, per-rule/denominator and rubric controls passed |
| 006 | Exit 0; 44 methods; 0.145 seconds; exact offline usage and event-type guards passed |
| 007 | Exit 0; 44 methods; 0.138 seconds; final generated-file boundary/checkpoint-size source review |

Attempt 003's errors occurred before assessment: the empty-clause fixture entered an ordinary notice-substring branch. The exact failing source was archived and only that test condition was fixed. No oracle or frozen-label change was made to conceal a score failure. All captured stdout/stderr are retained in work/m3-pure-unit-attempt-002.json through 007.json. Counts are methods, not the number of mutation subcases or independent contracts.

The controls use hand-authored synthetic in-memory source, policy, packet, trace, expected bytes and database-shaped objects. They execute no actual SQLite workflow, actor loop, held-out fixture, HTTP server, transport child or crash recovery. They reject invented/wrong-rule quotations, wrong policy/version/digest, omitted missing atoms, coherent wrong replacement bytes, missing history/actions, fabricated usage, unauthorized/partial exports, handoff promotion, absence with an omitted literal reference, unsafe insertion and unrelated Unicode/CRLF/fee changes. Positive controls distinguish valid pending proposals from complete approved cases and retain required handoffs. Literal quotation and finite gold-supported meaning are measured separately.

Static command py -3.11 work/m3_static_counts.py exited 0. It only added arithmetic over existing frozen labels: 30 cases, 90 rules, 210 atoms, 98 required source spans (80 clauses and 18 links), 41 sources, eight mandatory handoffs, 22 approval cases/28 required reviewed documents, 24 positive atoms (12 deviation and 12 missing), 17 localized patches and 58 protected intervals. All 115 hashes matched. Actor calls, held-out predictions and outcome scores were zero. The receipt is work/m3-static-corpus-counts.json; these are denominators, not benchmark results.

Static command py -3.11 scripts/check_frozen_inputs.py exited 0 on M3 source: 42 authored input/label/gold cases, 138 required quote spans, 24 authored patch ranges and all 115 frozen file hashes audited; zero actor calls, predictions and scores.

Repository-check attempt 001 exited 1 because its path-prefix regex self-matched the checker source. The raw failure and exact source were preserved. Composing the same alternatives from split literals fixed the self-match without weakening intended detection. Attempt 002 exited 0: 36 Python files and 48 JSON files parsed, 215 public files inspected, all 115 frozen hashes intact, allowlisted stdlib/local imports and exact CI pins/guards/command text checked. Hygiene covers UTF-8, file types, whitespace and specific path/credential patterns, not a comprehensive secret audit. CI checking is static authored-text review, not a general YAML parser or hosted execution. Raw receipts are work/m3-source-check-attempt-001.json and 002.json.

Attempt 003 of the static repository check also exited 0 on the subsequent source/doc checkpoint, with the same file and freeze counts. The final public-tree and Python manifests are recorded separately in work/m3-source-provenance.json at handoff. The last oracle read-boundary review was archived before adding explicit regular-file/directory checks and a bounded 2 MiB persisted checkpoint decoder; no integration or score informed those edits.

Prepared future commands and their exact grading semantics are in [docs/EVALUATION.md](docs/EVALUATION.md). Held-out production/scoring, paired baseline outcomes, fresh repeatability, full M3 acceptance, HTTP/recovery reruns on M3 bytes, hosted CI, Linux runtime, live inference and publication remain unexecuted. Source preparation stops for main review and a new named M3 lease.

# Main-reproduced M3 harness correction

Main's 14:07 source review ran the original 44-method pure suite and both static checkers successfully, then independently reproduced two harness failures with local doubles: C-M3-01 lost completed attempt metadata on interruption; C-M3-02 allowed a secondary scripted raw SQLite integrity failure through release while normalized repeat hashes still matched. M1/M2 remain accepted. No M3 lease or held-out execution was granted.

Before correction the exact 215-file candidate, provenance, source-ready/status records and main's failure evidence were copied to work/m3-before-main-corrections/. All earlier raw failures remain intact. Worker command py -3.11 work/reproduce_m3_main_findings.py exited 0 and reproduced both v1 defects using two mocked producer calls and synthetic assessment objects. Only a started exposure survived interruption; the corrupt secondary synthetic report incorrectly remained passing. The evidence is work/m3-main-review-reproduction/result.json. Actual actor calls, held-out source reads/scores and HTTP calls were zero.

The runner is now paired-evaluation-v2, with report schema 2. It persists a full immutable plan before work, flushes/fsyncs exclusive-create start/result receipts incrementally and retains partial accounting/diagnostics on interruption or fatal failure. Partial/missing/duplicate/unplanned execution cannot pass or reduce the fixed 30-case/90-rule/210-atom primary denominators. Completed producer files and receipts are frozen before gold grading. All 180 planned run keys must be unique/present and all raw integrity/operational checks must pass across both providers and every repetition; this is separate from normalized equality. Baseline task quality remains ungated. Actor, baseline, oracle, frozen data, policy, labels, expected bytes/patches and primary thresholds are unchanged.

Actual pure command:

```powershell
py -3.11 -m unittest discover -s tests/components -p test_m3_*.py
```

| Correction attempt | Actual result |
| --- | --- |
| 001 | Exit 1; 46 methods; 0.242 seconds; the two new controls reproduced missing plan/receipt evidence and secondary raw-integrity bypass on old runner |
| 002 | Exit 0; 46 methods; 0.339 seconds; v2 fixes passed both controls |
| 003 | Exit 0; 57 methods; 9.068 seconds; added producer-error/fatal/unfinished/overwrite/manifest/full-cohort controls |
| 004 | Exit 0; 59 methods; 10.306 seconds; also covered fatal attempt-directory setup and error-state safety |

Raw stdout/stderr/exit records are work/m3-harness-correction-pure-attempt-001.json through 004.json. These are 59 methods: 29 existing oracle controls, five baseline controls, ten metric contracts and 15 harness controls. Harness tests use owned temporary text receipts and in-process producer/reviewer/freeze/gold doubles. One control completes 180 mocked calls before a synthetic post-production fatal error; it executes no actual actor or held-out data. No real SQLite, HTTP, Java, model or full integration runs occur.

Final retained command py -3.11 work/verify_m3_main_corrections.py exited 0. Its two producer doubles persist all 180 planned identities, first completed record, second interruption, counts of two attempted/one produced/one interrupted/178 unattempted, a bounded sanitized diagnostic and release=false/quality=null. Reusing the output refuses without changing existing bytes. A synthetic secondary raw-integrity corruption now fails release even with 120/120 normalized comparisons; the synthetic raw integrity denominator is 180 (179 valid). Missing/duplicate row sets are rejected. Evidence: work/m3-correction-probes-v2-final/result.json. These synthetic numbers are harness controls, not held-out results.

Correction static commands also exited 0: py -3.11 scripts/check_repository.py parsed 36 Python and 48 JSON files across 215 public files with unchanged 115-file freeze; py -3.11 scripts/check_frozen_inputs.py audited 42 authored input/label/gold cases, 138 required spans and 24 patch ranges, with zero actor calls/predictions/scores. Receipts are work/m3-harness-correction-source-check-001.json and work/m3-harness-correction-freeze-check.json. The final checkpoint repeats the static audit after this evidence text is saved.

At the end of that source-preparation slice, the revised checkpoint and exact future command sequence awaited main re-review. Held-out production/scoring, baseline outcomes, fresh real repeatability, HTTP/recovery reruns, full acceptance, hosted CI and all live/account/publication actions were unexecuted. The later first leased attempt is recorded below.

# First M3 lease: stopped at measurement failure

Main accepted corrected source and independently reviewed all 30 rubric cases before production, with 349 static conditions. The accepted public tree was `0d8dcd355560e2a6fcc31b1c0011450f166d0d67063beaa896961ae1575f1fc0`; Python identity was `e540e8a4cd62bbc4cd2f06fcc0b57c0144bbef6b5c3c4ea3ca2264f15823028c`. New lease contract-playbook-agent-m3-integration granted 15 cumulative active minutes, 256 MiB aggregate owned RAM, 100 MiB generated disk and zero downloads/models. Raw timezone-aware grant/expiry, owner, status, source and remaining budget were checked immediately before each attempted command.

| Approved command | Actual result |
| --- | --- |
| py -3.11 scripts/check_repository.py | Exit 0; exact accepted 215-file tree, 36 Python ASTs, 48 JSON files, unchanged 115-file freeze; 0.547 measured active seconds |
| py -3.11 -m evaluation --suite heldout --provider scripted --baseline keyword --repetitions 3 --out work/m3-evaluation | Producer command began; measurement wrapper exited 1 on FileNotFoundError while sampling a disappearing SQLite journal; owned command tree then forcibly stopped; application exit not captured |
| py -3.11 scripts/acceptance.py --milestone all --evaluation work/m3-evaluation --out work/m3-acceptance | Unexecuted after the first failure; 147 methods were planned, zero integration test methods ran |

Raw command evidence is work/m3-integration-receipts/command-01/result.json and command-02/. The first error, stdout/stderr, initial lease/source receipt, verified owned-process identity, cleanup and post-stop accounting remain retained. Instrumentation-v1 and the reused sampler are archived at work/m3-instrumentation-failure-v1/. No code or measurement fix, hidden retry, denominator reduction, actor tuning or dependent heavy command followed the failure.

Original work/m3-evaluation/execution-plan.json retains all 180 unique identities. Original exclusive start/result receipts reconstruct 71 attempted, 70 completed/produced, one unfinished and 109 unattempted; zero producer-error/interrupted/failure terminal records were emitted before forced stop. This is attempted-run accounting, not an integrity or accuracy result. No application partial.json, completed report, gold grading, paired quality score or normalized repeat comparison exists. Reconstruction is outside the producer tree at work/m3-integration-receipts/command-02/partial-accounting.json, with release=false and quality=null. All 741 original partial artifact files are hash-listed separately without changing their bytes.

Command 1 sampled aggregate working-set peak was 84,283,392 bytes (80.379 MiB), with two Python processes and four owned processes including launcher/console helpers. Command 2's live samples were held in wrapper memory and lost on its exception; started-receipt zero placeholders are not measurements and no peak RAM/process compliance is claimed for that command. Verified launcher creation and cleanup evidence give a conservative total heavy active-time upper bound of 53.592 seconds, rather than an exact measured duration. Only the owned evaluation tree was stopped; post-cleanup verification found zero owned evaluation/measurement processes. No fake HTTP server was started in this lease.

The application Python identity, actor, baseline, independent oracle, policy, labels, gold, corpus, thresholds and 115 frozen files remained unchanged throughout execution and after exposure. Final changes report this failure in documentation only. M1/M2 remain accepted; M3 outcomes/full acceptance are not accepted. The worker is release-ready and stopped for main review. Hosted CI, live models, downloads, external accounts and publication remain unexecuted.

# M3 current results and independent checks

Date: 8 October 2026. This section records subsequent results on unchanged application/evaluation source. It supersedes earlier pending descriptions for the specific checks below and preserves every failed attempt. Final M3 package acceptance remains pending documentation review.

## Complete saved evaluation

A separately recorded producer invocation completed all 180 planned runs: 30 authored cases, two deterministic providers and three passes. The application produced its graded schema-2 report, but that invocation's private measurement wrapper subsequently failed. Successful saved artifacts and a failed measurement wrapper are separate outcomes. Main later independently reverified the entire saved evaluation, with no new producers.

Primary results use 30 cases per provider. Repeats are excluded from these quality denominators:

| Primary metric | Scripted | Keyword baseline |
| --- | ---: | ---: |
| Exact cases | 30/30 | 16/30 |
| Correct rule outcomes | 90/90 | 76/90 |
| Correct obligation atoms | 210/210 | 168/210 |
| Required source-span recall | 98/98 | 86/98 |
| Literal emitted source citations | 98/98 | 86/86 |
| Positive-atom precision | 24/24 | 9/9 |
| Positive-atom recall | 24/24 | 9/24 |
| Missing-atom recall | 12/12 | 0/12 |
| Mandatory handoffs preserved | 8/8 | 8/8 |
| Exact preview documents | 41/41 | 33/41 |
| Exact required reviewed documents | 28/28 | 9/28 |
| Unnecessary handoffs on 22 approvable cases | 0/22 | 13/22 |
| Unrelated violating bytes | 0 | 0 |

The paired primary outcomes are 14 scripted-only successes, 16 both-exact ties, zero keyword-only successes and zero neither-exact cases. An exact case includes the required domain status: all eight mandatory handoffs count as correct outcomes without an approved export. A 30/30 result therefore does not mean 30 automatically completed contracts. Scripted approval/export matches the 22 cases requiring simulated review; reviewer actions are fictional local CLI decisions.

Raw integrity and operational success passed for **180/180 planned runs** across both providers and all repetitions. Normalized repeat equality passed **120/120 comparisons**, two fresh repeats for each of the 60 primary provider/case outcomes. These are separate gates; repeated bytes alone do not prove SQLite integrity, and repeats do not add independent legal examples. All 12 declared release gates passed without changing labels, thresholds or denominators. Baseline task quality remains ungated.

Main ran the documented verify-only route against saved outputs, exit 0. The actual selected interpreter used `-E -s -m evaluation --verify-only --out work/m3-evaluation-v2`; the evaluation command measured 2.781 seconds and its wrapper including before/after hashes measured 2.953 seconds. All 1,893 saved files remained unchanged, and no new producer ran. A separate main parser, importing no repository actor/scorer code, checked all 180 SQLite/domain artifacts with 2,592 explicit conditions and 552 literal source citations, including exact edit preimages, preview/export bytes, approval decisions, original preservation and 120 repeat fingerprints. That parser passed in 0.281 seconds. Its checks corroborate the repository oracle; they are not new contracts or a second live-model benchmark.

The original saved report file SHA-256 is `b9d0720a0876050fa5f4a9ba28246871e98579618082e552d79f5739dc9944b9`. The canonical 1,893-file entry digest is `485220c8d3679f1336dac63385ebb40b09adb40adcbbe853f489fbc6688dedce`. Application/evaluation Python identity is `e540e8a4cd62bbc4cd2f06fcc0b57c0144bbef6b5c3c4ea3ca2264f15823028c`. All 115 frozen files still match entry digest `efd5dd3d38583f0aec2d41bf9c209c0c48d37ef73e55679c1ee647b06035cdaf`. The freeze's original `scored: false` and pending-review fields remain historical metadata; later results are recorded here rather than rewriting the freeze.

## Independent public application checks

Main copied the 215 public files to a relocated directory and independently ran 14 commands with all expected exits. The public-tree digest at that point was `9cb6d59bd181dc2b9032bbc8e9fd85413a87a5c65111ad0cfeadc93fa1866c02`; only the final documentation changes follow it. The application check covered:

- Repository and frozen-input static checks.
- 147 passing test methods: 28 M1, 101 component, 11 fake-provider HTTP and seven recovery methods.
- M1 development regression, 345 assertions, and M2 development regression, 2,141 assertions.
- README direct/compliant/conflict demos, explicit approval, identical repeated approval, exact gold export bytes and refused handoff approval.

The independent harness passed 259 explicit checks in 83.953 seconds. Nested regression assertions, harness checks and test methods are distinct counts. One fake HTTP test emitted a connection-reset server diagnostic during its controlled transport exchanges; that suite still reported all 11 methods OK and exit 0. No real Ollama server/model or external model endpoint was used. Native peak RAM was not measured in this main application slice or the main saved-verification slice; no zero or bound is inferred.

These successful independent checks supply the missing public acceptance coverage. They do not relabel the worker's interrupted `all` command as successful or manufacture a terminal worker acceptance receipt.

## Preserved worker measurement failures

| Attempt | Preserved outcome |
| --- | --- |
| Initial paired producer | Transient SQLite-journal sampling failure; 70 produced, one unfinished, 109 unattempted of 180. No grading. All 741 partial files retained. Exact command time/peak RAM remain unknown; the conservative cumulative active upper bound is 53.592 seconds. |
| Later paired producer with wrapper v2 | All 180 producers and gold grading completed; 1,893 saved files and the passing report retained. Wrapper failed on an image-query WinError 5. Its sampling omitted the actual interpreter, so full RAM/Python-process coverage and the application root exit remain unknown. |
| Application acceptance with wrapper v3 | Wrapper failed on PID 13660 image-query WinError 5 with immediate same-handle wait 258; no later wait exists. Only the repository checker completed. Actual partial unittest methods remain unknown. Root interval 2.265 seconds; 34 durable samples. |
| Application acceptance with wrapper v4 | Wrapper exit 1 after 67.563 measured root seconds. All 147 units and M1/345 assertions completed, but M2 and saved regrade did not. Cached PID 11144 changed creation identity; 851 durable samples and six completed inner command receipts retained. |

The v4 comparison recorded expected creation FILETIME `134359546562366301` and new creation FILETIME `134359546983901520`. The new retained handle was positively in the owned job; the historical PID cache rejected the generation change. Cleanup left no owned job PIDs, had no secondary/cleanup errors and closed job/thread/process handles. This is a private measurement failure, with no public application defect identified by the independent checks. The original error, partial M2 files, source snapshots and all earlier failed receipts remain archived. The successful v4 samples reached 131,207,168 aggregate bytes and four Python processes; the failed frame was not replaced by zero. This is sampled coverage, not an exact lifetime peak.

Separate bounded private monitor controls passed before v4 acceptance: an expected injected-failure ownership/cleanup control and a finite 20-child normal-exit control. The latter recorded 20 child exits, 16 children in periodic telemetry, 301 samples, one bounded delayed same-handle exit confirmation and three immediate confirmations. Those controls do not repair old failed receipts, prove the original WinError 5 cause or add application test methods. Historical unknown timing/RAM fields remain unknown. Private monitoring helpers are excluded from shipped source.

All historical failures, both native controls and the complete saved evaluation remain independently hashable under ignored local work artifacts. No application, actor, baseline, oracle, test, fixture, label, policy, expected bytes or gate changed after exposure. This closeout changes documentation only; it executes just the two static repository/frozen-input checks, with no additional full suite, native job, producer or regrade.

## Practical limits and remaining review

This is an inspectable same-author synthetic/template comparison of scripted policies. The corpus is label-exposed, narrow and not lawyer-certified or unseen independent data. Exact spans and gold bytes measure the authored contract, not legal entailment or alternative valid drafting. ToolRegistry restrictions are in-process tool separation, not an OS sandbox. Required handoffs still need human work; simulated local reviewer labels are not authenticated identity.

Final M3 package acceptance is pending the documentation review. Hosted CI, Linux/macOS runtime, real Ollama inference, legal quality, production adoption/business impact, publication and deployment remain unexecuted or unmeasured. Code and fictional data retain the existing MIT/data/dependency notices. Generated evidence is retained locally and is not part of the shipped source tree; the standalone README commands create a user's own local outputs without any internal lease or coordinator dependency.

## Public source release — 9 October 2026

All three local MVP milestones passed independent acceptance on 8 October 2026, including final documentation review. The review was executed separately from the implementation worker and included documented quickstarts, meaningful success/failure tests and direct domain-state checks. The results and limitations above remain unchanged.

This source release includes application code, authored fixtures, evaluator/tests, quickstart, architecture, license/attribution and the prepared CI workflow. Private orchestration records, machine-specific paths, runtime caches and generated local runs are excluded. Offline scripted/rule/replay outcomes and local provider doubles do not establish live model quality, employer adoption or production impact. Hosted CI results are available in this repository's Actions tab after publication; historical local reports retain their original execution dates.

# Version and exposure record

Record date: 8 October 2026. Main accepted corrected runner v2 before production. The initial measurement failure retains 70 produced records, one unfinished attempt and 109 unattempted identities. A later complete 180-run evaluation was graded and independently verified; current results and all intervening failures are recorded in [evidence](../EVIDENCE.md#m3-current-results-and-independent-checks). Source identities are hashes of exact bytes, not claims of Git commits. Ignored archives and raw attempts are retained locally for review; their personal absolute paths are excluded from shipped files.

## Accepted M2 before M3 changes

M2 integration used public-tree digest `c0a698a3ff943a5bf62b86db829388e6d388ef642d094ae763869ca82320b8b3`; documentation-only handoff changes produced `be9431a722c9db27704dc91376b95e92bc5bf61a89e8068486a17790d1b14480`. Main independently accepted M2. Before adding M3 dispatch/source, the following originals were copied into `work/m3-prechange-m2/` and versioned in its archive manifest:

| Original | SHA-256 |
| --- | --- |
| service.py | `761ca910c5cbef955db4d51cbcbfeb9d3042822b72098291e998bf1ff28b4abb` |
| actor CLI | `f44bb8bf009b444858e966d636cb6320932d8bf8ae5c06d3e91f8e0707df08fc` |
| M2 development verifier | `97e63669cf4511c5e0d990b8a729a4972a124ad7d22ab074f4f004ba510bf604` |
| M1 acceptance CLI | `2273f20e757f11410d3af4c0051f69e692e7e9bc3b6295d3b83f5e246bf66abd` |

M3 adds a keyword provider branch and CLI choice. The scripted protocol remains `m2-v1`; its grammar, tools, journal, patch guards, provider adapter and reviewer logic remain unchanged. New keyword runs use protocol `keyword-v1`, avoiding silent resume across provider changes. The acceptance CLI adds M2/all dispatch around the unchanged M1 body.

## M3 source versions before scoring

| Component | Declared version | Reason |
| --- | --- | --- |
| Keyword baseline | `keyword-v1` | Fixed direct keyword/number scan through shared guards; no reference investigation or absence inference |
| Paired runner | `paired-evaluation-v2` | Immutable full attempt plan, durable incremental/partial evidence and all-repetition raw safety; primary quality denominators unchanged |
| Independent oracle | `outcome-oracle-v1.1` | Pre-score source review strengthened raw reference inventory, bounded/trusted insertion, observed rule/receipt guards and required-export completion |

Initial `outcome-oracle-v1` and its supporting source were preserved in `work/m3-oracle-v1-before-hardening/` after 31 pure unit methods passed. Its verifier SHA-256 is `32a73cd1539acbf33af300877b9c1d33092e209f1cd2f6469dfc303e08799112`. No held-out score informed v1.1. Per-rule reporting and the frozen rubric's allowance for extra genuine quotes on uncertain findings were made explicit before scoring.

Pure-unit attempt 003 then found four setup errors in a new empty-clause fixture: the ordinary notice-substring branch ran before the insertion branch. The failing test source and full raw receipt were preserved. Only that factory condition was fixed; the oracle and 115 frozen files were unchanged by that repair. Later actual checks are recorded in [EVIDENCE.md](../EVIDENCE.md). Failed attempts are never erased or presented as successful runs.

The static source checker initially self-matched its own literal path-prefix pattern. Its failed receipt and source were retained before composing the same regex from split literals; the intended personal-path detection was not relaxed. This hygiene correction involved no actor, oracle, gold or outcome run.

Final pre-score read-boundary review preserved the preceding v1.1 oracle in work/m3-oracle-v11-before-read-boundary-review/ before adding explicit regular trace/directory checks and a bounded 2 MiB persisted checkpoint decoder. This belongs to the same pre-review v1.1 source slice; no score or producer run informed it.

## Main review and narrow v2 harness correction

Main's 14:07 source review reproduced C-M3-01 (completed producer metadata lost on interruption) and C-M3-02 (secondary scripted raw integrity failure could pass while normalized results matched). The exact 215-file candidate was preserved under work/m3-before-main-corrections/, including source provenance, worker handoff/status and main's failure evidence. Candidate public-tree digest: `e0e85c07444dab4d1bcb7fcecbabb200ad880f1014001159333d2451949e2de4`; Python identity: `e22691f8a5c542bd87af6023e77d43d0b6eb1a3c036d1ffaf2f34b6c3644bacf`; old runner hash: `8cca0c319f812283a68963995dd436a4b479fa7ce1bcdf81d45db61da46169c2`.

`paired-evaluation-v2` and evaluation report schema 2 add an immutable 180-attempt plan, exclusive-create flushed/fsynced start/result receipts, sanitized bounded failure diagnostics, persistent partial accounting, and safety checks across every planned repetition/provider. Partial/missing/duplicate/unplanned sets cannot be accepted or shrink quality denominators. Producer plan/receipts are frozen before gold grading and checked against reported records on regrade. Primary scripted thresholds and ungated baseline task accuracy are unchanged.

The worker independently reproduced both old failures with in-process doubles before correction and retained the failing 46-method regression run. The corrected 59-method pure suite and final retained probes pass; no actual actor, HTTP/SQLite workflow or held-out source/score informed the revision. Only runner/CLI harness, pure tests and relevant docs change from the reviewed candidate. Actor, baseline, oracle, corpus, policy, labels, expected edits/bytes and primary thresholds are preserved.

## First leased attempt and instrumentation failure

Main accepted public tree `0d8dcd355560e2a6fcc31b1c0011450f166d0d67063beaa896961ae1575f1fc0` and Python identity `e540e8a4cd62bbc4cd2f06fcc0b57c0144bbef6b5c3c4ea3ca2264f15823028c`, independently passing the 59-method suite, static checks and 349 conditions across all 30 rubric cases. The new worker-owned M3 lease authorized only the three declared commands.

The source checker passed. The paired producer command began, but ignored instrumentation-v1 reused a disk sampler that enumerated a temporary SQLite journal and then failed when that file vanished before stat. The wrapper exception also bypassed its cleanup/result write. The worker verified and stopped only the owned command tree, retained all original outputs and reconstructed incomplete accounting without grading. The third command was not run. Failed measurement source and its dependency are preserved at work/m3-instrumentation-failure-v1/; original error and cleanup evidence are under work/m3-integration-receipts/command-02/. No measurement correction or producer retry was made. Application, actor, baseline, oracle, labels, gold, corpus and thresholds remain byte-identical; only final reporting documentation changes after this failed attempt.

The source-ready handoff inventories the full public tree and separately records the Python source identity used by evaluation. The driver embeds the Python identity and accepted freeze in every evaluation report; documentation/CI hashes are separately checkpointed. Any later code/oracle change requires a new version/exposure note, preservation of old output and a fresh evaluation; old scores cannot be claimed for new bytes. The accepted rubric, labels, gold document bytes and thresholds remain frozen.

## Subsequent results and documentation closeout

The scored saved evaluation uses unchanged scripted `m2-v1`, baseline `keyword-v1`, oracle `outcome-oracle-v1.1`, runner `paired-evaluation-v2` and report schema 2. Python-source identity remains `e540e8a4cd62bbc4cd2f06fcc0b57c0144bbef6b5c3c4ea3ca2264f15823028c`; frozen 115-entry identity remains `efd5dd3d38583f0aec2d41bf9c209c0c48d37ef73e55679c1ee647b06035cdaf`. No actor, scorer, test, policy, label, expected-byte or release-threshold change followed score exposure.

The complete saved directory contains 180 runs and 1,893 immutable files, canonical entry digest `485220c8d3679f1336dac63385ebb40b09adb40adcbbe853f489fbc6688dedce`. Its original report file SHA-256 is `b9d0720a0876050fa5f4a9ba28246871e98579618082e552d79f5739dc9944b9`. Independent saved verification and a separate raw SQLite/domain parser confirmed the recorded results without producing new cases. Main separately exercised the unchanged public application from a relocated 215-file copy. Successful main checks are distinct from failed worker measurement attempts.

Final synchronization changes only README, EVIDENCE and the evaluation, versions and limitations documents. The pre-documentation public-tree identity is `9cb6d59bd181dc2b9032bbc8e9fd85413a87a5c65111ad0cfeadc93fa1866c02`. Before/after public inventories and document hashes are retained separately; the Python and frozen identities above remain unchanged. No model, dependency, hosted CI, publication or deployment occurred. Final package acceptance is pending the documentation review.

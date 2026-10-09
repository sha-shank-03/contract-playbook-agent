# Authored outcome evaluation

Current results, 8 October 2026: the complete saved evaluation has 30/30 exact scripted cases and 16/30 exact keyword cases, with 14 scripted-only successes and 16 ties. Integrity and operational checks passed for all 180 runs; all 120 normalized repeat comparisons matched. Main independently verified the saved evaluation and separately passed all 147 application tests, both development regressions and quickstart approval/handoff checks. Earlier worker measurement failures remain failed, including the original 70-produced/one-unfinished/109-unattempted directory. Final package acceptance awaits documentation review; hosted CI remains unexecuted. See [current evidence](../EVIDENCE.md#m3-current-results-and-independent-checks).

The 12 development cases and 30 additional frozen cases were authored by the same developer with AI assistance. They share narrow canonical sentences. The frozen cases check structural variants of a fictional commercial playbook, not blind legal accuracy, expert annotation, live model quality or performance on diverse contracts. The author has seen the labels while constructing the corpus and oracle. Freezing controls later change; it does not remove that exposure.

## Corpus and immutable identity

The accepted [rubric](../evaluation/RUBRIC.md), labels, expected document bytes, source inputs and buyer-v2 playbook are covered by 115 immutable file entries. The freeze retains its original `scored: false` and review-pending historical fields. Later review and run status belong in evidence; the freeze is never rewritten to update them.

| Identity | SHA-256 |
| --- | --- |
| Freeze file | `8ae16854230fd754760c38a205f698857fdbdb3f75e0da92ee16cd9daac3b666` |
| Canonical 115-entry manifest | `efd5dd3d38583f0aec2d41bf9c209c0c48d37ef73e55679c1ee647b06035cdaf` |

H01-H06 cover direct boundaries; H07-H12 omitted obligations and insertion anchors; H13-H18 reference topology; H19-H24 amendment precedence, conflict and invalid targets; H25-H30 source injection, Unicode/CRLF, number distractors and unsupported timing. Each family has six cases. Static arithmetic over frozen labels gives the following denominators **per provider, for the primary pass**. These are corpus counts, not results.

| Required outcome | Count |
| --- | ---: |
| Cases / rule outcomes / obligation atoms | 30 / 90 / 210 |
| Unique required source spans, including links | 98 |
| Primary clause spans / reference or replacement spans | 80 / 18 |
| Source and preview documents | 41 |
| Mandatory handoff cases | 8 |
| Cases requiring simulated approval / required reviewed documents | 22 / 28 |
| Positive atoms: deviation / missing | 24: 12 / 12 |
| Localized gold patches / protected original intervals | 17 / 58 |

Each of REN-01, TERM-01 and PAY-01 has 30 outcomes. Their atom denominators are 30, 90 and 90; their required-span denominators are 30, 30 and 38. Every reported fraction includes a numerator, denominator and ratio. A zero denominator has a null ratio, never a fabricated perfect score. Emitted citation/claim denominators depend on actual output and are reported separately.

## Fixed comparison and source separation

The scripted actor uses protocol `m2-v1`: bounded iterative reference following, explicit amendment investigation and full coverage before absence claims. `KeywordBaseline` version `keyword-v1` performs one fixed complete paginated scan, reads/searches the same three rules and matches direct topic, keyword and day phrases. It selects no reference-resolution action and infers no missing atoms or insertions. Host-reported conflicts are retained; unsupported amendment/reference meaning yields uncertainty. It can still correct direct numeric/renewal phrases through the shared guards.

Both providers use the same input manifest, playbook, ToolRegistry, budget, proposal schema, SQLite journal, validators and separate reviewer gate. The baseline cannot export directly or bypass a known conflict/unknown source. Its limitations remain visible as missed outcomes or unnecessary handoffs. Baseline superiority is not a release condition; paired wins, ties, losses and failures are reported together. Both policies are deterministic; no LLM improvement is measured.

The acting registry exposes only manifest-listed source documents and trusted rules. It offers no filesystem, shell, network, approval or label-reading tool. AST checks reject production imports of evaluation code. The orchestrating evaluator and actor are Python code in the same OS process; this is tool-access separation, not an OS sandbox or protection from a malicious repository owner.

## Produce, freeze, independently grade

The command below performs one primary pass plus **two fresh repeat passes**. Each pass runs both providers on all 30 cases: 180 producer runs total. It simulates explicit review only for actual PENDING_REVIEW packets. Runner `paired-evaluation-v2` persists `execution-plan.json` with all 180 identities, source/freeze hashes and fixed denominators before the first producer. Each attempt gets exclusive-create, flushed/fsynced start and result receipts. Results survive incrementally; they are not held only in memory until the last case.

Caught producer errors retain a bounded sanitized diagnostic and are counted as operational failures. Interruption or a fatal harness error retains `partial.json`, completed/failed/interrupted/unfinished/unattempted accounting and all original files. Its status is failed/interrupted, release is false and quality metrics are null; declared 30-case/90-rule/210-atom primary denominators do not shrink. A start receipt without a result is unfinished. Regrading rejects partial, missing, duplicate or unplanned attempt sets. Existing directories and immutable receipt files cannot be overwritten. Diagnostics remove controls, paths/URLs and recognizable secret values, with messages bounded to 512 UTF-8 bytes; this is a specific sanitization contract, not a general secret audit.

All completed producer files, the plan and incremental receipts are SHA-256 inventoried before the driver decodes gold labels for grading. The driver also logs start/completion/incomplete exposure records under ignored `work/`. Python identity covers actor, evaluation, scripts and tests; documentation and CI belong to the separate full public-tree source checkpoint. Local flush/fsync is exercised with pure filesystem doubles; no OS power-loss or distributed durability claim is made. If the filesystem refuses evidence writes, the command retains earlier files, reports a sanitized recording error and fails. Interrupted partial directories remain intact; another producer invocation requires a new output directory.

The independent oracle imports no production materializer, parser, controller, registry or store. It reads JSON, immutable source snapshots, SQLite actions/checkpoints/decisions/drafts and raw exported files. It independently indexes sections, validates exact source/policy quotations, reconstructs patch bytes and compares against separately authored gold bytes. It checks full coverage, literal reference inventory, required reads, known conflict/unknown guards, bounded patches, trusted insertions, proposal digest and all-or-none review/export. Original inputs are rehashed after production against the freeze. A self-reported status is insufficient.

An exact case requires correct dispositions and all atoms, required gold evidence, correct localized patches and domain status, correct preview bytes for every source, required reviewed exports, intact protected bytes and valid persisted evidence. A correct pending proposal without required approval/export is incomplete. Honest HANDOFF is structurally valid but misses the outcome when gold requires a correction. No export is allowed for a required handoff.

Quote fidelity tests whether an emitted quote literally matches its versioned source span and read block. Gold support and clause precision/recall test unique exact span tuples associated with the correct rule. They do not infer legal entailment. Duplicates do not inflate unique support counts. Link spans are excluded from primary clause metrics. Finite labels can reject a reasonable alternative span/edit; no fuzzy match or hidden equivalence is used. As the frozen rubric specifies, an uncertain finding may add genuine source quotes beyond required ones; those extras still reduce finite gold-overlap precision and are not treated as proven semantic support.

Positive detection metrics count deviation/missing **atoms**, with TP/FP/FN and separate missed/unsupported missing-atom totals. Patch correctness and exact cases distinguish the two positive statuses. Source/preview preservation and required reviewed-document preservation are separate fractions; changed unrelated bytes are counted across both actual previews and reviewed copies. Required reviewed-document denominators come from gold, so abstaining does not shrink them. Reports include primary aggregates, per-case errors, each family and each rule.

Repeatability compares 120 fresh provider/case outcomes against their corresponding primary outcome. Its normalized hash includes packet, observed trace, usage counters, preview/reviewed hashes and decision receipt. It excludes elapsed runtime and the decision timestamp. Normalized equality does not attest to raw SQLite state. Separate integrity and operational gates cover **every one of the 180 planned runs**, including all secondary scripted and baseline repetitions; complete unique key coverage is required before aggregation. Repeated failures can be deterministic and still fail safety gates. Repeats are not pooled into primary 30-case accuracy or treated as independent legal examples. Baseline task accuracy remains ungated.

## Declared release targets and commands

The fixed scripted primary targets remain at least 27/30 exact cases, at least 0.90 positive-atom precision and recall, all eight mandatory handoffs, perfect emitted source/version and policy quotation fidelity, zero unrelated changed bytes and complete protected-byte preservation. All 180 planned runs must independently have valid raw integrity and zero operational failure; this includes baseline and secondary repetitions. All 120 fresh repeat comparisons must match. Unapproved/stale export negatives and original-preservation checks run in full regression acceptance. Targets are not results and frozen labels or thresholds cannot be changed to pass them.

From the repository root, use a fresh evaluation directory to produce another comparison. Verify-only reads existing artifacts and creates no producer runs:

```powershell
py -3.11 scripts/check_repository.py
py -3.11 -m evaluation --suite heldout --provider scripted --baseline keyword --repetitions 3 --out work/evaluation
py -3.11 -m evaluation --verify-only --out work/evaluation
py -3.11 scripts/acceptance.py --milestone all --evaluation work/evaluation --out work/acceptance
```

`all` explicitly discovers M1, all component, fake HTTP and recovery suites; reruns M1 and M2 CLI acceptance sequentially; then independently regrades the existing 180 raw producer runs and recalculates aggregates/targets. It does not launch a second hidden held-out evaluation. It records each command's complete stdout/stderr/exit in a fresh numbered attempt. Regrading checks immutable plan/attempt receipt identity and accounting, all producer file hashes, every raw assessment, and all-repetition safety before accepting reported aggregates. It rejects partial runs, changed source/freeze/output, missing/duplicate keys or edited metrics. `--milestone m1` and `--milestone m2` remain available separately.

The initial interrupted producer directory remains incomplete and cannot be verified as a successful evaluation. A later separately recorded directory contains all 180 outputs and a graded report; independent verification reads that complete directory. Partial production, complete saved evaluation, failed worker acceptance wrappers and successful independent application checks remain separate evidence. The prepared CI uses standard GitHub-hosted Ubuntu/Windows runners, Python 3.11 and immutable checkout/setup-python commits, with read-only contents permission and serial matrix jobs. It installs no project dependency or model and needs no secret. Hosted execution and any account billing eligibility remain unverified; see [sources](SOURCES.md).

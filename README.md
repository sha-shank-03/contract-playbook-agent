# Contract Playbook Agent

Review authored fictional services agreements against three explicit buyer rules and produce localized, cited proposals for human review.

The default decision provider is **scripted** and works offline. It supports bounded references, explicit amendments, coverage checks for missing obligations, localized edits and persisted recovery. Independent Windows checks on 8 October 2026 passed all 147 application tests, both development CLI regressions and the quickstart's approval, repeat-approval and handoff behavior.

The recorded M3 comparison has **30/30 exact scripted cases versus 16/30 for the fixed keyword baseline**: 14 scripted-only successes and 16 ties. Both providers preserve all eight required human handoffs; those correct handoffs count as exact outcomes, not automatic completion. All 180 saved runs passed integrity and operational checks, and all 120 repeat comparisons matched. These are same-author fictional template cases with deterministic providers; they establish neither general legal accuracy nor live model quality. Separate independent checks verified the saved results after worker measurement failures. Final M3 package acceptance passed independent documentation and release review; see [evidence](EVIDENCE.md#m3-current-results-and-independent-checks).

Python 3.11 and its standard library are sufficient. No installation, account or model is needed for the offline path.

The bounded [U1 upgrade](docs/UPGRADE_U1.md) adds one fictional paraphrase journey using Gateway-native envelopes through explicitly labeled local doubles. Its pure unit checks are recorded separately. Transport and end-to-end acceptance remain unexecuted pending review and an integration lease; live inference and external sandbox integration remain disabled. The historical MVP results below belong to the original published commit.

Run the offline path from the repository root:

```powershell
py -3.11 -m contract_playbook demo --case direct-review --out work/demo
Get-Content -LiteralPath work/demo/review.md
$packet = Get-Content -LiteralPath work/demo/review.json -Raw | ConvertFrom-Json
py -3.11 -m contract_playbook review --run work/demo --decision approve --expected-proposal $packet.proposal_sha256 --reviewer demo-reviewer
Get-Content -LiteralPath work/demo/reviewed/agreement.txt
py -3.11 -m contract_playbook demo --case compliant-review --out work/compliant
```

These commands simulate review of fictional data. Inspect the proposal before approving. Reject with `--decision reject`. Approval checks the exact proposal digest, current originals, manifest and playbook; it exports a separate copy of every supplied document. Repeated approval returns the stored receipt and draft bytes. Originals stay unchanged.

For a local authored input use `run --case-dir <directory> --playbook <json-file> --out <separate-directory>`. The manifest contains one base agreement and at most two supplied A1/A2 amendments. Inputs are strict UTF-8 with numbered `Section N - Title` headings, at most 64 KiB and 48 blocks in total. PDF, DOCX and OCR are outside scope.

M2 development examples:

```powershell
py -3.11 -m contract_playbook demo --case cross-reference --out work/reference
py -3.11 -m contract_playbook demo --case precedence-amendments --out work/amendments
py -3.11 -m contract_playbook demo --case missing-payment --out work/missing
py -3.11 -m contract_playbook demo --case conflicting-amendments --out work/conflict
```

The complete list has 12 cases: direct-review, compliant-review, cross-reference, broken-reference, cycle-reference, explicit-amendment, conflicting-amendments, precedence-amendments, missing-payment, missing-written-notice, missing-attachment and source-injection. Unknown references and competing amendments produce a HANDOFF, with approval disabled. Missing referenced evidence stays unknown rather than becoming an absence finding.

A run contains immutable `review.json`, readable `review.md`, committed observations in `trace.jsonl`, `usage.json`, an inspection diff and unapproved `preview/<document-id>.txt` files. Only a separate approval creates `reviewed/<document-id>.txt`. Later review decisions appear in `review-receipt.json` and SQLite; the proposal's original pending status does not change.

Incomplete investigations require explicit resume and retain their consumed budgets:

```powershell
py -3.11 -m contract_playbook cancel --run work/reference
py -3.11 -m contract_playbook resume --run work/reference
```

Cancellation applies to an incomplete investigation. Resume clears its known cancellation marker after input checks. After an interrupted approval, repeat the exact `review --decision approve` command to finish exporting stored drafts. Use a new output directory for changed inputs, settings or a prior M1 run created before the M2 protocol.

Pure component and static integrity checks:

```powershell
py -3.11 -m unittest discover -s tests/components -p test_m2_*.py
py -3.11 -m unittest discover -s tests/components -p test_m3_*.py
py -3.11 scripts/check_frozen_inputs.py
py -3.11 scripts/check_repository.py
```

Integration commands exercised against the reviewed M2 source:

```powershell
py -3.11 -m unittest discover -s tests -p test_m1_*.py
py -3.11 scripts/acceptance.py --milestone m1 --out work/m2-m1-regression
py -3.11 scripts/acceptance_m2.py --out work/m2-acceptance
py -3.11 -m unittest discover -s tests/provider_contract -p test_*.py
py -3.11 -m unittest discover -s tests/recovery -p test_*.py
```

The development acceptance runner launches the actual CLI sequentially and compares all three rule outcomes, obligation atoms, required quotes, exact edits, reviewed document bytes and untouched intervals against independent authored labels. It checks handoff approval refusal and deliberately changes unrelated fee text to challenge the verifier. The HTTP harness uses a local fake server and owned transport workers. Its responses emulate native tool calls; they are not live model evidence.

Thirty additional authored cases and labels are frozen in `evaluation/HELDOUT_FREEZE.json`. The [rubric](evaluation/RUBRIC.md) and sample gold were independently reviewed before evaluation; all 115 frozen files remain unchanged. The primary pass has 30 cases, 90 rule outcomes, 210 obligation atoms, 98 required source spans and eight mandatory handoffs per provider. The scripted run matched all 90 rule outcomes, 210 atoms and 98 required spans. Repeats are measured separately and do not add independent contracts to the 30-case quality denominator.

To reproduce the offline comparison, choose a fresh evaluation output directory, then verify its saved artifacts and run acceptance:

```powershell
py -3.11 -m evaluation --suite heldout --provider scripted --baseline keyword --repetitions 3 --out work/evaluation
py -3.11 -m evaluation --verify-only --out work/evaluation
py -3.11 scripts/acceptance.py --milestone all --evaluation work/evaluation --out work/acceptance
```

The evaluation uses one primary pass and two fresh repeats for both providers. Runner v2 persists an immutable 180-attempt plan and flushed start/result receipts before gold grading. Interruptions retain completed records, diagnostics and attempted/unattempted accounting; partial evidence cannot count as success. Complete runs freeze all producer/receipt files, then report primary 30-case quality denominators, paired failures/ties/losses, family/rule breakdowns and 120 repeat comparisons. Raw integrity and operational safety must pass for all 180 runs across every repetition. `all` reruns each explicit test suite and M1/M2 CLI regression, then independently regrades those existing raw outputs; it creates no hidden held-out runs. Use a fresh evaluation directory for another producer invocation. The fixed keyword baseline has the same tools, guards and reviewer gate; it does not follow references or infer absence. See [evaluation methodology](docs/EVALUATION.md) and [versions/exposure](docs/VERSIONS.md).

The prepared `.github/workflows/ci.yml` uses immutable action commits and serial standard Ubuntu/Windows jobs with Python 3.11, no project dependencies, models or secrets. Hosted CI, Linux/macOS runtime checks, publication and deployment remain unexecuted.

The optional native adapter requires a separately supplied local Ollama server and explicit model; this repository does not install, pull or start either. This opt-in route remains unexecuted:

```powershell
py -3.11 -m contract_playbook run --case-dir fixtures/dev/direct-review --playbook fixtures/playbooks/buyer-services-v1.json --out work/opt-in-model --provider ollama --endpoint http://127.0.0.1:11434/api/chat --model YOUR_EXPLICIT_LOCAL_MODEL
```

Only an explicit HTTP loopback address is accepted, with redirects and proxies disabled. The adapter serializes native tool-call/observation history and validates exactly one allowlisted action. Its live-route flag describes adapter execution; fake-server results and observed usage counters do not establish model quality. Missing usage remains unknown. See [architecture](docs/ARCHITECTURE.md), [limitations](docs/LIMITATIONS.md) and [evidence](EVIDENCE.md).

The contribution is a small inspectable investigation/edit contract with external guards and independently authored final-state checks. Source code and fictional data use the MIT license; see [attribution](THIRD_PARTY_NOTICES.md). On another platform replace `py -3.11` with an explicitly configured Python 3.11 interpreter.


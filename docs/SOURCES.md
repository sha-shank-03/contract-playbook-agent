# Sources and design attribution

Primary sources checked on 8 October 2026. They support the API/runtime contracts and research context below. They do not validate fictional legal rules, our architecture choices, authored outcomes or future scores. No external contract dataset, source excerpt, model or third-party runtime package is bundled.

| Source | Use and limit |
| --- | --- |
| [Harvey Agents role](https://jobs.ashbyhq.com/harvey/672f45e7-0689-4a6a-92e4-712beaa2eeca), checked against the employer's [Ashby board API](https://api.ashbyhq.com/posting-api/job-board/harvey?includeCompensation=true) | Dated context for playbook, retrieval/editing, tools and practical evaluation work; no endorsement or employment claim |
| [The Atticus Project: CUAD](https://www.atticusprojectai.org/cuad/) | Prior art for clause annotation; publisher identifies CC BY 4.0 data; no dataset used |
| [Stanford NLP: ContractNLI](https://stanfordnlp.github.io/contract-nli/) | Prior art for evidence-linked outcomes; no dataset used or score comparison made |
| [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling) and [chat API](https://docs.ollama.com/api/chat) | Native function schemas, assistant/tool history and observed usage fields; only fake-server conformance exercised |
| [Ollama license](https://github.com/ollama/ollama/blob/main/LICENSE) | External server licensing context; neither server nor model bundled; model licenses are separate |
| [Python 3.11.9 release](https://www.python.org/downloads/release/python-3119/) | Existing local interpreter version; no interpreter installed by this project |
| [Python sqlite3](https://docs.python.org/3.11/library/sqlite3.html) | Local transaction and read-only connection APIs; no distributed/power-loss guarantee inferred |
| [Python urllib.request](https://docs.python.org/3.11/library/urllib.request.html) | HTTP request, proxy handler and redirect handler APIs |
| [Python license](https://docs.python.org/3.11/license.html) and [SQLite copyright](https://www.sqlite.org/copyright.html) | Attribution for existing runtime components; no binaries redistributed |
| [checkout v7.0.0](https://github.com/actions/checkout/releases/tag/v7.0.0), [exact commit](https://github.com/actions/checkout/commit/9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0) | Immutable prepared workflow pin `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` |
| [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0), [exact commit](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97) | Immutable prepared workflow pin `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) and [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) | Prepared standard runners; public-repository standard usage can be free under GitHub's terms. No hosted run or account eligibility verified |

The actor, independent verifier and fictional data are project-authored with AI assistance. Three fictional commercial preferences, exact patch/gold-byte matching, a fixed keyword baseline and deterministic repeats are design choices. The project makes no legal-quality, production adoption, human time-saved or employer-equivalence claim. Licenses and bundling boundaries are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

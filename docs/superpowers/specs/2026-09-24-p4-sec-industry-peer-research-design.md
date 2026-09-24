# P4 SEC industry and peer research

## 中文摘要

P4 首版用美国 SEC 的公开申报构建一个**可追溯、可重放的上市比特币矿企样本研究**。固定 MARA Holdings 与 Riot Platforms 的 2025 财年 10-K，分别产生样本行业概览和同行比较 Markdown 报告，由现有 QuantAgent 结果 API 读取。报告逐项引用 CIK、申报编号、财务期间、单位与来源；缺失或口径冲突必须显示，不能补猜。OpenStock 专用页面等待 P3 前端发布验收后接入；P5 不在本工作中启动。

Date: 2026-09-24. This design implements the three P4 increments in `QuantAgent_项目方案_V1.2.md` as one small, testable research workflow. It does not make investment recommendations, train a model, run P5 agents, or deploy a public service.

## User intent and acceptance

The user selected U.S. listed bitcoin miners as the first industry/peer sample and approved an initial result made of a source-traceable report plus the existing read-only Result API. A dedicated OpenStock page follows P3 frontend acceptance. P4 is complete for this first slice when a live, authorized read of SEC data yields one run with a verifiable sector section and peer section, a matching offline replay, explicit negative cases, and unchanged legacy recipes/read API behavior. The two-company cohort is **a sample of public issuers**, not a measure of the entire mining industry.

## Source decision

Use the official SEC `data.sec.gov` Submissions and Company Facts JSON APIs, with immutable accession selection. This is preferable to manually copied spreadsheet values, which lose ingestion evidence, and to an unlicensed commercial feed, whose permitted use and accounting semantics are unknown. SEC says its EDGAR public filing content is free to access and reuse; automated access must declare a real project contact and respect fair access. The contact is supplied at runtime through `SEC_USER_AGENT`, used only in the HTTP header, and never written into Git, packets, run metadata, reports, errors, or test snapshots.

Primary source references:

- API contract and XBRL limitations: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Public content reuse: https://www.sec.gov/about/webmaster-frequently-asked-questions
- Declared bot identity and fair access: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- MARA 2025 10-K, accession `0001507605-26-000007`, accepted `2026-03-02T21:49:11Z`, CIK `0001507605`: https://www.sec.gov/Archives/edgar/data/1507605/000150760526000007/0001507605-26-000007-index.htm
- Riot 2025 10-K, accession `0001104659-26-022322`, accepted `2026-03-02T22:05:32Z`, CIK `0001167419`: https://www.sec.gov/Archives/edgar/data/1167419/000110465926022322/0001104659-26-022322-index.html
- CleanSpark 2025 10-K, fiscal year ended `2025-09-30`, is a deliberate period-mismatch negative case rather than a peer row: https://www.sec.gov/Archives/edgar/data/827876/000119312525297510/0001193125-25-297510-index.htm

The SEC API publishes standardized non-custom taxonomy facts applying to the whole filing entity. It excludes many issuer-specific operational metrics. No hashrate, electricity cost, bitcoin produced, or AI/HPC revenue is inferred from a generic GAAP fact. Human-readable filing narrative may be cited as clearly attributed context, but no full filing body is copied into packets or reports.

## Fixed cohort and metric semantics

The v1 cohort is MARA and Riot, each with fiscal year `2025-01-01` through `2025-12-31`, 10-K form, and the exact accession above. CIK and accession are canonical identity; ticker is a display label only and is checked against the Submissions response. The live adapter sets research `as_of` to an aware timestamp immediately after the last successful response retrieval; it does not accept an arbitrary historical cutoff. A live API response can change later, so every run records retrieval time and raw response SHA-256; a replay consumes the frozen selected packet and its `as_of` rather than requesting live data again. Acceptance time is a filing event, while retrieval time is the conservative proof of availability to this run; neither is misnamed the first public availability time.

The first comparison includes only `us-gaap:Revenues` for the full annual duration and `us-gaap:Assets` at the fiscal year end, each in `USD` and linked to the selected accession. Values are integer USD from Company Facts; display conversion to USD millions or billions is explicit and reversible. Both values must be cross-checked against the corresponding 10-K primary financial statements in acceptance evidence. No annualized quarterly value or ticker-based guess is allowed.

The canary revealed why matching taxonomy names alone are insufficient: MARA and Riot expose `ProfitLoss` and `NetIncomeLoss` with different relationships to tax and noncontrolling interests in their 10-K presentation. Net income is excluded from the first numeric peer table until a separately reviewed mapping pins the same economic line for both issuers. MARA also exposes both `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax`; the latter is a narrower subtotal and cannot replace `Revenues` for Riot. The report may explain these omissions as concrete data-quality findings.

## Components and contracts

1. **SEC source adapter.** A curated, opt-in network plugin accepts only the two fixed CIKs and accessions and the two approved concepts. It builds fixed HTTPS URLs on `data.sec.gov`, disallows redirects, caps each response at 8 MiB, enforces a 15-second timeout, and uses at most four requests at no more than one per second for a sample run. It requires `network:https` and an explicit runtime `SEC_USER_AGENT` with contact; offline mode rejects it before run creation. No model output can choose host, CIK, URL, concept, or credential. The adapter reads SEC only; local run artifacts may hold frozen response bytes and their SHA-256 within the allowed run directory.
2. **Normalized `quantagent.sec_company_facts.v1` packet.** This records cohort ID, `as_of`, per-response URL/hash/retrieval timestamp, CIK, ticker, accession, form, filing acceptance timestamp, fiscal start/end, concept, unit, original integer value, and exact source link for each selected fact. A selector joins each fact to its accession in Submissions, requires the filed and accepted times to precede `as_of`, rejects duplicate/conflicting values, and keeps missing reasons distinct from numeric zero. Live `as_of` must also follow retrieval, so a current response cannot be presented as a historical point-in-time snapshot. Unselected API facts do not enter the packet. Existing `DataPacket` hash and time checks protect the frozen packet on replay.
3. **Deterministic sector overview.** A dedicated plugin reads the normalized packet and emits `quantagent.sec_sector_overview.v1`: fixed cohort definition, coverage `2/2` for each admitted metric, two-company sample sums, observations with evidence IDs, and limitations. Its only numeric conclusions are arithmetic over admitted facts. It must say the sums are not industry totals and does not infer upstream events or investment outlook.
4. **Deterministic peer comparison.** A separate plugin consumes the sector packet and emits `quantagent.sec_peer_comparison.v1`: MARA/Riot rows, same-tag/same-period/same-unit values, per-cell evidence IDs and source links, conversion formula, and a visible omission table for unavailable or semantically incompatible metrics. It may compare magnitude without ranking investment quality.
5. **Report and read surface.** A Markdown report plugin consumes the comparison packet and writes one final `quantagent.report.v1` artifact, containing distinct “sector overview” and “peer comparison” sections, provenance links, method, missing data, and limitations. The existing authenticated `GET /api/v1/runs/{run_id}` and `/report` then serve the immutable run; no P4-specific endpoint or OpenStock UI is added in this slice. The existing `run` CLI gains `sec-edgar` and `sec-replay` source choices: live SEC needs no `--input`, replay requires a packet path, and all older sources continue requiring `--input`. The live choice requires explicit `--online` and permissions; it is never the default.

The current `RecipeRunner` is linear. The peer packet must carry forward the sector summary plus the minimal normalized facts it needs; this avoids adding branching/fan-in machinery before P5. Plugin catalog entries and one recipe pin exact versions and contracts. The network source remains `experimental` until the live canary and replay pass; the deterministic transforms can be `verified` only under the repository's existing offline-test policy.

## Failure, trust, and version rules

- SEC `403`, `429`, timeout, oversized body, invalid JSON, unexpected redirect, mismatched CIK/accession/form, missing timestamp, or source hash mismatch produce typed failure and no completed report. Retries are not automatic. A failed run remains in the existing run audit.
- A fact with a missing requested concept, wrong unit, wrong period, duplicate conflicting value, later accession, or acceptance time after `as_of` is not silently used. If one metric is unavailable, the report may complete with an explicit omission and coverage `1/2` or `0/2`; a core identity/timing mismatch aborts the run.
- Each run is append-only. Later SEC response changes create a new response hash and run; they never mutate earlier packets. The frozen selected packet can be replayed offline to reproduce the same report values and evidence references. `accepted_at` is the SEC filing event, `retrieved_at` is this run's observed availability, and fiscal period end is a separate field.
- Display text from SEC is untrusted source material. Report output escapes Markdown control characters; no filing text is interpreted as a command, capability, path, or URL to fetch.
- No secret, private prompt, project contact email, full filing body, or paid data is written to a public repository. Public tests use synthetic API responses and small synthetic finance values.

## Verification and rollout

Start from an isolated worktree at current `origin/main`. The unmodified baseline on 2026-09-24 passed `142` tests with `3` skips in `.quantagent-qa`. Use TDD for source parsing, semantic selection, derived calculations, report rendering, runner integration, and Result API readback.

Acceptance cases include: correct FY2025 MARA/Riot `Revenues` and `Assets` selection; URL/CIK/accession/period/unit/time lineage per numeric cell; exact USD conversion; SEC contact redaction; online permission and offline preflight; missing concept and duplicate-conflict behavior; CleanSpark fiscal mismatch; `as_of` before acceptance; amended filing not silently replacing selected 10-K; source hash tampering; deterministic replay; report API integrity; legacy recipe regressions. The live canary uses the user-supplied SEC contact at runtime, makes only the four allowed requests, compares values with the linked 10-Ks, saves response hashes privately, and reports retrieval time. It does not call a paid model or publish research externally.

After canary and test evidence, report the local commit SHA, exact source accession IDs, response hashes, passing/failed tests, run ID, report path, and limitations. A future OpenStock page can consume the existing report endpoint after P3 frontend acceptance. P5 starts only on a later user request.

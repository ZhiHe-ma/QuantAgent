# P4 SEC Industry and Peer Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one source-traceable MARA/Riot FY2025 SEC sample report through the existing QuantAgent Result API, with an offline replay that reproduces its values and evidence references.

**Architecture:** A fixed-host SEC client downloads four bounded JSON responses. A strict selector turns only the pinned accession, period, unit, and concepts into a hash-addressed packet. Linear recipe steps derive a sample sector overview, peer comparison, and immutable Markdown report; a separate offline source rehydrates that packet. The existing authenticated read API serves the report without a P4-specific endpoint.

**Tech Stack:** Python 3 standard-library `urllib.request`, `zoneinfo`, `json`, `hashlib`, existing `DataPacket`/`RecipeRunner`/FastAPI Result API, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-24-p4-sec-industry-peer-research-design.md`

## Global Constraints

- P4 v1 cohort: MARA CIK `0001507605`, accession `0001507605-26-000007`; Riot CIK `0001167419`, accession `0001104659-26-022322`; both fiscal `2025-01-01` through `2025-12-31`.
- Admitted comparison metrics: annual `us-gaap:Revenues` and year-end `us-gaap:Assets` in integer `USD`. No net-income, operational, investment-quality, or whole-industry claim.
- Live requests use fixed `https://data.sec.gov` Submissions and Company Facts URLs only, at most four requests, at most one per second, timeout 15 seconds, 8 MiB maximum response, no redirect or automatic retry.
- `SEC_USER_AGENT` stays in the request header only; never put it in exceptions, logs, packets, run state, tests, or reports.
- Live needs explicit `--online` and `network:https`; offline replay needs a packet path. All preexisting sources retain mandatory `--input`.
- Research `as_of` is timezone-aware and set after the last successful live retrieval. Accepted, filed, retrieved, and fiscal times remain distinct. Replay keeps the original `as_of`.
- Source provenance and integrity-critical hashes belong in `DataPacket.records`, since the current packet digest covers records but does not cover metadata.
- The report is read through the existing `GET /api/v1/runs/{run_id}` and `/report`; no OpenStock P4 page or P5 work is included.
- No new runtime dependency, paid model, automatic external publication, or public fixture containing real contact details.

## File Structure

- Create `quantagent_platform/sec_client.py`: fixed SEC URL construction, bounded fetch, rate limit, sanitized network failures, raw-byte hashes.
- Create `quantagent_platform/sec_contracts.py`: pinned cohort, strict JSON parsing and SEC selection, normalized packet validation, deterministic fact/evidence identifiers.
- Create `quantagent_platform/sec_analysis.py`: pure sector and peer transforms over the normalized packet.
- Create `quantagent_platform/sec_plugins.py`: live and replay sources, transform adapters, and Markdown report plugin.
- Modify `quantagent_platform/runner.py`: register four new plugin classes plus replay source.
- Modify `quantagent_platform/cli.py`: live/replay source bindings and input/online preflight without changing older source behavior.
- Modify `plugin_catalog/catalog.json`; create `recipes/sec_industry_peers.json`: exact plugin IDs, versions, contracts, permissions.
- Create `tests/test_sec_client.py`, `tests/test_sec_contracts.py`, `tests/test_sec_analysis.py`, `tests/test_sec_workflow.py`: synthetic source and end-to-end cases.
- Create `docs/P4_SEC_RESEARCH_ACCEPTANCE.md`: exact invocation, live canary evidence, 10-K cross-check, test results, limitations. Keep real raw responses under an ignored private run directory.

## Review Focus

1. Submissions `acceptanceDateTime` without a timezone: Task 2 must interpret it using `America/New_York`, including the DST boundary, before comparing with aware `as_of`.
2. A duplicate XBRL row or a later amended accession: Task 2 must reject the former and ignore the latter rather than silently replacing pinned facts.
3. A tampered packet field whose digest is not updated: Task 2 replay must fail before any completed report; all provenance fields used by replay must be in hashed records.
4. SEC text with Markdown controls or an injected URL: Task 4 report must escape displayed text and link only to fixed official SEC hosts.
5. Live CLI invoked without `--input`, or an old source invoked without it: Task 5 must accept the former only with online permission and reject the latter before creating a run.

---

### Task 1: Fixed and Bounded SEC Transport

**Files:**
- Create: `quantagent_platform/sec_client.py`
- Test: `tests/test_sec_client.py`

**Interfaces:**
- Produces: `fetch_sample(user_agent: str, *, opener=None, clock=None, sleeper=None) -> list[SecResponse]`; each frozen `SecResponse` has `kind`, `cik`, `url`, `raw`, `sha256`, `retrieved_at`. `SEC_URLS` fixes the four URLs and request order.
- Consumes: no project code except `PluginError`.

- [ ] **Step 1: Write failing transport tests.** Define a fake opener returning four byte streams with `status=200` and `geturl()` equal to the requested fixed URL; record URLs and `User-Agent`. Assert exactly four fixed `data.sec.gov` URLs, byte hashes, aware monotonically increasing `retrieved_at`, a sleep of at least one second between requests, and that `repr(result)` excludes the supplied contact. Add subtests where the fake returns `302`, `403`, `429`, an 8 MiB plus one byte stream, and a timeout; each must raise `PluginError` with no contact text.

```python
responses = fetch_sample("QuantAgent test-contact@example.invalid", opener=fake, clock=clock, sleeper=sleep)
self.assertEqual(len(responses), 4)
self.assertTrue(all(r.url.startswith("https://data.sec.gov/") for r in responses))
self.assertEqual(responses[0].sha256, hashlib.sha256(responses[0].raw).hexdigest())
self.assertNotIn("test-contact@example.invalid", repr(responses))
```

- [ ] **Step 2: Run the test to see the missing module failure.** `python -m unittest tests.test_sec_client -v`; expected `ModuleNotFoundError: quantagent_platform.sec_client`.
- [ ] **Step 3: Implement the transport.** Use `urllib.request.OpenerDirector` with a redirect handler whose `redirect_request()` returns `None`; hardcode the four paths `/submissions/CIK0001507605.json`, `/api/xbrl/companyfacts/CIK0001507605.json`, and the corresponding two CIK `0001167419` paths. Read at most `8*1024*1024+1` bytes, require `status == 200`, `geturl() == requested_url`, apply `timeout=15`, and compute SHA-256 over the exact bytes. Catch `HTTPError`, `URLError`, `TimeoutError`, invalid response types, and oversize with status-only sanitized `PluginError`. Sleep based on monotonic time to guarantee starts are at least one second apart. Use `datetime.now(timezone.utc).isoformat()` after each full read. Never format the header value in a failure message.

```python
@dataclass(frozen=True, repr=False)
class SecResponse:
    kind: str
    cik: str
    url: str
    raw: bytes
    sha256: str
    retrieved_at: str
```

- [ ] **Step 4: Run transport tests.** `python -m unittest tests.test_sec_client -v`; expected all tests pass.
- [ ] **Step 5: Commit.** Run `git add quantagent_platform/sec_client.py tests/test_sec_client.py`, then `git commit -m "feat: add bounded SEC transport"`.

### Task 2: Strict SEC Selection and Replay Integrity

**Files:**
- Create: `quantagent_platform/sec_contracts.py`
- Test: `tests/test_sec_contracts.py`

**Interfaces:**
- Consumes: `SecResponse` from Task 1 and existing `DataPacket`.
- Produces: `normalize_sample(responses: list[SecResponse]) -> DataPacket`, `validate_sec_packet(packet: DataPacket) -> dict[str, Any]`, and constants `SEC_FACTS_CONTRACT = "quantagent.sec_company_facts.v1"`, `COHORT_ID = "us-listed-bitcoin-miners-fy2025-mara-riot-v1"`.
- Normalized packet has one record: `cohort_id`, `as_of`, `sources` (four URL/hash/retrieval objects), and `companies` (two CIK/ticker/accession/form/accepted/period objects, each with `facts` for selected concepts and `omissions` for absent metrics). Every admitted fact has `evidence_id`, `concept`, `unit`, `period_start` (null for Assets), `period_end`, `value_usd`, `filed_at`, `filing_index_url`, and `companyfacts_url`.

- [ ] **Step 1: Write synthetic selection tests.** Build tiny Submissions and Company Facts JSON responses for both issuers. Include the exact pinned accession, `10-K`, fiscal bounds, `USD`, and a later amended row with a different accession. Assert only pinned `Revenues` and `Assets` values enter the packet, `as_of` follows all retrieval times, and all four source hashes are inside `records[0]`. Add cases: CleanSpark CIK or September year-end, missing Revenues with explicit omission, wrong unit/period, a repeated qualifying fact, conflicting duplicate, later acceptance, naive/wrong `as_of`, and a raw response whose bytes disagree with its declared SHA-256. Test a tampered source hash inside a serialized packet both without a refreshed packet digest (outer integrity) and with one (semantic validation). Use an `America/New_York` acceptance string on a DST change date to assert the UTC conversion.

```python
packet = normalize_sample(synthetic_responses)
self.assertEqual(packet.contract_version, "quantagent.sec_company_facts.v1")
self.assertEqual(packet.records[0]["companies"][0]["facts"]["Revenues"]["unit"], "USD")
tampered = packet.to_dict()
tampered["records"][0]["sources"][0]["sha256"] = "0" * 64
with self.assertRaises(ContractError):
    DataPacket.from_dict(tampered)
```

- [ ] **Step 2: Run the test to see the missing module failure.** `python -m unittest tests.test_sec_contracts -v`; expected `ModuleNotFoundError: quantagent_platform.sec_contracts`.
- [ ] **Step 3: Implement strict parsing and normalization.** Recompute each raw response SHA-256 before parsing. Decode UTF-8 with `json.loads(parse_constant=reject, object_pairs_hook=unique_pairs)`; reject duplicate JSON keys and invalid constants. Locate the pinned accession in `filings.recent` with matching `form`, `reportDate`, and ticker; interpret SEC `acceptanceDateTime` in `ZoneInfo("America/New_York")` when its source value is naive, convert to UTC, and require it before the final aware `as_of`. Require the Company Facts CIK to match; select exactly one matching `units.USD` row per approved concept with matching `accn`, `form`, full fiscal period, and `filed <= as_of`. Treat a missing concept as an omission; reject multiple qualifying rows, wrong core identity, or invalid numeric types. Exclude `ProfitLoss`, `NetIncomeLoss`, and `RevenueFromContractWithCustomerExcludingAssessedTax`. Generate evidence IDs from fixed identity/concept/period components. Construct only official filing index and Company Facts URLs from fixed CIK/accession, not source-supplied URLs. Put all provenance in the single hashed record. Validate the entire semantic record in `validate_sec_packet`, not just its outer digest.

```python
def normalize_sample(responses: list[SecResponse]) -> DataPacket:
    as_of = datetime.now(timezone.utc).isoformat()
    record = select_pinned_facts(responses, as_of=as_of)
    return DataPacket.create(contract_version=SEC_FACTS_CONTRACT,
        packet_type="sec_company_facts", source="builtin.sec-edgar-source",
        records=[record], created_at=as_of)
```

- [ ] **Step 4: Run selection tests.** `python -m unittest tests.test_sec_contracts -v`; expected all tests pass.
- [ ] **Step 5: Commit.** Run `git add quantagent_platform/sec_contracts.py tests/test_sec_contracts.py`, then `git commit -m "feat: normalize pinned SEC facts"`.

### Task 3: Deterministic Sector and Peer Calculations

**Files:**
- Create: `quantagent_platform/sec_analysis.py`
- Test: `tests/test_sec_analysis.py`

**Interfaces:**
- Consumes: validated `quantagent.sec_company_facts.v1` packet from Task 2.
- Produces: `build_sector(packet: DataPacket) -> DataPacket` with `quantagent.sec_sector_overview.v1`; `build_peers(packet: DataPacket) -> DataPacket` with `quantagent.sec_peer_comparison.v1`. The sector record carries `cohort_id`, `as_of`, admitted `companies`, `sources`, `coverage`, `sample_sums_usd`, and limitations. The peer record carries that sector record plus `rows` and `omissions` so the linear runner needs no fan-in.

- [ ] **Step 1: Write failing arithmetic tests.** Feed a two-company normalized packet with Revenues `907093000` and `647435000`, Assets `7286899000` and `3936767000`. Assert two-company sums `1554528000` and `11223666000`, coverage `2/2`, original integer per-cell values and evidence links retained. With one missing Revenues, assert coverage `1/2`, sum clearly labeled sample sum of available issuers, and omission reason carried into peer rows. Assert a zero value remains present, wrong contract fails, and each displayed million value equals `Decimal(value_usd) / Decimal(1000000)` without float rounding.

```python
sector = build_sector(packet)
self.assertEqual(sector.records[0]["sample_sums_usd"]["Revenues"], 1554528000)
peers = build_peers(sector)
self.assertEqual(peers.records[0]["rows"][0]["Revenues"]["value_usd"], 907093000)
```

- [ ] **Step 2: Run the test to see the missing module failure.** `python -m unittest tests.test_sec_analysis -v`; expected `ModuleNotFoundError: quantagent_platform.sec_analysis`.
- [ ] **Step 3: Implement pure transforms.** Call `validate_sec_packet` before deriving; use integer sums and `Decimal` for display conversion. Never calculate rank, outlook, profit, or whole-industry totals. Propagate original evidence IDs/source links and the complete sector record through the peer packet. Record a fixed method/version string and explicit two-issuer limitation in each output record. Refuse malformed input rather than filling from ticker or a later filing.

```python
def build_sector(packet: DataPacket) -> DataPacket:
    record = validate_sec_packet(packet)
    summary = summarize_admitted_facts(record)
    return DataPacket.create(contract_version=SECTOR_CONTRACT,
        packet_type="sec_sector_overview", source="builtin.sec-sector-overview",
        records=[summary], created_at=record["as_of"])
```

- [ ] **Step 4: Run analysis tests.** `python -m unittest tests.test_sec_analysis -v`; expected all tests pass.
- [ ] **Step 5: Commit.** Run `git add quantagent_platform/sec_analysis.py tests/test_sec_analysis.py`, then `git commit -m "feat: derive SEC sample sector and peer facts"`.

### Task 4: Recipe Plugins and Markdown Artifact

**Files:**
- Create: `quantagent_platform/sec_plugins.py`, `recipes/sec_industry_peers.json`
- Modify: `quantagent_platform/runner.py`, `plugin_catalog/catalog.json`
- Test: `tests/test_sec_workflow.py`

**Interfaces:**
- Consumes: `fetch_sample`, `normalize_sample`, `validate_sec_packet`, `build_sector`, `build_peers`, existing `RunContext` and `RecipeRunner`.
- Produces: `SecEdgarSource`, `SecReplaySource` (both capability `source.sec_company_facts`, output `SEC_FACTS_CONTRACT`), `SecSectorOverview`, `SecPeerComparison`, `MarkdownSecResearchReport` (final `quantagent.report.v1`). Source plugins differ only in live/frozen acquisition; both feed the same three downstream steps.

- [ ] **Step 1: Write failing recipe tests.** Assert default registry contains five exact manifest/catalog entries, one recipe preflights offline with replay binding and online with live binding plus `network:https`, and offline live/permission-denied runs fail before a run directory is created. Inject a synthetic `403` transport failure after run creation and assert the run state is `failed` with no completed report or contact leak. Use synthetic packet as replay input to run all four steps and assert report has separate `## Sector overview` and `## Peer comparison` sections, source evidence links, exact fiscal periods/units, missing-data table, and a warning that two issuers are not industry totals. Give a ticker/title containing `` ` | [ ] < > `` and assert escaped output; give an external URL in a synthetic source record and assert report refuses it. Assert final packet `records[0]` contains `path`, `format`, `input_sha256`, `artifact_sha256`.

```python
result = RecipeRunner(default_registry()).run(recipe, params={"source_path": str(packet_path),
    "report_title": "SEC sample"}, output_dir=run_root, allowed_read_roots=[fixture_root],
    bindings={"source.sec_company_facts": "builtin.sec-replay-source"})
self.assertEqual(result.final_packet.contract_version, "quantagent.report.v1")
self.assertIn("## Peer comparison", (result.run_dir / "sec_industry_peers.md").read_text())
```

- [ ] **Step 2: Run the test to confirm missing plugin/recipe failures.** `python -m unittest tests.test_sec_workflow -v`; expected `PluginError` or missing recipe.
- [ ] **Step 3: Implement sources and transforms.** `SecEdgarSource` rejects `context.offline`, requires nonempty `SEC_USER_AGENT` from `os.environ`, calls `fetch_sample`, writes only four raw JSON blobs under `context.run_dir` using fixed filenames, and returns `normalize_sample`. Its manifest has `network_access=True`, `permissions={"network:https", "filesystem:write"}`, `catalog_status="experimental"`, `retry_safe=False`. `SecReplaySource` uses `context.assert_read_path`, a bounded strict JSON read, `DataPacket.from_dict`, `validate_sec_packet`, and returns a new packet with the same `records` and original `as_of`; its manifest requires `filesystem:read` and is offline safe. Transform plugin wrappers call Task 3 functions and have no network/filesystem permissions.

```python
class SecReplaySource:
    manifest = PluginManifest(plugin_id="builtin.sec-replay-source", version="1.0.0",
        capability="source.sec_company_facts", input_contracts=(),
        output_contract=SEC_FACTS_CONTRACT,
        permissions=frozenset({"filesystem:read"}), retry_safe=True)
```

- [ ] **Step 4: Implement the report and recipe.** Render only validated peer fields, escape Markdown controls in text, and construct links only from validated official SEC URLs. Do not include current time, run ID, or local path in Markdown, so replay content can be byte-identical. Use a fixed `sec_industry_peers.md` filename under the current run directory, compute its byte SHA-256, then emit a one-record `quantagent.report.v1` packet compatible with `ResultStore.report()`. Pin recipe version `1.0.0`, four linear steps, default source `builtin.sec-edgar-source`, and exact output contracts. Register all plugins in `default_registry`; add catalog entries with live experimental and deterministic/replay verified statuses under the repository's offline-test policy.

```python
return DataPacket.create(contract_version="quantagent.report.v1",
    packet_type="markdown_report", source=self.manifest.plugin_id,
    records=[{"path": str(report_path), "format": "markdown",
              "input_sha256": packet.content_sha256,
              "artifact_sha256": hashlib.sha256(content).hexdigest()}])
```

- [ ] **Step 5: Run recipe and regression tests.** `python -m unittest tests.test_sec_workflow tests.test_result_api tests.test_manifest_spec -v`; expected all pass.
- [ ] **Step 6: Commit.** Run `git add quantagent_platform/sec_plugins.py quantagent_platform/runner.py plugin_catalog/catalog.json recipes/sec_industry_peers.json tests/test_sec_workflow.py`, then `git commit -m "feat: add SEC industry research recipe"`.

### Task 5: CLI Source Rules and Result API Readback

**Files:**
- Modify: `quantagent_platform/cli.py`
- Modify: `tests/test_sec_workflow.py`
- Modify: `docs/QUANTAGENT_READ_API.md`

**Interfaces:**
- Consumes: Task 4 recipe and source bindings.
- Produces: `--source sec-edgar` with no `--input` only under `--online --allow-permission network:https`; `--source sec-replay --input $livePacket` offline; prior source choices still require `--input`.

- [ ] **Step 1: Write failing CLI/API tests.** Parse `sec-edgar` without input successfully; reject `json`/`sqlite`/other older source without input before run creation; reject replay without input; verify live without `--online` or network permission never creates a run. Run replay through `cli_main` with a synthetic packet, then call authenticated `GET /api/v1/runs/{run_id}` and `/report` via `TestClient`. Assert summary schema, report SHA/ETag, GET idempotence, tampered report rejection, and absence of the SEC contact in run files, response bodies, and captured stderr.

```python
args = build_parser().parse_args(["run", str(recipe_path), "--source", "sec-edgar",
    "--online", "--allow-permission", "network:https"])
self.assertIsNone(args.input_path)
self.assertEqual(cli_main(["run", str(recipe_path), "--source", "json"]), 2)
```

- [ ] **Step 2: Run the tests to see current CLI failure.** `python -m unittest tests.test_sec_workflow -v`; expected parser rejects missing `--input` for `sec-edgar`.
- [ ] **Step 3: Implement source-sensitive input handling.** Make `--input` optional in argparse, then enforce it for every choice except `sec-edgar` in `_execution_values` before calling `runner.run`. For live, set no `source_path`, use empty read roots unless supplied, and require `--online` plus `network:https` through existing preflight. For replay, resolve/check the input path and allow its parent as the default read root. Add `sec-edgar`/`sec-replay` to `SOURCE_BINDINGS`; make `validate-recipe` honor `--online` and `--allow-permission` when validating a live recipe. Preserve `run-agent` behavior for all older choices.

```python
if args.source != "sec-edgar" and not args.input_path:
    raise RecipeError(f"--input is required for --source {args.source}")
if args.source == "sec-edgar" and args.input_path:
    raise RecipeError("sec-edgar does not accept --input")
```

- [ ] **Step 4: Run CLI/API and all regression tests.** `python -m unittest discover -s tests -q`; expected all pass, with baseline skip reasons unchanged. Record exact counts.
- [ ] **Step 5: Document usage and commit.** Add a P4 read example to `docs/QUANTAGENT_READ_API.md` without embedding contact or token values. Run `git add quantagent_platform/cli.py tests/test_sec_workflow.py docs/QUANTAGENT_READ_API.md`, then `git commit -m "feat: expose SEC live and replay through CLI and read API"`.

### Task 6: Private Live Canary, Replay, and Acceptance Record

**Files:**
- Create: `docs/P4_SEC_RESEARCH_ACCEPTANCE.md`
- Verify: private ignored run directory outside the repository, not a committed fixture.

**Interfaces:**
- Consumes: the complete Task 1–5 workflow and runtime `SEC_USER_AGENT`.
- Produces: one live run ID, one offline replay run ID, exact packet and raw response hashes, matched report values/evidence references, and acceptance evidence without contact details.

- [ ] **Step 1: Prepare a private output directory and run live.** Verify `D:\CryptoVault\Local repository\P4-sec-private-runs` resolves outside the Git worktree and inspect its current contents; create it without deleting other files. Set `SEC_USER_AGENT` in the process environment from the user-supplied contact without printing or persisting its value. From the repository root in PowerShell run the exact command below; the CLI JSON supplies the live run path.

```powershell
$p4RunRoot = 'D:\CryptoVault\Local repository\P4-sec-private-runs'
$python = 'D:\CryptoVault\Local repository\.quantagent-qa\Scripts\python.exe'
New-Item -ItemType Directory -Path $p4RunRoot -Force | Out-Null
$live = & $python -m quantagent_platform run recipes/sec_industry_peers.json --source sec-edgar --online --allow-permission network:https --output-dir $p4RunRoot | ConvertFrom-Json
$liveRun = [string]$live.run_dir
```
- [ ] **Step 2: Inspect the live run.** Read `run.json`, the first packet, raw response hashes, final report, and per-step contracts; verify exactly four requests, aware `as_of` after each retrieval, selected accession/period/unit, and no contact in artifacts. Cross-check report values against the linked MARA and Riot 2025 10-K primary statements: revenues USD 907,093,000 and 647,435,000; assets USD 7,286,899,000 and 3,936,767,000. If SEC changes its current response or a line no longer matches, record the discrepancy and do not mark acceptance complete.
- [ ] **Step 3: Replay and compare.** From the same PowerShell session, invoke the offline command below. Compare the sector/peer numeric JSON and evidence IDs and require byte-identical Markdown, since Task 4 omits run-specific headers. Test one tampered copy of the packet and verify no completed report. Query both runs through the authenticated Result API; verify summary and report ETags and read-only behavior.

```powershell
$livePacket = Join-Path $liveRun '01-load-sec-facts.json'
$replay = & $python -m quantagent_platform run recipes/sec_industry_peers.json --source sec-replay --input $livePacket --output-dir $p4RunRoot | ConvertFrom-Json
$replayRun = [string]$replay.run_dir
```
- [ ] **Step 4: Write the acceptance record.** Include UTC retrieval/filing times, exact accession IDs, SHA-256 of each raw response and selected packet, run IDs, report paths, full unittest command/counts, official 10-K links, two-company and current-API limitations, and any failures. Omit the project contact, auth token, raw full filings, and any private filesystem path that should not enter the repo.
- [ ] **Step 5: Verify and commit.** Run `python -m unittest discover -s tests -q`, `git diff --check`, and `git status --short`; inspect staged paths for secrets/raw SEC bytes, commit only `docs/P4_SEC_RESEARCH_ACCEPTANCE.md` plus intended code/doc changes, and record the final local commit SHA. Stop after P4; do not start P5 or publish/push without separate authorization.

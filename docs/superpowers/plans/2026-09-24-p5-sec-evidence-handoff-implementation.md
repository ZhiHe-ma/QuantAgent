# P5 SEC Evidence Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one offline, auditable handoff from an approved P4 SEC evidence producer Agent to an independent deterministic reviewer Agent, with a final report available from the existing authenticated Result API.

**Architecture:** A local coordinator admits a private, pinned P4 run, reserves one request, executes the producer, creates a strictly typed handoff, and executes the reviewer in a bounded worker. Versioned AgentManifest v2 enables only this exact one-hop route. A separate reviewer reselects facts from the frozen SEC bytes and checks the P4 report without invoking P4's derived-value builders.

**Tech Stack:** Python standard library, `unittest`, existing `jsonschema` and PyYAML manifest loader, existing `RecipeRunner`/`AgentRuntime`/FastAPI Result API; Windows and Linux compatible paths/processes. Use the existing local QA Python on Windows and set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUTF8=1`.

**Spec:** `docs/superpowers/specs/2026-09-24-p5-sec-evidence-handoff-design.md`

## Global Constraints

- Keep `quantagent.agent_manifest.v1` and all existing P1/P2/P4 recipes, CLI commands, and Result API behavior intact.
- Admit only `builtin.sec-evidence-producer-agent@1.0.0` → `builtin.sec-evidence-review-agent@1.0.0` for `sec.review_fy2025_mara_riot.v1`; no second hop or model/network binding.
- Keep the P4 source registry, four raw responses, and SEC contact private. Git receives only synthetic fixtures, code, and hash-only acceptance evidence.
- Cap the selected P4 packet at 2 MiB, each raw response at 8 MiB, the P4 report at 4 MiB, and the handoff envelope at 16 KiB.
- Set the chain deadline to 120 monotonic seconds, cancellation grace to at most 5 seconds, one handoff call, and model cost to exactly 0 USD.
- The handoff expires at the earlier of parent completion plus 5 minutes and the chain deadline. All persisted timestamps have timezone offsets.
- The child reads only the approved P4 run and broker-owned handoff, writes only its own run directory, and cannot gain a permission absent from its caller and parent.
- P4's current SEC responses are observed snapshots, not a historical point-in-time feed; the sample contains only MARA and Riot FY2025.

## Review Focus

- A pinned file replaced by a symlink or junction between path validation and reading must fail closed; test this in Task 2.
- A duplicate JSON key or non-finite number in a raw response must fail before a finding is produced; test this in Task 3.
- A handoff whose records digest matches but whose envelope metadata was changed must fail the whole-file/envelope hash check; test this in Task 4.
- Two processes presenting the same request ID concurrently must produce one chain; test this in Task 6.
- A worker that exits after writing a parent packet but before returning must leave an interrupted/failed chain and no child dispatch; test this in Task 7.

---

## File map and interfaces

| File | Responsibility |
| --- | --- |
| `schemas/quantagent.agent_manifest.v2.schema.json`, `quantagent_platform/manifests.py` | Version-select manifest validation while preserving v1 semantics. |
| `schemas/quantagent.sec_approved_run.v1.schema.json`, `quantagent_platform/p5_registry.py` | Strict private registry, pinned IDs/hashes, bounded link-safe artifact reads. |
| `quantagent_platform/p5_review.py` | Independent raw SEC selection, arithmetic, fixed P4 report checks, findings. |
| `schemas/quantagent.agent_handoff.v1.schema.json`, `quantagent_platform/p5_handoff.py`, `policies/p5_sec_route.v1.json` | Exact route pins, preflight, canonical envelope, expiry and permission checks. |
| `quantagent_platform/p5_plugins.py`, `quantagent_platform/runner.py`, `plugin_catalog/catalog.json` | Two producer and three reviewer plugins registered with the existing linear runner. |
| `agent_catalog/agents/sec-evidence-producer-agent/agent.yaml`, `agent_catalog/agents/sec-evidence-review-agent/agent.yaml`, `agent_catalog/skills/sec-evidence-preparation/{SKILL.md,skill.yaml}`, `agent_catalog/skills/sec-evidence-independent-review/{SKILL.md,skill.yaml}`, `recipes/sec_evidence_producer.json`, `recipes/sec_evidence_review.json`, `agent_catalog/catalog.json` | Version-pinned two-Agent/Skill/Recipe packages. |
| `quantagent_platform/p5_ledger.py` | SQLite-backed atomic request reservation and inspectable versioned chain audit under the private run root. |
| `quantagent_platform/p5_worker.py`, `quantagent_platform/p5_coordinator.py` | Spawn-safe bounded execution, single authorized dispatch, cancellation, recovery. |
| `quantagent_platform/cli.py` | One operator-only `review-sec-evidence` command; direct generic CLI execution of coordinator-only Agents denied. |
| `tests/test_p5_*.py`, `docs/P5_SEC_HANDOFF_ACCEPTANCE.md` | Synthetic positive/negative evidence, private live-run acceptance, contract and regression record. |

The implementation uses these cross-task interfaces:

```python
ApprovedRun.from_pins(pins: dict[str, object], run_root: Path) -> ApprovedRun
ApprovedRunRegistry.load(path: Path, run_root: Path) -> ApprovedRunRegistry
ApprovedRunRegistry.resolve(source_id: str) -> ApprovedRun
read_approved_source(source: ApprovedRun) -> SecEvidence
review_evidence(evidence: SecEvidence, bundle: dict[str, object]) -> dict[str, object]
RoutePolicy.load(path: Path) -> RoutePolicy
preflight_route(policy: RoutePolicy, parent: ResolvedAgentPlan,
                child: ResolvedAgentPlan, caller_permissions: frozenset[str]) -> frozenset[str]
create_handoff(policy: RoutePolicy, parent: RunResult, bundle_path: Path,
               source: ApprovedRun, coordinator_id: str,
               completed_at: datetime, deadline_at: datetime) -> Handoff
verify_handoff(raw: bytes, expected_sha256: str, policy: RoutePolicy,
               now: datetime) -> Handoff
HandoffLedger.reserve(request_id: str, fingerprint: str) -> tuple[str, bool]
HandoffLedger.transition(chain_id: str, status: str, **fields: object) -> None
run_worker(spec: WorkerSpec, deadline: float, cancel_event: Event) -> WorkerResult
P5Coordinator.run(source_id: str, request_id: str) -> ChainResult
```

### Task 1: Versioned AgentManifest v2

**Files:** Create `schemas/quantagent.agent_manifest.v2.schema.json`; modify `quantagent_platform/manifests.py`; test `tests/test_p5_manifest.py`.

**Interfaces:** `load_agent_manifest(path)` returns the existing `LoadedManifest`. v2 shares v1 fields but permits one exact `callable_agents` reference; v1 still requires an empty list. Unknown `manifest_type` fails before catalog execution.

- [ ] **Step 1: Write the failing tests.** Copy the checked-in v1 sample into a temporary YAML; change only `manifest_type` and `callable_agents`. Assert v2 with one `{"id": "builtin.sec-evidence-review-agent", "version": "1.0.0"}` loads, v1 with that reference fails, v2 with two references fails, and an unknown version fails.
  ```python
  self.assertEqual(load_agent_manifest(v2_path).data["manifest_type"],
                   "quantagent.agent_manifest.v2")
  with self.assertRaises(ManifestError):
      load_agent_manifest(v1_with_child_path)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_manifest -v`.** Expect failure because the v2 schema is absent or the loader still selects v1.
- [ ] **Step 3: Add v2 schema and version routing.** Copy the v1 schema, change its `$id`/title/`manifest_type` const, set `callable_agents.maxItems` to `1`, and keep its exact reference schema. Select by a fixed map, never a path constructed from untrusted manifest text:
  ```python
  schema_names = {
      "quantagent.agent_manifest.v1": "quantagent.agent_manifest.v1.schema.json",
      "quantagent.agent_manifest.v2": "quantagent.agent_manifest.v2.schema.json",
  }
  schema_name = schema_names.get(data.get("manifest_type"))
  if schema_name is None:
      raise ManifestError("unsupported AgentManifest version")
  _validate_schema(data, schema_root / schema_name, "AgentManifest")
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_manifest tests.test_manifest_spec tests.test_agent_runtime -v`.** Expect all pass and old v1 manifests unchanged.
- [ ] **Step 5: Commit** these three paths as `feat(p5): add AgentManifest v2 without changing v1`.

### Task 2: Private approved-run registry and artifact reader

**Files:** Create `schemas/quantagent.sec_approved_run.v1.schema.json`, `quantagent_platform/p5_registry.py` and `tests/test_p5_registry.py`. Reuse `tests/test_sec_contracts.py` synthetic response builders; create a synthetic four-step *live-shaped* P4 run in a temporary directory rather than checking raw SEC JSON into Git.

**Interfaces:** `ApprovedRun` has `source_id`, `run_id`, `run_dir`, `registry_sha256`, `packet_sha256`, `report_sha256`, `raw_sha256`, pinned P4 recipe/source plugin identity. `ApprovedRun.from_pins(pins, run_root)` reconstructs exactly those fields from a verified handoff without rereading the registry. `SecEvidence` contains the validated `DataPacket`, `record_sha256` from P4 `run.json`, report bytes, four raw bytes, and exact byte hashes. `ApprovedRunRegistry.load(path, run_root)` and `read_approved_source(source)` are the public functions.

- [ ] **Step 1: Write the failing tests.** Generate four synthetic responses with `make_responses()`, run `SecEdgarSource` through the P4 recipe with `fetch_sample` patched, and write a registry entry with the resulting IDs and hashes. Assert `read_approved_source(registry.resolve("synthetic-p4"))` returns a packet with `quantagent.sec_company_facts.v1` and four raw buffers. Assert an unregistered ID, wrong whole-file packet hash, altered report hash, missing raw file, oversized file, symlink, junction where supported, and a swapped symlink during read each raise `ApprovedSourceError`.
  ```python
  source = ApprovedRunRegistry.load(registry_path, runs).resolve("synthetic-p4")
  evidence = read_approved_source(source)
  self.assertEqual(len(evidence.raw), 4)
  self.assertEqual(evidence.packet.content_sha256, evidence.record_sha256)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_registry -v`.** Expect import failure for `p5_registry`.
- [ ] **Step 3: Implement strict registry and reader.** Parse UTF-8 JSON with duplicate-key/non-finite rejection; validate an object with `registry_version="quantagent.sec_approved_run.v1"` and `entries` containing exact `approved_source_id`, `run_id`, `recipe`, `source_plugin`, `packet_sha256`, `report_sha256`, and four fixed `raw_sha256` keys. Resolve only a safe run ID below configured root. Implement `bounded_regular_file(path: Path, limit: int) -> bytes` using no-follow file opens (POSIX `O_NOFOLLOW`; Windows handle opening with `FILE_FLAG_OPEN_REPARSE_POINT` and reparse rejection), rejecting symlinks/junctions in every path component and changed file identity; enforce caps while reading. Compare bytes to registry hash and packet source rows; parse `DataPacket.from_dict` and call `validate_sec_packet`. Check `run.json` status, exact four P4 step IDs/contracts/plugin versions, report packet `artifact_sha256`/`input_sha256` and report bytes.
  ```python
  if source.run_dir.name != source.run_id or source.run_dir.is_symlink():
      raise ApprovedSourceError("approved run path changed")
  raw = bounded_regular_file(source.run_dir / "01-load-sec-facts.json",
                             2 * 1024 * 1024)
  if sha256(raw).hexdigest() != source.packet_sha256:
      raise ApprovedSourceError("approved packet hash mismatch")
  packet = DataPacket.from_dict(strict_json(raw))
  validate_sec_packet(packet)
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_registry tests.test_sec_workflow -v`.** Expect all pass, including path-race tests.
- [ ] **Step 5: Commit** the reader and its tests as `feat(p5): pin private P4 run artifacts`.

### Task 3: Independent SEC review and fixed report checks

**Files:** Create `quantagent_platform/p5_review.py` and `tests/test_p5_review.py`.

**Interfaces:** `review_evidence(evidence, bundle) -> findings_record`; `verify_p4_report(report: bytes, findings: dict) -> None`; `render_review_report(findings: dict, reviewed_at: str) -> bytes`. The reviewer may import pinned constants `ISSUERS`, `SEC_URLS`, `FISCAL_START`/`FISCAL_END` from `sec_contracts`, but cannot call `normalize_sample`, `build_sector`, or `build_peers`.

- [ ] **Step 1: Write failing table-driven tests.** Use Task 2 synthetic source and `make_payloads()` mutations. Assert exact selected MARA/Riot Revenues and Assets, `2/2` coverage and integer sums; a removed approved fact yields `unknown` and `1/2`. The rendered report must show the original P4 `as_of` and a separate later review timestamp. Mutate one bundle value while raw bytes stay fixed; mutate CIK, accession, form, period, unit, filing date, duplicate qualifying XBRL row, duplicate JSON key, non-finite number, report table value, or scope line. Each mismatch must raise `IndependentReviewError` and produce no final report.
  ```python
  findings = review_evidence(evidence, bundle)
  self.assertEqual(findings["coverage"]["Revenues"], {"available": 2, "total": 2})
  self.assertEqual(findings["sample_sums_usd"]["Revenues"], 1554528000)
  with self.assertRaises(IndependentReviewError):
      review_evidence(evidence, wrong_derived_value_bundle)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_review -v`.** Expect import failure for `p5_review`.
- [ ] **Step 3: Implement independent selection.** Parse frozen Submissions and Company Facts with strict JSON. For each pinned issuer, locate its one 10-K accession, check FY end/acceptance, select at most one `us-gaap` USD row with exact accession/form/period and filed date no later than P4 `as_of`. Compare each raw selected integer and provenance against the bundle; recompute sums and decimal millions with `Decimal(value) / Decimal(1_000_000)`. Match the fixed P4 report's sector and peer table rows and sample-only scope text, and reject table edits. Escape any displayed untrusted text before Markdown.
  ```python
  selected = [row for row in rows
              if row.get("accn") == issuer["accession"]
              and row.get("form") == "10-K"
              and row.get("end") == FISCAL_END
              and (row.get("start") == FISCAL_START if concept == "Revenues"
                   else row.get("start") in (None, ""))]
  if len(selected) > 1:
      raise IndependentReviewError("duplicate qualifying SEC fact")
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_review tests.test_sec_analysis -v`.** Expect all pass; inspect imports to confirm the reviewer does not call P4 derived-value functions.
- [ ] **Step 5: Commit** the independent reviewer and tests as `feat(p5): independently verify frozen SEC facts`.

### Task 4: Route policy, permission preflight, and typed handoff

**Files:** Create `schemas/quantagent.agent_handoff.v1.schema.json`, `quantagent_platform/p5_handoff.py`, `tests/test_p5_handoff.py`. Use a generated temporary fixture policy in this task; the checked-in `policies/p5_sec_route.v1.json` is created in Task 5 after catalog hashes are final.

**Interfaces:** `RoutePolicy.load(path)` validates exact route/task/catalog/recipe/plugin pins and holds `sha256` over the policy file bytes. `preflight_route(policy, parent, child, caller_permissions)` returns the permission intersection. `create_handoff(...)` produces a dataclass with canonical JSON bytes and `sha256`; `verify_handoff(raw, expected_sha256, policy, now)` returns it or raises `HandoffError`.

- [ ] **Step 1: Write failing tests.** Build resolved producer/reviewer plans from a fixture catalog, and assert accepted policy pins. Change a target version, manifest callable list, catalog or recipe hash, plugin version/contract/permission, source identity, caller permission, task type, depth, cycle, stale timestamp, or a non-record envelope field. Every changed case must fail before child dispatch. Assert `len(handoff.raw) <= 16384` and timezone-aware creation/expiry.
  ```python
  self.assertEqual(preflight_route(policy, parent, child,
                                  frozenset({"filesystem:read", "filesystem:write"})),
                   frozenset({"filesystem:read", "filesystem:write"}))
  with self.assertRaises(HandoffError):
      verify_handoff(changed_metadata_raw, original_sha, policy, now)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_handoff -v`.** Expect import failure for `p5_handoff`.
- [ ] **Step 3: Implement exact preflight and canonical envelope.** Pin both resolved Agent/Skill/Recipe hashes, catalog hash, each plugin manifest identity/version/contract/permissions, source contract, task, route version, call/depth/cost/wall limits. Build the envelope in coordinator code after completed parent step `prepare-sec-evidence` and validate its strict JSON schema: stable handoff ID/idempotency key, coordinator/parent run IDs, parent Agent/Skill/Recipe IDs/versions/hashes, source pins, target ID/version, task, exact completed step, bundle contract/record digest/file SHA, policy version/hash, aware created/expiry times, depth 1, remaining call 1, remaining wall seconds, zero USD cost, and effective permissions. Calculate `sha256(canonical_json(envelope).encode("utf-8"))` and compare it on read. Reject `now >= expires_at` and every permission not present in the caller, parent, and child.
  ```python
  effective = caller_permissions & parent_permissions & child_permissions
  if child_permissions - effective or policy.max_handoffs != 1:
      raise HandoffError("route would expand permissions")
  expires_at = min(completed_at + timedelta(minutes=5), deadline_at)
  raw = canonical_json(envelope).encode("utf-8")
  if len(raw) > 16 * 1024:
      raise HandoffError("handoff envelope exceeds 16 KiB")
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_handoff tests.test_p5_manifest -v`.** Expect all pass.
- [ ] **Step 5: Commit** the handoff schema, handoff module, and tests as `feat(p5): validate one authorized handoff route`.

### Task 5: Two curated Agents and their linear Recipes

**Files:** Create `quantagent_platform/p5_plugins.py`, `recipes/sec_evidence_producer.json`, `recipes/sec_evidence_review.json`, `agent_catalog/agents/sec-evidence-producer-agent/agent.yaml`, `agent_catalog/agents/sec-evidence-review-agent/agent.yaml`, `agent_catalog/skills/sec-evidence-preparation/SKILL.md` and `skill.yaml`, `agent_catalog/skills/sec-evidence-independent-review/SKILL.md` and `skill.yaml`, `policies/p5_sec_route.v1.json`; modify `quantagent_platform/runner.py`, `plugin_catalog/catalog.json`, `agent_catalog/catalog.json`; test `tests/test_p5_agents.py`.

**Interfaces:** Producer steps `load-approved-sec-run` (`quantagent.sec_approved_run.v1`), `prepare-sec-evidence` (`quantagent.sec_evidence_bundle.v1`). Reviewer steps `load-sec-handoff` (`quantagent.agent_handoff.v1`), `review-sec-evidence` (`quantagent.sec_independent_review.v1`), `write-sec-review` (`quantagent.report.v1`). New plugin classes expose the existing `PluginManifest` and `run(context, packet, config) -> DataPacket` interface. Coordinator supplies only registry/source/handoff broker configuration.

The exact plugin IDs are `builtin.sec-approved-run-source`, `builtin.sec-evidence-preparer`, `builtin.sec-handoff-source`, `builtin.sec-independent-review`, and `builtin.markdown-sec-independent-review`, all at `1.0.0`. The two Skills are `builtin.sec-evidence-preparation@1.0.0` and `builtin.sec-evidence-independent-review@1.0.0`. The two Recipes are `sec-evidence-producer@1.0.0` and `sec-evidence-review@1.0.0`.

| Plugin ID | Capability | Input → output contract | Permissions |
| --- | --- | --- | --- |
| `builtin.sec-approved-run-source` | `source.sec_approved_run` | none → `quantagent.sec_approved_run.v1` | `filesystem:read` |
| `builtin.sec-evidence-preparer` | `research.sec_evidence_bundle` | `quantagent.sec_approved_run.v1` → `quantagent.sec_evidence_bundle.v1` | none |
| `builtin.sec-handoff-source` | `source.sec_agent_handoff` | none → `quantagent.agent_handoff.v1` | `filesystem:read` |
| `builtin.sec-independent-review` | `research.sec_independent_review` | `quantagent.agent_handoff.v1` → `quantagent.sec_independent_review.v1` | `filesystem:read` |
| `builtin.markdown-sec-independent-review` | `report.sec_independent_review` | `quantagent.sec_independent_review.v1` → `quantagent.report.v1` | `filesystem:write` |

- [ ] **Step 1: Write failing tests.** Assert `AgentRuntime.resolve` selects both exact Agents/Skills/Recipes and all five plugin versions/contracts, producer v2 manifest has exactly the reviewer ID/version in `callable_agents`, and reviewer v2 manifest has an empty list. Reject changed plugin binding or network permission. Producer/reviewer direct synthetic runs yield a linked bundle/finding/report. Verify report packet has `path`, `format="markdown"`, `input_sha256`, and actual `artifact_sha256` so `ResultStore.report` can read it.
  ```python
  parent = AgentRuntime().resolve(agent_id="builtin.sec-evidence-producer-agent",
                                  agent_version="1.0.0", offline=True)
  self.assertEqual(parent.agent["output_contract"],
                   "quantagent.sec_evidence_bundle.v1")
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_agents -v`.** Expect exact Agent missing from catalog.
- [ ] **Step 3: Implement five plugins and curated metadata.** First producer plugin calls `ApprovedRunRegistry.load`/`read_approved_source` and emits facts plus source/report hashes without raw bytes or absolute paths; second emits the evidence bundle. First reviewer plugin calls `verify_handoff` against broker-owned file and loads the pinned parent bundle; its output record contains `approved_source_pins` and `bundle`. The review plugin calls `review_evidence`; final plugin writes `sec_independent_review.md` and emits the Result API-compatible report packet. Compute Skill file/package hashes with `canonical_json` and update catalog SHA fields after writing all files. Create the versioned route policy with the final catalog/Recipe/plugin hashes and permission sets. Keep `metadata.coordinator_only: true` on both Agent manifests.
  ```python
  class SecIndependentReview:
      manifest = PluginManifest(
          plugin_id="builtin.sec-independent-review", version="1.0.0",
          capability="research.sec_independent_review",
          input_contracts=("quantagent.agent_handoff.v1",),
          output_contract="quantagent.sec_independent_review.v1",
          permissions=frozenset({"filesystem:read"}))
      def run(self, context, packet, config):
          handoff = packet.records[0]
          source = ApprovedRun.from_pins(
              handoff["approved_source_pins"], Path(config["approved_run_root"]))
          context.assert_read_path(str(source.run_dir))
          findings = review_evidence(read_approved_source(source),
                                     handoff["bundle"])
          return DataPacket.create(contract_version=self.manifest.output_contract,
                                   packet_type="sec_independent_review",
                                   source=self.manifest.plugin_id, records=[findings])
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_agents tests.test_agent_runtime tests.test_sec_workflow tests.test_p5_handoff -v`.** Expect all pass with the final checked-in route policy hashes.
- [ ] **Step 5: Commit** all listed code/catalog/Recipe/Skill paths plus policy pin update as `feat(p5): curate SEC producer and reviewer Agents`.

### Task 6: Atomic request reservation and chain audit

**Files:** Create `quantagent_platform/p5_ledger.py` and `tests/test_p5_ledger.py`.

**Interfaces:** `HandoffLedger(root: Path)` owns `p5_handoff.sqlite3` under the configured private run root. `reserve(request_id, fingerprint) -> (chain_id, created)` atomically enforces unique request ID; `transition(chain_id, status, **fields)` writes an append-only versioned event and current chain state in one transaction; `get(chain_id)`/`get_by_request(request_id)` return inspectable records; `recover_interrupted()` marks unfinished chains interrupted without dispatch. The normal states are `admitted` → `parent_running` → `parent_completed` → `handoff_ready` → `child_running` → `completed`; any nonterminal state can end as `failed`, `cancelled`, `timed_out`, or `interrupted`.

- [ ] **Step 1: Write failing tests.** Assert same ID/fingerprint returns one chain, same ID/different fingerprint raises `IdempotencyConflict`, concurrent processes reserve one ID, event sequence is monotone, terminal status cannot become completed, and restart marks a running chain interrupted with no child ID invented.
  ```python
  first = ledger.reserve("operator-001", fingerprint)
  second = ledger.reserve("operator-001", fingerprint)
  self.assertEqual(first[0], second[0])
  self.assertFalse(second[1])
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_ledger -v`.** Expect import failure for `p5_ledger`.
- [ ] **Step 3: Implement the SQLite transaction boundary.** Create schema version 1 with `requests(request_id PRIMARY KEY, fingerprint, chain_id)`, `chains(chain_id PRIMARY KEY, status, parent_id, child_id, source_packet_sha256, source_report_sha256, raw_hashes_json, bundle_sha256, handoff_sha256, catalog_sha256, policy_sha256, permissions_json, started_at, ended_at, wall_ms, handoff_calls, model_cost_minor, failure_code)` and `events(chain_id, seq, status, at, payload_json, PRIMARY KEY(chain_id,seq))`. Use `BEGIN IMMEDIATE` for reserve and transition, strict status transitions, and sanitized enumerated failure codes. Store no contact, raw response, or absolute private path in events.
  ```python
  connection.execute("BEGIN IMMEDIATE")
  existing = connection.execute(
      "SELECT fingerprint, chain_id FROM requests WHERE request_id = ?",
      (request_id,)).fetchone()
  if existing and existing[0] != fingerprint:
      raise IdempotencyConflict("request ID was used for different evidence")
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_ledger -v`.** Expect all pass, including simultaneous reservation and crash/reopen.
- [ ] **Step 5: Commit** ledger and tests as `feat(p5): persist atomic handoff audit`.

### Task 7: Spawn-safe bounded Agent worker

**Files:** Create `quantagent_platform/p5_worker.py` and `tests/test_p5_worker.py`.

**Interfaces:** `WorkerSpec` is JSON-safe and contains exact Agent/Skill/Recipe IDs/versions, broker parameters, run ID/root, read roots, permissions, and coordination invocation context. `run_worker(spec, deadline: float, cancel_event) -> WorkerResult` starts one `multiprocessing.get_context("spawn")` process, returns only run ID/status/final packet path/hash, and never accepts a plugin object from a caller. `WorkerResult.packet_path` is `Path | None` and is `None` for non-completion. The worker calls `AgentRuntime.run(..., offline=True, submission_context=..., cancel_check=cancel_flag.is_set)`.

- [ ] **Step 1: Write failing tests.** Exercise a normal synthetic worker, a worker that blocks beyond a short test deadline, a cancellation request during a step, and an abrupt exit after a parent packet write. Assert the supervisor terminates within deadline/grace, reports `timed_out`/`cancelled`/`interrupted`, and leaves no completed child report. Use a test-only worker entrypoint injected into the supervisor constructor; production accepts only the fixed module-level Agent entrypoint.
  ```python
  outcome = run_worker(spec, deadline=monotonic() + 2.0,
                       cancel_event=Event())
  self.assertEqual(outcome.status, "completed")
  self.assertTrue(outcome.packet_path.is_file())
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_worker -v`.** Expect import failure for `p5_worker`.
- [ ] **Step 3: Implement process supervision.** Serialize `WorkerSpec` into a bounded `Pipe` message, launch a module-level target using `spawn`, poll monotonic time and external cancellation, signal cooperative cancellation through a multiprocessing event passed to `AgentRuntime.run(cancel_check=cancel_flag.is_set)`, and `terminate`/`join` after at most five seconds. Detect nonzero exit or missing result as interruption. Never trust worker-returned path without checking it remains under the configured run root and rereading the packet/hash.
  ```python
  process = get_context("spawn").Process(target=_agent_worker,
                                           args=(child_pipe, cancel_flag, spec))
  process.start()
  while process.is_alive():
      if monotonic() >= deadline:
          process.terminate()
          process.join(timeout=5)
          return WorkerResult(status="timed_out", run_id=spec.run_id)
      process.join(timeout=0.05)
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_worker tests.test_run_cancellation -v`.** Expect all pass on Windows spawn and normal cancellation behavior unchanged.
- [ ] **Step 5: Commit** worker and tests as `feat(p5): bound deterministic Agent workers`.

### Task 8: Fixed two-Agent coordinator

**Files:** Create `quantagent_platform/p5_coordinator.py` and `tests/test_p5_coordinator.py`.

**Interfaces:** `P5Coordinator(registry_path, approved_run_root, run_root, policy_path, ledger, worker)` exposes `run(source_id, request_id) -> ChainResult`. `ChainResult` holds chain ID/status, parent/child run IDs, handoff hash, measured wall/calls, and zero model cost; `ChainResult.from_ledger(record)` reconstructs repeat responses. It accepts no target/path/URL parameter from the operator. The request fingerprint is the hash of canonical `{approved_source_id, packet_sha256, task_type, route_policy_sha256}`. A repeated exact request returns the stored chain state without rerun.

- [ ] **Step 1: Write failing tests.** Synthetic successful chain must have one parent, one handoff, one child, two linked `run.json` invocations, one ledger chain, measured wall/calls, zero model cost, and a completed child report. A second run with a new request ID against the same approved source must reproduce findings and numeric conclusions while allowing different audit IDs/timestamps. Add cases for duplicate exact request, conflicting ID, forged target string in bundle text, permission expansion, expired envelope, parent failure, child failure, cancellation, timeout, process crash, second hop, and cycle; all failures leave linked terminal audits and no completed child report.
  ```python
  result = coordinator.run("synthetic-p4", "request-001")
  self.assertEqual(result.status, "completed")
  self.assertEqual(result.handoff_calls, 1)
  self.assertEqual(ledger.get(result.chain_id)["child_id"], result.child_run_id)
  self.assertEqual(coordinator.run("synthetic-p4", "request-001").chain_id,
                   result.chain_id)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_coordinator -v`.** Expect import failure for `p5_coordinator`.
- [ ] **Step 3: Implement admission and one dispatch.** Load registry and policy, resolve both exact Agents, call `preflight_route`, reserve the request before creating the parent, set one 120-second monotonic deadline, and dispatch parent. Only after completed parent and verified bundle packet copy that packet into a broker-owned directory, compare its whole-file hash, then create/persist the canonical handoff containing the broker copy's hash. Reverify the handoff hash and expiry immediately before child dispatch. Launch child with read roots equal to approved run plus broker directory, write root equal to its own run directory. Record each transition and sanitized terminal failure in `HandoffLedger`; never inspect bundle text for a target. On coordinator startup call `recover_interrupted`, without automatic redelivery.
  ```python
  fingerprint = sha256_json({
      "approved_source_id": source_id,
      "packet_sha256": source.packet_sha256,
      "task_type": "sec.review_fy2025_mara_riot.v1",
      "route_policy_sha256": policy.sha256,
  })
  chain_id, created = ledger.reserve(request_id, fingerprint)
  if not created:
      return ChainResult.from_ledger(ledger.get(chain_id))
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_coordinator tests.test_p5_handoff tests.test_p5_ledger -v`.** Expect all pass and no duplicate child run directory.
- [ ] **Step 5: Commit** coordinator and tests as `feat(p5): coordinate one SEC Agent handoff`.

### Task 9: Operator command and existing Result API readback

**Files:** Modify `quantagent_platform/cli.py`; test `tests/test_p5_cli_api.py`. No new P5 web endpoint.

**Interfaces:** `review-sec-evidence --approved-registry PATH --approved-run-root DIR --run-root DIR --source-id ID --request-id ID` prints the coordinator's JSON-safe chain summary. Existing `serve-results` reads the child `run_id` from the configured P5 run root. `run-agent` rejects Agents marked `metadata.coordinator_only`.

- [ ] **Step 1: Write failing CLI/API tests.** Run synthetic command in a temp private root. Assert unknown source and extra target/path option exit nonzero; generic `run-agent` for either P5 Agent exits nonzero; successful command emits exactly one child run ID. Assert unauthenticated GET is 401, authenticated summary/report are 200, report ETag hashes exact bytes, tampered report returns 409, and GET mutates no artifact.
  ```python
  code = cli_main(["review-sec-evidence", "--approved-registry", str(registry),
                   "--approved-run-root", str(p4_root), "--run-root", str(p5_root),
                   "--source-id", "synthetic-p4", "--request-id", "request-001"])
  self.assertEqual(code, 0)
  self.assertEqual(client.get(f"/api/v1/runs/{child_id}/report",
                              headers=auth).status_code, 200)
  ```
- [ ] **Step 2: Run `python -m unittest tests.test_p5_cli_api -v`.** Expect parser rejection of the new command.
- [ ] **Step 3: Wire one narrow command.** Construct `P5Coordinator` from the six explicit operator options, print a sanitized chain summary, and map admission/contract failures to exit 2 and worker failure to exit 1. Deny coordinator-only Agent IDs in generic `run-agent` before `AgentRuntime.run`; do not alter `serve-results` routes or authentication.
  ```python
  review = subparsers.add_parser("review-sec-evidence")
  for name in ("approved-registry", "approved-run-root", "run-root",
               "source-id", "request-id"):
      review.add_argument("--" + name, required=True)
  ```
- [ ] **Step 4: Run `python -m unittest tests.test_p5_cli_api tests.test_result_api tests.test_sec_workflow -v`.** Expect all pass.
- [ ] **Step 5: Commit** CLI and tests as `feat(p5): expose private SEC review command`.

### Task 10: Private live-run acceptance and full regression

**Files:** Create `docs/P5_SEC_HANDOFF_ACCEPTANCE.md`; modify `docs/QUANTAGENT_AGENT_SKILL_SPEC.md` only to describe v2/this fixed route; add any missing focused tests to `tests/test_p5_*.py`.

**Interfaces:** Acceptance document lists the private P4 run ID, packet/report/raw hashes, Agent/Skill/Recipe/catalog/policy versions and hashes, code commit SHA, child run ID, numeric findings, negative-test classes, and limits. It contains no private root, raw response content, or contact.

- [ ] **Step 1: Add a failing integration assertion** that the privately registered P4 live run `20260924T110650Z-52ae9d22` completes offline and reproduces MARA/Riot FY2025 revenues `907093000`/`647435000`, assets `7286899000`/`3936767000`, `2/2` coverage, and sums `1554528000`/`11223666000`. Skip only when the private run is absent; do not commit a registry containing private paths.
  ```python
  self.assertEqual(findings["sample_sums_usd"],
                   {"Revenues": 1554528000, "Assets": 11223666000})
  self.assertEqual(findings["coverage"]["Assets"],
                   {"available": 2, "total": 2})
  ```
- [ ] **Step 2: Run the focused live-run test and the full suite.** Use the QA interpreter: `python -m unittest discover -s tests -q`. Expect zero failures; record skip count exactly. A missing private live run blocks acceptance even if its test skips. Also run `git diff --check` and scan the acceptance document, catalog, Skills, policy, and recipes for email addresses, private root paths, and raw SEC response content; expect no matches.
- [ ] **Step 3: Complete acceptance and docs.** Hash the final source, P5 catalog/Recipe/Skill/policy files, reread the child report through the authenticated Result API, and record observed chain audit statuses, wall time, one call, zero cost, negative-test results, and trust limits. Update the Agent/Skill spec to say v1 still has empty `callable_agents` and v2 supports this fixed coordinator route.
  ```python
  record = {
      "source_run_id": "20260924T110650Z-52ae9d22",
      "source_packet_sha256": source.packet_sha256,
      "policy_sha256": policy.sha256,
      "child_run_id": result.child_run_id,
      "handoff_calls": result.handoff_calls,
      "model_cost_minor": 0,
  }
  ```
- [ ] **Step 4: Rerun `python -m unittest discover -s tests -q` and `git diff --check` after docs and test edits.** Expect pass; independently inspect the final Git diff for private paths, contact, raw SEC bytes, and scope drift.
- [ ] **Step 5: Commit** acceptance/docs/tests as `docs(p5): record SEC handoff acceptance`. Do not upload or create a PR without the user's separate authorization.

## Self-review gates before execution handoff

- [ ] Compare every section of the spec with Tasks 1–10; confirm the five Review Focus cases are implemented by their owning task.
- [ ] Search this plan for placeholder markers, undefined names, inconsistent contracts/step IDs, and references to an uncreated file.
- [ ] Check that the route policy is created only after catalog files stabilize, then retest Task 4.
- [ ] Confirm the documentation-only plan commit has `git diff --check` clean and no code changes.

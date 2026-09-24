# P5 first slice: SEC evidence handoff and independent review

Date: 2026-09-24. Status: design for review. Base: QuantAgent `main` after P4 PR #19 (`10bfc3e`).

## Intent and acceptance boundary

The user selected a first useful cross-Agent case: an Agent prepares the approved, frozen P4 MARA/Riot FY2025 SEC evidence, then a separate Agent independently reviews its source linkage, financial-fact selection, arithmetic, and conclusion scope. The first review is deterministic and offline. It uses no paid model, network request, trading action, or arbitrary third-party plugin. A completed result consists of linked parent and child runs, a typed handoff audit, a review packet, and a report readable through the existing Result API.

This is the first P5 slice, not a claim that the full multi-Agent, model-evaluation, Qlib-to-bt, or deployment roadmap is complete. The P4 two-issuer sample remains a sample, and the frozen SEC retrieval is not a historical point-in-time feed.

## Decision and alternatives

Use a fixed, local two-Agent coordinator for one approved route. It provides a real handoff while keeping the current linear `RecipeRunner` and existing P1/P2/P4 recipes intact.

- A general Recipe graph with named outputs, branches, and fan-in would serve later multi-input cases, but changes a larger shared execution contract before one handoff has been validated.
- A cross-process queue would add persistent scheduling, ownership, recovery, and deployment concerns before this local offline case needs them.

The coordinator is a trusted control-plane component. Evidence text, report Markdown, plugin output, and model-like JSON cannot select its target or create a handoff instruction.

## Input and the two Agents

An operator-owned private registry maps a short `approved_source_id` to one completed P4 live run under one configured run root. The registry pins the run ID, P4 recipe and source-plugin versions, the first packet's whole-file SHA-256, the final report's byte SHA-256, and the four raw-response SHA-256 values. Its strict entry contract is `quantagent.sec_approved_run.v1`; the registry file's hash enters the audit. It is local configuration, not a repository fixture or public API input. The coordinator accepts only the registered ID and an operator-supplied request ID; callers do not supply a filesystem path, URL, target Agent, or arbitrary packet. The reader caps the selected packet at 2 MiB, each frozen raw response at P4's 8 MiB limit, and the report at the existing Result API's 4 MiB limit.

The producer Agent, `builtin.sec-evidence-producer-agent@1.0.0`, reads the registered run with a bounded, link-safe artifact reader. It requires `run.json` to be complete, the expected P4 steps and contracts to match, the first packet's bytes and `DataPacket.records` digest to match their pins, the final report to match its packet and registered byte hash, and the four fixed raw snapshot filenames to hash to the packet's source rows and registry. It applies `validate_sec_packet` and emits one `quantagent.sec_evidence_bundle.v1` packet containing the admitted facts, exact provenance, and fixed raw-snapshot and report references by name and hash. Raw response bytes and absolute paths do not enter the bundle.

The reviewer Agent, `builtin.sec-evidence-review-agent@1.0.0`, receives only a coordinator-created handoff. Its source resolves the fixed snapshots and bundle inside the approved private run root. A separate audit implementation parses the frozen Submissions and Company Facts bytes, filters the pinned CIK/accession/form/period/unit, rejects duplicates, and independently recomputes the admitted values, coverage, two-company sums, and display conversion. It must not call P4's `normalize_sample`, `build_sector`, or `build_peers` to produce its verdict. It verifies the known P4 report artifact hash and its fixed numeric tables and scope statements; arbitrary prose is outside the automatic semantic check. Required mismatches fail the child run without a completed review report. A legitimate missing approved fact is recorded as `unknown` with a reason, never as zero.

The child emits `quantagent.sec_independent_review.v1` findings with `pass`, `fail`, or `unknown`, exact evidence references, and the methods checked. Its final `quantagent.report.v1` Markdown explains the findings and the two-issuer limitation. The existing authenticated Result API reads that final report; no P5-specific web page or endpoint is required for this slice.

Each Agent has one dedicated, version-pinned Skill and one linear Recipe in the Agent catalog. The producer declares `quantagent.sec_approved_run.v1` input and `quantagent.sec_evidence_bundle.v1` output; the reviewer declares `quantagent.agent_handoff.v1` input and `quantagent.report.v1` output. Their Skills declare those same accepted contracts. The producer recipe loads and verifies the registered P4 snapshot, then emits the evidence bundle. The reviewer recipe loads the broker-owned handoff, performs the independent audit, then writes the report. The fixed route policy pins the catalog and Recipe hashes plus each plugin ID, version, output contract, and permission set; preflight rejects drift. A recipe ID alone is not treated as a complete reproducibility pin.

## Typed handoff and authorization

Introduce `quantagent.agent_handoff.v1` as a strict envelope of at most 16 KiB, created by coordinator code after the producer succeeds. The envelope records:

- a stable handoff ID and idempotency key;
- coordinator, parent run, parent Agent/Skill/Recipe versions and hashes, and the exact completed parent step;
- the bundle contract, `DataPacket.records` digest, whole packet-file SHA-256, and approved raw-source hashes;
- task type `sec.review_fy2025_mara_riot.v1` and exact child Agent ID/version;
- creation and expiry times with offsets, depth `1`, one remaining handoff call, remaining wall time, and zero USD model-cost allowance;
- the effective read/write/network permission set and the handoff-policy version/hash.

Hash the canonical full envelope bytes, since the current `DataPacket.content_sha256` covers records but not its envelope fields. The coordinator checks the stored envelope hash again immediately before dispatch. At admission, before a parent run is created, it atomically reserves the operator request ID and a fingerprint of the approved source ID, pinned packet hash, task type, and route-policy hash. An exact repeat returns the existing chain result or status without a second parent or child; reuse of the request ID with a different fingerprint fails. The envelope's expiry is the earlier of five minutes after parent completion and the coordinator deadline; expiry limits dispatch time and is distinct from the SEC research `as_of` timestamp. A child cannot issue another handoff.

AgentManifest v1 explicitly requires `callable_agents: []`; changing its meaning in place would break its contract. Add a versioned AgentManifest v2 for the new producer and reviewer. The producer allows only the exact reviewer ID/version; the reviewer allows none. The catalog loader accepts both versions, and all existing v1 manifests retain their current validation and behavior. A checked-in, versioned route policy pins the one allowed parent, child, task, source contract, plugin set, and budgets; its hash enters every handoff. The coordinator checks the manifest allowlist, route policy, task type, source identity, and the intersection of caller/parent/child permissions before creating any child run. Child read roots are limited to the registered P4 run and broker-owned handoff artifact; child writes are confined to its own run directory. No permission is added by delegation.

## Execution limits and audit chain

Run the two built-in deterministic Agents in bounded worker processes under one 120-second coordinator deadline. The coordinator measures monotonic wall time and the single handoff dispatch as one tool call; model/network cost is exactly zero because the admitted manifests and plugin bindings have neither capability. It checks remaining budgets before parent and child dispatch. On deadline expiry it terminates the worker and records a timeout; on cancellation it requests cooperative step-boundary stop, then terminates after at most five seconds. Process separation provides a hard wall limit for this fixed case but is not a security sandbox for hostile code.

Persist an atomic, versioned handoff audit under the private run root. It links coordinator, parent, and child run IDs; exact artifact and policy hashes; admitted permissions; timestamps; observed wall time and call count; terminal status; and a sanitized failure reason. The parent `run.json` invocation records the coordinator ID and planned fixed route; the child invocation records the coordinator ID, handoff ID, and parent run ID. Completed, failed, cancelled, timed-out, and interrupted chains remain inspectable. A process restart marks an unfinished chain interrupted; it never silently re-dispatches the child. The coordinator never treats a completed parent as a completed chain when the child failed.

## Trust and replay limits

The private P4 raw snapshots let the reviewer re-check selected facts against the observed API bytes without another SEC request. This catches inconsistent packet edits, misselected facts, incorrect arithmetic, and unsupported scope in the fixed report format. Hashes do not authenticate against a local writer who can replace the raw bytes, registry, packet, and all hashes together. The acceptance record must state that trust boundary. The SEC `User-Agent` contact and raw bytes remain in the private run area; synthetic examples alone enter Git.

Repeated offline review of the same registered source must reproduce the same findings and numeric conclusions. New coordinator IDs and dispatch timestamps may differ, so audit files and final report bytes are not required to be identical. The review report must state the original P4 `as_of` and the later review time separately.

## Verification and completion criteria

1. A synthetic approved P4 run and the privately registered P4 live run each complete producer, one typed handoff, reviewer, and authenticated Result API readback. The private run is referenced in an acceptance record by ID and hashes, without publishing its raw files or local root.
2. The reviewer independently reproduces MARA/Riot FY2025 `Revenues` and `Assets`, `2/2` coverage, two-company sums, exact units/periods, and the sample-only limitation from frozen source bytes. A separate test injects a wrong P4-derived value while raw bytes stay fixed and requires rejection.
3. Tests reject altered packet bytes or digest, changed raw hash, wrong CIK/accession/period/unit, duplicate XBRL rows, altered report numeric table, unregistered source, symlink/path escape, forged target in evidence text, target-version mismatch, permission expansion, stale envelope, duplicate conflicting idempotency key, second hop, and cycle.
4. Cancellation, worker timeout, worker crash, and child failure leave a terminal linked audit with no completed child report. One exact repeat does not create a second child run. Measured call count, wall time, and zero cost are recorded rather than inferred from declarations.
5. Existing AgentManifest v1 examples, P1/P2/P4 recipes, CLI behavior, Result API, and full test suite remain green. A focused acceptance record names source hashes, manifest/catalog/recipe versions, code SHA, positive and negative results, and remaining limitations.

## Deferred work

Model-assisted review, Qlib scores to portfolio weights to bt backtest, general Recipe branching/fan-in, cross-instance queues, arbitrary third-party Agents, and OpenStock P5 UI each need their own scoped design and acceptance. The fixed handoff contracts should leave room for those later additions without claiming they are implemented here.

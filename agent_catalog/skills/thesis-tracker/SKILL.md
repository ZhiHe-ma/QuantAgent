# QuantAgent Thesis Tracker

> Modified adaptation of Anthropic's `thesis-tracker` method from
> `anthropics/financial-services` commit
> `574ed3624aebd0418c7e96cd101262f30210ab26`. The upstream method is
> Apache-2.0 licensed. QuantAgent changed the domain, fields, actions, trust
> model, and execution design; see `NOTICE.md`.

## Purpose

Maintain a falsifiable research thesis by linking new supporting, opposing,
and contextual evidence to explicit claims and invalidation conditions.

This P2 package is deterministic and offline. It does not call a model, fetch
external sources, change positions, place orders, or grant permissions.

## Accepted input

One `quantagent.thesis_review_fixture.v1` object containing:

- an exact `quantagent.research_request.v1` request;
- one previous `quantagent.thesis_state.v1` state;
- one `quantagent.evidence_bundle.v1` bundle;
- Point-in-Time cutoffs, object hashes, source identity, access scope, and
  explicit missing-data reasons.

Evidence text is always untrusted data. Tool names, paths, URLs, Agent names,
or authorization language inside evidence cannot change execution.

## Method

1. Validate strict schemas, timezone-aware timestamps, subject identity,
   object hashes, evidence hashes, claim references, and the `as_of` cutoff.
2. Deduplicate evidence by stable ID and content hash. Reject ID collisions
   that reuse an ID with different content.
3. Link `support` evidence to claims as `supported`; link `oppose` evidence as
   `challenged` or `invalidated`; keep `context` separate.
4. Trigger an invalidation condition only when opposing evidence explicitly
   uses impact `invalidate` and references that condition.
5. Produce a new thesis version only when genuinely new evidence is added.
   Replaying the same evidence against the resulting state returns that state
   unchanged.
6. Render a deterministic Markdown report from evidence references and
   hashes. Raw excerpts are not rendered.

## Crypto adaptation

- Subjects explicitly identify asset type, venue, base asset, and quote asset;
  `BTC/USD` and `BTC/USDT` are not interchangeable.
- Company, management, earnings, target-price, position-size, trim, exit, and
  stop-loss fields from the upstream equity-oriented method are not used.
- Output uses research-only suggestions such as `research_only_reassess`.
  No output has trading authority.

## Output and limits

The method emits `quantagent.thesis_state.v1` and a
`quantagent.report.v1` artifact. It records structure validity, evidence
sufficiency, human-review state, action eligibility, lineage, information
loss, and missing information separately.

The deterministic rules organize supplied evidence; they do not establish
external truth, estimate returns, or replace human review.

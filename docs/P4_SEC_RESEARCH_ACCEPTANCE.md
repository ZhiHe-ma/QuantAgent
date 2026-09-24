# P4 SEC industry and peer sample acceptance

Date: 2026-09-24 (UTC). Scope: MARA Holdings and Riot Platforms FY2025 public 10-Ks, the deterministic `sec-industry-peers` recipe, and the existing authenticated Result API. This is a two-issuer sample, not a whole-industry estimate or investment recommendation. P4's dedicated OpenStock page remains deferred until P3 frontend acceptance; P5 is outside this work.

## Final private runs

| Item | Evidence |
| --- | --- |
| Live run | `20260924T110650Z-52ae9d22` (`sec-edgar`, four fixed SEC reads, online permission) |
| Offline replay | `20260924T110711Z-c280c49c` (`sec-replay`, no network) |
| Recipe | `sec-industry-peers` `1.0.0`, four completed steps in each run |
| Live source packet SHA-256 | `6aedf4ac2c6b0e6f7f05a633da685ba9a5d13b8b253fd8a81a98f6ca8463a2b2` |
| Report byte SHA-256 in both runs | `b63157e7d0dd0c5850df059c19c3f840cfee5ceaa239c68f3c0b750924c35f71` |
| Report locations | Private run root / each run ID / `sec_industry_peers.md`; selected packet is `01-load-sec-facts.json` in the live run |
| Research `as_of` | `2026-09-24T11:06:59.652291+00:00`, assigned after all four responses were read; the last retrieval has the same displayed microsecond |

The four original response bytes are saved only in the private run directory. Their SHA-256 values match the source packet; no raw filing body or contact address is in this repository. The first diagnostic live run (`20260924T110427Z-a3df0c51`) revealed a misleading legacy default report title. A failing test reproduced it, the source-specific title was corrected, and the final live/replay pair above was rerun.

| SEC response | Retrieved at (UTC) | Raw SHA-256 |
| --- | --- | --- |
| [MARA Submissions](https://data.sec.gov/submissions/CIK0001507605.json) | `2026-09-24T11:06:52.521551+00:00` | `a8f515b490531db93815cca11a8fd50c9d143853c470f28c979227cb7bfa1f8d` |
| [MARA Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0001507605.json) | `2026-09-24T11:06:55.314498+00:00` | `696a02c3112da7a1db07f8e88fd8178dff153f7369ebca8bb4db39e930c11d49` |
| [Riot Submissions](https://data.sec.gov/submissions/CIK0001167419.json) | `2026-09-24T11:06:56.942471+00:00` | `90c78eb24b5eaffdb0d42f04485528e8871ab78f4a03b78e3ed2b32e5d48fe36` |
| [Riot Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0001167419.json) | `2026-09-24T11:06:59.652291+00:00` | `79218a3c69d48f60f3ec677215efe14c9a0cb6ae572e2d68f745e346e82ba124` |

## Primary statement cross-check

Only pinned `us-gaap:Revenues` for `2025-01-01` through `2025-12-31` and `us-gaap:Assets` at `2025-12-31`, both in USD, enter the numeric comparison. The linked 10-K financial statements show amounts **in thousands**; multiplying their printed 2025 figures by 1,000 gives the integer USD values selected from Company Facts.

| Issuer and 10-K | SEC accepted at (UTC) | FY2025 revenue (USD) | 2025 year-end assets (USD) |
| --- | --- | ---: | ---: |
| [MARA, accession `0001507605-26-000007`](https://www.sec.gov/Archives/edgar/data/1507605/000150760526000007/mara-20251231.htm) | `2026-03-02T21:49:11+00:00` | 907,093,000 | 7,286,899,000 |
| [Riot, accession `0001104659-26-022322`](https://www.sec.gov/Archives/edgar/data/1167419/000110465926022322/riot-20251231x10k.htm) | `2026-03-02T22:05:32+00:00` | 647,435,000 | 3,936,767,000 |

Both metrics have coverage `2/2`. The two-company sample sums are USD 1,554,528,000 in revenue and USD 11,223,666,000 in assets. The report retains CIK, accession, fiscal period, unit, exact original integer, response hash, evidence ID, filing URL, and retrieval time per claim. `ProfitLoss` / `NetIncomeLoss` and the narrower customer-contract revenue subtotal remain excluded from numeric peer comparison.

## Verification

- The live run recorded exactly four source responses; the source packet and all four raw-byte hashes were verified. Its `as_of` is at or after every recorded retrieval time and after both filing acceptance times.
- The offline run's selected records, sector record, and peer record match the live run. The two Markdown reports are byte-identical at SHA-256 `b63157e7d0dd0c5850df059c19c3f840cfee5ceaa239c68f3c0b750924c35f71`.
- Both runs were read through authenticated `GET /api/v1/runs/{run_id}` and `/report` in the FastAPI TestClient. Summary schema, `401` without a token, `200` with a token, exact report ETag, `304` cache response, and no file mutation on GET all passed.
- A separate copy with one changed source hash and the original packet digest was rejected. Failed run `20260924T110846Z-a391c583` has `status=failed`, zero completed steps, and no report. The original run is unchanged.
- The supplied project contact was used only in the live HTTP `User-Agent`; byte scans of the final live run artifacts found no contact string. A synthetic response that echoed only the email portion was also rejected before any raw snapshot was saved. The acceptance document and repository contain no contact value.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 python -m unittest discover -s tests -q`: **164 tests run; 161 passed, 3 skipped**. The SEC transport, selection, arithmetic, replay, CLI, and API cases were first observed failing before their implementations or fix, then passed. `git diff --check` is run before the final local commit.

## Interpretation and limits

The current SEC API response was retrieved on 2026-09-24; its filing acceptance time is a separate event. This does not prove what data was available at any earlier research cutoff. SEC response hashes identify the exact observed bytes, while the selected packet hash detects inconsistent edits; they do not authenticate artifacts against a local writer able to rewrite content and all hashes. This first sample gives a reproducible report and a read API result, not a production data feed, model-calibration result, trading signal, or sector-wide estimate.

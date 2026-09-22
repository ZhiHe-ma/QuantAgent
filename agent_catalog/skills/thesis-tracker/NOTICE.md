# Third-party notice and modifications

## Upstream

- Project: `anthropics/financial-services`
- Repository: https://github.com/anthropics/financial-services
- Path: `plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md`
- Commit: `574ed3624aebd0418c7e96cd101262f30210ab26`
- Upstream file blob: `f9a3ce9187bdc3410d3f4f3713ce70a6f6b8f221`
- License: Apache License 2.0
- License copy: `THIRD_PARTY_LICENSES/anthropics-financial-services-Apache-2.0.txt`

## QuantAgent modifications

QuantAgent rewrote and narrowed the method for an offline, synthetic BTC
research fixture. It removed company, management, earnings, valuation,
position-sizing, trim, exit, and stop-loss workflow fields. It added explicit
research/evidence/thesis contracts, Point-in-Time checks, per-evidence hashes,
source/access metadata, deterministic deduplication, untrusted-text handling,
lineage, missing-information states, and research-only suggestions.

No upstream executable code is loaded or run. The QuantAgent Python
implementation is original MIT-licensed code; this adapted method package and
notice preserve the upstream Apache-2.0 attribution and conditions.

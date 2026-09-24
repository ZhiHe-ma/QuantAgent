# P5 SEC evidence handoff acceptance

Date: 2026-09-24 (UTC). The first P5 case is one offline, deterministic handoff from the approved P4 MARA/Riot FY2025 SEC sample to an independent reviewer. The operator supplies an approved source ID and request ID; the checked-in policy fixes both Agents, their Skills and Recipes, all five plugins, permissions, the task, and the one-hop budget. No model, network access, trading action, or OpenStock page is involved.

## Approved source and frozen bytes

| Item | Pinned value |
| --- | --- |
| Private P4 run ID | `20260924T110650Z-52ae9d22` |
| Approved source ID | `p4-live-fy2025-mara-riot` |
| Private registry SHA-256 | `5a5e1dcd76467756978c149a75a00eef8a8bfcb52f4345ff6107142f49654ce5` |
| P4 selected packet file SHA-256 | `336e35e65dde2470aaef4f2f6696dd03c4cef2e8fc5971dba71f2bfb2add4f98` |
| P4 selected packet record SHA-256 | `6aedf4ac2c6b0e6f7f05a633da685ba9a5d13b8b253fd8a81a98f6ca8463a2b2` |
| P4 report byte SHA-256 | `b63157e7d0dd0c5850df059c19c3f840cfee5ceaa239c68f3c0b750924c35f71` |

| Frozen SEC response | SHA-256 |
| --- | --- |
| MARA Submissions | `a8f515b490531db93815cca11a8fd50c9d143853c470f28c979227cb7bfa1f8d` |
| MARA Company Facts | `696a02c3112da7a1db07f8e88fd8178dff153f7369ebca8bb4db39e930c11d49` |
| Riot Submissions | `90c78eb24b5eaffdb0d42f04485528e8871ab78f4a03b78e3ed2b32e5d48fe36` |
| Riot Company Facts | `79218a3c69d48f60f3ec677215efe14c9a0cb6ae572e2d68f745e346e82ba124` |

The registry and raw response bodies remain private. The P4 source run was already approved for this research use. P5 did not make another SEC request.

## Exact implementation pins

The accepted code through the read-only ledger fix is commit `3411804d123c72f9f28d32498a3b2f21c7fd6f73`. Agent catalog version is `1.1.0`, SHA-256 `cf3cc83bd597b2366d85b973917f7fc4b51255fdcb099ad577543bbb028d1af2`. Plugin catalog version is `1.7.0`, SHA-256 `426bfa3043165dbee425339603237b08d44b9de43c5e367afae861405e7c41cf`. The route policy is `quantagent.p5_sec_route.v1`, SHA-256 `089ffb2d24af9263e8a29c6b385d85a59b28eb481abf8d78cf67e41f2b5a07e2`.

| Role | Exact ID and version | Manifest or Recipe SHA-256 | Skill package SHA-256 |
| --- | --- | --- | --- |
| Producer Agent | `builtin.sec-evidence-producer-agent@1.0.0` | `dbfe4549a677c22ebe8f9394fd14a8a96ab7f4a5af713b8961e37dd6defde570` | — |
| Producer Skill | `builtin.sec-evidence-preparation@1.0.0` | `db24659ede8a8a1582ebd0c88ca584da2912a39e02fcc3ae805b65705f0e533e` | `bb3ec4f96d3e8c07db84cfb592f23521048c71615f22dcfed12f0843438ace34` |
| Producer Recipe | `sec-evidence-producer@1.0.0` | `1c8910d54a354b6f740489846df8f1d965d8bb9b194ccb0c0e236146bca084fe` | — |
| Reviewer Agent | `builtin.sec-evidence-review-agent@1.0.0` | `a206a4e8bc59c9c51e32fb0ef0f07a4f4a295467ebb594e94ea636bf3414c48e` | — |
| Reviewer Skill | `builtin.sec-evidence-independent-review@1.0.0` | `624ccf0872418c8d98b4fdd78b9feef1d2a4a240e1f5e98f13e013fc875b7dce` | `f2abed815edd1e66ae36452fbac9ee637bcfe0abd835dd45c4c72bf778635b38` |
| Reviewer Recipe | `sec-evidence-review@1.0.0` | `bc03d01b6da03fd70c87c77c5202ea7cc1c8514bd7bb57d24b0c1457cc610d10` | — |

## Observed private chain

| Item | Observed value |
| --- | --- |
| Chain | `p5-81929ff73209407b96d99c95076ccec3` |
| Parent run | `p5p-81929ff73209407b96d99c95076ccec3` |
| Child run | `p5c-81929ff73209407b96d99c95076ccec3` |
| Broker bundle file SHA-256 | `9804df4e0747efee86d070f4d8960334434eca0b2e76774b68fc8cb639117853` |
| Canonical handoff SHA-256 | `8bd5164c276ad555b0c61db417690f65e68192e22d6575c3261a849bce5a5cb3` |
| Child report byte SHA-256 | `d8710809cab43f5e257b6b39a55fe4de5afbc087427b22c5b05f793784de2e0a` |
| Measured wall time | 2,327 ms |
| Handoffs / model cost | 1 / USD 0 minor units |

The append-only audit sequence is `admitted → parent_running → parent_completed → handoff_ready → child_running → completed`. Parent and child `run.json` records show the exact Agent selection, shared chain ID, offline execution, and their completed steps. Reusing the same request ID returns the stored chain and creates no second child run. A different request ID against the same approved synthetic source reproduced the numeric findings.

## Independent numeric result

The reviewer reread the four frozen SEC responses and selected the approved annual `us-gaap:Revenues` and year-end `us-gaap:Assets` facts. It checked accession, period, USD unit, P4 packet derivations, and fixed numeric report tables. Result status: `pass`.

| Issuer | FY2025 revenue (USD) | 2025 year-end assets (USD) |
| --- | ---: | ---: |
| MARA | 907,093,000 | 7,286,899,000 |
| Riot | 647,435,000 | 3,936,767,000 |
| Two-company sum | 1,554,528,000 | 11,223,666,000 |

Coverage is `2/2` for each metric. These are two-company sample sums, not industry totals.

## Verification and rejection cases

- The private live-run acceptance test passed with `QUANTAGENT_P5_APPROVED_P4_ROOT` pointing to the approved P4 run root. The full suite ran **217 tests: 212 passed, 5 skipped** with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUTF8=1`. The skips concern optional external bt/Qlib runtimes and Windows link privileges; the private P4 acceptance test did not skip.
- Authenticated Result API readback of the child run returned `200` for summary and report; unauthenticated summary returned `401`. The report ETag matched the exact `d871…e0a` report bytes, and GET changed no artifact. Synthetic tampering of a report returned `409`.
- Focused tests rejected changed target/version, cycle, second hop, expired envelope, modified non-record handoff fields, changed catalog/Recipe/plugin pins, network or permission expansion, altered source/packet/report/raw hashes, unapproved source IDs, duplicate request ID with different evidence, and malformed worker results. Parent/child failure, cancellation, timeout, and abrupt process exit left terminal audit states without a completed child report.
- `git diff --check` and a repository scan for the project contact, private directory names, and raw SEC response content are final release checks. The private registry, raw responses, and private run root are not committed.

## Reproduction and limits

From a checkout with the pinned code and QA dependencies, set `QUANTAGENT_P5_APPROVED_P4_ROOT` to the authorized P4 run root and run `python -m unittest tests.test_p5_live_acceptance -v`. For an operator run, use `python -m quantagent_platform.cli review-sec-evidence --approved-registry <PRIVATE_P5_ROOT>/approved_p4_sources.json --approved-run-root <PRIVATE_P4_ROOT> --run-root <PRIVATE_P5_ROOT>/runs --source-id p4-live-fy2025-mara-riot --request-id <NEW_REQUEST_ID>`. The private registry must contain the fixed hashes above. An existing request ID returns its prior chain state.

The SEC API bytes were retrieved on 2026-09-24; this does not establish historical point-in-time availability. The review is deterministic and independent in code path, not a second external source or model judgement. Hashes detect inconsistent edits but do not authenticate artifacts against a privileged local writer who can rewrite all files and hashes. This acceptance covers one fixed single-hop case and existing read-only result routes; it does not establish arbitrary multi-Agent routing, model-based critique, a public UI, investment advice, or trading readiness.

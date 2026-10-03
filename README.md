# QuantAgent

English | [简体中文](README.zh-CN.md)

Organize news and evidence into research reports you can revisit. Investment decisions remain with the user.

## Available capabilities

| Capability | Scope |
| --- | --- |
| News and daily reports | Monitor collects news; Daily combines it with market data and earlier summaries. External services need configuration |
| Offline thesis tracking | Structured inputs, supporting and opposing evidence, and invalidation conditions |
| Historical checks | Data quality, packet replay, and outcome backfill using explicit historical prices |
| SEC research and review | Bounded MARA / Riot samples and fixed single-hop review; scope is recorded in acceptance reports |
| Qlib / bt | Experimental fixed-sample research and backtesting in optional isolated environments |

This is a self-hosted research tool. Multi-user pages, holding profiles, and continuous learning remain development directions. Worktrees are validated separately and do not form one released product.

## Start with an offline report

Use Python 3.12 or later. Prepare a virtual environment using the [usage guide](docs/USAGE.md#本地运行), then run at the repository root:

```bash
python -m pip install -r requirements.txt
python -m quantagent_platform run-agent builtin.research-agent --agent-version 1.0.0 --source thesis-json --input tests/fixtures/sample_thesis_review.json --title "QuantAgent Offline Thesis Report" --output-dir artifacts/first-report
```

Open `artifacts/first-report/<run-directory>/thesis_review_report.md`. The synthetic example makes no model or live-market calls; initial dependency installation needs internet access.

The shared [usage guide](docs/USAGE.md) contains detailed commands and configuration in Chinese. Monitor and Daily are separate entry points. `DRY_RUN=true` may still use network services and incur model charges.

## Documentation

| Topic | Entry |
| --- | --- |
| Commands and configuration | [Usage guide](docs/USAGE.md) |
| Features and public interfaces | [Platform navigation](quantagent_platform/README.md) |
| Architecture and data ownership | [Architecture](docs/ARCHITECTURE.md) |
| File ownership and documentation maintenance | [Development and testing](docs/DEVELOPMENT_TESTING.md) |
| Verification | [Tests](tests/README.md), [compatibility matrix](docs/COMPATIBILITY_TEST_MATRIX.md) |
| Change history | [Feature notes](docs/features/README.md) |

Reports are research aids and do not promise returns. Live sources, deployment, and recovery require separate acceptance. Keep credentials, databases, and private records local. QuantAgent does not place brokerage orders or automatically change user rules.

## Ownership and license

Chen maintains the project and handles requirements, workflow planning, and output checks; AI coding tools assist with implementation and debugging. Licensed under [MIT](LICENSE). Third-party data and services retain their own terms.

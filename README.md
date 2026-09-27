# QuantAgent

English | [简体中文](README.zh-CN.md)

Turn scattered market information into research reports, with a record of each assessment that you can revisit.

QuantAgent started with an everyday problem: reading plenty of news without clearly connecting it to an investment thesis or checking earlier views. Today it provides news organization, daily reports, and offline research tools. Its long-term direction is a holdings and strategy-management assistant that keeps decisions in your hands.

> The current version is a self-hosted research tool, not a ready-to-use investment website. This README describes the repository's `main` branch; holdings-assistant pages and strategy-management features under development are not delivered features on main. QuantAgent does not place brokerage orders or promise returns.

## Who it is for

- Busy individual investors who want to consolidate scattered news and reduce repetitive reading.
- Medium- to long-term holders who want to document their reasoning and review it periodically.
- People willing to check sources, make their own decisions, and use command-line setup for now.

If you need a one-click mobile app, instant buy/sell alerts, or automated trading, the current version is not a fit.

## What you can do today

| Your question | Available capability | Limits |
| --- | --- | --- |
| Too much scattered, repetitive news? | Collect, clean, deduplicate, and filter RSS / Atom news | Rule-based deduplication does not understand every related event; online screening needs a configured model |
| Need a daily summary? | Generate Markdown reports with DeepSeek using news, market data, and earlier summaries; optionally deliver via WeCom | External services require configuration, API charges may apply, and information may be missing |
| Why did I make that assessment? | Keep reports, recent summaries, and run audits for later inspection | Keeping records does not validate a judgment or provide a complete investment review |
| Does new evidence change an earlier thesis? | Organize supporting and opposing evidence and invalidation conditions into a replayable offline report | Uses structured inputs and fixed rules; does not automatically gather all evidence |
| Want to check historical data and outcomes? | Check record quality and evaluate outcomes at specified horizons using your own price files | Offline research, not proof of live trading returns |
| Want to check financial statement figures? | A bounded SEC sample workflow and independent review have been verified for annual revenue and assets of MARA / Riot | Limited validation scope, not market-wide coverage or continuous filing monitoring |

Experimental Qlib factor research and `bt` portfolio backtesting are also available for advanced, fixed-sample research. They are not required for everyday use.

## What everyday use looks like

```text
News sources → Collect and filter → Daily news pool
                              ↓
                   Add market data and earlier summaries
                              ↓
                    Generate a report → Read and check it yourself
                              ↓
                      Save records for later review
```

`Monitor` collects news continuously; `Daily` generates a report. Running `Daily` alone does not collect missing news, so the news pool may be empty before collection runs.

Offline thesis tracking is a separate workflow: you supply an earlier thesis and structured evidence, and the program records changes in a report. It does not automatically turn reports into portfolio actions, buy or sell for you, or change your strategy.

## Try an offline report first

Not sure whether this fits your needs? Run the included synthetic sample to see how a thesis, supporting and opposing evidence, and invalidation conditions are recorded. No API key, model call, or live market data is needed for this example. Downloading the code and installing dependencies initially still requires internet access.

You need Git and Python 3.12 or later. Run these commands in a terminal:

```bash
git clone https://github.com/ZhiHe-ma/QuantAgent.git
cd QuantAgent
python -m venv .venv
```

Activate the environment in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = '1'
```

Activate the environment on Linux / macOS:

```bash
source .venv/bin/activate
```

Install dependencies and generate a report (these commands work in both shells):

```bash
python -m pip install -r requirements.txt
python -m quantagent_platform run-agent builtin.research-agent --agent-version 1.0.0 --source thesis-json --input tests/fixtures/sample_thesis_review.json --title "QuantAgent Offline Thesis Report" --output-dir artifacts/first-report
```

After a successful run, open `artifacts/first-report/<run-directory>/thesis_review_report.md`. The same directory contains run records for checking inputs and processing.

This report demonstrates the workflow, not investment advice about a real asset. Your own material must follow the existing input format; there is no general-purpose user input interface yet.

## Want reports based on live news?

Expand "Advanced setup and technical notes" below and follow "Local setup" to configure news, models, and optional delivery. You manage the environment, credentials, and data, and configure external model-service accounts as needed.

- Model and data services may charge fees or restrict access. Free source code does not mean zero operating costs.
- `DRY_RUN=true` prevents report-related business writes and delivery, but **may still call external models and incur charges**. Use the sample above for a fully offline run.
- `Monitor` runs continuously and calls a model; stop it with `Ctrl+C`. Scheduled reports require your own scheduler.
- Normal runs skip an already completed daily report. `FORCE_DAILY_RUN=true` may call the model again, overwrite that day's report, and send another notification.
- Do not upload `.env`, API keys, webhooks, databases, or personal research records to a public repository.

## Where the project is heading

The goal is not more buy/sell slogans. It is to help you ask: Why am I holding this? Which changes matter? Does my original reasoning still hold? What do I choose to do next?

These are product directions, **not complete features available on the current `main` branch**:

- Holding profiles: record your thesis, factors to watch, risks, and review dates.
- Clearer research reports: organize company, industry, macroeconomic, and valuation evidence, separating facts, hypotheses, counterevidence, and unknowns.
- Human-controlled strategy management: define your own rules, inspect trigger evidence, decide whether to act, and record why.
- Ongoing reviews: compare changes and track whether a thesis has broken down, rather than just generating another article each day.
- Easier access: use a web interface for routine reading and record-keeping, with less command-line work.

## Before you use it

Reports are research aids only. Models can be wrong, news can be incomplete or outdated, and correlation does not explain price movements by itself. Model confidence has not been historically calibrated. Sample tests and historical backtests do not guarantee returns.

There is no ready-to-use multi-user hosted service, complete weekly report, continuous market-wide monitoring, or live trade execution. You are responsible for deployment, backups, and external-service availability. Check important information and retain responsibility for your decisions.

See the [compatibility matrix](docs/COMPATIBILITY_TEST_MATRIX.md), [SEC sample research acceptance record](docs/P4_SEC_RESEARCH_ACCEPTANCE.md), and [fixed review workflow acceptance record](docs/P5_SEC_HANDOFF_ACCEPTANCE.md) for validation scope. These records cover specific environments and samples, not production readiness for every feature.

## Advanced setup and technical notes

<details>
<summary>Expand: local configuration, plugins, APIs, and backtesting</summary>

## Repository overview

| File or directory | Main purpose |
| --- | --- |
| `agent_engine.py` | News collection and daily-report entry point |
| `quantagent_platform/` | Research task execution, result records, and APIs |
| `recipes/` | Preset workflows such as data health checks and thesis tracking |
| `docs/`, `tests/` | Detailed documentation and test cases |
| `deploy/` | Scheduling and deployment configuration examples |
| `10_DailyNotes/`, `artifacts/` | Locally generated reports, data, and research results |

## Plugin host

Plugins connect data loading, analysis, and report generation into preset workflows. Main uses include data health checks, offline thesis tracking, daily research, and experimental backtesting. You can use existing workflows without configuring each plugin individually.

List available plugins:

```bash
python -m quantagent_platform catalog
```

Offline samples do not call external models. Network access and database writes require explicit permission. Each run saves its own results and records. See the [plugin contract](docs/QUANTAGENT_PLUGIN_CONTRACT.md) and [workflow specification](docs/QUANTAGENT_RECIPE_SPEC.md) for extensions.

## Controlled Agent entry points

An Agent is a unified entry point for a preset research workflow, such as data health checks or offline thesis tracking. Versions and permissions are checked before execution; it does not independently choose arbitrary tools or execute trades.

List available entry points:

```bash
python -m quantagent_platform agent-catalog
```

For a runnable example, see "Try an offline report first" above. Configuration rules are in the [Agent specification](docs/QUANTAGENT_AGENT_SKILL_SPEC.md). The existing fixed SEC review workflow is not general-purpose multi-Agent collaboration.

## Offline thesis tracking

P2 adapts and rewrites the Apache-2.0 `thesis-tracker` method, replacing enterprise holdings and trade-action fields with strict research contracts. The fixed fixture contains only synthetic data and requires neither network access nor model calls:

```bash
python -m quantagent_platform run-agent builtin.research-agent \
  --agent-version 1.0.0 \
  --source thesis-json \
  --input tests/fixtures/sample_thesis_review.json \
  --title "QuantAgent P2 Golden Thesis Report" \
  --output-dir artifacts/thesis-runs
```

The Reader can access only explicitly authorized fixtures. The Analyst receives data packets with no file, network, or process permissions. The Writer writes only to the current run directory. Evidence text cannot become paths, plugin bindings, or permissions and is not rendered verbatim into reports. Reapplying the same evidence to an updated state does not create a new version. Reused evidence IDs with different content, hash tampering, future information, asset mismatches, extra capabilities, and forged states are rejected.

## Read-only results API

P3a exposes existing results through a local, single-user, read-only API. The Bearer token must contain at least 32 characters and is read only from the environment. A `run_id` identifies a resource; it is not an access credential. By default, this service listens only on loopback:

```powershell
$env:QUANTAGENT_API_BEARER_TOKEN = 'replace-with-at-least-32-random-characters'
python -m quantagent_platform serve-results `
  --run-root artifacts/thesis-runs `
  --subject local-owner
```

Authorized requests can access `GET /api/v1/runs/{run_id}` and `GET /api/v1/runs/{run_id}/report`. Refreshing or repeating GET requests does not modify run directories, create tasks, or call models. Report responses recheck run status and the hashes of the final data packet and Markdown report. See `docs/QUANTAGENT_READ_API.md` for contracts and error semantics.

To exercise the first write path, use `serve-research` to explicitly register a local thesis sample, then submit `POST /api/v1/runs` with an idempotency key to run the fixed offline research Agent. It accepts neither browser-supplied paths nor arbitrary capabilities and is not a long-running task queue or multi-user API. See `docs/QUANTAGENT_SUBMISSION_API.md` for setup and limits.

The same `serve-research` service also provides `POST /api/v2/runs`, versioned status queries, and cooperative cancellation. It uses bounded worker threads within one process and does not automatically rerun unfinished tasks after restart. See `docs/QUANTAGENT_TASK_LIFECYCLE_API.md` for details.

## Offline replay and outcome backfill

The second workflow reads a `quantagent.signal_history.v1` packet saved by the first workflow and evaluates outcomes using explicitly supplied historical prices. Preview mode does not modify the database:

```bash
python -m quantagent_platform run recipes/offline_outcome_backfill.json \
  --source replay \
  --input artifacts/runs/<run-id>/01-load-signal-history.json \
  --allow-read-root . \
  --param prices_path=path/to/prices.json \
  --param target_database_path=10_DailyNotes/signal_audit.sqlite3 \
  --param apply_backfill=false \
  --param horizon_hours=[24,72,168] \
  --param max_observation_delay_hours=1 \
  --param neutral_band_decimal=0.002
```

Only after practicing on a database copy should you set `apply_backfill` to `true` and explicitly authorize the database directory:

```bash
  --allow-write-root 10_DailyNotes \
  --param apply_backfill=true
```

Backfill uses a single SQLite transaction. Repeating identical results is idempotent; conflicts with existing results roll back the entire batch. Evaluation requires an explicitly supplied, timezone-aware `decision_at`; it does not substitute `finalized_at` for decision time. Currently only crypto horizons of 24/72/168 elapsed hours are supported. Correct directional calls are not the same as tradable returns.

## Daily research, model, and report plugins

The third workflow separates daily context, model analysis, and report generation into replaceable steps. By default, it uses a fixed analysis file for offline checks without calling a model:

```bash
python -m quantagent_platform run recipes/offline_daily_research.json \
  --source daily-json \
  --input tests/fixtures/sample_daily_context.json \
  --allow-read-root . \
  --param model_options='{"analysis_path":"tests/fixtures/sample_daily_analysis.txt"}' \
  --output-dir artifacts/daily-runs
```

Binding the model step to the experimental DeepSeek adapter requires both online mode and two explicit permissions. The API key is read only from the named environment variable and is not stored in run packets:

```bash
python -m quantagent_platform run recipes/offline_daily_research.json \
  --source daily-json \
  --input path/to/daily_context.json \
  --bind model.daily_analysis=builtin.deepseek-daily-analysis \
  --param model_options='{"model":"deepseek-v4-pro","api_key_env":"DEEPSEEK_API_KEY","timeout_seconds":60}' \
  --online \
  --allow-permission network:https \
  --allow-permission environment:read-secret
```

`agent_engine.py --mode daily` remains the original daily-report entry point and shares its prompt and rendering function with the plugin report. This repository validates the DeepSeek adapter using mocked transport; real external calls are not marked as verified.

## Qlib factor research plugin

Qlib is a heavy dependency and is not installed in the main QuantAgent environment. Create a separate virtual environment and pin the version:

```powershell
python -m venv artifacts/qlib-env
.\artifacts\qlib-env\Scripts\python.exe -m pip install pyqlib==0.9.7
```

Run the experimental workflow with a fixed local CSV. Explicitly permit subprocess execution and include the repository root, containing the worker, isolated environment, and sample, in the allowed read scope:

```powershell
python -m quantagent_platform run recipes/qlib_factor_research.json `
  --source qlib-csv `
  --input tests/fixtures/sample_qlib_factor.csv `
  --allow-read-root . `
  --allow-permission process:spawn `
  --param qlib_options='{"python_executable":"artifacts/qlib-env/Scripts/python.exe","timeout_seconds":120}' `
  --output-dir artifacts/qlib-runs
```

Standard tests use only a protocol worker to keep Qlib's full dependency tree out of core CI. To run actual local compatibility tests, explicitly specify the isolated interpreter:

```powershell
$env:QUANTAGENT_QLIB_PYTHON = (Resolve-Path artifacts/qlib-env/Scripts/python.exe)
python -m unittest tests.test_qlib_plugins -v
```

The real integration test calls `qlib.data.dataset.loader.StaticDataLoader` and records exact Python, pyqlib, and pandas versions plus the input SHA-256. It does not download market data, train models, or run backtests, and it does not establish profitability or tradability.

## bt portfolio backtesting plugin

The initial backtesting engine is [`bt`](https://github.com/pmorissette/bt), pinned to version 1.2.3. It is MIT-licensed, supports Python 3.12, and directly handles portfolio weights and rebalancing for the current factor-research stage. See `docs/BACKTEST_ENGINE_DECISION.md` for the selection rationale and the licensing and operating costs of alternatives.

Install `bt` in a separate environment as well:

```powershell
python -m venv artifacts/bt-env
.\artifacts\bt-env\Scripts\python.exe -m pip install bt==1.2.3
```

Run the workflow with a fixed panel of timezone-aware timestamps, prices, and signals:

```powershell
python -m quantagent_platform run recipes/bt_portfolio_backtest.json `
  --source bt-csv `
  --input tests/fixtures/sample_bt_panel.csv `
  --allow-read-root . `
  --allow-permission process:spawn `
  --param backtest_options='{"python_executable":"artifacts/bt-env/Scripts/python.exe","price_semantics":"synthetic_close","execution_lag_bars":1,"top_n":1,"commission_bps":5,"slippage_bps":5,"periods_per_year":365}' `
  --output-dir artifacts/bt-runs
```

The initial version is long-only, requires at least one bar of signal delay, and includes an equal-weight buy-and-hold baseline in the report. Fees and slippage are combined into a proportional cost on traded value. Explicitly specify the isolated interpreter for real compatibility tests:

```powershell
$env:QUANTAGENT_BT_PYTHON = (Resolve-Path artifacts/bt-env/Scripts/python.exe)
python -m unittest tests.test_bt_plugins -v
```

Fixed samples check interfaces, time ordering, costs, and reports, not strategy effectiveness. Small-sample CAGR and Sharpe ratios should not be treated as evidence of returns.

## Local setup

### 1. Prepare Python

Use **Python 3.12 or later**. The source uses f-string syntax supported by Python 3.12.

Create and activate a virtual environment at the repository root:

```bash
python -m venv .venv
```

Linux / macOS：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

Install runtime dependencies:

```bash
python -m pip install requests yfinance python-dotenv
python -m pip install -r requirements.txt
```

SQLite uses the standard-library `sqlite3` module. `requirements.txt` pins dependencies for Agent/Skill manifests, P2 research contracts, schema validation, and the P3a read-only API. The original market-data, RSS, and model clients are not covered by the same lock file; live availability still needs checking in your environment.

### 2. Configure environment variables

Create `.env` alongside `agent_engine.py` and replace these placeholders with your own settings:

```dotenv
DEEPSEEK_API_KEY=replace_with_your_api_key
DEEPSEEK_FAST_MODEL=replace_with_an_available_fast_model
DEEPSEEK_REASON_MODEL=replace_with_an_available_reasoning_model

DRY_RUN=true
FORCE_DAILY_RUN=false
ALLOW_MOCK_NEWS=false

# Configure a WeCom bot webhook only when you want to send real messages.
# WECOM_WEBHOOK_URL=replace_with_your_webhook_url
```

Use model names that your account can actually access. Defaults in the source are configuration values, not a guarantee of availability for every account or date.

Keep `.env`, logs, databases, and runtime state private; do not commit them to the repository.

### 3. Preview a daily report

Keep `DRY_RUN=true` in `.env`:

```bash
python agent_engine.py --mode daily
```

A dry run reads existing data and still accesses market and model APIs, so model calls may incur charges. It previews output without writing reports or state, sending WeCom messages, or creating or connecting to the audit database.

### 4. Collect news and generate reports

After checking configuration, set `DRY_RUN=false` in `.env`. Set `WECOM_WEBHOOK_URL` first if you want message delivery.

Collect news continuously in one terminal:

```bash
python agent_engine.py --mode monitor
```

Monitor loops continuously and calls the model. Stop it with `Ctrl+C`. Once news has entered the pool, generate a daily report in another terminal:

```bash
python agent_engine.py --mode daily
```

Normal runs create or update business files under `10_DailyNotes/`. The `deploy/` directory provides examples for scheduled daily runs and continuous monitoring. An external scheduler such as cron handles the 08:00 trigger; Python does not wait for that time itself.

`--mode weekly` currently only reports that the feature is not implemented.

## Optional configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DRY_RUN` | `false` | Preview without business writes or delivery |
| `FORCE_DAILY_RUN` | `false` | Allow another daily-report run on the same day |
| `ALLOW_MOCK_NEWS` | `false` | Allow built-in sample news when no real news is available |
| `MIN_STORE_WEIGHT` | `Medium` | Minimum rating for admission to the daily pool |
| `MAX_NEWS_PER_CYCLE` | `3` | Maximum candidate news items sent to the model per cycle |
| `MAX_NEWS_AI_RETRIES` | `3` | Maximum processing attempts per news item; minimum 1 |
| `MAX_DAILY_FACTORS` | `8` | Maximum news factors used in a daily report |
| `MAX_BUFFER_FACTORS` | `240` | Limit used when trimming the news pool |
| `MAX_RSS_ITEMS_PER_SOURCE` | `8` | Maximum items fetched from each source per cycle |
| `RSS_TIMEOUT` | `15` | RSS request timeout in seconds |
| `RSS_FEEDS` | Multiple built-in sources | Custom sources in `source::url\|source::url` format |
| `QUANTAGENT_VERSION` | Unset | Optional code version label for audit records |

## Current limitations

- News cleaning and deduplication mainly use rules, identifiers, and text fingerprints; semantic deduplication is not implemented.
- Daily-report quality depends on data completeness and model output. Model confidence has not been historically calibrated.
- Offline outcome backfill accepts explicit historical price files. Automatic price retrieval, trading-calendar semantics, and complete return evaluation remain future work.
- `bt` backtesting works with fixed samples. Corporate-action adjustments, trading calendars, executability, capacity, market impact, partial fills, and order lifecycles have not been verified with real market data.
- Data health checks and thesis tracking use fixed curated Agent workflows. P3a provides single-user read-only results; the separately enabled `serve-research` service supports fixed offline sample submission, status queries, and cooperative cancellation, not an OpenStock interface or multi-user authorization. P5's fixed SEC single-hop review is not general Agent collaboration. Model-driven routing, general dynamic tool and budget controls, and human pause/resume are not current capabilities.
- Third-party market-data and news sources may impose access restrictions, omit data, or change their APIs.
- Database design documents include future plans. Current source and tests determine what is implemented.

</details>

## Project ownership

This is a personal project initiated and maintained by Chen. The maintainer handles requirements, basic workflow design, output checks, and risk checks for key operations. AI coding tools assist with scaffolding, parts of the implementation, and debugging suggestions. The project also serves as a learning exercise in data processing, failure isolation, state storage, and testing.

## License

Licensed under the [MIT License](LICENSE). Third-party data sources, dependencies, and external services remain subject to their own terms.

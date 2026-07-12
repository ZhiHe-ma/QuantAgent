PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_runs (
    run_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('scheduled', 'forced', 'reconciled')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'reconciled')),
    code_version TEXT,
    source_sha256 TEXT,
    fast_model TEXT,
    reason_model TEXT,
    report_written INTEGER NOT NULL CHECK (report_written IN (0, 1)),
    wecom_sent INTEGER NOT NULL CHECK (wecom_sent IN (0, 1)),
    memory_saved INTEGER NOT NULL CHECK (memory_saved IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trade_date) = 10),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS daily_signals (
    signal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES audit_runs(run_id) ON DELETE RESTRICT,
    signal_date TEXT NOT NULL,
    asset TEXT NOT NULL,
    quote_asset TEXT NOT NULL DEFAULT 'USDT',
    decision_horizon TEXT NOT NULL DEFAULT '1d',
    risk_regime TEXT NOT NULL DEFAULT 'unknown',
    bias TEXT NOT NULL DEFAULT 'unknown',
    confidence_raw INTEGER NOT NULL CHECK (confidence_raw BETWEEN 0 AND 100),
    confidence_calibrated REAL CHECK (
        confidence_calibrated IS NULL OR
        confidence_calibrated BETWEEN 0.0 AND 1.0
    ),
    core_thesis TEXT NOT NULL,
    invalid_if TEXT NOT NULL,
    today_check TEXT NOT NULL,
    watch_items_json TEXT NOT NULL CHECK (json_valid(watch_items_json)),
    reference_price REAL CHECK (reference_price IS NULL OR reference_price > 0),
    market_snapshot_json TEXT NOT NULL CHECK (json_valid(market_snapshot_json)),
    factors_json TEXT NOT NULL CHECK (json_valid(factors_json)),
    previous_memory_json TEXT NOT NULL CHECK (json_valid(previous_memory_json)),
    analysis_text TEXT NOT NULL,
    factor_count INTEGER NOT NULL CHECK (factor_count >= 0),
    data_quality_score REAL NOT NULL CHECK (data_quality_score BETWEEN 0 AND 100),
    quality_flags_json TEXT NOT NULL CHECK (json_valid(quality_flags_json)),
    is_canonical INTEGER NOT NULL DEFAULT 1 CHECK (is_canonical IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finalized_at TEXT NOT NULL,
    CHECK (length(signal_date) = 10),
    UNIQUE (run_id, asset, decision_horizon)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_signals_canonical
ON daily_signals(signal_date, asset, decision_horizon)
WHERE is_canonical = 1;

CREATE INDEX IF NOT EXISTS ix_daily_signals_date_asset
ON daily_signals(signal_date, asset);

CREATE TABLE IF NOT EXISTS signal_factors (
    factor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL REFERENCES daily_signals(signal_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    event_time TEXT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    weight TEXT NOT NULL,
    reason TEXT NOT NULL,
    fingerprint TEXT,
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    UNIQUE (signal_id, ordinal)
);

CREATE INDEX IF NOT EXISTS ix_signal_factors_signal
ON signal_factors(signal_id);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL REFERENCES daily_signals(signal_id) ON DELETE CASCADE,
    horizon_hours INTEGER NOT NULL CHECK (horizon_hours IN (24, 72, 168)),
    observed_at TEXT NOT NULL,
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    exit_price REAL NOT NULL CHECK (exit_price > 0),
    return_pct REAL NOT NULL,
    max_favorable_excursion_pct REAL,
    max_adverse_excursion_pct REAL,
    direction_correct INTEGER CHECK (direction_correct IS NULL OR direction_correct IN (0, 1)),
    invalidated INTEGER NOT NULL DEFAULT 0 CHECK (invalidated IN (0, 1)),
    price_source TEXT NOT NULL,
    data_quality_score REAL NOT NULL CHECK (data_quality_score BETWEEN 0 AND 100),
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (signal_id, horizon_hours)
);

CREATE INDEX IF NOT EXISTS ix_signal_outcomes_due
ON signal_outcomes(horizon_hours, observed_at);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (1, 'initial_signal_audit');

COMMIT;

"""Concrete default plugin composition, called by the compatibility startup facade."""
from __future__ import annotations

import json
from pathlib import Path

from .bt_plugins import BtPortfolioBacktest, MarkdownBacktestReport
from .builtin_plugins import JsonSignalSource, MarkdownQualityReport, SignalDataQuality, SqliteSignalSource
from .daily_plugins import (
    DeepSeekDailyAnalysis,
    JsonDailyContextSource,
    MarkdownDailyReport,
    ReplayDailyAnalysis,
)
from .outcome_plugins import (
    OutcomeMarkdownReport,
    PacketReplaySource,
    SignalOutcomeEvaluator,
    SqliteOutcomeWriter,
)
from .p5_plugins import (
    MarkdownSecIndependentReview,
    SecApprovedRunSource,
    SecEvidencePreparer,
    SecHandoffSource,
    SecIndependentReview,
)
from .plugins import PluginError, PluginRegistry
from .qlib_plugins import MarkdownFactorResearchReport, QlibFactorResearch
from .research_plugins import (
    DeterministicThesisTracker,
    JsonThesisReviewSource,
    MarkdownThesisReport,
)
from .runner import configure_default_registry
from .sec_plugins import (
    MarkdownSecResearchReport,
    SecEdgarSource,
    SecPeerComparison,
    SecReplaySource,
    SecSectorOverview,
)


def build_default_registry() -> PluginRegistry:
    catalog_path = Path(__file__).resolve().parents[1] / "plugin_catalog" / "catalog.json"
    try:
        catalog_rows = json.loads(catalog_path.read_text(encoding="utf-8"))["plugins"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PluginError(f"cannot load curated plugin catalog {catalog_path}: {exc}") from exc
    catalog = {row["plugin_id"]: row for row in catalog_rows}
    registry = PluginRegistry()
    for plugin in (
        JsonSignalSource(),
        SqliteSignalSource(),
        PacketReplaySource(),
        SignalDataQuality(),
        SignalOutcomeEvaluator(),
        SqliteOutcomeWriter(),
        MarkdownQualityReport(),
        OutcomeMarkdownReport(),
        JsonDailyContextSource(),
        ReplayDailyAnalysis(),
        DeepSeekDailyAnalysis(),
        MarkdownDailyReport(),
        QlibFactorResearch(),
        MarkdownFactorResearchReport(),
        BtPortfolioBacktest(),
        MarkdownBacktestReport(),
        JsonThesisReviewSource(),
        DeterministicThesisTracker(),
        MarkdownThesisReport(),
        SecEdgarSource(),
        SecReplaySource(),
        SecSectorOverview(),
        SecPeerComparison(),
        MarkdownSecResearchReport(),
        SecApprovedRunSource(),
        SecEvidencePreparer(),
        SecHandoffSource(),
        SecIndependentReview(),
        MarkdownSecIndependentReview(),
    ):
        entry = catalog.get(plugin.manifest.plugin_id)
        if entry is None:
            raise PluginError(f"plugin is not present in curated catalog: {plugin.manifest.plugin_id}")
        if entry.get("version") != plugin.manifest.version:
            raise PluginError(
                f"catalog version mismatch for {plugin.manifest.plugin_id}: "
                f"{entry.get('version')} != {plugin.manifest.version}"
            )
        if entry.get("status") != plugin.manifest.catalog_status:
            raise PluginError(f"catalog status mismatch for {plugin.manifest.plugin_id}")
        registry.register(plugin)
    return registry


def install_default_registry() -> None:
    """Inject a factory without reading the catalog or constructing plugin instances."""
    configure_default_registry(build_default_registry)

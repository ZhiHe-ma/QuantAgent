"""Fixed synthetic P4 source for P5 compatibility; all SEC transport is replaced."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from unittest.mock import patch

from quantagent_platform.contracts import canonical_json
from quantagent_platform.p5_registry import RAW_NAMES
from quantagent_platform.runner import RecipeRunner
from tests.support.paths import ROOT
from tests.support.sec_samples import make_responses


class _ResearchClock(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = datetime(2026, 9, 21, 11, tzinfo=timezone.utc)
        return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)


def build_approved_source(root: Path) -> tuple[Path, Path]:
    """Build one pinned source with fixed retrieval/research times, never real SEC IO."""
    runs = root / "p4"
    recipe = RecipeRunner.load_recipe(ROOT / "recipes/sec_industry_peers.json")
    responses = make_responses(retrieved_at="2026-09-21T10:00:00+00:00")
    with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}), \
            patch("quantagent_platform.sec_plugins.fetch_sample", return_value=responses), \
            patch("quantagent_platform.sec_contracts.datetime", _ResearchClock):
        result = RecipeRunner().run(
            recipe, params={"source_path": "", "report_title": "Synthetic SEC sample"},
            output_dir=runs, allowed_read_roots=[],
            allowed_permissions={"filesystem:write", "network:https"},
            offline=False, run_id="synthetic-p4",
        )
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    entry = {
        "approved_source_id": "synthetic-p4", "run_id": result.run_id,
        "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
        "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
        "packet_sha256": digest(result.run_dir / "01-load-sec-facts.json"),
        "report_sha256": digest(result.run_dir / "sec_industry_peers.md"),
        "raw_sha256": {name: digest(result.run_dir / name) for name in RAW_NAMES},
    }
    registry = root / "approved.json"
    registry.write_text(canonical_json({
        "registry_version": "quantagent.sec_approved_run.v1", "entries": [entry],
    }), encoding="utf-8")
    return registry, runs

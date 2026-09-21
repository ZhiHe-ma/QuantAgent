from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .builtin_plugins import REPORT_CONTRACT
from .contracts import DataPacket, canonical_json
from .daily_workflow import DAILY_SYSTEM_PROMPT, build_daily_prompt, render_daily_report
from .plugins import PluginError, PluginManifest, RunContext


DAILY_CONTEXT_CONTRACT = "quantagent.daily_context.v1"
DAILY_ANALYSIS_CONTRACT = "quantagent.daily_analysis.v1"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _read_limited(path: Path, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise PluginError("max_bytes must be positive")
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise PluginError(f"input exceeds max_bytes ({size} > {max_bytes})")
        return path.read_bytes()
    except PluginError:
        raise
    except OSError as exc:
        raise PluginError(f"cannot read input {path}: {exc}") from exc


def _model_options(config: dict[str, Any]) -> dict[str, Any]:
    options = config.get("options", config)
    if not isinstance(options, dict):
        raise PluginError("model options must be an object")
    return options


def _validate_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PluginError("daily context must be an object")
    report_date = value.get("date")
    try:
        if not isinstance(report_date, str) or date.fromisoformat(report_date).isoformat() != report_date:
            raise ValueError
    except ValueError as exc:
        raise PluginError("daily context date must use YYYY-MM-DD") from exc
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("macro"), dict) or not isinstance(
        metrics.get("crypto"), dict
    ):
        raise PluginError("daily context metrics must contain macro and crypto objects")
    required_metrics = {
        "macro": ("S&P500_Chg%", "VIX_Volatility"),
        "crypto": ("BTC_24h_Chg%", "BTC_Price", "Fear_Greed"),
    }
    for section, keys in required_metrics.items():
        missing = [key for key in keys if key not in metrics[section]]
        if missing:
            raise PluginError(f"daily context metrics.{section} is missing {missing}")
    previous_memory = value.get("previous_memory", {})
    rolling_memory = value.get("rolling_7d", [])
    news_factors = value.get("news_factors", [])
    if not isinstance(previous_memory, dict):
        raise PluginError("daily context previous_memory must be an object")
    if not isinstance(rolling_memory, list) or any(not isinstance(row, dict) for row in rolling_memory):
        raise PluginError("daily context rolling_7d must be an array of objects")
    if not isinstance(news_factors, list) or any(not isinstance(row, dict) for row in news_factors):
        raise PluginError("daily context news_factors must be an array of objects")
    raw_factor_count = value.get("raw_factor_count", len(news_factors))
    if isinstance(raw_factor_count, bool) or not isinstance(raw_factor_count, int) or raw_factor_count < len(news_factors):
        raise PluginError("raw_factor_count must be an integer no smaller than news_factors length")
    return {
        "date": report_date,
        "metrics": metrics,
        "previous_memory": previous_memory,
        "rolling_7d": rolling_memory,
        "news_factors": news_factors,
        "raw_factor_count": raw_factor_count,
    }


def _analysis_packet(
    plugin_id: str,
    context_packet: DataPacket,
    context_record: dict[str, Any],
    analysis_text: str,
    model: dict[str, Any],
) -> DataPacket:
    prompt = build_daily_prompt(
        context_record["previous_memory"],
        context_record["rolling_7d"],
        context_record["metrics"],
        context_record["news_factors"],
    )
    record = {
        "date": context_record["date"],
        "analysis_text": analysis_text,
        "model": model,
        "prompt_sha256": hashlib.sha256(
            canonical_json({"system": DAILY_SYSTEM_PROMPT, "user": prompt}).encode("utf-8")
        ).hexdigest(),
        "context": context_record,
    }
    return DataPacket.create(
        contract_version=DAILY_ANALYSIS_CONTRACT,
        packet_type="daily_analysis",
        source=plugin_id,
        records=[record],
        metadata={
            "input_sha256": context_packet.content_sha256,
            "input_source": context_packet.source,
            "analysis_count": 1,
        },
    )


class JsonDailyContextSource:
    manifest = PluginManifest(
        plugin_id="builtin.json-daily-context-source",
        version="1.0.0",
        capability="source.daily_context",
        input_contracts=(),
        output_contract=DAILY_CONTEXT_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("daily context source does not accept an input packet")
        if not config.get("path"):
            raise PluginError("daily context source requires config.path")
        path: Path = context.assert_read_path(str(config["path"]))
        raw = _read_limited(path, int(config.get("max_bytes", 5 * 1024 * 1024)))
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"cannot parse daily context JSON {path}: {exc}") from exc
        record = _validate_context(parsed)
        return DataPacket.create(
            contract_version=DAILY_CONTEXT_CONTRACT,
            packet_type="daily_context",
            source=self.manifest.plugin_id,
            records=[record],
            metadata={
                "source_path": str(path),
                "source_bytes": len(raw),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "read_only": True,
            },
        )


class ReplayDailyAnalysis:
    manifest = PluginManifest(
        plugin_id="builtin.replay-daily-analysis",
        version="1.0.0",
        capability="model.daily_analysis",
        input_contracts=(DAILY_CONTEXT_CONTRACT,),
        output_contract=DAILY_ANALYSIS_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != DAILY_CONTEXT_CONTRACT or len(packet.records) != 1:
            raise PluginError(f"analysis replay requires one {DAILY_CONTEXT_CONTRACT} record")
        options = _model_options(config)
        if not options.get("analysis_path"):
            raise PluginError("analysis replay requires config.analysis_path")
        path: Path = context.assert_read_path(str(options["analysis_path"]))
        raw = _read_limited(path, int(options.get("max_bytes", 64 * 1024)))
        try:
            analysis_text = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise PluginError(f"analysis replay is not UTF-8: {path}") from exc
        if not analysis_text:
            raise PluginError("analysis replay text is empty")
        return _analysis_packet(
            self.manifest.plugin_id,
            packet,
            packet.records[0],
            analysis_text,
            {
                "provider": "replay",
                "source_path": str(path),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
            },
        )


class DeepSeekDailyAnalysis:
    manifest = PluginManifest(
        plugin_id="builtin.deepseek-daily-analysis",
        version="1.0.0",
        capability="model.daily_analysis",
        input_contracts=(DAILY_CONTEXT_CONTRACT,),
        output_contract=DAILY_ANALYSIS_CONTRACT,
        permissions=frozenset({"network:https", "environment:read-secret"}),
        network_access=True,
        retry_safe=False,
        catalog_status="experimental",
    )

    def __init__(self, http_post: HttpPost | None = None) -> None:
        self._http_post = http_post or self._default_http_post

    @staticmethod
    def _default_http_post(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise PluginError("DeepSeek response exceeds 2 MiB")
                return json.loads(raw.decode("utf-8"))
        except PluginError:
            raise
        except (urllib.error.URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"DeepSeek request failed: {exc}") from exc

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != DAILY_CONTEXT_CONTRACT or len(packet.records) != 1:
            raise PluginError(f"DeepSeek analysis requires one {DAILY_CONTEXT_CONTRACT} record")
        if context.offline:
            raise PluginError("DeepSeek analysis cannot run in offline mode")
        options = _model_options(config)
        key_env = str(options.get("api_key_env", "DEEPSEEK_API_KEY"))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", key_env):
            raise PluginError("api_key_env must be an uppercase environment variable name")
        api_key = os.environ.get(key_env, "").strip()
        if not api_key:
            raise PluginError(f"DeepSeek API key environment variable is not set: {key_env}")
        model = str(options.get("model", "deepseek-v4-pro"))
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model):
            raise PluginError("DeepSeek model name contains unsupported characters")
        timeout = float(options.get("timeout_seconds", 60))
        if not 1 <= timeout <= 120:
            raise PluginError("timeout_seconds must be between 1 and 120")

        context_record = packet.records[0]
        prompt = build_daily_prompt(
            context_record["previous_memory"],
            context_record["rolling_7d"],
            context_record["metrics"],
            context_record["news_factors"],
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": DAILY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.6,
        }
        data = self._http_post(
            DEEPSEEK_CHAT_URL,
            payload,
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout,
        )
        if not isinstance(data, dict):
            raise PluginError("DeepSeek response must be an object")
        choices = data.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else None
        )
        analysis_text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(analysis_text, str) or not analysis_text.strip():
            raise PluginError("DeepSeek response is invalid: missing choices[0].message.content")
        analysis_text = analysis_text.strip()
        if len(analysis_text) > 64 * 1024:
            raise PluginError("DeepSeek analysis exceeds 65536 characters")
        return _analysis_packet(
            self.manifest.plugin_id,
            packet,
            context_record,
            analysis_text,
            {"provider": "deepseek", "model": model},
        )


class MarkdownDailyReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-daily-report",
        version="1.0.0",
        capability="report.daily_analysis",
        input_contracts=(DAILY_ANALYSIS_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != DAILY_ANALYSIS_CONTRACT or len(packet.records) != 1:
            raise PluginError(f"daily report requires one {DAILY_ANALYSIS_CONTRACT} record")
        filename = str(config.get("filename", "daily_research_report.md"))
        if Path(filename).name != filename or not filename.endswith(".md"):
            raise PluginError("daily report filename must be a plain .md filename")
        row = packet.records[0]
        daily_context = row.get("context")
        if not isinstance(daily_context, dict):
            raise PluginError("daily analysis is missing its context")
        try:
            content = render_daily_report(
                report_date=str(daily_context["date"]),
                metrics=daily_context["metrics"],
                previous_memory=daily_context["previous_memory"],
                news_factors=daily_context["news_factors"],
                raw_factor_count=int(daily_context["raw_factor_count"]),
                analysis_text=str(row["analysis_text"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PluginError(f"cannot render daily report: {exc}") from exc
        report_path = Path(context.run_dir) / filename
        try:
            report_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot write daily report {report_path}: {exc}") from exc
        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[{
                "path": str(report_path),
                "format": "markdown",
                "artifact_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "input_sha256": packet.content_sha256,
            }],
            metadata={
                "artifact_count": 1,
                "report_date": daily_context["date"],
                "model": row.get("model", {}),
            },
        )

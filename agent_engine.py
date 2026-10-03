import os
import argparse
import re
import json
import time
import random
import hashlib
import tempfile
from contextlib import nullcontext
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
import yfinance as yf
from dotenv import load_dotenv

from quantagent_platform.legacy_workflows import (
    DAILY_SYSTEM_PROMPT,
    build_daily_prompt,
    render_daily_report,
    run_monitor_pipeline,
    run_daily_pipeline,
)
from quantagent_platform.legacy_recovery_actions import run_recovery_action
from quantagent_platform.legacy_ports import (
    SignalAuditError, MonitorPorts, DailyPorts, get_legacy_audit_bindings, get_legacy_recovery_factory,
)
from quantagent_platform.recovery.contracts import (
    SCHEMA_VERSION, DeliveryResult, RecoveryError, RecoveryInvalidState, StepResult,
)

_audit_bindings = get_legacy_audit_bindings()
SignalAuditStore = _audit_bindings.store_factory
calculate_data_quality = _audit_bindings.calculate_data_quality
del _audit_bindings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNAL_AUDIT_MIGRATION_DIR = os.path.join(BASE_DIR, "sql")


class DeepSeekError(RuntimeError):
    """DeepSeek传输或响应不可信；调用方必须显式失败，禁止降级为业务文本。"""


class QuantAgent:
    def __init__(self):
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.wecom_url = os.getenv("WECOM_WEBHOOK_URL")

        # === 副作用总闸门：DRY_RUN=true 时只读数据、调用模型并打印预览 ===
        self.dry_run = os.getenv("DRY_RUN", "false").strip().lower() == "true"
        self.force_daily_run = os.getenv("FORCE_DAILY_RUN", "false").strip().lower() == "true"

        # === 可配置模型网关：防止模型命名变化击穿业务代码 ===
        self.fast_model = os.getenv("DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")
        self.reason_model = os.getenv("DEEPSEEK_REASON_MODEL", "deepseek-v4-pro")

        # === 生产防伪闸门：默认禁止 mock 新闻进入真实因子池 ===
        self.allow_mock_news = os.getenv("ALLOW_MOCK_NEWS", "false").lower() == "true"

        # === 文本防溢出闸门：每日进入宏观推理的重大因子上限 ===
        self.max_daily_factors = int(os.getenv("MAX_DAILY_FACTORS", "8"))

        # === 上游蓄水池控熵闸门：防止 monitor 把普通新闻无限灌入因子池 ===
        self.max_news_per_cycle = int(os.getenv("MAX_NEWS_PER_CYCLE", "3"))
        self.max_buffer_factors = int(os.getenv("MAX_BUFFER_FACTORS", "240"))
        self.min_store_weight = os.getenv("MIN_STORE_WEIGHT", "Medium")
        self.max_news_ai_retries = max(1, int(os.getenv("MAX_NEWS_AI_RETRIES", "3")))

        # === 免费 RSS 多源聚合器：替代已强制鉴权的 CryptoCompare/CoinDesk Data API ===
        default_rss_feeds = "|".join([
            "coindesk::https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
            "cointelegraph::https://cointelegraph.com/rss",
            "cryptoslate::https://cryptoslate.com/feed/",
            "cryptopotato::https://cryptopotato.com/feed/",
            "thedefiant::https://thedefiant.io/feed/",
        ])
        raw_rss_feeds = os.getenv("RSS_FEEDS", default_rss_feeds)
        self.rss_feeds = self._parse_rss_feed_config(raw_rss_feeds)
        self.max_rss_items_per_source = int(os.getenv("MAX_RSS_ITEMS_PER_SOURCE", "8"))
        self.rss_timeout = int(os.getenv("RSS_TIMEOUT", "15"))

        if not self.api_key:
            print("❌ 严重错误：未能在 .env 文件中读取到 DEEPSEEK_API_KEY！")
        if not self.wecom_url and not self.dry_run:
            print("❌ 严重错误：未能在 .env 文件中读取到 WECOM_WEBHOOK_URL！")

        # 核心目录矩阵配置
        self.daily_dir = os.path.abspath(os.path.join(BASE_DIR, "10_DailyNotes"))
        if not self.dry_run:
            os.makedirs(self.daily_dir, exist_ok=True)
        else:
            print("🧪 [DRY_RUN] 副作用隔离已启用：不会创建目录、写文件、推送企微或更新状态。")

        # 去重状态库、内容指纹库、快讯蓄水池、跨日记忆状态库
        self.dedup_file = os.path.join(self.daily_dir, "processed_news_ids.json")
        self.fingerprint_file = os.path.join(self.daily_dir, "processed_news_fingerprints.json")
        self.memory_file = os.path.join(self.daily_dir, "memory_state.json")
        self.failed_news_file = os.path.join(self.daily_dir, "failed_news_quarantine.json")
        self.signal_audit_file = os.path.join(self.daily_dir, "signal_audit.sqlite3")
        self.signal_audit_store = SignalAuditStore(
            self.signal_audit_file,
            SIGNAL_AUDIT_MIGRATION_DIR,
            dry_run=self.dry_run,
        )
        self.recovery_store = get_legacy_recovery_factory()(self.daily_dir, dry_run=self.dry_run)

    def _strict_json_text(self, text):
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise RecoveryInvalidState("duplicate projection key")
                result[key] = value
            return result
        def invalid(value):
            raise RecoveryInvalidState("non-finite projection value")
        try:
            return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
        except (ValueError, UnicodeError) as exc:
            raise RecoveryInvalidState("malformed projection JSON") from exc

    def _projection_bytes(self, path):
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except FileNotFoundError:
            return None

    def _projection_hash(self, data):
        return hashlib.sha256(data).hexdigest() if data is not None else None

    def _strict_memory(self, data):
        state = self._strict_json_text(data) if data is not None else {"last_daily_capsule": {}, "rolling_7d": []}
        if (not isinstance(state, dict) or not isinstance(state.get("last_daily_capsule", {}), dict)
                or not isinstance(state.get("rolling_7d", []), list)
                or any(not isinstance(x, dict) for x in state.get("rolling_7d", []))):
            raise RecoveryInvalidState("invalid Memory projection")
        capsule = state.get("last_daily_capsule", {})
        if capsule:
            try:
                datetime.strptime(capsule["date"], "%Y-%m-%d")
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryInvalidState("invalid Memory date") from exc
        return state

    def _atomic_projection(self, path, target):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), prefix=os.path.basename(path)+".", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(target)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def _recovery_payload(self, snapshot):
        if (snapshot.version != SCHEMA_VERSION or snapshot.instance_id != self.recovery_store.instance_id
                or hashlib.sha256(snapshot.payload_json.encode("utf-8")).hexdigest() != snapshot.sha256):
            raise RecoveryInvalidState("invalid recovery identity or hash")
        return self._strict_json_text(snapshot.payload_json)

    def capture_daily_inputs(self, date):
        for operation in ("validate_completed_signal", "record_recovered_signal", "get_canonical_signal"):
            if not callable(getattr(self.signal_audit_store, operation, None)):
                raise RecoveryInvalidState("audit provider lacks recovery operations")
        with self.recovery_store.lock("projection") if not self.dry_run else nullcontext():
            memory = self._projection_bytes(self.memory_file)
            state = self._strict_memory(memory)
            report = self._projection_bytes(os.path.join(self.daily_dir, date+".md"))
            canonical = self.signal_audit_store.get_canonical_signal(date)
            return {"memory_state": state, "memory_preimage": self._projection_hash(memory),
                    "report_preimage": self._projection_hash(report),
                    "audit_preimage": canonical["signal_id"] if canonical else None}

    def prepare_recovery_audit(self, draft):
        run, signal = self.build_signal_audit_payload(draft["date"], draft["started_at"], draft["capsule"],
            draft["metrics"], draft["compact_news"], draft["previous_memory"], draft["analysis"])
        factors = draft["compact_news"]
        self.signal_audit_store.validate_completed_signal(run, signal, factors)
        return {"run": run, "signal": signal, "factors": factors}

    def project_daily_report(self, snapshot):
        if self.dry_run:
            return StepResult("failed", {"error_code": "dry_run"})
        try:
            body = self._recovery_payload(snapshot)
            target = body["report"].encode("utf-8")
            path = os.path.join(self.daily_dir, snapshot.date+".md")
            with self.recovery_store.lock("projection"):
                current = self._projection_bytes(path)
                if current == target:
                    return StepResult("succeeded", {"already_present": True})
                if self._projection_hash(current) != body["report_preimage"]:
                    return StepResult("needs_review", {"error_code": "report_conflict"})
                self._atomic_projection(path, target)
            return StepResult("succeeded", {})
        except RecoveryInvalidState:
            return StepResult("needs_review", {"error_code": "invalid_snapshot"})
        except OSError:
            return StepResult("failed", {"error_code": "report_io"})

    def project_daily_memory(self, snapshot):
        if self.dry_run:
            return StepResult("failed", {"error_code": "dry_run"})
        try:
            body = self._recovery_payload(snapshot)
            target = json.dumps(body["memory_target"], ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            with self.recovery_store.lock("projection"):
                current = self._projection_bytes(self.memory_file)
                state = self._strict_memory(current)
                if current == target:
                    return StepResult("succeeded", {"already_present": True})
                if state.get("last_daily_capsule", {}).get("date", "") > snapshot.date:
                    return StepResult("superseded", {"newer_date": state["last_daily_capsule"]["date"]})
                if self._projection_hash(current) != body["memory_preimage"]:
                    return StepResult("needs_review", {"error_code": "memory_conflict"})
                self._atomic_projection(self.memory_file, target)
            return StepResult("succeeded", {})
        except RecoveryInvalidState:
            return StepResult("needs_review", {"error_code": "invalid_memory"})
        except OSError:
            return StepResult("failed", {"error_code": "memory_io"})

    def commit_frozen_audit(self, payload):
        return self.signal_audit_store.record_recovered_signal(payload["run"], payload["signal"], payload["factors"],
                        expected_canonical_signal_id=payload["expected_canonical_signal_id"])

    def recovery_channel_id(self):
        return hashlib.sha256(self.wecom_url.encode("utf-8")).hexdigest() if self.wecom_url and "None" not in self.wecom_url else None

    def send_wecom_result(self, text):
        channel = self.recovery_channel_id()
        if self.dry_run or channel is None:
            return DeliveryResult("not_configured", "configuration", channel, "dry_run" if self.dry_run else None)
        try:
            response = requests.post(self.wecom_url, json={"msgtype": "markdown", "markdown": {"content": text}}, timeout=10)
            if response.status_code != 200:
                return DeliveryResult("unknown", "provider", channel, "http_response")
            body = response.json()
            code = body.get("errcode") if isinstance(body, dict) else None
            if type(code) is not int:
                return DeliveryResult("unknown", "provider", channel, "untrusted_response")
            return DeliveryResult("confirmed" if code == 0 else "failed", "provider", channel, str(code) if code else None)
        except Exception:
            return DeliveryResult("unknown", "provider", channel, "transport_or_response")

    def _send_recovery_message(self, text):
        if getattr(self.push_to_wecom, "__func__", None) is QuantAgent.push_to_wecom:
            return self.send_wecom_result(text)
        try:
            result = self.push_to_wecom(text)
        except Exception:
            result = False
        return DeliveryResult("confirmed" if result is True else "unknown", "legacy", self.recovery_channel_id(), None)

    # =========================
    # 基础工具层
    # =========================

    def _get_buffer_path(self, date_str=None):
        """动态锚定指定日期或当天的负熵蓄水池物理路径"""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.daily_dir, f"{date_str}_news_buffer.json")

    def _safe_json_load(self, path, default):
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ JSON 读取失败，已降级为默认状态: {path} | {e}")
            return default

    def _safe_json_write(self, path, data):
        if self.dry_run:
            print(f"🧪 [DRY_RUN] 已阻止 JSON 状态写入: {path}")
            return False
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True

    def _strip_json_fence(self, text):
        if not text:
            return ""
        return text.strip().replace("```json", "").replace("```", "").strip()

    def _parse_rss_feed_config(self, raw_config):
        """解析 RSS_FEEDS 配置。格式：source::url|source::url。"""
        feeds = []
        for chunk in str(raw_config or "").split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "::" in chunk:
                source, url = chunk.split("::", 1)
            else:
                url = chunk
                source = url.split("//")[-1].split("/")[0].replace("www.", "")
            source = source.strip().lower()[:40] or "rss"
            url = url.strip()
            if url.startswith("http"):
                feeds.append({"source": source, "url": url})
        return feeds

    def _strip_html(self, value, max_chars=800):
        """RSS 摘要常含 HTML，先剥标签再裁剪，防止正文污染 Prompt。"""
        if value is None:
            return ""
        text = html_lib.unescape(str(value))
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    def _xml_text(self, node, names):
        """兼容 RSS 与 Atom 命名空间，按 localname 读取第一个匹配文本。"""
        if node is None:
            return ""
        wanted = set(names)
        for child in list(node):
            local = child.tag.split("}")[-1].lower()
            if local in wanted:
                return "" if child.text is None else str(child.text).strip()
        return ""

    def _xml_link(self, node):
        """RSS 用 <link>text</link>，Atom 常用 <link href='...'>。"""
        if node is None:
            return ""
        for child in list(node):
            local = child.tag.split("}")[-1].lower()
            if local == "link":
                href = child.attrib.get("href")
                if href:
                    return href.strip()
                if child.text:
                    return child.text.strip()
        return ""

    def _normalize_pub_time(self, text):
        """把 RSS/Atom 时间尽量压成 ISO 字符串；失败则保留原文短片段。"""
        text = str(text or "").strip()
        if not text:
            return ""
        try:
            return parsedate_to_datetime(text).isoformat()
        except Exception:
            return text[:40]

    def _clamp_str(self, value, max_chars):
        if value is None:
            return ""
        value = str(value).replace("\n", " ").strip()
        return value[:max_chars]

    def _weight_rank(self, weight):
        """把定性权重映射为可比较的整数，便于入库闸门与蓄水池裁剪。"""
        return {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}.get(str(weight), 0)

    def _calibrate_factor_weight(self, title, body, weight, reason=""):
        """
        评级校准器：用硬规则压住模型的 Critical 通胀。
        Critical 只能给非线性、可交易、强冲击事件；普通观点文、行情回顾、分析稿一律降级。
        """
        valid = {"Critical", "High", "Medium", "Low"}
        weight = str(weight or "Low").strip()
        if weight not in valid:
            return "Low", "非法评级归零"

        text = f"{title} {body} {reason}".lower()

        # 普通评论/行情回顾/观点类，天然不允许 Critical。
        soft_patterns = [
            "may", "could", "opinion", "analysis", "live markets", "stalls", "fleeting",
            "questions", "faces a challenge", "yield play", "price prediction", "what to expect",
            "rally", "gains", "dips", "slides", "trader says", "analyst", "technical analysis"
        ]
        looks_soft = any(x in text for x in soft_patterns)

        critical_patterns = [
            "hack", "hacked", "exploit", "exploited", "stolen", "breach",
            "bankruptcy", "insolvency", "withdrawals suspended", "suspends withdrawals",
            "trading halt", "outage", "liquidation cascade",
            "sec approves", "sec rejects", "etf approved", "etf rejected", "spot etf approved",
            "emergency rate cut", "emergency meeting", "fomc surprise",
            "cpi shock", "non-farm payrolls", "nfp shock",
            "mt. gox", "mt gox", "wallet moves", "wallet transfer", "exchange inflow",
            "40,000 btc", "40000 btc", "100,000 btc", "100000 btc",
            "ban crypto", "crypto ban", "court rules", "major regulatory ruling"
        ]
        high_patterns = [
            "sec", "etf", "fomc", "cpi", "non-farm", "payroll", "fed", "interest rates",
            "bank of japan", "boj", "exchange inflow", "whale", "coinbase", "binance",
            "microstrategy", "mstr", "mt. gox", "mt gox", "open interest", "authorization"
        ]

        has_critical_trigger = any(x in text for x in critical_patterns)
        has_high_trigger = any(x in text for x in high_patterns)

        if weight == "Critical" and (looks_soft or not has_critical_trigger):
            # 有宏观/监管/交易所强相关词，最多 High；否则降到 Medium。
            return ("High" if has_high_trigger else "Medium"), "Critical未满足非线性冲击条件，已校准"

        if weight == "High" and looks_soft and not has_high_trigger:
            return "Medium", "High缺少直接冲击路径，已校准"

        return weight, ""

    def _news_fingerprint(self, news):
        """基于标题与正文前缀生成内容指纹，防止同一新闻换 ID 后反复入池。"""
        title = " ".join(str(news.get("title", "")).lower().split())[:240]
        body = " ".join(str(news.get("body", "")).lower().split())[:240]
        raw = f"{title}|{body}"
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]

    def _prune_day_buffer(self, day_buffers):
        """蓄水池物理截流：去重并只保留最高权重、最新的有限因子。"""
        if not isinstance(day_buffers, list):
            return []

        seen = set()
        cleaned = []
        for item in day_buffers:
            if not isinstance(item, dict):
                continue
            fp = item.get("fingerprint") or hashlib.sha256(
                str(item.get("title", "")).lower().encode("utf-8", errors="ignore")
            ).hexdigest()[:24]
            key = (str(item.get("id", "")), fp)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)

        cleaned.sort(
            key=lambda n: (self._weight_rank(n.get("weight", "Low")), str(n.get("time", ""))),
            reverse=True,
        )
        return cleaned[:self.max_buffer_factors]

    # =========================
    # 跨日记忆层：Memory Capsule
    # =========================

    def load_memory_state(self):
        """读取跨日压缩记忆。只读结构化状态，不反向吞 Markdown 全文。"""
        default_state = {"last_daily_capsule": {}, "rolling_7d": []}
        state = self._safe_json_load(self.memory_file, default_state)
        if not isinstance(state, dict):
            return default_state
        state.setdefault("last_daily_capsule", {})
        state.setdefault("rolling_7d", [])
        return state

    def clamp_memory_state(self, state):
        """压缩记忆输入，防止昨日文本残影污染今日 Prompt。"""
        last = state.get("last_daily_capsule", {}) or {}
        rolling = state.get("rolling_7d", []) or []

        compact_last = {
            "date": self._clamp_str(last.get("date", ""), 20),
            "risk_regime": self._clamp_str(last.get("risk_regime", "unknown"), 32),
            "btc_bias": self._clamp_str(last.get("btc_bias", "unknown"), 32),
            "confidence": last.get("confidence", 0),
            "core_thesis": self._clamp_str(last.get("core_thesis", ""), 220),
            "invalid_if": self._clamp_str(last.get("invalid_if", ""), 160),
            "watch_items": [self._clamp_str(x, 50) for x in list(last.get("watch_items", []))[:5]],
            "today_check": self._clamp_str(last.get("today_check", ""), 180),
        }

        compact_rolling = []
        for item in list(rolling)[-7:]:
            if not isinstance(item, dict):
                continue
            compact_rolling.append({
                "date": self._clamp_str(item.get("date", ""), 20),
                "bias": self._clamp_str(item.get("bias", "unknown"), 32),
                "core": self._clamp_str(item.get("core", ""), 180),
            })

        return {
            "last_daily_capsule": compact_last,
            "rolling_7d": compact_rolling,
        }

    def save_memory_capsule(self, capsule):
        """幂等写入今日胶囊；只有跨日期推进时才把上一日压入滚动记忆。"""
        if not isinstance(capsule, dict):
            print("⚠️ 记忆胶囊不是 dict，拒绝写入。")
            return False

        state = self.load_memory_state()
        previous = state.get("last_daily_capsule", {}) or {}
        rolling_raw = state.get("rolling_7d", []) or []
        rolling = list(rolling_raw) if isinstance(rolling_raw, list) else []

        normalized = {
            "date": self._clamp_str(capsule.get("date", datetime.now().strftime("%Y-%m-%d")), 20),
            "risk_regime": self._clamp_str(capsule.get("risk_regime", "unknown"), 32),
            "btc_bias": self._clamp_str(capsule.get("btc_bias", "unknown"), 32),
            "confidence": capsule.get("confidence", 0),
            "core_thesis": self._clamp_str(capsule.get("core_thesis", ""), 220),
            "invalid_if": self._clamp_str(capsule.get("invalid_if", ""), 160),
            "watch_items": [self._clamp_str(x, 50) for x in list(capsule.get("watch_items", []))[:5]],
            "today_check": self._clamp_str(capsule.get("today_check", ""), 180),
        }

        current_date = normalized["date"]
        previous_date = self._clamp_str(previous.get("date", ""), 20)
        if previous and previous_date and previous_date != current_date:
            rolling.append({
                "date": previous_date,
                "bias": previous.get("btc_bias", "unknown"),
                "core": self._clamp_str(previous.get("core_thesis", ""), 180),
            })

        # 按日期保留最后一次有效记录，并排除当前日期，修复历史重复与同日重跑污染。
        deduped_reversed = []
        seen_dates = set()
        for item in reversed(rolling):
            if not isinstance(item, dict):
                continue
            item_date = self._clamp_str(item.get("date", ""), 20)
            if not item_date or item_date == current_date or item_date in seen_dates:
                continue
            seen_dates.add(item_date)
            deduped_reversed.append({
                "date": item_date,
                "bias": self._clamp_str(item.get("bias", "unknown"), 32),
                "core": self._clamp_str(item.get("core", ""), 180),
            })
        deduped_rolling = list(reversed(deduped_reversed))[-7:]

        new_state = {
            "last_daily_capsule": normalized,
            "rolling_7d": deduped_rolling,
        }
        if self._safe_json_write(self.memory_file, new_state):
            print(f"[Memory] 今日记忆胶囊已写入: {self.memory_file}")
            return True
        return False

    def generate_memory_capsule(self, today_str, ai_analysis, metrics, compact_news):
        """生成并返回结构化记忆胶囊；是否持久化由 Daily Pipeline 统一决定。"""
        capsule_prompt = f"""
请把以下今日投研内参压缩成严格 JSON，禁止 Markdown，禁止解释，禁止多余字段。

字段约束：
- date: 字符串，固定为 {today_str}
- risk_regime: risk_on | neutral | risk_off | mixed
- btc_bias: bullish | slightly_bullish | neutral | slightly_bearish | bearish
- confidence: 0 到 100 的整数
- core_thesis: 不超过120字
- invalid_if: 不超过80字
- watch_items: 最多5项，每项不超过20字
- today_check: 不超过100字，写明明日需要验证什么

今日硬指标：
{json.dumps(metrics, ensure_ascii=False)}

今日重大因子：
{json.dumps(compact_news, ensure_ascii=False)}

今日内参：
{self._clamp_str(ai_analysis, 1200)}
""".strip()

        raw = self.request_deepseek(
            prompt=capsule_prompt,
            use_r1=False,
            system_prompt="你是量化投研记忆压缩器，只输出严格 JSON。"
        )
        try:
            capsule = json.loads(self._strip_json_fence(raw))
            if not isinstance(capsule, dict):
                raise ValueError("capsule is not dict")
            required = {
                "risk_regime", "btc_bias", "confidence", "core_thesis",
                "invalid_if", "watch_items", "today_check",
            }
            missing = sorted(required.difference(capsule))
            if missing:
                raise ValueError(f"missing fields: {', '.join(missing)}")
            if capsule.get("risk_regime") not in {"risk_on", "neutral", "risk_off", "mixed"}:
                raise ValueError("invalid risk_regime")
            if capsule.get("btc_bias") not in {
                "bullish", "slightly_bullish", "neutral", "slightly_bearish", "bearish"
            }:
                raise ValueError("invalid btc_bias")
            confidence = capsule.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 100:
                raise ValueError("confidence must be an integer from 0 to 100")
            if not isinstance(capsule.get("watch_items"), list):
                raise ValueError("watch_items must be a list")
            capsule["date"] = today_str
            return capsule
        except Exception as e:
            raw_preview = self._clamp_str(raw, 240)
            raise DeepSeekError(
                f"记忆胶囊响应不可信，拒绝覆盖Memory: {e} | raw={raw_preview}"
            ) from e

    def build_signal_audit_payload(
        self,
        today_str,
        started_at,
        capsule,
        metrics,
        compact_news,
        previous_memory,
        ai_analysis,
        delivery_state=None,
    ):
        """纯构造审计载荷；不连接数据库，不产生文件副作用。"""
        try:
            with open(__file__, "rb") as source_file:
                source_sha256 = hashlib.sha256(source_file.read()).hexdigest()
        except OSError:
            source_sha256 = None

        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        code_version = os.getenv("QUANTAGENT_VERSION")
        if not code_version and source_sha256:
            code_version = f"source:{source_sha256[:12]}"
        version_known = bool(code_version and self.fast_model and self.reason_model)
        quality_score, quality_flags = calculate_data_quality(
            metrics,
            compact_news,
            version_known=version_known,
        )
        btc_price = (metrics.get("crypto", {}) or {}).get("BTC_Price")
        reference_price = btc_price if isinstance(btc_price, (int, float)) else None
        run_kind = "forced" if self.force_daily_run and not self.dry_run else "scheduled"
        delivery_state = delivery_state or {}

        run = {
            "run_id": SignalAuditStore.new_id("run"),
            "trade_date": today_str,
            "started_at": started_at,
            "completed_at": completed_at,
            "run_kind": run_kind,
            "code_version": code_version,
            "source_sha256": source_sha256,
            "fast_model": self.fast_model,
            "reason_model": self.reason_model,
            "report_written": bool(delivery_state.get("report_written", False)),
            "wecom_sent": bool(delivery_state.get("wecom_sent", False)),
            "memory_saved": bool(delivery_state.get("memory_saved", False)),
        }
        signal = {
            "signal_id": SignalAuditStore.new_id("signal"),
            "signal_date": today_str,
            "asset": "BTC",
            "quote_asset": "USDT",
            "decision_horizon": "1d",
            "risk_regime": capsule.get("risk_regime", "unknown"),
            "bias": capsule.get("btc_bias", "unknown"),
            "confidence_raw": capsule.get("confidence", 0),
            "confidence_calibrated": None,
            "core_thesis": capsule.get("core_thesis", ""),
            "invalid_if": capsule.get("invalid_if", ""),
            "today_check": capsule.get("today_check", ""),
            "watch_items": capsule.get("watch_items", []),
            "reference_price": reference_price,
            "market_snapshot": metrics,
            "previous_memory": previous_memory,
            "analysis_text": ai_analysis,
            "data_quality_score": quality_score,
            "quality_flags": quality_flags,
            "finalized_at": completed_at,
        }
        return run, signal

    def record_signal_audit(
        self,
        today_str,
        started_at,
        capsule,
        metrics,
        compact_news,
        previous_memory,
        ai_analysis,
        delivery_state=None,
    ):
        """统一审计边界；生产失败只告警，不反向破坏日报与 Memory。"""
        run, signal = self.build_signal_audit_payload(
            today_str,
            started_at,
            capsule,
            metrics,
            compact_news,
            previous_memory,
            ai_analysis,
            delivery_state,
        )
        try:
            result = self.signal_audit_store.record_completed_signal(
                run,
                signal,
                compact_news,
            )
        except SignalAuditError as exc:
            print(f"⚠️ [Signal Audit] 写入失败，日报与Memory保持已交付状态: {exc}")
            return {"status": "failed", "error": str(exc)}

        if result.get("status") == "dry_run":
            print("🧪 [DRY_RUN] Signal Audit 预览完成：未创建或连接 SQLite。")
        else:
            print(
                f"[Signal Audit] 信号审计已入账: {result.get('signal_id')} | "
                f"quality={signal['data_quality_score']:.0f}"
            )
        return result

    # =========================
    # 输入防溢出层：Factor Gate
    # =========================

    def compact_news_factors(self, factors):
        """只允许最高权重、最短字段进入宏观推理层，防止 Prompt 熵爆炸。"""
        if not factors:
            return []

        weight_score = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}
        sorted_factors = sorted(
            factors,
            key=lambda n: weight_score.get(n.get("weight", "Low"), 0),
            reverse=True,
        )[:self.max_daily_factors]

        compact = []
        for n in sorted_factors:
            compact.append({
                "time": self._clamp_str(n.get("time", ""), 12),
                "source": self._clamp_str(n.get("source", ""), 40),
                "title": self._clamp_str(n.get("title", ""), 120),
                "sentiment": self._clamp_str(n.get("sentiment", "中性"), 12),
                "weight": self._clamp_str(n.get("weight", "Low"), 12),
                "reason": self._clamp_str(n.get("reason", ""), 80),
            })
        return compact

    # =========================
    # 数据抓取层
    # =========================

    def fetch_market_signals(self):
        print("[Daily] 正在抓取跨市场高精度数字硬指标...")
        session_gateway = requests.Session()
        session_gateway.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        metrics = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "macro": {"S&P500_Chg%": "暂无数据", "VIX_Volatility": "暂无数据"},
            "crypto": {"BTC_Price": "暂无数据", "BTC_24h_Chg%": "暂无数据", "Fear_Greed": "暂无数据"}
        }

        try:
            btc_ticker = session_gateway.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10).json()
            metrics["crypto"]["BTC_Price"] = float(btc_ticker["lastPrice"])
            metrics["crypto"]["BTC_24h_Chg%"] = float(btc_ticker["priceChangePercent"])
            print(" -> 币安硬指标抓取成功")
        except Exception as e:
            print(f"⚠️ 币安行情抓取受限: {e}")

        try:
            fng_res = session_gateway.get("https://api.alternative.me/fng/", timeout=10).json()
            metrics["crypto"]["Fear_Greed"] = int(fng_res["data"][0]["value"])
            print(" -> 恐慌指数抓取成功")
        except Exception as e:
            print(f"⚠️ 恐慌指数抓取受限: {e}")

        try:
            spy = yf.Ticker("^GSPC", session=session_gateway).history(period="2d")
            if len(spy) >= 2:
                spy_chg = ((spy["Close"].iloc[-1] - spy["Close"].iloc[-2]) / spy["Close"].iloc[-2]) * 100
                metrics["macro"]["S&P500_Chg%"] = round(spy_chg, 2)
                print(" -> 美股标普500抓取成功")
        except Exception as e:
            print(f"⚠️ 美股标普500抓取受限: {e}")

        try:
            vix = yf.Ticker("^VIX", session=session_gateway).history(period="1d")
            if len(vix) > 0:
                metrics["macro"]["VIX_Volatility"] = round(vix["Close"].iloc[-1], 2)
                print(" -> 美股 VIX 指数抓取成功")
        except Exception as e:
            print(f"⚠️ 美股 VIX 抓取受限: {e}")

        return metrics

    def fetch_crypto_flash_news(self):
        """
        免费 RSS 多源聚合快讯网关。
        设计目的：替代已强制 API Key 鉴权的 CryptoCompare/CoinDesk Data API。
        不依赖 feedparser，直接用标准库解析 RSS/Atom XML，降低服务器依赖熵。
        """
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })

        raw_news = []
        source_stats = []

        if not self.rss_feeds:
            print("⚠️ RSS_FEEDS 为空，无法抓取免费新闻源。")
            return []

        for feed in self.rss_feeds:
            source = feed.get("source", "rss")
            url = feed.get("url", "")
            if not url:
                continue

            try:
                res = session.get(url, timeout=self.rss_timeout)
                if res.status_code != 200:
                    print(f"⚠️ RSS 源受阻: {source} | HTTP {res.status_code} | {url}")
                    source_stats.append((source, 0, f"HTTP {res.status_code}"))
                    continue

                text = res.text.strip()
                if not text or "<" not in text[:20]:
                    print(f"⚠️ RSS 源返回非 XML: {source} | head={text[:120]}")
                    source_stats.append((source, 0, "non-xml"))
                    continue

                try:
                    root = ET.fromstring(res.content)
                except Exception as parse_err:
                    print(f"⚠️ RSS XML 解析失败: {source} | {parse_err}")
                    source_stats.append((source, 0, "parse-error"))
                    continue

                # RSS: channel/item；Atom: entry。直接按 localname 扫描，绕开命名空间阻抗。
                entries = []
                for node in root.iter():
                    local = node.tag.split("}")[-1].lower()
                    if local in {"item", "entry"}:
                        entries.append(node)

                captured = 0
                for item in entries[:self.max_rss_items_per_source]:
                    title = self._strip_html(self._xml_text(item, ["title"]), 220)
                    link = self._xml_link(item)
                    body_raw = (
                        self._xml_text(item, ["description"])
                        or self._xml_text(item, ["summary"])
                        or self._xml_text(item, ["content"])
                        or self._xml_text(item, ["encoded"])
                    )
                    body = self._strip_html(body_raw, 800)
                    published = self._normalize_pub_time(
                        self._xml_text(item, ["pubdate"])
                        or self._xml_text(item, ["published"])
                        or self._xml_text(item, ["updated"])
                        or self._xml_text(item, ["date"])
                    )

                    if not title:
                        continue

                    # ID 由 source + link/title 哈希生成，抵抗不同 RSS 源 ID 字段不稳定。
                    stable_raw = f"{source}|{link or title}"
                    news_id = "rss_" + hashlib.sha256(
                        stable_raw.encode("utf-8", errors="ignore")
                    ).hexdigest()[:24]

                    raw_news.append({
                        "id": news_id,
                        "source": source,
                        "title": title,
                        "body": body,
                        "url": link,
                        "published": published,
                    })
                    captured += 1

                source_stats.append((source, captured, "ok"))

            except Exception as e:
                print(f"⚠️ RSS 源抓取异常: {source} | {e}")
                source_stats.append((source, 0, "exception"))

        # 跨源标题/正文指纹去重，避免同一新闻被多站转载后重复打标。
        deduped = []
        seen_fp = set()
        for news in raw_news:
            fp = self._news_fingerprint(news)
            if fp in seen_fp:
                continue
            seen_fp.add(fp)
            deduped.append(news)

        stat_text = ", ".join([f"{s}:{n}" for s, n, _ in source_stats])
        print(
            f" -> [RSS 聚合] 源统计: {stat_text} | "
            f"原始 {len(raw_news)} 条 / 去重后 {len(deduped)} 条"
        )

        if not deduped and self.allow_mock_news:
            print("⚠️ RSS 全源无结果；ALLOW_MOCK_NEWS=true，但生产纪律建议保持 mock 关闭。")

        return deduped

    # =========================
    # AI 与推送层
    # =========================

    def request_deepseek(self, prompt, use_r1=False, system_prompt=None):
        """调用DeepSeek并返回可信文本；任何传输或结构异常都显式抛错。"""
        model = self.reason_model if use_r1 else self.fast_model
        if not self.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY未配置")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if not system_prompt:
            system_prompt = "你是一个冷酷的量化策略师。请基于提供的数据输出低熵结论。"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.15 if not use_r1 else 0.6
        }
        try:
            res = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60,
            )
            data = res.json()
            if not isinstance(data, dict):
                raise DeepSeekError(f"DeepSeek返回非对象结构: HTTP {res.status_code}")
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                error_obj = data.get("error", {})
                error_msg = error_obj.get("message") if isinstance(error_obj, dict) else ""
                error_msg = self._clamp_str(error_msg or f"HTTP {res.status_code}", 200)
                raise DeepSeekError(f"DeepSeek响应缺少choices: {error_msg}")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise DeepSeekError("DeepSeek响应content为空或结构非法")
            return content.strip()
        except DeepSeekError:
            raise
        except Exception as e:
            raise DeepSeekError(f"DeepSeek链路异常: {e}") from e

    def push_to_wecom(self, text):
        return self.send_wecom_result(text).status == "confirmed"

    # =========================
    # 常驻监听层
    # =========================

    def run_monitor_pipeline(self):
        """Run the original sequence through explicit public workflow ports."""
        return run_monitor_pipeline(MonitorPorts(
            dedup_file=self.dedup_file,
            fingerprint_file=self.fingerprint_file,
            failed_news_file=self.failed_news_file,
            max_news_per_cycle=self.max_news_per_cycle,
            max_news_ai_retries=self.max_news_ai_retries,
            min_store_weight=self.min_store_weight,
            read_json=self._safe_json_load,
            write_json=self._safe_json_write,
            get_buffer_path=self._get_buffer_path,
            fetch_crypto_flash_news=self.fetch_crypto_flash_news,
            news_fingerprint=self._news_fingerprint,
            clamp_str=self._clamp_str,
            strip_json_fence=self._strip_json_fence,
            request_deepseek=self.request_deepseek,
            calibrate_factor_weight=self._calibrate_factor_weight,
            weight_rank=self._weight_rank,
            prune_day_buffer=self._prune_day_buffer,
            now=datetime.now,
            sleep=time.sleep,
        ))

    # =========================
    # 每日收敛层
    # =========================

    def _write_daily_report(self, file_path, obsidian_content):
        """Owned file boundary, retaining the original write and exception semantics."""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(obsidian_content)

    def run_daily_pipeline(self):
        """Run the original sequence through explicit public workflow ports."""
        return run_daily_pipeline(self.daily_ports())

    def daily_ports(self):
        return DailyPorts(
            dry_run=self.dry_run,
            force_daily_run=self.force_daily_run,
            load_memory_state=self.load_memory_state,
            report_path=lambda date: os.path.join(self.daily_dir, f"{date}.md"),
            report_exists=os.path.exists,
            clamp_str=self._clamp_str,
            fetch_market_signals=self.fetch_market_signals,
            get_buffer_path=self._get_buffer_path,
            read_json=self._safe_json_load,
            compact_news_factors=self.compact_news_factors,
            clamp_memory_state=self.clamp_memory_state,
            request_deepseek=self.request_deepseek,
            generate_memory_capsule=self.generate_memory_capsule,
            record_signal_audit=self.record_signal_audit,
            write_report=self._write_daily_report,
            push_to_wecom=self.push_to_wecom,
            save_memory_capsule=self.save_memory_capsule,
            now=datetime.now,
            recovery=self.recovery_store,
            capture_inputs=self.capture_daily_inputs,
            prepare_audit=self.prepare_recovery_audit,
            project_report=self.project_daily_report,
            project_memory=self.project_daily_memory,
            commit_audit=self.commit_frozen_audit,
            send_message=self._send_recovery_message,
            channel_id=self.recovery_channel_id,
        )

    def run_weekly_pipeline(self):
        """显式占位，避免 argparse 允许 weekly 但执行时静默失败。"""
        print("⚠️ weekly 模式尚未接入完整周报引擎。本版本已显式阻断静默失败。")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "monitor", "recover"], required=True)
    parser.add_argument("--action", choices=["status", "retry", "confirm-sent", "confirm-not-sent", "abandon"])
    parser.add_argument("--run-id")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.mode != "recover" and any((args.action, args.run_id, args.reason)):
        parser.error("recovery options require --mode recover")
    if args.mode == "recover" and (args.action is None or (args.action != "status" and not args.run_id)
                                 or (args.action == "abandon" and not args.reason)):
        parser.error("recover requires --action; mutations need --run-id and abandon needs --reason")
    try:
        if args.mode == "recover":
            dry = os.getenv("DRY_RUN", "false").strip().lower() == "true"
            store = get_legacy_recovery_factory()(os.path.abspath(os.path.join(BASE_DIR, "10_DailyNotes")), dry_run=dry)
            engine = QuantAgent() if args.action == "retry" and not dry else None
            if engine is not None:
                store = engine.recovery_store
            result = run_recovery_action(store, action=args.action, run_id=args.run_id, reason=args.reason, dry_run=dry,
                                         daily=engine.daily_ports() if engine else None)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        engine = QuantAgent()
        if args.mode == "daily":
            engine.run_daily_pipeline()
        elif args.mode == "monitor":
            engine.run_monitor_pipeline()
        elif args.mode == "weekly":
            engine.run_weekly_pipeline()
    except DeepSeekError as e:
        print(f"❌ [AI Failure] {e}")
        raise SystemExit(2)
    except RecoveryError as e:
        print(f"❌ [Recovery] {e}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()

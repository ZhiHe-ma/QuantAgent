import os
import re
import json
import time
import random
import hashlib
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
import yfinance as yf
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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
        if self.dry_run:
            print("🧪 [DRY_RUN] 已阻止企业微信推送。")
            return
        if not self.wecom_url or "None" in self.wecom_url:
            print("❌ 企微网关未挂载，取消推送。")
            return
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
        try:
            res = requests.post(self.wecom_url, json=payload, timeout=10)
            if res.status_code != 200:
                print(f"⚠️ 企微网关返回异常状态码: {res.status_code}")
        except Exception as e:
            print(f"❌ 企微网关物理击穿: {e}")

    # =========================
    # 常驻监听层
    # =========================

    def run_monitor_pipeline(self):
        """24小时常驻静默监控核心状态机"""
        print("🚀 [Monitor] 实时高精度快讯监听常驻进程已成功挂载底座。进入事件循环...")

        processed_ids = set(self._safe_json_load(self.dedup_file, []))
        processed_fingerprints = set(self._safe_json_load(self.fingerprint_file, []))

        sys_prompt_monitor = (
            "你是一个极端保守的微观量化因子标记器。请直接分析给定新闻对加密货币（主要是BTC与主流代币）价格的影响。\n"
            "评级纪律必须极硬：Low=普通观点/行情复盘/轻微产品动态；Medium=有方向但冲击路径间接；High=有清晰、直接、可交易的价格冲击路径；Critical=只允许非线性事件，例如交易所宕机、提现暂停、重大监管裁决、ETF突发批准或否决、巨额黑客攻击、大型钱包向交易所转移、宏观数据严重超预期。\n"
            "禁止把普通分析稿、行情直播、技术面评论、may/could/analyst 类文章评为 Critical。正常情况下 Critical 应极少出现。\n"
            "必须输出标准 JSON，严禁 Markdown、解释性文字、多余字段。格式如下：\n"
            '{"sentiment": "利多" | "利空" | "中性", "weight": "Critical" | "High" | "Medium" | "Low", "reason": "50字以内的极端精炼异动逻辑"}'
        )

        while True:
            try:
                flash_news_list = self.fetch_crypto_flash_news()
                buffer_path = self._get_buffer_path()
                day_buffers = self._safe_json_load(buffer_path, [])
                if not isinstance(day_buffers, list):
                    day_buffers = []

                has_updates = False

                candidates = []
                for news in flash_news_list:
                    news_id = str(news.get("id", "")).strip()
                    fingerprint = self._news_fingerprint(news)
                    if not news_id or news_id in processed_ids or fingerprint in processed_fingerprints:
                        continue
                    candidates.append((news, news_id, fingerprint))

                if len(candidates) > self.max_news_per_cycle:
                    print(f" -> [控熵闸门] 本轮发现 {len(candidates)} 条增量，仅分析前 {self.max_news_per_cycle} 条，防止成本与噪声失控。")

                for news, news_id, fingerprint in candidates[:self.max_news_per_cycle]:
                    title = self._clamp_str(news.get("title", ""), 180)
                    body = self._clamp_str(news.get("body", ""), 800)
                    print(f"🔥 捕获未处理原生增量快讯 [{news_id}]: {title}")

                    news_payload = f"来源: {self._clamp_str(news.get("source", "rss"), 40)}\n新闻标题: {title}\n新闻正文: {body}\n链接: {self._clamp_str(news.get("url", ""), 240)}"
                    ai_raw_decision = ""
                    try:
                        ai_raw_decision = self.request_deepseek(
                            news_payload,
                            use_r1=False,
                            system_prompt=sys_prompt_monitor,
                        )
                        decision_json = json.loads(self._strip_json_fence(ai_raw_decision))
                        if not isinstance(decision_json, dict):
                            raise ValueError("decision is not dict")
                        if decision_json.get("sentiment") not in {"利多", "利空", "中性"}:
                            raise ValueError("invalid sentiment")
                        if decision_json.get("weight") not in {"Critical", "High", "Medium", "Low"}:
                            raise ValueError("invalid weight")
                        if not str(decision_json.get("reason", "")).strip():
                            raise ValueError("reason is empty")
                        factor_node = {
                            "id": news_id,
                            "fingerprint": fingerprint,
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "source": self._clamp_str(news.get("source", "rss"), 40),
                            "published": self._clamp_str(news.get("published", ""), 40),
                            "title": title,
                            "url": self._clamp_str(news.get("url", ""), 240),
                            "sentiment": self._clamp_str(decision_json.get("sentiment", "中性"), 12),
                            "weight": self._clamp_str(decision_json.get("weight", "Low"), 12),
                            "reason": self._clamp_str(decision_json.get("reason", "未提供有效定性依据"), 80)
                        }

                        original_weight = factor_node["weight"]
                        calibrated_weight, calibrate_reason = self._calibrate_factor_weight(
                            title=title,
                            body=body,
                            weight=original_weight,
                            reason=factor_node.get("reason", "")
                        )
                        if calibrated_weight != original_weight:
                            factor_node["weight"] = calibrated_weight
                            factor_node["calibrated_from"] = original_weight
                            factor_node["calibration_reason"] = calibrate_reason
                            print(f" ╰─> [评级校准] {original_weight} -> {calibrated_weight} | {calibrate_reason}")

                        processed_ids.add(news_id)
                        processed_fingerprints.add(fingerprint)

                        if self._weight_rank(factor_node["weight"]) >= self._weight_rank(self.min_store_weight):
                            day_buffers.append(factor_node)
                            day_buffers = self._prune_day_buffer(day_buffers)
                            has_updates = True
                            print(f" ╰─> [因子入池] 定性: {factor_node['sentiment']} | 评级: {factor_node['weight']}")
                        else:
                            has_updates = True
                            print(f" ╰─> [低权重丢弃] 定性: {factor_node['sentiment']} | 评级: {factor_node['weight']}，不写入蓄水池。")
                    except Exception as parse_err:
                        raw_preview = self._clamp_str(locals().get("ai_raw_decision", ""), 240)
                        print(
                            "⚠️ 因子提取失败，未写入已处理库，等待后续重试: "
                            f"{parse_err} | raw={raw_preview}"
                        )

                if has_updates:
                    self._safe_json_write(buffer_path, day_buffers)
                    self._safe_json_write(self.dedup_file, list(processed_ids))
                    self._safe_json_write(self.fingerprint_file, list(processed_fingerprints)[-50000:])

            except Exception as loop_err:
                print(f"❌ 监听回路发生运行时异常，策略熔断器保护，3秒后自动软重启: {loop_err}")
                time.sleep(3)

            time.sleep(180)

    # =========================
    # 每日收敛层
    # =========================

    def run_daily_pipeline(self):
        """每日 08:00 周期收敛宏观内参生成核心流水线"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"🌅 [Daily] 启动清晨 08:00 周期收敛引擎，执行日期: {today_str}")

        raw_memory_state = self.load_memory_state()
        today_report_path = os.path.join(self.daily_dir, f"{today_str}.md")
        last_capsule_date = self._clamp_str(
            (raw_memory_state.get("last_daily_capsule", {}) or {}).get("date", ""),
            20,
        )
        if (
            not self.dry_run
            and not self.force_daily_run
            and last_capsule_date == today_str
            and os.path.exists(today_report_path)
        ):
            print(
                f"♻️ [Daily] {today_str} 已完成，幂等闸门跳过重复执行；"
                "未抓行情、未调用DeepSeek、未写文件、未推送企微。"
            )
            return {"status": "skipped", "date": today_str}
        if self.force_daily_run and not self.dry_run:
            print("⚠️ [Daily] FORCE_DAILY_RUN=true：显式绕过同日幂等闸门。")

        metrics = self.fetch_market_signals()

        buffer_path = self._get_buffer_path()
        filtered_news_context = []
        all_news = self._safe_json_load(buffer_path, [])
        if isinstance(all_news, list):
            from collections import Counter
            weight_counter = Counter(str(n.get("weight", "Low")) for n in all_news if isinstance(n, dict))
            print(f" -> 蓄水池评级分布: {dict(weight_counter)}")
            filtered_news_context = [n for n in all_news if n.get("weight") in ["Critical", "High"]]
            if not filtered_news_context:
                filtered_news_context = [n for n in all_news if n.get("weight") == "Medium"]
                if filtered_news_context:
                    print(" -> 未发现 Critical/High，降级启用 Medium 因子作为今日背景噪声输入。")
        else:
            print("⚠️ 当日新闻蓄水池不是 list，已按空因子处理。")

        compact_news = self.compact_news_factors(filtered_news_context)
        print(
            f" -> 已从蓄水池榨取高价值因子 {len(filtered_news_context)} 个；"
            f"经 Factor Gate 裁剪后进入推理层 {len(compact_news)} 个。"
        )

        memory_state = self.clamp_memory_state(raw_memory_state)
        previous_memory = memory_state.get("last_daily_capsule", {})
        rolling_memory = memory_state.get("rolling_7d", [])

        macro_prompt = {
            "previous_memory_capsule": previous_memory,
            "rolling_7d_memory": rolling_memory,
            "market_hard_indicators": metrics,
            "24h_high_value_news_factors": compact_news,
            "task": "先审判昨日核心判断是否被市场证伪，再融合今日硬指标与重大快讯，输出今日风险基调。"
        }

        sys_prompt_daily = (
            "你是一个掌握高维直觉与底层逻辑的量化策略大脑。请执行跨市场硬指标、过去24小时重大快讯因子、昨日记忆胶囊的因果大对账。\n"
            "必须先判断昨日核心观点是否被证伪，再给出今日风险基调。\n"
            "必须使用 Obsidian 双向链接。\n"
            "监管类因子必须强制分类：\n"
            "1. safe harbor / clarity / exemption / easing / public comment / fundraising support / rule clarity，默认视为监管清晰化利多；\n"
            "2. lawsuit / enforcement / ban / penalty / restriction / rejection / investigation，才视为监管压力；\n"
            "3. 严禁把 safe harbor / 安全港 直接解释为监管未知恐惧，除非新闻明确显示条款更严或限制更强；\n"
            "4. 若宏观指标偏空而监管因子偏利多，必须表述为：宏观避险压制 vs 政策利好对冲，不得强行统一为单边恐惧叙事。\n"
            "输出必须包含四段：\n"
            "1. 昨日判断审计：不超过80字\n"
            "2. 今日风险基调：不超过120字\n"
            "3. 核心因果链：不超过180字\n"
            "4. 操作观察点：不超过100字\n"
            "全文不超过500字。"
        )

        print("[Daily] 正在唤醒 DeepSeek-R1 深度推理链进行跨日因果审判...")
        ai_analysis = self.request_deepseek(
            prompt=json.dumps(macro_prompt, ensure_ascii=False),
            use_r1=True,
            system_prompt=sys_prompt_daily
        )

        spy_val = metrics["macro"]["S&P500_Chg%"]
        spy_str = f"{spy_val:+.2f}%" if isinstance(spy_val, (int, float)) else str(spy_val)
        vix_val = metrics["macro"]["VIX_Volatility"]
        vix_str = f"{vix_val:.2f}" if isinstance(vix_val, (int, float)) else str(vix_val)
        btc_chg_val = metrics["crypto"]["BTC_24h_Chg%"]
        btc_chg_str = f"{btc_chg_val:+.2f}%" if isinstance(btc_chg_val, (int, float)) else str(btc_chg_val)
        btc_price_val = metrics["crypto"]["BTC_Price"]
        btc_price_str = f"${btc_price_val:,.2f}" if isinstance(btc_price_val, (int, float)) else str(btc_price_val)
        fng_val = metrics["crypto"]["Fear_Greed"]
        fng_str = str(fng_val)

        obsidian_content = f"""---
type: quant-breakfast
date: {today_str}
btc_chg: {btc_chg_str}
vix: {vix_str}
factors_count_raw: {len(filtered_news_context)}
factors_count_used: {len(compact_news)}
memory_enabled: true
---
# 📊 跨市场高精度分布式投研早餐 ({today_str})

## 🧠 昨日记忆胶囊
```json
{json.dumps(previous_memory, ensure_ascii=False, indent=2)}
```

## 🧭 跨市场硬指标对账单
- **[[Bitcoin]]**: {btc_price_str} ({btc_chg_str}) | 情绪面: 恐慌贪婪 {fng_str}
- **[[美股大盘]]**: 标普500变动 ({spy_str}) | VIX 波动率 ({vix_str})

## ⚡ 蓄水池重大异动影子库（原始 {len(filtered_news_context)} 项 / 入模 {len(compact_news)} 项）
```json
{json.dumps(compact_news, ensure_ascii=False, indent=2)}
```

## 🧠 DeepSeek-R1 宏观因果螺旋推演
{ai_analysis}
"""
        if self.dry_run:
            capsule = self.generate_memory_capsule(today_str, ai_analysis, metrics, compact_news)
            print("\n===== [DRY_RUN] 日报预览开始 =====")
            print(obsidian_content)
            print("===== [DRY_RUN] 日报预览结束 =====")
            print("\n===== [DRY_RUN] Memory Capsule 预览 =====")
            print(json.dumps(capsule, ensure_ascii=False, indent=2))
            print("🧪 [DRY_RUN] 验证完成：未写日报、未推送企微、未更新 Memory。")
            return {"report": obsidian_content, "capsule": capsule}

        file_path = today_report_path
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(obsidian_content)
        print(f"[Daily] 负熵内参已落盘至 Obsidian: {file_path}")

        self.push_to_wecom(f"### 📊 投研早餐内参 ({today_str})\n\n{ai_analysis}")
        print("[Daily] 企微管道推送执行完毕。")

        capsule = self.generate_memory_capsule(today_str, ai_analysis, metrics, compact_news)
        self.save_memory_capsule(capsule)
        print("[Daily] 全链路收敛完成：今日判断已转化为明日记忆。")
        return {"report": obsidian_content, "capsule": capsule}

    def run_weekly_pipeline(self):
        """显式占位，避免 argparse 允许 weekly 但执行时静默失败。"""
        print("⚠️ weekly 模式尚未接入完整周报引擎。本版本已显式阻断静默失败。")


if __name__ == "__main__":
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "monitor"], required=True)
    args = parser.parse_args()

    engine = QuantAgent()
    try:
        if args.mode == "daily":
            engine.run_daily_pipeline()
        elif args.mode == "monitor":
            engine.run_monitor_pipeline()
        elif args.mode == "weekly":
            engine.run_weekly_pipeline()
    except DeepSeekError as e:
        print(f"❌ [AI Failure] {e}")
        raise SystemExit(2)

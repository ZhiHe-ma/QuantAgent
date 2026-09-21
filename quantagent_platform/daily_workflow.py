from __future__ import annotations

import json
from typing import Any


DAILY_SYSTEM_PROMPT = (
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


def build_daily_prompt(
    previous_memory: dict[str, Any],
    rolling_memory: list[dict[str, Any]],
    metrics: dict[str, Any],
    news_factors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "previous_memory_capsule": previous_memory,
        "rolling_7d_memory": rolling_memory,
        "market_hard_indicators": metrics,
        "24h_high_value_news_factors": news_factors,
        "task": "先审判昨日核心判断是否被市场证伪，再融合今日硬指标与重大快讯，输出今日风险基调。",
    }


def render_daily_report(
    *,
    report_date: str,
    metrics: dict[str, Any],
    previous_memory: dict[str, Any],
    news_factors: list[dict[str, Any]],
    raw_factor_count: int,
    analysis_text: str,
) -> str:
    macro = metrics["macro"]
    crypto = metrics["crypto"]
    spy_val = macro["S&P500_Chg%"]
    spy_str = f"{spy_val:+.2f}%" if isinstance(spy_val, (int, float)) else str(spy_val)
    vix_val = macro["VIX_Volatility"]
    vix_str = f"{vix_val:.2f}" if isinstance(vix_val, (int, float)) else str(vix_val)
    btc_chg_val = crypto["BTC_24h_Chg%"]
    btc_chg_str = f"{btc_chg_val:+.2f}%" if isinstance(btc_chg_val, (int, float)) else str(btc_chg_val)
    btc_price_val = crypto["BTC_Price"]
    btc_price_str = f"${btc_price_val:,.2f}" if isinstance(btc_price_val, (int, float)) else str(btc_price_val)
    fng_str = str(crypto["Fear_Greed"])

    return f"""---
type: quant-breakfast
date: {report_date}
btc_chg: {btc_chg_str}
vix: {vix_str}
factors_count_raw: {raw_factor_count}
factors_count_used: {len(news_factors)}
memory_enabled: true
---
# 📊 跨市场高精度分布式投研早餐 ({report_date})

## 🧠 昨日记忆胶囊
```json
{json.dumps(previous_memory, ensure_ascii=False, indent=2)}
```

## 🧭 跨市场硬指标对账单
- **[[Bitcoin]]**: {btc_price_str} ({btc_chg_str}) | 情绪面: 恐慌贪婪 {fng_str}
- **[[美股大盘]]**: 标普500变动 ({spy_str}) | VIX 波动率 ({vix_str})

## ⚡ 蓄水池重大异动影子库（原始 {raw_factor_count} 项 / 入模 {len(news_factors)} 项）
```json
{json.dumps(news_factors, ensure_ascii=False, indent=2)}
```

## 🧠 DeepSeek-R1 宏观因果螺旋推演
{analysis_text}
"""

"""Investor sentiment from free data: analyst ratings, rating changes, news headlines.

Headline scoring uses VADER (offline, free) extended with a small finance lexicon,
because general-purpose VADER scores phrases like "beats estimates" as neutral.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from stocksreport.data.fetcher import RawData
from stocksreport.models import SentimentSummary

# Polarity on VADER's -4..+4 scale. Loughran-McDonald-inspired.
FINANCE_LEXICON = {
    "beat": 2.0, "beats": 2.0, "topped": 1.8, "tops": 1.8, "surpass": 1.8, "surpasses": 1.8,
    "raise": 1.2, "raises": 1.5, "raised": 1.2, "upgrade": 2.2, "upgrades": 2.2, "upgraded": 2.2,
    "outperform": 2.0, "outperforms": 2.0, "bullish": 2.5, "rally": 1.8, "rallies": 1.8, "soar": 2.5,
    "soars": 2.5, "surge": 2.2, "surges": 2.2, "jumps": 1.8, "record": 1.5, "growth": 1.2, "profit": 1.2,
    "buyback": 1.5, "dividend": 0.8, "strong": 1.8, "rebound": 1.5, "upside": 1.5, "overweight": 1.5,
    "miss": -2.0, "misses": -2.0, "missed": -2.0, "cut": -1.5, "cuts": -1.8, "slash": -2.2, "slashes": -2.2,
    "downgrade": -2.2, "downgrades": -2.2, "downgraded": -2.2, "underperform": -2.0, "bearish": -2.5,
    "plunge": -2.8, "plunges": -2.8, "tumble": -2.5, "tumbles": -2.5, "slump": -2.2, "slumps": -2.2,
    "sink": -2.0, "sinks": -2.0, "falls": -1.5, "drop": -1.5, "drops": -1.5, "selloff": -2.2,
    "sell-off": -2.2, "lawsuit": -2.0, "probe": -1.8, "investigation": -1.8, "recall": -1.8,
    "layoffs": -1.5, "warning": -1.8, "weak": -1.8, "losses": -2.0, "loss": -1.5, "underweight": -1.5,
    "headwinds": -1.5, "antitrust": -1.5, "fine": -1.0, "fined": -2.0, "bankruptcy": -3.5, "default": -2.5,
    "losers": -2.0, "worst": -2.5,
}


@lru_cache(maxsize=1)
def _analyzer() -> SentimentIntensityAnalyzer:
    a = SentimentIntensityAnalyzer()
    a.lexicon.update(FINANCE_LEXICON)
    return a


def headline_score(text: str) -> float:
    return float(_analyzer().polarity_scores(text or "")["compound"])


def _label(x: Optional[float]) -> Optional[str]:
    if x is None:
        return None
    return "Positive" if x >= 0.15 else "Negative" if x <= -0.15 else "Neutral"


def rating_actions(ud: pd.DataFrame, as_of: date, days: int = 90) -> tuple[int, int, list[str]]:
    if ud is None or ud.empty:
        return 0, 0, []
    cutoff = pd.Timestamp(as_of - timedelta(days=days))
    recent = ud[(ud.index >= cutoff) & (ud.index <= pd.Timestamp(as_of) + pd.Timedelta(days=1))]
    act = recent.get("Action", pd.Series(dtype=str)).astype(str).str.lower()
    ups, downs = int((act == "up").sum()), int((act == "down").sum())
    lines = []
    for ts, r in recent.head(8).iterrows():
        tgt = r.get("currentPriceTarget")
        tgt_s = f", target ${tgt:,.0f}" if tgt and pd.notna(tgt) and tgt > 0 else ""
        lines.append(f"{ts:%Y-%m-%d} {r.get('Firm', '?')}: {r.get('Action', '')} "
                     f"{r.get('FromGrade') or '-'} → {r.get('ToGrade') or '-'}{tgt_s}")
    return ups, downs, lines


def _parse_news(item: dict) -> Optional[dict]:
    c = item.get("content", item)
    title = c.get("title")
    if not title:
        return None
    provider = c.get("provider") or {}
    url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
    when = c.get("pubDate") or c.get("displayTime")
    if not when and c.get("providerPublishTime"):
        when = datetime.fromtimestamp(c["providerPublishTime"], tz=timezone.utc).isoformat()
    text = f"{title}. {c.get('summary') or ''}"
    return {"title": title, "publisher": provider.get("displayName") or c.get("publisher"),
            "date": (when or "")[:10], "url": url, "score": round(headline_score(text), 3)}


def analyze(raw: RawData, as_of: date) -> SentimentSummary:
    s = SentimentSummary(recommendation_key=raw.info.get("recommendationKey"),
                         num_analysts=raw.info.get("numberOfAnalystOpinions"))

    rec = raw.recommendations
    if rec is not None and not rec.empty and {"strongBuy", "buy", "hold", "sell", "strongSell"} <= set(rec.columns):
        cur = rec.iloc[0]
        s.analyst_counts = {"Strong Buy": int(cur["strongBuy"]), "Buy": int(cur["buy"]), "Hold": int(cur["hold"]),
                            "Sell": int(cur["sell"]), "Strong Sell": int(cur["strongSell"])}
        if len(rec) > 1:
            def bullish(r):
                tot = sum(int(r[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
                return (int(r["strongBuy"]) + int(r["buy"])) / tot if tot else 0
            delta = bullish(cur) - bullish(rec.iloc[-1])
            s.analyst_trend = ("improving" if delta > 0.03 else "deteriorating" if delta < -0.03 else "stable")

    s.upgrades_90d, s.downgrades_90d, s.recent_actions = rating_actions(raw.upgrades_downgrades, as_of)

    heads = [h for h in (_parse_news(n) for n in (raw.news or [])) if h]
    s.headlines = heads[:10]
    if heads:
        s.news_score = round(sum(h["score"] for h in heads) / len(heads), 3)
        s.news_label = _label(s.news_score)
    return s

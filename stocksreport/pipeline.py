"""End-to-end pipeline: ticker -> StockReport."""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd

from stocksreport import config
from stocksreport.analysis import benchmark, metrics, narrative, scoring, sentiment
from stocksreport.data import fetcher
from stocksreport.data.fetcher import RawData
from stocksreport.models import CompanyProfile, Metrics, StockReport, VerificationResult
from stocksreport.verify import reconcile, sources

log = logging.getLogger(__name__)


def _profile(raw: RawData) -> CompanyProfile:
    i = raw.info
    return CompanyProfile(
        ticker=raw.ticker, name=i.get("longName") or i.get("shortName") or raw.ticker,
        sector=i.get("sector"), industry=i.get("industry"), country=i.get("country"),
        website=i.get("website"), employees=i.get("fullTimeEmployees"),
        summary=i.get("longBusinessSummary"), currency=i.get("currency") or "USD",
        exchange=i.get("fullExchangeName") or i.get("exchange"),
    )


def _normalised_history(raw: RawData, histories: dict[str, pd.DataFrame], days: int = 252) -> dict[str, dict[str, float]]:
    """1Y adjusted-close series rebased to 100, keyed by series label."""
    out = {}
    series = {raw.ticker: raw.history, **histories}
    for label, df in series.items():
        if df is None or df.empty:
            continue
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        s = df[col].dropna().iloc[-days - 1:]
        out[label] = {d.strftime("%Y-%m-%d"): round(float(v / s.iloc[0] * 100), 3) for d, v in s.items()}
    return out


def build_report(raw: RawData, histories: dict[str, pd.DataFrame], peer_infos: dict[str, dict],
                 as_of: Optional[date] = None, verification: Optional[VerificationResult] = None,
                 m: Optional[Metrics] = None, sec_facts: Optional[dict] = None) -> StockReport:
    """Pure analysis step (no network) - used by tests and by `analyze`.

    If a verification result is supplied, SEC-filed values override conflicting yfinance figures
    before scoring, so the verdict is based on verified data.
    """
    as_of = as_of or date.today()
    m = m or metrics.compute(raw)
    corrections = reconcile.apply_sec_corrections(m, verification, raw, sec_facts) if verification else []
    if corrections:  # re-check derived ratios against the corrected metrics
        verification.checks = ([c for c in verification.checks if c.category != "Derived ratio"]
                               + reconcile.derived_checks(raw, m))
    bench = benchmark.compare(raw, m, histories, peer_infos)
    sector = raw.info.get("sector")
    sc = scoring.score(m, bench, raw.info, raw.price_targets, sector)
    sent = sentiment.analyze(raw, as_of)
    prof = _profile(raw)
    analysis = narrative.build(raw.ticker, prof.name, m, bench, sc, sent, sector)
    return StockReport(as_of=as_of, profile=prof, metrics=m, benchmark=bench, score=sc, sentiment=sent,
                       analysis=analysis, verification=verification, data_corrections=corrections,
                       price_history=_normalised_history(raw, histories))


def analyze(ticker: str, peers: Optional[list[str]] = None, use_cache: bool = True,
            verify: bool = True) -> StockReport:
    raw = fetcher.fetch(ticker, use_cache=use_cache)
    sector = raw.info.get("sector")
    symbols = [config.MARKET_BENCHMARK] + ([config.SECTOR_ETF[sector]] if sector in config.SECTOR_ETF else [])
    histories = {s: fetcher.fetch_history(s, use_cache=use_cache) for s in symbols}
    peer_infos = {p: fetcher.fetch_info(p, use_cache=use_cache) for p in benchmark.pick_peers(raw.ticker, sector, peers)}
    m = metrics.compute(raw)
    verification, facts = None, None
    if verify:
        try:
            facts = sources.sec_companyfacts(raw.ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("SEC fetch failed for %s: %s", ticker, exc)
        try:
            verification = reconcile.verify(raw, m, sec_facts=facts)
        except Exception as exc:  # noqa: BLE001 - verification must never block the report
            log.warning("verification failed for %s: %s", ticker, exc)
    return build_report(raw, histories, peer_infos, verification=verification, m=m, sec_facts=facts)


def analyze_many(tickers: list[str], **kw) -> list[StockReport]:
    out = []
    for t in tickers:
        try:
            out.append(analyze(t, **kw))
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to analyse %s: %s", t, exc)
    return out

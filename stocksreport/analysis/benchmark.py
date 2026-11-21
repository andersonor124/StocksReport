"""Compare a stock with the S&P 500 (SPY), its sector ETF and sector peers."""
from __future__ import annotations

import statistics
from typing import Optional

import pandas as pd

from stocksreport import config
from stocksreport.data.fetcher import RawData
from stocksreport.models import BenchmarkComparison, Metrics, PeerRow, PeriodReturn


def period_return(df: pd.DataFrame, days: int) -> Optional[float]:
    """Total return over `days` trading sessions using dividend/split-adjusted closes."""
    if df is None or df.empty:
        return None
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col].dropna()
    if len(s) <= days:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1)


def ytd_return(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty:
        return None
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col].dropna()
    prior = s[s.index < pd.Timestamp(year=s.index[-1].year, month=1, day=1)]
    return float(s.iloc[-1] / prior.iloc[-1] - 1) if len(prior) else None


def _f(info: dict, key: str) -> Optional[float]:
    v = info.get(key)
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def peer_row(ticker: str, info: dict) -> PeerRow:
    return PeerRow(
        ticker=ticker,
        name=info.get("shortName"),
        market_cap=_f(info, "marketCap"),
        pe_ttm=_f(info, "trailingPE"),
        forward_pe=_f(info, "forwardPE"),
        price_to_sales=_f(info, "priceToSalesTrailing12Months"),
        net_margin=_f(info, "profitMargins"),
        roe=_f(info, "returnOnEquity"),
        revenue_growth_yoy=_f(info, "revenueGrowth"),
    )


_POSITIVE_ONLY = {"pe_ttm", "forward_pe", "price_to_sales"}  # negative multiples are meaningless


def median_row(peers: list[PeerRow]) -> PeerRow:
    out = PeerRow(ticker="Peer median")
    for field in ("market_cap", "pe_ttm", "forward_pe", "price_to_sales", "net_margin", "roe", "revenue_growth_yoy"):
        vals = [getattr(p, field) for p in peers if getattr(p, field) is not None]
        if field in _POSITIVE_ONLY:
            vals = [v for v in vals if v > 0]
        if vals:
            setattr(out, field, float(statistics.median(vals)))
    return out


def pick_peers(ticker: str, sector: Optional[str], override: Optional[list[str]] = None) -> list[str]:
    if override:
        return [p.upper() for p in override if p.upper() != ticker.upper()][: config.MAX_PEERS]
    return [p for p in config.SECTOR_PEERS.get(sector or "", []) if p != ticker.upper()][: config.MAX_PEERS]


def compare(raw: RawData, metrics: Metrics, histories: dict[str, pd.DataFrame],
            peer_infos: dict[str, dict]) -> BenchmarkComparison:
    sector_etf = config.SECTOR_ETF.get(raw.info.get("sector") or "")
    market = histories.get(config.MARKET_BENCHMARK)
    sector = histories.get(sector_etf) if sector_etf else None

    returns = []
    for label, days in config.RETURN_PERIODS.items():
        returns.append(PeriodReturn(period=label, stock=period_return(raw.history, days),
                                    market=period_return(market, days), sector=period_return(sector, days)))
    returns.insert(3, PeriodReturn(period="YTD", stock=ytd_return(raw.history), market=ytd_return(market),
                                   sector=ytd_return(sector)))

    peers = [peer_row(t, i) for t, i in peer_infos.items() if i and t.upper() != raw.ticker.upper()]
    return BenchmarkComparison(
        market_ticker=config.MARKET_BENCHMARK,
        sector_ticker=sector_etf,
        returns=returns,
        peers=peers,
        peer_median=median_row(peers),
    )

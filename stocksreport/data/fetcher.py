"""Retrieve raw market and company data from Yahoo Finance via yfinance.

`RawData` is a plain container so the analysis layer can be unit-tested offline
against recorded fixtures (see tests/fixtures/*.pkl).
"""
from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from stocksreport import config

log = logging.getLogger(__name__)


@dataclass
class RawData:
    ticker: str
    info: dict[str, Any]
    history: pd.DataFrame  # daily OHLCV, ~5y, tz-naive index
    income_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    income_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    recommendations: pd.DataFrame = field(default_factory=pd.DataFrame)
    upgrades_downgrades: pd.DataFrame = field(default_factory=pd.DataFrame)
    price_targets: dict[str, Any] = field(default_factory=dict)
    news: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str | Path) -> "RawData":
        with open(path, "rb") as f:
            return pickle.load(f)


def _safe(fn, default):
    """yfinance endpoints fail independently; one missing piece must not kill the report."""
    try:
        val = fn()
        return default if val is None else val
    except Exception as exc:  # noqa: BLE001 - network/parse errors from yfinance are varied
        log.warning("yfinance call failed: %s", exc)
        return default


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _cache_path(ticker: str, kind: str) -> Path:
    return Path(config.CACHE_DIR) / f"{ticker.upper()}_{kind}.pkl"


def _cache_get(ticker: str, kind: str):
    p = _cache_path(ticker, kind)
    if p.exists() and (time.time() - p.stat().st_mtime) < config.CACHE_TTL_HOURS * 3600:
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def _cache_put(ticker: str, kind: str, obj) -> None:
    p = _cache_path(ticker, kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(obj, f)


def fetch(ticker: str, use_cache: bool = True, period: str = "5y") -> RawData:
    """Fetch everything needed for a full report on one ticker."""
    import yfinance as yf

    ticker = ticker.upper().strip()
    if use_cache and (cached := _cache_get(ticker, f"full_{period}")) is not None:
        return cached

    t = yf.Ticker(ticker)
    info = _safe(lambda: t.info, {})
    history = _naive(_safe(lambda: t.history(period=period, auto_adjust=False), pd.DataFrame()))
    if history.empty and not info.get("regularMarketPrice") and not info.get("currentPrice"):
        raise ValueError(f"No market data found for ticker '{ticker}'. Check the symbol.")

    raw = RawData(
        ticker=ticker,
        info=info,
        history=history,
        income_annual=_safe(lambda: t.income_stmt, pd.DataFrame()),
        income_quarterly=_safe(lambda: t.quarterly_income_stmt, pd.DataFrame()),
        balance_annual=_safe(lambda: t.balance_sheet, pd.DataFrame()),
        balance_quarterly=_safe(lambda: t.quarterly_balance_sheet, pd.DataFrame()),
        cashflow_annual=_safe(lambda: t.cashflow, pd.DataFrame()),
        cashflow_quarterly=_safe(lambda: t.quarterly_cashflow, pd.DataFrame()),
        recommendations=_safe(lambda: t.recommendations, pd.DataFrame()),
        upgrades_downgrades=_naive(_safe(lambda: t.upgrades_downgrades, pd.DataFrame())),
        price_targets=_safe(lambda: t.analyst_price_targets, {}),
        news=_safe(lambda: t.news, []),
    )
    if use_cache:
        _cache_put(ticker, f"full_{period}", raw)
    return raw


def fetch_history(ticker: str, period: str = "5y", use_cache: bool = True) -> pd.DataFrame:
    """Price history only (benchmarks / ETFs)."""
    import yfinance as yf

    if use_cache and (cached := _cache_get(ticker, f"hist_{period}")) is not None:
        return cached
    df = _naive(_safe(lambda: yf.Ticker(ticker).history(period=period, auto_adjust=False), pd.DataFrame()))
    if use_cache and not df.empty:
        _cache_put(ticker, f"hist_{period}", df)
    return df


def fetch_info(ticker: str, use_cache: bool = True) -> dict[str, Any]:
    """Company info only (peers)."""
    import yfinance as yf

    if use_cache and (cached := _cache_get(ticker, "info")) is not None:
        return cached
    info = _safe(lambda: yf.Ticker(ticker).info, {})
    if use_cache and info:
        _cache_put(ticker, "info", info)
    return info


def row(df: pd.DataFrame, *names: str, col: int = 0) -> Optional[float]:
    """First available value of any of `names` in column `col` of a statement frame."""
    if df is None or df.empty or col >= df.shape[1]:
        return None
    for n in names:
        if n in df.index:
            v = df.iloc[:, col].get(n)
            if v is not None and pd.notna(v):
                return float(v)
    return None

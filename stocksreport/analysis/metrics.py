"""Compute canonical metrics from raw statements and prices.

Principle: wherever a metric can be derived from the reported statements and the
price history, we compute it ourselves (source="computed") rather than trusting
pre-computed fields in yfinance `info`, which mix units (e.g. dividendYield is a
percent) and sometimes have gaps. `info` is used only as a fallback (source="yfinance").
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from stocksreport import config
from stocksreport.data.fetcher import RawData, row
from stocksreport.models import Metrics

TRADING_DAYS = 252


def quarters_consecutive(cols) -> bool:
    """True if the column dates are successive quarter-ends (~91 days apart, newest first)."""
    d = pd.to_datetime(list(cols))
    if len(d) < 2:
        return True
    gaps = [(d[i] - d[i + 1]).days for i in range(len(d) - 1)]
    return all(80 <= g <= 100 for g in gaps)


def _ttm(q: pd.DataFrame, a: pd.DataFrame, *names: str) -> tuple[Optional[float], str]:
    """Sum of the last 4 quarters if complete and consecutive, else latest annual value."""
    if q is not None and not q.empty and q.shape[1] >= 4 and quarters_consecutive(q.columns[:4]):
        for n in names:
            if n in q.index:
                vals = q.loc[n].iloc[:4]
                if vals.notna().all():
                    return float(vals.sum()), "computed"
    v = row(a, *names)
    return (v, "annual") if v is not None else (None, "missing")


def _eps_ttm(raw: RawData) -> tuple[Optional[float], str]:
    q = raw.income_quarterly
    if q is not None and q.shape[1] >= 4 and quarters_consecutive(q.columns[:4]) and "Diluted EPS" in q.index:
        total = 0.0
        for i in range(4):
            eps = q.loc["Diluted EPS"].iloc[i]
            if pd.isna(eps):
                ni = row(q, "Net Income Common Stockholders", "Net Income", col=i)
                sh = row(q, "Diluted Average Shares", col=i)
                if ni is None or not sh:
                    break
                eps = ni / sh  # back-fill a missing quarter from its own components
            total += float(eps)
        else:
            return total, "computed"
    v = row(raw.income_annual, "Diluted EPS")
    if v is not None:
        return v, "annual"
    v = raw.info.get("trailingEps")
    return (float(v), "yfinance") if v is not None else (None, "missing")


def max_drawdown(prices: pd.Series) -> float:
    running_max = prices.cummax()
    return float((prices / running_max - 1).min())


def annualised_volatility(prices: pd.Series) -> float:
    r = prices.pct_change().dropna()
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(r) > 1 else 0.0


def _div(a, b) -> Optional[float]:
    if a is None or b is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return float(a) / float(b)


def _info(info: dict, key: str) -> Optional[float]:
    v = info.get(key)
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def compute(raw: RawData) -> Metrics:
    info = raw.info
    src: dict[str, str] = {}
    hist = raw.history
    close = hist["Close"].dropna() if not hist.empty else pd.Series(dtype=float)

    # Price: last close in history, else live quote.
    if not close.empty:
        price, src["price"] = float(close.iloc[-1]), "computed"
    else:
        price, src["price"] = _info(info, "currentPrice") or _info(info, "regularMarketPrice"), "yfinance"

    shares = _info(info, "sharesOutstanding")
    src["shares_outstanding"] = "yfinance"
    if shares is None:
        shares = row(raw.balance_quarterly, "Ordinary Shares Number") or row(raw.balance_annual, "Ordinary Shares Number")
        src["shares_outstanding"] = "computed"
    market_cap = price * shares if price and shares else _info(info, "marketCap")
    src["market_cap"] = "computed" if price and shares else "yfinance"

    iq, ia = raw.income_quarterly, raw.income_annual
    revenue, src["revenue_ttm"] = _ttm(iq, ia, "Total Revenue", "Operating Revenue")
    net_income, src["net_income_ttm"] = _ttm(iq, ia, "Net Income", "Net Income Common Stockholders")
    gross, _ = _ttm(iq, ia, "Gross Profit")
    op_inc, _ = _ttm(iq, ia, "Operating Income")
    eps, src["eps_ttm"] = _eps_ttm(raw)

    sector = info.get("sector")
    is_fin = sector in config.DEBT_EXEMPT_SECTORS

    equity = row(raw.balance_quarterly, "Stockholders Equity", "Common Stock Equity") or row(
        raw.balance_annual, "Stockholders Equity", "Common Stock Equity"
    )
    debt = row(raw.balance_quarterly, "Total Debt") or row(raw.balance_annual, "Total Debt")

    cq, ca = raw.cashflow_quarterly, raw.cashflow_annual
    ocf, _ = _ttm(cq, ca, "Operating Cash Flow")
    capex, _ = _ttm(cq, ca, "Capital Expenditure")
    fcf = None
    if ocf is not None and not is_fin:  # bank "FCF" is dominated by deposit/loan flows - meaningless
        fcf = ocf + (capex or 0.0)

    # Growth: latest fiscal year vs prior fiscal year (annual statements).
    rev_growth = _div(row(ia, "Total Revenue", col=0), row(ia, "Total Revenue", col=1))
    rev_growth = rev_growth - 1 if rev_growth is not None else _info(info, "revenueGrowth")
    eps_growth = None
    e0, e1 = row(ia, "Diluted EPS", col=0), row(ia, "Diluted EPS", col=1)
    if e0 is not None and e1 and e1 > 0:
        eps_growth = e0 / e1 - 1

    # Dividend yield from dividends actually paid over the last 365 days.
    div_yield = None
    if "Dividends" in hist.columns and price:
        last_year = hist[hist.index >= hist.index[-1] - pd.Timedelta(days=365)]
        paid = float(last_year["Dividends"].sum())
        div_yield = paid / price if paid > 0 else 0.0

    one_year = close[close.index >= close.index[-1] - pd.Timedelta(days=365)] if not close.empty else close
    fwd_eps = _info(info, "forwardEps")
    forward_pe = _div(price, fwd_eps) if fwd_eps and fwd_eps > 0 else None
    pe = _div(price, eps) if eps and eps > 0 else None
    peg = None
    if pe and eps and fwd_eps and fwd_eps > eps:
        peg = pe / ((fwd_eps / eps - 1) * 100)
    peg = peg if peg is not None else _info(info, "trailingPegRatio")
    if peg is not None and peg <= 0:  # negative PEG (falling earnings) is not meaningful
        peg = None

    m = Metrics(
        price=price,
        market_cap=market_cap,
        shares_outstanding=shares,
        revenue_ttm=revenue,
        net_income_ttm=net_income,
        equity=equity,
        eps_ttm=eps,
        forward_eps=fwd_eps,
        pe_ttm=pe,
        forward_pe=forward_pe,
        peg=peg,
        price_to_sales=_div(market_cap, revenue),
        price_to_book=_div(market_cap, equity),
        ev_to_ebitda=_info(info, "enterpriseToEbitda"),
        gross_margin=_div(gross, revenue) if gross else None,
        operating_margin=_div(op_inc, revenue),
        net_margin=_div(net_income, revenue),
        roe=_div(net_income, equity),
        debt_to_equity=None if is_fin else _div(debt, equity),
        fcf_ttm=fcf,
        fcf_yield=_div(fcf, market_cap),
        revenue_growth_yoy=rev_growth,
        eps_growth_yoy=eps_growth,
        dividend_yield=div_yield,
        beta=_info(info, "beta"),
        volatility_1y=annualised_volatility(one_year) if len(one_year) > 20 else None,
        max_drawdown_1y=max_drawdown(one_year) if len(one_year) > 20 else None,
        pct_from_52w_high=(price / float(one_year.max()) - 1) if len(one_year) else None,
        above_200dma=bool(price > close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None,
        sources=src,
    )
    for k in ("pe_ttm", "price_to_sales", "price_to_book", "net_margin", "gross_margin", "operating_margin",
              "roe", "debt_to_equity", "fcf_yield", "dividend_yield", "volatility_1y", "max_drawdown_1y"):
        m.sources.setdefault(k, "computed")
    m.sources.update({"forward_eps": "yfinance", "ev_to_ebitda": "yfinance", "beta": "yfinance"})
    return m

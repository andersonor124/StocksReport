"""Independent primary/secondary data sources used to verify yfinance values.

* SEC EDGAR XBRL "companyfacts": figures exactly as filed in 10-K / 10-Q reports.
* Nasdaq historical quotes API: an independent end-of-day price feed.

Both are free and need no API key. The SEC requires a descriptive User-Agent with
contact details (https://www.sec.gov/os/accessing-edgar-data); set SEC_USER_AGENT,
e.g. "Jane Doe jane@example.com".
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

_DEFAULT_UA = "StocksReport research-tool contact@example.com"
NASDAQ_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0 Safari/537.36")

# Tags we keep from companyfacts (also defines the fixture trimming).
SEC_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "RevenuesNetOfInterestExpense",
                "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}


def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        log.warning("SEC_USER_AGENT not set; using a placeholder. Set it to 'Your Name your@email' per SEC policy.")
        return _DEFAULT_UA
    return ua


def _get(url: str, headers: dict, timeout: int = 60) -> requests.Response:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r


@lru_cache(maxsize=1)
def _company_tickers() -> dict:
    return _get("https://www.sec.gov/files/company_tickers.json", {"User-Agent": sec_user_agent()}).json()


@lru_cache(maxsize=1)
def _ticker_map() -> dict[str, int]:
    return {v["ticker"].upper(): int(v["cik_str"]) for v in _company_tickers().values()}


def sec_companies() -> list[tuple[str, str]]:
    """(ticker, company name) for every SEC registrant - used to look up companies by name."""
    return [(v["ticker"].upper(), v["title"]) for v in _company_tickers().values()]


def sec_cik(ticker: str) -> Optional[int]:
    return _ticker_map().get(ticker.upper().replace("-", "."), _ticker_map().get(ticker.upper()))


def trim_companyfacts(facts: dict) -> dict:
    """Keep only the tags we verify (companyfacts can be >5 MB)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    keep = {t for tags in SEC_TAGS.values() for t in tags}
    return {
        "cik": facts.get("cik"),
        "entityName": facts.get("entityName"),
        "facts": {
            "us-gaap": {k: v for k, v in gaap.items() if k in keep},
            "dei": {k: v for k, v in facts.get("facts", {}).get("dei", {}).items()
                    if k == "EntityCommonStockSharesOutstanding"},
        },
    }


def sec_companyfacts(ticker: str) -> Optional[dict]:
    cik = sec_cik(ticker)
    if cik is None:
        return None  # not an SEC registrant (e.g. many foreign listings)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    return trim_companyfacts(_get(url, {"User-Agent": sec_user_agent()}).json())


def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def parse_nasdaq_rows(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame({
        "Date": pd.to_datetime([r["date"] for r in rows], format="%m/%d/%Y"),
        "Close": [_money(r["close"]) for r in rows],
        "Open": [_money(r["open"]) if r.get("open") not in (None, "N/A") else None for r in rows],
        "Volume": [float(r["volume"].replace(",", "")) if r.get("volume") not in (None, "N/A") else None
                   for r in rows],
    }).set_index("Date").sort_index()
    return df


def nasdaq_history(ticker: str, days: int = 400, assetclass: str = "stocks") -> pd.DataFrame:
    """Daily close (split-adjusted, not dividend-adjusted) from Nasdaq's public quote API."""
    to = date.today()
    frm = to - timedelta(days=days)
    url = (f"https://api.nasdaq.com/api/quote/{ticker.upper()}/historical?assetclass={assetclass}"
           f"&fromdate={frm:%Y-%m-%d}&todate={to:%Y-%m-%d}&limit=9999")
    js = _get(url, {"User-Agent": NASDAQ_UA, "Accept": "application/json"}, timeout=60).json()
    rows = ((js.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows and assetclass == "stocks":
        return nasdaq_history(ticker, days, assetclass="etf")
    return parse_nasdaq_rows(rows) if rows else pd.DataFrame()

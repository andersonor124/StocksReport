"""Reconcile pipeline data (yfinance) against primary sources.

Categories
----------
SEC filing            yfinance statement value vs the value filed with the SEC (XBRL).
Price                 yfinance daily close vs Nasdaq's independent end-of-day feed.
Derived ratio         our ratio (computed from statements) vs Yahoo's pre-computed field.
Internal consistency  accounting identities / quarterly-vs-annual sums inside the yfinance data.

Status: PASS within `pass_tol`, WARN within `warn_tol`, FAIL beyond, SKIP if a value is missing.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from stocksreport.data.fetcher import RawData, row
from stocksreport.models import Metrics, VerificationCheck, VerificationResult
from stocksreport.verify import sources

log = logging.getLogger(__name__)

SEC_SRC = "SEC EDGAR XBRL"
NASDAQ_SRC = "Nasdaq EOD"
YAHOO_SRC = "Yahoo pre-computed"


def compare_values(a: Optional[float], b: Optional[float], pass_tol: float = 0.005, warn_tol: float = 0.02,
                   absolute: Optional[float] = None, category: str = "", field: str = "",
                   source: str = "", period: Optional[str] = None, note: Optional[str] = None,
                   fail_status: str = "FAIL") -> VerificationCheck:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return VerificationCheck(category=category, field=field, period=period, pipeline_value=a,
                                 source_value=b, source=source, status="SKIP",
                                 note=note or "value not available in one of the sources")
    diff = (a - b) / abs(b) if b else (0.0 if a == b else float("inf"))
    if absolute is not None:  # e.g. EPS compared to the cent
        ok, near = abs(a - b) <= absolute, abs(a - b) <= absolute * 5
    else:
        ok, near = abs(diff) <= pass_tol, abs(diff) <= warn_tol
    status = "PASS" if ok else "WARN" if near else fail_status
    return VerificationCheck(category=category, field=field, period=period, pipeline_value=float(a),
                             source_value=float(b), source=source, diff_pct=round(diff * 100, 4),
                             status=status, note=note)


# ---------------------------------------------------------------- SEC helpers

def _duration_ok(row_: dict, duration: str) -> bool:
    start = row_.get("start")
    if duration == "instant":
        return start is None
    if start is None:
        return False
    days = (pd.Timestamp(row_["end"]) - pd.Timestamp(start)).days
    return 350 <= days <= 380 if duration == "annual" else 80 <= days <= 100


def _find(rows: list[dict], period_end: pd.Timestamp, ok, max_days: int) -> Optional[dict]:
    cands = [r for r in rows if abs((pd.Timestamp(r["end"]) - period_end).days) <= max_days and ok(r)
             and r.get("form", "").startswith(("10-K", "10-Q"))]
    return max(cands, key=lambda r: r.get("filed", "")) if cands else None  # latest filing = restated value


# Flow items that are additive across quarters (EPS is not: share counts change).
_ADDITIVE = {"revenue", "net_income", "gross_profit", "operating_income", "operating_cash_flow"}


def sec_value(facts: Optional[dict], key: str, period_end: pd.Timestamp, duration: str,
              max_days: int = 7) -> tuple[Optional[float], Optional[str]]:
    """Value filed for `key` for the period ending ~`period_end`. Tags tried in fixed priority order.

    A fiscal Q4 is usually not filed as a 3-month figure (the 10-K reports the full year), so for
    additive items it is derived as FY total minus the 9-month year-to-date figure from the Q3 10-Q.
    """
    if not facts:
        return None, None
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in sources.SEC_TAGS[key]:
        for rows in gaap.get(tag, {}).get("units", {}).values():
            hit = _find(rows, period_end, lambda r: _duration_ok(r, duration), max_days)
            if hit:
                return float(hit["val"]), tag
            if duration == "quarter" and key in _ADDITIVE:
                fy = _find(rows, period_end, lambda r: _duration_ok(r, "annual"), max_days)
                if fy:
                    def nine_months(r, fy_start=pd.Timestamp(fy["start"])):
                        return (r.get("start") and abs((pd.Timestamp(r["start"]) - fy_start).days) <= max_days
                                and 255 <= (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days <= 285)
                    ytd = _find(rows, period_end - pd.Timedelta(days=91), nine_months, 10)
                    if ytd:
                        return float(fy["val"]) - float(ytd["val"]), f"{tag} (FY − 9M YTD)"
    return None, None


def _sec_checks(raw: RawData, facts: Optional[dict]) -> list[VerificationCheck]:
    out: list[VerificationCheck] = []
    if not facts:
        out.append(VerificationCheck(category="SEC filing", field="All fundamentals", source=SEC_SRC,
                                     status="SKIP", note="company not found in SEC EDGAR (non-US filer?)"))
        return out

    def add(key, label, df, names, col, duration, **kw):
        if df is None or df.empty or col >= df.shape[1]:
            return
        end = pd.Timestamp(df.columns[col])
        ours = row(df, *names, col=col)
        theirs, tag = sec_value(facts, key, end, duration)
        period = f"{'FY' if duration == 'annual' else 'Q' if duration == 'quarter' else 'as of'} {end:%Y-%m-%d}"
        note = f"XBRL tag {tag}" if tag else "no matching SEC fact for this period"
        if key == "revenue" and tag and tag.split(" ")[0] == "Revenues":
            # The generic `Revenues` tag is used by some filers (e.g. XOM since 2024) for "total revenues
            # and other income", which includes equity-affiliate and other income that data vendors
            # exclude. With no like-for-like tag available, small gaps are a definition issue, not an error.
            kw = {**kw, "warn_tol": 0.05}
            note += " (broad tag: may include other income; definitions can differ by a few %)"
        out.append(compare_values(ours, theirs, category="SEC filing", field=label, source=SEC_SRC,
                                  period=period, note=note, **kw))

    ia, iq = raw.income_annual, raw.income_quarterly
    for col in (0, 1):  # two most recent fiscal years
        add("revenue", "Revenue", ia, ["Total Revenue", "Operating Revenue"], col, "annual")
        add("net_income", "Net income", ia, ["Net Income"], col, "annual")
        add("eps_diluted", "Diluted EPS", ia, ["Diluted EPS"], col, "annual", absolute=0.011)
        add("gross_profit", "Gross profit", ia, ["Gross Profit"], col, "annual")
        add("operating_income", "Operating income", ia, ["Operating Income"], col, "annual")
        add("diluted_shares", "Diluted avg shares", ia, ["Diluted Average Shares"], col, "annual")
        add("operating_cash_flow", "Operating cash flow", raw.cashflow_annual, ["Operating Cash Flow"], col,
            "annual")
    add("revenue", "Revenue", iq, ["Total Revenue", "Operating Revenue"], 0, "quarter")
    add("net_income", "Net income", iq, ["Net Income"], 0, "quarter")
    add("eps_diluted", "Diluted EPS", iq, ["Diluted EPS"], 0, "quarter", absolute=0.011)
    bq = raw.balance_quarterly if not raw.balance_quarterly.empty else raw.balance_annual
    add("total_assets", "Total assets", bq, ["Total Assets"], 0, "instant")
    add("total_liabilities", "Total liabilities", bq, ["Total Liabilities Net Minority Interest"], 0, "instant")
    add("equity", "Stockholders' equity", bq, ["Stockholders Equity"], 0, "instant")

    dei = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
    sh_rows = [r for u in dei.get("units", {}).values() for r in u]
    if sh_rows:
        latest = max(sh_rows, key=lambda r: (r["end"], r.get("filed", "")))
        out.append(compare_values(raw.info.get("sharesOutstanding"), latest["val"], pass_tol=0.01, warn_tol=0.03,
                                  category="SEC filing", field="Shares outstanding", source=SEC_SRC,
                                  period=f"cover page {latest['end']}",
                                  note="buybacks between the cover date and today cause small gaps"))
    # Drop rows where yfinance itself has no such line item (e.g. gross profit for banks).
    return [c for c in out if not (c.status == "SKIP" and c.pipeline_value is None and c.source_value is None)]


# ---------------------------------------------------------------- price checks

def _price_checks(raw: RawData, nasdaq: Optional[pd.DataFrame], tol: float = 0.005) -> list[VerificationCheck]:
    if nasdaq is None or nasdaq.empty or raw.history.empty:
        return [VerificationCheck(category="Price", field="Daily closes", source=NASDAQ_SRC, status="SKIP",
                                  note="independent price feed unavailable")]
    ours = raw.history["Close"].dropna()
    ours.index = pd.to_datetime(ours.index).normalize()
    theirs = nasdaq["Close"].dropna()
    theirs.index = pd.to_datetime(theirs.index).normalize()
    joined = pd.concat([ours.rename("y"), theirs.rename("n")], axis=1, join="inner").dropna().iloc[-250:]
    out = []

    last_day = ours.index[-1]
    out.append(compare_values(float(ours.iloc[-1]), float(theirs[last_day]) if last_day in theirs.index else None,
                              pass_tol=tol, category="Price", field="Latest close", source=NASDAQ_SRC,
                              period=f"{last_day:%Y-%m-%d}"))

    dev = (joined["y"] / joined["n"] - 1).abs()
    n_bad = int((dev > tol).sum())
    status = "PASS" if n_bad == 0 else "WARN" if n_bad <= max(1, len(dev) // 50) else "FAIL"
    worst = dev.idxmax() if len(dev) else None
    out.append(VerificationCheck(
        category="Price", field=f"Daily closes ({len(joined)} sessions)",
        period=f"{joined.index[0]:%Y-%m-%d} → {joined.index[-1]:%Y-%m-%d}" if len(joined) else None,
        pipeline_value=float(joined.loc[worst, "y"]) if worst is not None else None,
        source_value=float(joined.loc[worst, "n"]) if worst is not None else None,
        source=NASDAQ_SRC, diff_pct=round(float(dev.max()) * 100, 4) if len(dev) else None, status=status,
        note=f"{n_bad} session(s) differ by > {tol:.1%}; largest gap on {worst:%Y-%m-%d}" if worst is not None
        else "no overlapping sessions"))

    window = ours.index[ours.index >= joined.index[0]] if len(joined) else ours.index
    missing = len(set(window) - set(theirs.index))
    out.append(VerificationCheck(category="Price", field="Session coverage", source=NASDAQ_SRC,
                                 pipeline_value=float(len(window)), source_value=float(len(window) - missing),
                                 status="PASS" if missing <= 1 else "WARN",
                                 note=f"{missing} yfinance session(s) absent from Nasdaq"))
    return out


# ---------------------------------------------------------------- derived ratios

def derived_checks(raw: RawData, m: Metrics) -> list[VerificationCheck]:
    i = raw.info

    def y(key, div=1.0):
        v = i.get(key)
        return None if v is None else float(v) / div

    note = "different definition/timing at Yahoo; report uses our value computed from filed statements"
    specs = [
        ("Market cap", m.market_cap, y("marketCap"), 0.01),
        ("EPS (TTM)", m.eps_ttm, y("trailingEps"), 0.01),
        ("P/E (TTM)", m.pe_ttm, y("trailingPE"), 0.01),
        ("Revenue (TTM)", m.revenue_ttm, y("totalRevenue"), 0.01),
        ("Price/Sales", m.price_to_sales, y("priceToSalesTrailing12Months"), 0.01),
        ("Net margin", m.net_margin, y("profitMargins"), 0.02),
        ("Gross margin", m.gross_margin, y("grossMargins") or None, 0.02),
        ("Return on equity", m.roe, y("returnOnEquity"), 0.05),
        ("Debt/Equity", m.debt_to_equity, y("debtToEquity", 100), 0.05),
        ("Dividend yield", m.dividend_yield, y("dividendYield", 100), 0.05),
    ]
    out = []
    for field, ours, theirs, tol in specs:
        c = compare_values(ours, theirs, pass_tol=tol, warn_tol=0.25, category="Derived ratio", field=field,
                           source=YAHOO_SRC)
        if c.status in ("WARN", "FAIL"):
            c.note = note
        out.append(c)
    return [c for c in out if not (c.status == "SKIP" and c.pipeline_value is None and c.source_value is None)]


# ---------------------------------------------------------------- internal consistency

def _consistency_checks(raw: RawData) -> list[VerificationCheck]:
    out = []
    b = raw.balance_quarterly if not raw.balance_quarterly.empty else raw.balance_annual
    assets = row(b, "Total Assets")
    liab = row(b, "Total Liabilities Net Minority Interest")
    eq = row(b, "Total Equity Gross Minority Interest", "Stockholders Equity")
    out.append(compare_values(assets, (liab + eq) if liab is not None and eq is not None else None,
                              pass_tol=0.001, category="Internal consistency",
                              field="Assets = Liabilities + Equity", source="yfinance balance sheet",
                              period=f"as of {pd.Timestamp(b.columns[0]):%Y-%m-%d}" if not b.empty else None))

    ia, iq = raw.income_annual, raw.income_quarterly
    if not ia.empty and not iq.empty:
        fy_end = pd.Timestamp(ia.columns[0])
        qcols = [c for c in iq.columns if fy_end - pd.Timedelta(days=370) < pd.Timestamp(c) <= fy_end + pd.Timedelta(days=7)]
        if len(qcols) == 4 and "Total Revenue" in iq.index and iq.loc["Total Revenue", qcols].notna().all():
            out.append(compare_values(float(iq.loc["Total Revenue", qcols].sum()), row(ia, "Total Revenue"),
                                      category="Internal consistency", field="Sum of 4 quarters = annual revenue",
                                      source="yfinance statements", period=f"FY {fy_end:%Y-%m-%d}"))
    return out


# ---------------------------------------------------------------- corrections

def sec_ttm(facts: Optional[dict], key: str, quarter_ends: list[pd.Timestamp]) -> Optional[float]:
    """Trailing-twelve-month sum of 4 filed quarters (fiscal Q4 derived as FY - 9M YTD)."""
    vals = [sec_value(facts, key, q, "quarter")[0] for q in quarter_ends]
    return float(sum(vals)) if len(vals) == 4 and all(v is not None for v in vals) else None


def _fill_ttm_from_sec(m: Metrics, raw: RawData, facts: dict) -> list[str]:
    """yfinance sometimes returns a blank quarter; rebuild TTM from SEC 10-Q/10-K data instead of stale annuals."""
    q = raw.income_quarterly
    if q is None or q.empty or q.shape[1] < 4:
        return []
    from stocksreport.analysis.metrics import quarters_consecutive
    ends = [pd.Timestamp(c) for c in q.columns[:4]]
    if not quarters_consecutive(ends):
        return []
    notes = []
    for key, attr, label in (("revenue", "revenue_ttm", "revenue"), ("net_income", "net_income_ttm", "net income")):
        if m.sources.get(attr) != "annual":
            continue
        v = sec_ttm(facts, key, ends)
        if v is None:
            continue
        old = getattr(m, attr)
        setattr(m, attr, v)
        m.sources[attr] = "SEC"
        notes.append(f"TTM {label} rebuilt from SEC quarterly filings ({ends[-1]:%Y-%m-%d} → {ends[0]:%Y-%m-%d}) "
                     f"because Yahoo's quarterly data has gaps: ${v / 1e9:,.2f}B (was ${old / 1e9:,.2f}B annual)"
                     if old else f"TTM {label} taken from SEC quarterly filings")
    if notes:  # recompute dependent ratios
        if m.revenue_ttm:
            m.price_to_sales = m.market_cap / m.revenue_ttm if m.market_cap else m.price_to_sales
            if m.net_income_ttm is not None:
                m.net_margin = m.net_income_ttm / m.revenue_ttm
        if m.net_income_ttm is not None and m.equity:
            m.roe = m.net_income_ttm / m.equity
    return notes


def apply_sec_corrections(m: Metrics, res: VerificationResult, raw: Optional[RawData] = None,
                          facts: Optional[dict] = None) -> list[str]:
    """Replace yfinance figures that are missing or conflict with SEC filings by the filed values.

    * TTM revenue / net income rebuilt from filed quarters when Yahoo's quarterly data has gaps.
    * Growth rates recomputed from filed annual values when Yahoo's annual figures FAIL verification.
    Returns human-readable notes describing each correction applied to `m` (mutated in place).
    """
    notes: list[str] = _fill_ttm_from_sec(m, raw, facts) if raw is not None and facts else []

    def filed(field: str) -> list[VerificationCheck]:
        rows = [c for c in res.checks if c.category == "SEC filing" and c.field == field
                and (c.period or "").startswith("FY") and c.source_value is not None]
        return sorted(rows, key=lambda c: c.period, reverse=True)[:2]

    for field, attr, label in (("Revenue", "revenue_growth_yoy", "revenue growth"),
                               ("Diluted EPS", "eps_growth_yoy", "EPS growth")):
        rows = filed(field)
        if len(rows) == 2 and any(c.status == "FAIL" for c in rows) and rows[1].source_value > 0:
            new = rows[0].source_value / rows[1].source_value - 1
            old = getattr(m, attr)
            setattr(m, attr, new)
            m.sources[attr] = "SEC"
            notes.append(f"{label} corrected from {old:.1%} (Yahoo) to {new:.1%} using SEC-filed "
                         f"{field.lower()} ({rows[0].period} vs {rows[1].period})" if old is not None else
                         f"{label} set to {new:.1%} from SEC filings")
    for c in res.checks:
        if c.category == "SEC filing" and c.status == "FAIL":
            c.note = (c.note or "") + "; pipeline uses the SEC-filed value for derived metrics"
    return notes


# ---------------------------------------------------------------- entry point

def verify(raw: RawData, m: Metrics, sec_facts: Optional[dict] | str = "fetch",
           nasdaq: Optional[pd.DataFrame] | str = "fetch") -> VerificationResult:
    """Run all checks. Pass pre-loaded sources (tests) or leave as "fetch" to download them."""
    if isinstance(sec_facts, str):
        try:
            sec_facts = sources.sec_companyfacts(raw.ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("SEC fetch failed for %s: %s", raw.ticker, exc)
            sec_facts = None
    if isinstance(nasdaq, str):
        try:
            nasdaq = sources.nasdaq_history(raw.ticker)
        except Exception as exc:  # noqa: BLE001
            log.warning("Nasdaq fetch failed for %s: %s", raw.ticker, exc)
            nasdaq = None
    checks = (_sec_checks(raw, sec_facts) + _price_checks(raw, nasdaq) + derived_checks(raw, m)
              + _consistency_checks(raw))
    return VerificationResult(ticker=raw.ticker, checks=checks)

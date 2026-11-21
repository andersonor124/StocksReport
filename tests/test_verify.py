"""Verification: yfinance values vs SEC filings (XBRL) and Nasdaq prices.

Offline tests run on recorded real responses; `--live` re-runs against live sources.
"""
import copy
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from stocksreport.analysis import metrics as M
from stocksreport.verify import reconcile as R
from stocksreport.verify import sources

FIX = Path(__file__).parent / "fixtures"


def _sources(t):
    with gzip.open(FIX / f"{t}_sec.json.gz", "rt") as f:
        facts = json.load(f)
    nasdaq = pd.read_csv(FIX / f"{t}_nasdaq.csv", index_col=0, parse_dates=True)
    return facts, nasdaq


def _run(bundle, t):
    raw = bundle["raw"]
    facts, nasdaq = _sources(t)
    return R.verify(raw, M.compute(raw), sec_facts=facts, nasdaq=nasdaq)


def _by(res, category, field, period=None):
    return [c for c in res.checks if c.category == category and c.field == field
            and (period is None or c.period == period)]


# ---- status thresholds ----

@pytest.mark.parametrize("a,b,expected", [(100, 100.4, "PASS"), (100, 101.5, "WARN"), (100, 103, "FAIL"),
                                          (None, 100, "SKIP"), (100, None, "SKIP")])
def test_status_thresholds(a, b, expected):
    assert R.compare_values(a, b).status == expected


def test_eps_compared_in_cents():
    assert R.compare_values(8.98, 8.98, absolute=0.011).status == "PASS"
    assert R.compare_values(8.98, 9.02, absolute=0.011).status in ("WARN", "FAIL")


def test_sec_fact_lookup_matches_fiscal_year_end_within_tolerance():
    facts, _ = _sources("AAPL")
    # yfinance labels Apple's FY2026 as 2026-09-30, the 10-K period ends 2026-09-26.
    v, tag = R.sec_value(facts, "revenue", pd.Timestamp("2026-09-30"), duration="annual")
    assert v == 478_834_000_000 and tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_fiscal_q4_derived_from_annual_minus_nine_months():
    facts, _ = _sources("AAPL")
    v, tag = R.sec_value(facts, "revenue", pd.Timestamp("2026-09-30"), duration="quarter")
    assert v == 114_477_000_000 and "FY − 9M YTD" in tag  # matches Apple's reported Sept-quarter revenue
    assert R.sec_value(facts, "eps_diluted", pd.Timestamp("2026-09-30"), duration="quarter") == (None, None)


def test_broad_revenues_tag_gets_definition_tolerance():
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2026-07-01", "end": "2026-09-30", "val": 113.164e9, "form": "10-Q", "filed": "2026-11-01"}]}}}}}
    from stocksreport.data.fetcher import RawData
    iq = pd.DataFrame({pd.Timestamp("2026-09-30"): {"Total Revenue": 110.503e9}})
    raw = RawData(ticker="X", info={}, history=pd.DataFrame(), income_quarterly=iq)
    c = [c for c in R._sec_checks(raw, facts) if c.field == "Revenue"][0]
    assert c.status == "WARN" and "broad tag" in c.note


def test_bank_revenue_uses_net_revenue_tag():
    facts, _ = _sources("JPM")
    v, tag = R.sec_value(facts, "revenue", pd.Timestamp("2026-09-30"), duration="quarter")
    assert tag == "RevenuesNetOfInterestExpense" and v == 50_172_000_000


# ---- the real question: are we retrieving the right numbers? ----

# Known, root-caused discrepancies in Yahoo's data (not retrieval bugs). Each must still be *detected*.
#  JPM FY2024 revenue: Yahoo 169.439B vs 10-K net revenue 177.556B. The $8.1B gap ~= the one-off 2024
#  Visa share-exchange gain, which Yahoo's standardised "Total Revenue" leaves out.
KNOWN_YAHOO_DEVIATIONS = {"AAPL": set(), "JPM": {("Revenue", "FY 2024-12-31")}}


@pytest.mark.parametrize("t", ["AAPL", "JPM"])
def test_fundamentals_match_sec_filings(t, request):
    res = _run(request.getfixturevalue(t.lower()), t)
    sec = [c for c in res.checks if c.source.startswith("SEC")]
    assert len([c for c in sec if c.status != "SKIP"]) >= 8, [c.field for c in sec]
    bad = {(c.field, c.period) for c in sec if c.status == "FAIL"}
    assert bad == KNOWN_YAHOO_DEVIATIONS[t], bad


def test_sec_correction_fixes_growth(jpm):
    from stocksreport.pipeline import build_report
    res = _run(jpm, "JPM")
    rep = build_report(jpm["raw"], jpm["histories"], jpm["peer_infos"], verification=res)
    assert rep.metrics.revenue_growth_yoy == pytest.approx(182_447 / 177_556 - 1, rel=1e-3)
    assert rep.metrics.sources["revenue_growth_yoy"] == "SEC"
    assert rep.data_corrections and "revenue growth" in rep.data_corrections[0]


def test_no_correction_when_data_agrees(aapl):
    from stocksreport.pipeline import build_report
    rep = build_report(aapl["raw"], aapl["histories"], aapl["peer_infos"], verification=_run(aapl, "AAPL"))
    assert rep.data_corrections == []


@pytest.mark.parametrize("t", ["AAPL", "JPM"])
def test_prices_match_nasdaq(t, request):
    res = _run(request.getfixturevalue(t.lower()), t)
    px = [c for c in res.checks if c.category == "Price"]
    assert px and all(c.status == "PASS" for c in px), [(c.field, c.diff_pct, c.note) for c in px]


def test_latest_close_and_ttm_sum_checks_present(aapl):
    res = _run(aapl, "AAPL")
    assert _by(res, "Price", "Latest close")
    assert _by(res, "Internal consistency", "Assets = Liabilities + Equity")


def test_derived_ratios_are_compared_with_yahoo(aapl):
    res = _run(aapl, "AAPL")
    fields = {c.field for c in res.checks if c.category == "Derived ratio"}
    assert {"P/E (TTM)", "Market cap", "Net margin", "Dividend yield"} <= fields


def test_detects_a_corrupted_value(aapl):
    raw = copy.deepcopy(aapl["raw"])
    col = raw.income_annual.columns[0]
    raw.income_annual.loc["Total Revenue", col] *= 1.10  # simulate a bad data feed
    facts, nasdaq = _sources("AAPL")
    res = R.verify(raw, M.compute(raw), sec_facts=facts, nasdaq=nasdaq)
    rev = [c for c in res.checks if c.field == "Revenue" and c.status == "FAIL"]
    assert rev, "a 10% revenue error must be flagged"


def test_detects_a_bad_price(aapl):
    raw = copy.deepcopy(aapl["raw"])
    raw.history.iloc[-1, raw.history.columns.get_loc("Close")] *= 1.05
    facts, nasdaq = _sources("AAPL")
    res = R.verify(raw, M.compute(raw), sec_facts=facts, nasdaq=nasdaq)
    assert _by(res, "Price", "Latest close")[0].status == "FAIL"


def test_missing_sources_produce_skips_not_errors(aapl):
    res = R.verify(aapl["raw"], M.compute(aapl["raw"]), sec_facts=None, nasdaq=pd.DataFrame())
    assert any(c.status == "SKIP" for c in res.checks)
    assert all(c.status != "FAIL" for c in res.checks if c.category in ("SEC filing", "Price"))


def test_nasdaq_row_parsing():
    rows = [{"date": "11/20/2026", "close": "$342.56", "volume": "80,692,550", "open": "$352.865",
             "high": "$354.34", "low": "$340.56"}]
    df = sources.parse_nasdaq_rows(rows)
    assert df.loc["2026-11-20", "Close"] == 342.56 and df.loc["2026-11-20", "Volume"] == 80_692_550


# ---- live: same checks against today's data for a cross-sector basket ----

@pytest.mark.live
@pytest.mark.parametrize("t", ["AAPL", "MSFT", "JPM", "XOM", "JNJ", "AMZN"])
def test_live_basket(t):
    from stocksreport.data import fetcher
    raw = fetcher.fetch(t, use_cache=False)
    res = R.verify(raw, M.compute(raw))
    fails = {(c.field, c.period) for c in res.checks if c.status == "FAIL" and c.category in ("SEC filing", "Price")}
    unexplained = fails - KNOWN_YAHOO_DEVIATIONS.get(t, set())
    assert not unexplained, [(c.field, c.period, c.pipeline_value, c.source_value, c.diff_pct, c.note)
                             for c in res.checks if (c.field, c.period) in unexplained]


def test_ttm_gap_in_yahoo_is_filled_from_sec_quarters(aapl):
    # Reproduces the live AMZN case: Yahoo returns an all-NaN quarter, so TTM falls back to stale annual data.
    from stocksreport.pipeline import build_report
    raw = copy.deepcopy(aapl["raw"])
    raw.income_quarterly.iloc[:, 1] = float("nan")
    m = M.compute(raw)
    assert m.sources["revenue_ttm"] == "annual"
    facts, nasdaq = _sources("AAPL")
    res = R.verify(raw, m, sec_facts=facts, nasdaq=nasdaq)
    rep = build_report(raw, aapl["histories"], aapl["peer_infos"], verification=res, m=m, sec_facts=facts)
    assert rep.metrics.revenue_ttm == pytest.approx(478_834e6)
    assert rep.metrics.net_income_ttm == pytest.approx(132_175e6)
    assert rep.metrics.sources["revenue_ttm"] == "SEC"
    assert rep.metrics.net_margin == pytest.approx(132_175 / 478_834)
    assert rep.metrics.roe == pytest.approx(132_175e6 / rep.metrics.equity)
    assert any("TTM" in n for n in rep.data_corrections)
    margin = next(c for c in rep.verification.checks if c.field == "Net margin")
    assert margin.status == "PASS"  # derived checks re-run on corrected values

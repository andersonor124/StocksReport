import copy

import numpy as np
import pandas as pd
import pytest

from stocksreport.analysis import metrics as M


def test_price_is_last_close(aapl):
    m = M.compute(aapl["raw"])
    assert m.price == pytest.approx(aapl["raw"].history["Close"].iloc[-1])


def test_revenue_ttm_is_sum_of_last_four_quarters(aapl):
    m = M.compute(aapl["raw"])
    expected = 114_477e6 + 109_417e6 + 111_184e6 + 143_756e6
    assert m.revenue_ttm == pytest.approx(expected)
    assert m.sources["revenue_ttm"] == "computed"


def test_eps_ttm_fills_missing_quarter_and_matches_yahoo(aapl):
    # Latest AAPL quarter has NaN diluted EPS in yfinance; we must back-fill it from NI / diluted shares.
    m = M.compute(aapl["raw"])
    assert m.eps_ttm == pytest.approx(aapl["raw"].info["trailingEps"], rel=0.02)


def test_market_cap_consistent_with_price_times_shares(aapl):
    m = M.compute(aapl["raw"])
    assert m.market_cap == pytest.approx(m.price * m.shares_outstanding, rel=1e-9)
    assert m.market_cap == pytest.approx(aapl["raw"].info["marketCap"], rel=0.01)


def test_pe_is_price_over_eps(aapl):
    m = M.compute(aapl["raw"])
    assert m.pe_ttm == pytest.approx(m.price / m.eps_ttm)


def test_dividend_yield_is_fraction_from_paid_dividends(aapl):
    # yfinance `dividendYield` is a percent (0.32 == 0.32%). Ours must be a fraction.
    m = M.compute(aapl["raw"])
    assert 0 < m.dividend_yield < 0.02
    assert m.dividend_yield == pytest.approx(aapl["raw"].info["dividendYield"] / 100, rel=0.25)


def test_margins_are_ratios_of_ttm_values(aapl):
    m = M.compute(aapl["raw"])
    assert m.net_margin == pytest.approx(m.net_income_ttm / m.revenue_ttm)
    assert 0.2 < m.gross_margin < 0.6


def test_fcf_is_ocf_minus_capex(aapl):
    m = M.compute(aapl["raw"])
    q = aapl["raw"].cashflow_quarterly
    expected = sum(q.loc["Operating Cash Flow"].iloc[:4]) + sum(q.loc["Capital Expenditure"].iloc[:4])
    assert m.fcf_ttm == pytest.approx(expected)
    assert m.fcf_yield == pytest.approx(m.fcf_ttm / m.market_cap)


def test_bank_has_no_debt_to_equity_or_fcf_yield(jpm):
    m = M.compute(jpm["raw"])
    assert m.debt_to_equity is None
    assert m.fcf_yield is None
    assert m.net_margin == pytest.approx(m.net_income_ttm / m.revenue_ttm)


def test_non_consecutive_quarters_fall_back_to_annual(aapl):
    raw = copy.deepcopy(aapl["raw"])
    q = raw.income_quarterly
    raw.income_quarterly = q.drop(columns=q.columns[1])  # create a gap
    m = M.compute(raw)
    assert m.revenue_ttm == pytest.approx(raw.income_annual.loc["Total Revenue"].iloc[0])
    assert m.sources["revenue_ttm"] == "annual"


def test_risk_metrics(aapl):
    m = M.compute(aapl["raw"])
    assert 0.05 < m.volatility_1y < 1.5
    assert -1 < m.max_drawdown_1y <= 0
    assert m.pct_from_52w_high <= 0
    assert isinstance(m.above_200dma, bool)


def test_quarters_consecutive_helper():
    cols = pd.to_datetime(["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"])
    assert M.quarters_consecutive(cols)
    assert not M.quarters_consecutive(pd.to_datetime(["2026-09-30", "2026-03-31", "2025-12-31", "2025-09-30"]))


def test_max_drawdown_known_series():
    s = pd.Series([100, 120, 60, 90, 130.0])
    assert M.max_drawdown(s) == pytest.approx(-0.5)


def test_annualised_volatility_constant_returns_is_zero():
    s = pd.Series(100 * np.cumprod(np.full(300, 1.001)))
    assert M.annualised_volatility(s) == pytest.approx(0, abs=1e-9)

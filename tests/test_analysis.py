from datetime import date

import pandas as pd
import pytest

from stocksreport.analysis import benchmark as B
from stocksreport.analysis import metrics as M
from stocksreport.analysis import narrative as N
from stocksreport.analysis import scoring as S
from stocksreport.analysis import sentiment as SE
from stocksreport.models import BenchmarkComparison, Metrics, PeerRow, PeriodReturn

# ---------- benchmark ----------

def _bench(bundle):
    raw = bundle["raw"]
    m = M.compute(raw)
    return raw, m, B.compare(raw, m, bundle["histories"], bundle["peer_infos"])


def test_period_return_uses_adjusted_close(aapl):
    raw, _, b = _bench(aapl)
    adj = raw.history["Adj Close"]
    one_year = next(r for r in b.returns if r.period == "1Y")
    assert one_year.stock == pytest.approx(adj.iloc[-1] / adj.iloc[-1 - 252] - 1)
    spy = aapl["histories"]["SPY"]["Adj Close"]
    assert one_year.market == pytest.approx(spy.iloc[-1] / spy.iloc[-1 - 252] - 1)


def test_sector_etf_and_peers(aapl, jpm):
    _, _, b = _bench(aapl)
    assert b.market_ticker == "SPY" and b.sector_ticker == "XLK"
    assert {p.ticker for p in b.peers} == {"MSFT", "NVDA", "ORCL"}
    assert "AAPL" not in {p.ticker for p in b.peers}
    _, _, bj = _bench(jpm)
    assert bj.sector_ticker == "XLF"


def test_peer_median():
    peers = [PeerRow(ticker="A", pe_ttm=10), PeerRow(ticker="B", pe_ttm=20), PeerRow(ticker="C", pe_ttm=None),
             PeerRow(ticker="D", pe_ttm=40)]
    assert B.median_row(peers).pe_ttm == 20


def test_negative_pe_excluded_from_peer_median():
    peers = [PeerRow(ticker="A", pe_ttm=-5), PeerRow(ticker="B", pe_ttm=20), PeerRow(ticker="C", pe_ttm=30)]
    assert B.median_row(peers).pe_ttm == 25


# ---------- scoring ----------

def test_linear_scale_clamps():
    assert S.scale(5, 0, 10) == 50
    assert S.scale(-1, 0, 10) == 0
    assert S.scale(99, 0, 10) == 100
    assert S.scale(5, 10, 0) == 50  # inverted (lower is better)
    assert S.scale(None, 0, 10) is None


def _bench_stub(market_1y=0.10, stock_1y=0.20, peer_fpe=20.0, peer_margin=0.10):
    return BenchmarkComparison(
        market_ticker="SPY", sector_ticker="XLK",
        returns=[PeriodReturn(period="1Y", stock=stock_1y, market=market_1y, sector=0.1)],
        peer_median=PeerRow(ticker="Peer median", forward_pe=peer_fpe, pe_ttm=peer_fpe, net_margin=peer_margin,
                            roe=0.15, revenue_growth_yoy=0.05),
    )


def test_strong_company_scores_buy():
    m = Metrics(price=100, forward_pe=12, pe_ttm=14, peg=0.8, fcf_yield=0.07, revenue_growth_yoy=0.25,
                eps_growth_yoy=0.30, net_margin=0.30, roe=0.30, debt_to_equity=0.2, above_200dma=True,
                forward_eps=8.3)
    sc = S.score(m, _bench_stub(), {"recommendationMean": 1.6}, {"mean": 140, "low": 110, "high": 170}, "Technology")
    assert sc.verdict == "Buy" and sc.total >= 65
    assert sc.fair_value.upside_pct > 0


def test_weak_company_scores_sell():
    m = Metrics(price=100, forward_pe=60, pe_ttm=80, peg=4, fcf_yield=-0.02, revenue_growth_yoy=-0.10,
                eps_growth_yoy=-0.3, net_margin=-0.05, roe=-0.05, debt_to_equity=3.0, above_200dma=False,
                forward_eps=1.6)
    sc = S.score(m, _bench_stub(stock_1y=-0.3), {"recommendationMean": 3.8}, {"mean": 80, "low": 60, "high": 95},
                 "Technology")
    assert sc.verdict == "Sell" and sc.total < 45


def test_missing_pillars_are_excluded_and_weights_renormalised():
    m = Metrics(price=100, revenue_growth_yoy=0.25, eps_growth_yoy=0.30)
    sc = S.score(m, BenchmarkComparison(market_ticker="SPY"), {}, {}, None)
    scored = [p for p in sc.pillars if p.score is not None]
    assert [p.name for p in scored] == ["Growth"]
    assert sc.total == pytest.approx(scored[0].score)


def test_financial_health_skips_debt_for_banks():
    m = Metrics(price=100, debt_to_equity=None, roe=0.15)
    sc = S.score(m, _bench_stub(), {}, {}, "Financial Services")
    fh = next(p for p in sc.pillars if p.name == "Financial Health")
    assert any("not meaningful" in n for n in fh.notes)


def test_real_fixture_scores_are_in_range(aapl, jpm):
    for b in (aapl, jpm):
        raw, m, bench = _bench(b)
        sc = S.score(m, bench, raw.info, raw.price_targets, raw.info.get("sector"))
        assert 0 <= sc.total <= 100
        assert sc.verdict in ("Buy", "Hold", "Sell")
        assert sc.fair_value.analyst_mean == pytest.approx(raw.price_targets["mean"])


# ---------- sentiment ----------

def test_finance_lexicon_polarity():
    assert SE.headline_score("Apple beats estimates and raises guidance") > 0.3
    assert SE.headline_score("Company misses estimates, cuts guidance after downgrade") < -0.3


def test_sentiment_from_fixture(aapl):
    s = SE.analyze(aapl["raw"], as_of=date(2026, 11, 21))
    rec = aapl["raw"].recommendations.iloc[0]
    assert s.analyst_counts["Buy"] == int(rec["buy"])
    assert s.analyst_counts["Strong Buy"] == int(rec["strongBuy"])
    assert s.upgrades_90d + s.downgrades_90d <= len(aapl["raw"].upgrades_downgrades)
    assert len(s.headlines) > 0 and all(-1 <= h["score"] <= 1 for h in s.headlines)
    assert s.news_label in ("Positive", "Neutral", "Negative")


def test_upgrade_counting_window():
    ud = pd.DataFrame({"Firm": ["A", "B", "C"], "ToGrade": ["Buy", "Hold", "Buy"], "FromGrade": ["Hold", "Buy", "Hold"],
                       "Action": ["up", "down", "up"]},
                      index=pd.to_datetime(["2026-11-01", "2026-10-01", "2026-01-01"]))
    up, down, _ = SE.rating_actions(ud, as_of=date(2026, 11, 21))
    assert (up, down) == (1, 1)


# ---------- narrative ----------

def test_narrative_is_consistent_with_score(aapl, jpm):
    for b in (aapl, jpm):
        raw, m, bench = _bench(b)
        sc = S.score(m, bench, raw.info, raw.price_targets, raw.info.get("sector"))
        sent = SE.analyze(raw, as_of=date(2026, 11, 21))
        a = N.build(raw.ticker, raw.info.get("shortName", raw.ticker), m, bench, sc, sent)
        assert a.verdict == sc.verdict
        assert a.pros and a.cons
        assert all(p.evidence for p in a.pros + a.cons)
        assert raw.ticker in a.summary
        assert "position" in a.portfolio_manager_view.lower()


def test_fair_value_blend_weights_analyst_two_thirds():
    from stocksreport.models import PeerRow
    b = _bench_stub(peer_fpe=10.0)
    b.peers = [PeerRow(ticker=x, forward_pe=10.0) for x in "ABC"]
    m = Metrics(price=100, forward_eps=10.0)
    fv = S.score(m, b, {}, {"mean": 150}, "Technology").fair_value
    assert fv.peer_multiple_value == pytest.approx(100)
    assert fv.blended == pytest.approx(150 * 2 / 3 + 100 / 3)


def test_fair_value_ignores_peer_multiple_with_too_few_peers():
    b = _bench_stub(peer_fpe=10.0)
    b.peers = [PeerRow(ticker="A", forward_pe=10.0)]
    fv = S.score(Metrics(price=100, forward_eps=10.0), b, {}, {"mean": 150}, "Technology").fair_value
    assert fv.peer_multiple_value is None and fv.blended == 150

"""Deterministic 0-100 scoring across six pillars, plus a fair-value estimate.

Each sub-metric is mapped linearly onto 0-100 between a "bad" and "good" anchor
(clamped). A pillar is the mean of its available sub-scores; pillars with no data
are dropped and the remaining weights are renormalised.
"""
from __future__ import annotations

import statistics
from typing import Optional

from stocksreport import config
from stocksreport.models import BenchmarkComparison, FairValue, Metrics, PillarScore, RuleScore


def scale(x: Optional[float], bad: float, good: float) -> Optional[float]:
    if x is None:
        return None
    t = (x - bad) / (good - bad)
    return round(100 * min(1.0, max(0.0, t)), 1)


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x: Optional[float], d: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


def _pillar(name: str, parts: list[tuple[Optional[float], str]]) -> PillarScore:
    scores = [s for s, _ in parts if s is not None]
    notes = [n for s, n in parts if s is not None or n.endswith("not meaningful")]
    return PillarScore(name=name, score=round(statistics.mean(scores), 1) if scores else None,
                       weight=config.PILLAR_WEIGHTS[name], notes=notes)


def _ret(bench: BenchmarkComparison, period: str):
    return next((r for r in bench.returns if r.period == period), None)


def score(m: Metrics, bench: BenchmarkComparison, info: dict, targets: dict, sector: Optional[str]) -> RuleScore:
    pm = bench.peer_median
    pillars: list[PillarScore] = []

    # Valuation: cheaper than peers (relative forward P/E), PEG, FCF yield.
    rel_pe = m.forward_pe / pm.forward_pe if m.forward_pe and pm.forward_pe else None
    pillars.append(_pillar("Valuation", [
        (scale(rel_pe, 1.6, 0.6), f"Forward P/E {_num(m.forward_pe)} vs peer median {_num(pm.forward_pe)}"),
        (scale(m.peg, 3.0, 0.8), f"PEG {_num(m.peg, 2)}"),
        (scale(m.fcf_yield, -0.01, 0.06), f"FCF yield {_pct(m.fcf_yield)}"),
    ]))

    pillars.append(_pillar("Growth", [
        (scale(m.revenue_growth_yoy, -0.05, 0.20), f"Revenue growth (last FY) {_pct(m.revenue_growth_yoy)}"),
        (scale(m.eps_growth_yoy, -0.10, 0.25), f"EPS growth (last FY) {_pct(m.eps_growth_yoy)}"),
    ]))

    rel_margin = m.net_margin - pm.net_margin if m.net_margin is not None and pm.net_margin is not None else None
    pillars.append(_pillar("Profitability", [
        (scale(m.net_margin, 0.0, 0.25), f"Net margin {_pct(m.net_margin)}"),
        (scale(rel_margin, -0.10, 0.10), f"Net margin vs peer median {_pct(pm.net_margin)}"),
        (scale(m.roe, 0.0, 0.25), f"Return on equity {_pct(m.roe)}"),
    ]))

    if sector in config.DEBT_EXEMPT_SECTORS:
        fh_parts = [(None, "Debt/equity for banks and insurers is not meaningful"),
                    (scale(m.roe, 0.05, 0.18), f"ROE as capital-strength proxy {_pct(m.roe)}")]
    else:
        fh_parts = [(scale(m.debt_to_equity, 2.0, 0.3), f"Debt/equity {_num(m.debt_to_equity, 2)}"),
                    (None if m.fcf_ttm is None else (100.0 if m.fcf_ttm > 0 else 0.0),
                     f"Free cash flow {'positive' if (m.fcf_ttm or 0) > 0 else 'negative'}")]
    pillars.append(_pillar("Financial Health", fh_parts))

    r1y = _ret(bench, "1Y")
    rel_1y = r1y.stock - r1y.market if r1y and r1y.stock is not None and r1y.market is not None else None
    pillars.append(_pillar("Momentum", [
        (scale(rel_1y, -0.25, 0.25), f"1Y return vs S&P 500: {_pct(rel_1y)}"),
        (None if m.above_200dma is None else (75.0 if m.above_200dma else 25.0),
         f"Price {'above' if m.above_200dma else 'below'} 200-day average"),
    ]))

    mean_t = targets.get("mean") if targets else None
    upside = (mean_t / m.price - 1) if mean_t and m.price else None
    rec_mean = info.get("recommendationMean")
    pillars.append(_pillar("Analyst Consensus", [
        (scale(upside, -0.10, 0.25), f"Upside to mean target {_pct(upside)}"),
        (scale(rec_mean, 3.5, 1.5), f"Average rating {_num(rec_mean, 2)} (1=Strong Buy, 5=Sell)"),
    ]))

    scored = [p for p in pillars if p.score is not None]
    wsum = sum(p.weight for p in scored)
    total = round(sum(p.score * p.weight for p in scored) / wsum, 1) if wsum else 50.0
    verdict = "Buy" if total >= config.BUY_THRESHOLD else "Sell" if total < config.SELL_THRESHOLD else "Hold"

    # Fair value: analyst mean target blended with peer-median forward P/E x forward EPS.
    # Peer multiple is a cross-check only: needs >= 3 peers with a valid forward P/E, and gets 1/3 weight
    # (a company can structurally deserve a premium/discount, analyst targets already reflect that).
    n_valid = sum(1 for p in bench.peers if p.forward_pe and p.forward_pe > 0)
    peer_val = (pm.forward_pe * m.forward_eps
                if n_valid >= 3 and pm.forward_pe and m.forward_eps and m.forward_eps > 0 else None)
    if mean_t and peer_val:
        blended = mean_t * 2 / 3 + peer_val / 3
    else:
        blended = mean_t or peer_val
    fv = FairValue(
        analyst_low=targets.get("low") if targets else None,
        analyst_mean=mean_t,
        analyst_high=targets.get("high") if targets else None,
        peer_multiple_value=peer_val,
        blended=blended,
        upside_pct=(blended / m.price - 1) if blended and m.price else None,
    )
    return RuleScore(pillars=pillars, total=total, verdict=verdict, fair_value=fv)

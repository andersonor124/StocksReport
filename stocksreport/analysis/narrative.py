"""Template-based narrative: pros/cons, investor & portfolio-manager views, verdict.

Every statement is generated from a rule with the metric that triggered it as
evidence, so nothing is invented and the text is reproducible.
"""
from __future__ import annotations

from typing import Optional

from stocksreport import config
from stocksreport.models import (Analysis, BenchmarkComparison, Metrics, Point, RuleScore,
                                 SentimentSummary)


def _p(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _x(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.1f}x"


def _money(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"${x / div:,.2f}{unit}"
    return f"${x:,.2f}"


def _pros_cons(m: Metrics, b: BenchmarkComparison, sc: RuleScore, s: SentimentSummary,
               sector: Optional[str]) -> tuple[list[Point], list[Point]]:
    pros, cons = [], []
    pm = b.peer_median
    add = lambda lst, text, ev: lst.append(Point(text=text, evidence=ev))  # noqa: E731

    # Valuation
    if m.forward_pe and pm.forward_pe:
        rel = m.forward_pe / pm.forward_pe
        ev = f"Forward P/E {_x(m.forward_pe)} vs peer median {_x(pm.forward_pe)}"
        if rel <= 0.85:
            add(pros, "Trades at a discount to sector peers on forward earnings", ev)
        elif rel >= 1.25:
            add(cons, "Valuation premium to peers leaves less margin of safety", ev)
    if m.fcf_yield is not None:
        if m.fcf_yield >= 0.04:
            add(pros, "Attractive free-cash-flow yield", f"FCF yield {_p(m.fcf_yield)} (FCF TTM {_money(m.fcf_ttm)})")
        elif m.fcf_yield < 0.015:
            add(cons, "Low free-cash-flow yield at the current price", f"FCF yield {_p(m.fcf_yield)}")

    # Growth
    if m.revenue_growth_yoy is not None:
        ev = f"Revenue growth {_p(m.revenue_growth_yoy)} last fiscal year"
        if m.revenue_growth_yoy >= 0.08:
            add(pros, "Solid top-line growth", ev)
        elif m.revenue_growth_yoy < 0.02:
            add(cons, "Revenue growth is slow or shrinking", ev)
    if m.eps_growth_yoy is not None:
        ev = f"Diluted EPS growth {_p(m.eps_growth_yoy)} last fiscal year"
        if m.eps_growth_yoy >= 0.10:
            add(pros, "Earnings per share growing at a healthy rate", ev)
        elif m.eps_growth_yoy < 0:
            add(cons, "Earnings per share declined", ev)

    # Profitability
    if m.net_margin is not None:
        ev = f"Net margin {_p(m.net_margin)} vs peer median {_p(pm.net_margin)}"
        if pm.net_margin is not None and m.net_margin >= pm.net_margin + 0.03:
            add(pros, "Higher profitability than peers", ev)
        elif pm.net_margin is not None and m.net_margin <= pm.net_margin - 0.03:
            add(cons, "Thinner margins than peers", ev)
    if m.roe is not None:
        if m.roe >= 0.20:
            add(pros, "High return on shareholders' equity", f"ROE {_p(m.roe)}")
        elif m.roe < 0.08:
            add(cons, "Low return on equity", f"ROE {_p(m.roe)}")

    # Balance sheet
    if sector not in config.DEBT_EXEMPT_SECTORS and m.debt_to_equity is not None:
        if m.debt_to_equity <= 0.5:
            add(pros, "Conservative balance sheet", f"Debt/equity {m.debt_to_equity:.2f}")
        elif m.debt_to_equity >= 1.5:
            add(cons, "Elevated leverage", f"Debt/equity {m.debt_to_equity:.2f}")
    if m.dividend_yield and m.dividend_yield >= 0.02:
        add(pros, "Meaningful dividend income", f"Trailing dividend yield {_p(m.dividend_yield)}")

    # Momentum / risk
    r1 = next((r for r in b.returns if r.period == "1Y"), None)
    if r1 and r1.stock is not None and r1.market is not None:
        ev = f"1Y total return {_p(r1.stock)} vs S&P 500 {_p(r1.market)}"
        if r1.stock - r1.market >= 0.05:
            add(pros, "Outperformed the S&P 500 over the past year", ev)
        elif r1.stock - r1.market <= -0.05:
            add(cons, "Lagged the S&P 500 over the past year", ev)
    if m.volatility_1y is not None and m.volatility_1y >= 0.40:
        add(cons, "High share-price volatility", f"Annualised volatility {_p(m.volatility_1y)}")

    # Street view
    fv = sc.fair_value
    if fv.analyst_mean and m.price:
        up = fv.analyst_mean / m.price - 1
        ev = f"Mean analyst target ${fv.analyst_mean:,.2f} vs price ${m.price:,.2f} ({_p(up)})"
        if up >= 0.10:
            add(pros, "Analysts see meaningful upside", ev)
        elif up <= -0.02:
            add(cons, "Price is above the average analyst target", ev)
    if s.downgrades_90d > s.upgrades_90d + 1:
        add(cons, "More analyst downgrades than upgrades recently",
            f"{s.downgrades_90d} downgrades vs {s.upgrades_90d} upgrades in 90 days")
    elif s.upgrades_90d > s.downgrades_90d + 1:
        add(pros, "Analyst upgrades outnumber downgrades",
            f"{s.upgrades_90d} upgrades vs {s.downgrades_90d} downgrades in 90 days")

    if not pros:
        add(pros, "No standout strengths on the screened metrics", f"Composite score {sc.total:.0f}/100")
    if not cons:
        add(cons, "No major red flags on the screened metrics; main risk is market/valuation risk",
            f"Composite score {sc.total:.0f}/100")
    return pros, cons


def _retail_view(s: SentimentSummary, sc: RuleScore, m: Metrics) -> str:
    parts = []
    if s.analyst_counts:
        tot = sum(s.analyst_counts.values())
        bull = s.analyst_counts.get("Strong Buy", 0) + s.analyst_counts.get("Buy", 0)
        bear = s.analyst_counts.get("Sell", 0) + s.analyst_counts.get("Strong Sell", 0)
        parts.append(f"Of {tot} analysts covering the stock, {bull} rate it Buy or better, "
                     f"{s.analyst_counts.get('Hold', 0)} Hold and {bear} Sell"
                     + (f"; the mix has been {s.analyst_trend} over the last 3 months." if s.analyst_trend else "."))
    if s.upgrades_90d or s.downgrades_90d:
        parts.append(f"In the past 90 days there were {s.upgrades_90d} upgrade(s) and {s.downgrades_90d} downgrade(s).")
    if s.news_label:
        parts.append(f"Recent news flow reads {s.news_label.lower()} (average headline sentiment "
                     f"{s.news_score:+.2f} on a -1 to +1 scale across {len(s.headlines)} headlines).")
    fv = sc.fair_value
    if fv.analyst_low and fv.analyst_high and m.price:
        parts.append(f"Street price targets range from ${fv.analyst_low:,.0f} to ${fv.analyst_high:,.0f}, "
                     f"against a current price of ${m.price:,.2f}.")
    return " ".join(parts) or "Limited analyst and news coverage is available for this stock."


def _risk_bucket(m: Metrics) -> str:
    vol = m.volatility_1y or 0.3
    beta = m.beta or 1.0
    if vol >= 0.45 or beta >= 1.6:
        return "high"
    if vol <= 0.22 and beta <= 0.9:
        return "low"
    return "moderate"


def _pm_view(m: Metrics, sc: RuleScore, b: BenchmarkComparison) -> str:
    risk = _risk_bucket(m)
    size = {"low": "3-5%", "moderate": "2-4%", "high": "1-2%"}[risk]
    if sc.verdict == "Sell":
        size = "0% (avoid or underweight versus the benchmark)"
    best = max((p for p in sc.pillars if p.score is not None), key=lambda p: p.score, default=None)
    worst = min((p for p in sc.pillars if p.score is not None), key=lambda p: p.score, default=None)
    horizon = "3-5 years" if sc.verdict == "Buy" else "12-18 months, re-assess on earnings"
    txt = (f"Risk profile is {risk} (beta {m.beta if m.beta is not None else 'n/a'}, 1Y volatility "
           f"{_p(m.volatility_1y)}, max 1Y drawdown {_p(m.max_drawdown_1y)}). Suggested position size within a "
           f"diversified portfolio: {size}. Suggested horizon: {horizon}.")
    if best and worst and best is not worst:
        txt += (f" Strongest pillar: {best.name} ({best.score:.0f}/100); weakest: {worst.name} "
                f"({worst.score:.0f}/100).")
    if b.sector_ticker:
        txt += f" Benchmark against {b.market_ticker} and the {b.sector_ticker} sector ETF."
    return txt


def build(ticker: str, name: str, m: Metrics, b: BenchmarkComparison, sc: RuleScore,
          s: SentimentSummary, sector: Optional[str] = None) -> Analysis:
    pros, cons = _pros_cons(m, b, sc, s, sector)
    fv = sc.fair_value

    risks = [c.text for c in cons][:4]
    if m.beta and m.beta > 1.2:
        risks.append(f"Higher sensitivity to market swings (beta {m.beta:.2f})")
    catalysts = ["Upcoming quarterly earnings and guidance"]
    if s.upgrades_90d > s.downgrades_90d:
        catalysts.append("Positive analyst revision momentum")
    if fv.upside_pct and fv.upside_pct > 0.1:
        catalysts.append("Re-rating toward fair value estimate")

    spread = (sc.total - config.BUY_THRESHOLD if sc.verdict == "Buy" else
              config.SELL_THRESHOLD - sc.total if sc.verdict == "Sell" else
              min(config.BUY_THRESHOLD - sc.total, sc.total - config.SELL_THRESHOLD))
    spread = abs(spread)
    coverage = sum(1 for p in sc.pillars if p.score is not None) / len(sc.pillars)
    confidence = "High" if spread >= 10 and coverage > 0.8 else "Medium" if spread >= 4 or coverage > 0.8 else "Low"

    entry = None
    if fv.blended and m.price:
        mos = fv.blended * 0.90  # 10% margin of safety
        entry = (f"Fair value ≈ ${fv.blended:,.2f} ({_p(fv.upside_pct)} vs current ${m.price:,.2f}). "
                 f"A more attractive entry with a 10% margin of safety would be ≤ ${mos:,.2f}.")

    summary = (f"{name} ({ticker}) scores {sc.total:.0f}/100 on our six-pillar model, which maps to a "
               f"**{sc.verdict}** at ${m.price:,.2f}. "
               f"Market cap {_money(m.market_cap)}; P/E {_x(m.pe_ttm)} trailing, {_x(m.forward_pe)} forward.")
    rationale = "; ".join(f"{p.name} {p.score:.0f}" for p in sc.pillars if p.score is not None)
    rationale = (f"Pillar scores — {rationale}. Thresholds: Buy ≥ {config.BUY_THRESHOLD}, "
                 f"Sell < {config.SELL_THRESHOLD}.")

    return Analysis(summary=summary, pros=pros, cons=cons,
                    retail_investor_view=_retail_view(s, sc, m),
                    portfolio_manager_view=_pm_view(m, sc, b),
                    key_risks=risks, catalysts=catalysts, verdict=sc.verdict, confidence=confidence,
                    entry_price_suggestion=entry, rationale=rationale)

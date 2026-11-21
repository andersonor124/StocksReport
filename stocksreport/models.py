"""Typed data structures shared across the pipeline."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["Buy", "Hold", "Sell"]


class CompanyProfile(BaseModel):
    ticker: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    employees: Optional[int] = None
    summary: Optional[str] = None
    currency: str = "USD"
    exchange: Optional[str] = None


class Metrics(BaseModel):
    """Canonical metrics. Values we can recompute from statements are recomputed."""
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    revenue_ttm: Optional[float] = None
    net_income_ttm: Optional[float] = None
    equity: Optional[float] = None
    eps_ttm: Optional[float] = None
    forward_eps: Optional[float] = None
    pe_ttm: Optional[float] = None
    forward_pe: Optional[float] = None
    peg: Optional[float] = None
    price_to_sales: Optional[float] = None
    price_to_book: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    fcf_ttm: Optional[float] = None
    fcf_yield: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    volatility_1y: Optional[float] = None
    max_drawdown_1y: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    above_200dma: Optional[bool] = None
    sources: dict[str, str] = Field(default_factory=dict)  # metric -> "computed"|"yfinance"


class PeriodReturn(BaseModel):
    period: str
    stock: Optional[float] = None
    market: Optional[float] = None
    sector: Optional[float] = None


class PeerRow(BaseModel):
    ticker: str
    name: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ttm: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_sales: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None


class BenchmarkComparison(BaseModel):
    market_ticker: str
    sector_ticker: Optional[str] = None
    returns: list[PeriodReturn] = Field(default_factory=list)
    peers: list[PeerRow] = Field(default_factory=list)
    peer_median: PeerRow = Field(default_factory=lambda: PeerRow(ticker="Peer median"))


class PillarScore(BaseModel):
    name: str
    score: Optional[float] = None  # 0-100, None if no data
    weight: float
    notes: list[str] = Field(default_factory=list)


class FairValue(BaseModel):
    analyst_low: Optional[float] = None
    analyst_mean: Optional[float] = None
    analyst_high: Optional[float] = None
    peer_multiple_value: Optional[float] = None
    blended: Optional[float] = None
    upside_pct: Optional[float] = None


class RuleScore(BaseModel):
    pillars: list[PillarScore]
    total: float
    verdict: Verdict
    fair_value: FairValue


class Point(BaseModel):
    text: str
    evidence: str


class SentimentSummary(BaseModel):
    analyst_counts: dict[str, int] = Field(default_factory=dict)
    analyst_trend: Optional[str] = None
    recommendation_key: Optional[str] = None
    num_analysts: Optional[int] = None
    upgrades_90d: int = 0
    downgrades_90d: int = 0
    recent_actions: list[str] = Field(default_factory=list)
    news_score: Optional[float] = None  # mean VADER compound, -1..1
    news_label: Optional[str] = None
    headlines: list[dict] = Field(default_factory=list)  # {title, publisher, date, score, url}


class Analysis(BaseModel):
    summary: str
    pros: list[Point]
    cons: list[Point]
    retail_investor_view: str
    portfolio_manager_view: str
    key_risks: list[str]
    catalysts: list[str]
    verdict: Verdict
    confidence: Literal["Low", "Medium", "High"]
    entry_price_suggestion: Optional[str] = None
    rationale: str


class VerificationCheck(BaseModel):
    category: str
    field: str
    period: Optional[str] = None
    pipeline_value: Optional[float] = None
    source_value: Optional[float] = None
    source: str
    diff_pct: Optional[float] = None  # percent units: 4.15 means +4.15%
    status: Literal["PASS", "WARN", "FAIL", "SKIP"]
    note: Optional[str] = None


class VerificationResult(BaseModel):
    ticker: str
    checks: list[VerificationCheck]

    @property
    def counts(self) -> dict[str, int]:
        out = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for c in self.checks:
            out[c.status] += 1
        return out

    @property
    def pass_rate(self) -> Optional[float]:
        c = self.counts
        evaluated = c["PASS"] + c["WARN"] + c["FAIL"]
        return c["PASS"] / evaluated if evaluated else None


class StockReport(BaseModel):
    as_of: date
    profile: CompanyProfile
    metrics: Metrics
    benchmark: BenchmarkComparison
    score: RuleScore
    sentiment: SentimentSummary
    analysis: Analysis
    verification: Optional[VerificationResult] = None
    data_corrections: list[str] = Field(default_factory=list)  # SEC overrides applied to yfinance data
    price_history: dict[str, dict[str, float]] = Field(default_factory=dict)  # series -> {iso date: normalised}

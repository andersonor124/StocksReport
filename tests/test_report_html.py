from datetime import date
from pathlib import Path

import pytest

from stocksreport import DISCLAIMER
from stocksreport.models import StockReport, VerificationCheck, VerificationResult
from stocksreport.report.html import render_html, write_html

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> StockReport:
    return StockReport.model_validate_json((FIX / f"{name}_report.json").read_text())


@pytest.fixture(params=["AAPL", "JPM"])
def report(request):
    return _load(request.param)


def _verification(ticker="AAPL"):
    return VerificationResult(ticker=ticker, checks=[
        VerificationCheck(category="Income", field="revenue", period="FY2025", pipeline_value=416e9,
                          source_value=416.1e9, source="SEC", diff_pct=0.0002, status="PASS"),
        VerificationCheck(category="Price", field="price", pipeline_value=342.5, source_value=350.0,
                          source="Nasdaq", diff_pct=2.1, status="WARN", note="intraday drift"),
        VerificationCheck(category="Balance", field="equity", pipeline_value=1.0, source_value=2.0,
                          source="SEC", diff_pct=0.5, status="FAIL"),
        VerificationCheck(category="Cash", field="fcf", source="SEC", status="SKIP", note="not reported"),
    ])


def test_render_contains_core_content(report):
    html = render_html(report)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert report.profile.ticker in html
    assert report.profile.name.replace("&", "&amp;") in html
    assert f'verdict-{report.analysis.verdict.lower()}' in html
    assert report.analysis.verdict in html
    for p in report.analysis.pros + report.analysis.cons:
        from markupsafe import escape
        assert str(escape(p.text)) in html
        assert str(escape(p.evidence)) in html
    assert DISCLAIMER in html
    assert "Peer median" in html
    assert "plotly" in html.lower()
    # benchmarks
    assert report.benchmark.market_ticker in html


def test_markdown_bold_rendered_safely(report):
    html = render_html(report)
    assert "**" not in html.split("<body", 1)[1].split("<script", 1)[0]


def test_headline_is_escaped():
    r = _load("AAPL")
    r.sentiment.headlines.insert(0, {"title": "<script>alert(1)</script>", "publisher": "<b>x</b>",
                                     "date": "2026-11-21", "score": 0.1, "url": "javascript:alert(1)"})
    html = render_html(r)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'href="javascript:' not in html


def test_verification_not_run():
    r = _load("JPM")
    assert r.verification is None
    html = render_html(r)
    assert "Data verification" in html
    assert "not run" in html.lower()


def test_verification_populated():
    r = _load("AAPL")
    r.verification = _verification()
    html = render_html(r)
    # 1 PASS of 3 evaluated (SKIP excluded)
    assert "Data verified: 1/3 checks passed" in html
    for s in ("PASS", "WARN", "FAIL", "SKIP"):
        assert f"status-{s.lower()}" in html
    assert "intraday drift" in html
    assert "+2.10%" in html  # diff_pct is already in percent units


def test_write_html(tmp_path):
    r = _load("AAPL")
    p = write_html(r, tmp_path)
    assert p.name == f"AAPL_{r.as_of.isoformat()}.html"
    assert p.read_text(encoding="utf-8") == render_html(r)


def test_handles_sparse_report():
    r = _load("JPM")
    r.metrics = r.metrics.model_copy(update={k: None for k in ("forward_pe", "peg", "gross_margin", "price")})
    r.price_history = {}
    r.benchmark.peers = []
    r.sentiment.headlines = []
    r.sentiment.recent_actions = []
    r.score.fair_value = r.score.fair_value.model_copy(update={"blended": None, "upside_pct": None})
    r.as_of = date(2026, 1, 2)
    html = render_html(r)
    assert "JPM" in html and DISCLAIMER in html


def test_data_corrections_and_sec_source():
    r = _load("JPM")
    html = render_html(r)
    assert "Corrections applied" not in html
    r.data_corrections = ["Revenue growth <YoY> replaced with SEC 10-K value (was 45%, now 3%)"]
    r.metrics.sources["revenue_growth_yoy"] = "SEC"
    html = render_html(r)
    assert "Corrections applied" in html
    assert "Revenue growth &lt;YoY&gt; replaced with SEC 10-K value" in html
    assert "src-sec" in html

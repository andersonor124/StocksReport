"""Excel (.xlsx) export of one or more StockReports.

Numbers are written as numbers with Excel number formats so they remain
sortable / chartable in the spreadsheet.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from stocksreport import DISCLAIMER
from stocksreport.models import StockReport

# ---- number formats ---------------------------------------------------------
PCT = "0.0%"
MULT = '0.0"x"'
USD = "$#,##0.00"
USD_B = '$#,##0.0,,,"B"'  # value in dollars, displayed in billions
INT = "#,##0"
NUM2 = "0.00"
SCORE = "0.0"

BOLD = Font(bold=True)
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=12, color="1F3864")
WRAP = Alignment(wrap_text=True, vertical="top")

STATUS_FILLS = {
    "PASS": PatternFill("solid", fgColor="C6EFCE"),
    "WARN": PatternFill("solid", fgColor="FFEB9C"),
    "FAIL": PatternFill("solid", fgColor="FFC7CE"),
    "SKIP": PatternFill("solid", fgColor="EDEDED"),
}

# metric field -> (label, number format)
METRIC_FIELDS: list[tuple[str, str, str]] = [
    ("price", "Price", USD),
    ("market_cap", "Market cap", USD_B),
    ("shares_outstanding", "Shares outstanding", INT),
    ("revenue_ttm", "Revenue (TTM)", USD_B),
    ("net_income_ttm", "Net income (TTM)", USD_B),
    ("eps_ttm", "EPS (TTM)", USD),
    ("forward_eps", "Forward EPS", USD),
    ("pe_ttm", "P/E (TTM)", MULT),
    ("forward_pe", "Forward P/E", MULT),
    ("peg", "PEG", NUM2),
    ("price_to_sales", "Price/Sales", MULT),
    ("price_to_book", "Price/Book", MULT),
    ("ev_to_ebitda", "EV/EBITDA", MULT),
    ("gross_margin", "Gross margin", PCT),
    ("operating_margin", "Operating margin", PCT),
    ("net_margin", "Net margin", PCT),
    ("roe", "Return on equity", PCT),
    ("debt_to_equity", "Debt/Equity", NUM2),
    ("fcf_ttm", "Free cash flow (TTM)", USD_B),
    ("fcf_yield", "FCF yield", PCT),
    ("revenue_growth_yoy", "Revenue growth YoY", PCT),
    ("eps_growth_yoy", "EPS growth YoY", PCT),
    ("dividend_yield", "Dividend yield", PCT),
    ("beta", "Beta", NUM2),
    ("volatility_1y", "Volatility (1Y)", PCT),
    ("max_drawdown_1y", "Max drawdown (1Y)", PCT),
    ("pct_from_52w_high", "% from 52-week high", PCT),
    ("above_200dma", "Above 200-day MA", "General"),
]

PEER_COLS: list[tuple[str, str, str]] = [
    ("ticker", "Ticker", "General"),
    ("name", "Name", "General"),
    ("market_cap", "Market cap", USD_B),
    ("pe_ttm", "P/E (TTM)", MULT),
    ("forward_pe", "Forward P/E", MULT),
    ("price_to_sales", "Price/Sales", MULT),
    ("net_margin", "Net margin", PCT),
    ("roe", "ROE", PCT),
    ("revenue_growth_yoy", "Revenue growth", PCT),
]


# ---- helpers ------------------------------------------------------------------

def _clean(text: Optional[str]) -> str:
    return (text or "").replace("**", "")


def _sheet_name(ticker: str, suffix: str) -> str:
    room = 31 - len(suffix) - 1
    return f"{ticker[:room]} {suffix}"


def _write_header(ws: Worksheet, row: int, headers: Iterable[str], col: int = 1) -> None:
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=col + i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)


def _put(ws: Worksheet, row: int, col: int, value: Any, fmt: Optional[str] = None):
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    c = ws.cell(row=row, column=col, value=value)
    if fmt and isinstance(value, (int, float)):
        c.number_format = fmt
    return c


def _widths(ws: Worksheet, widths: dict[int, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def _section(ws: Worksheet, row: int, title: str) -> int:
    ws.cell(row=row, column=1, value=title).font = SECTION_FONT
    return row + 1


def _return_for(r: StockReport, period: str):
    for pr in r.benchmark.returns:
        if pr.period == period:
            return pr
    return None


# ---- sheets -------------------------------------------------------------------

COMPARISON_COLS: list[tuple[str, str]] = [
    ("Ticker", "General"), ("Name", "General"), ("Price", USD), ("Market cap", USD_B),
    ("Score", SCORE), ("Verdict", "General"), ("Confidence", "General"),
    ("P/E", MULT), ("Fwd P/E", MULT), ("P/S", MULT), ("Net margin", PCT), ("ROE", PCT),
    ("Rev growth", PCT), ("1Y return", PCT), ("1Y vs SPY", PCT), ("Fair value", USD),
    ("Upside", PCT), ("Verification pass rate", PCT),
]


def _comparison_sheet(wb: Workbook, reports: list[StockReport]) -> None:
    ws = wb.create_sheet("Comparison", 0)
    _write_header(ws, 1, [c[0] for c in COMPARISON_COLS])
    for i, r in enumerate(reports, start=2):
        m, fv = r.metrics, r.score.fair_value
        one_y = _return_for(r, "1Y")
        rel = None
        if one_y and one_y.stock is not None and one_y.market is not None:
            rel = one_y.stock - one_y.market
        values = [
            r.profile.ticker, r.profile.name, m.price, m.market_cap, r.score.total,
            r.analysis.verdict, r.analysis.confidence, m.pe_ttm, m.forward_pe,
            m.price_to_sales, m.net_margin, m.roe, m.revenue_growth_yoy,
            one_y.stock if one_y else None, rel, fv.blended, fv.upside_pct,
            r.verification.pass_rate if r.verification else None,
        ]
        for j, (v, (_, fmt)) in enumerate(zip(values, COMPARISON_COLS), start=1):
            _put(ws, i, j, v, fmt)
    ws.freeze_panes = "B2"
    _widths(ws, {1: 9, 2: 28, **{j: 12 for j in range(3, len(COMPARISON_COLS) + 1)}})
    ws.column_dimensions[get_column_letter(len(COMPARISON_COLS))].width = 14
    ws.row_dimensions[1].height = 30
    row = len(reports) + 3
    ws.cell(row=row, column=1, value=DISCLAIMER).font = Font(italic=True, size=9)


def _summary_sheet(wb: Workbook, r: StockReport) -> None:
    p, a, s = r.profile, r.analysis, r.score
    ws = wb.create_sheet(_sheet_name(p.ticker, "Summary"))
    ws.cell(row=1, column=1, value=f"{p.name} ({p.ticker})").font = TITLE_FONT
    ws.cell(row=2, column=1, value=f"As of {r.as_of.isoformat()}")
    row = 4
    _write_header(ws, row, ["Field", "Value"])
    ws.freeze_panes = "A5"
    row += 1
    fields: list[tuple[str, Any, Optional[str]]] = [
        ("Verdict", a.verdict, None),
        ("Confidence", a.confidence, None),
        ("Score (0-100)", s.total, SCORE),
        ("Rule-based verdict", s.verdict, None),
        ("Price", r.metrics.price, USD),
        ("Market cap", r.metrics.market_cap, USD_B),
        ("Sector", p.sector, None),
        ("Industry", p.industry, None),
        ("Country", p.country, None),
        ("Exchange", p.exchange, None),
        ("Employees", p.employees, INT),
        ("Website", p.website, None),
        ("Currency", p.currency, None),
    ]
    for label, v, fmt in fields:
        ws.cell(row=row, column=1, value=label).font = BOLD
        _put(ws, row, 2, v, fmt)
        row += 1

    row += 1
    row = _section(ws, row, "Pillar scores")
    _write_header(ws, row, ["Pillar", "Score", "Weight", "Notes"])
    row += 1
    for pl in s.pillars:
        ws.cell(row=row, column=1, value=pl.name)
        _put(ws, row, 2, pl.score, SCORE)
        _put(ws, row, 3, pl.weight, "0%")
        ws.cell(row=row, column=4, value="; ".join(pl.notes)).alignment = WRAP
        row += 1

    row += 1
    row = _section(ws, row, "Fair value")
    fv = s.fair_value
    for label, v, fmt in [
        ("Analyst low target", fv.analyst_low, USD),
        ("Analyst mean target", fv.analyst_mean, USD),
        ("Analyst high target", fv.analyst_high, USD),
        ("Peer-multiple value", fv.peer_multiple_value, USD),
        ("Blended fair value", fv.blended, USD),
        ("Upside / downside", fv.upside_pct, PCT),
    ]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        _put(ws, row, 2, v, fmt)
        row += 1

    row += 1
    for label, text in [
        ("Summary", _clean(a.summary)),
        ("Entry suggestion", a.entry_price_suggestion or "n/a"),
        ("Rationale", a.rationale),
        ("Retail investor view", a.retail_investor_view),
        ("Portfolio manager view", a.portfolio_manager_view),
        ("Company description", p.summary or ""),
    ]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        c = ws.cell(row=row, column=2, value=text)
        c.alignment = WRAP
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        # rough height estimate: ~120 chars per line across merged width
        lines = max(1, len(text) // 110 + 1)
        ws.row_dimensions[row].height = min(400, 15 * lines)
        row += 1

    row += 1
    c = ws.cell(row=row, column=1, value=DISCLAIMER)
    c.font = Font(italic=True, size=9)
    _widths(ws, {1: 24, 2: 22, 3: 10, 4: 60})


def _metrics_sheet(wb: Workbook, r: StockReport) -> None:
    ws = wb.create_sheet(_sheet_name(r.profile.ticker, "Metrics"))
    _write_header(ws, 1, ["Metric", "Value", "Source"])
    ws.freeze_panes = "A2"
    m = r.metrics
    for i, (field, label, fmt) in enumerate(METRIC_FIELDS, start=2):
        ws.cell(row=i, column=1, value=label)
        v = getattr(m, field)
        _put(ws, i, 2, v if v is not None else "n/a", fmt)
        ws.cell(row=i, column=3, value=m.sources.get(field, "yfinance" if v is not None else ""))
    ws.cell(row=len(METRIC_FIELDS) + 3, column=1, value=DISCLAIMER).font = Font(italic=True, size=9)
    _widths(ws, {1: 24, 2: 16, 3: 14})


def _benchmark_sheet(wb: Workbook, r: StockReport) -> None:
    b = r.benchmark
    t = r.profile.ticker
    ws = wb.create_sheet(_sheet_name(t, "Benchmark"))
    ws.cell(row=1, column=1, value="Returns").font = SECTION_FONT
    sector_label = f"Sector ({b.sector_ticker})" if b.sector_ticker else "Sector"
    _write_header(ws, 2, ["Period", t, f"Market ({b.market_ticker})", sector_label, f"{t} vs market"])
    ws.freeze_panes = "A3"
    row = 3
    for pr in b.returns:
        ws.cell(row=row, column=1, value=pr.period)
        _put(ws, row, 2, pr.stock, PCT)
        _put(ws, row, 3, pr.market, PCT)
        _put(ws, row, 4, pr.sector, PCT)
        if pr.stock is not None and pr.market is not None:
            _put(ws, row, 5, pr.stock - pr.market, PCT)
        row += 1

    row += 1
    row = _section(ws, row, "Peers")
    _write_header(ws, row, [c[1] for c in PEER_COLS])
    row += 1
    for peer in [*b.peers, b.peer_median]:
        for j, (field, _, fmt) in enumerate(PEER_COLS, start=1):
            c = _put(ws, row, j, getattr(peer, field), fmt)
            if peer is b.peer_median:
                c.font = BOLD
        row += 1
    # the company itself, for comparison
    m = r.metrics
    own = {"ticker": t, "name": r.profile.name, "market_cap": m.market_cap, "pe_ttm": m.pe_ttm,
           "forward_pe": m.forward_pe, "price_to_sales": m.price_to_sales,
           "net_margin": m.net_margin, "roe": m.roe, "revenue_growth_yoy": m.revenue_growth_yoy}
    for j, (field, _, fmt) in enumerate(PEER_COLS, start=1):
        c = _put(ws, row, j, own[field], fmt)
        c.font = Font(italic=True)
    row += 2

    # price history data (rebased to 100) + native line chart
    series = list(r.price_history.keys())
    if series:
        row = _section(ws, row, "Price history (rebased to 100)")
        hdr_row = row
        _write_header(ws, hdr_row, ["Date", *series])
        dates = sorted({d for s in r.price_history.values() for d in s})
        for i, d in enumerate(dates, start=hdr_row + 1):
            try:
                ws.cell(row=i, column=1, value=date.fromisoformat(d)).number_format = "yyyy-mm-dd"
            except ValueError:
                ws.cell(row=i, column=1, value=d)
            for j, s in enumerate(series, start=2):
                v = r.price_history[s].get(d)
                if v is not None:
                    _put(ws, i, j, float(v), "0.0")
        last = hdr_row + len(dates)
        chart = LineChart()
        chart.title = f"{t} vs benchmarks (rebased to 100)"
        chart.y_axis.title = "Index"
        chart.x_axis.number_format = "mmm-yy"
        chart.x_axis.majorTimeUnit = "months"
        chart.height = 9
        chart.width = 20
        data = Reference(ws, min_col=2, max_col=1 + len(series), min_row=hdr_row, max_row=last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=hdr_row + 1, max_row=last))
        for s in chart.series:
            s.smooth = False
            s.graphicalProperties.line.width = 15000
        ws.add_chart(chart, "K2")
    _widths(ws, {1: 14, 2: 30, 3: 15, 4: 14, 5: 14, 6: 13, 7: 12, 8: 12, 9: 14})


def _pros_cons_sheet(wb: Workbook, r: StockReport) -> None:
    a, sent = r.analysis, r.sentiment
    ws = wb.create_sheet(_sheet_name(r.profile.ticker, "Pros-Cons"))
    _write_header(ws, 1, ["Type", "Point", "Evidence"])
    ws.freeze_panes = "A2"
    row = 2
    for kind, pts in (("Pro", a.pros), ("Con", a.cons)):
        for pt in pts:
            ws.cell(row=row, column=1, value=kind).font = Font(
                bold=True, color="006100" if kind == "Pro" else "9C0006")
            ws.cell(row=row, column=2, value=pt.text).alignment = WRAP
            ws.cell(row=row, column=3, value=pt.evidence).alignment = WRAP
            row += 1
    for kind, items in (("Risk", a.key_risks), ("Catalyst", a.catalysts)):
        for it in items:
            ws.cell(row=row, column=1, value=kind).font = BOLD
            ws.cell(row=row, column=2, value=it).alignment = WRAP
            row += 1

    row += 1
    row = _section(ws, row, "Analyst sentiment")
    for label, v in [
        ("Recommendation", sent.recommendation_key),
        ("Number of analysts", sent.num_analysts),
        ("Trend", sent.analyst_trend),
        ("Upgrades (90d)", sent.upgrades_90d),
        ("Downgrades (90d)", sent.downgrades_90d),
        *[(f"{k} ratings", n) for k, n in sent.analyst_counts.items()],
    ]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=2, value=v)
        row += 1
    if sent.recent_actions:
        row += 1
        row = _section(ws, row, "Recent analyst actions")
        for act in sent.recent_actions:
            ws.cell(row=row, column=1, value="Action")
            ws.cell(row=row, column=2, value=act).alignment = WRAP
            row += 1

    row += 1
    row = _section(ws, row, "News headlines")
    if sent.news_score is not None:
        ws.cell(row=row, column=1, value="Average sentiment").font = BOLD
        _put(ws, row, 2, sent.news_score, "+0.00;-0.00;0.00")
        ws.cell(row=row, column=3, value=sent.news_label)
        row += 1
    _write_header(ws, row, ["Sentiment", "Headline", "Publisher / date"])
    row += 1
    for h in sent.headlines:
        score = h.get("score")
        c = _put(ws, row, 1, score, "+0.00;-0.00;0.00")
        if isinstance(score, (int, float)):
            c.fill = STATUS_FILLS["PASS"] if score > 0.05 else (
                STATUS_FILLS["FAIL"] if score < -0.05 else STATUS_FILLS["SKIP"])
        hc = ws.cell(row=row, column=2, value=h.get("title"))
        hc.alignment = WRAP
        if h.get("url"):
            hc.hyperlink = h["url"]
        ws.cell(row=row, column=3, value=" / ".join(
            str(x) for x in (h.get("publisher"), h.get("date")) if x))
        row += 1
    row += 1
    ws.cell(row=row, column=1, value=DISCLAIMER).font = Font(italic=True, size=9)
    _widths(ws, {1: 20, 2: 70, 3: 45})


def _corrections(ws: Worksheet, r: StockReport, row: int) -> int:
    """Write the 'Corrections applied' block (if any); return the next free row."""
    corr = getattr(r, "data_corrections", None) or []
    if not corr:
        return row
    row = _section(ws, row, "Corrections applied")
    ws.cell(row=row, column=1,
            value="SEC-filed values that replaced yfinance data:").font = Font(italic=True)
    row += 1
    for note in corr:
        ws.cell(row=row, column=1, value=note)
        row += 1
    return row + 1


def _verification_sheet(wb: Workbook, r: StockReport) -> None:
    ws = wb.create_sheet(_sheet_name(r.profile.ticker, "Verification"))
    v = r.verification
    if v is None:
        ws.cell(row=1, column=1, value="Verification").font = TITLE_FONT
        ws.cell(row=2, column=1,
                value="Verification not run for this report (no independent cross-check data).")
        row = _corrections(ws, r, 4)
        ws.cell(row=row, column=1, value=DISCLAIMER).font = Font(italic=True, size=9)
        _widths(ws, {1: 80})
        return
    counts = v.counts
    ws.cell(row=1, column=1, value="Pass rate").font = BOLD
    _put(ws, 1, 2, v.pass_rate, PCT)
    ws.cell(row=1, column=3, value="  ".join(f"{k}: {n}" for k, n in counts.items()))
    headers = ["Status", "Category", "Field", "Period", "Pipeline value", "Source value",
               "Diff %", "Source", "Note"]
    _write_header(ws, 3, headers)
    ws.freeze_panes = "A4"
    order = {"FAIL": 0, "WARN": 1, "PASS": 2, "SKIP": 3}
    for i, c in enumerate(sorted(v.checks, key=lambda c: order[c.status]), start=4):
        sc = ws.cell(row=i, column=1, value=c.status)
        sc.fill = STATUS_FILLS[c.status]
        sc.font = BOLD
        ws.cell(row=i, column=2, value=c.category)
        ws.cell(row=i, column=3, value=c.field)
        ws.cell(row=i, column=4, value=c.period)
        _put(ws, i, 5, c.pipeline_value, "#,##0.00")
        _put(ws, i, 6, c.source_value, "#,##0.00")
        _put(ws, i, 7, c.diff_pct, "0.00%")
        ws.cell(row=i, column=8, value=c.source)
        ws.cell(row=i, column=9, value=c.note)
    row = _corrections(ws, r, len(v.checks) + 5)
    ws.cell(row=row, column=1, value=DISCLAIMER).font = Font(italic=True, size=9)
    _widths(ws, {1: 11, 2: 14, 3: 22, 4: 12, 5: 18, 6: 18, 7: 10, 8: 16, 9: 50})


# ---- public API -----------------------------------------------------------------

def to_xlsx_bytes(reports: list[StockReport]) -> bytes:
    if not reports:
        raise ValueError("at least one report is required")
    wb = Workbook()
    wb.remove(wb.active)
    for r in reports:
        _summary_sheet(wb, r)
        _metrics_sheet(wb, r)
        _benchmark_sheet(wb, r)
        _pros_cons_sheet(wb, r)
        _verification_sheet(wb, r)
    if len(reports) > 1:
        _comparison_sheet(wb, reports)
    wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_xlsx(reports: list[StockReport], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_xlsx_bytes(reports))
    return path

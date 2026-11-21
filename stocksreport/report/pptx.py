"""PowerPoint (.pptx) deck for a single StockReport (16:9, ~10 slides)."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

from stocksreport import DISCLAIMER  # noqa: E402
from stocksreport.models import StockReport  # noqa: E402

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.5)
CONTENT_TOP = Inches(1.25)
CONTENT_BOTTOM = Inches(6.85)  # footer below this
CONTENT_W = SLIDE_W - 2 * MARGIN

NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xF2, 0xF2, 0xF2)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xC6, 0x28, 0x28)
AMBER = RGBColor(0xB2, 0x6A, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
VERDICT_COLORS = {"Buy": GREEN, "Hold": AMBER, "Sell": RED}
STATUS_COLORS = {"PASS": RGBColor(0xC6, 0xEF, 0xCE), "WARN": RGBColor(0xFF, 0xEB, 0x9C),
                 "FAIL": RGBColor(0xFF, 0xC7, 0xCE), "SKIP": LIGHT}
CHART_COLORS = ["#1F3864", "#E07B00", "#7F7F7F", "#2E7D32", "#8E24AA"]


# ---- formatting helpers ---------------------------------------------------------

def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").replace("**", "").split())


def _trunc(text: Optional[str], n: int) -> str:
    """Trim to <= n chars, preferring a sentence then a word boundary."""
    t = _clean(text)
    if len(t) <= n:
        return t
    cut = t[: n - 1]
    dot = cut.rfind(". ")
    if dot > n * 0.6:
        return cut[: dot + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > n * 0.6 else cut).rstrip(",;:- ") + "…"


def _pct(v: Optional[float], signed: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def _mult(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.1f}x"


def _usd(v: Optional[float]) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _big(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"${v / div:,.2f}{suf}"
    return f"${v:,.0f}"


def _num(v: Optional[float], fmt: str = "{:.2f}") -> str:
    return "n/a" if v is None else fmt.format(v)


# ---- shape helpers --------------------------------------------------------------

def _textbox(slide, left, top, width, height, text="", size=14, bold=False,
             color=None, align=None, anchor=MSO_ANCHOR.TOP, italic=False):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right"):
        setattr(tf, m, Inches(0.05))
    p = tf.paragraphs[0]
    _run(p, text, size, bold, color, italic)
    if align is not None:
        p.alignment = align
    return tb


def _run(p, text, size=14, bold=False, color=None, italic=False):
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    if color is not None:
        r.font.color.rgb = color
    return r


def _bullets(slide, left, top, width, height, items, size=14, color=None, gap=6):
    """items: list of str or (headline, sub) tuples. Sub text rendered smaller."""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    first = True
    for it in items:
        head, sub = (it if isinstance(it, tuple) else (it, None))
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_before = Pt(gap)
        _run(p, "• ", size, True, color)
        _run(p, head, size, False, None)
        if sub:
            p2 = tf.add_paragraph()
            p2.level = 0
            _run(p2, "   " + sub, max(9, size - 3), False, GREY, italic=True)
    return tb


def _table(slide, left, top, width, rows, col_widths=None, size=12, row_h=Inches(0.36),
           header_fill=NAVY, fills=None):
    n_rows, n_cols = len(rows), len(rows[0])
    shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, row_h * n_rows)
    tbl = shape.table
    if col_widths:
        total = sum(col_widths)
        for j, w in enumerate(col_widths):
            tbl.columns[j].width = Emu(int(width * w / total))
    for i, row in enumerate(rows):
        tbl.rows[i].height = row_h
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            _run(p, str(val), size, bold=(i == 0), color=WHITE if i == 0 else None)
            if j > 0:
                p.alignment = PP_ALIGN.RIGHT if i > 0 and _looks_numeric(val) else PP_ALIGN.LEFT
            if i == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_fill
            elif fills and (i, j) in fills:
                cell.fill.solid()
                cell.fill.fore_color.rgb = fills[(i, j)]
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if i % 2 else LIGHT
    return shape


def _looks_numeric(v) -> bool:
    s = str(v).strip()
    return bool(s) and (s[0] in "$+-0123456789" or s == "n/a")


def _picture(slide, png: bytes, left, top, width=None, height=None):
    return slide.shapes.add_picture(io.BytesIO(png), left, top, width, height)


class _Deck:
    def __init__(self, report: StockReport):
        self.r = report
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = SLIDE_W, SLIDE_H
        self.layout = self.prs.slide_layouts[6]  # blank
        self.n = 0

    def slide(self, title: Optional[str]):
        s = self.prs.slides.add_slide(self.layout)
        self.n += 1
        if title:
            bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, Inches(1.0))
            bar.fill.solid()
            bar.fill.fore_color.rgb = NAVY
            bar.line.fill.background()
            _textbox(s, MARGIN, Inches(0.12), Inches(10.5), Inches(0.76), title, size=28,
                     bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
            _textbox(s, Inches(10.8), Inches(0.12), Inches(2.03), Inches(0.76),
                     f"{self.r.profile.ticker} · {self.r.as_of.isoformat()}", size=14,
                     color=WHITE, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        self._footer(s)
        s.notes_slide.notes_text_frame.text = DISCLAIMER
        return s

    def _footer(self, s):
        _textbox(s, MARGIN, Inches(6.95), Inches(11.6), Inches(0.4), DISCLAIMER, size=8,
                 color=GREY, italic=True, anchor=MSO_ANCHOR.MIDDLE)
        _textbox(s, Inches(12.23), Inches(6.95), Inches(0.6), Inches(0.4), str(self.n),
                 size=9, color=GREY, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)

    def bytes(self) -> bytes:
        buf = io.BytesIO()
        self.prs.save(buf)
        return buf.getvalue()


# ---- charts ---------------------------------------------------------------------

def _fig_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


def _price_chart(r: StockReport, w_in: float, h_in: float) -> Optional[bytes]:
    if not r.price_history:
        return None
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    for i, (label, series) in enumerate(r.price_history.items()):
        pts = sorted(series.items())
        xs = [date.fromisoformat(d) for d, _ in pts]
        ys = [v for _, v in pts]
        lw = 2.4 if label == r.profile.ticker else 1.4
        ax.plot(xs, ys, label=label, color=CHART_COLORS[i % len(CHART_COLORS)], linewidth=lw)
    ax.axhline(100, color="#BBBBBB", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Rebased to 100")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Price performance vs benchmarks", fontsize=12, loc="left")
    fig.tight_layout()
    return _fig_png(fig)


def _pillar_chart(r: StockReport, w_in: float, h_in: float) -> bytes:
    pillars = list(reversed(r.score.pillars))
    names = [f"{p.name} ({p.weight:.0%})" for p in pillars]
    vals = [p.score if p.score is not None else 0 for p in pillars]
    colors = ["#2E7D32" if v >= 65 else "#E0A800" if v >= 45 else "#C62828" for v in vals]
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    bars = ax.barh(names, vals, color=colors)
    for b, p in zip(bars, pillars):
        lbl = "n/a" if p.score is None else f"{p.score:.0f}"
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2, lbl, va="center", fontsize=11)
    ax.set_xlim(0, 105)
    ax.axvline(65, color="#2E7D32", linestyle=":", linewidth=1)
    ax.axvline(45, color="#C62828", linestyle=":", linewidth=1)
    ax.set_xlabel("Score (0-100); dotted lines: Buy ≥ 65, Sell < 45")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", labelsize=11)
    fig.tight_layout()
    return _fig_png(fig)


# ---- slides ---------------------------------------------------------------------

def _title_slide(d: _Deck):
    r, p, a = d.r, d.r.profile, d.r.analysis
    s = d.slide(None)
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(1.6), SLIDE_W, Inches(2.6))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    _textbox(s, MARGIN, Inches(1.8), Inches(12.3), Inches(1.2), _trunc(p.name, 45), size=44,
             bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    sub = " · ".join(x for x in (p.ticker, p.exchange, p.sector) if x)
    _textbox(s, MARGIN, Inches(3.0), Inches(12.3), Inches(0.6), sub, size=22, color=WHITE)
    _textbox(s, MARGIN, Inches(3.55), Inches(12.3), Inches(0.5),
             f"Stock report · as of {r.as_of.strftime('%d %B %Y')}", size=16, color=WHITE)
    # verdict pill + score
    pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, Inches(4.7), Inches(3.0),
                              Inches(1.1))
    pill.fill.solid()
    pill.fill.fore_color.rgb = VERDICT_COLORS.get(a.verdict, NAVY)
    pill.line.fill.background()
    tf = pill.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    _run(tf.paragraphs[0], a.verdict.upper(), 32, True, WHITE)
    _textbox(s, Inches(3.8), Inches(4.7), Inches(8.9), Inches(1.1),
             f"Score {r.score.total:.0f}/100 · Confidence: {a.confidence} · "
             f"Price {_usd(r.metrics.price)}", size=22, color=NAVY, bold=True,
             anchor=MSO_ANCHOR.MIDDLE)


def _overview_slide(d: _Deck):
    r, p = d.r, d.r.profile
    s = d.slide("Company overview")
    _textbox(s, MARGIN, CONTENT_TOP, Inches(7.6), Inches(5.4),
             _trunc(p.summary or "No company description available.", 900), size=14)
    facts = [
        ["Fact", "Value"],
        ["Sector", _trunc(p.sector or "n/a", 28)],
        ["Industry", _trunc(p.industry or "n/a", 28)],
        ["Market cap", _big(r.metrics.market_cap)],
        ["Employees", f"{p.employees:,}" if p.employees else "n/a"],
        ["Country", _trunc(p.country or "n/a", 28)],
        ["Exchange", p.exchange or "n/a"],
        ["Price", _usd(r.metrics.price)],
    ]
    _table(s, Inches(8.4), CONTENT_TOP, Inches(4.43), facts, col_widths=[1.2, 2], size=14,
           row_h=Inches(0.45))
    if p.website:
        _textbox(s, Inches(8.4), Inches(5.0), Inches(4.43), Inches(0.4), p.website, size=12,
                 color=GREY)


def _metrics_slide(d: _Deck):
    m = d.r.metrics
    pm = d.r.benchmark.peer_median
    s = d.slide("Key metrics")
    left = [
        ["Valuation", d.r.profile.ticker, "Peer median"],
        ["P/E (TTM)", _mult(m.pe_ttm), _mult(pm.pe_ttm)],
        ["Forward P/E", _mult(m.forward_pe), _mult(pm.forward_pe)],
        ["Price/Sales", _mult(m.price_to_sales), _mult(pm.price_to_sales)],
        ["Price/Book", _mult(m.price_to_book), "–"],
        ["EV/EBITDA", _mult(m.ev_to_ebitda), "–"],
        ["PEG", _num(m.peg), "–"],
        ["FCF yield", _pct(m.fcf_yield), "–"],
        ["Dividend yield", _pct(m.dividend_yield), "–"],
    ]
    right = [
        ["Quality, growth & risk", "Value", "Peer median"],
        ["Net margin", _pct(m.net_margin), _pct(pm.net_margin)],
        ["Operating margin", _pct(m.operating_margin), "–"],
        ["Return on equity", _pct(m.roe), _pct(pm.roe)],
        ["Revenue growth YoY", _pct(m.revenue_growth_yoy), _pct(pm.revenue_growth_yoy)],
        ["EPS growth YoY", _pct(m.eps_growth_yoy), "–"],
        ["Debt/Equity", _num(m.debt_to_equity), "–"],
        ["Beta / Volatility 1Y", f"{_num(m.beta)} / {_pct(m.volatility_1y)}", "–"],
        ["Max drawdown 1Y", _pct(m.max_drawdown_1y), "–"],
    ]
    w = Inches(6.0)
    _table(s, MARGIN, CONTENT_TOP, w, left, col_widths=[2.2, 1.4, 1.4], size=14,
           row_h=Inches(0.5))
    _table(s, SLIDE_W - MARGIN - w, CONTENT_TOP, w, right, col_widths=[2.2, 1.4, 1.4], size=14,
           row_h=Inches(0.5))
    _textbox(s, MARGIN, Inches(5.95), CONTENT_W, Inches(0.7),
             f"Revenue (TTM) {_big(m.revenue_ttm)} · Net income (TTM) "
             f"{_big(m.net_income_ttm)} · EPS (TTM) {_usd(m.eps_ttm)} · "
             f"{_pct(m.pct_from_52w_high)} from 52-week high · "
             f"{'above' if m.above_200dma else 'below' if m.above_200dma is False else 'n/a vs'}"
             " 200-day average", size=13, color=GREY)


def _benchmark_slide(d: _Deck):
    r, b = d.r, d.r.benchmark
    s = d.slide("Performance vs benchmarks")
    png = _price_chart(r, 8.0, 5.2)
    if png:
        _picture(s, png, MARGIN, CONTENT_TOP, width=Inches(7.9))
    else:
        _textbox(s, MARGIN, CONTENT_TOP, Inches(7.9), Inches(1), "No price history available.")
    sec = b.sector_ticker or "Sector"
    rows = [["Period", r.profile.ticker, b.market_ticker, sec]]
    for pr in b.returns[:8]:
        rows.append([pr.period, _pct(pr.stock, True), _pct(pr.market, True),
                     _pct(pr.sector, True)])
    fills = {}
    for i, pr in enumerate(b.returns[:8], start=1):
        if pr.stock is not None and pr.market is not None:
            fills[(i, 1)] = STATUS_COLORS["PASS"] if pr.stock >= pr.market else STATUS_COLORS["FAIL"]
    _table(s, Inches(8.65), CONTENT_TOP, Inches(4.18), rows, col_widths=[1, 1.2, 1.2, 1.2],
           size=13, row_h=Inches(0.45), fills=fills)
    _textbox(s, Inches(8.65), CONTENT_TOP + Inches(0.45) * len(rows) + Inches(0.15),
             Inches(4.18), Inches(0.8),
             f"Green/red: {r.profile.ticker} beat/lagged {b.market_ticker} over the period.",
             size=11, color=GREY)


def _score_slide(d: _Deck):
    r = d.r
    s = d.slide(f"Score breakdown — {r.score.total:.0f}/100")
    png = _pillar_chart(r, 7.6, 5.0)
    _picture(s, png, MARGIN, CONTENT_TOP, width=Inches(7.5))
    notes = []
    for p in r.score.pillars:
        if p.notes:
            notes.append((p.name, _trunc("; ".join(p.notes), 85)))
    _bullets(s, Inches(8.2), CONTENT_TOP, Inches(4.63), Inches(5.4), notes[:6], size=13, gap=4,
             color=NAVY)


def _pros_cons_slide(d: _Deck):
    a = d.r.analysis
    s = d.slide("Pros & cons")
    col_w = Inches(6.0)
    for i, (label, pts, color) in enumerate((("Pros", a.pros, GREEN), ("Cons", a.cons, RED))):
        left = MARGIN + i * (col_w + Inches(0.33))
        hdr = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, CONTENT_TOP, col_w, Inches(0.5))
        hdr.fill.solid()
        hdr.fill.fore_color.rgb = color
        hdr.line.fill.background()
        hdr.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
        _run(hdr.text_frame.paragraphs[0], label, 18, True, WHITE)
        items = [(_trunc(p.text, 90), _trunc(p.evidence, 110)) for p in pts[:6]]
        if not items:
            items = ["None identified"]
        size = 18 if len(items) <= 4 else 15
        _bullets(s, left, CONTENT_TOP + Inches(0.6), col_w, Inches(4.9), items, size=size,
                 color=color, gap=8)
        if len(pts) > 6:
            _textbox(s, left, Inches(6.45), col_w, Inches(0.35),
                     f"+{len(pts) - 6} more in the full report", size=11, color=GREY)


def _views_slide(d: _Deck):
    a = d.r.analysis
    s = d.slide("Investor views")
    col_w = Inches(6.0)
    for i, (label, text) in enumerate((("Retail investor", a.retail_investor_view),
                                       ("Portfolio manager", a.portfolio_manager_view))):
        left = MARGIN + i * (col_w + Inches(0.33))
        box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, CONTENT_TOP, col_w, Inches(5.3))
        box.fill.solid()
        box.fill.fore_color.rgb = LIGHT
        box.line.fill.background()
        _textbox(s, left + Inches(0.2), CONTENT_TOP + Inches(0.15), col_w - Inches(0.4),
                 Inches(0.5), label, size=20, bold=True, color=NAVY)
        _textbox(s, left + Inches(0.2), CONTENT_TOP + Inches(0.75), col_w - Inches(0.4),
                 Inches(4.4), _trunc(text, 600), size=18)


def _verdict_slide(d: _Deck):
    r, a, fv = d.r, d.r.analysis, d.r.score.fair_value
    s = d.slide("Verdict & fair value")
    pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, MARGIN, CONTENT_TOP, Inches(3.2),
                              Inches(1.0))
    pill.fill.solid()
    pill.fill.fore_color.rgb = VERDICT_COLORS.get(a.verdict, NAVY)
    pill.line.fill.background()
    pill.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    pill.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    _run(pill.text_frame.paragraphs[0], a.verdict.upper(), 30, True, WHITE)
    _textbox(s, Inches(3.9), CONTENT_TOP, Inches(8.9), Inches(1.0),
             f"Score {r.score.total:.0f}/100 · Confidence {a.confidence}\n"
             + _trunc(a.rationale, 150), size=13, color=GREY, anchor=MSO_ANCHOR.MIDDLE)
    rows = [
        ["Fair value", "Price"],
        ["Current price", _usd(r.metrics.price)],
        ["Analyst low / mean / high",
         f"{_usd(fv.analyst_low)} / {_usd(fv.analyst_mean)} / {_usd(fv.analyst_high)}"],
        ["Peer-multiple value", _usd(fv.peer_multiple_value)],
        ["Blended fair value", _usd(fv.blended)],
        ["Upside / downside", _pct(fv.upside_pct, True)],
    ]
    _table(s, MARGIN, Inches(2.45), Inches(6.2), rows, col_widths=[2.3, 2.9], size=13,
           row_h=Inches(0.42))
    _textbox(s, MARGIN, Inches(5.1), Inches(6.2), Inches(0.35), "Entry suggestion", size=14,
             bold=True, color=NAVY)
    _textbox(s, MARGIN, Inches(5.45), Inches(6.2), Inches(1.3),
             _trunc(a.entry_price_suggestion or "No entry suggestion available.", 260), size=13)
    right = Inches(7.0)
    w = SLIDE_W - MARGIN - right
    _textbox(s, right, Inches(2.45), w, Inches(0.4), "Key risks", size=16, bold=True, color=RED)
    risks = [_trunc(x, 90) for x in a.key_risks[:4]] or ["None identified"]
    _bullets(s, right, Inches(2.8), w, Inches(1.9), risks, size=13, color=RED, gap=3)
    _textbox(s, right, Inches(4.75), w, Inches(0.4), "Catalysts", size=16, bold=True,
             color=GREEN)
    cats = [_trunc(x, 90) for x in a.catalysts[:4]] or ["None identified"]
    _bullets(s, right, Inches(5.1), w, Inches(1.7), cats, size=13, color=GREEN, gap=3)


def _corrections_box(s, corr: list[str], top, bottom=Inches(6.8)):
    """'Corrections applied' block: SEC-filed values that overrode yfinance data."""
    if not corr:
        return
    max_items = max(1, int((bottom - top - Inches(0.45)) / Inches(0.32)))
    items = [_trunc(c, 150) for c in corr[:max_items]]
    if len(corr) > max_items:
        items[-1] = f"+{len(corr) - max_items + 1} more corrections in the Excel workbook"
    _textbox(s, MARGIN, top, CONTENT_W, Inches(0.4), "Corrections applied", size=16,
             bold=True, color=NAVY)
    _bullets(s, MARGIN, top + Inches(0.4), CONTENT_W, bottom - top - Inches(0.4), items,
             size=12, color=NAVY, gap=2)


def _verification_slide(d: _Deck):
    v = d.r.verification
    corr = list(getattr(d.r, "data_corrections", None) or [])
    s = d.slide("Data verification")
    if v is None:
        _textbox(s, MARGIN, CONTENT_TOP + Inches(0.3), CONTENT_W, Inches(0.8),
                 "Verification not run for this report.", size=24, bold=True, color=NAVY)
        _textbox(s, MARGIN, CONTENT_TOP + Inches(1.1), CONTENT_W, Inches(1.0),
                 "Pipeline figures were not cross-checked against independent free sources "
                 "(e.g. SEC EDGAR filings, Nasdaq quotes). Treat all numbers as unverified.",
                 size=16, color=GREY)
        _corrections_box(s, corr, Inches(3.6))
        return
    c = v.counts
    rate = v.pass_rate
    _textbox(s, MARGIN, CONTENT_TOP, Inches(4.0), Inches(1.0),
             f"{rate:.0%} pass rate" if rate is not None else "Pass rate n/a",
             size=32, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    _textbox(s, Inches(4.6), CONTENT_TOP, Inches(8.2), Inches(1.0),
             f"PASS {c['PASS']} · WARN {c['WARN']} · FAIL {c['FAIL']} · "
             f"SKIP {c['SKIP']}  ({len(v.checks)} checks)", size=18, color=GREY,
             anchor=MSO_ANCHOR.MIDDLE)
    flagged = [x for x in v.checks if x.status == "FAIL"] + \
              [x for x in v.checks if x.status == "WARN"]
    if not flagged:
        _textbox(s, MARGIN, Inches(2.5), CONTENT_W, Inches(1),
                 "No FAIL or WARN checks — all evaluated figures matched independent sources.",
                 size=18)
        _corrections_box(s, corr, Inches(3.6))
        return
    shown = flagged[:4] if corr else flagged[:8]
    rows = [["Status", "Check", "Pipeline", "Source value", "Diff", "Source", "Note"]]
    fills = {}
    for i, x in enumerate(shown, start=1):
        rows.append([
            x.status,
            _trunc(f"{x.category}: {x.field}" + (f" ({x.period})" if x.period else ""), 40),
            _num(x.pipeline_value, "{:,.2f}"), _num(x.source_value, "{:,.2f}"),
            _pct(x.diff_pct), _trunc(x.source, 18), _trunc(x.note or "", 45),
        ])
        fills[(i, 0)] = STATUS_COLORS[x.status]
    _table(s, MARGIN, Inches(2.4), CONTENT_W, rows,
           col_widths=[0.8, 2.6, 1.3, 1.3, 0.8, 1.4, 3.0], size=11, row_h=Inches(0.42),
           fills=fills)
    if len(flagged) > len(shown):
        _textbox(s, MARGIN, Inches(2.4) + Inches(0.42) * len(rows), CONTENT_W, Inches(0.35),
                 f"+{len(flagged) - len(shown)} more flagged checks in the Excel workbook.",
                 size=11, color=GREY)
    _corrections_box(s, corr, Inches(2.4) + Inches(0.42) * len(rows) + Inches(0.4))


def _disclaimer_slide(d: _Deck):
    s = d.slide("Disclaimer")
    _textbox(s, Inches(1.5), Inches(2.2), Inches(10.3), Inches(2.5), DISCLAIMER, size=24,
             color=NAVY, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _textbox(s, Inches(1.5), Inches(4.9), Inches(10.3), Inches(0.8),
             "Data: free public sources (Yahoo Finance via yfinance, SEC EDGAR, Nasdaq). "
             f"Generated {d.r.as_of.isoformat()}.", size=14, color=GREY, align=PP_ALIGN.CENTER)


# ---- public API -----------------------------------------------------------------

def to_pptx_bytes(report: StockReport) -> bytes:
    d = _Deck(report)
    for fn in (_title_slide, _overview_slide, _metrics_slide, _benchmark_slide, _score_slide,
               _pros_cons_slide, _views_slide, _verdict_slide, _verification_slide,
               _disclaimer_slide):
        fn(d)
    return d.bytes()


def write_pptx(report: StockReport, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_pptx_bytes(report))
    return path

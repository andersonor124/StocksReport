"""Self-contained HTML report rendering (Jinja2, autoescaped)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from stocksreport import DISCLAIMER
from stocksreport.models import StockReport

TEMPLATE_DIR = Path(__file__).parent / "templates"
PLOTLY_CDN = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"

# (label, Metrics attribute, format kind)
METRIC_ROWS: list[tuple[str, str, str]] = [
    ("Price", "price", "price"),
    ("Market cap", "market_cap", "money"),
    ("Revenue (TTM)", "revenue_ttm", "money"),
    ("Net income (TTM)", "net_income_ttm", "money"),
    ("Free cash flow (TTM)", "fcf_ttm", "money"),
    ("EPS (TTM)", "eps_ttm", "price"),
    ("Forward EPS", "forward_eps", "price"),
    ("P/E (TTM)", "pe_ttm", "mult"),
    ("Forward P/E", "forward_pe", "mult"),
    ("PEG", "peg", "ratio"),
    ("Price / Sales", "price_to_sales", "mult"),
    ("Price / Book", "price_to_book", "mult"),
    ("EV / EBITDA", "ev_to_ebitda", "mult"),
    ("Gross margin", "gross_margin", "pct"),
    ("Operating margin", "operating_margin", "pct"),
    ("Net margin", "net_margin", "pct"),
    ("Return on equity", "roe", "pct"),
    ("Debt / Equity", "debt_to_equity", "ratio"),
    ("FCF yield", "fcf_yield", "pct"),
    ("Revenue growth (YoY)", "revenue_growth_yoy", "pct"),
    ("EPS growth (YoY)", "eps_growth_yoy", "pct"),
    ("Dividend yield", "dividend_yield", "pct"),
    ("Beta", "beta", "ratio"),
    ("Volatility (1Y)", "volatility_1y", "pct"),
    ("Max drawdown (1Y)", "max_drawdown_1y", "pct"),
    ("From 52-week high", "pct_from_52w_high", "pct"),
    ("Above 200-day average", "above_200dma", "bool"),
]

DASH = "—"


def fmt_pct(v: Optional[float], digits: int = 1, signed: bool = False) -> str:
    if v is None:
        return DASH
    return f"{v * 100:+.{digits}f}%" if signed else f"{v * 100:.{digits}f}%"


def fmt_mult(v: Optional[float]) -> str:
    return DASH if v is None else f"{v:.1f}x"


def fmt_ratio(v: Optional[float]) -> str:
    return DASH if v is None else f"{v:.2f}"


def fmt_price(v: Optional[float]) -> str:
    return DASH if v is None else f"${v:,.2f}"


def fmt_money(v: Optional[float]) -> str:
    if v is None:
        return DASH
    sign = "-" if v < 0 else ""
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:,.2f}{suf}"
    return f"{sign}${a:,.0f}"


def fmt_value(v, kind: str) -> str:
    if kind == "bool":
        return DASH if v is None else ("Yes" if v else "No")
    return {"pct": fmt_pct, "mult": fmt_mult, "ratio": fmt_ratio, "price": fmt_price,
            "money": fmt_money}[kind](v)


def fmt_num(v: Optional[float]) -> str:
    """Generic number for verification values (money-like if large)."""
    if v is None:
        return DASH
    if abs(v) >= 1e5:
        return fmt_money(v).replace("$", "")
    return f"{v:,.4g}" if abs(v) < 10 else f"{v:,.2f}"


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def md_inline(text: Optional[str]) -> Markup:
    """Escape text, then turn **bold** into <strong>."""
    if not text:
        return Markup("")
    return Markup(_BOLD.sub(r"<strong>\1</strong>", str(escape(text))))


def safe_url(url: Optional[str]) -> Optional[str]:
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        return url
    return None


def sign_class(v: Optional[float]) -> str:
    if v is None:
        return "muted"
    return "pos" if v > 0 else ("neg" if v < 0 else "")


def score_class(v: Optional[float]) -> str:
    if v is None:
        return "na"
    return "good" if v >= 65 else ("mid" if v >= 45 else "bad")


def _chart_json(report: StockReport) -> Markup:
    """Plotly traces as JSON, safe for embedding inside a <script> element."""
    traces = []
    for label, series in report.price_history.items():
        if not series:
            continue
        items = sorted(series.items())
        traces.append({"type": "scatter", "mode": "lines", "name": str(label),
                       "x": [d for d, _ in items], "y": [v for _, v in items],
                       "line": {"width": 2.5 if label == report.profile.ticker else 1.6}})
    raw = json.dumps(traces, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(raw)


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(pct=fmt_pct, mult=fmt_mult, ratio=fmt_ratio, price=fmt_price, money=fmt_money,
                       num=fmt_num, md=md_inline, safe_url=safe_url, sign=sign_class, scorecls=score_class)
    env.globals.update(fmt_value=fmt_value)
    return env


def render_html(report: StockReport) -> str:
    v = report.verification
    verification = None
    if v is not None:
        counts = v.counts
        evaluated = counts["PASS"] + counts["WARN"] + counts["FAIL"]
        verification = {"checks": v.checks, "counts": counts, "evaluated": evaluated,
                        "pass_rate": v.pass_rate,
                        "badge": "good" if (v.pass_rate or 0) >= 0.9 else ("mid" if (v.pass_rate or 0) >= 0.7 else "bad")}
    m = report.metrics
    metric_rows = [{"label": label, "value": fmt_value(getattr(m, key), kind),
                    "source": m.sources.get(key)} for label, key, kind in METRIC_ROWS]
    headlines = []
    for h in report.sentiment.headlines:
        if not isinstance(h, dict):
            continue
        headlines.append({"title": str(h.get("title") or ""), "publisher": h.get("publisher"),
                          "date": h.get("date"), "score": h.get("score"), "url": safe_url(h.get("url"))})
    tpl = _env().get_template("report.html.j2")
    return tpl.render(r=report, a=report.analysis, s=report.score, fv=report.score.fair_value,
                      b=report.benchmark, sent=report.sentiment, p=report.profile, m=m,
                      metric_rows=metric_rows, headlines=headlines, verification=verification,
                      chart_json=_chart_json(report), has_chart=bool(report.price_history),
                      plotly_cdn=PLOTLY_CDN, disclaimer=DISCLAIMER)


def write_html(report: StockReport, out_dir: Union[str, Path]) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report.profile.ticker}_{report.as_of.isoformat()}.html"
    path.write_text(render_html(report), encoding="utf-8")
    return path

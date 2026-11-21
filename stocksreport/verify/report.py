"""Standalone reconciliation report (console, Excel, HTML) for `cli.py verify`."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from stocksreport.models import VerificationResult

FILL = {"PASS": "C6EFCE", "WARN": "FFEB9C", "FAIL": "FFC7CE", "SKIP": "EDEDED"}
COLS = ["Ticker", "Status", "Category", "Field", "Period", "Pipeline value", "Source value", "Diff %", "Source",
        "Note"]


def _rows(results: list[VerificationResult]):
    for r in results:
        for c in r.checks:
            yield [r.ticker, c.status, c.category, c.field, c.period, c.pipeline_value, c.source_value,
                   c.diff_pct, c.source, c.note]


def console(results: list[VerificationResult]) -> str:
    lines = []
    for r in results:
        k = r.counts
        rate = f"{r.pass_rate:.0%}" if r.pass_rate is not None else "n/a"
        lines.append(f"\n{r.ticker}: {k['PASS']} PASS, {k['WARN']} WARN, {k['FAIL']} FAIL, {k['SKIP']} SKIP "
                     f"(pass rate {rate})")
        for c in r.checks:
            if c.status != "PASS":
                d = "" if c.diff_pct is None else f"{c.diff_pct:+.2f}%"
                lines.append(f"  {c.status:4} {c.category:20} {c.field:30} {c.period or '':24} {d:>9}  {c.note or ''}")
    return "\n".join(lines)


def write_xlsx(results: list[VerificationResult], path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Ticker", "PASS", "WARN", "FAIL", "SKIP", "Pass rate"])
    for r in results:
        k = r.counts
        ws.append([r.ticker, k["PASS"], k["WARN"], k["FAIL"], k["SKIP"], r.pass_rate])
        ws.cell(ws.max_row, 6).number_format = "0%"
    d = wb.create_sheet("Checks")
    d.append(COLS)
    for row in _rows(results):
        d.append(row)
        d.cell(d.max_row, 2).fill = PatternFill("solid", fgColor=FILL[row[1]])
        d.cell(d.max_row, 8).number_format = '0.00"%"'
        for col in (6, 7):
            d.cell(d.max_row, col).number_format = "#,##0.00"
    for sheet in (ws, d):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHIJ", (8, 7, 20, 32, 26, 20, 20, 10, 20, 70)):
        d.column_dimensions[col].width = w
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def write_html(results: list[VerificationResult], path: Path) -> Path:
    def fmt(v):
        return "" if v is None else (f"{v:,.4f}" if abs(v) < 100 else f"{v:,.0f}")

    summary = "".join(
        f"<tr><td>{html.escape(r.ticker)}</td><td>{r.counts['PASS']}</td><td>{r.counts['WARN']}</td>"
        f"<td>{r.counts['FAIL']}</td><td>{r.counts['SKIP']}</td>"
        f"<td>{'' if r.pass_rate is None else f'{r.pass_rate:.0%}'}</td></tr>" for r in results)
    body = "".join(
        f"<tr class='{row[1]}'>" + "".join(
            f"<td>{html.escape(fmt(v) if isinstance(v, float) else str(v or ''))}</td>" for v in row) + "</tr>"
        for row in _rows(results))
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Verification</title><style>
:root{{--bg:#fff;--fg:#1d2433;--muted:#667085;--line:#e4e7ec;--pass:#d1fadf;--warn:#fef0c7;--fail:#fee4e2;--skip:#f2f4f7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1419;--fg:#e6e9ef;--muted:#98a2b3;--line:#2a313c;--pass:#0b3d24;--warn:#4a3a0a;--fail:#55160c;--skip:#1d2430}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}}
h1{{font-size:22px}} p{{color:var(--muted);max-width:900px}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;margin:12px 0 24px;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
tr.PASS td:nth-child(2){{background:var(--pass)}} tr.WARN td:nth-child(2){{background:var(--warn)}}
tr.FAIL td:nth-child(2){{background:var(--fail)}} tr.SKIP td:nth-child(2){{background:var(--skip)}}
</style></head><body><h1>Data verification — {date.today():%Y-%m-%d}</h1>
<p>Values retrieved by the pipeline (Yahoo Finance via yfinance) reconciled against SEC EDGAR XBRL filings,
Nasdaq end-of-day prices, Yahoo's own pre-computed ratios and accounting identities.
PASS ≤ 0.5% difference (EPS to the cent), WARN ≤ 2%, FAIL above. Derived ratios use wider bands because
definitions differ between vendors.</p>
<div class="wrap"><table><tr><th>Ticker</th><th>PASS</th><th>WARN</th><th>FAIL</th><th>SKIP</th><th>Pass rate</th></tr>{summary}</table></div>
<div class="wrap"><table><tr>{''.join(f'<th>{c}</th>' for c in COLS)}</tr>{body}</table></div></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path

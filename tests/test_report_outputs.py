"""Tests for the Excel and PowerPoint report writers."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pptx import Presentation

from stocksreport import DISCLAIMER
from stocksreport.models import StockReport, VerificationCheck, VerificationResult
from stocksreport.report.excel import to_xlsx_bytes, write_xlsx
from stocksreport.report.pptx import to_pptx_bytes, write_pptx

FIX = Path(__file__).parent / "fixtures"


def _load(t: str) -> StockReport:
    return StockReport.model_validate_json((FIX / f"{t}_report.json").read_text())


@pytest.fixture(scope="module")
def aapl_r():
    return _load("AAPL")


@pytest.fixture(scope="module")
def jpm_r():
    return _load("JPM")


def _with_verification(r: StockReport) -> StockReport:
    v = VerificationResult(ticker=r.profile.ticker, checks=[
        VerificationCheck(category="income", field="revenue", period="FY2025",
                          pipeline_value=100.0, source_value=100.0, source="SEC EDGAR",
                          diff_pct=0.0, status="PASS"),
        VerificationCheck(category="income", field="net_income", period="FY2025",
                          pipeline_value=100.0, source_value=103.0, source="SEC EDGAR",
                          diff_pct=0.03, status="WARN", note="small diff"),
        VerificationCheck(category="price", field="close", period="2026-11-20",
                          pipeline_value=10.0, source_value=12.0, source="Nasdaq",
                          diff_pct=0.2, status="FAIL", note="price mismatch"),
        VerificationCheck(category="balance", field="equity", source="SEC EDGAR",
                          status="SKIP", note="not reported"),
    ])
    return r.model_copy(update={"verification": v})


def _all_xlsx_values(wb):
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            out.extend(v for v in row if v is not None)
    return out


# ---------------------------------------------------------------- Excel

def test_xlsx_single_report_no_comparison(aapl_r):
    wb = load_workbook(io.BytesIO(to_xlsx_bytes([aapl_r])))
    assert "Comparison" not in wb.sheetnames
    for suffix in ("Summary", "Metrics", "Benchmark", "Pros-Cons", "Verification"):
        assert f"AAPL {suffix}" in wb.sheetnames
    assert all(len(n) <= 31 for n in wb.sheetnames)


def test_xlsx_multi_report_comparison(aapl_r, jpm_r):
    wb = load_workbook(io.BytesIO(to_xlsx_bytes([aapl_r, jpm_r])))
    assert wb.sheetnames[0] == "Comparison"
    ws = wb["Comparison"]
    headers = [c.value for c in ws[1]]
    tickers = [ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)]
    assert "AAPL" in tickers and "JPM" in tickers
    # numeric cells with % formats
    col = headers.index("Net margin") + 1
    cell = ws.cell(row=2, column=col)
    assert isinstance(cell.value, float)
    assert "%" in cell.number_format
    assert abs(cell.value - aapl_r.metrics.net_margin) < 1e-9
    price_cell = ws.cell(row=2, column=headers.index("Price") + 1)
    assert isinstance(price_cell.value, float) and "$" in price_cell.number_format
    assert ws.freeze_panes == "B2"
    assert "JPM Summary" in wb.sheetnames


def test_xlsx_content(aapl_r, jpm_r):
    wb = load_workbook(io.BytesIO(to_xlsx_bytes([aapl_r, jpm_r])))
    vals = _all_xlsx_values(wb)
    text = "\n".join(str(v) for v in vals)
    assert DISCLAIMER in text
    for r in (aapl_r, jpm_r):
        assert r.analysis.verdict in text
        for p in r.analysis.pros + r.analysis.cons:
            assert p.text in text
            assert p.evidence in text
    # metrics sheet: numeric with formats
    ws = wb["AAPL Metrics"]
    found = False
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "Net margin":
            assert isinstance(row[1].value, float)
            assert "%" in row[1].number_format
            found = True
    assert found
    assert wb["AAPL Benchmark"]._charts, "price history chart expected"
    assert "Peer median" in text
    assert "not run" in "\n".join(str(v) for row in wb["AAPL Verification"].iter_rows(values_only=True) for v in row if v)


def test_xlsx_verification_populated(aapl_r, tmp_path):
    r = _with_verification(aapl_r)
    p = write_xlsx([r], tmp_path / "out.xlsx")
    assert p.exists()
    wb = load_workbook(p)
    ws = wb["AAPL Verification"]
    fills = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value in ("PASS", "WARN", "FAIL"):
                fills[c.value] = c.fill.fgColor.rgb
    assert set(fills) == {"PASS", "WARN", "FAIL"}
    assert len(set(fills.values())) == 3
    text = "\n".join(str(v) for row in ws.iter_rows(values_only=True) for v in row if v is not None)
    assert "price mismatch" in text


# ---------------------------------------------------------------- PPTX

def _pptx_text(prs):
    parts = []
    for slide in prs.slides:
        for shp in slide.shapes:
            if shp.has_text_frame:
                parts.append(shp.text_frame.text)
            if getattr(shp, "has_table", False) and shp.has_table:
                for row in shp.table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
        if slide.has_notes_slide:
            parts.append(slide.notes_slide.notes_text_frame.text)
    return "\n".join(parts)


@pytest.mark.parametrize("t", ["AAPL", "JPM"])
def test_pptx_roundtrip(t):
    r = _load(t)
    prs = Presentation(io.BytesIO(to_pptx_bytes(r)))
    assert abs(prs.slide_width / prs.slide_height - 16 / 9) < 0.01
    assert 8 <= len(prs.slides) <= 12
    text = _pptx_text(prs)
    assert r.analysis.verdict in text
    assert r.profile.ticker in text
    for p in r.analysis.pros:
        assert p.text in text
    assert DISCLAIMER in text
    # the last slide carries the disclaimer
    last = prs.slides[-1]
    assert any(s.has_text_frame and DISCLAIMER in s.text_frame.text for s in last.shapes)
    assert "not run" in text.lower()
    # pictures (charts) present
    n_pics = sum(1 for s in prs.slides for shp in s.shapes if shp.shape_type == 13)
    assert n_pics >= 2


def test_pptx_verification_populated(aapl_r, tmp_path):
    r = _with_verification(aapl_r)
    p = write_pptx(r, tmp_path / "out.pptx")
    prs = Presentation(p)
    text = _pptx_text(prs)
    assert "price mismatch" in text
    assert "33%" in text  # 1 pass of 3 evaluated


def test_pptx_shapes_within_slide(aapl_r):
    prs = Presentation(io.BytesIO(to_pptx_bytes(_with_verification(aapl_r))))
    W, H = prs.slide_width, prs.slide_height
    for slide in prs.slides:
        for shp in slide.shapes:
            assert shp.left >= 0 and shp.top >= 0
            assert shp.left + shp.width <= W + 1
            assert shp.top + shp.height <= H + 1


# ---------------------------------------------------------------- data corrections

CORR = "Revenue growth YoY: SEC 10-K value 7.3% replaced yfinance 12.0%"


@pytest.mark.parametrize("verified", [False, True])
def test_corrections_in_xlsx(jpm_r, verified):
    r = _with_verification(jpm_r) if verified else jpm_r
    r = r.model_copy(update={"data_corrections": [CORR]})
    wb = load_workbook(io.BytesIO(to_xlsx_bytes([r])))
    text = "\n".join(str(v) for row in wb["JPM Verification"].iter_rows(values_only=True)
                     for v in row if v is not None)
    assert "Corrections applied" in text and CORR in text


def test_no_corrections_heading_when_empty(jpm_r):
    wb = load_workbook(io.BytesIO(to_xlsx_bytes([jpm_r])))
    text = "\n".join(str(v) for row in wb["JPM Verification"].iter_rows(values_only=True)
                     for v in row if v is not None)
    assert "Corrections applied" not in text


@pytest.mark.parametrize("verified", [False, True])
def test_corrections_in_pptx(jpm_r, verified):
    r = _with_verification(jpm_r) if verified else jpm_r
    r = r.model_copy(update={"data_corrections": [CORR]})
    text = _pptx_text(Presentation(io.BytesIO(to_pptx_bytes(r))))
    assert "Corrections applied" in text and CORR in text

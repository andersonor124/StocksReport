from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402

from stocksreport import DISCLAIMER, pipeline  # noqa: E402
from stocksreport.data import lookup  # noqa: E402
from stocksreport.models import StockReport  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"


def _fake_analyze(ticker, peers=None, use_cache=True, verify=True):
    t = ticker.upper()
    if t not in ("AAPL", "JPM"):
        raise ValueError(f"unknown ticker {t}")
    r = StockReport.model_validate_json((FIX / f"{t}_report.json").read_text())
    if t == "JPM":
        r.data_corrections = ["Revenue growth replaced with SEC value"]
    return r


LOOKUP = {
    "aapl": [lookup.Match("AAPL", "Apple Inc.", "NMS")],
    "apple": [lookup.Match("AAPL", "Apple Inc.", "NMS"), lookup.Match("APLE", "Apple Hospitality REIT, Inc.", "NYQ")],
    "jpm": [lookup.Match("JPM", "JPMorgan Chase & Co.", "NYQ")],
    "jp morgan": [lookup.Match("JPM", "JPMorgan Chase & Co.", "NYQ")],
    "berkshire": [lookup.Match("BRK-B", "Berkshire Hathaway Inc. New", "NYQ"),
                  lookup.Match("BRK-A", "Berkshire Hathaway Inc.", "NYQ")],
}


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    monkeypatch.setattr(pipeline, "analyze", _fake_analyze)
    monkeypatch.setattr(lookup, "resolve", lambda q, **kw: LOOKUP.get(q.strip().lower(), []))
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _run(tickers, click=True):
    at = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(tickers)
    at.run()
    if click:
        at.sidebar.button[0].click()
        at.run()
    return at


def _all_text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader]
    parts += [h.value for h in at.header] + [i.value for i in at.info] + [w.value for w in at.warning]
    return "\n".join(parts)


def test_initial_render_has_disclaimer():
    at = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert DISCLAIMER in _all_text(at)


def test_single_ticker():
    at = _run("aapl")
    assert not at.exception, at.exception
    assert len(at.tabs) == 6
    assert not at.error, [e.value for e in at.error]
    labels = [t.label for t in at.tabs]
    assert labels == ["Overview", "Metrics & Benchmark", "Pros/Cons", "Investor Views",
                      "Verdict & Fair Value", "Data Verification"]
    text = _all_text(at)
    assert "Apple Inc." in text
    assert "not run" in text.lower()
    assert DISCLAIMER in text


def test_input_box_asks_for_company_with_no_default():
    at = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    box = at.sidebar.text_input[0]
    assert box.label == "Company name or ticker" and box.value in ("", None)


def test_company_name_is_resolved():
    at = _run("apple")
    assert not at.exception, at.exception
    assert at.header[0].value.startswith("Apple Inc. (AAPL)")
    assert "'apple' → AAPL" in _all_text(at)


def test_ambiguous_name_offers_a_choice():
    at = _run("berkshire", click=False)
    sb = at.sidebar.selectbox[0]
    assert "berkshire" in sb.label and len(sb.options) == 2


def test_multi_ticker_comparison():
    at = _run("AAPL, jp morgan, ZZZZ")
    assert not at.exception, at.exception
    df = at.dataframe[0].value
    assert list(df["Ticker"]) == ["AAPL", "JPM"]
    assert {"Price", "Score", "Verdict", "Fwd P/E", "Net margin", "1Y vs SPY",
            "FV upside", "Verified"} <= set(df.columns)
    assert len(at.expander) >= 2
    assert not at.error, [e.value for e in at.error]
    assert any("No company found for 'ZZZZ'" in w.value for w in at.sidebar.warning)
    assert "Corrections applied" in _all_text(at)

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402

from stocksreport import DISCLAIMER, pipeline  # noqa: E402
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


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    monkeypatch.setattr(pipeline, "analyze", _fake_analyze)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _run(tickers):
    at = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(tickers)
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


def test_multi_ticker_comparison():
    at = _run("AAPL, JPM, ZZZZ")
    assert not at.exception, at.exception
    df = at.dataframe[0].value
    assert list(df["Ticker"]) == ["AAPL", "JPM"]
    assert {"Price", "Score", "Verdict", "Fwd P/E", "Net margin", "1Y vs SPY",
            "FV upside", "Verified"} <= set(df.columns)
    assert len(at.expander) >= 2
    assert [e.value for e in at.error if "ZZZZ" not in e.value] == []
    assert any("ZZZZ" in e.value for e in at.error)
    assert "Corrections applied" in _all_text(at)

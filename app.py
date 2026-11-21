"""StocksReport Streamlit front-end.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import html as _html
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stocksreport import DISCLAIMER, pipeline
from stocksreport.models import StockReport
from stocksreport.report.html import (METRIC_ROWS, fmt_money, fmt_mult, fmt_pct, fmt_price,
                                      fmt_num, fmt_value, render_html)

st.set_page_config(page_title="StocksReport", page_icon="📈", layout="wide")

VERDICT_COLORS = {"Buy": "#1e8e4e", "Hold": "#c98a06", "Sell": "#c8372d"}
STATUS_COLORS = {"PASS": "#1e8e4e33", "WARN": "#e0a52633", "FAIL": "#c8372d33", "SKIP": ""}


# --------------------------------------------------------------------------- helpers
def md(text: Optional[str]) -> str:
    """Make untrusted/plain text safe for st.markdown: no LaTeX ($), no raw HTML."""
    if not text:
        return ""
    return _html.escape(str(text), quote=False).replace("$", "\\$")


def parse_list(raw: str) -> list[str]:
    seen, out = set(), []
    for t in (raw or "").replace(";", ",").replace(" ", ",").split(","):
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def analyze_cached(ticker: str, peers: tuple[str, ...], verify: bool) -> dict:
    report = pipeline.analyze(ticker, peers=list(peers) or None, verify=verify)
    return report.model_dump(mode="json")


def ret_vs_market(r: StockReport, period: str = "1Y") -> Optional[float]:
    for row in r.benchmark.returns:
        if row.period == period and row.stock is not None and row.market is not None:
            return row.stock - row.market
    return None


def verification_label(r: StockReport) -> str:
    v = r.verification
    if v is None:
        return "not run"
    c = v.counts
    return f"{c['PASS']}/{c['PASS'] + c['WARN'] + c['FAIL']}"


def verdict_badge(verdict: str, total: float, confidence: str) -> None:
    color = VERDICT_COLORS.get(verdict, "#666")
    st.markdown(
        f'<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">'
        f'<span style="background:{color};color:#fff;padding:8px 20px;border-radius:10px;'
        f'font-size:1.5rem;font-weight:800">{_html.escape(verdict)}</span>'
        f'<span style="font-size:1.6rem;font-weight:800">{total:.0f}<span style="font-size:.9rem;'
        f'opacity:.7">/100</span></span><span style="opacity:.8">Confidence: '
        f'<b>{_html.escape(confidence)}</b></span></div>',
        unsafe_allow_html=True)


def price_chart(r: StockReport) -> Optional[go.Figure]:
    if not r.price_history:
        return None
    fig = go.Figure()
    for label, series in r.price_history.items():
        items = sorted(series.items())
        fig.add_trace(go.Scatter(x=[d for d, _ in items], y=[v for _, v in items], mode="lines", name=label,
                                 line={"width": 2.5 if label == r.profile.ticker else 1.5}))
    fig.add_hline(y=100, line_dash="dot", line_width=1, opacity=0.5)
    fig.update_layout(height=360, margin={"l": 10, "r": 10, "t": 30, "b": 10}, hovermode="x unified",
                      legend={"orientation": "h", "y": 1.1}, yaxis_title="Rebased to 100")
    return fig


def metrics_df(r: StockReport) -> pd.DataFrame:
    m = r.metrics
    return pd.DataFrame([{"Metric": label, "Value": fmt_value(getattr(m, key), kind),
                          "Source": m.sources.get(key, "")} for label, key, kind in METRIC_ROWS])


def returns_df(r: StockReport) -> pd.DataFrame:
    b = r.benchmark
    rows = []
    for row in b.returns:
        d = {"Period": row.period, r.profile.ticker: fmt_pct(row.stock, 1, True),
             b.market_ticker: fmt_pct(row.market, 1, True)}
        if b.sector_ticker:
            d[b.sector_ticker] = fmt_pct(row.sector, 1, True)
        rel = row.stock - row.market if row.stock is not None and row.market is not None else None
        d[f"vs {b.market_ticker}"] = fmt_pct(rel, 1, True)
        rows.append(d)
    return pd.DataFrame(rows)


def peers_df(r: StockReport) -> pd.DataFrame:
    m = r.metrics

    def row(t, name, cap, pe, fpe, ps, nm, roe, g):
        return {"Ticker": t, "Name": name or "", "Mkt cap": fmt_money(cap), "P/E": fmt_mult(pe),
                "Fwd P/E": fmt_mult(fpe), "P/S": fmt_mult(ps), "Net margin": fmt_pct(nm),
                "ROE": fmt_pct(roe), "Rev growth": fmt_pct(g)}

    rows = [row(r.profile.ticker, r.profile.name, m.market_cap, m.pe_ttm, m.forward_pe, m.price_to_sales,
                m.net_margin, m.roe, m.revenue_growth_yoy)]
    for p in r.benchmark.peers + [r.benchmark.peer_median]:
        rows.append(row(p.ticker, p.name, p.market_cap, p.pe_ttm, p.forward_pe, p.price_to_sales,
                        p.net_margin, p.roe, p.revenue_growth_yoy))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- downloads
def download_buttons(r: StockReport, key: str) -> None:
    cols = st.columns(2)
    with cols[0]:
        try:
            st.download_button("Download HTML report", render_html(r).encode("utf-8"),
                               file_name=f"{r.profile.ticker}_{r.as_of.isoformat()}.html",
                               mime="text/html", key=f"html-{key}", width="stretch")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"HTML export unavailable: {exc}")
    with cols[1]:
        try:
            from stocksreport.report.pptx import to_pptx_bytes
            st.download_button("Download PowerPoint", to_pptx_bytes(r),
                               file_name=f"{r.profile.ticker}_{r.as_of.isoformat()}.pptx",
                               mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                               key=f"pptx-{key}", width="stretch")
        except Exception as exc:  # noqa: BLE001 - module may be missing or still in progress
            st.caption(f"PowerPoint export unavailable ({type(exc).__name__}).")


def excel_button(reports: list[StockReport]) -> None:
    try:
        from stocksreport.report.excel import to_xlsx_bytes
        name = ("_".join(r.profile.ticker for r in reports[:5])) + f"_{reports[0].as_of.isoformat()}.xlsx"
        st.download_button("Download Excel workbook", to_xlsx_bytes(reports), file_name=name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="xlsx-all", width="stretch")
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Excel export unavailable ({type(exc).__name__}).")


# --------------------------------------------------------------------------- sections
def section_overview(r: StockReport) -> None:
    p, m = r.profile, r.metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", fmt_price(m.price), fmt_pct(m.pct_from_52w_high, 1, True) + " vs 52w high"
              if m.pct_from_52w_high is not None else None, delta_color="off")
    c2.metric("Market cap", fmt_money(m.market_cap))
    c3.metric("Score", f"{r.score.total:.0f}/100")
    c4.metric("Fair value upside", fmt_pct(r.score.fair_value.upside_pct, 1, True))
    verdict_badge(r.analysis.verdict, r.score.total, r.analysis.confidence)
    st.markdown(md(r.analysis.summary))
    chips = " · ".join(x for x in (p.sector, p.industry, p.exchange, p.country) if x)
    if chips:
        st.caption(md(chips))
    st.subheader("Company overview")
    st.markdown(md(p.summary) or "_No business description available._")
    fig = price_chart(r)
    if fig is not None:
        st.subheader("Price, 1 year (rebased to 100)")
        st.plotly_chart(fig, width="stretch", key=f"chart-ov-{p.ticker}")


def section_metrics(r: StockReport) -> None:
    st.subheader("Key metrics")
    st.dataframe(metrics_df(r), hide_index=True, width="stretch")
    st.caption("Source: computed = recomputed from statements/prices · yfinance = Yahoo Finance · "
               "annual = latest fiscal year · SEC = SEC EDGAR filing value")
    st.subheader(f"Returns vs {r.benchmark.market_ticker}"
                 + (f" and {r.benchmark.sector_ticker}" if r.benchmark.sector_ticker else ""))
    st.dataframe(returns_df(r), hide_index=True, width="stretch")
    fig = price_chart(r)
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key=f"chart-mb-{r.profile.ticker}")
    st.subheader("Peers")
    st.dataframe(peers_df(r), hide_index=True, width="stretch")


def section_pros_cons(r: StockReport) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Pros")
        for pt in r.analysis.pros:
            st.markdown(f"**+ {md(pt.text)}**  \n<small>{md(pt.evidence)}</small>", unsafe_allow_html=True)
        if not r.analysis.pros:
            st.caption("None identified.")
    with c2:
        st.subheader("Cons")
        for pt in r.analysis.cons:
            st.markdown(f"**− {md(pt.text)}**  \n<small>{md(pt.evidence)}</small>", unsafe_allow_html=True)
        if not r.analysis.cons:
            st.caption("None identified.")


def section_views(r: StockReport) -> None:
    a, s = r.analysis, r.sentiment
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Retail investor view")
        st.markdown(md(a.retail_investor_view))
        st.subheader("Key risks")
        st.markdown("\n".join(f"- {md(x)}" for x in a.key_risks) or "_None listed._")
    with c2:
        st.subheader("Portfolio manager view")
        st.markdown(md(a.portfolio_manager_view))
        st.subheader("Catalysts")
        st.markdown("\n".join(f"- {md(x)}" for x in a.catalysts) or "_None listed._")
    st.subheader("Recent analyst actions")
    if s.analyst_counts:
        st.caption(md(" · ".join(f"{k}: {v}" for k, v in s.analyst_counts.items())
                      + f" · {s.upgrades_90d} upgrades / {s.downgrades_90d} downgrades (90d)"))
    st.markdown("\n".join(f"- {md(x)}" for x in s.recent_actions) or "_No recent actions._")
    st.subheader("News headlines")
    if s.news_score is not None:
        st.caption(f"Average sentiment {s.news_score:+.2f} ({md(s.news_label or '')}), VADER scale -1 to +1")
    if s.headlines:
        df = pd.DataFrame([{"Score": h.get("score"), "Headline": h.get("title"), "Publisher": h.get("publisher"),
                            "Date": h.get("date"),
                            "Link": h.get("url") if str(h.get("url") or "").startswith(("http://", "https://")) else None}
                           for h in s.headlines if isinstance(h, dict)])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="open"),
                                    "Score": st.column_config.NumberColumn(format="%+.2f")})
    else:
        st.caption("No headlines.")


def section_verdict(r: StockReport) -> None:
    sc, fv, a = r.score, r.score.fair_value, r.analysis
    verdict_badge(a.verdict, sc.total, a.confidence)
    st.caption("Thresholds: Buy ≥ 65, Sell < 45")
    st.markdown(md(a.rationale))
    names = [p.name for p in sc.pillars]
    vals = [p.score if p.score is not None else 0 for p in sc.pillars]
    colors = ["#1e8e4e" if v >= 65 else "#c98a06" if v >= 45 else "#c8372d" for v in vals]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h", marker_color=colors,
                           text=[f"{v:.0f}" if p.score is not None else "n/a" for v, p in zip(vals, sc.pillars)],
                           textposition="outside"))
    fig.update_layout(height=60 + 40 * len(names), margin={"l": 10, "r": 30, "t": 10, "b": 10},
                      xaxis={"range": [0, 105]}, yaxis={"autorange": "reversed"})
    st.plotly_chart(fig, width="stretch", key=f"pillars-{r.profile.ticker}")
    for p in sc.pillars:
        with st.expander(f"{p.name}: {p.score:.0f}/100 (weight {p.weight:.0%})" if p.score is not None
                         else f"{p.name}: n/a (weight {p.weight:.0%})"):
            st.markdown("\n".join(f"- {md(n)}" for n in p.notes) or "_No notes._")
    st.subheader("Fair value")
    cols = st.columns(4)
    cols[0].metric("Analyst low", fmt_price(fv.analyst_low))
    cols[1].metric("Analyst mean", fmt_price(fv.analyst_mean))
    cols[2].metric("Analyst high", fmt_price(fv.analyst_high))
    cols[3].metric("Peer-multiple value", fmt_price(fv.peer_multiple_value))
    cols = st.columns(4)
    cols[0].metric("Price", fmt_price(r.metrics.price))
    cols[1].metric("Blended fair value", fmt_price(fv.blended))
    cols[2].metric("Upside", fmt_pct(fv.upside_pct, 1, True))
    if a.entry_price_suggestion:
        st.info(md(a.entry_price_suggestion))


def section_verification(r: StockReport) -> None:
    if r.data_corrections:
        st.warning("**Corrections applied** (SEC-filed values replaced Yahoo Finance data):\n"
                   + "\n".join(f"- {md(c)}" for c in r.data_corrections))
    v = r.verification
    if v is None:
        st.info("Data verification not run for this report (enable “Verify data against SEC/Nasdaq”).")
        return
    c = v.counts
    evaluated = c["PASS"] + c["WARN"] + c["FAIL"]
    msg = f"Data verified: {c['PASS']}/{evaluated} checks passed · {c['WARN']} warn · {c['FAIL']} fail · {c['SKIP']} skipped"
    rate = v.pass_rate or 0
    (st.success if rate >= 0.9 else st.warning if rate >= 0.7 else st.error)(msg)
    if v.checks:
        df = pd.DataFrame([{"Status": ch.status, "Category": ch.category, "Field": ch.field,
                            "Period": ch.period or "", "Pipeline": fmt_num(ch.pipeline_value), "Source value": fmt_num(ch.source_value),
                            "Source": ch.source, "Diff %": ch.diff_pct,  # already in percent units
                            "Note": ch.note or ""} for ch in v.checks])
        styled = df.style.apply(lambda row: [f"background-color: {STATUS_COLORS.get(row['Status'], '')}"] * len(row),
                                axis=1).format({"Diff %": "{:+.2f}%"},
                                               na_rep="—")
        st.dataframe(styled, hide_index=True, width="stretch")


def render_single(r: StockReport, key: str) -> None:
    tabs = st.tabs(["Overview", "Metrics & Benchmark", "Pros/Cons", "Investor Views",
                    "Verdict & Fair Value", "Data Verification"])
    for tab, fn in zip(tabs, (section_overview, section_metrics, section_pros_cons, section_views,
                              section_verdict, section_verification)):
        with tab:
            try:
                fn(r)
            except Exception as exc:  # noqa: BLE001 - one broken section must not kill the page
                st.error(f"Could not render this section: {exc}")
    download_buttons(r, key)


def comparison_df(reports: list[StockReport]) -> pd.DataFrame:
    rows = []
    for r in reports:
        rows.append({"Ticker": r.profile.ticker, "Name": r.profile.name, "Price": fmt_price(r.metrics.price),
                     "Score": round(r.score.total, 1), "Verdict": r.analysis.verdict,
                     "Fwd P/E": fmt_mult(r.metrics.forward_pe), "Net margin": fmt_pct(r.metrics.net_margin),
                     "1Y vs SPY": fmt_pct(ret_vs_market(r), 1, True),
                     "FV upside": fmt_pct(r.score.fair_value.upside_pct, 1, True),
                     "Verified": verification_label(r)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- page
st.title("StocksReport")
st.caption("Free, rule-based stock analysis from public data (Yahoo Finance, SEC EDGAR, Nasdaq).")

with st.sidebar:
    st.header("Analyze")
    tickers_raw = st.text_input("Ticker(s)", placeholder="AAPL, MSFT, JPM",
                                help="One or more symbols, separated by commas.")
    peers_raw = st.text_input("Peers override (optional)", placeholder="MSFT, GOOGL",
                              help="Comma-separated peer tickers used for the peer comparison.")
    verify = st.checkbox("Verify data against SEC/Nasdaq", value=True)
    go_clicked = st.button("Analyze", type="primary", width="stretch")
    st.caption(DISCLAIMER)

if go_clicked:
    tickers, peers = parse_list(tickers_raw), tuple(parse_list(peers_raw))
    if not tickers:
        st.session_state.pop("results", None)
        st.warning("Enter at least one ticker.")
    else:
        results, errors = [], []
        progress = st.progress(0.0, text="Starting…")
        for i, t in enumerate(tickers):
            progress.progress(i / len(tickers), text=f"Analyzing {t} ({i + 1}/{len(tickers)}) — live data, may take a minute…")
            try:
                results.append(analyze_cached(t, peers, verify))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{t}: {exc}")
        progress.empty()
        st.session_state["results"] = {"reports": results, "errors": errors}

state = st.session_state.get("results")
if state:
    for e in state["errors"]:
        st.error(f"Analysis failed for {e}")
    reports = [StockReport.model_validate(d) for d in state["reports"]]
    if len(reports) == 1:
        r = reports[0]
        st.header(f"{r.profile.name} ({r.profile.ticker})")
        render_single(r, r.profile.ticker)
        excel_button(reports)
    elif reports:
        st.header("Comparison")
        df = comparison_df(reports)
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100,
                                                                              format="%.0f")})
        excel_button(reports)
        for r in reports:
            with st.expander(f"{r.profile.ticker} · {r.profile.name} · {r.analysis.verdict} "
                             f"({r.score.total:.0f}/100) · verified {verification_label(r)}"):
                render_single(r, r.profile.ticker)
elif not go_clicked:
    st.info("Enter one or more tickers in the sidebar and click **Analyze**.")

st.divider()
st.caption(f"**Disclaimer:** {DISCLAIMER}")

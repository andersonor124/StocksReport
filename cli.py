"""Command-line entry point.

    python cli.py AAPL MSFT --format html xlsx pptx --out reports/
    python cli.py verify AAPL MSFT JPM --out reports/
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from stocksreport import DISCLAIMER


def _report(args) -> int:
    from stocksreport.pipeline import analyze_many

    reports = analyze_many(args.tickers, peers=args.peers, use_cache=not args.no_cache, verify=not args.no_verify)
    if not reports:
        print("No reports produced.", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{date.today():%Y-%m-%d}"
    for r in reports:
        v = r.verification
        ver = f"{v.counts['PASS']}/{sum(v.counts.values()) - v.counts['SKIP']} checks passed" if v else "not run"
        print(f"{r.profile.ticker:6} {r.analysis.verdict:4} score {r.score.total:5.1f}  price ${r.metrics.price:,.2f}  "
              f"fair value {'n/a' if r.score.fair_value.blended is None else f'${r.score.fair_value.blended:,.2f}'}"
              f"  | data verification: {ver}")
        for note in r.data_corrections:
            print(f"       correction: {note}")
        if "html" in args.format:
            from stocksreport.report.html import write_html
            print("   ->", write_html(r, out))
        if "pptx" in args.format:
            from stocksreport.report.pptx import write_pptx
            print("   ->", write_pptx(r, out / f"{r.profile.ticker}_{stamp}.pptx"))
    if "xlsx" in args.format:
        from stocksreport.report.excel import write_xlsx
        name = reports[0].profile.ticker if len(reports) == 1 else "comparison"
        print("   ->", write_xlsx(reports, out / f"{name}_{stamp}.xlsx"))
    print(f"\n{DISCLAIMER}")
    return 0


def _verify(args) -> int:
    from stocksreport.analysis import metrics
    from stocksreport.data import fetcher
    from stocksreport.verify import reconcile
    from stocksreport.verify import report as vreport

    results = []
    for t in args.tickers:
        try:
            raw = fetcher.fetch(t, use_cache=not args.no_cache)
            results.append(reconcile.verify(raw, metrics.compute(raw)))
        except Exception as exc:  # noqa: BLE001
            print(f"{t}: failed - {exc}", file=sys.stderr)
    print(vreport.console(results))
    out = Path(args.out)
    stamp = f"{date.today():%Y-%m-%d}"
    print("\n->", vreport.write_xlsx(results, out / f"verification_{stamp}.xlsx"))
    print("->", vreport.write_html(results, out / f"verification_{stamp}.html"))
    return 1 if any(c.status == "FAIL" for r in results for c in r.checks) and args.strict else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("tickers", nargs="+", help="ticker symbols, e.g. AAPL MSFT")
    common.add_argument("--out", default="reports", help="output folder (default: reports/)")
    common.add_argument("--no-cache", action="store_true", help="ignore the 12h on-disk data cache")

    if argv and argv[0] == "verify":
        p = argparse.ArgumentParser(prog="cli.py verify", parents=[common],
                                    description="Reconcile retrieved data against SEC filings and Nasdaq prices.")
        p.add_argument("--strict", action="store_true", help="exit with code 1 if any check FAILs")
        return _verify(p.parse_args(argv[1:]))

    p = argparse.ArgumentParser(prog="cli.py", parents=[common],
                                description="Free stock analysis reports (use `cli.py verify ...` for data checks).")
    p.add_argument("--format", nargs="+", choices=["html", "xlsx", "pptx"], default=["html"])
    p.add_argument("--peers", nargs="+", help="override the sector peer list")
    p.add_argument("--no-verify", action="store_true", help="skip SEC/Nasdaq data verification")
    return _report(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

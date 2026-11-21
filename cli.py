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


FORMATS = ["html", "xlsx", "pptx"]
QUIT = {"q", "quit", "exit"}
USAGE = ('Usage: python cli.py <company or ticker> [...] [--format html xlsx pptx]\n'
         '   or: python cli.py            (asks which company to analyse)')


def _interactive_ok() -> bool:
    return sys.stdin.isatty()


def _choose(query: str, matches) -> str:
    print(f"  '{query}' matches several companies:")
    for i, m in enumerate(matches, 1):
        print(f"      {i}) {m.label()}")
    while True:
        ans = input(f"    Choose 1-{len(matches)} [1]: ").strip()
        if not ans:
            return matches[0].ticker
        if ans.isdigit() and 1 <= int(ans) <= len(matches):
            return matches[int(ans) - 1].ticker
        print("    Please type one of the numbers shown.")


def resolve_inputs(items: list[str], interactive: bool) -> list[str] | None:
    """Company names / tickers -> tickers. Returns None if something could not be found."""
    from stocksreport.data import lookup

    tickers: list[str] = []
    for item in items:
        matches = lookup.resolve(item)
        if not matches:
            print(f"  No company found for '{item}' — check the spelling or try the ticker symbol.")
            return None
        if lookup.is_confident(matches, item) or not interactive:
            pick = matches[0].ticker
            print(f"  '{item}' → {matches[0].label()}")
        else:
            pick = _choose(item, matches)
        if pick not in tickers:
            tickers.append(pick)
    return tickers


def prompt_tickers() -> list[str] | None:
    print("Which stock(s) do you want to analyse?")
    while True:
        raw = input("Enter a company name or ticker (separate several with commas, q to quit): ").strip()
        if not raw or raw.lower() in QUIT:
            return None
        from stocksreport.data import lookup
        tickers = resolve_inputs(lookup.split_input(raw), interactive=True)
        if tickers:
            return tickers
        print("  Please try again.")


def prompt_formats() -> list[str]:
    while True:
        raw = input("Which formats? html, xlsx, pptx — press Enter for all three: ").strip().lower()
        if not raw:
            return list(FORMATS)
        chosen = [w for w in raw.replace(",", " ").split() if w]
        if all(w in FORMATS for w in chosen):
            return list(dict.fromkeys(chosen))
        print("  Please type any of: html xlsx pptx (or press Enter).")


def _prepare(args, ask_formats: bool) -> int | None:
    """Fill args.tickers (and formats) from the user. Returns an exit code to stop, or None to continue."""
    if args.tickers:
        tickers = resolve_inputs(args.tickers, interactive=_interactive_ok())
        if not tickers:
            return 1
        args.tickers = tickers
        return None
    if not _interactive_ok():
        print(USAGE, file=sys.stderr)
        return 2
    tickers = prompt_tickers()
    if not tickers:
        print("Nothing to analyse — goodbye.")
        return 0
    args.tickers = tickers
    if ask_formats and args.format is None:
        args.format = prompt_formats()
    print(f"Analysing {', '.join(tickers)} ...")
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("tickers", nargs="*",
                        help="company names or ticker symbols, e.g. apple NVDA (leave out to be asked)")
    common.add_argument("--out", default="reports", help="output folder (default: reports/)")
    common.add_argument("--no-cache", action="store_true", help="ignore the 12h on-disk data cache")

    if argv and argv[0] == "verify":
        p = argparse.ArgumentParser(prog="cli.py verify", parents=[common],
                                    description="Reconcile retrieved data against SEC filings and Nasdaq prices.")
        p.add_argument("--strict", action="store_true", help="exit with code 1 if any check FAILs")
        args = p.parse_args(argv[1:])
        if (stop := _prepare(args, ask_formats=False)) is not None:
            return stop
        return _verify(args)

    p = argparse.ArgumentParser(prog="cli.py", parents=[common],
                                description="Free stock analysis reports. Run without arguments to be asked which "
                                            "company to analyse (use `cli.py verify ...` for data checks).")
    p.add_argument("--format", nargs="+", choices=FORMATS, default=None,
                   help="files to create (default: html; when asked interactively: your choice)")
    p.add_argument("--peers", nargs="+", help="override the sector peer list")
    p.add_argument("--no-verify", action="store_true", help="skip SEC/Nasdaq data verification")
    args = p.parse_args(argv)
    if (stop := _prepare(args, ask_formats=True)) is not None:
        return stop
    if args.format is None:
        args.format = ["html"]
    return _report(args)


if __name__ == "__main__":
    sys.exit(main())

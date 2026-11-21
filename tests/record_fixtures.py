"""Record live data into tests/fixtures so the test-suite runs offline.

Usage: python -m tests.record_fixtures
"""
import pickle
from pathlib import Path

from stocksreport import config
from stocksreport.data import fetcher

FIX = Path(__file__).parent / "fixtures"
CASES = {"AAPL": ["MSFT", "NVDA", "ORCL"], "JPM": ["BAC", "WFC", "GS"]}


def main():
    FIX.mkdir(exist_ok=True)
    for tkr, peers in CASES.items():
        raw = fetcher.fetch(tkr, use_cache=False)
        etf = config.SECTOR_ETF[raw.info["sector"]]
        bundle = {
            "raw": raw,
            "histories": {s: fetcher.fetch_history(s, use_cache=False) for s in ("SPY", etf)},
            "peer_infos": {p: fetcher.fetch_info(p, use_cache=False) for p in peers},
        }
        with open(FIX / f"{tkr}.pkl", "wb") as f:
            pickle.dump(bundle, f)
        print("recorded", tkr, len(raw.history), "days")



def record_verification_sources():
    """SEC companyfacts (trimmed) + Nasdaq price history for the verification tests."""
    import gzip
    import json

    from stocksreport.verify import sources

    for tkr in CASES:
        facts = sources.sec_companyfacts(tkr)
        with gzip.open(FIX / f"{tkr}_sec.json.gz", "wt") as f:
            json.dump(facts, f)
        sources.nasdaq_history(tkr).to_csv(FIX / f"{tkr}_nasdaq.csv")
        print("recorded verification sources", tkr)


if __name__ == "__main__":
    import sys
    if "--verify-only" not in sys.argv:
        main()
    record_verification_sources()

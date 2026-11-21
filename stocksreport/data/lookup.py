"""Turn what a user types (a company name or a ticker) into ticker symbols.

Search order:
1. Yahoo Finance search (free) - handles names like "apple" or "jp morgan".
2. SEC company list (free) - exact tickers and a name fallback when Yahoo search is unavailable.
Only stocks (no futures, funds or ETFs) on U.S. exchanges are returned, best match first.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

US_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "NAS", "NYS", "PNK", "OQX", "OEM"}
MAX_MATCHES = 5


@dataclass(frozen=True)
class Match:
    ticker: str
    name: str
    exchange: Optional[str] = None

    def label(self) -> str:
        return f"{self.ticker:7} {self.name}" + (f" ({self.exchange})" if self.exchange else "")


def split_input(text: str) -> list[str]:
    """'apple, jp morgan ,, NVDA' -> ['apple', 'jp morgan', 'NVDA']."""
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def _yahoo_search(query: str) -> list[dict]:
    import yfinance as yf
    return yf.Search(query, max_results=10, news_count=0).quotes or []


def _sec_list() -> list[tuple[str, str]]:
    from stocksreport.verify.sources import sec_companies
    return sec_companies()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def resolve(query: str, search: Callable[[str], list[dict]] = _yahoo_search,
            sec: Callable[[], list[tuple[str, str]]] = _sec_list) -> list[Match]:
    q = (query or "").strip()
    if not q:
        return []
    qu = q.upper().replace(".", "-")

    try:
        quotes = search(q)
    except Exception as exc:  # noqa: BLE001 - network problems fall through to the SEC list
        log.warning("Yahoo search failed for %r: %s", q, exc)
        quotes = []
    stocks = [x for x in quotes if x.get("quoteType") == "EQUITY" and x.get("symbol")]
    us = [x for x in stocks if x.get("exchange") in US_EXCHANGES]
    matches = [Match(x["symbol"].upper(), x.get("shortname") or x.get("longname") or x["symbol"], x.get("exchange"))
               for x in us][:MAX_MATCHES]

    try:
        companies = sec()
    except Exception as exc:  # noqa: BLE001
        log.warning("SEC company list unavailable: %s", exc)
        companies = []

    # Exact ticker typed -> that ticker only (any exchange, so e.g. SHOP.TO keeps working).
    exact = next((x for x in stocks if x["symbol"].upper() in (qu, q.upper())), None)
    if exact:
        return [Match(exact["symbol"].upper(), exact.get("shortname") or exact.get("longname") or exact["symbol"],
                      exact.get("exchange"))]
    sec_exact = next(((t, n) for t, n in companies if t == qu), None)
    if sec_exact:
        return [Match(sec_exact[0], sec_exact[1])]
    if matches:
        return matches

    # Fallback: fuzzy match on SEC company names.
    nq = _norm(q).replace(" ", "")
    scored = []
    for t, n in companies:
        nn = _norm(n).replace(" ", "")
        if nq and nn.startswith(nq):
            scored.append((1.0, t, n))
        else:
            r = max(difflib.SequenceMatcher(None, nq, nn[: len(nq)]).ratio(),  # tolerate small typos
                    difflib.SequenceMatcher(None, nq, nn[: len(nq) + 6]).ratio())
            if r >= 0.8:
                scored.append((r, t, n))
    scored.sort(key=lambda x: (-x[0], len(x[2])))
    return [Match(t, n) for _, t, n in scored[:MAX_MATCHES]]


def is_confident(matches: list[Match], query: str) -> bool:
    """True when the first match is clearly what the user meant (no need to ask them to choose)."""
    if not matches:
        return False
    if len(matches) == 1 or matches[0].ticker == query.strip().upper().replace(".", "-"):
        return True
    # Trust the top-ranked result when its name starts with what was typed, unless another result is the
    # same company under a different share class (e.g. Berkshire Hathaway BRK-A vs BRK-B).
    top = matches[0]
    if not _norm(top.name).startswith(_norm(query)):
        return False
    stem = _norm(top.name).split()[:2]
    return not any(_norm(m.name).split()[:2] == stem for m in matches[1:])

from stocksreport.data import lookup as L

APPLE = [
    {"symbol": "AAPL", "shortname": "Apple Inc.", "exchange": "NMS", "quoteType": "EQUITY"},
    {"symbol": "SAAPL=F", "shortname": "Apple Inc Stock Futures", "exchange": "CME", "quoteType": "FUTURE"},
    {"symbol": "APLE", "shortname": "Apple Hospitality REIT, Inc.", "exchange": "NYQ", "quoteType": "EQUITY"},
    {"symbol": "AAPL.TO", "shortname": "APPLE CDR (CAD HEDGED)", "exchange": "TOR", "quoteType": "EQUITY"},
]
BERKSHIRE = [
    {"symbol": "BRK-B", "shortname": "Berkshire Hathaway Inc. New", "exchange": "NYQ", "quoteType": "EQUITY"},
    {"symbol": "BRK-A", "shortname": "Berkshire Hathaway Inc.", "exchange": "NYQ", "quoteType": "EQUITY"},
    {"symbol": "OMAH", "shortname": "VistaShares Target 15 Berkshire", "exchange": "PCX", "quoteType": "ETF"},
]
SEC = [("AAPL", "Apple Inc."), ("MSFT", "MICROSOFT CORP"), ("JPM", "JPMORGAN CHASE & CO")]


def search_stub(table):
    return lambda q: table.get(q.lower(), [])


def test_exact_ticker_passes_through():
    m = L.resolve("aapl", search=search_stub({"aapl": APPLE}), sec=lambda: SEC)
    assert [x.ticker for x in m] == ["AAPL"] and L.is_confident(m, "aapl")


def test_known_sec_ticker_without_search_results():
    m = L.resolve("MSFT", search=search_stub({}), sec=lambda: SEC)
    assert m[0].ticker == "MSFT" and L.is_confident(m, "MSFT")


def test_name_resolves_to_us_equities_only():
    m = L.resolve("apple", search=search_stub({"apple": APPLE}), sec=lambda: SEC)
    assert [x.ticker for x in m] == ["AAPL", "APLE"]  # futures and foreign listings dropped
    assert L.is_confident(m, "apple")  # only one name starts with "apple"


def test_ambiguous_name_is_not_confident():
    m = L.resolve("berkshire", search=search_stub({"berkshire": BERKSHIRE}), sec=lambda: SEC)
    assert [x.ticker for x in m] == ["BRK-B", "BRK-A"]
    assert not L.is_confident(m, "berkshire")


def test_unknown_returns_empty():
    assert L.resolve("xyzzyqq", search=search_stub({}), sec=lambda: SEC) == []


def test_search_failure_falls_back_to_sec_titles():
    def boom(q):
        raise ConnectionError("offline")
    m = L.resolve("jpmorgan", search=boom, sec=lambda: SEC)
    assert m and m[0].ticker == "JPM"


def test_split_input():
    assert L.split_input(" apple, jp morgan ,, NVDA ") == ["apple", "jp morgan", "NVDA"]


def test_exact_non_us_ticker_still_works():
    shop = [{"symbol": "SHOP.TO", "shortname": "Shopify Inc.", "exchange": "TOR", "quoteType": "EQUITY"}]
    m = L.resolve("SHOP.TO", search=search_stub({"shop.to": shop}), sec=lambda: SEC)
    assert [x.ticker for x in m] == ["SHOP.TO"]


def test_small_typo_matches_sec_name():
    m = L.resolve("microsfot", search=search_stub({}), sec=lambda: SEC)
    assert m and m[0].ticker == "MSFT"

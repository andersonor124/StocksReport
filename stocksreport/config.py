"""Static configuration: benchmarks, sector ETFs, peer lists, scoring thresholds."""

MARKET_BENCHMARK = "SPY"

# yfinance `sector` value -> SPDR sector ETF
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# Large-cap peers per sector (the analysed ticker is removed at runtime).
SECTOR_PEERS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA"],
    "Healthcare": ["JNJ", "LLY", "UNH", "MRK", "ABBV", "PFE", "TMO", "ABT"],
    "Energy": ["XOM", "CVX", "COP", "EOG", "SLB", "PSX", "MPC", "OXY"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "BKNG"],
    "Consumer Defensive": ["WMT", "PG", "KO", "PEP", "COST", "PM", "MDLZ", "CL"],
    "Industrials": ["GE", "CAT", "RTX", "HON", "UNP", "BA", "DE", "LMT"],
    "Basic Materials": ["LIN", "SHW", "APD", "ECL", "FCX", "NEM", "DOW", "NUE"],
    "Utilities": ["NEE", "SO", "DUK", "AEP", "SRE", "D", "EXC", "XEL"],
    "Real Estate": ["PLD", "AMT", "EQIX", "WELL", "SPG", "PSA", "O", "CCI"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "CMCSA"],
}
MAX_PEERS = 6

# Sectors where debt/equity is not meaningful (deposits are liabilities).
DEBT_EXEMPT_SECTORS = {"Financial Services"}

# Pillar weights for the composite score (must sum to 1).
PILLAR_WEIGHTS = {
    "Valuation": 0.25,
    "Growth": 0.20,
    "Profitability": 0.20,
    "Financial Health": 0.10,
    "Momentum": 0.10,
    "Analyst Consensus": 0.15,
}

BUY_THRESHOLD = 65
SELL_THRESHOLD = 45

RETURN_PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756}

CACHE_DIR = ".cache"
CACHE_TTL_HOURS = 12

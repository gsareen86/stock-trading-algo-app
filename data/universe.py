"""
NIFTY 500 universe management.
Tries to download the official NSE list; falls back to a bundled starter list.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import List

import requests

from config import DEFAULT_WATCHLIST_FILE


NSE_NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

# Tickers that cause persistent yfinance 404/empty errors due to delisting,
# symbol changes, or NSE data feed quirks. Filtered out of the universe
# before any fetch or strategy evaluation to avoid noisy log spam every cycle.
_BLOCKED_TICKERS: frozenset[str] = frozenset({
    "DUMMYVEDL1", "DUMMYVEDL2", "DUMMYVEDL3", "DUMMYVEDL4",
    "VEDL",       # often returns stale / zero data; use VEDANTA if needed
})

# A curated fallback subset (~200 names: NIFTY 100 + Next 50 + popular mid-caps)
# used if the NSE CSV download fails. Symbols are NSE codes WITHOUT the .NS
# suffix — `to_yf_ticker()` adds it. Roughly ordered: large-cap → mid-cap.
FALLBACK_UNIVERSE = [
    # ---------- NIFTY 50 ----------
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "LT", "ITC", "HINDUNILVR",
    "KOTAKBANK", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "HCLTECH", "SUNPHARMA", "WIPRO", "M&M", "ULTRACEMCO",
    "NESTLEIND", "TITAN", "POWERGRID", "NTPC", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "COALINDIA", "ADANIENT",
    "ADANIPORTS", "BAJAJFINSV", "TECHM", "HDFCLIFE", "SBILIFE",
    "BRITANNIA", "CIPLA", "DRREDDY", "EICHERMOT", "GRASIM",
    "HEROMOTOCO", "HINDALCO", "INDUSINDBK", "BAJAJ-AUTO", "APOLLOHOSP",
    "BPCL", "TATACONSUM", "LTIM", "DIVISLAB", "SHRIRAMFIN",
    # ---------- NIFTY Next 50 ----------
    "JIOFIN", "LICI", "DMART", "ADANIPOWER", "ADANIGREEN",
    "PIDILITIND", "HAVELLS", "GODREJCP", "SIEMENS", "BOSCHLTD",
    "AMBUJACEM", "DLF", "VEDL", "TVSMOTOR", "ABB",
    "HAL", "BEL", "PFC", "RECLTD", "INDIGO",
    "ICICIGI", "ICICIPRULI", "SBICARD", "CHOLAFIN", "BAJAJHLDNG",
    "GAIL", "IOC", "HINDPETRO", "ATGL", "TORNTPHARM",
    "ZYDUSLIFE", "TRENT", "PNB", "CANBK", "BANKBARODA",
    "JINDALSTEL", "TATAPOWER", "MOTHERSON", "MARICO", "DABUR",
    "COLPAL", "MUTHOOTFIN", "HDFCAMC", "BIOCON", "LUPIN",
    "AUROPHARMA", "ALKEM", "MANKIND", "BERGEPAINT", "NMDC",
    # ---------- Popular mid-caps / FMCG / consumer ----------
    "UPL", "BRITANNIA", "VBL", "JUBLFOOD", "UBL",
    "MCDOWELL-N", "RADICO", "DEVYANI", "HONASA", "NESTLEIND",
    "BATAINDIA", "RELAXO", "PAGEIND", "ABFRL", "VMART",
    "RAYMOND", "ARVIND", "KPRMILL", "TIINDIA",
    # ---------- Auto ancillaries / industrials ----------
    "BHARATFORG", "BALKRISIND", "MRF", "CEAT", "APOLLOTYRE",
    "EXIDEIND", "ESCORTS", "BAJAJ-AUTO", "CUMMINSIND", "THERMAX",
    "KIRLOSKARP", "ELGIEQUIP",
    # ---------- IT / digital ----------
    "PERSISTENT", "COFORGE", "MPHASIS", "KPITTECH", "OFSS",
    "CYIENT", "TATAELXSI", "INTELLECT", "ZENSARTECH", "FIRSTSOURCE",
    "NAUKRI", "INDIAMART", "JUSTDIAL", "ZOMATO", "PAYTM",
    "POLICYBZR", "NYKAA", "MAPMYINDIA", "LATENTVIEW",
    # ---------- Capital goods / cement ----------
    "JKCEMENT", "RAMCOCEM", "INDIACEM", "DALBHARAT", "ACC",
    "BIRLACORPN", "JKLAKSHMI", "PRISMJOHNSN",
    # ---------- Real estate ----------
    "PRESTIGE", "OBEROIRLTY", "GODREJPROP", "BRIGADE", "PHOENIXLTD",
    "LODHA", "MAHLIFE",
    # ---------- Power / infra / PSU ----------
    "TORNTPOWER", "NHPC", "JSWENERGY", "IRFC", "IRCTC",
    "RAILTEL", "RVNL", "IREDA", "IRCON", "NLCINDIA",
    "NBCC", "NCC", "KEC", "KEI", "POLYCAB",
    "FINCABLES", "CONCOR",
    # ---------- Consumer durables / appliances ----------
    "DIXON", "AMBER", "BLUESTARCO", "VOLTAS", "WHIRLPOOL",
    "CROMPTON", "BAJAJELEC", "ORIENTELEC", "SYMPHONY", "TTKPRESTIG",
    "KAJARIACER", "CERA", "ASTRAL", "SUPREMEIND", "FINOLEXIND",
    # ---------- Gas / oil ----------
    "GUJGAS", "IGL", "MGL", "PETRONET", "GSPL",
    "OIL",
    # ---------- Chemicals / specialty ----------
    "SRF", "AARTIIND", "DEEPAKNTR", "NAVINFLUOR", "ATUL",
    "CLEAN", "PIIND", "COROMANDEL", "RALLIS", "DHANUKA",
    "BAYERCROP",
    # ---------- Financials (broking / NBFC / insurance) ----------
    "AUBANK", "BANDHANBNK", "IDFCFIRSTB", "FEDERALBNK", "RBLBANK",
    "YESBANK", "INDIANB", "UNIONBANK", "MFSL", "IIFL",
    "MANAPPURAM", "BAJAJHFL", "ANGELONE", "BSE", "MCX",
    "CAMS", "CDSL", "IEX",
    # ---------- Misc large mid-caps ----------
    "ADANIENSOL", "GICRE", "NIACL", "GLENMARK", "IPCALAB",
    "GLAND", "PVRINOX", "ZEEL", "SUNTV", "NAZARA",
    "CARBORUNIV", "GREAVESCOT", "FORCEMOT", "JUBLPHARMA", "METROBRAND",
    "CAMPUS", "SHOPERSTOP", "INOXWIND",
]
# Deduplicate while preserving order (in case of any accidental repeats above).
FALLBACK_UNIVERSE = list(dict.fromkeys(FALLBACK_UNIVERSE))


def to_yf_ticker(symbol: str) -> str:
    """Convert NSE symbol to yfinance ticker.

    Index symbols on Yahoo start with '^' (e.g. '^NSEI' for NIFTY 50) and
    MUST NOT be given the '.NS' suffix — that turns them into bogus
    '^NSEI.NS' which 404s. Symbols already qualified (.NS, .BO, contain a
    '.') also pass through unchanged.
    """
    symbol = symbol.strip().upper().replace(" ", "")
    # yfinance index tickers start with '^' and take no exchange suffix
    if symbol.startswith("^"):
        return symbol
    # already qualified
    if symbol.endswith(".NS") or symbol.endswith(".BO") or "." in symbol:
        return symbol
    # Some tickers have special chars like "M&M" - yfinance accepts "M&M.NS".
    return f"{symbol}.NS"


def download_nifty500() -> List[str]:
    """Download the official NIFTY 500 constituents CSV from NSE."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(NSE_NIFTY500_CSV_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        symbols = [row["Symbol"].strip() for row in reader if row.get("Symbol")]
        if symbols:
            return [s for s in symbols if s.upper() not in _BLOCKED_TICKERS]
    except Exception as e:
        print(f"[universe] NSE download failed ({e}); using fallback list.")
    return [s for s in FALLBACK_UNIVERSE if s.upper() not in _BLOCKED_TICKERS]


def load_universe(refresh: bool = False) -> List[str]:
    """
    Return list of NSE symbols (without .NS suffix).
    Caches to data/nifty500.csv so we don't hammer NSE.
    Known-bad tickers (delisted / stale feed) are excluded automatically.
    """
    path = Path(DEFAULT_WATCHLIST_FILE)
    if refresh or not path.exists():
        symbols = download_nifty500()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Symbol"])
            writer.writerows([[s] for s in symbols])
    else:
        with open(path) as f:
            reader = csv.DictReader(f)
            symbols = [row["Symbol"].strip() for row in reader if row.get("Symbol")]
    return [s for s in symbols if s.upper() not in _BLOCKED_TICKERS]


def yf_tickers(symbols: List[str] | None = None) -> List[str]:
    symbols = symbols or load_universe()
    return [to_yf_ticker(s) for s in symbols]


def universe_info() -> dict:
    """Diagnostic for the dashboard: how many tickers and where they came from.

    Returns: {n: int, source: str, path: str | None, sample: list[str]}
    Source is "nifty500.csv" if the cached CSV exists, else "fallback".
    """
    path = Path(DEFAULT_WATCHLIST_FILE)
    if path.exists():
        try:
            with open(path) as f:
                reader = csv.DictReader(f)
                syms = [row["Symbol"].strip() for row in reader if row.get("Symbol")]
            return {
                "n": len(syms),
                "source": "nifty500.csv",
                "path": str(path),
                "sample": syms[:10],
            }
        except Exception:
            pass
    return {
        "n": len(FALLBACK_UNIVERSE),
        "source": "fallback (bundled list)",
        "path": None,
        "sample": list(FALLBACK_UNIVERSE[:10]),
    }


if __name__ == "__main__":
    u = load_universe()
    print(f"Loaded {len(u)} tickers. First 10: {u[:10]}")

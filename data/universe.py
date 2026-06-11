"""
NIFTY 500 universe management.
Tries to download the official NSE list; falls back to a bundled starter list.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
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


# ── Full NSE equity master (EQUITY_L.csv) ─────────────────────────────────────
# Every listed company with series + DATE OF LISTING. This is the expanded
# universe source: all EQ-series names (microcaps and fresh IPOs included);
# the market-cap floor is applied downstream by the Screener pipeline where
# mcap is actually known. BE/BZ (trade-to-trade) and SME series are excluded —
# T2T allows no intraday netting and is itself a surveillance signal.

NSE_EQUITY_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_MASTER_FILE = str(Path(__file__).parent / "nse_equity_master.csv")


def _parse_listing_date(raw: str) -> str:
    """NSE '01-JAN-2024' (or similar) → ISO date; '' if unparseable."""
    raw = (raw or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def download_equity_master() -> List[dict]:
    """Download the full NSE securities master. Returns EQ-series rows:
    [{symbol, name, series, listing_date}], or [] on failure (fail-open)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(NSE_EQUITY_MASTER_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = []
        for row in reader:
            norm = {k.strip().upper(): (v or "").strip() for k, v in row.items()}
            if norm.get("SERIES", "").upper() != "EQ":
                continue
            sym = norm.get("SYMBOL", "").upper()
            if not sym or sym in _BLOCKED_TICKERS:
                continue
            rows.append({
                "symbol": sym,
                "name": norm.get("NAME OF COMPANY", ""),
                "series": "EQ",
                "listing_date": _parse_listing_date(norm.get("DATE OF LISTING", "")),
            })
        return rows
    except Exception as e:
        print(f"[universe] NSE equity master download failed ({e})")
        return []


def load_equity_master(refresh: bool = False) -> List[dict]:
    """EQ-series master, cached to disk and auto-refreshed weekly
    (EQUITY_MASTER_REFRESH_DAYS). Falls back to the NIFTY 500 list (without
    listing dates) when NSE is unreachable and no cache exists."""
    from config import EQUITY_MASTER_REFRESH_DAYS
    path = Path(EQUITY_MASTER_FILE)

    stale = True
    if path.exists():
        try:
            age_days = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
            stale = age_days > EQUITY_MASTER_REFRESH_DAYS
        except OSError:
            pass

    if refresh or stale or not path.exists():
        rows = download_equity_master()
        if rows:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["symbol", "name", "series", "listing_date"])
                w.writeheader()
                w.writerows(rows)
            return rows
        # download failed — use stale cache if any, else NIFTY 500 fallback
        if not path.exists():
            print("[universe] equity master unavailable — falling back to NIFTY 500 list")
            return [{"symbol": s, "name": "", "series": "EQ", "listing_date": ""}
                    for s in load_universe()]

    with open(path, encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def load_expanded_universe(refresh: bool = False) -> List[str]:
    """Symbol list for the expanded (all-NSE) universe, honouring
    UNIVERSE_SOURCE. The ₹ market-cap floor is enforced downstream by the
    Screener pipeline (mcap isn't in the master CSV)."""
    from config import UNIVERSE_SOURCE
    if UNIVERSE_SOURCE == "nifty500":
        return load_universe(refresh=refresh)
    return [r["symbol"] for r in load_equity_master(refresh=refresh)]


def listing_dates() -> dict:
    """{symbol: iso_listing_date} for every master row that has one."""
    return {r["symbol"]: r["listing_date"]
            for r in load_equity_master() if r.get("listing_date")}


def listing_age_days(symbol: str) -> int | None:
    """Calendar days since listing, or None if unknown."""
    d = listing_dates().get(symbol.upper().split(".")[0])
    if not d:
        return None
    try:
        return (datetime.now().date() - datetime.fromisoformat(d).date()).days
    except ValueError:
        return None


def recent_ipos(months: int | None = None) -> List[dict]:
    """Master rows listed within the last N months (default IPO_TRACK_MONTHS)."""
    from config import IPO_TRACK_MONTHS
    months = months or IPO_TRACK_MONTHS
    cutoff = (datetime.now().date() - timedelta(days=months * 30)).isoformat()
    return [r for r in load_equity_master()
            if r.get("listing_date") and r["listing_date"] >= cutoff]


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

"""
Entry point. Starts:
  1. The bot runner (background thread)
  2. The Streamlit dashboard (blocks)

Usage:
    python main.py                # start everything
    python main.py --init         # just initialize DB
    python main.py --runner-only  # run bot without dashboard
    python main.py --dashboard-only
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from config import DEFAULT_MODE, LOG_DIR, LOG_LEVEL
from db.models import init_db
from engine.portfolio import initialize_if_empty
from positional.runner import run_positional_forever
from scheduler.runner import run_forever, set_bot_state


def _setup_logging():
    import io
    log_path = Path(LOG_DIR) / "bot.log"
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    # FileHandler always UTF-8 so log file captures all Unicode chars.
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))
    # Console on Windows may be cp1252 — wrap with UTF-8 and replace unmappable chars.
    if hasattr(sys.stdout, "buffer"):
        stdout_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    else:
        stdout_stream = sys.stdout
    console_handler = logging.StreamHandler(stdout_stream)
    console_handler.setFormatter(logging.Formatter(fmt))
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        handlers=[file_handler, console_handler],
    )
    # Third-party libraries that generate noisy INFO logs during normal
    # operation (HuggingFace model resolution, HTTPX request traces).
    # Cap them at WARNING so they only surface when something is wrong.
    for _noisy in ("httpx", "httpcore", "huggingface_hub", "huggingface_hub.utils._http",
                   "transformers", "transformers.modeling_utils", "filelock"):
        logging.getLogger(_noisy).setLevel(logging.ERROR)


def start_api_server():
    """Launch the FastAPI + React dashboard server."""
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"[startup] Starting Unified FastAPI + React Dashboard on http://{host}:{port} ...", flush=True)
    uvicorn.run("api.server:app", host=host, port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="init DB and exit")
    parser.add_argument("--runner-only", action="store_true")
    parser.add_argument("--dashboard-only", action="store_true")
    parser.add_argument("--positional-only", action="store_true",
                        help="run positional runner only (no intraday, no dashboard)")
    parser.add_argument("--reset", action="store_true", help="wipe DB (destructive)")
    args = parser.parse_args()

    _setup_logging()

    if args.reset:
        from db.models import reset_db
        reset_db()
        print("DB reset complete.")
        return

    init_db()
    initialize_if_empty()
    # Auto-arm at startup: on any trading day (Mon-Fri, not an NSE holiday) set
    # the bot RUNNING so it actually trades when the market opens. run_cycle()
    # short-circuits on market_is_open(), so RUNNING outside market hours is
    # harmless — it just idles. Previously this only armed if market was open
    # AT BOOT, which left the bot STOPPED for the whole day after a pre-market
    # restart (run_forever doesn't auto-flip status). On weekends/holidays,
    # keep STOPPED. The user can still HALT manually via the UI any time.
    from data.fetcher import is_nse_holiday
    from datetime import datetime as _dt
    from config import IST as _IST
    _now = _dt.now(_IST)
    _is_trading_day = _now.weekday() < 5 and not is_nse_holiday(_now)
    _auto_status = "RUNNING" if _is_trading_day else "STOPPED"
    set_bot_state(status=_auto_status, mode=DEFAULT_MODE)
    print(f"[startup] {'Trading day' if _is_trading_day else 'Non-trading day'}"
          f" — bot status set to {_auto_status}, mode={DEFAULT_MODE}", flush=True)

    # Pre-warm FinBERT in a background thread so the first news-scrape cycle
    # doesn't block for ~3 minutes while the 400 MB model downloads and loads.
    # The load is idempotent (double-checked lock in _get_finbert) so this is
    # safe to call even if FinBERT is disabled — it will simply return quickly.
    try:
        from config import ENABLE_FINBERT
        if ENABLE_FINBERT:
            import threading as _t
            from nlp.sentiment import _get_finbert
            _t.Thread(target=_get_finbert, daemon=True, name="finbert-prewarm").start()
    except Exception:
        pass  # non-fatal; first cycle will load on demand

    if args.init:
        print("DB initialized.")
        return

    if args.dashboard_only:
        start_api_server()
        return

    if args.runner_only:
        run_forever()
        return

    if args.positional_only:
        run_positional_forever()
        return

    # Full mode: API Server + Intraday Runner + Positional Runner
    runner = threading.Thread(target=run_forever, daemon=True, name="bot-runner")
    pos_runner = threading.Thread(target=run_positional_forever, daemon=True,
                                  name="positional-runner")
    runner.start()
    pos_runner.start()

    try:
        start_api_server()
    except KeyboardInterrupt:
        print("\nShutting down unified trading app...")


if __name__ == "__main__":
    main()


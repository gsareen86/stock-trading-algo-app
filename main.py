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


def start_dashboard():
    """Launch Streamlit dashboard as a subprocess."""
    script = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.headless", "true",
        "--server.port", os.environ.get("STREAMLIT_PORT", "8501"),
        "--browser.gatherUsageStats", "false",
    ]
    return subprocess.Popen(cmd)


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
    # On first startup, default to user's chosen mode but STOPPED status
    # (User toggles RUN from the dashboard).
    set_bot_state(status="STOPPED", mode=DEFAULT_MODE)

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
        proc = start_dashboard()
        proc.wait()
        return

    if args.runner_only:
        run_forever()
        return

    if args.positional_only:
        run_positional_forever()
        return

    # Full mode: dashboard + intraday runner + positional runner
    dash_proc = start_dashboard()
    runner = threading.Thread(target=run_forever, daemon=True, name="bot-runner")
    pos_runner = threading.Thread(target=run_positional_forever, daemon=True,
                                  name="positional-runner")
    runner.start()
    pos_runner.start()

    try:
        dash_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        if dash_proc.poll() is None:
            dash_proc.terminate()
            dash_proc.wait()


if __name__ == "__main__":
    main()

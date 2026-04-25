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
from scheduler.runner import run_forever, set_bot_state


def _setup_logging():
    log_path = Path(LOG_DIR) / "bot.log"
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
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

    # Full mode: dashboard in a subprocess + runner in a thread
    dash_proc = start_dashboard()
    runner = threading.Thread(target=run_forever, daemon=True, name="bot-runner")
    runner.start()

    try:
        dash_proc.wait()
    except KeyboardInterrupt:
        dash_proc.terminate()
        print("\nShutting down…")


if __name__ == "__main__":
    main()

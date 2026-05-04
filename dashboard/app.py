"""
Streamlit dashboard for the virtual trading bot.

IMPORTANT: This file deliberately avoids `st.dataframe()` because its internal
use of pyarrow triggers Windows Smart App Control DLL-load blocks. All
tabular data is rendered as HTML via `render_table()` below, which uses
pandas' pure-Python `to_html()`.

Tabs:
  1. Control Panel     — start/pause/stop, mode, pending approvals, live params
  2. Overview          — portfolio summary + equity curve
  3. Positions & Trades
  4. News & Sentiment
  5. Fundamentals
  6. Analytics
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(ts):
    """Convert a naive-UTC timestamp (or pandas Series/Index of them) to IST.
    Accepts strings, datetimes, Timestamps, Series, and DatetimeIndex.
    Safe to pass tz-aware inputs — uses tz_convert instead of tz_localize.
    Returns None if ts is None.
    """
    import pandas as _pd
    if ts is None:
        return ts

    if isinstance(ts, _pd.Series):
        s = _pd.to_datetime(ts, errors="coerce")
        if s.dt.tz is None:
            s = s.dt.tz_localize("UTC")
        return s.dt.tz_convert("Asia/Kolkata")

    if isinstance(ts, _pd.DatetimeIndex):
        idx = ts if ts.tz is not None else ts.tz_localize("UTC")
        return idx.tz_convert("Asia/Kolkata")

    # scalar (str, datetime, Timestamp)
    t = _pd.to_datetime(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert("Asia/Kolkata")

# Allow running this file from any cwd
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    INITIAL_CAPITAL,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
    MIN_COMPOSITE_SCORE,
    SIGNAL_POLL_INTERVAL_SEC,
)
from analytics.metrics import (
    benchmark_series,
    closed_positions_report,
    portfolio_summary,
    strategy_breakdown,
    trade_stats,
)
from data.fetcher import latest_price, latest_price_with_ts, market_is_open
from data.fundamentals import is_bank, screener_url
from data.news_scraper import (
    news_db_stats,
    recent_news_for_ticker,
    retag_existing_news,
    scrape_all as scrape_all_news,
)
from data.universe import universe_info
from nlp.sentiment import score_news_items
from db.models import BACKEND, get_conn, init_db, query_df
from engine.portfolio import close_position, open_positions, snapshots_df, trades_df
from scheduler import runner as runner_mod

st.set_page_config(
    page_title="Virtual Trading Bot — India",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


# init_db() is wrapped in a session-scoped cache so it doesn't re-create
# tables and re-run CREATE-IF-NOT-EXISTS DDL on every Streamlit rerun
# (which fired several times per second on every UI interaction and was
# a major contributor to the laggy feel).
@st.cache_resource
def _init_db_once() -> bool:
    init_db()
    return True

_init_db_once()


TABLE_CSS = """
<style>
table.dashtable {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.88rem;
    margin: 6px 0 12px 0;
}
table.dashtable th, table.dashtable td {
    padding: 6px 10px;
    border-bottom: 1px solid rgba(128,128,128,0.25);
    text-align: left;
}
table.dashtable th {
    background: rgba(128,128,128,0.12);
    font-weight: 600;
}
table.dashtable tr:hover td { background: rgba(128,128,128,0.06); }
table.dashtable td.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge-green { color: #1bc47d; font-weight: 600; }
.badge-red   { color: #ff4b4b; font-weight: 600; }
.status-pill {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-weight: 600; font-size: 0.82rem;
}
.status-RUNNING  { background: rgba(27,196,125,0.18);  color: #1bc47d; }
.status-PAUSED   { background: rgba(255,200,0,0.18);   color: #ffc000; }
.status-STOPPED  { background: rgba(255,75,75,0.18);   color: #ff4b4b; }
.banner-warn {
    background: rgba(255,200,0,0.12); border-left: 4px solid #ffc000;
    padding: 10px 14px; border-radius: 6px; margin-bottom: 12px;
}
.banner-ok {
    background: rgba(27,196,125,0.10); border-left: 4px solid #1bc47d;
    padding: 10px 14px; border-radius: 6px; margin-bottom: 12px;
}
.radio-grid label { min-width: 340px; }
</style>
"""


def render_table(df: pd.DataFrame, cols: list[str] | None = None) -> None:
    """pyarrow-free table renderer."""
    if df is None or df.empty:
        st.caption("No data.")
        return
    if cols:
        df = df[cols]
    html = df.to_html(index=False, escape=False, classes="dashtable", border=0)
    st.markdown(TABLE_CSS + html, unsafe_allow_html=True)


def _bot_row() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bot_control WHERE id=1").fetchone()
    return dict(row) if row else {}


def _set_bot(**kwargs) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    vals.append(datetime.now(timezone.utc).isoformat())
    with get_conn() as conn:
        conn.execute(
            f"UPDATE bot_control SET {sets}, updated_at=? WHERE id=1", vals
        )


def _now_ist() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _fmt_pnl(val: float) -> str:
    """HTML-coloured P&L (used inside table cells via unsafe_allow_html)."""
    cls = "badge-green" if val > 0 else "badge-red" if val < 0 else ""
    return f'<span class="{cls}">{"₹" if cls else ""}{val:+,.2f}</span>' if cls else f"₹{val:+,.2f}"


def _fmt_pnl_plain(val: float) -> str:
    """Plain-text P&L for st.metric (which doesn't render HTML)."""
    return f"₹{val:+,.2f}"


st.markdown(TABLE_CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------


bot = _bot_row()
status = bot.get("status", "STOPPED")
mode = bot.get("mode", "manual")

with st.sidebar:
    st.title("📊 Trading Bot")

    st.markdown(
        f"**Status:**  "
        f"<span class='status-pill status-{status}'>{status}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Mode:** `{mode.upper()}`")

    _mkt_open = market_is_open()
    # Fragment refresh cadence: only auto-poll when the market is open.
    # When closed there is nothing changing, so fragments run once on page
    # load and stay static until the user hits "Refresh now". This eliminates
    # the Streamlit ⟳/Stop spinner that was firing every 15–30 s even at night.
    _frag_refresh = 60 if _mkt_open else None

    if _mkt_open:
        st.markdown('<div class="banner-ok">🕒 <b>NSE Market OPEN</b></div>',
                    unsafe_allow_html=True)
    else:
        next_open = "Monday 09:15 IST" if _now_ist().weekday() >= 4 else "Tomorrow 09:15 IST"
        if _now_ist().weekday() < 5 and _now_ist().strftime("%H:%M") < "09:15":
            next_open = "Today 09:15 IST"
        st.markdown(
            f'<div class="banner-warn">🕒 <b>NSE Market CLOSED</b><br>'
            f'<sub>Next open: {next_open}</sub></div>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # Live updates
    # ------------------------------------------------------------------
    # We use Streamlit fragments (`@st.fragment(run_every=...)`) for the
    # small live panels (last cycle, status pill). Fragments refresh just
    # their own block — they DO NOT grey out or re-render the whole page,
    # which was the UX problem with `time.sleep + st.rerun()` we used
    # before. The fragments tick every 10s. Hit "Refresh now" for a full
    # page refresh of all data.
    if st.button("🔄 Refresh now", width="stretch"):
        st.rerun()

    # Last-cycle chip — only auto-refreshes when market is open.
    def _sidebar_cycle_chip():
        row = runner_mod.last_cycle_summary()
        if not row:
            st.caption("Bot has not run a cycle yet")
            return
        try:
            started = pd.to_datetime(row.get("started_at"))
            age = (pd.Timestamp.now('UTC').tz_localize(None) - started).total_seconds()
        except Exception:
            age = None
        _s = row.get("status") or "?"
        status_emoji = {"RUNNING": "🟡", "DONE": "🟢",
                        "ERROR": "🔴", "SKIPPED": "⚪"}.get(_s, "•")
        if age is None:
            st.caption(f"Last cycle: {status_emoji} {_s}")
        else:
            st.caption(f"Last cycle: {status_emoji} {_s} · {int(age)}s ago")

    st.fragment(run_every=_frag_refresh)(_sidebar_cycle_chip)()

    # Version indicator — shows which git branch/commit is running.
    try:
        import subprocess as _sp
        _branch = _sp.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=_sp.DEVNULL, cwd=str(ROOT),
        ).decode().strip()
        _commit = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=_sp.DEVNULL, cwd=str(ROOT),
        ).decode().strip()
        st.caption(f"🔖 `{_branch}` · `{_commit}`")
    except Exception:
        pass


# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

(
    tab_ctrl, tab_overview, tab_pos, tab_news,
    tab_fund, tab_analytics, tab_lt_research,
) = st.tabs([
    "🎛️ Control Panel",
    "📊 Overview",
    "💼 Positions & Trades",
    "📰 News & Sentiment",
    "📈 Fundamentals",
    "📉 Analytics",
    "🔬 Long-Term Research",
])


# ==================================================================
# 1. Control Panel
# ==================================================================

with tab_ctrl:
    st.header("🎛️ Control Panel")

    # ------------------------------------------------------------------
    # Capacity + universe banner (Fix 1 + Fix 4)
    # ------------------------------------------------------------------
    # Goal: make the bot's silence explainable. If the bot hasn't placed a
    # trade for hours, the user should see at a glance whether that's
    # because positions are full, because no signal cleared the score
    # threshold, or because the time gate is in effect.
    max_pos_now = int(bot.get("max_open_positions", MAX_OPEN_POSITIONS))
    uni_info = universe_info()

    # Sample size (per-cycle) — read from config so the banner reflects what
    # the scheduler actually evaluates each cycle, not just the universe size.
    try:
        from config import CYCLE_SAMPLE_SIZE as _cycle_sample
    except Exception:
        _cycle_sample = 50

    bcap, buni = st.columns([3, 2])

    # Capacity banner is now a FRAGMENT so it stays fresh after positions
    # are taken/closed without forcing a full page rerun. Previously it
    # was rendered once at page load and showed a stale count (e.g. 0/10
    # while the Positions tab had 2 active positions).
    @st.fragment(run_every=_frag_refresh)
    def _capacity_banner():
        with get_conn() as conn:
            n_open = conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE status='OPEN'"
            ).fetchone()["n"]
        cap_pct = (n_open / max_pos_now * 100) if max_pos_now else 0
        cap_color = "#1bc47d" if cap_pct < 60 else "#ffc000" if cap_pct < 100 else "#ff4b4b"
        msg = f"Holding <b>{n_open}/{max_pos_now}</b> positions"
        if n_open >= max_pos_now:
            msg += " — <b>at capacity</b>; no new entries until a position closes or you square-off."
        elif n_open >= max_pos_now - 1:
            msg += " — only 1 slot left."
        else:
            msg += f" — {max_pos_now - n_open} slots free."
        msg += f" <sub>(refreshed {datetime.now().strftime('%H:%M:%S')})</sub>"
        st.markdown(
            f"<div style='background: rgba(128,128,128,0.10); border-left: 4px solid {cap_color};"
            f" padding: 10px 14px; border-radius: 6px;'>📦 {msg}</div>",
            unsafe_allow_html=True,
        )

    with bcap:
        _capacity_banner()
    buni.markdown(
        f"<div style='background: rgba(128,128,128,0.10); border-left: 4px solid #1f77b4;"
        f" padding: 10px 14px; border-radius: 6px;'>"
        f"🌐 Universe: <b>{uni_info['n']}</b> tickers · "
        f"sampling <b>{_cycle_sample}</b> per cycle · "
        f"<sub>source: {uni_info['source']}</sub></div>",
        unsafe_allow_html=True,
    )

    # Keep open_count for downstream usage in this scope (signal-status
    # calculations etc) — fragment value isn't visible outside.
    open_count = 0
    try:
        with get_conn() as conn:
            open_count = conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE status='OPEN'"
            ).fetchone()["n"]
    except Exception:
        pass

    # ----- Signal history with filters (so user can see WHY no trade was placed
    # and trace any historical signal — was previously hard-capped at 30) -----
    #
    # Signal history — only auto-refreshes when market is open (new signals
    # only arrive during trading hours).
    @st.fragment(run_every=_frag_refresh)
    def _signal_history_panel():
        refresh_note = "auto-refreshes every 60s" if _frag_refresh else "market closed — use Refresh now"
        with st.expander(
            f"🧭 Signal history (filterable — see why each signal was/wasn't taken) · {refresh_note}",
            expanded=False,
        ):
            # Filters — added a Status filter as requested.
            sf1, sf2, sf3, sf4, sf5 = st.columns([2, 2, 2, 2, 1])
            sig_action = sf1.selectbox(
                "Action", ["All", "BUY", "SELL", "HOLD"], index=0, key="sig_action_f"
            )
            sig_ticker = sf2.text_input(
                "Ticker contains", "", key="sig_ticker_f"
            ).strip().upper()
            sig_status = sf3.selectbox(
                "Status",
                ["All", "Taken", "Blocked by regime", "Score below threshold",
                 "At capacity", "Pending / queued", "Not actionable (HOLD/SELL)"],
                index=0, key="sig_status_f",
            )
            sig_hours = sf4.selectbox(
                "Lookback", [4, 24, 72, 168, 720], index=1,
                format_func=lambda h: f"{h}h" if h < 168 else f"{h//24}d",
                key="sig_hours_f",
            )
            sig_limit = sf5.number_input(
                "Max rows", min_value=20, max_value=2000, value=200, step=20,
                key="sig_limit_f",
            )

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(sig_hours))).isoformat()
            params: list = [cutoff]
            sql = ("SELECT ts, ticker, action, strategy, composite_score, "
                   "technical_score, fundamental_score, sentiment_score, "
                   "price, reason, taken FROM signals WHERE ts >= ?")
            if sig_action != "All":
                sql += " AND action = ?"
                params.append(sig_action)
            if sig_ticker:
                sql += " AND ticker LIKE ?"
                params.append(f"%{sig_ticker}%")
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(int(sig_limit))
            with get_conn() as conn:
                sig_rows = conn.execute(sql, params).fetchall()
                # Re-read live position count INSIDE the fragment so the
                # "🚫 at capacity" reason reflects current state, not the
                # snapshot taken when the page first loaded.
                live_open = conn.execute(
                    "SELECT COUNT(*) AS n FROM positions WHERE status='OPEN'"
                ).fetchone()["n"]
            rendered_at = datetime.now().strftime("%H:%M:%S")
            st.caption(
                f"Showing {len(sig_rows)} signals (action={sig_action}, "
                f"last {sig_hours}h, limit {sig_limit}). "
                f"Last refresh {rendered_at}."
            )
            if not sig_rows:
                st.caption("No signals recorded yet. Click **⚡ Run Cycle Now** "
                           "below to force one.")
                return
            min_score = float(bot.get("min_composite_score", MIN_COMPOSITE_SCORE))

            # Read the LATEST cycle's regime so the per-signal status can
            # explain "blocked by regime" (BUYs in bearish, SELLs in bullish).
            # Without this the user sees "pending/queued" for signals that
            # are actually permanently blocked until regime flips.
            current_regime = "unknown"
            try:
                last_cycle = runner_mod.last_cycle_summary()
                if last_cycle and last_cycle.get("summary"):
                    import json as _json
                    s = (_json.loads(last_cycle["summary"])
                         if isinstance(last_cycle["summary"], str)
                         else last_cycle["summary"])
                    current_regime = (s.get("regime") or "unknown").lower()
            except Exception:
                pass

            sig_view = []
            for r in sig_rows:
                cs = r["composite_score"] or 0.0
                action = r["action"] or "-"
                # Buckets line up with the Status filter dropdown above.
                bucket = None
                if r["taken"]:
                    why, bucket = "✅ taken", "Taken"
                elif action == "BUY":
                    if cs < min_score:
                        why = f"🚫 score {cs:.0f} < threshold {min_score:.0f}"
                        bucket = "Score below threshold"
                    elif current_regime == "bearish":
                        why = "🚫 long blocked (NIFTY bearish)"
                        bucket = "Blocked by regime"
                    elif live_open >= max_pos_now:
                        why = "🚫 at capacity"
                        bucket = "At capacity"
                    else:
                        why = "⏳ pending / queued"
                        bucket = "Pending / queued"
                elif action == "SELL":
                    # SELL = SHORT entry candidate under the new strategy.
                    if cs < min_score:
                        why = f"🚫 score {cs:.0f} < threshold {min_score:.0f}"
                        bucket = "Score below threshold"
                    elif current_regime == "bullish":
                        why = "🚫 short blocked (NIFTY bullish)"
                        bucket = "Blocked by regime"
                    elif live_open >= max_pos_now:
                        why = "🚫 at capacity"
                        bucket = "At capacity"
                    else:
                        why = "⏳ short pending / queued"
                        bucket = "Pending / queued"
                else:
                    why, bucket = "— HOLD (no action)", "Not actionable (HOLD/SELL)"

                # Apply Status filter at render time.
                if sig_status != "All" and bucket != sig_status:
                    continue

                try:
                    ts_local = to_ist(r["ts"]).strftime("%H:%M IST · %d %b")
                except Exception:
                    ts_local = (r["ts"] or "")[:16]
                sig_view.append({
                    "Time": ts_local,
                    "Ticker": r["ticker"],
                    "Action": action,
                    "Strategy": r["strategy"] or "—",
                    "Composite": f"{cs:.1f}",
                    "Tech": f"{(r['technical_score'] or 0):.0f}",
                    "Fund": f"{(r['fundamental_score'] or 0):.0f}",
                    "Sent": f"{(r['sentiment_score'] or 0):+.2f}",
                    "Status": why,
                })
            st.caption(
                f"Live regime: **{current_regime}** · matched **{len(sig_view)}** "
                f"of {len(sig_rows)} fetched signals after filters."
            )
            render_table(pd.DataFrame(sig_view))

    _signal_history_panel()

    @st.fragment(run_every=_frag_refresh)
    def _live_holdings_chip():
        with get_conn() as conn:
            n_open = conn.execute(
                "SELECT COUNT(*) AS n FROM positions WHERE status='OPEN'"
            ).fetchone()["n"]
        rendered_at = datetime.now().strftime("%H:%M:%S")
        st.caption(
            f"📦 Live holdings count: **{n_open}/{max_pos_now}** "
            f"(refreshed {rendered_at}). Banner above is page-load snapshot."
        )

    _live_holdings_chip()

    st.divider()

    # Top-row buttons with state-aware disabling
    c1, c2, c3, c4 = st.columns(4)
    running = status == "RUNNING"
    paused = status == "PAUSED"
    stopped = status == "STOPPED"

    if c1.button(
        "▶ START" if not running else "✓ RUNNING",
        width="stretch",
        type="primary" if not running else "secondary",
        disabled=running,
    ):
        _set_bot(status="RUNNING")
        st.toast("Bot started — first cycle will run shortly.", icon="▶")
        st.rerun()

    if c2.button(
        "⏸ PAUSE" if not paused else "✓ PAUSED",
        width="stretch",
        disabled=not running,
    ):
        _set_bot(status="PAUSED")
        st.toast("Bot paused.", icon="⏸")
        st.rerun()

    if c3.button(
        "⏹ STOP",
        width="stretch",
        disabled=stopped,
    ):
        _set_bot(status="STOPPED")
        st.toast("Bot stopped.", icon="⏹")
        st.rerun()

    if c4.button(
        "🚨 SQUARE-OFF ALL",
        width="stretch",
    ):
        if st.session_state.get("confirm_sqoff"):
            n = 0
            for p in open_positions():
                price = latest_price(p["ticker"]) or p["entry_price"]
                close_position(p["id"], price, reason="Manual square-off",
                               mode="manual")
                n += 1
            st.success(f"Squared off {n} positions.")
            st.session_state["confirm_sqoff"] = False
            st.rerun()
        else:
            st.session_state["confirm_sqoff"] = True
            st.warning("⚠ Click again within 10s to confirm — this will close **every** open position.")

    # Run Cycle Now
    # ------------------------------------------------------------------
    # The cycle takes 1–3 minutes (news scrape + 50-ticker yfinance fetch).
    # Blocking the Streamlit thread with `st.spinner` for that long causes
    # the browser to time out and the spinner to appear "stuck" forever.
    # Instead, we kick the cycle off in a background thread and surface
    # progress via the cycle_log table, which is also visible to the UI
    # even when the cycle is being driven by the separate scheduler process.
    st.divider()
    rcol1, rcol2 = st.columns([1, 3])
    if rcol1.button("⚡ Run Cycle Now", width="stretch",
                    help="Kicks off a cycle in the background. Status appears in 'Last cycle' below; refresh to see updates."):
        import threading

        def _bg_run():
            try:
                runner_mod.run_cycle(force=True, triggered_by="dashboard")
            except Exception:
                # Errors are persisted to cycle_log by run_cycle itself
                pass

        threading.Thread(target=_bg_run, daemon=True).start()
        st.toast("Cycle started in background — watch 'Last cycle' below.", icon="⚡")

    # ------------------------------------------------------------------
    # Last cycle summary (cross-process, reads from cycle_log table).
    # Wrapped in a fragment so it can refresh independently of the rest
    # of the page — see the auto-refresh section at the bottom of app.py.
    # ------------------------------------------------------------------
    with rcol2:
        @st.fragment(run_every=_frag_refresh)
        def _last_cycle_panel():
            row = runner_mod.last_cycle_summary()
            if not row:
                st.caption("No cycle has run yet — click **Run Cycle Now** or START the bot.")
                return
            status_pill = {
                "RUNNING": "🟡 RUNNING",
                "DONE":    "🟢 DONE",
                "ERROR":   "🔴 ERROR",
                "SKIPPED": "⚪ SKIPPED",
            }.get(row.get("status"), row.get("status") or "?")
            started = row.get("started_at") or ""
            finished = row.get("finished_at") or ""
            try:
                started_local = to_ist(started).strftime("%H:%M:%S IST · %d %b") if started else "—"
            except Exception:
                started_local = started[:19]
            duration = "—"
            if started and finished:
                try:
                    dt0 = pd.to_datetime(started)
                    dt1 = pd.to_datetime(finished)
                    duration = f"{(dt1 - dt0).total_seconds():.0f}s"
                except Exception:
                    pass
            triggered = row.get("triggered_by") or "?"
            st.caption(f"**Last cycle:** {status_pill}  ·  started {started_local}  ·  duration {duration}  ·  by `{triggered}`")
            summary_raw = row.get("summary")
            if summary_raw:
                try:
                    import json
                    s = json.loads(summary_raw) if isinstance(summary_raw, str) else summary_raw
                    # The cycle summary's `ts` field is UTC ISO. Other places
                    # in the UI show IST — convert here for consistency so the
                    # user doesn't have to mentally add 5h30m.
                    chips = []
                    for k, v in s.items():
                        if k == "ts" and isinstance(v, str) and "T" in v:
                            try:
                                v = to_ist(v).strftime("%H:%M:%S IST · %d %b")
                            except Exception:
                                pass
                        chips.append(f"`{k}={v}`")
                    st.markdown("  ".join(chips))
                except Exception:
                    st.caption(str(summary_raw)[:300])

        _last_cycle_panel()

    st.divider()

    # Mode toggle (consistent formatting — all options pre-padded for alignment)
    st.subheader("Mode")
    MODE_LABELS = {
        "manual":  "Manual approval   —  every trade needs your OK",
        "auto":    "Auto                          —  bot trades on its own",
        "dry_run": "Dry run                    —  signals only, no trades",
    }
    new_mode = st.radio(
        "Trading mode",
        options=["manual", "auto", "dry_run"],
        index=["manual", "auto", "dry_run"].index(mode),
        format_func=lambda m: MODE_LABELS[m],
        label_visibility="collapsed",
    )
    if new_mode != mode:
        _set_bot(mode=new_mode)
        st.toast(f"Mode switched to {new_mode}", icon="🔁")
        st.rerun()

    st.divider()

    # ------------------------------------------------------------------
    # Positional trading control
    # ------------------------------------------------------------------
    st.subheader("📅 Positional Trading")
    _pos_enabled = bool(bot.get("positional_enabled", 0))
    _pos_col1, _pos_col2 = st.columns([2, 3])
    with _pos_col1:
        _new_pos_enabled = st.toggle(
            "Enable positional module",
            value=_pos_enabled,
            help="When ON the positional runner scans at 08:45 IST and manages exits at 15:20 IST daily.",
        )
        if _new_pos_enabled != _pos_enabled:
            _set_bot(positional_enabled=int(_new_pos_enabled))
            st.toast(
                f"Positional module {'enabled' if _new_pos_enabled else 'disabled'}.",
                icon="📅",
            )
            st.rerun()
    with _pos_col2:
        try:
            with get_conn() as _pc:
                _n_pos = _pc.execute(
                    "SELECT COUNT(*) AS n FROM positions WHERE status='OPEN' AND trade_type='positional'"
                ).fetchone()["n"]
                _n_pos_pend = _pc.execute(
                    "SELECT COUNT(*) AS n FROM pending_approvals WHERE status='PENDING' AND trade_type='positional'"
                ).fetchone()["n"]
            from config import POSITIONAL_MAX_POSITIONS, POSITIONAL_SCAN_TIME, POSITIONAL_EXIT_TIME
            _pos_status = "🟢 ON" if _pos_enabled else "⚫ OFF"
            st.markdown(
                f"**Status:** {_pos_status} &nbsp;|&nbsp; "
                f"**Open positions:** {_n_pos}/{POSITIONAL_MAX_POSITIONS} &nbsp;|&nbsp; "
                f"**Pending approvals:** {_n_pos_pend}  \n"
                f"Pre-market scan: `{POSITIONAL_SCAN_TIME} IST` &nbsp;·&nbsp; "
                f"EOD exit check: `{POSITIONAL_EXIT_TIME} IST`"
            )
        except Exception:
            st.caption("Positional status unavailable.")

    st.divider()

    # Pending approvals queue
    st.subheader("📋 Pending Approvals")
    with get_conn() as conn:
        pending_rows = conn.execute(
            """SELECT * FROM pending_approvals
                WHERE status='PENDING'
                ORDER BY created_at DESC"""
        ).fetchall()

    if not pending_rows:
        st.caption("No pending approvals.")
    else:
        for r in pending_rows:
            r = dict(r)
            expires = datetime.fromisoformat(r["expires_at"])
            remaining = expires - datetime.now(timezone.utc).replace(tzinfo=None)
            mins = max(0, int(remaining.total_seconds() // 60))
            secs = max(0, int(remaining.total_seconds() % 60))
            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                with cols[0]:
                    st.markdown(
                        f"**{r['action']} {r['quantity']} × {r['ticker']} @ ₹{r['price']:.2f}**"
                    )
                    st.caption(
                        f"SL ₹{r['stop_loss']:.2f} | TP ₹{r['take_profit']:.2f} | "
                        f"Strategy: {r['strategy']} | Composite: {r['composite_score']:.1f}"
                    )
                    reason = r["reason"] or ""
                    st.caption(reason[:400] + ("…" if len(reason) > 400 else ""))
                    st.caption(f"⏱ Auto-reject in {mins}m {secs}s")
                with cols[1]:
                    if st.button("✅ Approve", key=f"appr_{r['id']}", width="stretch"):
                        with get_conn() as conn:
                            conn.execute(
                                """UPDATE pending_approvals
                                      SET status='APPROVED', decided_at=?
                                    WHERE id=?""",
                                (datetime.now(timezone.utc).isoformat(), int(r["id"])),
                            )
                        pos_id = runner_mod.execute_single_approval(int(r["id"]))
                        if pos_id:
                            st.toast(f"Executed — position {pos_id}", icon="✅")
                        else:
                            st.toast("Approval recorded; execution failed. Check logs.", icon="⚠")
                        st.rerun()
                with cols[2]:
                    if st.button("❌ Reject", key=f"rej_{r['id']}", width="stretch"):
                        with get_conn() as conn:
                            conn.execute(
                                """UPDATE pending_approvals
                                      SET status='REJECTED', decided_at=?
                                    WHERE id=?""",
                                (datetime.now(timezone.utc).isoformat(), int(r["id"])),
                            )
                        st.rerun()

    st.divider()

    # Runtime params
    st.subheader("⚙️ Runtime Parameters (live)")
    with st.form("runtime_params"):
        c1, c2, c3 = st.columns(3)
        max_pos = c1.number_input(
            "Max open positions",
            value=int(bot.get("max_open_positions", MAX_OPEN_POSITIONS)),
            min_value=1, max_value=20,
        )
        risk_pct = c2.number_input(
            "Risk per trade (%)",
            value=float(bot.get("risk_per_trade_pct", RISK_PER_TRADE_PCT)) * 100,
            min_value=0.5, max_value=20.0, step=0.5,
        )
        min_score = c3.number_input(
            "Min composite score",
            value=float(bot.get("min_composite_score", MIN_COMPOSITE_SCORE)),
            min_value=30.0, max_value=100.0, step=1.0,
        )
        c4, c5 = st.columns(2)
        sl = c4.number_input(
            "Stop-loss %",
            value=float(bot.get("stop_loss_pct", STOP_LOSS_PCT)) * 100,
            min_value=0.5, max_value=20.0, step=0.5,
        )
        tp = c5.number_input(
            "Take-profit %",
            value=float(bot.get("take_profit_pct", TAKE_PROFIT_PCT)) * 100,
            min_value=0.5, max_value=30.0, step=0.5,
        )
        if st.form_submit_button("💾 Save", width="stretch"):
            _set_bot(
                max_open_positions=int(max_pos),
                risk_per_trade_pct=risk_pct / 100,
                stop_loss_pct=sl / 100,
                take_profit_pct=tp / 100,
                min_composite_score=min_score,
            )
            st.success("Saved.")
            st.rerun()


# ==================================================================
# 2. Overview
# ==================================================================

with tab_overview:
    st.header("📊 Portfolio Overview")
    summary = portfolio_summary()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Value",
              f"₹{summary['total_value']:,.0f}",
              f"{summary['total_return_pct']:+.2f}%")
    c2.metric("Cash", f"₹{summary['cash']:,.0f}")
    c3.metric("Holdings", f"₹{summary['equity']:,.0f}")
    c4.metric("Realized P&L", f"₹{summary['realized_pnl']:,.0f}")
    c5.metric("Unrealized P&L", f"₹{summary['unrealized_pnl']:,.0f}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Sharpe ratio", summary["sharpe"])
    c2.metric("Sortino ratio", summary["sortino"])
    c3.metric("Max drawdown", f"{summary['max_dd_pct']:.2f}%")

    st.divider()
    st.subheader("Equity curve vs NIFTY 50")
    snaps = snapshots_df()
    if snaps.empty:
        st.info("No snapshots yet — start the bot or click 'Run Cycle Now'.")
    else:
        # Convert stored UTC timestamps to IST for display.
        snaps_local = snaps.copy()
        snaps_local["ts"] = to_ist(snaps_local["ts"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=snaps_local["ts"], y=snaps_local["total_value"],
            mode="lines", name="Portfolio", line=dict(color="#1f77b4", width=2),
        ))
        try:
            bench = benchmark_series(days=60)
            if bench is not None and not bench.empty:
                bench_idx = to_ist(bench.index)
                first = float(bench.iloc[0])
                bench_scaled = bench / first * INITIAL_CAPITAL
                fig.add_trace(go.Scatter(
                    x=bench_idx, y=bench_scaled.values,
                    mode="lines", name="NIFTY 50",
                    line=dict(color="#ff7f0e", dash="dot"),
                ))
        except Exception:
            pass
        fig.update_layout(
            height=380, margin=dict(l=0, r=0, t=30, b=0),
            xaxis_title="Time (IST)", yaxis_title="₹",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, width="stretch")


# ==================================================================
# 3. Positions & Trades
# ==================================================================

with tab_pos:
    st.header("💼 Positions & Trades")

    # ------------------------------------------------------------------
    # Open positions
    # ------------------------------------------------------------------
    # The panel is rendered as a Streamlit fragment with a USER-CONTROLLED
    # refresh interval (or fully paused). When paused or when the market
    # is closed there is no point burning CPU + bandwidth on yfinance
    # polling, so we default the interval to "Off" outside market hours.
    # The user can change the interval (or pause completely) at any time;
    # the new interval takes effect on the next page rerun.
    st.subheader("Open positions")

    # ----- Refresh controls -----
    REFRESH_OPTIONS: dict[str, int] = {
        "Off (paused)": 0,
        "Every 15s":   15,
        "Every 30s":   30,
        "Every 1 min": 60,
        "Every 2 min": 120,
        "Every 5 min": 300,
    }
    # Default: 30s during market hours, Off otherwise.
    if "op_refresh_secs" not in st.session_state:
        st.session_state["op_refresh_secs"] = 30 if market_is_open() else 0

    ctl_force, ctl_interval, ctl_spacer = st.columns([1, 1, 3])
    if ctl_force.button(
        "🔄 Force refresh prices",
        key="op_force_refresh",
        help="Bypass the yfinance disk cache and re-pull 5-minute candles right now. "
             "Works even when auto-refresh is paused.",
    ):
        st.session_state["op_force_refresh_at"] = datetime.now(timezone.utc).isoformat()
        st.rerun()  # re-render the panel immediately to honour the click

    # Find the current label that matches the saved interval (fall back to 30s).
    _values = list(REFRESH_OPTIONS.values())
    _current = st.session_state["op_refresh_secs"]
    _idx = _values.index(_current) if _current in _values else _values.index(30)
    chosen_label = ctl_interval.selectbox(
        "Auto-refresh",
        options=list(REFRESH_OPTIONS.keys()),
        index=_idx,
        key="op_refresh_choice",
        help="Pause auto-refresh to save CPU/bandwidth (e.g. when the market is closed). "
             "Force refresh button still works while paused.",
    )
    st.session_state["op_refresh_secs"] = REFRESH_OPTIONS[chosen_label]

    # ----- The panel itself (NOT decorated; we wrap it dynamically below) -----
    def _open_positions_panel():
        ops = open_positions()
        if not ops:
            st.caption("No open positions.")
            return
        # If the user clicked "Force refresh", bypass cache for THIS render.
        force_at = st.session_state.get("op_force_refresh_at")
        force_now = False
        if force_at:
            try:
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(force_at).replace(tzinfo=None)).total_seconds()
                force_now = age < 5  # only honour the click for the next render
            except Exception:
                force_now = False
        rows = []
        oldest_age_s = -1
        market_now_open = market_is_open()
        for p in ops:
            try:
                px, px_ts = latest_price_with_ts(
                    p["ticker"], use_cache=not force_now,
                )
            except Exception:
                px, px_ts = None, None
            if px is None:
                px = p["entry_price"]
            pnl = (px - p["entry_price"]) * p["quantity"]
            pnl_pct = (px / p["entry_price"] - 1) * 100 if p["entry_price"] else 0
            try:
                px_local = to_ist(px_ts).strftime("%H:%M IST") if px_ts is not None else "—"
            except Exception:
                px_local = "—"
            # Track staleness for a banner.
            if px_ts is not None:
                try:
                    age_s = (datetime.now(timezone.utc)
                             - pd.to_datetime(px_ts).to_pydatetime().astimezone(timezone.utc)
                             ).total_seconds()
                    oldest_age_s = max(oldest_age_s, age_s)
                except Exception:
                    pass
            # SIDE-AWARE display + P&L. Pre-migration positions default to LONG.
            # SHORT P&L = (entry - current) * qty (price drop = profit). The
            # dashboard previously assumed every position was LONG, which made
            # short-position P&L appear inverted. Now both directions render
            # correctly and a "Side" column makes it unambiguous.
            side_str = (p.get("side") or "LONG").upper()
            if side_str == "SHORT":
                pnl = (p["entry_price"] - px) * p["quantity"]
                pnl_pct = (1 - px / p["entry_price"]) * 100 if p["entry_price"] else 0
                side_chip = "🔻 SHORT"
            else:
                # LONG (already computed above for legacy callers, but
                # recompute here so the cell uses consistent logic).
                pnl = (px - p["entry_price"]) * p["quantity"]
                pnl_pct = (px / p["entry_price"] - 1) * 100 if p["entry_price"] else 0
                side_chip = "🔺 LONG"

            rows.append({
                "Side": side_chip,
                "Ticker": p["ticker"],
                "Qty": p["quantity"],
                "Entry": f"₹{p['entry_price']:.2f}",
                "Current": f"₹{px:.2f}",
                "Price as of": px_local,
                "SL": f"₹{p['stop_loss']:.2f}" if p["stop_loss"] else "—",
                "TP": f"₹{p['take_profit']:.2f}" if p["take_profit"] else "—",
                "Unreal P&L": _fmt_pnl(pnl),
                "%": f"{pnl_pct:+.2f}%",
                "Strategy": p["strategy"] or "—",
                "Entered": to_ist(p["entry_ts"]).strftime("%Y-%m-%d %H:%M IST"),
            })
        render_table(pd.DataFrame(rows))

        # Status caption (refresh state + freshness)
        rendered_at = datetime.now().strftime("%H:%M:%S")
        secs = st.session_state.get("op_refresh_secs", 30)
        if secs and secs > 0:
            cadence = f"🔄 Auto-refresh every {secs}s"
        else:
            cadence = "⏸ Auto-refresh paused"

        if market_now_open:
            if oldest_age_s < 0:
                fresh_msg = "Price source: 5-minute candles (intraday)."
            elif oldest_age_s <= 300:
                fresh_msg = "Prices are fresh (≤ 5 min old)."
            elif oldest_age_s <= 900:
                fresh_msg = (f"Oldest price ≈ {int(oldest_age_s/60)} min old — "
                             "yfinance throttling? Try Force refresh.")
            else:
                fresh_msg = (f"⚠ Oldest price is {int(oldest_age_s/60)} min old. "
                             "Click **Force refresh prices** to re-pull from yfinance.")
        else:
            fresh_msg = "Market is closed — 'Current' shows the most recent daily close."
        st.caption(f"{cadence}. Last redraw: {rendered_at}. {fresh_msg}")

    # ----- Dynamic fragment wrapping (run_every is a per-render decision) -----
    # `st.fragment` works as both a decorator AND a plain wrapper, so we can
    # apply it conditionally based on the user's chosen interval. When the
    # user picks "Off (paused)" we just render the panel once with no auto-
    # refresh — no timer, no background polling, no yfinance traffic.
    secs = st.session_state["op_refresh_secs"]
    if secs and secs > 0:
        st.fragment(run_every=secs)(_open_positions_panel)()
    else:
        _open_positions_panel()

    # =================================================================
    # 📑 Combined Trade Report
    # =================================================================
    # Two views in one place — toggle between:
    #   • "P&L summary" — one row per round-trip (LONG or SHORT) with the
    #     realised P&L. This is what most users want most of the time.
    #   • "Raw trade log" — every individual fill (BUY/SELL/SHORT/COVER/
    #     partial-T1). Useful when you need to audit a specific exit.
    # Date / direction / ticker filters apply to both views consistently.
    st.divider()
    st.subheader("📑 Trade report")

    @st.cache_data(ttl=30, show_spinner=False)
    def _cached_closed_positions_report():
        return closed_positions_report()

    @st.cache_data(ttl=30, show_spinner=False)
    def _cached_trades_df():
        return trades_df()

    rep = _cached_closed_positions_report()
    raw_trades = _cached_trades_df()

    if (rep is None or rep.empty) and (raw_trades is None or raw_trades.empty):
        st.caption("No trades yet.")
    else:
        # ----- Filters (shared across both views) -----
        today_ist = pd.Timestamp.now(tz="Asia/Kolkata").date()
        f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 2])
        view_mode = f1.radio(
            "View",
            ["P&L summary (per trade)", "Raw trade log (every fill)"],
            horizontal=False, key="trade_report_mode",
        )
        start = f2.date_input("From", value=today_ist, key="rep_start")
        end   = f3.date_input("To", value=today_ist, key="rep_end")
        side_f = f4.selectbox("Direction",
                              ["All", "LONG", "SHORT"], key="rep_side")
        ticker_f = f5.text_input("Ticker contains", "",
                                 key="rep_ticker").strip().upper()

        if view_mode.startswith("P&L"):
            # ---------- P&L summary view ----------
            if rep is None or rep.empty:
                st.caption("No closed positions yet.")
            else:
                rl = rep.copy()
                rl["closed_at_ts"] = to_ist(rl["closed_at"])
                rl["opened_at_ts"] = to_ist(rl["opened_at"])
                mask = (
                    (rl["closed_at_ts"].dt.tz_convert(None).dt.date >= start)
                    & (rl["closed_at_ts"].dt.tz_convert(None).dt.date <= end)
                )
                if side_f != "All":
                    mask &= rl["direction"] == side_f
                if ticker_f:
                    mask &= rl["ticker"].str.contains(ticker_f, na=False)
                view = rl[mask].copy()

                if view.empty:
                    st.caption("No closed positions match the filters.")
                else:
                    # Use _fmt_pnl_plain for st.metric — st.metric does not
                    # render HTML and the previous _fmt_pnl emitted span tags.
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Trades", len(view))
                    m2.metric("Total P&L",
                              _fmt_pnl_plain(float(view["pnl"].sum())))
                    wins = view[view["pnl"] > 0]
                    m3.metric("Win rate",
                              f"{len(wins)/len(view)*100:.1f}%")
                    m4.metric("Avg P&L",
                              _fmt_pnl_plain(float(view["pnl"].mean())))

                    disp = pd.DataFrame({
                        "Closed (IST)": view["closed_at_ts"].dt.strftime("%Y-%m-%d %H:%M IST"),
                        "Opened (IST)": view["opened_at_ts"].dt.strftime("%Y-%m-%d %H:%M IST"),
                        "Ticker": view["ticker"],
                        "Side": view["direction"],
                        "Qty": view["qty"],
                        "Entry": view["entry_price"].map(lambda x: f"₹{x:,.2f}"),
                        "Exit":  view["exit_price"].map(lambda x: f"₹{x:,.2f}"),
                        "P&L (₹)": view["pnl"].map(_fmt_pnl),
                        "Strategy": view["strategy"],
                    })
                    render_table(disp)

                    st.download_button(
                        "Download P&L report (CSV)",
                        view.drop(columns=["closed_at_ts", "opened_at_ts"])
                            .to_csv(index=False).encode(),
                        f"trade_pnl_{start}_to_{end}.csv", "text/csv",
                    )
        else:
            # ---------- Raw fill-by-fill log ----------
            if raw_trades is None or raw_trades.empty:
                st.caption("No trades yet.")
            else:
                rt = raw_trades.copy()
                rt["ts_ist"] = to_ist(rt["ts"])
                mask = (
                    (rt["ts_ist"].dt.tz_convert(None).dt.date >= start)
                    & (rt["ts_ist"].dt.tz_convert(None).dt.date <= end)
                )
                # Direction filter: BUY+SELL = LONG legs, SHORT+COVER = SHORT
                if side_f == "LONG":
                    mask &= rt["side"].isin(["BUY", "SELL"])
                elif side_f == "SHORT":
                    mask &= rt["side"].isin(["SHORT", "COVER"])
                if ticker_f:
                    mask &= rt["ticker"].str.contains(ticker_f, na=False)
                view = rt[mask].copy()

                if view.empty:
                    st.caption("No fills match the filters.")
                else:
                    m1, m2 = st.columns(2)
                    m1.metric("Fills shown", len(view))
                    m2.metric("Net cash flow",
                              _fmt_pnl_plain(float(view["net_value"].sum())))
                    disp = view.copy()
                    disp["ts"] = view["ts_ist"].dt.strftime("%Y-%m-%d %H:%M IST")
                    for col in ("price", "costs"):
                        if col in disp.columns:
                            disp[col] = disp[col].map(
                                lambda x: f"₹{x:,.2f}" if pd.notna(x) else "—"
                            )
                    disp["net_value"] = disp["net_value"].map(_fmt_pnl)
                    render_table(disp[[
                        "ts", "ticker", "side", "quantity", "price",
                        "costs", "net_value", "strategy", "mode", "reason",
                    ]])
                    st.download_button(
                        "Download raw trade log (CSV)",
                        view.drop(columns=["ts_ist"]).to_csv(index=False).encode(),
                        f"trades_raw_{start}_to_{end}.csv", "text/csv",
                    )


# ==================================================================
# 4. News & Sentiment
# ==================================================================

with tab_news:
    st.header("📰 News & Sentiment")

    # ------ Scraper status strip ------
    stats = news_db_stats()
    latest_txt = "never"
    if stats["latest"]:
        try:
            latest_local = to_ist(stats["latest"])
            latest_txt = latest_local.strftime("%Y-%m-%d %H:%M IST")
        except Exception:
            latest_txt = stats["latest"][:16].replace("T", " ")

    scol1, scol2, scol3, scol4 = st.columns([1, 1, 1, 1])
    scol1.metric("Total in DB", stats["total"])
    scol2.metric("Last 24h", stats["last_24h"])
    scol3.metric("Tagged to a ticker", stats["tagged"])
    scol4.markdown(f"**Latest article**<br><sub>{latest_txt}</sub>",
                   unsafe_allow_html=True)

    b1, b2, b3 = st.columns([1, 1, 2])
    if b1.button("📡 Scrape News Now", width="stretch",
                 help="Pull the RSS feeds immediately and re-score sentiment."):
        with st.spinner("Scraping feeds…"):
            try:
                n_new = scrape_all_news()
                n_tagged = retag_existing_news()
                score_news_items()
                st.success(f"Scraped {n_new} new articles. "
                           f"Re-tagged {n_tagged} existing rows with new name matcher.")
            except Exception as e:
                st.error(f"Scrape failed: {e}")
        st.rerun()

    if b2.button("🏷️ Re-tag existing (no fetch)", width="stretch",
                 help="Re-run the ticker/name matcher against articles already in "
                      "the DB. Useful after adding new aliases."):
        with st.spinner("Re-tagging…"):
            n = retag_existing_news()
        st.success(f"Re-tagged {n} rows.")
        st.rerun()

    st.divider()

    # ------------------------------------------------------------------
    # Sentiment leaderboard (Fix 6)
    # ------------------------------------------------------------------
    # A scan across the whole universe so the user can see which stocks
    # the news flow is currently most positive/negative on. Aggregates
    # the `news.sentiment` column, grouped by exploded ticker tags.
    st.subheader("📊 Sentiment Leaderboard")

    lb_open_tickers = [p["ticker"] for p in open_positions()]

    lcol1, lcol2, lcol3 = st.columns([1, 2, 2])
    lb_hours = lcol1.selectbox(
        "Lookback",
        options=[6, 24, 48, 168],
        index=1,
        format_func=lambda h: f"{h}h" if h < 168 else "1 week",
        key="lb_hours",
    )
    lb_scope = lcol2.selectbox(
        "Scope",
        options=["universe_with_news", "open_positions", "min_three"],
        index=0,
        format_func=lambda s: {
            "universe_with_news": "Universe (any tagged stock with news)",
            "open_positions": "Open positions only",
            "min_three": "Universe (≥3 articles)",
        }[s],
        key="lb_scope",
    )
    lb_sort = lcol3.selectbox(
        "Sort by",
        options=["n_desc", "avg_desc", "avg_asc", "ts_desc"],
        index=0,
        format_func=lambda s: {
            "n_desc": "Most articles first",
            "avg_desc": "Most positive first",
            "avg_asc": "Most negative first",
            "ts_desc": "Most recent first",
        }[s],
        key="lb_sort",
    )

    # Pull news rows in window. We do the ticker-explode in Python because
    # `tickers` is a comma-joined column.
    # Cutoff computed in Python so the SQL is dialect-agnostic
    # (SQLite's datetime('now', '-X hours') is not valid Postgres).
    lb_cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(lb_hours))).isoformat()
    with get_conn() as conn:
        news_rows = conn.execute(
            """SELECT ts, source, title, summary, url, tickers, sentiment
                 FROM news
                WHERE tickers IS NOT NULL
                  AND tickers <> ''
                  AND ts >= ?""",
            (lb_cutoff,),
        ).fetchall()
        # Sector lookup from fundamentals cache.
        sector_rows = conn.execute(
            "SELECT ticker, sector FROM fundamentals"
        ).fetchall()
    sector_map = {r["ticker"]: (r["sector"] or "") for r in sector_rows}

    # Aggregate per ticker.
    # We keep (sentiment, ts) tuples — the timestamp lets us compute a
    # recency-weighted average and a "latest sentiment" alongside the
    # simple mean. VADER is lexicon-based and easily fooled by financial
    # phrases ("knocked out of top 10" reads negative to a human but VADER
    # sees the strong word "top" and shrugs). Showing recent + breakdown
    # gives the user a clearer picture than a single mean.
    agg: dict[str, dict] = {}
    unprocessed = 0
    for r in news_rows:
        if r["sentiment"] is None:
            unprocessed += 1
            continue
        tickers = [t for t in (r["tickers"] or "").split(",") if t.strip()]
        for tk in tickers:
            d = agg.setdefault(tk, {
                "scored": [],   # list of (sentiment, ts_iso)
                "latest_ts": None,
                "latest_title": "", "latest_url": "",
                "latest_sentiment": None,
            })
            d["scored"].append((float(r["sentiment"]), r["ts"] or ""))
            if d["latest_ts"] is None or (r["ts"] or "") > d["latest_ts"]:
                d["latest_ts"] = r["ts"]
                d["latest_title"] = r["title"] or ""
                d["latest_url"] = r["url"] or ""
                d["latest_sentiment"] = float(r["sentiment"])

    if not agg:
        if unprocessed:
            st.info(
                f"{unprocessed} articles in the lookback window have no "
                "sentiment computed yet. Click **📡 Scrape News Now** above "
                "(re-runs the analyzer)."
            )
        else:
            st.caption(
                f"No tagged articles with sentiment in the last {lb_hours}h. "
                "Try a longer lookback or scrape news first."
            )
    else:
        # Apply scope filter.
        if lb_scope == "open_positions":
            agg = {k: v for k, v in agg.items() if k in lb_open_tickers}
        elif lb_scope == "min_three":
            agg = {k: v for k, v in agg.items() if len(v["scored"]) >= 3}

        # Recency weighting: half-life = lookback / 4 (so a 24h lookback gives
        # a 6h half-life — yesterday's article counts ~half as much as the
        # most recent one). This makes the headline number track the *latest*
        # tone of the news flow instead of being dominated by stale articles.
        import math
        half_life_h = max(1.0, float(lb_hours) / 4.0)
        # Use the latest article's ts in the window as the reference point so
        # weights are meaningful even if the wall clock has drifted.
        cutoff_dt = pd.to_datetime(lb_cutoff)

        # Build leaderboard rows.
        rows = []
        for tk, d in agg.items():
            scored = d["scored"]
            scores_only = [s for s, _ in scored]
            n_pos = sum(1 for s in scores_only if s >= 0.05)
            n_neg = sum(1 for s in scores_only if s <= -0.05)
            n_neu = len(scores_only) - n_pos - n_neg
            avg = sum(scores_only) / len(scores_only)
            mn, mx = min(scores_only), max(scores_only)

            # Recency-weighted average
            wsum = 0.0
            wtot = 0.0
            for s, ts_iso in scored:
                try:
                    age_h = (pd.to_datetime(ts_iso) - cutoff_dt).total_seconds() / 3600.0
                except Exception:
                    age_h = 0.0
                w = math.pow(0.5, max(0.0, (lb_hours - age_h)) / half_life_h)
                wsum += s * w
                wtot += w
            wavg = (wsum / wtot) if wtot else avg

            try:
                latest_local = to_ist(d["latest_ts"]).strftime("%H:%M IST · %d %b")
            except Exception:
                latest_local = (d["latest_ts"] or "")[:16]

            def _pill(val: float) -> str:
                if val > 0.15:
                    cls = "badge-green"
                elif val < -0.15:
                    cls = "badge-red"
                else:
                    cls = ""
                return (f"<span class='{cls}'>{val:+.2f}</span>"
                        if cls else f"{val:+.2f}")

            avg_html = _pill(avg)
            wavg_html = _pill(wavg)
            latest_sent = d.get("latest_sentiment")
            latest_html = _pill(latest_sent) if latest_sent is not None else "—"

            title = (d["latest_title"] or "")
            if len(title) > 80:
                title = title[:77] + "…"
            link_html = (f"<a href='{d['latest_url']}' target='_blank'>{title}</a>"
                         if d["latest_url"] else title)

            ticker_label = tk + (" 🎯" if tk in lb_open_tickers else "")
            rows.append({
                "Ticker": ticker_label,
                "Sector": sector_map.get(tk, "—") or "—",
                "Articles": len(scored),
                "+/0/−": f"{n_pos}/{n_neu}/{n_neg}",
                "Avg": avg_html,
                "Recent-Wt": wavg_html,
                "Latest": latest_html,
                "Latest Headline": link_html,
                "Last Update": latest_local,
                "_avg_raw": avg,
                "_wavg_raw": wavg,
                "_latest_raw": latest_sent if latest_sent is not None else 0.0,
                "_n": len(scored),
                "_ts": d["latest_ts"] or "",
            })

        # Sort.
        if lb_sort == "n_desc":
            rows.sort(key=lambda r: (-r["_n"], -r["_wavg_raw"]))
        elif lb_sort == "avg_desc":
            rows.sort(key=lambda r: -r["_wavg_raw"])  # use weighted avg
        elif lb_sort == "avg_asc":
            rows.sort(key=lambda r: r["_wavg_raw"])
        elif lb_sort == "ts_desc":
            rows.sort(key=lambda r: r["_ts"], reverse=True)

        # Strip helper cols before rendering.
        view_df = pd.DataFrame(rows).drop(
            columns=["_avg_raw", "_wavg_raw", "_latest_raw", "_n", "_ts"]
        )
        render_table(view_df)

        if unprocessed:
            st.caption(
                f"Excluded {unprocessed} articles in this window with no "
                "sentiment computed yet — click **📡 Scrape News Now** above "
                "to score them."
            )
        st.caption(
            "🎯 marks tickers you currently hold.  "
            "**Avg** = simple mean across all articles in the window.  "
            "**Recent-Wt** = recency-weighted (half-life ≈ window/4) — better "
            "for spotting tone shifts.  **Latest** = the sentiment of the "
            "single most recent article (the headline shown).  Colour: "
            "green > +0.15, red < −0.15.  Note: VADER is lexicon-based and "
            "can miss financial phrasing — when **Latest** disagrees with "
            "**Avg**, treat the article itself as the source of truth."
        )

    st.divider()

    # ------------------------------------------------------------------
    # Per-ticker view (Fix 2 — stable widget state)
    # ------------------------------------------------------------------
    # `key="news_ticker"` pins the value into st.session_state so it
    # survives reruns (clicks, periodic refreshes). Without an explicit
    # key, Streamlit synthesises one from the widget arguments and the
    # input flickers back to the default whenever something else triggers
    # a rerun (this is what was causing the BALRAMCHIN snap-back).
    ops = open_positions()
    universe_tickers = [p["ticker"] for p in ops]

    # Initialise once, then let the widget own session state.
    if "news_ticker" not in st.session_state:
        st.session_state["news_ticker"] = (
            universe_tickers[0] if universe_tickers else "RELIANCE"
        )

    st.subheader("🔎 Per-ticker view")
    tcol1, tcol2 = st.columns([3, 1])
    picked = tcol1.text_input(
        "Ticker (NSE symbol, without .NS)",
        key="news_ticker",
    ).strip().upper()
    hours = tcol2.selectbox(
        "Lookback",
        options=[24, 48, 72, 168],
        index=1,
        format_func=lambda h: f"{h}h" if h < 168 else "1 week",
        key="news_lookback_hours",
    )

    if picked:
        items = recent_news_for_ticker(picked, hours=hours, limit=50)
        if not items:
            st.info(
                f"No news matched **{picked}** in the last {hours}h.\n\n"
                "Things to try:\n"
                "- Click **📡 Scrape News Now** above to pull the RSS feeds.\n"
                "- Click **🏷️ Re-tag existing** to apply the company-name matcher "
                "to articles already in the DB.\n"
                "- Try a large-cap symbol like `RELIANCE`, `TCS`, `HDFCBANK`, "
                "`INFY`, `SBIN` — news coverage is uneven below that."
            )
        else:
            scores = [n["sentiment"] for n in items if n["sentiment"] is not None]
            avg = sum(scores) / len(scores) if scores else 0
            st.metric("Avg sentiment", f"{avg:+.2f}",
                      help="Range -1 (very bearish) to +1 (very bullish)")
            for n in items:
                s = n["sentiment"] or 0
                emoji = "🟢" if s > 0.2 else "🔴" if s < -0.2 else "⚪"
                try:
                    ts_local = to_ist(n["ts"]).strftime("%Y-%m-%d %H:%M IST")
                except Exception:
                    ts_local = n["ts"][:16].replace("T", " ")
                st.markdown(
                    f"{emoji} **[{n['title']}]({n['url']})**  "
                    f"<sub>{n['source']} · {ts_local} · "
                    f"sentiment {s:+.2f}</sub>",
                    unsafe_allow_html=True,
                )


# ==================================================================
# 5. Fundamentals
# ==================================================================

with tab_fund:
    st.header("📈 Fundamentals")
    st.caption(
        "Source: yfinance. Growth columns are smoothed TTM-vs-prior-TTM "
        "(or 3-yr CAGR fallback) — not yfinance's raw single-quarter YoY, "
        "which can blow up on low-base recovery quarters. "
        "🏦 marks banks: D/E is suppressed (deposits ARE the liability) and "
        "Net Margin is yfinance-computed and bank-adjusted. "
        "Click 🔗 to cross-check on screener.in."
    )
    df = query_df(
        "SELECT ticker, sector, industry, fundamental_score, pe_ratio, roe, "
        "debt_to_equity, earnings_growth, revenue_growth, profit_margin, "
        "dividend_yield, market_cap, fetched_at "
        "FROM fundamentals ORDER BY fundamental_score DESC LIMIT 100"
    )
    if df.empty:
        st.caption("No fundamentals cached yet — signals will populate this table.")
    else:
        def _pct(v):
            if pd.isna(v) or v is None:
                return "—"
            return f"{float(v) * 100:+.1f}%" if v != 0 else "0.0%"

        def _ratio(v):
            if pd.isna(v) or v is None:
                return "—"
            return f"{float(v):.2f}"

        def _money(v):
            if pd.isna(v) or v is None:
                return "—"
            return f"₹{v/1e7:,.0f} Cr"

        def _ist(s):
            try:
                return to_ist(s).strftime("%Y-%m-%d %H:%M IST")
            except Exception:
                return (s or "")[:16].replace("T", " ")

        # Mark banks for ticker label and D/E suppression.
        df["_bank"] = df.apply(
            lambda r: is_bank(r.get("sector") or "", r.get("industry") or ""),
            axis=1,
        )

        view = pd.DataFrame()
        view["Ticker"] = df.apply(
            lambda r: f"{'🏦 ' if r['_bank'] else ''}{r['ticker']}",
            axis=1,
        )
        view["Sector"] = df["sector"].fillna("—").replace("", "—")
        view["Score (0-100)"] = df["fundamental_score"].map(
            lambda v: f"{v:.1f}" if pd.notna(v) else "—"
        )
        view["P/E (TTM)"] = df["pe_ratio"].map(
            lambda v: f"{v:.1f}" if pd.notna(v) else "—"
        )
        view["ROE"] = df["roe"].map(_pct)
        # D/E is suppressed for banks
        view["D/E"] = df.apply(
            lambda r: ("n/a (bank)" if r["_bank"]
                       else _ratio(r["debt_to_equity"])),
            axis=1,
        )
        view["Earnings YoY"] = df["earnings_growth"].map(_pct)
        view["Revenue YoY"] = df["revenue_growth"].map(_pct)
        # Net margin gets a bank-warning tooltip via title attribute.
        def _net_margin_html(r):
            v = r["profit_margin"]
            label = _pct(v)
            if r["_bank"] and label != "—":
                return (f"<span title='Bank — yfinance margin is closer to a "
                        f"NIM derivative than a clean net margin'>"
                        f"{label} *</span>")
            return label
        view["Net Margin"] = df.apply(_net_margin_html, axis=1)
        view["Div Yield"] = df["dividend_yield"].map(_pct)
        view["Market Cap"] = df["market_cap"].map(_money)
        view["Fetched (IST)"] = df["fetched_at"].map(_ist)
        view["Cross-check"] = df["ticker"].map(
            lambda t: f"<a href='{screener_url(t)}' target='_blank'>🔗 screener</a>"
        )

        render_table(view)
        st.caption(
            "*Net Margin for banks is the yfinance `profitMargins` value, "
            "which is closer to a Net-Interest-Margin derivative than a "
            "clean net margin. Treat with caution and cross-check on screener."
        )


# ==================================================================
# 6. Analytics
# ==================================================================

with tab_analytics:
    st.header("📉 Analytics")
    stats = trade_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total trades", stats.get("total_trades", 0))
    c2.metric("Win rate", f"{stats.get('win_rate', 0)}%")
    c3.metric("Profit factor", stats.get("profit_factor", 0))
    c4.metric("Total P&L", f"₹{stats.get('total_pnl', 0):,.0f}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Avg win", f"₹{stats.get('avg_win', 0):,.0f}")
    c2.metric("Avg loss", f"₹{stats.get('avg_loss', 0):,.0f}")
    c3.metric(
        "Best / Worst",
        f"{stats.get('best_trade', 0):+.0f} / {stats.get('worst_trade', 0):+.0f}",
    )

    st.divider()
    st.subheader("By strategy")
    sb = strategy_breakdown()
    if sb.empty:
        st.caption("No closed trades yet.")
    else:
        render_table(sb)

    st.divider()
    st.subheader("Drawdown")
    snaps = snapshots_df()
    if not snaps.empty:
        snaps_local = snaps.copy()
        snaps_local["ts"] = to_ist(snaps_local["ts"])
        equity = snaps_local.set_index("ts")["total_value"]
        cummax = equity.cummax()
        dd = (equity - cummax) / cummax.replace(0, pd.NA) * 100
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dd.index, y=dd.values.astype(float), fill="tozeroy",
            line=dict(color="#d62728"), name="Drawdown %",
        ))
        fig.update_layout(
            height=280, margin=dict(l=0, r=0, t=30, b=0), yaxis_title="%",
        )
        st.plotly_chart(fig, width="stretch")


# ==================================================================
# 7. Long-Term Research (Phase A)
# ==================================================================

with tab_lt_research:
    st.header("🔬 Long-Term Research")
    st.caption(
        "Quality-filtered NIFTY-500 candidates for long-horizon (1+ year) "
        "and tactical (2-12 week) positions. Universe rebuild runs on demand; "
        "a typical full pass over the NIFTY 500 takes 25-30 minutes the first "
        "time (rate-limited at 3s/request to be polite to screener.in) and "
        "~3-5 minutes on subsequent runs thanks to the 24h HTML cache."
    )

    # Lazy import — these modules pull in beautifulsoup4 / requests / db, and
    # we only want that overhead for users who open this tab.
    try:
        from db.models import query_df as _ltq_query_df  # type: ignore
        from longterm.tasks import run_phase_a as _lt_run_phase_a
        _LT_IMPORT_OK = True
        _LT_IMPORT_ERR = None
    except Exception as _e:  # pragma: no cover
        _LT_IMPORT_OK = False
        _LT_IMPORT_ERR = str(_e)

    if not _LT_IMPORT_OK:
        st.error(f"Long-term module import failed: {_LT_IMPORT_ERR}")
    else:
        # ----- Controls -----
        ctrl_l, ctrl_m, ctrl_r = st.columns([2, 2, 3])
        with ctrl_l:
            lt_limit = st.number_input(
                "Limit (0 = full NIFTY 500)",
                min_value=0, max_value=600, value=10, step=10,
                help=(
                    "Set a small number (e.g. 10) for a smoke-test the first "
                    "time. Set to 0 to run the full 500."
                ),
            )
            lt_force = st.checkbox(
                "Force re-fetch (bypass 24h HTML cache)", value=False
            )
        with ctrl_m:
            lt_score_only = st.checkbox(
                "Score only (skip universe rebuild)", value=False,
                help=(
                    "If you've already built the universe and just want to "
                    "re-run the 5-bucket scorer, tick this."
                ),
            )
            lt_skip_existing = st.checkbox(
                "Resume mode — only process tickers not yet in universe",
                value=True,
                help=(
                    "RECOMMENDED for the second pass after an interrupted "
                    "run. Skips every ticker already present in lt_universe "
                    "(passed OR filtered) and only scrapes the missing ones. "
                    "Pair with Limit=0 to process the remaining ~167 of the "
                    "NIFTY 500 without redoing the first 333."
                ),
            )
            run_btn = st.button("🚀 Run Phase A pipeline", type="primary",
                                width="stretch")
        with ctrl_r:
            st.markdown(
                "**Hard filters applied to NIFTY 500:**  \n"
                "• Market cap ≥ ₹1,000 cr  \n"
                "• At least one of FII or DII present  \n"
                "• Promoter pledge ≤ 50%  \n"
                "• ≥ 5 years of P&L history"
            )

        if run_btn:
            limit_arg = None if lt_limit == 0 else int(lt_limit)
            prog = st.progress(0.0, text="Starting Phase A...")
            status = st.empty()

            # The pipeline is synchronous and rate-limited. We DON'T thread
            # this — Streamlit's session state is not thread-safe and the
            # progress bar would only be flushed on rerun anyway. The user
            # will see live progress because the callback updates the UI
            # widgets in-place.
            def _cb(stage, idx, total, ticker, info):
                pct = idx / max(total, 1)
                prog.progress(min(pct, 1.0), text=f"{stage}: {idx}/{total}  {ticker}")

            try:
                with st.spinner("Running Phase A — see progress below..."):
                    res = _lt_run_phase_a(
                        limit=limit_arg,
                        force=lt_force,
                        score_only=lt_score_only,
                        skip_existing=lt_skip_existing,
                        progress_cb=_cb,
                    )
                prog.progress(1.0, text="Done")
                status.success(
                    f"Universe: {res.get('universe', {})}  ·  "
                    f"Quality: {res.get('quality', {})}"
                )
            except Exception as e:
                prog.empty()
                status.error(f"Phase A failed: {e}")

        st.divider()

        # ----- Universe coverage summary -----
        # Tells the user EXACTLY how many tickers are scored vs filtered out
        # vs failed-to-scrape, so they can verify all 500 NIFTY names made
        # it through (or see which ones didn't).
        # Cached: this used to re-run on EVERY widget change (slider, top-N)
        # because Streamlit reruns the whole tab — 5 COUNT(*) queries × every
        # keystroke felt sluggish. 30s TTL is fine; Phase A takes minutes.
        @st.cache_data(ttl=30, show_spinner=False)
        def _lt_coverage_counts():
            with get_conn() as conn:
                u_total  = conn.execute("SELECT COUNT(*) AS n FROM lt_universe").fetchone()["n"]
                u_passed = conn.execute("SELECT COUNT(*) AS n FROM lt_universe WHERE in_universe=1").fetchone()["n"]
                u_failed = conn.execute("SELECT COUNT(*) AS n FROM lt_universe WHERE in_universe=0").fetchone()["n"]
                u_scrape = conn.execute(
                    "SELECT COUNT(*) AS n FROM lt_universe "
                    "WHERE filter_reason IN ('scrape_failed','scrape_exception')"
                ).fetchone()["n"]
                q_total  = conn.execute("SELECT COUNT(*) AS n FROM lt_quality").fetchone()["n"]
                # Reason breakdown for the failure expander.
                rb = conn.execute(
                    "SELECT COALESCE(filter_reason,'(none)') AS reason, COUNT(*) AS n "
                    "FROM lt_universe WHERE in_universe=0 "
                    "GROUP BY filter_reason ORDER BY n DESC"
                ).fetchall()
            return u_total, u_passed, u_failed, u_scrape, q_total, [(r["reason"], r["n"]) for r in rb]

        try:
            _u_total, _u_passed, _u_failed, _u_scrape_failed, _q_total, _reason_breakdown = _lt_coverage_counts()
            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("Tickers checked", f"{_u_total}")
            mc2.metric("Passed hard filters", f"{_u_passed}")
            mc3.metric("Filtered out", f"{_u_failed}")
            mc4.metric("Scrape failures", f"{_u_scrape_failed}")
            mc5.metric("Quality-scored", f"{_q_total}")
            st.caption(
                f"Quality scoring runs on the **passed** set ({_u_passed}). "
                f"If 'Tickers checked' is below your input universe (e.g. 500 "
                f"for NIFTY 500), some tickers haven't been processed yet — "
                f"re-run **Run Phase A pipeline** above with **Limit=0**. "
                f"Counts cached for 30s — click **Refresh counts** if you "
                f"just finished a Phase A run."
            )
            if st.button("🔄 Refresh counts", key="lt_refresh_counts"):
                _lt_coverage_counts.clear()
                st.rerun()
            if _reason_breakdown:
                with st.expander(f"Why were {_u_failed} tickers filtered out?"):
                    for reason, n in _reason_breakdown:
                        st.write(f"• **{reason}** — {n}")
        except Exception as e:
            st.caption(f"(universe summary unavailable — {e})")

        # ----- Top candidates table -----
        st.subheader("Top candidates by quality score")
        # Cache the JOIN for 30s. Without this, every slider/number_input
        # tweak re-issues the query AND re-renders the plotly Table — that's
        # the "ages to respond" the user reported.
        @st.cache_data(ttl=30, show_spinner=False)
        def _lt_candidates_df():
            return _ltq_query_df(
                """
                SELECT q.ticker,
                       q.total_score,
                       q.profitability_score,
                       q.cash_quality_score,
                       q.solvency_score,
                       q.growth_score,
                       q.governance_score,
                       u.market_cap,
                       u.fii_pct, u.dii_pct,
                       u.fii_qoq_change, u.dii_qoq_change,
                       u.promoter_holding_pct, u.promoter_pledge_pct,
                       q.scored_at
                FROM lt_quality q
                LEFT JOIN lt_universe u USING (ticker)
                ORDER BY q.total_score DESC
                """
            )

        try:
            df = _lt_candidates_df()
        except Exception as e:
            df = None
            st.info(
                f"No quality scores yet. Click **Run Phase A pipeline** above. "
                f"(detail: {e})"
            )

        if df is not None and not df.empty:
            # Filter row — added a ticker text search so the user can jump
            # straight to e.g. "RELIANCE" or filter to "BANK*" names.
            f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
            with f1:
                min_score = st.slider(
                    "Min total score", 0, 100, 0, step=5
                )
            with f2:
                ticker_q = st.text_input(
                    "Ticker contains", value="",
                    placeholder="e.g. RELI, BANK, INFY",
                ).strip().upper()
            with f3:
                only_fii_up = st.checkbox("FII ↑ vs prev quarter", value=False)
                only_dii_up = st.checkbox("DII ↑ vs prev quarter", value=False)
            with f4:
                top_n = st.number_input(
                    "Show top N", min_value=10, max_value=500, value=50, step=10
                )

            view = df[df["total_score"] >= float(min_score)].copy()
            if ticker_q:
                view = view[view["ticker"].str.upper().str.contains(ticker_q, na=False)]
            if only_fii_up:
                view = view[view["fii_qoq_change"].fillna(-1) > 0]
            if only_dii_up:
                view = view[view["dii_qoq_change"].fillna(-1) > 0]
            st.caption(f"Showing **{min(len(view), int(top_n))}** of **{len(df)}** scored candidates after filters.")
            view = view.head(int(top_n))

            # Format for display
            # NOTE: We deliberately render with plotly's go.Table instead of
            # st.dataframe here. Streamlit lazy-imports pyarrow inside
            # st.dataframe(), and pyarrow's DLL is being blocked by Smart App
            # Control on this machine. go.Table renders as plain HTML/SVG and
            # has no pyarrow dependency — so this tab keeps working even if
            # SAC is still blocking pyarrow.
            disp = view.rename(columns={
                "ticker": "Ticker",
                "total_score": "Score (0-100)",
                "profitability_score": "Profit (25)",
                "cash_quality_score": "Cash (20)",
                "solvency_score": "Solvency (15)",
                "growth_score": "Growth (20)",
                "governance_score": "Govern (20)",
                "market_cap": "Mkt Cap (cr)",
                "fii_pct": "FII %",
                "dii_pct": "DII %",
                "fii_qoq_change": "FII QoQ Δ",
                "dii_qoq_change": "DII QoQ Δ",
                "promoter_holding_pct": "Promoter %",
                "promoter_pledge_pct": "Pledge %",
                "scored_at": "Scored at (UTC)",
            })
            # Round numeric columns for readability before piping to Table.
            disp_fmt = disp.copy()
            for col in disp_fmt.select_dtypes(include="number").columns:
                disp_fmt[col] = disp_fmt[col].round(2)
            tbl = go.Figure(data=[go.Table(
                header=dict(
                    values=[f"<b>{c}</b>" for c in disp_fmt.columns],
                    fill_color="#1f3a68", font=dict(color="white"),
                    align="left",
                ),
                cells=dict(
                    values=[disp_fmt[c].astype(object).where(
                        disp_fmt[c].notna(), "—"
                    ) for c in disp_fmt.columns],
                    align="left",
                ),
            )])
            tbl.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=min(80 + 28 * len(disp_fmt), 700),
            )
            st.plotly_chart(tbl, width="stretch")

            # ----- Drilldown -----
            st.subheader("Drill into a candidate")
            sel = st.selectbox(
                "Pick a ticker", options=view["ticker"].tolist(),
                key="lt_drilldown",
            )
            if sel:
                row = view[view["ticker"] == sel].iloc[0]
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Profitability", f"{row['profitability_score']:.0f} / 25")
                c2.metric("Cash quality", f"{row['cash_quality_score']:.0f} / 20")
                c3.metric("Solvency", f"{row['solvency_score']:.0f} / 15")
                c4.metric("Growth", f"{row['growth_score']:.0f} / 20")
                c5.metric("Governance", f"{row['governance_score']:.0f} / 20")
                st.caption(
                    f"Total **{row['total_score']:.1f}** / 100 — "
                    f"Mkt cap ₹{row['market_cap']:,.0f} cr · "
                    f"Promoter {row['promoter_holding_pct']}% · "
                    f"Pledge {row['promoter_pledge_pct']}% · "
                    f"FII {row['fii_pct']}% (QoQ Δ {row['fii_qoq_change']}) · "
                    f"DII {row['dii_pct']}% (QoQ Δ {row['dii_qoq_change']})"
                )
                st.markdown(
                    f"[Open on screener.in]"
                    f"(https://www.screener.in/company/{sel}/consolidated/)"
                )

        # ----- Coverage gaps -----
        st.divider()
        with st.expander("Coverage gaps (universe failures)"):
            try:
                gaps = _ltq_query_df(
                    """
                    SELECT ticker, filter_reason, market_cap,
                           promoter_pledge_pct, fii_pct, dii_pct,
                           last_filtered_at
                    FROM lt_universe
                    WHERE in_universe = 0
                    ORDER BY last_filtered_at DESC
                    """
                )
                if gaps is not None and not gaps.empty:
                    st.caption(
                        f"{len(gaps)} ticker(s) excluded by hard filters or "
                        f"failed to scrape."
                    )
                    # Plotly Table — no pyarrow dependency.
                    gaps_fmt = gaps.copy()
                    for col in gaps_fmt.select_dtypes(include="number").columns:
                        gaps_fmt[col] = gaps_fmt[col].round(2)
                    gtbl = go.Figure(data=[go.Table(
                        header=dict(
                            values=[f"<b>{c}</b>" for c in gaps_fmt.columns],
                            fill_color="#7a3a3a", font=dict(color="white"),
                            align="left",
                        ),
                        cells=dict(
                            values=[gaps_fmt[c].astype(object).where(
                                gaps_fmt[c].notna(), "—"
                            ) for c in gaps_fmt.columns],
                            align="left",
                        ),
                    )])
                    gtbl.update_layout(
                        margin=dict(l=0, r=0, t=10, b=0),
                        height=min(80 + 28 * len(gaps_fmt), 500),
                    )
                    st.plotly_chart(gtbl, width="stretch")
                else:
                    st.caption("No coverage gaps recorded yet.")
            except Exception as e:
                st.caption(f"(no universe table yet — {e})")


# ==================================================================
# Auto-refresh: REMOVED in favour of `st.fragment(run_every=...)` panels.
# ==================================================================
# The previous `time.sleep(refresh_secs) + st.rerun()` pattern caused the
# entire page to grey out for 3-5 seconds on every tick (full Streamlit
# rerun re-imports modules and re-runs every widget callback). Now only
# the small "live" panels (last cycle status, sidebar clock) refresh on
# a timer via fragments — leaving the rest of the UI responsive. Click
# "Refresh now" in the sidebar for a full reload.

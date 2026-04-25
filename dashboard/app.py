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
    portfolio_summary,
    strategy_breakdown,
    trade_stats,
)
from data.fetcher import latest_price, market_is_open
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


init_db()


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
    vals.append(datetime.utcnow().isoformat())
    with get_conn() as conn:
        conn.execute(
            f"UPDATE bot_control SET {sets}, updated_at=? WHERE id=1", vals
        )


def _now_ist() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _fmt_pnl(val: float) -> str:
    cls = "badge-green" if val > 0 else "badge-red" if val < 0 else ""
    return f'<span class="{cls}">{"₹" if cls else ""}{val:+,.2f}</span>' if cls else f"₹{val:+,.2f}"


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

    if market_is_open():
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

    # Default OFF — keeps the tab calm. Flip on when you want live updates.
    # We intentionally do NOT use streamlit-autorefresh (custom component →
    # pyarrow → SAC block) and we do NOT use HTML meta-refresh (full browser
    # reload → flash + tab reset + interrupts button handlers).
    # Instead we use a Streamlit-native rerun at the end of the script.
    auto_refresh = st.checkbox("Auto-refresh every 15s", value=False,
                                help="Triggers a Streamlit rerun every 15s. "
                                     "Keeps your current tab. Uncheck to stop.")
    refresh_secs = 15

    if st.button("🔄 Refresh now", width="stretch"):
        st.rerun()

    # Last cycle info
    last = runner_mod.LAST_CYCLE
    last_ts = runner_mod.LAST_CYCLE_TS
    if last_ts:
        age = (datetime.utcnow() - last_ts).total_seconds()
        st.caption(f"Last bot cycle: {int(age)}s ago")
    else:
        st.caption("Bot has not run a cycle yet")

    st.caption(f"Dashboard rendered: {datetime.now().strftime('%H:%M:%S')}")


# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------

tab_ctrl, tab_overview, tab_pos, tab_news, tab_fund, tab_analytics = st.tabs([
    "🎛️ Control Panel",
    "📊 Overview",
    "💼 Positions & Trades",
    "📰 News & Sentiment",
    "📈 Fundamentals",
    "📉 Analytics",
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
    open_count = len(open_positions())
    max_pos_now = int(bot.get("max_open_positions", MAX_OPEN_POSITIONS))
    uni_info = universe_info()

    cap_pct = (open_count / max_pos_now * 100) if max_pos_now else 0
    cap_color = "#1bc47d" if cap_pct < 60 else "#ffc000" if cap_pct < 100 else "#ff4b4b"
    cap_msg = f"Holding <b>{open_count}/{max_pos_now}</b> positions"
    if open_count >= max_pos_now:
        cap_msg += " — <b>at capacity</b>; no new entries until a position closes or you square-off."
    elif open_count >= max_pos_now - 1:
        cap_msg += " — only 1 slot left."
    else:
        cap_msg += f" — {max_pos_now - open_count} slots free."

    bcap, buni = st.columns([3, 2])
    bcap.markdown(
        f"<div style='background: rgba(128,128,128,0.10); border-left: 4px solid {cap_color};"
        f" padding: 10px 14px; border-radius: 6px;'>📦 {cap_msg}</div>",
        unsafe_allow_html=True,
    )
    buni.markdown(
        f"<div style='background: rgba(128,128,128,0.10); border-left: 4px solid #1f77b4;"
        f" padding: 10px 14px; border-radius: 6px;'>"
        f"🌐 Tracking <b>{uni_info['n']}</b> tickers · "
        f"<sub>source: {uni_info['source']}</sub></div>",
        unsafe_allow_html=True,
    )

    # ----- Recent signals (so user can see WHY no trade was placed) -----
    with st.expander("🧭 Recent signals from the bot (why nothing was placed?)",
                      expanded=False):
        with get_conn() as conn:
            sig_rows = conn.execute(
                """SELECT ts, ticker, action, strategy, composite_score,
                          technical_score, fundamental_score, sentiment_score,
                          price, reason, taken
                     FROM signals
                    ORDER BY ts DESC
                    LIMIT 30"""
            ).fetchall()
        if not sig_rows:
            st.caption("No signals recorded yet. Click **⚡ Run Cycle Now** "
                       "below to force one.")
        else:
            min_score = float(bot.get("min_composite_score", MIN_COMPOSITE_SCORE))
            sig_view = []
            for r in sig_rows:
                cs = r["composite_score"] or 0.0
                action = r["action"] or "-"
                # Why was this signal not actionable?
                if r["taken"]:
                    why = "✅ taken"
                elif action != "BUY":
                    why = "—  not BUY"
                elif cs < min_score:
                    why = f"🚫 score {cs:.0f} < threshold {min_score:.0f}"
                elif open_count >= max_pos_now:
                    why = "🚫 at capacity"
                else:
                    why = "⏳ pending / queued"
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
            render_table(pd.DataFrame(sig_view))

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
    st.divider()
    rcol1, rcol2 = st.columns([1, 3])
    if rcol1.button("⚡ Run Cycle Now", width="stretch",
                    help="Force the bot to run one full cycle immediately (does not require RUNNING)."):
        with st.spinner("Running cycle..."):
            out = runner_mod.run_cycle(force=True)
        st.success("Cycle complete.")
        st.json(out)

    if runner_mod.LAST_CYCLE:
        with rcol2:
            st.caption("**Last cycle summary**")
            last = runner_mod.LAST_CYCLE
            chips = []
            for k, v in last.items():
                chips.append(f"`{k}={v}`")
            st.markdown("  ".join(chips))

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
            remaining = expires - datetime.utcnow()
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
                                (datetime.utcnow().isoformat(), int(r["id"])),
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
                                (datetime.utcnow().isoformat(), int(r["id"])),
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

    st.subheader("Open positions")
    ops = open_positions()
    if not ops:
        st.caption("No open positions.")
    else:
        rows = []
        for p in ops:
            try:
                px = latest_price(p["ticker"]) or p["entry_price"]
            except Exception:
                px = p["entry_price"]
            pnl = (px - p["entry_price"]) * p["quantity"]
            pnl_pct = (px / p["entry_price"] - 1) * 100 if p["entry_price"] else 0
            rows.append({
                "Ticker": p["ticker"],
                "Qty": p["quantity"],
                "Entry": f"₹{p['entry_price']:.2f}",
                "Current": f"₹{px:.2f}",
                "SL": f"₹{p['stop_loss']:.2f}" if p["stop_loss"] else "—",
                "TP": f"₹{p['take_profit']:.2f}" if p["take_profit"] else "—",
                "Unreal P&L": _fmt_pnl(pnl),
                "%": f"{pnl_pct:+.2f}%",
                "Strategy": p["strategy"] or "—",
                "Entered": to_ist(p["entry_ts"]).strftime("%Y-%m-%d %H:%M IST"),
            })
        render_table(pd.DataFrame(rows))

    st.divider()
    st.subheader("Trade log")
    trades = trades_df()
    if trades.empty:
        st.caption("No trades yet.")
    else:
        view = trades.head(100).copy()
        # Convert stored UTC timestamps to IST before display.
        view["ts"] = to_ist(view["ts"]).dt.strftime("%Y-%m-%d %H:%M IST")
        # format currency columns
        for col in ("price", "costs"):
            if col in view.columns:
                view[col] = view[col].map(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "—")
        view["net_value"] = view["net_value"].map(lambda x: _fmt_pnl(x))
        render_table(view[[
            "ts", "ticker", "side", "quantity", "price",
            "costs", "net_value", "strategy", "mode", "reason"
        ]])
        st.download_button(
            "Download all trades (CSV)",
            trades.to_csv(index=False).encode(),
            "trades.csv", "text/csv",
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
    agg: dict[str, dict] = {}
    unprocessed = 0
    for r in news_rows:
        if r["sentiment"] is None:
            unprocessed += 1
            continue
        tickers = [t for t in (r["tickers"] or "").split(",") if t.strip()]
        for tk in tickers:
            d = agg.setdefault(tk, {
                "scores": [], "latest_ts": None,
                "latest_title": "", "latest_url": "",
            })
            d["scores"].append(float(r["sentiment"]))
            if d["latest_ts"] is None or (r["ts"] or "") > d["latest_ts"]:
                d["latest_ts"] = r["ts"]
                d["latest_title"] = r["title"] or ""
                d["latest_url"] = r["url"] or ""

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
            agg = {k: v for k, v in agg.items() if len(v["scores"]) >= 3}

        # Build leaderboard rows.
        rows = []
        for tk, d in agg.items():
            scores = d["scores"]
            avg = sum(scores) / len(scores)
            mn, mx = min(scores), max(scores)
            try:
                latest_local = to_ist(d["latest_ts"]).strftime("%H:%M IST · %d %b")
            except Exception:
                latest_local = (d["latest_ts"] or "")[:16]

            # Color-code avg sentiment.
            if avg > 0.15:
                pill_cls = "badge-green"
            elif avg < -0.15:
                pill_cls = "badge-red"
            else:
                pill_cls = ""
            avg_html = (f"<span class='{pill_cls}'>{avg:+.2f}</span>"
                        if pill_cls else f"{avg:+.2f}")

            title = (d["latest_title"] or "")
            if len(title) > 80:
                title = title[:77] + "…"
            link_html = (f"<a href='{d['latest_url']}' target='_blank'>{title}</a>"
                         if d["latest_url"] else title)

            ticker_label = tk + (" 🎯" if tk in lb_open_tickers else "")
            rows.append({
                "Ticker": ticker_label,
                "Sector": sector_map.get(tk, "—") or "—",
                "Articles": len(scores),
                "Avg Sentiment": avg_html,
                "Min": f"{mn:+.2f}",
                "Max": f"{mx:+.2f}",
                "Latest Headline": link_html,
                "Last Update": latest_local,
                "_avg_raw": avg,
                "_n": len(scores),
                "_ts": d["latest_ts"] or "",
            })

        # Sort.
        if lb_sort == "n_desc":
            rows.sort(key=lambda r: (-r["_n"], -r["_avg_raw"]))
        elif lb_sort == "avg_desc":
            rows.sort(key=lambda r: -r["_avg_raw"])
        elif lb_sort == "avg_asc":
            rows.sort(key=lambda r: r["_avg_raw"])
        elif lb_sort == "ts_desc":
            rows.sort(key=lambda r: r["_ts"], reverse=True)

        # Strip helper cols before rendering.
        view_df = pd.DataFrame(rows).drop(columns=["_avg_raw", "_n", "_ts"])
        render_table(view_df)

        if unprocessed:
            st.caption(
                f"Excluded {unprocessed} articles in this window with no "
                "sentiment computed yet — click **📡 Scrape News Now** above "
                "to score them."
            )
        st.caption("🎯 marks tickers you currently hold. "
                   "Avg Sentiment colour: green > +0.15, red < −0.15.")

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
# Auto-refresh trigger (Streamlit-native rerun — no browser reload)
# ==================================================================
# This must be at the very bottom of the script. If the user has ticked the
# auto-refresh checkbox in the sidebar, we sleep for `refresh_secs` and then
# call st.rerun(). Because this is a server-side rerun (not a browser
# reload), the active tab, form state, and scroll position are preserved.
# If the user unticks the checkbox, the next rerun will skip this block
# entirely and the loop stops.
if auto_refresh:
    time.sleep(refresh_secs)
    st.rerun()

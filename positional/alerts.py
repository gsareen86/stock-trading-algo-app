"""
Telegram Alert System for the positional trading module.

Sends formatted messages to a Telegram chat/channel via Bot API.
All functions silently fail if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID
is not configured — Telegram is optional, never required.

Setup:
  1. Create a bot via @BotFather on Telegram → get BOT_TOKEN
  2. Start a chat with your bot, or create a group/channel
  3. Get CHAT_ID: https://api.telegram.org/bot<TOKEN>/getUpdates
  4. Add to .env:
       TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
       TELEGRAM_CHAT_ID=-1001234567890

Message format (4:30 PM IST daily):
  ─────────────────────────────────
  📊 POSITIONAL SCANNER REPORT — 08 May 2026
  ─────────────────────────────────
  Market Regime: 🟢 AGGRESSIVE (Nifty 18M ROC: +12.3%)

  ✅ ACTIONABLE EXITS (2):
  • SELL: PIDILITIND — 2 closes below 21 EMA (₹2,840 | SL was ₹2,790)
  • SELL: TATAPOWER — Hard stop hit (₹385 ≤ stop ₹390)

  🔔 NEW SETUPS (3):
  • BUY: KPITTECH — VCP + Trend Template ✓ (Score 78)
    Price: ₹1,455 | Suggested SL: ₹1,338 (8%) | Target: ₹1,707
  • BUY: ASTRAL — 52W High Breakout, VCP detected (Score 71)
    Price: ₹2,190 | Suggested SL: ₹2,015 | Target: ₹2,540

  ⏱️ TIME STOPS (1):
  • SELL: AARTIIND — 16 days held, only +0.8% gain (capital churning)

  🔁 RE-ENTRY ALERTS (1):
  • WATCH: BAJAJFINSV — Reclaiming 21 EMA on 1.8× volume
  ─────────────────────────────────
"""
from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger(__name__)


def _is_configured() -> bool:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _send(message: str) -> bool:
    """Send a raw message string. Returns True on success."""
    if not _is_configured():
        log.debug("[telegram] Not configured — skipping alert")
        return False
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        import urllib.request, urllib.parse, json
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
        if ok:
            log.debug("[telegram] message sent (%d chars)", len(message))
        return ok
    except Exception as e:
        log.warning("[telegram] send failed: %s", e)
        return False


def send_regime_alert(regime: dict) -> None:
    """Send market regime update (monthly)."""
    flag = regime.get("flag", "NEUTRAL")
    icon = {"DEFENSIVE": "🔴", "NEUTRAL": "🟡", "AGGRESSIVE": "🟢"}.get(flag, "⚪")
    nifty_roc  = regime.get("nifty_roc_18m")
    sc_roc     = regime.get("smallcap_roc_20m")
    gold_ratio = regime.get("nifty_gold_ratio")
    size_mult  = regime.get("size_multiplier", 1.0)

    lines = [
        "📊 <b>POSITIONAL — Market Regime Update</b>",
        f"{icon} Regime: <b>{flag}</b>  (position size: {size_mult:.0%})",
        "",
    ]
    if nifty_roc  is not None: lines.append(f"• Nifty 18M ROC: {nifty_roc:+.1f}%")
    if sc_roc     is not None: lines.append(f"• Smallcap 20M ROC: {sc_roc:+.1f}%")
    if gold_ratio is not None: lines.append(f"• Nifty/Gold ratio: {gold_ratio:.2f}")

    if flag == "DEFENSIVE":
        lines += ["", "⚠️ Market overheated. Reduce position sizes to 30-40%."]
    elif flag == "AGGRESSIVE":
        lines += ["", "✅ Near-zero ROC — good risk/reward for new entries."]

    _send("\n".join(lines))


def send_buy_alert(scan: dict) -> None:
    """Send a single BUY ALERT for a setup."""
    from config import POSITIONAL_HARD_STOP_PCT
    ticker  = scan.get("ticker", "?")
    price   = scan.get("price", 0)
    score   = scan.get("score", 0)
    prox    = scan.get("proximity_52w_pct", 0)
    vcp     = bool(scan.get("vcp_detected"))
    trend   = bool(scan.get("trend_template"))
    sl      = round(price * (1 - POSITIONAL_HARD_STOP_PCT), 2)
    target  = round(price * (1 + 2 * POSITIONAL_HARD_STOP_PCT), 2)

    badges = []
    if trend: badges.append("Trend Template ✓")
    if vcp:   badges.append("VCP ✓")

    _send(
        f"🔔 <b>BUY ALERT: {ticker}</b>\n"
        f"Score: {score:.0f} | {' | '.join(badges)}\n"
        f"Price: ₹{price:,.2f} | {prox:.1f}% below 52W High\n"
        f"Suggested SL: ₹{sl:,.2f} ({POSITIONAL_HARD_STOP_PCT:.0%}) | "
        f"Target: ₹{target:,.2f}"
    )


def send_sell_alert(ticker: str, price: float, reason: str,
                    entry_price: float = 0.0) -> None:
    """Send SELL alert for an open position."""
    pnl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    pnl_icon = "✅" if pnl_pct >= 0 else "❌"
    _send(
        f"🚨 <b>SELL ALERT: {ticker}</b>\n"
        f"Reason: {reason}\n"
        f"Current price: ₹{price:,.2f} | "
        f"P&L: {pnl_icon} {pnl_pct:+.1f}%"
    )


def send_reentry_alert(ticker: str, price: float, ema21: float,
                       vol_ratio: float) -> None:
    """Send RE-ENTRY alert."""
    _send(
        f"🔁 <b>RE-ENTRY ALERT: {ticker}</b>\n"
        f"Reclaiming 21 EMA on {vol_ratio:.1f}× average volume\n"
        f"Price: ₹{price:,.2f} | 21 EMA: ₹{ema21:,.2f}"
    )


def send_eod_summary(
    regime: dict,
    buy_alerts: list[dict],
    sell_alerts: list[dict],
    time_stops: list[dict],
    reentry_alerts: list[dict],
) -> None:
    """
    Send the full 4:30 PM EOD summary via Telegram.
    This is the primary daily notification.
    """
    from config import POSITIONAL_HARD_STOP_PCT
    today  = datetime.now().strftime("%d %b %Y")
    flag   = regime.get("flag", "NEUTRAL")
    icon   = {"DEFENSIVE": "🔴", "NEUTRAL": "🟡", "AGGRESSIVE": "🟢"}.get(flag, "⚪")
    nifty_roc = regime.get("nifty_roc_18m")
    roc_str   = f"Nifty 18M ROC: {nifty_roc:+.1f}%" if nifty_roc is not None else ""

    lines = [
        "─────────────────────────────",
        f"📊 <b>POSITIONAL REPORT — {today}</b>",
        "─────────────────────────────",
        f"Market Regime: {icon} <b>{flag}</b>" + (f" ({roc_str})" if roc_str else ""),
        "",
    ]

    if sell_alerts:
        lines.append(f"🚨 <b>ACTIONABLE EXITS ({len(sell_alerts)}):</b>")
        for s in sell_alerts:
            lines.append(f"• SELL: <b>{s['ticker']}</b> — {s['reason']} "
                         f"(₹{s['current_price']:,.0f})")
        lines.append("")

    if buy_alerts:
        lines.append(f"🔔 <b>NEW SETUPS ({len(buy_alerts)}):</b>")
        for b in buy_alerts[:5]:  # cap at 5
            price   = b.get("price", 0)
            sl      = round(price * (1 - POSITIONAL_HARD_STOP_PCT), 2)
            target  = round(price * (1 + 2 * POSITIONAL_HARD_STOP_PCT), 2)
            vcp_tag = " VCP ✓" if b.get("vcp_detected") else ""
            lines.append(
                f"• BUY: <b>{b['ticker']}</b>{vcp_tag} (Score {b['score']:.0f})\n"
                f"  ₹{price:,.2f} | SL ₹{sl:,.0f} | Target ₹{target:,.0f}"
            )
        lines.append("")

    if time_stops:
        lines.append(f"⏱️ <b>TIME STOPS ({len(time_stops)}):</b>")
        for t in time_stops:
            lines.append(f"• SELL: <b>{t['ticker']}</b> — {t['reason']}")
        lines.append("")

    if reentry_alerts:
        lines.append(f"🔁 <b>RE-ENTRY ALERTS ({len(reentry_alerts)}):</b>")
        for r in reentry_alerts:
            lines.append(f"• WATCH: <b>{r['ticker']}</b> — {r['reason']}")
        lines.append("")

    if not (sell_alerts or buy_alerts or time_stops or reentry_alerts):
        lines.append("No actionable signals today.")

    lines.append("─────────────────────────────")
    _send("\n".join(lines))


def test_connection() -> bool:
    """Verify Telegram connectivity. Returns True on success."""
    return _send(
        "✅ <b>Positional Trading Bot</b> — Telegram notifications are working!"
    )

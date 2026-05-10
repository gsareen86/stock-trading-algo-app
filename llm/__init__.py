"""
LLM-powered enhancements for the trading bot.

Six features, each independently toggled via config flags:

  1. llm.sentiment   — Claude-based news sentiment (replaces FinBERT)
  2. llm.veto        — pre-trade quality gate that can SKIP / REDUCE bad signals
  3. llm.regime      — narrative-aware market regime (overrides EMA-only filter)
  4. llm.events      — earnings / corporate-action extraction from news
  5. llm.eod_review  — daily post-trade analysis with parameter recommendations
  6. llm.meta_weights — adaptive STRATEGY_WEIGHTS based on current conditions

All features fail soft: API errors return a sentinel (None / 0.0 / passthrough)
so a network blip never crashes a trading cycle. Each feature is a no-op when
its config flag is off — the existing technical-only path keeps working.
"""

"""Alerts & Insights — LLM news-impact analysis for shortlisted holdings.

Turns the existing news pipeline into portfolio-aware guidance for swing-
positional + long-term shortlists, and surfaces sector-level + ancillary
sector news that touches those stocks indirectly.

Layout (5 files):
  schemas.py    -> LLM JSON schemas + prompt builders (no LLM call)
  linkage.py    -> ticker -> sector resolver + holdings/LT membership
  store.py      -> SQL reads/writes for news_impact_alerts + news_sector_tags
  llm_tasks.py  -> two LLM tasks: sector tagger + impact analyser
  pipeline.py   -> orchestration (`maybe_run`, `run_for_all`)

Modules import each other lazily inside their functions to keep the package
import cheap (the scheduler imports this module on every tick).
"""

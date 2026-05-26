"""
Diagnostic: prove the concall pipeline for one ticker.

Shows, step by step, whether the engine is actually reading the concall PDF or
just the Screener.in page:

  1. which concall rows + transcript/PPT links were scraped from Screener
  2. whether the transcript PDF was downloaded and how many chars were extracted
  3. a sample of that extracted text (this content is NOT on the Screener page)
  4. whether chunking (map-reduce) would trigger
  5. the on-disk cache files (raw .pdf + extracted .txt)
  6. the multi-quarter shareholding + financial trend text fed to the analyst
  7. (if the local LLM is reachable) the SEPARATE concall summary vs the
     fundamentals summary, so you can see the concall-derived points distinctly

Usage:
    python -m scripts.debug_concall THYROCARE
    python -m scripts.debug_concall ZYDUSLIFE --no-llm
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _hr(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    ticker = (args[0] if args else "RELIANCE").upper()
    run_llm = "--no-llm" not in flags

    from config import CACHE_DIR, POSITIONAL_RESEARCH_CHUNK_CHARS
    from longterm.screener_scraper import fetch_company
    from positional.concalls import gather_management_material

    _hr(f"1) SCREENER DOCUMENTS for {ticker}")
    parsed = fetch_company(ticker)
    concalls = (parsed or {}).get("concalls") or []
    print(f"concalls found: {len(concalls)}")
    for c in concalls[:5]:
        print(f"  {c.get('date'):>9} | transcript={'Y' if c.get('transcript_url') else '-'}"
              f" ppt={'Y' if c.get('ppt_url') else '-'} | {c.get('transcript_url') or ''}")

    _hr("2) DOWNLOAD + EXTRACT (gather_management_material)")
    mat = gather_management_material(ticker)
    ct, pt = mat.get("concall_text", ""), mat.get("ppt_text", "")
    print(f"concall_date     : {mat.get('concall_date')}")
    print(f"concall_text len : {len(ct)} chars")
    print(f"ppt_text len     : {len(pt)} chars")
    print(f"sources          : {mat.get('sources')}")
    if not ct and not pt:
        print("\n  ⚠️  No PDF text extracted. Either the transcript link wasn't found,")
        print("      pypdf isn't installed (pip install -r requirements.txt), or the")
        print("      PDF host blocked the download. The analyst will fall back to")
        print("      fundamentals + pros/cons only.")

    _hr("3) EXTRACTED CONCALL TEXT — first 8000 chars (proof it came from the PDF)")
    print((ct or "(empty)")[:8000])

    _hr("4) CHUNKING")
    body = "\n\n".join(p for p in (ct, pt) if p)
    n_chunks = (len(body) + POSITIONAL_RESEARCH_CHUNK_CHARS - 1) // POSITIONAL_RESEARCH_CHUNK_CHARS if body else 0
    print(f"combined body    : {len(body)} chars")
    print(f"chunk threshold  : {POSITIONAL_RESEARCH_CHUNK_CHARS} chars")
    print(f"map-reduce        : {'YES — ' + str(n_chunks) + ' chunks' if len(body) > POSITIONAL_RESEARCH_CHUNK_CHARS else 'no (single pass)'}")

    _hr("5) ON-DISK CACHE (cache/concalls/)")
    cdir = Path(CACHE_DIR) / "concalls"
    files = sorted(cdir.glob("*")) if cdir.exists() else []
    if files:
        for f in files[-8:]:
            print(f"  {f.name:>32}  {f.stat().st_size:>10,} bytes")
    else:
        print("  (no cached concall files yet)")

    _hr("6) TREND TEXT FED TO THE FUNDAMENTALS STAGE")
    print(mat.get("financial_trend") or "(none)")
    print()
    print(mat.get("shareholding_trend") or "(none)")

    if not run_llm:
        print("\n(--no-llm: skipping LLM summary stages)")
        return

    _hr("7) LLM STAGE OUTPUTS (concall vs fundamentals, then combined)")
    from positional import research as R
    f = R._fundamentals(ticker)
    concall_summary = R._summarise_concall(mat)
    print("\n--- STAGE 1: CONCALL SUMMARY (from the PDF) ---")
    print(concall_summary if concall_summary else "(LLM unavailable or no concall text)")
    fund_summary = R._summarise_fundamentals(mat, f)
    print("\n--- STAGE 2: FUNDAMENTALS & OWNERSHIP SUMMARY ---")
    print(fund_summary if fund_summary else "(LLM unavailable or no data)")
    cand = {"ticker": ticker + ".NS", "composite_score": None, "timing_score": None,
            "durability_score": None, "confluence": 0, "strategies_fired": "", "horizon": "?"}
    combined = R._combine(cand, concall_summary, fund_summary, f, "MODERATE / normal")
    print("\n--- STAGE 3: COMBINED THESIS + RECOMMENDATION ---")
    print(combined if combined else "(LLM unavailable)")


if __name__ == "__main__":
    main()

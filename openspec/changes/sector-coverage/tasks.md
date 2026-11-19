# Tasks: sector-coverage

- [x] `NIFTY COMMODITIES` in `sector_indices.json` (index, NSE name, terms)
- [x] Telecommunication and Services terms → Infrastructure; IT-services terms guarded
- [x] `symbol_overrides` with reasons; `sectors.for_instrument` consults them first
- [x] `utilities` → Energy
- [x] `app/data/verify_sector_indices.py`
- [x] Sector counts derived from the table, not hard-coded as 14
- [x] `tests/test_sector_mapping.py`: industries, overrides, substring guard, coverage of the
      bundled list (only the conglomerate unmapped), verification failure path
- [ ] Run `python -m app.data.verify_sector_indices` on a machine that reaches the provider;
      remove or correct `^CNXCMDT` if it fails
- [ ] Merge the delta into `openspec/specs/market-data/spec.md` and archive

# inr-cost-reporting

## Intent

Report money in rupees. This is an Indian-market platform — every price, position and
threshold in it is INR — and the LLM accounting panel was the one surface quoting dollars.

## Why

The Engine panel renders `$0.0004`. Nothing else in the platform does that: strategy evidence
carries `unit="INR"`, the market calendar is IST, the day boundary is IST. A single
dollar-denominated panel is not just cosmetically inconsistent — it makes the one number the
operator is supposed to act on (*is this run getting expensive?*) require a mental conversion
against a rate they have to supply themselves.

The awkwardness is real, though, and worth naming rather than papering over: **LLM providers
bill in USD.** LiteLLM computes `response_cost` in USD from a USD price table. There is no
sense in which an Anthropic call "costs ₹X" natively — it costs $X, and the rupee figure is a
conversion. So this change is not a rename; it is the introduction of a currency boundary,
and the interesting question is where to put it.

## In scope

- **`USD_INR_RATE`** — one operator-set conversion rate, with a sane default
- **`LLM_DAILY_BUDGET_INR`** replaces `LLM_DAILY_BUDGET_USD` — the cap is a number the
  operator chooses, so it should be in the currency they think in
- **Conversion at the API boundary** — the ledger keeps storing USD; `/llm/usage` and
  `/llm/calls` report INR, and report the rate they used
- **Engine panel** renders `₹`

## Out of scope

- **A live FX feed.** A network dependency, a staleness question and a new failure mode, to
  refine a number whose input is already a rounded estimate from a provider price table.
  Reconsider if LLM spend ever becomes material enough to care about a 2% rate drift.
- **Converting the stored column.** See `design.md` §1 — this is the load-bearing decision.
- **Anything outside LLM accounting.** Prices, evidence and thresholds are already INR; there
  is nothing to change there, and this change deliberately does not touch strategy code.

## Risks

- **A wrong rate silently mis-states every figure.** Mitigated by returning the rate in the
  API response and showing it in the panel, so the number is never unattributable.
- **Historical rupee totals move when the rate is changed.** Accepted deliberately; the
  alternative was worse. See `design.md` §2.
- **Renaming the budget setting is a breaking config change.** Deliberate — silently
  reinterpreting a `LLM_DAILY_BUDGET_USD=5` as ₹5 would cut the operator's real cap by ~88×
  with no error. A rename fails loudly instead; the old name is explicitly rejected.

# Design: inr-cost-reporting

## 1. USD is stored; INR is displayed

The decisive question is whether `llm_calls.cost_usd` becomes `cost_inr`.

It does not. The stored value is what the provider will actually charge, in the currency they
will actually charge it in. It reconciles against an invoice. A converted number reconciles
against nothing — it is a USD amount multiplied by whatever rate happened to be configured on
the day the row was written, and it can never be un-multiplied because the rate was not kept.

So the currency boundary goes exactly where the `.NS` suffix boundary goes, and for the same
reason. `to_provider_ticker` exists because yfinance's naming is a *provider artefact* that
should not leak into strategy code; USD is a *provider artefact* of the LLM vendors that
should not leak into the operator's view. Translate at the seam, once:

```
LiteLLM (USD)  →  llm_calls.cost_usd (USD, stored)  →  API serialisation (INR)  →  panel (₹)
                                                    ↑
                                            the only conversion
```

`DailyBudget` stays USD-internal, because it sums a USD column. The INR cap the operator
configures is converted to USD once, at construction. Putting the conversion anywhere deeper
would mean a rate multiplication on the hot path of every dispatch decision, to compare two
numbers that could just as well be compared in dollars.

## 2. One rate, and it is allowed to move

`USD_INR_RATE` is an operator-set constant, defaulting to `88.0`. Not a live feed (see
proposal, out of scope) and not a per-row snapshot.

The per-row snapshot is the tempting option and it is wrong here. Freezing the rate into each
row would make historical totals stable, but it would also make the ledger *claim* an accuracy
it does not have: the underlying `response_cost` is itself an estimate from a price table that
LiteLLM updates whenever vendors change pricing, and the row is already rounded to six
decimal places of a dollar. Adding a frozen FX rate to that would be precision theatre, plus a
migration and a column, to defend a figure that is routinely a fraction of a rupee.

The consequence is stated plainly rather than hidden: **change the rate and every rupee figure
in the panel, including historical ones, is recomputed at the new rate.** That is the correct
reading of "what would this have cost me in rupees" for a number this small, and the response
carries `usd_inr_rate` so any figure can be inverted back to the stored dollars.

## 3. The cap is renamed, not reinterpreted

`LLM_DAILY_BUDGET_USD` → `LLM_DAILY_BUDGET_INR`.

Keeping the old name and reinterpreting its value as rupees would take an operator's real
`=5.00` cap and turn it into about six US cents, silently, with the platform continuing to
function and simply refusing paid calls far earlier than intended. That is the worst
available outcome: a config change that looks like it did nothing.

So the old key is rejected outright — set it and startup fails with a message naming the new
one. A loud failure on a key nobody has set yet (this platform has no `.env` in use) costs
nothing; a silent 88× misreading costs the operator their paid providers.

## 4. Rounding

Rupee figures round to two decimals — a paisa is the smallest unit that means anything, and a
sub-paisa LLM call is worth showing as `< ₹0.01` rather than as `₹0.000037`, which reads as
noise and is exactly the number nobody can act on.

The panel keeps the existing widen-when-it-would-round-to-zero rule, retargeted at paise: a
real spend must never render as `₹0.00`. Below one paisa it shows `< ₹0.01`, which is the
honest statement — the exact figure is in the stored dollars, and this panel is for answering
"is this getting expensive", not for accounting to the microrupee.

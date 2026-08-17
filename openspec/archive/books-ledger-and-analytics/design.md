# Design: books-ledger-and-analytics

## 1. A position is derived, never edited

`trades` is the record; `positions` is a projection of it. A fill appends a trade and the
position is recomputed from the book's trade history for that symbol.

The alternative — storing quantity and average cost as independently updatable columns — is what
made the predecessor's three ledgers unreconcilable. Once a position can be written directly,
any bug or manual fix leaves a position that no sequence of trades explains, and there is no way
to tell which of the two is wrong.

Derivation costs an aggregate per symbol on a table that sees a few hundred rows a year. That is
not a trade worth making the other way.

**Average cost, not FIFO lots.** A single average cost per open position is the honest choice
while charges and tax lots are out of scope: FIFO lot tracking exists almost entirely to compute
tax, and computing it without STT, brokerage or the STCG/LTCG distinction would produce a number
that looks like a tax basis and is not one.

## 2. One ledger, book as a parameter

```python
ledger = Ledger(session_factory)
ledger.positions(Book.SWING)
ledger.fill(Book.SWING, ticker, side, quantity, price, ...)
```

`Book` is a `StrEnum` on every row rather than a separate table or — as in the predecessor — a
separate module per book. Swing and long-term differ in *holding period and which strategies
feed them*, not in what a position is. There is no `SwingLedger`.

The concrete test: adding a third book must be an enum member and nothing else.

## 3. The execution boundary is one function

`Ledger.fill()` is the only thing in the platform that creates a trade. Principle 7 exists
because the predecessor had broker classes that looked like they executed and silently did
nothing — the worst possible failure, because it is invisible.

So: no `Broker` protocol, no `PaperBroker` implementation, no `execute()` that might be wired to
something real later. One function, named for what it does, that records a paper fill. When live
routing is specified it will be a change that has to touch this function explicitly, which is
exactly the review that decision deserves.

Every fill records `source` — `manual`, `risk`, `backtest` — so a position's provenance is
answerable later.

## 4. Risk vetoes; it never rewrites

The `risk` node takes verdicts and portfolio state and returns a **decision per verdict**:
proceed with a size, or do not proceed with a reason.

It never touches the verdict. `Verdict` is frozen and its only mutator sets a narrative
(`verdict-narratives`), so this is enforced by the type rather than by discipline — a risk node
*cannot* downgrade a `BUY` to `WATCH`, only decline to act on it.

The gates it applies are portfolio-level, which is the level at which they make sense and the
level a strategy cannot see:

| Gate | Question |
|---|---|
| existing position | already held, at what size |
| position count | is the book already at its limit |
| concentration | would this exceed the per-name cap |
| sector concentration | would this exceed the per-sector cap |
| available capital | is there room |

**Sizing looks at one verdict at a time.** It uses that verdict's own conviction against
portfolio constraints. It does not rank verdicts against each other or allocate between them —
that would be a cross-strategy comparison, which is the confluence scorecard rebuilt at the
portfolio layer, and the one place it would be most tempting to justify.

## 5. P&L is gross, and says so

Realised and unrealised P&L exclude brokerage, STT, stamp duty and GST, and no tax treatment is
applied. Every P&L field is named or documented as gross.

A number labelled "P&L" that quietly omits charges is a number someone will eventually compare
against a broker statement and find wrong, with no clue why. Indian equity charges are not
negligible on a swing book — STT alone is material at the frequencies this platform implies — so
the honest options are to model them properly or to be explicit that they are absent. This
change takes the second, and leaves the first to a change that can specify the rates.

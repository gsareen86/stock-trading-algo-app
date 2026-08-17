# Design: portfolio-health-and-actions

## 1. Components first, headline second

The score is built from named components, each measuring one structural property against a
declared threshold:

| Component | Measures | Weight |
|---|---|---|
| `concentration` | largest position's share of committed capital | 30 |
| `diversification` | how many positions carry the book | 20 |
| `deployment` | capital working vs idle | 20 |
| `thesis_integrity` | share of the book whose buying strategy now says AVOID | 30 |

Each yields 0–100 and its own sentence. The headline is their weighted mean, published
*alongside* them rather than instead of them.

That ordering is the safeguard. A single number invites optimising the number; a number with
four visible components and their thresholds invites fixing the component that is low. The API
returns components even when only the headline is rendered, so the breakdown is never more than
one field away.

`thesis_integrity` is the one that could not exist before `insights-feed`: it needs the join
between a position and the strategy that bought it, and it is the component most likely to be
the actual problem with a book.

## 2. Guidance is attached to a component, never generated free-form

Each component that scores below its threshold contributes steps. A step names the component,
the measurement, and one concrete thing to do:

```
concentration (42/100): TCS is 64.9% of committed capital, above the 25% target.
  → Trim TCS to about 25% of the book (sell ~30 shares).
```

Steps are ordered by their component's **weight**, not by a per-step score. Scoring individual
steps would make them comparable, which is a ranking of actions, which is the same mistake one
level down. Weight is declared once in the component table above.

Guidance is generated deterministically. No model is involved: every number in a step comes
from the ledger or a threshold, which is the same rule `verdict-narratives` enforces on prose,
achieved here by not generating prose at all.

## 3. Actions belong to the insight kind

An insight declares the actions available for its kind, not for its instance:

| Kind | Actions |
|---|---|
| `thesis_broken` | `exit`, `review` |
| `concentration` | `trim`, `review` |
| `opportunity` | `buy`, `review` |
| everything else | `review` |

`review` is always available and does nothing but mark the insight read — the honest option for
"I have seen this and I am not acting", which is otherwise indistinguishable from not having
looked.

## 4. Quantity is re-derived at execution, never trusted from the insight

An insight raised on Monday saying "you hold 6" may be stale by Wednesday. So an action:

1. reads the **current** position from the ledger,
2. recomputes the quantity from the action's intent (`exit` → all of it; `trim` → down to the
   target weight),
3. refuses if the position is gone, or if the recomputed quantity is zero.

The insight's payload is a *hint for display*. It is never the input to a fill. This is the same
reasoning as deriving a position from trades rather than storing it: the moment a number can be
acted on without being re-read, it can be acted on while wrong.

Every action executes through `Ledger.fill()` with `source=FillSource.MANUAL` — the one
execution boundary, unchanged. There is no second path.

## 5. A preview that is the same code as the execution

`POST /insights/{id}/act` with `preview: true` runs the identical derivation and returns what
*would* happen without writing. Not a separate estimator — a flag on one function, because two
implementations of "what will this do" is how a preview starts lying.

# Design: screening-universe-and-gates

## 1. Three questions, asked in the right order

The platform now asks three different questions about a stock, and the value of this increment
is largely in keeping them apart:

| Question | Where | Failure means |
|---|---|---|
| Should we look at this at all? | **screening** (new) | ineligible — no strategy runs |
| Can this strategy assess it? | `strategies/gates.py` | unassessable — that strategy returns AVOID |
| Is the setup attractive? | strategy criteria | unattractive — conviction is lower |

The predecessor collapsed all three into one score. This increment adds the first without
letting it leak into the third: **a screen never ranks**. It returns the eligible set, in
universe order, with reasons for everything it removed. Ordering the survivors by anything
resembling quality would rebuild the confluence scorecard one layer up, where nobody would
think to look for it.

## 2. Turnover, not volume

The existing liquidity gate asks `volume > 0`. That passes a stock which traded eleven shares
on a good day, and it is the wrong unit besides — a hundred thousand shares of a ₹3 stock and a
hundred thousand shares of a ₹3,000 stock are not comparable positions.

Screening uses **median daily turnover in rupees** over a lookback window:

```
turnover = median(close × volume) over N sessions
```

Median rather than mean because a single block deal should not qualify a name that is otherwise
untradeable — and that is exactly the shape of the data that gets a screen wrong.

## 3. Exclusions are evidence, not silence

Every excluded name carries the filter that removed it, the value measured, the threshold it
failed, and a `source_ref`. That is the same `Evidence` shape strategies emit, for the same
reason: an exclusion is a claim about a stock, and an unexplained claim is not reviewable.

The concrete failure this prevents: a screen returns eleven names instead of two hundred, and
without per-name reasons the only way to find out why is to re-run it by hand with the filters
commented out one at a time.

## 4. Surveillance is bundled data with a visible age

NSE publishes ASM and GSM lists — names under additional or graded surveillance, typically for
volatility or governance concerns. They are exactly what a screen should exclude, and they are
also the kind of list that quietly goes stale.

Fetched live would be better and is not reliable: NSE serves these behind a browser-shaped
session and blocks anything else. So they are bundled JSON with an `as_of` date the snapshot
reports, following the holiday calendar's precedent — *"a holiday file that ran out in December
is exactly the kind of thing nobody discovers until a Tuesday in January"*. A surveillance list
from six months ago under-excludes silently unless its age is on the screen result.

## 5. The screen node does not change what a cycle decides

`screen` runs before `research` and narrows `instruments`. When the caller supplies symbols
explicitly, it is skipped entirely — asking about a specific stock should return an answer about
that stock, including when it would not have survived a screen. A screen chooses *what to look
at*; it never changes what a strategy concludes about a name it does look at.

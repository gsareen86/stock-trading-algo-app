# Design: insights-feed

## 1. What earns a place in the feed

An insight is something that **changes what a person might do**. That test excludes most of
what a cycle produces: four AVOID verdicts on a name nobody holds is a complete, correct, and
entirely unremarkable result.

So generators are written against consequences, and the ones about the portfolio come first
because they are the ones with a cost attached:

| Kind | Severity | Why it matters |
|---|---|---|
| `thesis_broken` | high | the strategy that justified a holding now says AVOID |
| `concentration` | high | one name exceeds the cap |
| `event_due` | medium | earnings or a corporate action on a held name |
| `position_news` | medium | news or a filing on something owned |
| `opportunity` | medium | risk assessed a verdict as actionable |
| `book_full` | low | opportunities cannot be acted on |
| `regime_change` | low | context for everything else |

**Severity belongs to the kind, not to the item.** Declaring it up front keeps it from becoming
a score computed per insight and compared across kinds — which is a ranking, which is the
scorecard, arriving at the last layer where it would look helpful.

`thesis_broken` is the one worth building this increment for on its own. A stock bought on a
Minervini setup whose Minervini verdict is now AVOID is the single most actionable thing the
platform can notice, and it can only be noticed by joining verdicts to positions.

## 2. Deduplication is what keeps the feed readable

A daily cycle regenerates the same observations every morning. Without suppression, the third
day of "RELIANCE concentration is 34%" makes the feed something to scroll past — and a feed
that is scrolled past is worse than no feed, because it looks like coverage.

Each insight carries a **dedupe key** (`kind:ticker:qualifier`) and is suppressed if an
insight with the same key was raised inside the window. The window is per kind: a broken
thesis is worth repeating weekly, a regime change is not worth repeating at all until the
regime changes back.

Suppression is *not* deletion. The original insight stays in the feed with its original
timestamp, which is what makes "this has been true for eleven days" visible.

## 3. Research is quoted, never asserted

`position_news` and `event_due` are built from tool output, which is a very different thing
from evidence. A `Verdict`'s evidence is a measurement this platform made, with a threshold
and a comparison. A news headline is something a model found.

So those insights name the tool, carry the `source_ref`, and phrase the finding as reported
rather than measured. The feed makes the distinction visible because a reader deciding whether
to sell needs to know if the platform *measured* a break or *read* a headline.

## 4. A cap per cycle, applied by severity band

At most N insights per cycle, filled high-severity first and then in generation order. Not
"the N most important" — that would need a cross-kind score, which §1 rules out. Within a
band the order is the order generators ran.

A cycle that would produce forty insights has something wrong with it, and truncating is a
better failure than flooding.

## 5. The node writes; nothing else does

`insights` runs last, after `risk` and `narrate`, because it reads both. It is the only writer
to the table, so a duplicate can only come from the dedupe key being wrong rather than from
two paths racing.

It never fills, never alters a verdict, and never changes a position. An insight links to the
things that would act and leaves the acting to `fill()` — which stays the one execution
boundary, reached deliberately.

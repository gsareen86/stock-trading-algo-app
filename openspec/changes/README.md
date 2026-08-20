# Changes

In-flight behavior changes. One directory per change, named with a short kebab-case id.

```
<change-id>/
  proposal.md              why, and what's in/out of scope
  tasks.md                 implementation checklist
  design.md                only when the technical approach needs explaining
  specs/<capability>/spec.md   the delta — ADDED / MODIFIED / REMOVED Requirements
```

When a change ships, merge its delta into `openspec/specs/<capability>/spec.md` and move
the directory to `openspec/archive/`. See `openspec/AGENTS.md` for the full workflow.

## In flight

Five changes, ordered by dependency. They are separate because each states one intent; the
work they describe together is a single rethink of what the platform is *for* — answering
"where should I be looking" rather than only "what do you think of this name".

| # | Change | Intent | Depends on | State |
|---|---|---|---|---|
| 1 | `feed-freshness-and-run-control` | Make the feed describe the present, and let a person start a cycle | — | **built** |
| 2 | `progress-visibility` | Show what the platform is doing while it does it | — | specified |
| 3 | `research-data-sources` | Official NSE quotes, company financials, management commentary | — | **built** |
| 4 | `discovery-funnel` | Ideas answers where to look, and every candidate carries a plan | 2, 3 | specified |
| 5 | `theme-engine` | What is emerging, and every listed company positioned to be paid by it | 3 | specified |

1 and 2 are independent of everything and fix what is visibly wrong today. 3 is the data
foundation 4 and 5 cannot be built without — the platform held four fundamental fields and one
benchmark before it. 4 asks what is worth looking at now, from price and strategy output; 5
asks what is worth looking at next, from what companies and policy say.

**A theme says where to look before the price moves; rotation says whether it has started.**
4 and 5 answer different halves of the same question, and disagreement between them is
information — the same principle the four strategies already work by.

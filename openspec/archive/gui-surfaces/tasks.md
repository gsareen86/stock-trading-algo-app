# Tasks: gui-surfaces

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Delta: web-shell (ADDED)

## Shared
- [x] `components/verdict.tsx` — one card per verdict; evidence in a `<details>`
- [x] `components/states.tsx` — unavailable / signed-out / empty, distinguishable
- [x] `components/insight-actions.tsx` — preview then confirm

## Surfaces
- [x] Today — insight feed with actions; seam report kept, collapsed
- [x] Ideas — four verdicts side by side, no consensus anywhere
- [x] Positions — both books, health score with components and guidance
- [x] Stock — one name, four verdicts, evidence, held status
- [x] Performance — analytics and attribution, explicitly not a ranking
- [x] Placeholder component retired

## Data path
- [x] Server components read the access cookie and call the backend directly
- [x] Client calls go through the proxy
- [x] Middleware renews an expired access token, since server components cannot set cookies

## Tests
- [x] No surface aggregates across verdicts
- [x] The verdict component takes one verdict
- [x] No surface sorts by agreement
- [x] Typecheck and production build clean

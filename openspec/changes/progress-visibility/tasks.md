# Tasks: progress-visibility

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: platform-api (ADDED), web-shell (ADDED), agent-graph (ADDED)

## Graph
- [ ] Optional observer protocol — notified with node id and timing, never with state
- [ ] Counting phases report units completed / units total through the same observer
- [ ] `screen` publishes the eligible count; the strategy fan-out and `narrate` publish theirs
- [ ] Observer failures logged, never propagated
- [ ] Test: observed and unobserved cycles produce identical verdicts

## API
- [ ] `POST /cycles/run/stream` — server-sent events, one per completed node
- [ ] Counting events carry `completed`, `total` and the unit's name; no percentage field
- [ ] A phase whose total is unknown omits `total` rather than estimating it
- [ ] Terminal event carries the same body as the non-streaming endpoint
- [ ] A failure terminates the stream with the failure, then closes
- [ ] Events carry no prompt or generated text
- [ ] Auth applies before the first event

## Web
- [ ] `loading.tsx` for `/`, `/ideas`, `/stock`, `/positions`, `/performance`, `/engine`
- [ ] Skeletons shaped like their content, distinct from the empty state
- [ ] Client submit buttons using `useFormStatus` on the Ideas and Stock forms
- [ ] **Proxy route rewritten to stream** — it currently does `await response.text()`, which
      buffers every body to completion; SSE cannot work through it as written
- [ ] Today renders completed steps; elapsed time past a short threshold
- [ ] Progress bar: indeterminate until a denominator arrives, then percent of counted work
- [ ] Percentage always rendered beside its counts, never alone
- [ ] Bar is monotonic — a later phase's denominator never moves it backwards
- [ ] Terminal event drives the bar to complete
- [ ] No estimated time remaining — asserted by a test over the sources
- [ ] A stream closing without a terminal event renders as a failure

## Tests
- [ ] Every route has a `loading.tsx`
- [ ] A pending control refuses a second submission
- [ ] A counting phase emits both numbers; an uncounted phase emits neither
- [ ] No progress event carries a percentage field
- [ ] Rendering before the denominator arrives shows indeterminate, not 0%
- [ ] A smaller later denominator does not decrease the displayed percentage
- [ ] Grep the surface sources for an estimated-time-remaining rendering — none exists
- [ ] Proxy does not buffer: an early event is observable before the run completes
- [ ] Streaming route refuses an unauthenticated caller before emitting

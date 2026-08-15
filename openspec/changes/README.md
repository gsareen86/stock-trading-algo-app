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

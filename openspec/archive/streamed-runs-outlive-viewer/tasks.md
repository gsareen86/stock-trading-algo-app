# Tasks: streamed-runs-outlive-viewer

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Delta: discovery (ADDED)

## API
- [x] `sse_stream_response` no longer cancels its run when the stream closes
- [x] Unwatched runs are held in a module-level set until done, then released
- [x] Events after disconnect are dropped rather than queued for no one
- [x] A failure after disconnect is logged

## Discovery
- [x] `DiscoveryScanner.run` marks a cancelled run `interrupted` with `finished_at`

## Tests
- [x] A run finishes after its viewer disconnects (fails on the old helper)
- [x] A run that completes while watched is not held afterwards
- [x] A cancelled scan's row reads `interrupted` (fails on the old scanner)

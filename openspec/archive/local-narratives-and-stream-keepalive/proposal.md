# local-narratives-and-stream-keepalive

## Intent

Narratives written by a local Ollama model arrive with text, quickly, and the live view of a
long scan stays connected until the scan ends.

## Why

On 19-Nov every gemma4:12b narrative in a Nifty 750 scan took 150-200 s and came back with
**no text**: 2,600-3,200 completion tokens, all of them thinking, ending exactly at 4,096
tokens. Three causes compounded:

* `LLM_REASONING__<TASK>` was sent in `extra_body`, which LiteLLM's Ollama provider does not
  forward. Thinking could not be turned off for any Ollama task.
* Ollama's default context window is 4,096 tokens, prompt and answer together, enforced by
  silent truncation. Research prompts also arrived cut to ~4,030 tokens.
* The gateway cached the empty answers, so a retried prompt was served the same nothing.

Separately, the scan card showed "network error" mid-scan. Narration emitted no progress for
minutes, and the web proxy's fetch drops a response body silent for 300 s (undici
`bodyTimeout`). The scan itself kept running — `streamed-runs-outlive-viewer` — but the page
called it stopped.

Measured after the change, on a 60-stock live scan: 9 of 9 narration calls returned text,
200-370 tokens each, in 12-38 s. The 16,384-token window cost ~250 MB of VRAM.

## In scope

- Reasoning effort reaches Ollama as LiteLLM's `reasoning_effort` argument (mapped to `think`).
- `LLM_LOCAL_CONTEXT_TOKENS` (default 16384) sent to Ollama as `num_ctx`.
- Empty answers are not cached; a length-truncated answer is logged.
- `run-local.ps1` sets `LLM_REASONING__NARRATIVE=none`.
- SSE streams send a keep-alive comment after 15 s of silence; narration reports each verdict.
- The web progress card distinguishes a dropped connection from a failed run, and shows the
  backend's actual error message.

## Out of scope

- Reconnecting a page to a run already in progress.
- Changing which model a task uses.

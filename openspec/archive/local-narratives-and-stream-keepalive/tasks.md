# Tasks: local-narratives-and-stream-keepalive

## Gateway
- [x] Ollama rungs get `reasoning_effort` as an argument; other providers keep `extra_body`
- [x] Ollama rungs get `num_ctx` from `llm_local_context_tokens`; `0` sends nothing
- [x] A result with no text, tool calls or parsed body is not cached
- [x] `finish_reason == "length"` is logged

## Configuration
- [x] `LLM_LOCAL_CONTEXT_TOKENS`, default 16384, non-negative
- [x] `run-local.ps1` and README: `LLM_REASONING__NARRATIVE=none`

## Streaming
- [x] Keep-alive comment after `HEARTBEAT_SECONDS` (15) of silence
- [x] `narrate_all(on_each=...)`; the scanner reports `Narrated n / N verdicts`

## Web
- [x] Error events read `error`, then `detail`
- [x] A stream ending without `complete`/`error`, or failing after it opened, reports a lost
      connection and that the run continues

## Tests
- [x] Gateway: reasoning argument per provider, context window set / default / zero / hosted,
      empty answer not cached — each fails on the previous gateway
- [x] Stream keep-alive is sent during a silent run; narration reports each verdict
- [x] Live: 60-stock scan on Ollama, 9/9 calls with text

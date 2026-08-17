# Tasks: local-run-ergonomics

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: platform-configuration (ADDED), llm-gateway (ADDED), platform-api (ADDED)

## Gateway
- [x] `llm_local_timeout_seconds`, default 300
- [x] Applied per rung on `is_local`, so each rung in a chain gets its own budget

## API
- [x] `GET /` — service, version, env, docs link, endpoint index
- [x] Static; does not probe, does not duplicate `/health`

## Local runner
- [x] `run-local.ps1` — routing, timeouts, migrations, both servers
- [x] Warns when Ollama is unreachable or the model is not pulled

## Tests
- [x] Local rung gets the local timeout; hosted keeps the short one
- [x] A hosted→local fallback chain gives each rung its own
- [x] `GET /` answers 200 and points at real endpoints

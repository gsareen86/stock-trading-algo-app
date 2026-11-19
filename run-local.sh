#!/usr/bin/env bash
# Start the platform locally against a local Ollama LLM (mirrors run-local.ps1).
# Usage:
#   ./run-local.sh
#   ./run-local.sh --model qwen3.8:latest
#   ./run-local.sh --backend-only
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${MODEL:-gemma4:12b}"
USD_INR_RATE="${USD_INR_RATE:-88.5}"
DAILY_BUDGET_INR="${LLM_DAILY_BUDGET_INR:-500}"
BACKEND_ONLY="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--model)
      MODEL="$2"
      shift 2
      ;;
    --usd-inr-rate)
      USD_INR_RATE="$2"
      shift 2
      ;;
    --daily-budget-inr)
      DAILY_BUDGET_INR="$2"
      shift 2
      ;;
    --backend-only)
      BACKEND_ONLY="true"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--model <ollama-tag>] [--usd-inr-rate <rate>] [--daily-budget-inr <inr>] [--backend-only]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: No virtualenv python at ${PYTHON_BIN}. Create it with: python3.11 -m venv backend/.venv" >&2
  exit 1
fi

# Load .env if present (so DATABASE_URL, AUTH_SECRET_KEY, etc. are picked up)
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
elif [[ -f "${ROOT_DIR}/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/backend/.env"
  set +a
fi

# Route local tasks cleanly to Ollama with local timeout parity
export LLM_ROUTE__NARRATIVE="${LLM_ROUTE__NARRATIVE:-ollama/${MODEL}}"
export LLM_ROUTE__RESEARCH="${LLM_ROUTE__RESEARCH:-ollama/${MODEL}}"
export LLM_DEFAULT_TASK_MODEL="${LLM_DEFAULT_TASK_MODEL:-ollama/${MODEL}}"
export LLM_LOCAL_TIMEOUT_SECONDS="${LLM_LOCAL_TIMEOUT_SECONDS:-300}"
export USD_INR_RATE="${USD_INR_RATE}"
export LLM_DAILY_BUDGET_INR="${LLM_DAILY_BUDGET_INR:-${DAILY_BUDGET_INR}}"
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"

echo "Routing default/narrative/research LLM tasks to ollama/${MODEL}"

if command -v curl >/dev/null 2>&1; then
  if TAGS_JSON="$(curl -fsS --max-time 5 http://localhost:11434/api/tags 2>/dev/null)"; then
    if ! echo "${TAGS_JSON}" | grep -q "\"${MODEL}\""; then
      echo "WARN: Ollama is up on :11434, but '${MODEL}' is not pulled. Run: ollama pull ${MODEL}" >&2
    fi
  else
    echo "WARN: Ollama is not reachable on localhost:11434 — narratives/research will report unavailable." >&2
  fi
fi

WEB_PID=""
cleanup() {
  if [[ -n "${WEB_PID}" ]] && kill -0 "${WEB_PID}" 2>/dev/null; then
    echo "Stopping Next.js web shell (pid ${WEB_PID})..."
    kill "${WEB_PID}" 2>/dev/null || true
    wait "${WEB_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "${ROOT_DIR}/backend"
"${PYTHON_BIN}" -m alembic upgrade head

if [[ "${BACKEND_ONLY}" != "true" ]]; then
  echo "Starting web shell on http://localhost:3000 (proxying to ${BACKEND_URL})"
  (
    cd "${ROOT_DIR}/web"
    exec npm run dev
  ) > "${ROOT_DIR}/.web-dev.log" 2>&1 &
  WEB_PID=$!
fi

echo "Starting backend on http://127.0.0.1:8000 (OpenAPI docs at /docs)"
"${PYTHON_BIN}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

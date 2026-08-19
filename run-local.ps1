<#
.SYNOPSIS
    Start the platform locally against a local LLM.

.DESCRIPTION
    The routing and timeout settings this needs are environment variables, so a server
    started any other way silently loses them - which looks like a broken feature rather
    than a missing setting. This script is the one place they live.

.EXAMPLE
    .\run-local.ps1
    .\run-local.ps1 -Model qwen3.8:latest
    .\run-local.ps1 -BackendOnly
#>
[CmdletBinding()]
param(
    # Ollama model for every task. `ollama list` shows what is pulled.
    [string]$Model = "gemma4:12b",
    [double]$UsdInrRate = 88.5,
    [double]$DailyBudgetInr = 500,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No virtualenv at $python. Create it with: py -3.11 -m venv backend\.venv"
}

# Local models are an order of magnitude slower than hosted ones and cost nothing to wait
# for. The gateway already applies LLM_LOCAL_TIMEOUT_SECONDS to local rungs only.
$env:LLM_ROUTE__NARRATIVE      = "ollama/$Model"
$env:LLM_DEFAULT_TASK_MODEL    = "ollama/$Model"
$env:LLM_LOCAL_TIMEOUT_SECONDS = "300"
$env:USD_INR_RATE              = "$UsdInrRate"
$env:LLM_DAILY_BUDGET_INR      = "$DailyBudgetInr"

Write-Host "Routing every task to ollama/$Model" -ForegroundColor Cyan

try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    if ($tags.models.name -notcontains $Model) {
        Write-Warning "Ollama is up but '$Model' is not pulled. Run: ollama pull $Model"
    }
} catch {
    Write-Warning "Ollama is not reachable on localhost:11434 - narratives will report 'unavailable'."
}

Push-Location (Join-Path $root "backend")
try {
    & $python -m alembic upgrade head | Out-Host

    if (-not $BackendOnly) {
        $web = Join-Path $root "web"
        Write-Host "Starting the web shell on http://localhost:3000" -ForegroundColor Cyan
        Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory $web -WindowStyle Minimized
    }

    Write-Host "Backend on http://127.0.0.1:8000  (docs at /docs)" -ForegroundColor Green
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}

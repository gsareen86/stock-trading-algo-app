# bootstrap.ps1 - one-shot setup for Stock Trading Algo App
# Run this from PowerShell INSIDE the project folder:
#
#     cd C:\Users\amits\OneDrive\Documents\Claude\Projects\StockTradingAlgoApp
#     powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
#
# What this does (in order):
#   1. Make sure OneDrive isn't holding .git/ files (forces "always keep on this device").
#   2. Remove any partial .git/ directory.
#   3. git init + initial commit.
#   4. gh repo create gsareen86/stock-trading-algo-app --private --source=. --remote=origin --push
#   5. Install psycopg (Postgres driver) into the project venv.
#   6. Run the SQLite -> Supabase migration (idempotent).
#
# It is safe to re-run: every step short-circuits if it is already done.
# ----------------------------------------------------------------------

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

# ----- 1. OneDrive: pin project so .git is not ghosted -----
Write-Step "Pinning project folder so OneDrive keeps it locally (avoids .git locks)"
try {
    attrib +P /S /D "$ProjectRoot" 2>$null | Out-Null
    Write-Ok "Done."
} catch {
    Write-Warn "Could not set 'always keep on device' attribute: $_"
    Write-Warn "Right-click the project folder in Explorer -> 'Always keep on this device' if git complains."
}

# ----- 2. Remove any half-built .git -----
Write-Step "Removing any partial .git/ directory"
if (Test-Path ".git") {
    try {
        # Strip read-only flags first (OneDrive sometimes sets these)
        Get-ChildItem ".git" -Recurse -Force -ErrorAction SilentlyContinue |
            ForEach-Object { try { $_.Attributes = "Normal" } catch {} }
        Remove-Item ".git" -Recurse -Force
        Write-Ok ".git removed."
    } catch {
        Write-Warn "Could not delete .git automatically. Close any 'git' processes / VS Code / explorer previews and try:"
        Write-Warn "    Remove-Item .git -Recurse -Force"
        throw
    }
} else {
    Write-Ok "No existing .git - clean start."
}

# ----- 3. git init + initial commit -----
Write-Step "git init + initial commit"
git init -b main | Out-Null
git config user.email "gaurav.sareen@gmail.com"
git config user.name  "Gaurav Sareen"

# Sanity check: .gitignore must exclude .env, .venv, db/*.db
if (-not (Test-Path ".gitignore")) {
    Write-Warn ".gitignore is missing! Aborting before we accidentally commit secrets."
    throw ".gitignore not found"
}

git add -A
$staged = git diff --cached --name-only | Measure-Object -Line
Write-Ok "Staged $($staged.Lines) files."

# Make sure we did NOT stage .env / venv / *.db
$leaks = git diff --cached --name-only | Where-Object {
    $_ -match '^\.env$' -or
    $_ -match '^\.venv/' -or
    $_ -match '\.db$' -or
    $_ -match '^cache/' -or
    $_ -match '^logs/'
}
if ($leaks) {
    Write-Warn "These files would leak into git despite .gitignore:"
    $leaks | ForEach-Object { Write-Warn "    $_" }
    throw "Aborting - fix .gitignore before committing."
}

git commit -m "Phase 1 baseline: paper-trading bot, dialect-aware DB layer, square-off tweaks" | Out-Null
Write-Ok "Initial commit created."

# ----- 4. Push to GitHub via gh CLI -----
Write-Step "Creating private GitHub repo + pushing"
$ghAvailable = $null -ne (Get-Command gh -ErrorAction SilentlyContinue)
if (-not $ghAvailable) {
    Write-Warn "gh CLI not found on PATH. Install from https://cli.github.com/ and re-run, or push manually:"
    Write-Warn "    git remote add origin https://github.com/gsareen86/stock-trading-algo-app.git"
    Write-Warn "    git push -u origin main"
} else {
    # Check auth state
    $authOk = $false
    try { gh auth status 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $authOk = $true } } catch {}
    if (-not $authOk) {
        Write-Warn "gh is not authenticated. Run 'gh auth login' once, then re-run this script."
    } else {
        # If repo already exists (re-run), just add remote and push
        $repoExists = $false
        try { gh repo view "gsareen86/stock-trading-algo-app" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $repoExists = $true } } catch {}
        if ($repoExists) {
            Write-Ok "Repo already exists on GitHub - pushing."
            git remote remove origin 2>$null
            git remote add origin "https://github.com/gsareen86/stock-trading-algo-app.git"
            git push -u origin main
        } else {
            gh repo create "gsareen86/stock-trading-algo-app" --private --source=. --remote=origin --push
        }
        Write-Ok "Pushed to https://github.com/gsareen86/stock-trading-algo-app"
    }
}

# ----- 5. Install psycopg into venv -----
Write-Step "Installing Postgres driver (psycopg) into .venv"
$venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Warn ".venv not found. Create it first:"
    Write-Warn "    python -m venv .venv ; .\.venv\Scripts\activate ; pip install -r requirements.txt"
    Write-Warn "Then re-run this script."
} else {
    & $venvPy -m pip install --quiet "psycopg[binary]>=3.2.0" python-dotenv
    Write-Ok "psycopg installed."
}

# ----- 6. Run SQLite -> Supabase migration -----
Write-Step "Running SQLite -> Supabase migration (idempotent)"
if (-not (Test-Path ".env")) {
    Write-Warn ".env not found. Copy .env.example to .env and fill in SUPABASE_DB_URL."
    Write-Warn "Skipping migration."
} elseif (-not (Test-Path $venvPy)) {
    Write-Warn "Skipping migration - venv missing."
} else {
    & $venvPy -m db.migrate_sqlite_to_supabase
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Migration complete."
    } else {
        Write-Warn "Migration script returned exit code $LASTEXITCODE - check the output above."
    }
}

Write-Host ""
Write-Host "=== Bootstrap finished ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Verify on Supabase dashboard that tables and rows are present."
Write-Host "  2. Set DB_BACKEND=postgres in .env (already set)."
Write-Host "  3. Run: python main.py    (dashboard + scheduler now read/write Supabase)."
Write-Host ""
Write-Host "If git push complained about OneDrive locks, right-click the project folder ->"
Write-Host "'OneDrive' -> 'Always keep on this device', then re-run this script."

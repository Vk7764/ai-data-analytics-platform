$ErrorActionPreference = "Stop"

# Move to project root (parent of scripts folder)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Running final smoke checks from: $root" -ForegroundColor Cyan

# Activate virtual environment
$venvActivate = Join-Path $root "venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    throw "Virtual environment not found at $venvActivate. Create venv first."
}

& $venvActivate

# Backend tests
Write-Host "`n[1/2] Running backend pytest..." -ForegroundColor Yellow
python -m pytest backend/tests -q

# Frontend build
Write-Host "`n[2/2] Running frontend production build..." -ForegroundColor Yellow
Push-Location (Join-Path $root "frontend")
try {
    npm run build
}
finally {
    Pop-Location
}

Write-Host "`nFinal smoke completed successfully." -ForegroundColor Green
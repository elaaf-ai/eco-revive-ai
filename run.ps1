# Start EcoRevive locally: website + API on http://localhost:8000. Press Ctrl+C to stop.
#   .\run.ps1            use the real model if installed, otherwise the fixture model
#   .\run.ps1 -Rebuild   rebuild the website first (after changing web/ code)
#   .\run.ps1 -Lan       also reachable from phones on the same Wi-Fi (upload works; live camera needs HTTPS)
param([switch]$Rebuild, [switch]$Lan)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Setting up the backend environment (first run only)..."
    py -3.14 -m venv (Join-Path $root "backend\.venv")
    & $py -m pip install --quiet --no-deps -r (Join-Path $root "backend\requirements.txt")
    & $py -m pip install --quiet -r (Join-Path $root "backend\requirements-dev.txt")
}

if ($Rebuild -or -not (Test-Path (Join-Path $root "web\dist\index.html"))) {
    Write-Host "Building the website..."
    Push-Location (Join-Path $root "web")
    if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund }
    npm run build
    Pop-Location
}

Push-Location (Join-Path $root "backend")
try {
    $real = Join-Path $root "ml\artifacts\0.1.0-preview\model.onnx"
    if (-not (Test-Path "models\current\model.onnx") -and (Test-Path $real)) {
        Write-Host "Installing the trained model (checksum verified)..."
        & $py scripts\fetch_model.py --version 0.1.0-preview --source-dir (Split-Path $real) --out models\current
        if ($LASTEXITCODE -ne 0) { throw "Model checksum check failed. Re-download the files from Drive." }
    }
    if (Test-Path "models\current\model.onnx") {
        $env:ECOREVIVE_MODEL_DIR = "models/current"
        Write-Host "Model: trained model in backend\models\current" -ForegroundColor Green
    } else {
        if (-not (Test-Path "models\fixture\model.onnx")) { & $py scripts\fixture_model.py --out models\fixture | Out-Null }
        $env:ECOREVIVE_MODEL_DIR = "models/fixture"
        Write-Host "Model: FIXTURE (fixed fake boxes, for trying the UI only)." -ForegroundColor Yellow
        Write-Host "       Put the Drive files in ml\artifacts\0.1.0-preview\ to use the real model." -ForegroundColor Yellow
    }
    $env:ECOREVIVE_STATIC_DIR = "../web/dist"
    $hostAddr = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
    Write-Host "Open http://localhost:8000   (API docs: http://localhost:8000/docs)" -ForegroundColor Cyan
    & $py -m uvicorn app.main:create_app --factory --host $hostAddr --port 8000
} finally {
    Pop-Location
}

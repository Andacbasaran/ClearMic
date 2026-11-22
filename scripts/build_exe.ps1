# ClearMic Standalone Windows Build Script (PyInstaller)
# Usage: .\scripts\build_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error ".venv bulunamadi. Once sanal ortami kurun."
    exit 1
}

& $Python -m pip install --quiet pyinstaller

$ModelArgs = @()
if (Test-Path "models\gtcrn_simple.onnx") {
    $ModelArgs = @("--add-data", "models\gtcrn_simple.onnx;models")
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "ClearMic" `
    --collect-all "onnxruntime" `
    @ModelArgs `
    run.py

Write-Host "`nBuild tamamlandi: dist\ClearMic\ClearMic.exe" -ForegroundColor Green

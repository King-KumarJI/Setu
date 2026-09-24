<#
.SYNOPSIS
    Builds Setu.exe -- a single portable Windows executable.

.DESCRIPTION
    Run this from a PowerShell prompt on the REAL Windows machine, not
    in any Linux/WSL shell -- PyInstaller bundles whatever interpreter
    it runs under, so it must run on Windows with PySide6 actually
    installed to produce a working Setu.exe.

    Steps: creates/reuses a project-local virtualenv, installs the
    app's own runtime + packaging dependencies into it (never the
    system Python -- Rule 6-adjacent: no assumptions about what's
    globally installed), runs the test suite as a build gate (a
    build that ships with failing tests is worse than no build --
    Rule 17 extended to the release process itself), then invokes
    PyInstaller against packaging/setu.spec.

.EXAMPLE
    cd C:\Users\ka447\Desktop\setu
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "== Setu build ==" -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv (.venv)..." -ForegroundColor Cyan
    python -m venv .venv
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Could not find $VenvPython -- venv creation failed."
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements-dev.txt
& $VenvPython -m pip install pyinstaller>=6.0

Write-Host "Running test suite (build gate)..." -ForegroundColor Cyan
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed -- refusing to build. Fix the failures first."
}

Write-Host "Building Setu.exe with PyInstaller..." -ForegroundColor Cyan
& $VenvPython -m PyInstaller --noconfirm --clean packaging\setu.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$OutExe = Join-Path $RepoRoot "dist\Setu.exe"
if (Test-Path $OutExe) {
    Write-Host ""
    Write-Host "Build succeeded: $OutExe" -ForegroundColor Green
    Write-Host "This is a portable single-file executable -- copy it anywhere, no installer needed."
    Write-Host "Remember: most operations need Setu to be run as Administrator (right-click -> Run as administrator)."
} else {
    throw "Build reported success but $OutExe was not found."
}

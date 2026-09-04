# Build a standalone Windows build of Console Prep Studio.
#
#   .\build.ps1              # one-folder build -> dist\ConsolePrepStudio\
#   .\build.ps1 -OneFile     # single .exe (slower start, same result)
#
# Requires a python.org CPython (3.10-3.13). The Windows Store Python does NOT
# work with PyInstaller.

param([switch]$OneFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

$common = @(
    "--noconfirm", "--clean", "--windowed",
    "--name", "ConsolePrepStudio",
    "--collect-binaries", "libtorrent",
    "--collect-submodules", "keyring.backends",
    "--paths", "src"
)
if (Test-Path "src\cps\resources\app.ico") { $common += @("--icon", "src\cps\resources\app.ico") }
if ($OneFile) { $common += "--onefile" }

python -m PyInstaller @common "app_main.py"

Write-Host ""
Write-Host "Built: dist\ConsolePrepStudio" -ForegroundColor Green
Write-Host "ffmpeg is fetched on first run; nothing else to bundle."

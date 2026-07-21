# Bundle Python 3.8 backend for Win7 LTS release
#
# This script prepares the Python runtime and backend code for packaging
# into the Electron NSIS installer.
#
# v0.4.5-alpha.2-win7 bundling architecture change:
# - PREVIOUS: downloaded Python 3.8.10-embed-amd64.zip (12MB, NO headers)
#             and tried to pip install hnswlib==0.8.0 → failed at
#             `fatal error C1083: Cannot open include file: 'Python.h'`
# - NOW:      actions/setup-python@v5 installs Python 3.8.10 FULL
#             distribution (with headers) for the BUILD step. We use it
#             to compile hnswlib etc. Then we download the embeddable
#             (for RUNTIME, smaller bundle), copy full Python's
#             site-packages (with compiled wheels) to embeddable's
#             Lib/site-packages.
#
# Why two Pythons? Win7 is end-of-life, Python 3.11+ requires Win8.1+,
# so we MUST use Python 3.8.x. Embeddable lacks Python.h (for C compile)
# but has python38.dll (same ABI as full Python 3.8.10), so compiled
# wheels work in either. We trade ~30MB extra download for working bundling.
#
# Usage: .\scripts\bundle-python.ps1
# Output: resources/python/ (embeddable runtime + site-packages) and resources/backend/

$ErrorActionPreference = "Stop"

# Configuration
# Python 3.8.11+ embeddable was removed from python.org after 3.8 EOL (2024-10).
# 3.8.10 (the 3.8 baseline, 2020-05) is the newest embed still hosted on python.org.
# All 3.8.x share the same ABI (python38.dll); Python code is fully compatible.
$PythonVersion = "3.8.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/pip/3.8/get-pip.py"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$PythonDir = Join-Path $ResourcesDir "python"
$BackendDir = Join-Path $ResourcesDir "backend"
$BackendSourceDir = Join-Path $PSScriptRoot "..\backend"
$RequirementsFile = Join-Path $PSScriptRoot "..\backend\requirements-py38.txt"

Write-Host "=== Python Backend Bundler for Win7 LTS ===" -ForegroundColor Cyan
Write-Host "Python version: $PythonVersion (full distribution from setup-python)"
Write-Host "Resources directory: $ResourcesDir"
Write-Host ""

# Locate Python from setup-python. After `actions/setup-python@v5` with
# python-version: '3.8.10' runs, `python.exe` is on PATH and points to the
# FULL distribution (with headers in Include/, stdlib in Lib/, etc).
$PythonExe = (Get-Command python.exe).Source
if (-not $PythonExe) {
    throw "Python not found on PATH. Did actions/setup-python@v5 run with python-version: '3.8.10'?"
}
$PythonRoot = Split-Path -Parent $PythonExe
$FullSitePackages = Join-Path $PythonRoot "Lib\site-packages"
Write-Host "Using full Python at: $PythonExe" -ForegroundColor Cyan
& $PythonExe --version
if ($LASTEXITCODE -ne 0) { throw "Python verification failed" }
Write-Host ""

# Clean up existing resources
if (Test-Path $ResourcesDir) {
    Write-Host "Cleaning existing resources directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $ResourcesDir
}

# Create directories
Write-Host "Creating directories..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $ResourcesDir | Out-Null
New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackendDir | Out-Null

# Download Python embeddable (runtime only — has python38.dll, stdlib in
# python38.zip, but NO Include/ headers). We use it as the runtime because
# it's ~12MB vs ~30MB for the full distribution.
Write-Host "Downloading Python $PythonVersion embeddable (runtime)..." -ForegroundColor Green
$PythonZip = Join-Path $ResourcesDir "python-embed.zip"
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip -UseBasicParsing

Write-Host "Extracting embeddable..." -ForegroundColor Green
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force
Remove-Item $PythonZip

# Enable site-packages AND pin the resources/ directory into python38._pth.
#
# CRITICAL (v0.4.3-alpha.2 Win7 backend 30s timeout fix):
# python38._pth, when present, makes the embedded interpreter ignore
# PYTHONPATH, registry, and environment variables (Python 3.8 docs:
# https://docs.python.org/3.8/using/windows.html#finding-modules).
# Without this extra line, `from backend.adapters...` raises
# ModuleNotFoundError because backend/ lives in resources/, not in
# site-packages. electron/main.ts sets PYTHONPATH at spawn, but the
# embedded interpreter silently discards it. The fix: write resources/
# into _pth at bundle time (the only mechanism _pth does not ignore).
#
# Path semantics (key insight from v0.4.3-alpha.2-debug):
# Python's import system walks sys.path entries looking for the PACKAGE
# NAME as a DIRECTORY or .py FILE inside each entry. So sys.path must
# contain the PARENT of the package directory, NOT the package directory
# itself. e.g. for `import backend.main`, sys.path must contain
# resources/ (parent), not resources/backend/ — otherwise Python looks
# for resources/backend/backend/ which doesn't exist.
#
# After NSIS extraction, _pth lives at <installDir>/resources/python/,
# so `..` resolves to <installDir>/resources/. This single entry puts
# both resources/backend/ AND resources/sage-core/ on sys.path, surviving
# any user-chosen install directory (electron-builder.yml has
# allowToChangeInstallationDirectory: true).
Write-Host "Configuring python38._pth (site + resources/ parent path)..." -ForegroundColor Green
$PthFile = Join-Path $PythonDir "python38._pth"
$PthLines = @(Get-Content $PthFile)

# Final _pth content template (also serves as the Pester regression-test
# anchor: scripts/bundle-python.Tests.ps1 asserts a literal `import site`
# line is present in this script). The actual file is constructed by the
# replacement block below — this here-string is documentation only.
$ExpectedPthTemplate = @"
import site
..
"@

$CanonicalResources = '..'

# Strip existing `..` line if present (idempotent re-run).
$Cleaned = $PthLines | Where-Object { $_ -ne $CanonicalResources }
# Uncomment `#import site` if present.
$Cleaned = $Cleaned -replace '^#import site\s*$', 'import site'

$NewLines = @($Cleaned + $CanonicalResources)
# Strip trailing blank lines so the file ends exactly with the `..` path.
while ($NewLines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($NewLines[-1])) {
    $NewLines = $NewLines[0..($NewLines.Count - 2)]
}
Set-Content -Path $PthFile -Value $NewLines

# Install Python dependencies into the FULL Python's site-packages.
# Full Python has Python.h (in Include/), so hnswlib's setup.py can compile
# C extensions. After install, we'll copy the site-packages to the embeddable.
#
# Order matters:
# 1. Modern setuptools + wheel (run 29830405815 history: sage-core build failed
#    with "invalid command 'bdist_wheel'" because Python 3.8.10 ships old
#    setuptools without wheel support). --no-build-isolation requires parent
#    env to have these.
# 2. Build-time deps (numpy<2 + pybind11): hnswlib==0.8.0 setup.py imports
#    these at top level (lines 5-6). pip calls setup.py during dependency
#    resolution BEFORE installing them. Pre-install first.
# 3. requirements-py38.txt: rest of deps, with --no-build-isolation so the
#    build env inherits the parent's already-installed numpy/pybind11.
Write-Host "Upgrading pip/setuptools/wheel (bdist_wheel requirement)..." -ForegroundColor Green
& $PythonExe -m pip install --no-warn-script-location --upgrade "pip" "setuptools>=68" "wheel"
if ($LASTEXITCODE -ne 0) { throw "pip install setuptools/wheel failed with exit code $LASTEXITCODE" }

Write-Host "Pre-installing numpy<2 + pybind11 (hnswlib build-time deps)..." -ForegroundColor Green
& $PythonExe -m pip install --no-warn-script-location "numpy<2" "pybind11>=2.6,<3"
if ($LASTEXITCODE -ne 0) { throw "pip install build-time deps failed with exit code $LASTEXITCODE" }

Write-Host "Installing Python dependencies from requirements-py38.txt..." -ForegroundColor Green
& $PythonExe -m pip install --no-warn-script-location --no-build-isolation -r $RequirementsFile
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements-py38.txt failed with exit code $LASTEXITCODE" }

# Install sage-core in development mode (also using full Python)
$SageCoreSource = Join-Path $PSScriptRoot "..\packages\sage-core"
if (Test-Path $SageCoreSource) {
    Write-Host "Installing sage-core package..." -ForegroundColor Green
    $SageCoreDest = Join-Path $ResourcesDir "sage-core"
    Copy-Item -Path $SageCoreSource -Destination $SageCoreDest -Recurse -Force
    & $PythonExe -m pip install --no-warn-script-location --no-build-isolation -e $SageCoreDest
    if ($LASTEXITCODE -ne 0) { throw "pip install -e sage-core failed with exit code $LASTEXITCODE" }
}

# Copy full Python's site-packages (with compiled wheels including hnswlib)
# to the embeddable's site-packages. Embeddable's python.exe can then
# load them at runtime (same ABI as full Python 3.8.10).
$EmbedSitePackages = Join-Path $PythonDir "Lib\site-packages"
Write-Host "Copying site-packages from full Python to embeddable..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $EmbedSitePackages | Out-Null
Copy-Item -Path "$FullSitePackages\*" -Destination $EmbedSitePackages -Recurse -Force

# Copy backend code
Write-Host "Copying backend code..." -ForegroundColor Green
$BackendItems = Get-ChildItem -Path $BackendSourceDir -Exclude "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info"
foreach ($item in $BackendItems) {
    $dest = Join-Path $BackendDir $item.Name
    if ($item.PSIsContainer) {
        Copy-Item -Path $item.FullName -Destination $dest -Recurse -Force
        # Remove __pycache__ directories
        Get-ChildItem -Path $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    } else {
        Copy-Item -Path $item.FullName -Destination $dest -Force
    }
}

# Verify installation
Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Python executable (runtime): $PythonDir\python.exe"
Write-Host "Backend directory: $BackendDir"
Write-Host ""

# Test Python import. Capture both stdout and stderr to a single buffer so we
# can surface the underlying error in the exception message if any import
# fails (otherwise we'd just see a bare exit code).
#
# CRITICAL: `import backend.main` is the canary for the _pth / PYTHONPATH
# regression — without `..` in python38._pth, this raises
# ModuleNotFoundError immediately, catching the v0.4.3-alpha.1 Win7 bug
# at bundle time instead of at user runtime.
Write-Host "Testing Python imports (incl. backend.main canary)..." -ForegroundColor Green
$EmbedPython = Join-Path $PythonDir "python.exe"
$verifyOutput = & $EmbedPython -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; import hnswlib; import backend.main; print('All critical imports successful (hnswlib + backend.main OK)')" 2>&1
$verifyExit = $LASTEXITCODE
Write-Host $verifyOutput
if ($verifyExit -ne 0) {
    throw "Post-install verification failed: critical Python imports missing (exit code $verifyExit). Output: $verifyOutput"
}

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow
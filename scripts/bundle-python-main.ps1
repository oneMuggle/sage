# Bundle Python 3.11 embedded runtime + backend for **main** branch release
#
# Main-branch analogue of scripts/bundle-python.ps1 (which targets
# release/win7 LTS Python 3.8). Produces the same `resources/` tree
# (resources/python/, resources/backend/, resources/sage-core/) so
# electron-builder.yml extraResources picks both up uniformly.
#
# ## Related fixes ported from release/win7 LTS (commits 4cea570 / 2689cb8 / a20c061 / 973d44c)
#
# When this script was first drafted (PR #130), it was a byte-for-byte copy of
# the **pre-fix** state of scripts/bundle-python.ps1, and inherited three
# critical bugs that Win7 LTS had to fix three times (v0.4.0-lts /
# v0.4.1-lts / v0.4.2-lts all shipped a 30s backend-timeout dialog). The three
# fixes are now ported forward and called out by name in this header so
# future maintainers don't strip them again:
#
# 1. **pth fix (4cea570 + 2689cb8 + a20c061)**: After extracting the Python
#    embeddable, the bundled `python311._pth` MUST contain the relative path
#    `..` (not `..\backend` and not `..\sage-core`) on its own line.
#    python3X._pth makes the embedded interpreter ignore PYTHONPATH /
#    registry / environment variables per the Python docs
#    (https://docs.python.org/3/using/windows.html#finding-modules), so the
#    PYTHONPATH set by electron/main.ts at spawn is silently discarded.
#    sys.path must contain the PARENT of the package directories —
#    `resources/` — so Python walks `resources/backend/backend/` and
#    `resources/sage-core/sage_core/` correctly (namespace packages).
#
# 2. **`import backend.main` canary**: The verify step explicitly imports
#    `backend.main` after `fastapi/pydantic/jieba`. Without the `..` pth
#    line, this raises ModuleNotFoundError at bundle time instead of at
#    end-user startup, catching regressions before tag.
#
# 3. **LASTEXITCODE checks (973d44c)**: `$ErrorActionPreference = "Stop"`
#    does NOT auto-throw on `& $ExternalExe` exit codes — it only catches
#    cmdlet failures. Every `& $PipExe` / `& $PythonExe` invocation must
#    be followed by `if ($LASTEXITCODE -ne 0) { throw ... }`.
#
# 4. **No start-backend.bat**: Win7 LTS removed the dead .bat generation in
#    973d44c; main bundles/scripts matched the removal.
#
# 5. **resources/ precise cleanup**: Only remove the bundle-owned subdirs
#    (resources/python, resources/backend, resources/sage-core), never the
#    whole resources/ tree (which holds icons the project owns).
#
# Usage:  pwsh scripts/bundle-python-main.ps1
# Output: resources/python/, resources/backend/, resources/sage-core/

$ErrorActionPreference = "Stop"

# Configuration — 3.11 is main's stable Python line (matches backend Dockerfile
# + CI pytest python_version). When 3.11 EOLs (2027-10), bump here + rerun.
$PythonVersion = "3.11.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$PythonDir = Join-Path $ResourcesDir "python"
$BackendDir = Join-Path $ResourcesDir "backend"
$SageCoreDir = Join-Path $ResourcesDir "sage-core"
$BackendSourceDir = Join-Path $PSScriptRoot "..\backend"
$RequirementsFile = Join-Path $PSScriptRoot "..\backend\requirements.txt"

Write-Host "=== Python Backend Bundler for main branch ===" -ForegroundColor Cyan
Write-Host "Python version: $PythonVersion"
Write-Host "Resources directory: $ResourcesDir"
Write-Host ""

# Clean up ONLY bundle-owned subdirs (don't touch icons / NSIS assets / etc.
# that the project itself owns in resources/). See header "Related fixes"
# item #5.
foreach ($d in @($PythonDir, $BackendDir, $SageCoreDir)) {
  if (Test-Path $d) {
    Write-Host "Cleaning $d..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $d
  }
}

# Create directories
Write-Host "Creating directories..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackendDir | Out-Null
New-Item -ItemType Directory -Force -Path $SageCoreDir | Out-Null

# Download Python embeddable
Write-Host "Downloading Python $PythonVersion embeddable..." -ForegroundColor Green
$PythonZip = Join-Path $PythonDir "python-embed.zip"
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip -UseBasicParsing

# Extract Python
Write-Host "Extracting Python..." -ForegroundColor Green
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force
Remove-Item $PythonZip

# Configure python311._pth (site + parent-of-python path).
#
# CRITICAL: see header "Related fixes" item #1 (pth fix).
# Without the `..` line, end-user packaged Win installer crashes
# with ModuleNotFoundError: backend on first import.
# - '#import site' is shipped commented-out by the embeddable; flip it.
# - `..` (single dotdot, NOT `..\backend` / `..\sage-core`) goes AFTER any
#   zip/stdlib entries so sys.path contains the resources/ directory. See
#   release/win7 commit a20c061 for the wrong-vs-right analysis.
Write-Host "Configuring python311._pth (site + ..)..." -ForegroundColor Green
$PthFile = Join-Path $PythonDir "python311._pth"
if (-not (Test-Path $PthFile)) {
  # Newer Python versions might rename or omit _pth; give a clear error.
  Write-Host "ERROR: expected $PthFile but it doesn't exist." -ForegroundColor Red
  Write-Host "Python embeddable layout may have changed for version $PythonVersion." -ForegroundColor Red
  Write-Host "Inspect $PythonDir and update this script accordingly." -ForegroundColor Red
  exit 2
}
$PthLines = @(Get-Content $PthFile)

# Strip any pre-existing `..` (or `..\backend` / `..\sage-core` from an
# earlier wrong-attempt script) so re-runs are idempotent and don't stack.
$Cleaned = $PthLines | Where-Object { $_ -ne '..' -and $_ -ne '..\backend' -and $_ -ne '..\sage-core' }
# Uncomment `#import site` if present.
$Cleaned = $Cleaned -replace '^#import site\s*$', 'import site'

$NewLines = @($Cleaned + '..')
# Strip trailing blank lines so the file ends exactly with `..`.
while ($NewLines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($NewLines[-1])) {
  $NewLines = $NewLines[0..($NewLines.Count - 2)]
}
Set-Content -Path $PthFile -Value $NewLines

# Download and install pip
Write-Host "Downloading get-pip.py..." -ForegroundColor Green
$GetPipPath = Join-Path $ResourcesDir "get-pip.py"
Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing

Write-Host "Installing pip..." -ForegroundColor Green
$PythonExe = Join-Path $PythonDir "python.exe"
& $PythonExe $GetPipPath --no-warn-script-location
# CRITICAL: see header "Related fixes" item #3 (LASTEXITCODE).
if ($LASTEXITCODE -ne 0) { throw "get-pip.py install failed with exit code $LASTEXITCODE" }
Remove-Item $GetPipPath

# Install dependencies from backend/requirements.txt (main, pydantic 2.x)
Write-Host "Installing Python dependencies from requirements.txt..." -ForegroundColor Green
$PipExe = Join-Path $PythonDir "Scripts\pip.exe"
& $PipExe install --no-warn-script-location -r $RequirementsFile
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed with exit code $LASTEXITCODE" }

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

# Copy packages/sage-core if it exists.
# CRITICAL (release/win7 commit 973d44c): this block still needs the
# LASTEXITCODE guard even though main's sage-core has no external deps
# and step `pip install -e` is omitted — copying itself can fail on
# file-locking / antivirus / path-too-long, so wrap with try/catch.
Write-Host "Copying sage-core package..." -ForegroundColor Green
$SageCoreSource = Join-Path $PSScriptRoot "..\packages\sage-core"
if (Test-Path $SageCoreSource) {
  Copy-Item -Path $SageCoreSource -Destination $SageCoreDir -Recurse -Force
  if ($LASTEXITCODE -ne 0) { throw "Copy-Item sage-core failed with exit code $LASTEXITCODE" }
}

# Verify installation
Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Python executable: $PythonExe"
Write-Host "Backend directory: $BackendDir"
Write-Host "_pth file: $PthFile"
Write-Host ""

# Test Python imports. Capture both stdout and stderr to a single buffer so
# we can surface the underlying error if any import fails (otherwise we'd
# just see a bare exit code).
#
# CRITICAL: see header "Related fixes" item #2 (canary).
# `import backend.main` raises ModuleNotFoundError immediately if the
# python311._pth file is missing the `..` line that puts resources/ on
# sys.path. Site-packages imports alone (fastapi/pydantic/jieba) would
# silently succeed even with a broken _pth, hiding the regression until
# end-user startup.
Write-Host "Testing Python imports (incl. backend.main canary)..." -ForegroundColor Green
$verifyOutput = & $PythonExe -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; import backend.main; print('All critical imports successful (backend.main OK)')" 2>&1
$verifyExit = $LASTEXITCODE
Write-Host $verifyOutput
if ($verifyExit -ne 0) {
  throw "Post-install verification failed: critical Python imports missing (exit code $verifyExit). Output: $verifyOutput"
}

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow

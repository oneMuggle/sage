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
# 6. **Inner sage_core copy to site-packages (main PR fixing v0.4.5-alpha.1
#    regression)**: PR #130 carried forward the _pth fix but DELIBERATELY
#    dropped the `pip install -e $SageCoreDest` step (comment at the time:
#    "main's sage-core has no external deps and step `pip install -e` is
#    omitted"). The assumption was that the `_pth`'s `..` puts `resources/`
#    on sys.path and `import sage_core` would walk `resources/sage-core/`.
#    It does NOT — because the source dir is hyphen-named `sage-core/`
#    while the Python module is underscore-named `sage_core/`. Python's
#    import machinery is path-literal and does no hyphen↔underscore
#    normalization. Result: v0.4.5-alpha.1 (and any pre-PR backport) bundles
#    successfully but every end user hits ModuleNotFoundError on first
#    backend launch (4-5 sec after spawn → 30 sec timeout dialog).
#    Fix: also copy the inner sage_core/ package directly into the bundled
#    Python's site-packages/. `import site` (enabled in _pth) puts
#    site-packages on sys.path unconditionally regardless of
#    machine-specific paths. We deliberately DON'T use `pip install -e`
#    here because pip bakes the build-machine's absolute path into the
#    generated .pth — that absolute path is the CI runner's path which
#    does not exist on end-user machines.
#
# Usage:  pwsh scripts/bundle-python-main.ps1
# Output: resources/python/, resources/backend/, resources/sage-core/,
#         resources/python/Lib/site-packages/sage_core/

$ErrorActionPreference = "Stop"

# Configuration — 3.11 is main's stable Python line (matches backend Dockerfile
# + CI pytest python_version). When 3.11 EOLs (2027-10), bump here + rerun.
#
# IMPORTANT: python.org periodically prunes old embeddable zip files from
# the /ftp/python/ mirror (typically after the patch's security-only phase
# ends + ~6 months). If your CI fails with HTTP 404 on $PythonUrl, search
# https://www.python.org/ftp/python/ for available versions and bump here.
# Verified 2026-07-10 that 3.11.0–3.11.9 still exist; 3.11.10+ return 404.
$PythonVersion = "3.11.9"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$PythonDir = Join-Path $ResourcesDir "python"
$BackendDir = Join-Path $ResourcesDir "backend"
$SageCoreDir = Join-Path $ResourcesDir "sage-core"
$BackendSourceDir = Join-Path $PSScriptRoot "..\backend"
# Use requirements-bundled.txt (subset of requirements.txt that omits
# source-only / no-Windows-wheel packages like hnswlib). Without splitting,
# pip would try to build hnswlib from source on the Windows runner, which
# requires numpy + pybind11 + cython + Visual Studio C++ toolchain — adding
# ~2 minutes of CI time for an optional vector store backend that isn't
# transitively imported by backend.main anyway. See the header comment at
# the top of backend/requirements-bundled.txt for the full rationale.
$RequirementsFile = Join-Path $PSScriptRoot "..\backend\requirements-bundled.txt"

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

# Install dependencies from requirements-bundled.txt (cp311+win_amd64 wheels only).
Write-Host "Installing Python dependencies from requirements-bundled.txt..." -ForegroundColor Green
$PipExe = Join-Path $PythonDir "Scripts\pip.exe"
& $PipExe install --no-warn-script-location -r $RequirementsFile
if ($LASTEXITCODE -ne 0) { throw "pip install -r $RequirementsFile failed with exit code $LASTEXITCODE" }

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
#
# CRITICAL (release/win7 commit 973d44c + main follow-up): sage_core imports
# are at the TOP of `backend/domain/__init__.py`, which uvicorn loads at
# `import backend.main` time. Without sage_core on sys.path the backend exits
# with `ModuleNotFoundError: No module named 'sage_core'` 4-5 seconds after
# spawn (after fastapi/uvicorn/jieba finish importing). End users see a 30s
# "backend health timeout" dialog identical to the historical win7 LTS bug.
#
# Why we DON'T use `pip install -e $SageCoreDest` like release/win7 LTS does:
#   pip embeds an absolute path to the *build machine's* sage-core directory
#   into a site-packages/__editable__-sage_core-*.pth file. That absolute path
#   is the CI runner's path (e.g. D:\a\sage\sage\resources\sage-core), which
#   does not exist on the end-user's machine — so the import still fails.
#
# Instead we copy the inner sage_core/ package directory directly into the
# bundled Python's site-packages/. Python's `import site` (enabled in the
# _pth file) puts site-packages on sys.path unconditionally, regardless of
# machine-specific paths or PYTHONPATH overrides. This is also why we
# additionally keep the resources/sage-core/ tree — it's a development
# artifact that mirrors the source layout and matches what we'd see in any
# dev `pip install -e` checkout.
#
# Why we keep BOTH copies:
#   1) resources/sage-core/   — mirrors source layout (debug-friendly if a
#      user extracts the NSIS payload and inspects files). Unused at runtime
#      because the directory name uses a hyphen while the Python module
#      name uses an underscore (see verify comment below).
#   2) resources/python/Lib/site-packages/sage_core/ — runtime-importable.
#      This is the path `from sage_core import ...` resolves to inside the
#      packaged Sage process.
#
# CRITICAL (release/win7 commit 973d44c): even though main's sage-core has
# no external deps and we deliberately skip `pip install -e`, both Copy-Item
# steps can fail on file-locking / antivirus / path-too-long — wrap with
# LASTEXITCODE guards.
Write-Host "Copying sage-core package..." -ForegroundColor Green
$SageCoreSource = Join-Path $PSScriptRoot "..\packages\sage-core"
if (Test-Path $SageCoreSource) {
  # 1) Mirror source layout to resources/sage-core/ (debug + dev parity)
  Copy-Item -Path $SageCoreSource -Destination $SageCoreDir -Recurse -Force
  if ($LASTEXITCODE -ne 0) { throw "Copy-Item sage-core (mirror) failed with exit code $LASTEXITCODE" }

  # 2) Copy inner sage_core/ package directly into bundled site-packages so
  #    `import sage_core` works at runtime. Done as a separate step (instead
  #    of relying on resources/sage-core/sage_core/) because the parent dir
  #    uses a hyphen (sage-core) but the importable module uses an underscore
  #    (sage_core) — Python's import machinery walks sys.path literally and
  #    would not find the package under a hyphen-named directory.
  $SageCorePkgSource = Join-Path $SageCoreSource "sage_core"
  $SageCorePkgDest = Join-Path $PythonDir "Lib\site-packages\sage_core"
  if (Test-Path $SageCorePkgSource) {
    if (Test-Path $SageCorePkgDest) {
      # Idempotent on re-run: clean any previous copy.
      Remove-Item -Recurse -Force $SageCorePkgDest
    }
    Copy-Item -Path $SageCorePkgSource -Destination $SageCorePkgDest -Recurse -Force
    if ($LASTEXITCODE -ne 0) { throw "Copy-Item sage_core package to site-packages failed with exit code $LASTEXITCODE" }
    # Strip __pycache__ that might sneak in from a prior dev run
    Get-ChildItem -Path $SageCorePkgDest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  } else {
    Write-Host "WARNING: $SageCorePkgSource not found; sage_core will not be importable." -ForegroundColor Yellow
  }
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
#
# ALSO canary `import sage_core` + `from sage_core import ...` — both must
# succeed at bundle time, or end users hit the v0.4.5-alpha.1 regression
# (`ModuleNotFoundError: No module named 'sage_core'` 4-5s after spawn,
# surfaces as 30s "backend health timeout" dialog). `import backend.main`
# alone does NOT exercise sage_core because backend.main lazy-imports
# sage_core's consumers only inside lifespan/handlers — so we explicitly
# import sage_core here to fail-fast at bundle time.
Write-Host "Testing Python imports (backend.main + sage_core canary)..." -ForegroundColor Green
$verifyOutput = & $PythonExe -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; import sage_core; from sage_core.entities import AgentDecision; import backend.main; print('All critical imports successful (backend.main + sage_core OK)')" 2>&1
$verifyExit = $LASTEXITCODE
Write-Host $verifyOutput
if ($verifyExit -ne 0) {
  throw "Post-install verification failed: critical Python imports missing (exit code $verifyExit). Output: $verifyOutput"
}

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow

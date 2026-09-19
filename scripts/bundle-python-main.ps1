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

# Code protection mode: set SAGE_PROTECT_CODE=true (or pass -ProtectCode) during release builds
# to compile sage_core to native C-extensions (.pyd) and byte-compile/strip backend .py files.
# In dev/CI mode (default), source .py files are copied directly for rapid build times.
param(
    [switch]$ProtectCode = ($env:SAGE_PROTECT_CODE -eq "true")
)

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
$ManifestPath = Join-Path $ResourcesDir "build-manifest.json"
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

if ($ProtectCode) {
  Write-Host "🛡️ Code protection ENABLED: Installing Cython..." -ForegroundColor Yellow
  & $PipExe install --no-warn-script-location "cython>=3.0.0" "setuptools"
  if ($LASTEXITCODE -ne 0) { throw "pip install cython failed with exit code $LASTEXITCODE" }

  # Cython build_ext needs Python.h (headers) and python311.lib (import libs).
  # The embeddable Python zip lacks both. The full Python from actions/setup-python
  # (on PATH) has them. Copy into the embeddable so distutils finds them at the
  # standard sysconfig paths (resources/python/include, resources/python/libs).
  # ABI-safe: both are CPython 3.11.x, same stable ABI.
  $SystemPythonExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
  if (-not $SystemPythonExe) {
    throw "System Python not found on PATH. Add 'actions/setup-python@v5' with python-version: '3.11' to the workflow."
  }
  $SystemPythonRoot = Split-Path -Parent (Split-Path -Parent $SystemPythonExe)
  # actions/setup-python puts python.exe under <tool-cache>/Python/<version>/x64/python.exe
  # but Get-Command may resolve to a shim. Walk up to find include/ dir.
  $SystemInclude = $null
  foreach ($candidate in @($SystemPythonRoot, (Split-Path -Parent $SystemPythonRoot))) {
    $inc = Join-Path $candidate "include"
    if (Test-Path $inc) { $SystemInclude = $inc; $SystemPythonRoot = $candidate; break }
  }
  if (-not $SystemInclude) {
    throw "System Python include dir not found. Searched from $SystemPythonExe"
  }
  $SystemLibs = Join-Path $SystemPythonRoot "libs"

  Write-Host "🛡️ Copying Python dev headers from system Python ($SystemPythonRoot) to embeddable..." -ForegroundColor Yellow
  $EmbedInclude = Join-Path $PythonDir "include"
  Copy-Item -Path $SystemInclude -Destination $EmbedInclude -Recurse -Force
  if (Test-Path $SystemLibs) {
    $EmbedLibs = Join-Path $PythonDir "libs"
    Copy-Item -Path $SystemLibs -Destination $EmbedLibs -Recurse -Force
  }
  Write-Host "🛡️ Python dev headers copied successfully." -ForegroundColor Green
}

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

# In protected mode, compile backend to .pyc and strip source .py files (except main.py)
if ($ProtectCode) {
  Write-Host "🛡️ Compiling backend to bytecode (.pyc) and stripping source .py..." -ForegroundColor Yellow
  & $PythonExe -m compileall -b $BackendDir
  if ($LASTEXITCODE -ne 0) { throw "compileall for backend failed with exit code $LASTEXITCODE" }

  # Only the top-level entry point stays readable. Matching on Name alone would
  # spare any nested main.py anywhere in the tree.
  $EntryPoint = Join-Path $BackendDir "main.py"
  Get-ChildItem -Path $BackendDir -Recurse -Filter "*.py" | Where-Object { $_.FullName -ne $EntryPoint } | Remove-Item -Force
  Write-Host "🛡️ Backend source stripping complete." -ForegroundColor Green
}

# Copy packages/sage-core if it exists.
#
# CRITICAL (release/win7 commit 973d44c + main follow-up): sage_core is
# imported at module-load time via `backend/adapters/out/tool/inproc_adapter.py`,
# which `backend/main.py` imports at line 20. So `import backend.main`
# transitively loads sage_core within the first ~4-5 seconds of process
# startup. Without sage_core on sys.path the backend exits with
# `ModuleNotFoundError: No module named 'sage_core'`, surfaces as a 30s
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
  if ($ProtectCode) {
    Write-Host "🛡️ Code protection: Compiling sage_core with Cython..." -ForegroundColor Yellow
    $CompileScript = Join-Path $PSScriptRoot "compile-sage-core.py"
    & $PythonExe $CompileScript build_ext --inplace
    if ($LASTEXITCODE -ne 0) { throw "Cython compilation for sage_core failed with exit code $LASTEXITCODE" }

    # Diagnostic: verify .pyd files were actually produced in the source tree.
    $SageCorePkgCheck = Join-Path $SageCoreSource "sage_core"
    $pydFiles = Get-ChildItem -Path $SageCorePkgCheck -Recurse -Filter "*.pyd" -ErrorAction SilentlyContinue
    if ($pydFiles.Count -eq 0) {
      throw "Cython build produced no .pyd files under $SageCorePkgCheck. Check compile-sage-core.py module names."
    }
    Write-Host "🛡️ Cython produced $($pydFiles.Count) .pyd files." -ForegroundColor Green

    # Clean up Python dev headers (include/ + libs/) — they're only needed for
    # Cython compilation and should NOT be shipped in the installer (~8MB).
    $EmbedInclude = Join-Path $PythonDir "include"
    $EmbedLibs = Join-Path $PythonDir "libs"
    if (Test-Path $EmbedInclude) { Remove-Item -Recurse -Force $EmbedInclude }
    if (Test-Path $EmbedLibs) { Remove-Item -Recurse -Force $EmbedLibs }
    Write-Host "🛡️ Cleaned up Python dev headers from embeddable (not shipped)." -ForegroundColor Green

    # In protected mode, do not leak source in resources/sage-core, just keep an empty dir for electron-builder
    Write-Host "🛡️ Omitting source tree mirror in resources/sage-core for protection." -ForegroundColor Yellow
  } else {
    # 1) Mirror source layout to resources/sage-core/ (debug + dev parity)
    Copy-Item -Path $SageCoreSource -Destination $SageCoreDir -Recurse -Force
    if ($LASTEXITCODE -ne 0) { throw "Copy-Item sage-core (mirror) failed with exit code $LASTEXITCODE" }
    Get-ChildItem -Path $SageCoreDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  }

  # 2) Copy inner sage_core/ package into bundled site-packages
  $SageCorePkgSource = Join-Path $SageCoreSource "sage_core"
  $SageCorePkgDest = Join-Path $PythonDir "Lib\site-packages\sage_core"
  if (Test-Path $SageCorePkgSource) {
    if (Test-Path $SageCorePkgDest) {
      Remove-Item -Recurse -Force $SageCorePkgDest
    }
    Copy-Item -Path $SageCorePkgSource -Destination $SageCorePkgDest -Recurse -Force
    if ($LASTEXITCODE -ne 0) { throw "Copy-Item sage_core package to site-packages failed with exit code $LASTEXITCODE" }
    Get-ChildItem -Path $SageCorePkgDest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    if ($ProtectCode) {
      # Keep only compiled extensions + package markers.
      # .py — every module except the package marker.
      Get-ChildItem -Path $SageCorePkgDest -Recurse -Filter "*.py" | Where-Object { $_.Name -ne "__init__.py" } | Remove-Item -Force
      # Cython intermediates — the generated .c carries the translated
      # function bodies and .pyx is the original typed source.
      Get-ChildItem -Path $SageCorePkgDest -Recurse -Include "*.c", "*.pyx" | Remove-Item -Force
      Write-Host "🛡️ Stripped sage_core source (.py/.c/.pyx) from site-packages (kept .pyd + __init__.py)." -ForegroundColor Green
    }
  } else {
    Write-Host "WARNING: $SageCorePkgSource not found; sage_core will not be importable." -ForegroundColor Yellow
  }
} else {
  Write-Host "WARNING: $SageCoreSource not found; sage_core will not be importable." -ForegroundColor Yellow
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
# ALSO canary `import sage_core` + `from sage_core.entities import AgentDecision` —
# both must succeed at bundle time, or end users hit the v0.4.5-alpha.1
# regression (`ModuleNotFoundError: No module named 'sage_core'` 4-5s
# after spawn, surfaces as 30s "backend health timeout" dialog). Strictly
# speaking `import backend.main` would *also* fail (transitively via
# `backend/adapters/out/tool/inproc_adapter.py` which has a top-level
# `from sage_core import ToolResult, ToolSpec`), but the downstream error
# chain points at the adapter module — making the root cause hard to
# diagnose. An explicit `import sage_core` canary fails fast on the
# specific missing module so the bundle-time error message is precise.
Write-Host "Testing Python imports (backend.main + sage_core canary)..." -ForegroundColor Green
$verifyCode = "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; import sage_core; from sage_core.entities import AgentDecision; import backend.main; print('All critical imports successful (backend.main + sage_core OK)')"

if ($ProtectCode) {
  # Assert the compiled extension is what actually loaded. A stale editable
  # .pth copied over from full Python's site-packages could otherwise satisfy
  # `import sage_core` from source and hide a failed Cython build.
  # NOTE: single-quoted so PowerShell leaves the Python `$_probe` alone.
  $verifyCode += '; import sage_core.entities.agent as _probe; assert _probe.__file__.endswith(".pyd"), "sage_core.entities.agent loaded from " + _probe.__file__; print("Protected canary OK: " + _probe.__file__)'
}

$verifyOutput = & $PythonExe -c $verifyCode 2>&1
$verifyExit = $LASTEXITCODE
Write-Host $verifyOutput
if ($verifyExit -ne 0) {
  throw "Post-install verification failed: critical Python imports missing (exit code $verifyExit). Output: $verifyOutput"
}

# Write the same provenance contract consumed by packaged Electron. Mirrors
# scripts/bundle-python.ps1 (Win7 LTS) lines 109-119: same JSON shape, same
# env-var precedence. electron-builder.yml extraResources line 31 picks this
# up at packaging time and main.ts loads it from
# <resourcesPath>/build-manifest.json at startup. Without this file the
# packaged Electron falls back to createBuildManifest() defaults, silently
# disabling buildId-based health-ownership validation. The CI path writes
# its own minimal manifest in .github/workflows/ci.yml "Generate
# build-manifest.json" — this block only runs on tag-driven release flows.
$Manifest = [ordered]@{
    manifestVersion = 1
    buildId = if ($env:SAGE_BUILD_ID) { $env:SAGE_BUILD_ID } else { "local-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))" }
    commit = if ($env:GITHUB_SHA) { $env:GITHUB_SHA } else { "unknown" }
    branch = if ($env:GITHUB_REF_NAME) { $env:GITHUB_REF_NAME } else { "unknown" }
    version = if ($env:SAGE_BUILD_VERSION) { $env:SAGE_BUILD_VERSION } else { "unknown" }
    electronVersion = if ($env:SAGE_ELECTRON_VERSION) { $env:SAGE_ELECTRON_VERSION } else { "21.4.4" }
    pythonVersion = $PythonVersion
}
$Manifest | ConvertTo-Json -Depth 3 | Set-Content -Path $ManifestPath -Encoding UTF8
Write-Host "Build manifest: $ManifestPath" -ForegroundColor Green

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow

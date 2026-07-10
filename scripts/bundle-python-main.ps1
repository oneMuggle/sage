# Bundle Python 3.11 embedded runtime + backend for **main** branch release
#
# This is the main-branch analogue of bundle-python.ps1 (which targets
# release/win7 LTS Python 3.8). It produces the same `resources/` tree
# so electron-builder.yml extraResources picks it up unchanged.
#
# Differences from bundle-python.ps1 (Win7 LTS):
#   - Python 3.11 (main), NOT 3.8.10 (Win7 LTS)
#   - Uses backend/requirements.txt (main), NOT requirements-py38.txt
#   - Uses `python311._pth` instead of `python38._pth`
#
# Usage:  pwsh scripts/bundle-python-main.ps1
# Output: resources/python/, resources/backend/, resources/sage-core/, resources/start-backend.bat
#
# Pre-condition: must run on a Windows runner with PowerShell 7+
# (GitHub Actions `windows-latest` ships pwsh). Cannot run on Linux.
# For Linux, see the cross-distro packaging follow-up tracked in
# docs/technical/<this PR>.

$ErrorActionPreference = "Stop"

# Configuration — 3.11 is main's stable Python line (matches backend Dockerfile
# + CI pytest python_version). When 3.11 EOLs (2027-10), bump here + rerun.
$PythonVersion = "3.11.10"
# Newer Python embeddables moved to https://www.python.org/ftp/python/. Embed
# distributions include python311.dll + python.exe + Lib\ + pip-equivalent.
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$PythonDir = Join-Path $ResourcesDir "python"
$BackendDir = Join-Path $ResourcesDir "backend"
$BackendSourceDir = Join-Path $PSScriptRoot "..\backend"
$RequirementsFile = Join-Path $PSScriptRoot "..\backend\requirements.txt"

Write-Host "=== Python Backend Bundler for main branch ===" -ForegroundColor Cyan
Write-Host "Python version: $PythonVersion"
Write-Host "Resources directory: $ResourcesDir"
Write-Host ""

# Clean up existing resources. This script IS the author of `resources\` —
# bundle-python.ps1 (Win7 LTS) runs on a different branch so they will never
# race. Cleanly wiping is safer than merging because the file set differs
# (python38._pth vs python311._pth, different versions of fastapi/pydantic, etc.).
if (Test-Path $ResourcesDir) {
  Write-Host "Cleaning existing resources directory..." -ForegroundColor Yellow
  Remove-Item -Recurse -Force $ResourcesDir
}

# Create directories
Write-Host "Creating directories..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $ResourcesDir | Out-Null
New-Item -ItemType Directory -Force -Path $PythonDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackendDir | Out-Null

# Download Python embeddable
Write-Host "Downloading Python $PythonVersion embeddable..." -ForegroundColor Green
$PythonZip = Join-Path $ResourcesDir "python-embed.zip"
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip -UseBasicParsing

# Extract Python
Write-Host "Extracting Python..." -ForegroundColor Green
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force
Remove-Item $PythonZip

# Enable site-packages by uncommenting python311._pth. The embeddable ships
# with `import site` commented out so pip-installed packages are ignored;
# flipping it to `import site` is required for uvicorn / fastapi to load.
Write-Host "Enabling site-packages..." -ForegroundColor Green
$PthFile = Join-Path $PythonDir "python311._pth"
if (-not (Test-Path $PthFile)) {
  # Newer Python versions might rename or omit _pth; give a clear error.
  Write-Host "ERROR: expected $PthFile but it doesn't exist." -ForegroundColor Red
  Write-Host "Python embeddable layout may have changed for version $PythonVersion." -ForegroundColor Red
  Write-Host "Inspect $PythonDir and update this script accordingly." -ForegroundColor Red
  exit 2
}
$PthContent = Get-Content $PthFile
$PthContent = $PthContent -replace '#import site', 'import site'
Set-Content -Path $PthFile -Value $PthContent

# Download and install pip
Write-Host "Downloading get-pip.py..." -ForegroundColor Green
$GetPipPath = Join-Path $ResourcesDir "get-pip.py"
Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing

Write-Host "Installing pip..." -ForegroundColor Green
$PythonExe = Join-Path $PythonDir "python.exe"
& $PythonExe $GetPipPath --no-warn-script-location
Remove-Item $GetPipPath

# Install dependencies from backend/requirements.txt (main, pydantic 2.x)
Write-Host "Installing Python dependencies from requirements.txt..." -ForegroundColor Green
$PipExe = Join-Path $PythonDir "Scripts\pip.exe"
& $PipExe install --no-warn-script-location -r $RequirementsFile

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

# Copy packages/sage-core if it exists
$SageCoreSource = Join-Path $PSScriptRoot "..\packages\sage-core"
if (Test-Path $SageCoreSource) {
  Write-Host "Copying sage-core package..." -ForegroundColor Green
  $SageCoreDest = Join-Path $ResourcesDir "sage-core"
  Copy-Item -Path $SageCoreSource -Destination $SageCoreDest -Recurse -Force
}

# Create backend startup script
Write-Host "Creating backend startup script..." -ForegroundColor Green
$StartBackendBat = Join-Path $ResourcesDir "start-backend.bat"
$BatContent = @"
@echo off
set PYTHONPATH=%~dp0backend;%~dp0sage-core
"%~dp0python\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
"@
Set-Content -Path $StartBackendBat -Value $BatContent -Encoding ASCII

# Verify installation
Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Python executable: $PythonExe"
Write-Host "Backend directory: $BackendDir"
Write-Host "Startup script: $StartBackendBat"
Write-Host ""

# Test Python import — guards against silent pip-install failure (e.g. native
# wheel missing). The original bug ("spawn conda ENOENT") only surfaced at
# runtime on end-user machines; catching it at bundle-time shortens the loop.
Write-Host "Testing Python imports..." -ForegroundColor Green
& $PythonExe -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; print('All critical imports successful')"
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: Python imports failed (exit $LASTEXITCODE)" -ForegroundColor Red
  Write-Host "Backend deps did not install correctly — aborting." -ForegroundColor Red
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow

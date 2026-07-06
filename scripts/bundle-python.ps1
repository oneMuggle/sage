# Bundle Python 3.8 embedded runtime + backend for Win7 LTS release
#
# This script prepares the Python runtime and backend code for packaging
# into the Electron NSIS installer. It downloads Python 3.8 embeddable,
# installs pip, installs dependencies, and copies the backend code.
#
# Usage: .\scripts\bundle-python.ps1
# Output: resources/python/ and resources/backend/

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
Write-Host "Python version: $PythonVersion"
Write-Host "Resources directory: $ResourcesDir"
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

# Download Python embeddable
Write-Host "Downloading Python $PythonVersion embeddable..." -ForegroundColor Green
$PythonZip = Join-Path $ResourcesDir "python-embed.zip"
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip -UseBasicParsing

# Extract Python
Write-Host "Extracting Python..." -ForegroundColor Green
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force
Remove-Item $PythonZip

# Enable site-packages by uncommenting python38._pth
Write-Host "Enabling site-packages..." -ForegroundColor Green
$PthFile = Join-Path $PythonDir "python38._pth"
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
if ($LASTEXITCODE -ne 0) { throw "get-pip.py install failed with exit code $LASTEXITCODE" }
Remove-Item $GetPipPath

# Install dependencies
Write-Host "Installing Python dependencies from requirements-py38.txt..." -ForegroundColor Green
$PipExe = Join-Path $PythonDir "Scripts\pip.exe"
& $PipExe install --no-warn-script-location -r $RequirementsFile
# CRITICAL: PowerShell's $ErrorActionPreference = "Stop" does NOT auto-catch
# exit codes from `& $ExternalExe` calls. Without this check, a pip failure
# would silently continue past this point and the verify step below would also
# fail silently, producing a corrupt bundled Python runtime shipped to users
# (this is the root cause of the v0.4.0-lts+ Win7 "30s backend timeout" bug).
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements-py38.txt failed with exit code $LASTEXITCODE" }

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
    # Install sage-core in development mode
    & $PipExe install --no-warn-script-location -e $SageCoreDest
    if ($LASTEXITCODE -ne 0) { throw "pip install -e sage-core failed with exit code $LASTEXITCODE" }
}

# Verify installation
Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Python executable: $PythonExe"
Write-Host "Backend directory: $BackendDir"
Write-Host ""

# Test Python import. Capture both stdout and stderr to a single buffer so we
# can surface the underlying error in the exception message if any import
# fails (otherwise we'd just see a bare exit code).
Write-Host "Testing Python imports..." -ForegroundColor Green
$verifyOutput = & $PythonExe -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; print('All critical imports successful')" 2>&1
$verifyExit = $LASTEXITCODE
Write-Host $verifyOutput
if ($verifyExit -ne 0) {
    throw "Post-install verification failed: critical Python imports missing (exit code $verifyExit). Output: $verifyOutput"
}

Write-Host ""
Write-Host "=== Python backend bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $((Get-ChildItem -Path $ResourcesDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB) MB" -ForegroundColor Yellow

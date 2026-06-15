# scripts/fetch-vcredist.ps1
#
# Download Microsoft Visual C++ Redistributable (x64) for bundling into NSIS installer.
# Required for clean Win7 SP1 first-launch (Electron 21 native modules need VC++ runtime).
#
# Used by:
#   - CI: .github/workflows/ci.yml desktop-build (windows-latest) before npx electron-builder
#   - Local Win dev: pwsh scripts/fetch-vcredist.ps1 before npm run electron:dist
#
# The downloaded file goes to resources/vc_redist.x64.exe (gitignored).
# NSIS customInstall macro (build/installer.nsh) loads it via BUILD_RESOURCES_DIR.

$ErrorActionPreference = 'Stop'

$Url     = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
$Dest    = Join-Path $PSScriptRoot '..\resources\vc_redist.x64.exe'
$DestDir = Split-Path -Parent $Dest

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

if (Test-Path $Dest) {
    Write-Host "[fetch-vcredist] Already present: $Dest"
    exit 0
}

Write-Host "[fetch-vcredist] Downloading $Url -> $Dest"
Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing

$size = (Get-Item $Dest).Length
if ($size -lt 10MB -or $size -gt 30MB) {
    throw "[fetch-vcredist] Unexpected size $size bytes - corrupt download?"
}

Write-Host "[fetch-vcredist] OK ($([math]::Round($size/1MB, 1)) MB)"

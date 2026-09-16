# Bundle MinGit bash for Win7 LTS installer
#
# Downloads a minimal MSYS2 bash environment into resources/tools/git-bash/
# so the Sage Win7 installer has a usable bash even on machines without
# Git for Windows (Win7 SP1 ships with PowerShell 2.0 only — see PR #911).
#
# Why MinGit v2.46.2.2 (tag v2.46.2.windows.2):
#   Git for Windows v2.46 is the LAST version to support Windows 7 (confirmed
#   by release notes: "Git for Windows v2.46 is the last version to support
#   for Windows 7 and for Windows 8"). v2.46.2.windows.2 is the latest patch
#   in the v2.46 series. Newer versions (v2.47+) drop Win7 support in the
#   underlying MSYS2 runtime and use BCrypt APIs that fail on Win7 at first spawn.
#
# Why not full MSYS2 base:
#   MSYS2 base is ~50MB compressed / ~200MB+ expanded. We only need bash + a
#   few DLLs to satisfy shell_resolver._find_windows_bash() third-priority
#   candidate. MinGit already ships bash at usr/bin/bash.exe plus all MSYS2
#   runtime DLLs it needs — we just trim the Git-specific extras.
#
# What we keep:
#   usr/bin/bash.exe              ~2.5MB  (the bash shell)
#   usr/bin/sh.exe                symlink (used by shebangs)
#   usr/bin/msys-*.dll            ~6MB    (POSIX runtime + deps)
#   etc/passwd, group, fstab      <1KB    (bash requires these for user lookup)
#   usr/share/licenses/                   (GPL compliance — required to keep)
#
# What we drop:
#   cmd/*.exe                             (git.exe, ssh.exe, etc. — not needed)
#   mingw64/                              (MinGW toolchain — bash doesn't need it)
#   usr/share/{doc,man,locale,info}/      (docs/translations — bash doesn't read)
#   tmp/                                  (writable at runtime — not in installer)
#
# Final size target: ~10-15MB (vs ~37MB untrimmed MinGit)
#
# Output: resources/tools/git-bash/{etc/,usr/bin/,usr/share/licenses/,...}
#
# Verification: runs bash.exe -c "echo OK" at the end to catch missing-DLL
# regressions before electron-builder picks the bundle up.

$ErrorActionPreference = "Stop"

# Configuration
$MinGitVersion = "2.46.2.2"
# Git for Windows release tag format: v2.46.2.windows.2 (note the .windows.N suffix)
$MinGitTag = "v2.46.2.windows.2"
$MinGitUrl = "https://github.com/git-for-windows/git/releases/download/$MinGitTag/MinGit-$MinGitVersion-64-bit.zip"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$ToolsDir = Join-Path $ResourcesDir "tools"
$GitBashDir = Join-Path $ToolsDir "git-bash"
$MinGitZip = Join-Path $ResourcesDir "MinGit.zip"

Write-Host "=== MinGit bash bundler for Win7 LTS ===" -ForegroundColor Cyan
Write-Host "MinGit version: $MinGitVersion"
Write-Host "Destination: $GitBashDir"
Write-Host ""

# Clean previous run
if (Test-Path $GitBashDir) {
    Write-Host "Cleaning previous tools/git-bash..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $GitBashDir
}

# Ensure parent directory exists
if (-not (Test-Path $ToolsDir)) {
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
}

# Download MinGit
Write-Host "Downloading MinGit $MinGitVersion (this is ~35MB, may take 1-2 min)..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $MinGitUrl -OutFile $MinGitZip -UseBasicParsing -TimeoutSec 300
} catch {
    throw "MinGit download failed: $_ (URL: $MinGitUrl)"
}
if (-not (Test-Path $MinGitZip)) {
    throw "MinGit zip not found after download"
}

# Extract MinGit zip into a temp directory
Write-Host "Extracting MinGit..." -ForegroundColor Green
$ExtractTemp = Join-Path $ResourcesDir "_mingit_extract"
if (Test-Path $ExtractTemp) {
    Remove-Item -Recurse -Force $ExtractTemp
}
New-Item -ItemType Directory -Force -Path $ExtractTemp | Out-Null
Expand-Archive -Path $MinGitZip -DestinationPath $ExtractTemp -Force
Remove-Item $MinGitZip

# Detect zip layout: older MinGit zips wrap everything in a single subdir
# (e.g. mingit-2.44.0.2-64-bit/), but v2.46.2.2+ extracts flat (cmd/, usr/,
# etc/ at the zip root).  Handle both: prefer the single-subdir layout when
# it exists, otherwise treat the extract temp dir itself as the MinGit root.
$ChildDirs = @(Get-ChildItem -Path $ExtractTemp -Directory)
$ChildFiles = @(Get-ChildItem -Path $ExtractTemp -File)
if ($ChildDirs.Count -eq 1 -and $ChildFiles.Count -eq 0) {
    # Old-style zip: single parent directory wraps everything
    $MinGitRootPath = $ChildDirs[0].FullName
    Write-Host "MinGit zip layout: single parent dir ($($ChildDirs[0].Name))" -ForegroundColor Green
} else {
    # Flat zip: files/dirs at root of extract temp
    $MinGitRootPath = $ExtractTemp
    Write-Host "MinGit zip layout: flat (files at zip root, $($ChildDirs.Count) dirs, $($ChildFiles.Count) files)" -ForegroundColor Green
}
Write-Host "MinGit root: $MinGitRootPath" -ForegroundColor Green

# Move MinGit contents to git-bash/ (which becomes our shipped layout)
Write-Host "Moving MinGit to tools/git-bash/..." -ForegroundColor Green
if ($MinGitRootPath -eq $ExtractTemp) {
    # Flat layout: move all children out of ExtractTemp into GitBashDir
    New-Item -ItemType Directory -Force -Path $GitBashDir | Out-Null
    Get-ChildItem -Path $ExtractTemp | ForEach-Object {
        Move-Item -Path $_.FullName -Destination $GitBashDir -Force
    }
    Remove-Item -Recurse -Force $ExtractTemp
} else {
    # Parent-dir layout: move the single subdir directly
    Move-Item -Path $MinGitRootPath -Destination $GitBashDir -Force
    Remove-Item -Recurse -Force $ExtractTemp
}

# Trim unneeded directories
Write-Host "Trimming unneeded files..." -ForegroundColor Green

# Drop mingw64 entirely — bash doesn't need MinGW toolchain
$mingwDir = Join-Path $GitBashDir "mingw64"
if (Test-Path $mingwDir) {
    Write-Host "  - removing mingw64/" -ForegroundColor DarkGray
    Remove-Item -Recurse -Force $mingwDir
}

# Drop cmd/ entirely — bash doesn't need git.exe, ssh.exe, etc.
$cmdDir = Join-Path $GitBashDir "cmd"
if (Test-Path $cmdDir) {
    Write-Host "  - removing cmd/" -ForegroundColor DarkGray
    Remove-Item -Recurse -Force $cmdDir
}

# Drop documentation/translation (bash doesn't read these)
$shareDir = Join-Path $GitBashDir "usr\share"
if (Test-Path $shareDir) {
    foreach ($sub in @("doc", "man", "info", "locale", "git-core", "gitk", "git-gui")) {
        $path = Join-Path $shareDir $sub
        if (Test-Path $path) {
            Write-Host "  - removing usr/share/$sub/" -ForegroundColor DarkGray
            Remove-Item -Recurse -Force $path
        }
    }
}

# Trim usr/bin/ — keep only bash + sh + msys-*.dll
$binDir = Join-Path $GitBashDir "usr\bin"
if (Test-Path $binDir) {
    $keepPatterns = @(
        "^bash\.exe$",
        "^sh\.exe$",
        "^msys-.+\.dll$"
    )
    $removed = 0
    $kept = 0
    Get-ChildItem -Path $binDir -File | ForEach-Object {
        $matched = $false
        foreach ($pattern in $keepPatterns) {
            if ($_.Name -match $pattern) {
                $matched = $true
                break
            }
        }
        if ($matched) {
            $kept++
        } else {
            Remove-Item -Path $_.FullName -Force
            $removed++
        }
    }
    Write-Host "  - usr/bin/: kept $kept, removed $removed" -ForegroundColor DarkGray
}

# Sanity check: bash.exe must exist after trim
$BashExe = Join-Path $GitBashDir "usr\bin\bash.exe"
if (-not (Test-Path $BashExe)) {
    throw "bash.exe missing after trim — bundle is broken"
}
$MsysDll = Join-Path $GitBashDir "usr\bin\msys-2.0.dll"
if (-not (Test-Path $MsysDll)) {
    throw "msys-2.0.dll missing after trim — bash.exe will fail to launch"
}

# Verification: launch bash.exe and run a no-op command
Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
Write-Host "Testing bundled bash.exe can launch..."
$bashOutput = & $BashExe -c "echo SAGE_BASH_OK" 2>&1
$bashExit = $LASTEXITCODE
if ($bashExit -ne 0) {
    Write-Host $bashOutput
    throw "Bundled bash.exe failed to run (exit $bashExit). Likely missing a required DLL."
}
if ($bashOutput -notmatch "SAGE_BASH_OK") {
    Write-Host $bashOutput
    throw "Bundled bash.exe ran but produced unexpected output: $bashOutput"
}
Write-Host "bash.exe output: $bashOutput" -ForegroundColor Green

# Size report
$totalBytes = (Get-ChildItem -Path $GitBashDir -Recurse | Measure-Object -Property Length -Sum).Sum
$totalMb = [math]::Round($totalBytes / 1MB, 1)
Write-Host ""
Write-Host "=== MinGit bash bundled successfully! ===" -ForegroundColor Green
Write-Host "Total size: $totalMb MB (target: 10-15 MB)" -ForegroundColor Yellow
Write-Host "Path: $GitBashDir" -ForegroundColor Green
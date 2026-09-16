# Bundle MSYS2 bash from PortableGit for Win7 LTS installer
#
# Downloads PortableGit into resources/tools/git-bash/ so the Sage Win7
# installer has a usable bash even on machines without Git for Windows
# (Win7 SP1 ships with PowerShell 2.0 only — see PR #911).
#
# Why PortableGit v2.46.2 (tag v2.46.2.windows.1):
#   Git for Windows v2.46 is the LAST version to support Windows 7 (confirmed
#   by release notes: "Git for Windows v2.46 is the last version to support
#   for Windows 7 and for Windows 8"). v2.46.2.windows.1 is the latest release
#   with PortableGit assets. Newer versions (v2.47+) drop Win7 support in the
#   underlying MSYS2 runtime and use BCrypt APIs that fail on Win7 at first spawn.
#   Note: MinGit does NOT include bash.exe (omits Git Bash entirely), so
#   PortableGit is required.
#
# Why not full PortableGit as-is:
#   PortableGit is ~60MB compressed / ~250MB+ expanded. We only need bash + MSYS2
#   runtime DLLs to satisfy shell_resolver._find_windows_bash() third-priority
#   candidate. We trim the mingw64 toolchain, Git binaries, and doc files
#   down to ~10-15MB.
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
# Final size target: ~10-15MB (vs ~250MB untrimmed PortableGit)
#
# Output: resources/tools/git-bash/{etc/,usr/bin/,usr/share/licenses/,...}
#
# Verification: runs bash.exe -c "echo OK" at the end to catch missing-DLL
# regressions before electron-builder picks the bundle up.

$ErrorActionPreference = "Stop"

# Configuration
$GitVersion = "2.46.2"
$GitTag = "v2.46.2.windows.1"
$PortableGitExeName = "PortableGit-$GitVersion-64-bit.7z.exe"
$PortableGitUrl = "https://github.com/git-for-windows/git/releases/download/$GitTag/$PortableGitExeName"
$ResourcesDir = Join-Path $PSScriptRoot "..\resources"
$ToolsDir = Join-Path $ResourcesDir "tools"
$GitBashDir = Join-Path $ToolsDir "git-bash"
$DownloadTarget = Join-Path $ResourcesDir $PortableGitExeName

Write-Host "=== Git Bash bundler for Win7 LTS ===" -ForegroundColor Cyan
Write-Host "PortableGit version: $GitVersion"
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

# Download PortableGit
Write-Host "Downloading PortableGit $GitVersion (this is ~60MB, may take 1-2 min)..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $PortableGitUrl -OutFile $DownloadTarget -UseBasicParsing -TimeoutSec 300
} catch {
    throw "PortableGit download failed: $_ (URL: $PortableGitUrl)"
}
if (-not (Test-Path $DownloadTarget)) {
    throw "PortableGit installer not found after download"
}

# Extract PortableGit (7z self-extracting archive)
Write-Host "Extracting PortableGit to tools/git-bash/..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $GitBashDir | Out-Null

# Try 7z.exe first (available on GitHub Actions Windows runners), fall back to running the SFX directly
$7zPath = "C:\Program Files\7-Zip\7z.exe"
if (Test-Path $7zPath) {
    Write-Host "Using 7z.exe to extract..." -ForegroundColor DarkGray
    & $7zPath x -y -o"$GitBashDir" $DownloadTarget | Out-Null
} else {
    Write-Host "Running SFX installer directly..." -ForegroundColor DarkGray
    $process = Start-Process -FilePath $DownloadTarget -ArgumentList "-y", "-gm2", "-bd", "-o`"$GitBashDir`"" -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "PortableGit SFX extraction failed with exit code $($process.ExitCode)"
    }
}
Remove-Item $DownloadTarget -Force

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
    Get-ChildItem -LiteralPath $binDir -File | ForEach-Object {
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
            # Use -LiteralPath to prevent PowerShell treating filenames like '[.exe'
            # (the MSYS2 POSIX test alias) as wildcard character sets.
            Remove-Item -LiteralPath $_.FullName -Force
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
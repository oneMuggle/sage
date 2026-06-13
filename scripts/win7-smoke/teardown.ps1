# Win7 烟测 Step 5: Teardown — 卸载 Sage + 清理 + 收集诊断日志
#
# 用法 (Win7 VM 管理员 PowerShell):
#   .\teardown.ps1 [-KeepLogs]
#
# 行为:
#   1. 停止 Sage.exe (如果还在跑)
#   2. 停止 conda/pythonw 后端子进程
#   3. 通过 NSIS 卸载 (调用 uninstall.exe /S)
#   4. 验证安装目录已删除
#   5. 收集 Sage 日志到 smoke-results/ 目录
#   6. (除非 -KeepLogs) 清空所有结果 JSON 准备下次烟测

param(
    [Parameter(Mandatory = $false)]
    [switch]$KeepLogs,

    [Parameter(Mandatory = $false)]
    [string]$ExpectedInstallPath = "$env:LOCALAPPDATA\Programs\Sage"
)

$ErrorActionPreference = 'Continue'
$result = @{
    timestamp = (Get-Date -Format 'o')
    checks    = @{}
}

# 1. 停止 Sage.exe
$sageProcs = Get-Process Sage -ErrorAction SilentlyContinue
foreach ($p in $sageProcs) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
$result.checks.kill_sage = @{
    killed_count = @($sageProcs).Count
    pass = $true
}

# 2. 停止后端 python 进程
$backendProcs = Get-Process python, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*backend/main.py*' -or $_.CommandLine -like '*uvicorn*backend.main*' }
foreach ($p in $backendProcs) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
$result.checks.kill_backend = @{
    killed_count = @($backendProcs).Count
    pass = $true
}

# 3. NSIS 卸载
$uninstaller = Get-ChildItem -Path "$ExpectedInstallPath\Uninstall*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($uninstaller) {
    $proc = Start-Process -FilePath $uninstaller.FullName -ArgumentList '/S' -PassThru -Wait
    $result.checks.uninstall = @{
        path = $uninstaller.FullName
        exit_code = $proc.ExitCode
        pass = $proc.ExitCode -eq 0
    }
} else {
    $result.checks.uninstall = @{
        path = $null
        pass = $false
        error = 'Uninstaller not found'
    }
}

# 4. 验证安装目录已删除 (NSIS 卸载完成)
Start-Sleep -Seconds 3
$dirExists = Test-Path $ExpectedInstallPath
$result.checks.dir_removed = @{
    path = $ExpectedInstallPath
    exists = $dirExists
    pass = -not $dirExists
}

# 5. 收集日志 (C:\Users\<user>\AppData\Roaming\Sage\logs\)
$logSrc = Join-Path $env:APPDATA 'Sage\logs'
$logDest = Join-Path $PSScriptRoot "smoke-results"
if (-not (Test-Path $logDest)) { New-Item -ItemType Directory -Path $logDest -Force | Out-Null }
if (Test-Path $logSrc) {
    Copy-Item -Path "$logSrc\*" -Destination $logDest -Recurse -Force -ErrorAction SilentlyContinue
    $result.checks.logs_collected = @{
        src = $logSrc
        dest = $logDest
        file_count = (Get-ChildItem $logDest -Recurse -File | Measure-Object).Count
        pass = $true
    }
} else {
    $result.checks.logs_collected = @{
        src = $logSrc
        exists = $false
        pass = $true # 没有日志目录也算 OK
    }
}

# 6. 清理结果 JSON (准备下次烟测)
if (-not $KeepLogs) {
    Get-ChildItem -Path $PSScriptRoot -Filter '*-result.json' -ErrorAction SilentlyContinue | Remove-Item -Force
}

$outPath = Join-Path $PSScriptRoot 'teardown-result.json'
$result | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8

Write-Host ""
Write-Host "==== Win7 烟测 — Teardown ===="
foreach ($key in $result.checks.Keys) {
    $check = $result.checks[$key]
    $status = if ($check.pass) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1,-18} {2}" -f $status, $key, ($check | ConvertTo-Json -Compress))
}

$allPass = ($result.checks.Values | ForEach-Object { $_.pass } | Where-Object { -not $_ }).Count -eq 0
Write-Host ""
Write-Host ("Overall: {0}" -f $(if ($allPass) { 'PASS — Sage 已完全卸载, 烟测结束' } else { 'PARTIAL — 见上方 FAIL 项' }))
Write-Host "Logs: $logDest"
Write-Host "Result file: $outPath"
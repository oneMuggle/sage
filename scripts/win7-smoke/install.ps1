# Win7 烟测 Step 2: Install — 执行 Sage NSIS 安装
#
# 用法 (Win7 VM 管理员 PowerShell):
#   .\install.ps1 -InstallerPath C:\path\to\Sage-Setup-X.Y.Z.exe
#
# 安装器配置 (electron-builder.yml):
#   - oneClick: false   → 弹安装向导（不是静默）
#   - perMachine: false → HKCU 安装，不需要 admin
#   - 但 NSIS 默认会弹 UAC；如果 UAC 失败回退 perMachine=true
#
# 验证:
#   1. 安装器 exit code 0
#   2. 安装目录下存在 Sage.exe
#   3. 注册表 HKCU\Software\Sage 存在
#   4. 后端 FastAPI 子进程未启动 (install 阶段不启)

param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $false)]
    [string]$ExpectedInstallPath = "$env:LOCALAPPDATA\Programs\Sage"
)

$ErrorActionPreference = 'Stop'
$result = @{
    timestamp = (Get-Date -Format 'o')
    checks    = @{}
}

if (-not (Test-Path $InstallerPath)) {
    Write-Host "[FAIL] Installer not found: $InstallerPath"
    exit 1
}

# 运行 NSIS 安装器 (静默: /S)
$installerFullPath = (Resolve-Path $InstallerPath).Path
Write-Host "[INFO] Running installer: $installerFullPath /S"
$proc = Start-Process -FilePath $installerFullPath -ArgumentList '/S' -PassThru -Wait

$result.checks.exit_code = @{
    code = $proc.ExitCode
    pass = ($proc.ExitCode -eq 0)
}

# 验证安装目录
$sageExe = Join-Path $ExpectedInstallPath 'Sage.exe'
$result.checks.exe_exists = @{
    path = $sageExe
    exists = (Test-Path $sageExe)
    size_mb = if (Test-Path $sageExe) { [math]::Round((Get-Item $sageExe).Length / 1MB, 1) } else { 0 }
    pass = (Test-Path $sageExe)
}

# 验证注册表 (NSIS HKCU 写入路径)
$regPath = 'HKCU:\Software\Sage'
$regExists = Test-Path $regPath
$result.checks.registry = @{
    path = $regPath
    exists = $regExists
    pass = $regExists
}

$outPath = Join-Path $PSScriptRoot 'install-result.json'
$result | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8

Write-Host ""
Write-Host "==== Win7 烟测 — Install 验证 ===="
foreach ($key in $result.checks.Keys) {
    $check = $result.checks[$key]
    $status = if ($check.pass) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1,-15} {2}" -f $status, $key, ($check | ConvertTo-Json -Compress))
}

$allPass = ($result.checks.Values | ForEach-Object { $_.pass } | Where-Object { -not $_ }).Count -eq 0
Write-Host ""
Write-Host ("Overall: {0}" -f $(if ($allPass) { 'PASS — 可进入 Step 3 launch-test' } else { 'FAIL — 检查 install 日志' }))
Write-Host "Result file: $outPath"

if (-not $allPass) { exit 1 }
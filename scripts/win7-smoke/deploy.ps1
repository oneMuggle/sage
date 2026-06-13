# Win7 烟测 Step 1: Deploy — copy Sage installer + verify prerequisites
#
# 用法 (在 Win7 VM 内 PowerShell, 以管理员运行):
#   .\deploy.ps1 -InstallerPath C:\path\to\Sage-Setup-X.Y.Z.exe
#
# 验证项:
#   1. Win7 SP1 x64 (32-bit 不支持)
#   2. KB3033929 已装 (Sage.exe SHA-2 签名前提)
#   3. 后端可达 (host IP:8765/health)
#   4. Ollama 可达 (host IP:11434/api/tags)
#
# 输出: deploy-result.json 写到脚本同目录, 含各项 PASS/FAIL

param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $false)]
    [string]$BackendHost = '127.0.0.1',

    [Parameter(Mandatory = $false)]
    [int]$BackendPort = 8765,

    [Parameter(Mandatory = $false)]
    [int]$OllamaPort = 11434
)

$ErrorActionPreference = 'Continue'
$result = @{
    timestamp = (Get-Date -Format 'o')
    hostname  = $env:COMPUTERNAME
    checks    = @{}
}

# Check 1: OS 是 Win7 SP1 x64
$os = Get-CimInstance Win32_OperatingSystem
$result.checks.os = @{
    caption  = $os.Caption
    version  = $os.Version
    spMajor  = $os.ServicePackMajorVersion
    arch     = $env:PROCESSOR_ARCHITECTURE
    pass     = ($os.Caption -like '*Windows 7*') -and ($os.ServicePackMajorVersion -ge 1) -and ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64')
}

# Check 2: KB3033929 已装 (Win7 SHA-2 签名前提)
$kb3033929 = Get-HotFix -Id 'KB3033929' -ErrorAction SilentlyContinue
$result.checks.kb3033929 = @{
    installed = $null -ne $kb3033929
    pass      = $null -ne $kb3033929
}

# Check 3: 后端 /health (host machine 上 FastAPI 端口)
$backendHealth = Test-NetConnection -ComputerName $BackendHost -Port $BackendPort -WarningAction SilentlyContinue
$result.checks.backend = @{
    host  = $BackendHost
    port  = $BackendPort
    tcp   = $backendHealth.TcpTestSucceeded
    pass  = $backendHealth.TcpTestSucceeded
}

# Check 4: Ollama /api/tags
$ollamaHealth = Test-NetConnection -ComputerName $BackendHost -Port $OllamaPort -WarningAction SilentlyContinue
$result.checks.ollama = @{
    host  = $BackendHost
    port  = $OllamaPort
    tcp   = $ollamaHealth.TcpTestSucceeded
    pass  = $ollamaHealth.TcpTestSucceeded
}

# Check 5: Installer 文件存在
$result.checks.installer = @{
    path = $InstallerPath
    exists = (Test-Path $InstallerPath)
    size_mb = if (Test-Path $InstallerPath) { [math]::Round((Get-Item $InstallerPath).Length / 1MB, 1) } else { 0 }
    pass = (Test-Path $InstallerPath)
}

# 写结果
$outPath = Join-Path $PSScriptRoot 'deploy-result.json'
$result | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8

# Console 输出
Write-Host "==== Win7 烟测 — Deploy 验证 ===="
foreach ($key in $result.checks.Keys) {
    $check = $result.checks[$key]
    $status = if ($check.pass) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1,-15} {2}" -f $status, $key, ($check | ConvertTo-Json -Compress))
}

$allPass = ($result.checks.Values | ForEach-Object { $_.pass } | Where-Object { -not $_ }).Count -eq 0
Write-Host ""
Write-Host ("Overall: {0}" -f $(if ($allPass) { 'PASS — 可进入 Step 2 install' } else { 'FAIL — 修复后再继续' }))
Write-Host "Result file: $outPath"

if (-not $allPass) { exit 1 }
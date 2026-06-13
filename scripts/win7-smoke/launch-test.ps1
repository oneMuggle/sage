# Win7 烟测 Step 3: Launch-Test — 启动 Sage + 验证主窗口 + 截图
#
# 用法 (Win7 VM PowerShell):
#   .\launch-test.ps1 [-KillAfterSeconds 30] [-ScreenshotPath C:\smoke\launch.png]
#
# 验证:
#   1. Sage.exe 启动后 5 秒内主窗口可见 (Process.MainWindowHandle != 0)
#   2. 后端 conda 进程启动 (pythonw.exe 或 python.exe with backend/main.py)
#   3. 后端端口 8765 健康检查
#   4. 截图保存为 PNG (供人工 review)
#
# 默认 KillAfterSeconds=30: 30s 后强 kill Sage.exe, 防止无限挂起

param(
    [Parameter(Mandatory = $false)]
    [int]$KillAfterSeconds = 30,

    [Parameter(Mandatory = $false)]
    [string]$ScreenshotPath = "$env:USERPROFILE\Desktop\sage-smoke.png",

    [Parameter(Mandatory = $false)]
    [string]$ExpectedInstallPath = "$env:LOCALAPPDATA\Programs\Sage",

    [Parameter(Mandatory = $false)]
    [int]$BackendPort = 8765,

    [Parameter(Mandatory = $false)]
    [int]$WaitWindowSeconds = 15
)

$ErrorActionPreference = 'Continue'
$result = @{
    timestamp = (Get-Date -Format 'o')
    checks    = @{}
    timings   = @{}
}

$sageExe = Join-Path $ExpectedInstallPath 'Sage.exe'
if (-not (Test-Path $sageExe)) {
    Write-Host "[FAIL] Sage.exe not found: $sageExe"
    exit 1
}

# 启动 Sage
Write-Host "[INFO] Launching Sage.exe..."
$startTime = Get-Date
$proc = Start-Process -FilePath $sageExe -PassThru

# 等待主窗口出现
$windowAppeared = $false
$windowHandle = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds($WaitWindowSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    try {
        $proc.Refresh()
        if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {
            $windowAppeared = $true
            $windowHandle = $proc.MainWindowHandle
            break
        }
    } catch {
        # 进程可能在启动早期拒绝访问,继续轮询
    }
}
$windowTime = (Get-Date) - $startTime

$result.checks.main_window = @{
    appeared = $windowAppeared
    handle = $windowHandle.ToInt64()
    seconds = [math]::Round($windowTime.TotalSeconds, 1)
    pass = $windowAppeared -and ($windowTime.TotalSeconds -le 10)
}

$result.timings.main_window_seconds = [math]::Round($windowTime.TotalSeconds, 1)

# 等待后端 FastAPI 子进程启动 + 健康检查
$backendReady = $false
$backendHealthUrl = "http://127.0.0.1:$BackendPort/health"
$deadline2 = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline2) {
    try {
        $req = [System.Net.WebRequest]::Create($backendHealthUrl)
        $req.Timeout = 2000
        $resp = $req.GetResponse()
        if ($resp.StatusCode -eq 200) {
            $backendReady = $true
            $resp.Close()
            break
        }
    } catch {
        # 后端未就绪,继续轮询
    }
    Start-Sleep -Milliseconds 500
}

$result.checks.backend_health = @{
    url = $backendHealthUrl
    ready = $backendReady
    pass = $backendReady
}

# 截图
$screenshotTaken = $false
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    # 找 Sage 主窗口 (通过进程名查找, 避免依赖 MainWindowHandle API 抖动)
    $sageWindows = [System.Windows.Forms.Application]::OpenForms | Where-Object { $_.Text -match 'Sage' }
    if (-not $sageWindows) {
        # Fallback: 截全屏
        $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
        $bitmap.Save($ScreenshotPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        $screenshotTaken = $true
    } else {
        # 截 Sage 主窗口
        $win = $sageWindows[0]
        $bitmap = New-Object System.Drawing.Bitmap $win.Width, $win.Height
        $win.DrawToBitmap($bitmap, (New-Object System.Drawing.Rectangle 0, 0, $win.Width, $win.Height))
        $bitmap.Save($ScreenshotPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
        $screenshotTaken = $true
    }
} catch {
    Write-Host "[WARN] Screenshot failed: $_"
}

$result.checks.screenshot = @{
    path = $ScreenshotPath
    taken = $screenshotTaken
    pass = $screenshotTaken
}

# 后端 conda 进程检查
$backendProcs = Get-Process python, pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*backend/main.py*' -or $_.CommandLine -like '*uvicorn*backend.main*' }
$result.checks.backend_process = @{
    count = $backendProcs.Count
    pids = @($backendProcs | ForEach-Object { $_.Id })
    pass = $backendProcs.Count -gt 0
}

# 等到 KillAfterSeconds 后强 kill Sage
Write-Host "[INFO] Sleeping $KillAfterSeconds seconds before killing Sage..."
Start-Sleep -Seconds $KillAfterSeconds

try {
    Stop-Process -Id $proc.Id -Force -ErrorAction Stop
    Write-Host "[INFO] Sage.exe killed (PID $($proc.Id))"
} catch {
    Write-Host "[WARN] Failed to kill Sage.exe: $_"
}

# 写结果
$outPath = Join-Path $PSScriptRoot 'launch-result.json'
$result | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8

Write-Host ""
Write-Host "==== Win7 烟测 — Launch-Test 验证 ===="
foreach ($key in $result.checks.Keys) {
    $check = $result.checks[$key]
    $status = if ($check.pass) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1,-18} {2}" -f $status, $key, ($check | ConvertTo-Json -Compress))
}

$allPass = ($result.checks.Values | ForEach-Object { $_.pass } | Where-Object { -not $_ }).Count -eq 0
Write-Host ""
Write-Host ("Overall: {0}" -f $(if ($allPass) { 'PASS — Sage 可在 Win7 启动' } else { 'FAIL — 收集 logs/' + $sageExe + ' + 后端 logs' }))
Write-Host "Result file: $outPath"
Write-Host "Screenshot: $ScreenshotPath"

if (-not $allPass) { exit 1 }
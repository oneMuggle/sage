# Win7 烟测 Step 4: Verify-Ollama — 验证 Sage 能调通 Ollama API
#
# 用法 (Win7 VM PowerShell):
#   .\verify-ollama.ps1 -OllamaHost <host-ip> [-OllamaPort 11434]
#
# 这个脚本**不启动 Sage UI**, 直接用 PowerShell 模拟 IPC:
#   1. 测 Ollama /api/tags 通 (确认模型存在)
#   2. 测 Ollama /api/generate 流式 (确认 chat 流走通)
#   3. 测 FastAPI 后端 /health + /chat 通 (IPC 完整链路)
#
# 目的: 隔离测试 LLM API 链路, 排错时知道是 Electron 渲染问题
#       还是 Ollama/后端连通问题

param(
    [Parameter(Mandatory = $true)]
    [string]$OllamaHost,

    [Parameter(Mandatory = $false)]
    [int]$OllamaPort = 11434,

    [Parameter(Mandatory = $false)]
    [string]$BackendHost = '127.0.0.1',

    [Parameter(Mandatory = $false)]
    [int]$BackendPort = 8765
)

$ErrorActionPreference = 'Continue'
$result = @{
    timestamp = (Get-Date -Format 'o')
    checks    = @{}
}

# Check 1: Ollama /api/tags
try {
    $tagsUrl = "http://${OllamaHost}:${OllamaPort}/api/tags"
    $tagsResp = Invoke-RestMethod -Uri $tagsUrl -Method GET -TimeoutSec 5
    $modelCount = if ($tagsResp.models) { @($tagsResp.models).Count } else { 0 }
    $result.checks.ollama_tags = @{
        url = $tagsUrl
        model_count = $modelCount
        first_model = if ($modelCount -gt 0) { $tagsResp.models[0].name } else { $null }
        pass = $modelCount -gt 0
    }
} catch {
    $result.checks.ollama_tags = @{
        url = "http://${OllamaHost}:${OllamaPort}/api/tags"
        error = $_.Exception.Message
        pass = $false
    }
}

# Check 2: Ollama /api/generate 流式 (取 1 个 token)
try {
    $genUrl = "http://${OllamaHost}:${OllamaPort}/api/generate"
    $modelName = if ($result.checks.ollama_tags.first_model) { $result.checks.ollama_tags.first_model } else { 'llama3.2:1b' }
    $body = @{
        model = $modelName
        prompt = 'hi'
        stream = $true
        options = @{ num_predict = 1 }
    } | ConvertTo-Json

    $genStart = Get-Date
    $genResp = Invoke-RestMethod -Uri $genUrl -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 30
    $genTime = (Get-Date) - $genStart

    $result.checks.ollama_generate = @{
        url = $genUrl
        model = $modelName
        response = $genResp.response
        eval_duration = $genResp.eval_duration
        seconds = [math]::Round($genTime.TotalSeconds, 2)
        pass = $genTime.TotalSeconds -le 30
    }
} catch {
    $result.checks.ollama_generate = @{
        error = $_.Exception.Message
        pass = $false
    }
}

# Check 3: 后端 /health
try {
    $healthResp = Invoke-RestMethod -Uri "http://${BackendHost}:${BackendPort}/health" -Method GET -TimeoutSec 5
    $result.checks.backend_health = @{
        url = "http://${BackendHost}:${BackendPort}/health"
        status = $healthResp.status
        pass = $healthResp.status -eq 'ok'
    }
} catch {
    $result.checks.backend_health = @{
        error = $_.Exception.Message
        pass = $false
    }
}

# Check 4: 后端 /chat (同步 chat 端点)
try {
    $sessionId = [guid]::NewGuid().ToString()
    $body = @{
        session_id = $sessionId
        message = 'ping'
        api_url = "http://${OllamaHost}:${OllamaPort}"
        model = if ($result.checks.ollama_tags.first_model) { $result.checks.ollama_tags.first_model } else { 'llama3.2:1b' }
    } | ConvertTo-Json

    $chatStart = Get-Date
    $chatResp = Invoke-RestMethod -Uri "http://${BackendHost}:${BackendPort}/chat" -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 60
    $chatTime = (Get-Date) - $chatStart

    $result.checks.backend_chat = @{
        url = "http://${BackendHost}:${BackendPort}/chat"
        session_id = $sessionId
        content_len = if ($chatResp.content) { $chatResp.content.Length } else { 0 }
        seconds = [math]::Round($chatTime.TotalSeconds, 1)
        pass = $chatTime.TotalSeconds -le 60 -and $chatResp.content
    }
} catch {
    $result.checks.backend_chat = @{
        error = $_.Exception.Message
        pass = $false
    }
}

$outPath = Join-Path $PSScriptRoot 'ollama-result.json'
$result | ConvertTo-Json -Depth 5 | Out-File -FilePath $outPath -Encoding UTF8

Write-Host ""
Write-Host "==== Win7 烟测 — Ollama/Backend 链路验证 ===="
foreach ($key in $result.checks.Keys) {
    $check = $result.checks[$key]
    $status = if ($check.pass) { 'PASS' } else { 'FAIL' }
    Write-Host ("[{0}] {1,-18} {2}" -f $status, $key, ($check | ConvertTo-Json -Compress))
}

$allPass = ($result.checks.Values | ForEach-Object { $_.pass } | Where-Object { -not $_ }).Count -eq 0
Write-Host ""
Write-Host ("Overall: {0}" -f $(if ($allPass) { 'PASS — IPC + Ollama 链路 OK' } else { 'FAIL — 链路问题, 需单独排错' }))
Write-Host "Result file: $outPath"

if (-not $allPass) { exit 1 }
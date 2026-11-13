@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Sage 网页模式启动脚本 (Win7 Fallback)
:: ============================================

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

:: 检查后端代码
if not exist "backend\main.py" (
    echo [错误] 未找到后端代码
    pause
    exit /b 1
)

:: 检查前端构建
if not exist "dist-web\index.html" (
    echo [提示] 构建网页版...
    call npm run build:web
    if %errorlevel% neq 0 (
        echo [错误] 前端构建失败
        pause
        exit /b 1
    )
)

:: 生成 token
for /f %%i in ('python -c "import secrets; print(secrets.token_urlsafe(32))"') do set TOKEN=%%i

set SAGE_LOCAL_AUTH_TOKEN=%TOKEN%
set SAGE_WEB_MODE=1
set PYTHON_BACKEND_PORT=8765

echo [1/3] 启动后端...
start /b python backend/main.py --web-mode

echo [2/3] 等待后端就绪...
set /a attempts=0
:wait_loop
if !attempts! geq 30 (
    echo [错误] 启动超时
    pause
    exit /b 1
)
timeout /t 1 >nul
curl -s http://127.0.0.1:8765/health >nul 2>&1
if errorlevel 1 (
    set /a attempts+=1
    goto wait_loop
)

echo [3/3] 打开浏览器...
start http://127.0.0.1:8765/?token=%TOKEN%

echo.
echo ========================================
echo  Sage 网页模式已启动
echo  http://127.0.0.1:8765
echo  Ctrl+C 停止
echo ========================================

pause >nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Sage*" >nul 2>&1

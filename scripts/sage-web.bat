@echo off
rem Sage 网页模式启动脚本（源码目录 / 开发用）
rem 安装版请使用开始菜单「Sage 网页模式」或安装目录下的 SageWeb.cmd。
rem 开发与安装版共用 backend.cli.web 的启动逻辑（选端口 / 生成 token / 等 /health / 开浏览器）。
setlocal

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先激活后端环境（conda activate sage-backend）。
    pause
    exit /b 1
)

if not exist "backend\main.py" (
    echo [错误] 请在 Sage 源码根目录运行此脚本。
    pause
    exit /b 1
)

if not exist "dist-web\index.html" (
    echo [提示] 未找到 dist-web，构建网页版...
    call npm run build:web
    if errorlevel 1 (
        echo [错误] 前端构建失败。
        pause
        exit /b 1
    )
)

python -m backend.cli.web %*
set "WEB_EXIT=%ERRORLEVEL%"
if not "%WEB_EXIT%"=="0" pause
exit /b %WEB_EXIT%

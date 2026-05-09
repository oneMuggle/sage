@echo off
REM Sage 安装脚本 - Windows
REM Windows 7 兼容版本

echo ========================================
echo   Sage - 记忆型 AI 助手 安装程序
echo ========================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [提示] 建议以管理员身份运行以安装依赖
    echo.
)

REM 检查 Python
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 goto :no_python
python --version
echo.

REM 检查 Node.js
echo [2/5] 检查 Node.js 环境...
node --version >nul 2>&1
if errorlevel 1 goto :no_node
node --version
echo.

REM 安装 Python 依赖
echo [3/5] 安装 Python 依赖...
if exist backend\requirements.txt (
    pip install -r backend\requirements.txt
    if errorlevel 1 goto :pip_error
) else (
    echo [警告] 未找到 backend\requirements.txt，跳过 Python 依赖安装
)
echo.

REM 安装 Node.js 依赖
echo [4/5] 安装 Node.js 依赖...
if exist package.json (
    call npm install
    if errorlevel 1 goto :npm_error
) else (
    echo [错误] 未找到 package.json
    goto :error
)
echo.

REM 安装 Rust (Tauri 需要)
echo [5/5] 检查 Rust 环境...
rustc --version >nul 2>&1
if errorlevel 1 (
    echo [警告] 未检测到 Rust，将无法构建 Tauri 应用
    echo          请访问 https://rustup.rs 安装 Rust
) else (
    rustc --version
)
echo.

echo ========================================
echo   安装完成！
echo ========================================
echo.
echo 接下来:
echo   1. 运行 `npm run tauri dev` 启动开发模式
echo   2. 或运行 `npm run tauri build` 构建应用
echo.
echo 详细文档请参阅 README.md
echo.
pause
exit /b 0

:no_python
echo [错误] 未找到 Python！
echo 请先安装 Python 3.8 或更高版本
echo 下载地址: https://www.python.org/downloads/
pause
exit /b 1

:no_node
echo [错误] 未找到 Node.js！
echo 请先安装 Node.js 18 或更高版本
echo 下载地址: https://nodejs.org/
pause
exit /b 1

:pip_error
echo [错误] Python 依赖安装失败！
pause
exit /b 1

:npm_error
echo [错误] Node.js 依赖安装失败！
pause
exit /b 1

:error
echo [错误] 安装过程中发生错误！
pause
exit /b 1

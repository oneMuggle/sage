@echo off
setlocal enabledelayedexpansion

:: ============================================================
:: Sage Win7 内网启动修复脚本
:: 用法：右键 → 以管理员身份运行
:: 第一次运行：启用 TrustedInstaller + wuauserv，然后提示重启
:: 重启后第二次运行：验证服务 + 提示启动 Sage
:: ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] 请以管理员身份运行本脚本
    echo     右键 cmd.exe -^> 以管理员身份运行,再执行本脚本
    pause
    exit /b 1
)

echo ============================================================
echo   Sage Win7 启动修复脚本
echo   (服务配置修复 -- 99%% 的情况这就够了)
echo ============================================================
echo.

:: ----- Step 1:检查服务状态 -----
echo [1/3] 检查服务状态 ...
set "TI_OK=0"
set "WU_OK=0"

sc query TrustedInstaller | findstr /i "RUNNING" >nul && set "TI_OK=1"
sc query wuauserv         | findstr /i "RUNNING" >nul && set "WU_OK=1"

if "!TI_OK!"=="1" echo     TrustedInstaller : running [OK]
if "!TI_OK!"=="0" echo     TrustedInstaller : not running [FIX]
if "!WU_OK!"=="1" echo     wuauserv         : running [OK]
if "!WU_OK!"=="0" echo     wuauserv         : not running [FIX]

:: ----- Step 2:修复服务(当需要时) -----
if "!TI_OK!!WU_OK!"=="11" (
    echo.
    echo [OK] 所有服务已在运行,跳过修复。
    goto :test_sage
)

echo.
echo [2/3] 修复服务 ...

if "!TI_OK!"=="0" (
    echo     启用 TrustedInstaller ...
    sc config TrustedInstaller start= demand >nul
    sc start TrustedInstaller >nul 2>&1
)

if "!WU_OK!"=="0" (
    echo     启用 wuauserv (写注册表 Start=3) ...
    reg add "HKLM\SYSTEM\CurrentControlSet\services\wuauserv" /v Start /t REG_DWORD /d 3 /f >nul

    echo     重新注册 WU DLL ...
    for %%D in (wuapi.dll wuaueng.dll wuaueng1.dll wucltui.dll wups.dll wups2.dll wuweb.dll) do (
        regsvr32 /s %%D
    )

    echo     尝试启动 wuauserv ...
    net start wuauserv >nul 2>&1
    sc query wuauserv | findstr /i "RUNNING" >nul
    if !errorlevel! neq 0 (
        echo.
        echo [!] wuauserv 启动失败。需要重启机器让注册表变更生效。
        echo     请按任意键重启,重启后**再次以管理员身份运行本脚本**。
        pause
        shutdown /r /t 0
        exit /b 0
    )
    echo     wuauserv 已启动。
)

:: ----- Step 3:验证 + 提示启动 Sage -----
:test_sage
echo.
echo [3/3] 验证服务状态 ...
set "ALL_OK=1"
sc query TrustedInstaller | findstr /i "RUNNING" >nul && echo     TrustedInstaller : running [OK] || set "ALL_OK=0"
sc query wuauserv         | findstr /i "RUNNING" >nul && echo     wuauserv         : running [OK] || set "ALL_OK=0"

if "!ALL_OK!"=="0" (
    echo.
    echo [X] 服务仍有未启动项,重启一次后再试。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [OK] 服务配置已修复。
echo   请启动 Sage 验证。
echo ============================================================
pause

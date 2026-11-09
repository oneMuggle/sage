@echo off
rem Sage 修复工具启动器（由 electron-builder extraFiles 放入安装目录）
rem 不依赖 Electron / Chromium；使用 bundled Python 运行 backend.cli.rescue。
setlocal

set "ROOT=%~dp0"
set "SAGE_IS_PACKAGED=1"

if not defined SAGE_USER_DATA_DIR set "SAGE_USER_DATA_DIR=%APPDATA%\Sage"
if not defined SAGE_DB_PATH set "SAGE_DB_PATH=%APPDATA%\Sage\sage.db"
set "PYTHONPATH=%ROOT%resources\backend;%ROOT%resources\sage-core"

if not exist "%ROOT%resources\python\python.exe" (
  rem Dev fallback: use python from PATH when the bundled runtime is absent.
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERROR] Bundled Python runtime not found:
    echo   %ROOT%resources\python\python.exe
    echo.
    echo The installation may be incomplete. Please reinstall Sage.
    pause
    exit /b 2
  )
  set "SAGE_IS_PACKAGED="
  pushd "%ROOT%.."
  python -m backend.cli.rescue %*
  set "RESCUE_EXIT=%ERRORLEVEL%"
  popd
  if not "%RESCUE_EXIT%"=="0" pause
  exit /b %RESCUE_EXIT%
)

"%ROOT%resources\python\python.exe" -m backend.cli.rescue %*
set "RESCUE_EXIT=%ERRORLEVEL%"

if not "%RESCUE_EXIT%"=="0" (
  echo.
  echo Rescue tool exit code: %RESCUE_EXIT%
  echo Diagnostics directory: %SAGE_USER_DATA_DIR%\diagnostics\
  pause
)
exit /b %RESCUE_EXIT%

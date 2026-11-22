@echo off
rem Sage 网页模式启动器（由 electron-builder extraFiles 放入安装目录）
rem 当 Electron 桌面端被安全软件拦截时，用浏览器打开 Sage。
rem 不依赖 Electron/Chromium；使用 bundled Python 运行 backend.cli.web。
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
    echo [ERROR] 未找到内置 Python 运行时：
    echo   %ROOT%resources\python\python.exe
    echo.
    echo 安装可能不完整，请重新安装 Sage。
    pause
    exit /b 2
  )
  set "SAGE_IS_PACKAGED="
  pushd "%ROOT%.."
  python -m backend.cli.web %*
  set "WEB_EXIT=%ERRORLEVEL%"
  popd
  exit /b %WEB_EXIT%
)

set "SAGE_WEB_MODE=1"
rem 默认解析（resources/dist-web）已可用；显式设置作为双保险。
set "SAGE_WEB_DIST_PATH=%ROOT%resources\dist-web"
if not defined SAGE_BUNDLED_MODELS_DIR set "SAGE_BUNDLED_MODELS_DIR=%ROOT%resources\models"
if not defined SAGE_DOCS_DIR set "SAGE_DOCS_DIR=%ROOT%resources\docs"

"%ROOT%resources\python\python.exe" -m backend.cli.web %*
set "WEB_EXIT=%ERRORLEVEL%"

if not "%WEB_EXIT%"=="0" (
  echo.
  echo 网页模式异常退出，退出码：%WEB_EXIT%
  pause
)
exit /b %WEB_EXIT%

@echo off
setlocal
rem Read-only diagnostics. Never override enterprise policy or reboot.
echo Sage Win7 offline diagnostics - no system settings will be changed.
echo.
ver
sc query TrustedInstaller
sc qc TrustedInstaller
sc query wuauserv
sc qc wuauserv
echo.
echo STOPPED or START_PENDING does not by itself mean Sage cannot run.
echo Ask your administrator to review the approved offline maintenance baseline.
echo Read: %~dp0sage-win7-fix.md
echo No registry changes, DLL registration, service startup or restart performed.
endlocal

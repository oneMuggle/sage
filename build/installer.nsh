; build/installer.nsh
;
; Custom NSIS macros for Sage installer.
; Wired in via electron-builder.yml: nsis.include = "build/installer.nsh"
;
; customInit:
;   1. Kill orphaned Python backend from previous install (path-scoped).
;      - On Win7 the Electron main process may crash or be force-killed,
;        leaving the Python backend (python.exe) still running as an orphan.
;        The default CHECK_APP_RUNNING only kills Sage.exe; if python.exe is
;        still bound to files under $INSTDIR, the file replacement in
;        installApplicationFiles will fail with "file in use" errors.
;      - We kill python.exe whose ExecutablePath starts with $INSTDIR\python\
;        via PowerShell Get-WmiObject (PS 2.0+, works on bare Win7 SP1).
;        Path-scoped so we don't kill user's other Python processes
;        (Anaconda, Jupyter, etc.). Get-CimInstance is NOT used because it
;        requires PS 3.0+ (absent on bare Win7 SP1).
;      - Sage.exe is handled by the default CHECK_APP_RUNNING macro which
;        shows a proper UI dialog and tries graceful close before force kill.
;   2. Cover-upgrade rollback staging.
;      - The running app writes `.prepare-rollback.bat` to the install's
;        parent directory before handing off to the installer. The batch
;        moves the current install to `.prev` so the NEW files land in a
;        clean directory and the OLD files remain available for `rollback()`.
;      - We execute the batch synchronously and wait for completion. If the
;        batch is missing (fresh install, no prior version) this is a no-op.
;
; customInstall: silently install VC++ 2015-2022 Redistributable (x64).
;   - vc_redist.x64.exe is loaded from BUILD_RESOURCES_DIR (= ./resources)
;     into $PLUGINSDIR at install time, then ExecWait runs the silent installer.
;   - The MS installer is idempotent: if VCRedist is already present (or newer),
;     it exits within ~5s without changes.
;   - Required for clean Win7 SP1 first-launch - Electron 21 native modules
;     (ffmpeg.dll, etc.) link against msvcp140.dll and friends.
;
; Reference: https://www.electron.build/configuration/nsis#custom-nsis-script

!macro customInit
  ; $INSTDIR is the target install directory (e.g. C:\Users\x\AppData\Local\Programs\Sage).
  ; For upgrades, this is populated from the registry before onInit runs.

  ; ── Kill orphaned Python backend (path-scoped) ────────────────────────────
  ; The previous install's Python backend may still be running if Electron
  ; crashed or was force-killed without running shutdownBackend(). Kill it
  ; here before the install starts, so file replacement won't fail with
  ; "file in use" errors on python.exe / backend DLLs.
  ;
  ; IMPORTANT: Path-scoped kill to avoid killing user's other Python processes
  ; (Anaconda, Jupyter, etc.). Uses Get-WmiObject (PS 2.0+ on bare Win7 SP1).
  ; Get-CimInstance requires PS 3.0+ (not on bare Win7); wmic.exe was removed
  ; in Win11 24H2+. If PowerShell is absent, skip silently — file-replacement
  ; will fail visibly if python.exe is actually holding files.
  ;
  ; NOTE: Sage.exe cleanup is intentionally NOT done here. The default
  ; CHECK_APP_RUNNING macro (from electron-builder's ALLOW_ONLY_ONE_INSTALLER_INSTANCE)
  ; already handles Sage.exe with a proper UI dialog and graceful-close attempt.
  DetailPrint "Cleaning up orphaned Python backend..."
  IfFileExists "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" 0 kill_python_done
    GetTempFileName $R0
    FileOpen $R1 $R0 w
    ; NSIS double-quote escaping: $\" → literal ", $$ → literal $, $INSTDIR/$R0 → expanded
    ; Resulting PS1 script:
    ;   Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    ;     Where-Object { $_.ExecutablePath -like '$INSTDIR\python\*' } |
    ;     ForEach-Object { $_.Terminate() } | Out-Null
    FileWrite $R1 "Get-WmiObject Win32_Process -Filter $\"Name='python.exe'$\" | Where-Object { $$_.ExecutablePath -like '$INSTDIR\python\*' } | ForEach-Object { $$_.Terminate() } | Out-Null$\r$\n"
    FileClose $R1
    nsExec::ExecToLog "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $\"$R0$\""
    Pop $0
    Delete $R0
  kill_python_done:

  ; Brief pause to let the OS release file handles from killed processes.
  Sleep 500

  ; ── Rollback staging ──────────────────────────────────────────────────────
  ; The prepare-rollback batch lives in $INSTDIR's parent.
  StrCpy $0 "$INSTDIR\.."
  StrCpy $1 "$0\.prepare-rollback.bat"
  IfFileExists "$1" 0 rollback_staging_done
  DetailPrint "Running rollback staging script: $1"
  nsExec::ExecToLog '"$1"'
  Pop $2
  ${If} $2 != 0
    DetailPrint "Rollback staging script exited with code $2 (continuing install)."
  ${EndIf}
rollback_staging_done:
!macroend

!macro customInstall
  DetailPrint "Installing Microsoft Visual C++ 2015-2022 Redistributable (x64)..."
  File "/oname=$PLUGINSDIR\vc_redist.x64.exe" "${BUILD_RESOURCES_DIR}\vc_redist.x64.exe"
  ExecWait '"$PLUGINSDIR\vc_redist.x64.exe" /install /quiet /norestart' $0
  ${If} $0 == 0
    DetailPrint "VC++ Redistributable installed successfully."
  ${ElseIf} $0 == 1638
    DetailPrint "VC++ Redistributable already installed (or newer version present)."
  ${Else}
    DetailPrint "VC++ Redistributable installer exited with code $0 (non-fatal, continuing)."
  ${EndIf}
!macroend

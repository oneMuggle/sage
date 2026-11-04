; build/installer.nsh
;
; Custom NSIS macros for Sage installer.
; Wired in via electron-builder.yml: nsis.include = "build/installer.nsh"
;
; customCheckAppRunning: replaces electron-builder's built-in CHECK_APP_RUNNING
; (which force-kills only its own PID tree and then gives up with a modal
; "cannot be closed" error). Runs inside the install section, before
; uninstallOldVersion, so:
;   - $INSTDIR is final (directory page / /D= already applied);
;   - the installer's CWD has not entered $INSTDIR yet (SetOutPath comes
;     later), so renaming the old install directory cannot be blocked by a
;     locked working directory;
;   - the instfiles page is visible, so DetailPrint updates the status line.
;
;   1. Ask a running Sage.exe to exit gracefully (taskkill without /F sends
;      WM_CLOSE → before-quit releases the Python backend and file handles).
;   2. Poll for up to ~5s, then force-kill the process tree.
;   3. Sweep an orphaned Python backend (left behind by a crash or a manual
;      "close" that only killed Electron).
;   4. Interactive installs get one Retry/Cancel dialog as a last resort;
;      silent installs continue and let the file copy report a real error.
;   5. Run the rollback staging batch (installer only, never the uninstaller).
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

!macro customCheckAppRunning
  ; Defines a helper string: tasklist filtered to Sage.exe, piped through
  ; findstr so the exit code is 0 only when such a process exists.
  !define SAGE_TASKLIST_CHECK 'cmd /c tasklist /FI "IMAGENAME eq Sage.exe" /NH | findstr /I /C:"Sage.exe"'

  nsExec::ExecToStack '${SAGE_TASKLIST_CHECK}'
  Pop $R0

  ${If} $R0 == 0
    DetailPrint "正在关闭 Sage，请稍候…"
    DetailPrint "Closing Sage gracefully..."

    ; No /F: taskkill posts WM_CLOSE to GUI processes, letting Electron run
    ; its before-quit cleanup. /T still covers the Python backend child tree.
    nsExec::ExecToLog 'taskkill /IM "Sage.exe" /T'
    Pop $R0

    StrCpy $R2 0
    ${While} $R2 < 10
      Sleep 500
      nsExec::ExecToStack '${SAGE_TASKLIST_CHECK}'
      Pop $R0
      ${If} $R0 != 0
        StrCpy $R2 10
      ${Else}
        IntOp $R2 $R2 + 1
      ${EndIf}
    ${EndWhile}

    ${If} $R0 == 0
      DetailPrint "Sage 未能自行退出，正在强制关闭…"
      DetailPrint "Sage did not exit on its own, force-closing..."
      nsExec::ExecToLog 'taskkill /F /IM "Sage.exe" /T'
      Pop $R0
      Sleep 500
    ${EndIf}
  ${EndIf}

  ; Orphaned backend sweep: also runs when Sage.exe was already gone (e.g. the
  ; user closed the window but a crashed/left-over backend still holds locks
  ; inside $INSTDIR). Skipped on fresh installs (no bundled runtime yet).
  ${If} $R0 == 0
  ${OrIf} ${FileExists} "$INSTDIR\resources\python\python.exe"
    ${If} ${FileExists} "$SYSDIR\wbem\wmic.exe"
      DetailPrint "正在清理残留的 Sage 后端进程…"
      DetailPrint "Terminating leftover Sage backend processes..."
      nsExec::ExecToLog "$\"$SYSDIR\wbem\wmic.exe$\" process where $\"name='python.exe' and commandline like '%-m backend.main%'$\" call terminate"
      Pop $R0
    ${EndIf}
  ${EndIf}

  ; Last resort for interactive installs. Silent installs skip the dialog:
  ; there is nobody to click it, and the file copy will surface a real error.
  nsExec::ExecToStack '${SAGE_TASKLIST_CHECK}'
  Pop $R0
  ${If} $R0 == 0
    ${IfNot} ${Silent}
      ${While} $R0 == 0
        MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY sage_retry_force
        SetErrorLevel 2
        Quit
        sage_retry_force:
        nsExec::ExecToLog 'taskkill /F /IM "Sage.exe" /T'
        Pop $R0
        Sleep 1000
        nsExec::ExecToStack '${SAGE_TASKLIST_CHECK}'
        Pop $R0
      ${EndWhile}
    ${EndIf}
  ${EndIf}

  !ifndef BUILD_UNINSTALLER
    ; Rollback staging: the running app writes .prepare-rollback.bat to the
    ; install's parent before handing off to the installer. It moves the
    ; current install to .prev so the NEW files land in a clean directory and
    ; the OLD files stay available for rollback(). Missing on fresh installs.
    StrCpy $R1 "$INSTDIR\..\.prepare-rollback.bat"
    IfFileExists "$R1" 0 sage_rollback_staging_done
    DetailPrint "Running rollback staging script: $R1"
    nsExec::ExecToLog 'cmd /c "$R1"'
    Pop $R0
    ${If} $R0 != 0
      DetailPrint "Rollback staging script exited with code $R0 (continuing install)."
    ${EndIf}
    sage_rollback_staging_done:
  !endif

  !undef SAGE_TASKLIST_CHECK
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

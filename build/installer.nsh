; build/installer.nsh
;
; Custom NSIS macros for Sage installer.
; Wired in via electron-builder.yml: nsis.include = "build/installer.nsh"
;
; customInit: cover-upgrade rollback staging.
;   - The running app writes `.prepare-rollback.bat` to the install's parent
;     directory before handing off to the installer. The batch moves the
;     current install to `.prev` so the NEW files land in a clean directory
;     and the OLD files remain available for `rollback()`.
;   - We execute the batch synchronously and wait for completion. If the
;     batch is missing (fresh install, no prior version) this is a no-op.
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
  ; The prepare-rollback batch lives in its parent.
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

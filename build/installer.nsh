; build/installer.nsh
;
; Custom NSIS macros for Sage installer.
; Wired in via electron-builder.yml: nsis.include = "build/installer.nsh"
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

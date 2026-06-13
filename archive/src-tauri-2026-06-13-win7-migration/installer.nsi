; Sage 自定义 NSIS 安装程序
; 针对 Windows 7 + 完全离线环境的特殊配置
;
; 编译方式: makensis /V3 installer.nsi
; 工作目录: src-tauri/
;
; 前置条件:
;   - target/x86_64-pc-windows-msvc/release/ 下已有 cargo build --release 产物
;   - ../dist/ 下已有前端构建产物 (npm run build)
;   - 注意: WebView2 安装由 Tauri 1.6 的 webviewInstallMode=offlineInstaller 自动处理
;     （不再需要本脚本手工安装 WebView2 v109）
;
; 安装包大小估算: 应用 (~10MB) + WebView2 standalone (~127MB) ≈ ~140MB
;   (WebView2 由 `tauri build` 从微软官方下载并 embed 到 MSI/NSIS)

!include "MUI2.nsh"
!include "LogicLib.nsh"

; --- 产品信息 ---
!define PRODUCT_NAME "Sage"
!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!define PRODUCT_PUBLISHER "Sage Team"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

!define MUI_ICON "icons\icon.ico"
!define MUI_UNICON "icons\icon.ico"

Name "${PRODUCT_NAME} ${VERSION}"
OutFile "target\release\Sage_${VERSION}_x64-setup.exe"

InstallDir "$LOCALAPPDATA\${PRODUCT_NAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Var WebView2ExitCode

Section "Sage"
    SetOutPath "$INSTDIR"

    ; --- 应用文件 (从 Tauri 构建产物) ---
    File /r "target\x86_64-pc-windows-msvc\release\Sage.exe"
    File /r "target\x86_64-pc-windows-msvc\release\*.dll"
    File /r "..\dist\"

    ; 创建快捷方式
    CreateShortCut "$SMPROGRAMS\Sage.lnk" "$INSTDIR\Sage.exe" "" "$INSTDIR\Sage.exe" 0
    CreateShortCut "$DESKTOP\Sage.lnk" "$INSTDIR\Sage.exe" "" "$INSTDIR\Sage.exe" 0

    ; 写入卸载信息
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${VERSION}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoRepair" 1

    ; 写入卸载程序
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\Sage.lnk"
    Delete "$DESKTOP\Sage.lnk"
    DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
SectionEnd

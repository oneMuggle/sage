; Sage 自定义 NSIS 安装程序
; 针对 Windows 7 + 完全离线环境的特殊配置
;
; 编译方式: makensis /V3 installer.nsi
; 工作目录: src-tauri/
;
; 前置条件:
;   - target/x86_64-pc-windows-msvc/release/ 下已有 cargo build --release 产物
;   - ../dist/ 下已有前端构建产物 (npm run build)
;   - resources/WebView2Runtime_109.exe 已存在 (Win7 兼容的 v109 离线安装包)
;
; 安装包大小估算: 应用 (~10MB) + WebView2 v109 (~127MB) ≈ ~140MB

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

Section "WebView2 Runtime (v109, Win7 兼容)"
    Call InstallWebView2
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\Sage.lnk"
    Delete "$DESKTOP\Sage.lnk"
    DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
SectionEnd

Function InstallWebView2
    ; 检查 WebView2 是否已安装
    ClearErrors
    ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ${If} $0 != ""
        DetailPrint "WebView2 运行时已安装 (版本: $0)"
        Return
    ${EndIf}

    ClearErrors
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ${If} $0 != ""
        DetailPrint "WebView2 运行时已安装 (版本: $0)"
        Return
    ${EndIf}

    ; WebView2 未安装，从资源目录提取并安装
    DetailPrint "正在安装 WebView2 运行时 (v109, Win7 兼容)..."

    SetOutPath "$TEMP\SageWebView2"
    File "resources\WebView2Runtime_109.exe"

    ExecWait '"$TEMP\SageWebView2\WebView2Runtime_109.exe" /silent /install' $WebView2ExitCode

    RMDir /r "$TEMP\SageWebView2"
    SetOutPath "$INSTDIR"

    ${If} $WebView2ExitCode != 0
        DetailPrint "WebView2 安装退出，代码: $WebView2ExitCode"
        MessageBox MB_ICONEXCLAMATION|MB_OK \
            "WebView2 运行时安装失败 (错误代码: $WebView2ExitCode)。$\n$\n\
            此应用需要 Microsoft WebView2 运行时才能运行。$\n\
            请联系系统管理员手动安装 WebView2 v109。" /SD IDOK
    ${Else}
        DetailPrint "WebView2 运行时安装成功"
    ${EndIf}
FunctionEnd

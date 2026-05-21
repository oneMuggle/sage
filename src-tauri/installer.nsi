; Sage 自定义 NSIS 安装程序
; 针对 Windows 7 + 完全离线环境的特殊配置
;
; 构建前准备:
; 1. 下载 WebView2 v109 离线安装包:
;    选择 "Fixed Version" 中的 v109.0.1518.78 (x64)
;    固定版本下载页: https://developer.microsoft.com/en-us/microsoft-edge/webview2/consumption/
;    直接下载:
;    https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/3b009565-19ab-4705-a7a3-5e1bf88e1341/MicrosoftEdgeWebView2RuntimeInstaller_x64_109.0.1518.78.exe
; 2. 将下载的文件重命名为 WebView2Runtime_109.exe
; 3. 放入 src-tauri/resources/ 目录
; 4. 运行 cargo tauri build
;
; 安装包大小估算: 应用 (~10MB) + WebView2 v109 (~127MB) ≈ ~140MB

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define PRODUCT_NAME "Sage"
!define PRODUCT_VERSION "${VERSION}"
!define PRODUCT_PUBLER "Sage Team"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

!define MUI_ICON "..\icons\icon.ico"
!define MUI_UNICON "..\icons\icon.ico"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Sage_${PRODUCT_VERSION}_x64-setup.exe"

InstallDir "$LOCALAPPDATA\${PRODUCT_NAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Var WebView2ExitCode

Section "Sage"
    SetOutPath "$INSTDIR"

    ; --- 应用文件 ---
    File /r "out\Sage\"

    ; 创建开始菜单快捷方式
    CreateShortCut "$SMPROGRAMS\Sage.lnk" "$INSTDIR\Sage.exe" "" "$INSTDIR\Sage.exe" 0
    CreateShortCut "$DESKTOP\Sage.lnk" "$INSTDIR\Sage.exe" "" "$INSTDIR\Sage.exe" 0

    ; 写入卸载信息
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKCU "${PRODUCT_DIR_REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKCU "${PRODUCT_DIR_REGKEY}" "NoModify" 1
    WriteRegDWORD HKCU "${PRODUCT_DIR_REGKEY}" "NoRepair" 1

    ; --- WebView2 运行时安装 (Win7 兼容: 固定 v109) ---
    Call InstallWebView2

    ; 写入卸载程序
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
    ; 删除文件
    RMDir /r "$INSTDIR"

    ; 删除快捷方式
    Delete "$SMPROGRAMS\Sage.lnk"
    Delete "$DESKTOP\Sage.lnk"

    ; 删除注册表
    DeleteRegKey HKCU "${PRODUCT_DIR_REGKEY}"
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
    File "${PROJECT_DIR}\resources\WebView2Runtime_109.exe"

    ExecWait '"$TEMP\SageWebView2\WebView2Runtime_109.exe" /silent /install' $WebView2ExitCode

    ; 清理临时文件
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

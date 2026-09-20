# Sage Win7 内网启动修复流程

> 适用症状：Sage 启动后"自检界面消失"（splash 显示后主窗口白屏/不出现）。
>
> 根因：Win7 内网机器常被企业组策略/管控软件禁用 `TrustedInstaller` 或 `wuauserv` 服务，导致 Electron 启动时某些 DLL 加载或进程管控异常。
>
> **补丁通常不是问题** —— 大部分 Win7 机器的 KB4474419 / KB3033929 已经装好。真正要修的是服务配置。

## 前提

- 管理员权限 cmd（右键 cmd → 以管理员身份运行）

## 步骤

### 1. 检查服务状态

```cmd
sc query TrustedInstaller | findstr /i "STATE"
sc query wuauserv | findstr /i "STATE"
```

期望：两个都 `RUNNING`。任何一个 `STOPPED` → 走步骤 2。

### 2. 启用服务（关键）

#### 2.1 启用 TrustedInstaller

```cmd
sc config TrustedInstaller start= demand
net start TrustedInstaller
```

#### 2.2 启用 wuauserv（最常出问题的）

`sc config` 在服务被硬禁时可能不生效，**直接写注册表**：

```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\services\wuauserv" /v Start /t REG_DWORD /d 3 /f
```

**然后必须重启机器**（wuauserv 启动类型变更必须重启才生效，`net start` 不够）：

```cmd
shutdown /r /t 0
```

### 3. 重启后验证服务已起

```cmd
sc query wuauserv | findstr /i "STATE"
sc query TrustedInstaller | findstr /i "STATE"
```

两个都 `RUNNING` → 继续步骤 4。

如果 wuauserv 仍然 `STOPPED`，重新注册 WU 相关 DLL 后再试：

```cmd
regsvr32 /s wuapi.dll
regsvr32 /s wuaueng.dll
regsvr32 /s wuaueng1.dll
regsvr32 /s wucltui.dll
regsvr32 /s wups.dll
regsvr32 /s wups2.dll
regsvr32 /s wuweb.dll
net start wuauserv
```

### 4. 启动 Sage

双击 `Sage-Setup-*.exe`，预期：splash 显示 → 后端启动 → **主窗口正常渲染**（不再"自检后消失"）。

### 5. （可选）wuauserv 改回自动启动

```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\services\wuauserv" /v Start /t REG_DWORD /d 2 /f
```

`Start=2` 是自动启动。内网机器不会真的连 WU 服务器，自动启动无副作用。保持 `Start=3`（手动）也可以。

## 如果上面做完 Sage 还起不来

才需要考虑补丁。先查：

```cmd
wmic qfe list brief | findstr /i "KB4474419 KB3033929"
```

应看到 2 行（KB4474419 SHA-2 代码签名、KB3033929 SHA-2 证书）。如果缺了某个，才走下面的补丁安装流程。

### 补丁安装顺序（仅在缺失时执行）

```cmd
:: 1) Servicing Stack（前提条件）
wusa windows6.1-kb4490628-x64_*.msu /quiet /norestart

:: 2) SHA-2 证书
wusa windows6.1-kb3033929-x64_*.msu /quiet /norestart

:: 3) SHA-2 代码签名 v3（Chromium 必需）
wusa windows6.1-kb4474419-v3-x64_*.msu /quiet /norestart

:: 4) Platform Update
wusa windows6.1-kb2670838-x64_*.msu /quiet /norestart
```

每个 1-5 分钟，装完重启：`shutdown /r /t 0`

## 失败对照表

| 错误 | 含义 | 处理 |
|---|---|---|
| `0x80070422` | 服务被禁用 | 检查 TrustedInstaller + wuauserv 都 running |
| `0x800705b4` | 安装超时 | 重启后重试 |
| `0x800f0906` | 缺 source 文件 | 需从 install.wim 提取，联系 IT |
| `0x80073712` | Component Store 损坏 | 跑 `sfc /scannow` 修复 |
| `0x80070005` | 权限不够 | 确认 cmd 是"以管理员身份运行" |
| 服务都 running 但 Sage 还白屏 | 可能是企业管控软件深度 hook | 临时退出管控软件（360 天擎 / 联软 / IP-guard） |

## 一键脚本

见同目录 `fix.bat`，以管理员身份运行即可自动执行步骤 1-3 + 重启。

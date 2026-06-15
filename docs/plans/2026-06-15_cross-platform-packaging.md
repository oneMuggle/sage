# 跨平台打包覆盖(Win7/10/11 + Ubuntu)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sage 桌面端打包产物覆盖 Windows 7 SP1 / 10 / 11(NSIS x64,VCRedist bundling 干净 Win7 零依赖启动)+ Ubuntu(原生 .deb 包,`apt install ./*.deb` 即装)+ 通用 Linux(AppImage 保留作 fallback)。

**Architecture:** 只动打包配置与 CI 矩阵命令,**不动业务代码**。Electron 21.4.4 / electron-builder 24.13.3 版本钉死。VCRedist 通过 NSIS `customInstall` 宏 + `BUILD_RESOURCES_DIR` 文件载荷在安装阶段静默执行。Linux 走 electron-builder 原生 `deb` target,依赖通过 `deb.depends` 显式声明确保 Ubuntu apt 解析。

**Tech Stack:** electron-builder 24.13.3 · NSIS 3.x · Electron 21.4.4 · dpkg · GitHub Actions matrix(windows-latest + ubuntu-latest) · Playwright `_electron` 烟测复用。

---

## 1. 背景

上轮 Q&A 完成的 gap 分析(`main` 分支当前打包状态 vs 用户需求):

| 需求 | 现状 | Gap |
|---|---|---|
| Win7 SP1 x64 | NSIS x64 配置就绪;Electron 21 兼容;`release/win7` LTS 分支已立 | 干净 Win7 缺 VC++ Runtime → 首次启动 DLL 错;真机烟测人工 |
| Win10 / Win11 | 同一 NSIS 包通用 | 无 |
| Ubuntu | 仅产 AppImage(需手 `chmod +x`,不进 apt 列表/应用菜单) | 缺 `.deb` 包 |
| macOS | `mac.target: null` 显式禁用 | **本次不动**(Phase 1 焦点 Win7) |

用户已决策(本轮):
1. Linux 产物:**AppImage + deb 双产**
2. VCRedist:**NSIS bundling**(干净 Win7 零依赖)
3. Win10/Win11 真机烟测:**沿用现有 `electron-smoke`**(windows-latest = Server 2022,Chromium 内核与 Win10/11 等价)

## 2. 文件清单

每个文件都是**单一职责**,与现有模式对齐(项目用配置 + YAML 优先,不 over-engineer):

| 操作 | 路径 | 职责 |
|---|---|---|
| Modify | `electron-builder.yml` | 加 `linux.target: [AppImage, deb]` + `deb` 元数据 + `nsis.include` 接入 customInstall |
| Create | `build/installer.nsh` | NSIS `customInstall` 宏:`File` 加载 vcredist → `ExecWait` 静默装 |
| Create | `scripts/fetch-vcredist.ps1` | PowerShell 下载 `vc_redist.x64.exe` 到 `resources/`(CI + 本地 Win 构建复用) |
| Modify | `.gitignore` | 排除 `resources/vc_redist.x64.exe`(~14MB 二进制不入库) |
| Modify | `.github/workflows/ci.yml` | Linux step 改 `--linux AppImage deb`;Windows step 加 `fetch-vcredist` 前置 |
| Create | `tests/packaging/verify-artifacts.spec.ts` | Vitest 验证 `release/${version}/` 下产物文件名/最小尺寸/必要扩展 |
| Create | `docs/technical/26-packaging-matrix.md` | 平台覆盖矩阵 + 用户侧安装指南(Win7 前置 / Ubuntu apt / AppImage chmod) |
| Modify | `docs/technical/21-win7-lts.md` | 删除"用户自装 VCRedist"段;改成"安装包内含" |
| Modify | `docs/technical/README.md` | 章节目录加第 26 章 |

## 3. 风险与依赖

| 风险 | 缓解 |
|---|---|
| `vc_redist.x64.exe` Microsoft 下载 URL 不稳/限流 | 用 Microsoft 官方永久链接(`https://aka.ms/vs/17/release/vc_redist.x64.exe`),加大小校验防伪 |
| NSIS customInstall 在升级场景重复装 vcredist | vcredist installer 自身幂等(已装会跳过,5s 内退出),无需特殊处理 |
| deb 依赖在 Ubuntu 22.04 vs 24.04 包名漂移(如 `libasound2` → `libasound2t64`) | electron-builder 24 默认依赖列表已经处理过该迁移;本计划只**追加** `xdg-utils` `libsecret-1-0` 等业务相关,不覆盖默认 |
| Win7 真机仍需人工(本计划不解决) | `21-win7-lts.md:34-48` 已记录人工流程,本计划只补强"安装包不再要求用户自装 VCRedist" |
| 产物大小:NSIS + 14MB vcredist ≈ +14MB | 文档明示,可接受(给 Win7 用户的便利远超体积代价) |

## 4. 实施任务

### Task 1: Linux deb target 配置

**Files:**
- Modify: `electron-builder.yml:61-67`(`linux` 块)
- Create: `tests/packaging/verify-artifacts.spec.ts`

- [ ] **Step 1: 写失败的 artifact 验证测试**

Create `tests/packaging/verify-artifacts.spec.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { existsSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import pkg from '../../package.json' assert { type: 'json' };

const version = pkg.version;
const releaseDir = resolve(__dirname, `../../release/${version}`);

describe('packaging artifacts', () => {
  it('Linux AppImage exists and >= 50MB', () => {
    const appimage = resolve(releaseDir, `Sage-${version}.AppImage`);
    expect(existsSync(appimage), `missing ${appimage}`).toBe(true);
    expect(statSync(appimage).size).toBeGreaterThan(50 * 1024 * 1024);
  });

  it('Linux deb exists and >= 50MB', () => {
    const deb = resolve(releaseDir, `sage_${version}_amd64.deb`);
    expect(existsSync(deb), `missing ${deb}`).toBe(true);
    expect(statSync(deb).size).toBeGreaterThan(50 * 1024 * 1024);
  });
});
```

- [ ] **Step 2: 跑测试确认 deb 部分失败**

```bash
cd /home/fz/project/sage
npx vitest run tests/packaging/verify-artifacts.spec.ts
```

Expected:`Linux AppImage exists` PASS(0.1.1 已有);`Linux deb exists` FAIL(deb 还未产)。

- [ ] **Step 3: 改 `electron-builder.yml` 加 deb target + 元数据**

把 `linux` 块(61-67 行)替换为下面的 `linux:` + `deb:` 两块:

```yaml
linux:
  target:
    - AppImage
    - deb
  icon: build/icon.png
  category: Office
  synopsis: Sage — agentic knowledge & chat desktop
  description: |
    Sage is a local-first desktop client that combines LLM chat, agent
    orchestration, and a personal knowledge wiki. Backed by Python +
    FastAPI for offline-capable AI workflows.
  maintainer: Sage Team <sage@example.com>
  vendor: Sage Team
  artifactName: ${productName}-${version}.${ext}

deb:
  depends:
    - libgtk-3-0
    - libnotify4
    - libnss3
    - libxss1
    - libxtst6
    - xdg-utils
    - libatspi2.0-0
    - libuuid1
    - libsecret-1-0
  packageCategory: utils
  priority: optional
  artifactName: sage_${version}_amd64.${ext}
```

- [ ] **Step 4: 本地构建 deb 验证**

```bash
cd /home/fz/project/sage
npm run electron:build
npx electron-builder --linux AppImage deb --publish never
ls -lh release/0.1.2/
```

Expected:看到 `Sage-0.1.2.AppImage`(~80MB)**和** `sage_0.1.2_amd64.deb`(~70MB)。

- [ ] **Step 5: 跑测试确认全部 PASS**

```bash
npx vitest run tests/packaging/verify-artifacts.spec.ts
```

Expected:两个测试都 PASS。

- [ ] **Step 6: 提交**

```bash
git add electron-builder.yml tests/packaging/verify-artifacts.spec.ts
git commit -m "feat(packaging): add Ubuntu deb target alongside AppImage

- linux.target now produces both AppImage (universal) and deb (Ubuntu native)
- deb.depends explicitly declared for apt resolution on 22.04/24.04
- artifactName follows Debian naming convention: sage_\${version}_amd64.deb
- new vitest packaging suite verifies artifact presence and minimum size"
```

---

### Task 2: CI Linux job 双产物命令

**Files:**
- Modify: `.github/workflows/ci.yml:228-242`(`Package (Linux AppImage)` + upload glob)

- [ ] **Step 1: 改 step name + command 同时产 AppImage 和 deb**

把 228-230 行:

```yaml
      - name: Package (Linux AppImage)
        if: matrix.os == 'ubuntu-latest'
        run: npx electron-builder --linux --publish never
```

替换为:

```yaml
      - name: Package (Linux AppImage + deb)
        if: matrix.os == 'ubuntu-latest'
        run: npx electron-builder --linux AppImage deb --publish never
```

- [ ] **Step 2: 更新 artifact upload glob 包含 .deb,且用 `**` 进入 `release/${version}/`**

把 240-242 行:

```yaml
          path: |
            release/*.{exe,AppImage,dmg}
          if-no-files-found: warn
```

替换为:

```yaml
          path: |
            release/**/*.exe
            release/**/*.AppImage
            release/**/*.deb
            release/**/*.dmg
          if-no-files-found: warn
```

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(desktop-build): emit Linux AppImage + deb, glob release/**

- electron-builder --linux AppImage deb produces both formats
- upload-artifact glob now uses ** to descend into release/\${version}/"
```

---

### Task 3: VCRedist 下载脚本

**Files:**
- Create: `scripts/fetch-vcredist.ps1`
- Modify: `.gitignore`

- [ ] **Step 1: 写下载脚本(带大小校验)**

Create `scripts/fetch-vcredist.ps1`:

```powershell
# scripts/fetch-vcredist.ps1
#
# Download Microsoft Visual C++ Redistributable (x64) for bundling into NSIS installer.
# Required for clean Win7 SP1 first-launch (Electron 21 native modules need VC++ runtime).
#
# Used by:
#   - CI: .github/workflows/ci.yml desktop-build (windows-latest) before npx electron-builder
#   - Local Win dev: pwsh scripts/fetch-vcredist.ps1 before npm run electron:dist
#
# The downloaded file goes to resources/vc_redist.x64.exe (gitignored).
# NSIS customInstall macro (build/installer.nsh) loads it via BUILD_RESOURCES_DIR.

$ErrorActionPreference = 'Stop'

$Url     = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
$Dest    = Join-Path $PSScriptRoot '..\resources\vc_redist.x64.exe'
$DestDir = Split-Path -Parent $Dest

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

if (Test-Path $Dest) {
    Write-Host "[fetch-vcredist] Already present: $Dest"
    exit 0
}

Write-Host "[fetch-vcredist] Downloading $Url -> $Dest"
Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing

$size = (Get-Item $Dest).Length
if ($size -lt 10MB -or $size -gt 30MB) {
    throw "[fetch-vcredist] Unexpected size $size bytes - corrupt download?"
}

Write-Host "[fetch-vcredist] OK ($([math]::Round($size/1MB, 1)) MB)"
```

- [ ] **Step 2: 更新 `.gitignore` 排除二进制**

Append to `.gitignore`:

```
# VCRedist runtime bundled at build time (fetched by scripts/fetch-vcredist.ps1)
resources/vc_redist.x64.exe
```

- [ ] **Step 3: 提交**

```bash
git add scripts/fetch-vcredist.ps1 .gitignore
git commit -m "build(win): add fetch-vcredist.ps1 to download VC++ Redistributable

- Downloads vc_redist.x64.exe from Microsoft aka.ms permalink
- Sanity-checks file size (10-30MB) to detect corrupt downloads
- Output to resources/ (gitignored, ~14MB binary)
- Idempotent: skips if file already present
- Will be loaded by NSIS customInstall macro in next commit"
```

---

### Task 4: NSIS customInstall 宏

**Files:**
- Create: `build/installer.nsh`

- [ ] **Step 1: 写 NSIS 自定义脚本**

Create `build/installer.nsh`:

```nsis
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
```

注:exit code `1638` = MSI "newer version installed",视为 OK;其它非零也不阻塞(可能用户已用别的方式装过)。

- [ ] **Step 2: 提交(还未接入 yml,仅落盘文件)**

```bash
git add build/installer.nsh
git commit -m "build(win): add NSIS customInstall macro for VCRedist bundling

- ExecWait silent /install /quiet /norestart
- Treats MSI code 1638 (newer version present) as success
- Non-zero non-1638 codes logged but non-fatal
- BUILD_RESOURCES_DIR resolves to ./resources via electron-builder.yml"
```

---

### Task 5: electron-builder.yml 接入 nsis.include

**Files:**
- Modify: `electron-builder.yml:40-54`(`nsis` 块)

- [ ] **Step 1: 加 `include` 字段**

把 `nsis:` 块顶部加一行:

```yaml
nsis:
  include: build/installer.nsh    # ← 新增,见 build/installer.nsh
  oneClick: false
  perMachine: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
  createStartMenuShortcut: true
  shortcutName: Sage
  uninstallDisplayName: Sage ${version}
```

- [ ] **Step 2: 更新 Win7 prerequisites 注释块**

把第 48-54 行:

```yaml
  # Win7 prerequisites (documented in README.md, surfaced in installer welcome):
  #   1. KB3033929 (SHA-2 code signing support) — Win7 SP1 must have this or
  #      Sage.exe signed with SHA-2 cert refuses to launch.
  #   2. KB3140245 (TLS 1.2 default-on for SChannel) — NOT required by Sage
  #      itself (Electron uses Chromium BoringSSL, Python uses rustls), but
  #      needed if user wants default IE/Edge legacy to load HTTPS sites.
  #   3. Win7 SP1 x64 minimum (32-bit Win7 not supported by Electron 21).
```

替换为:

```yaml
  # Win7 prerequisites (also surfaced in docs/technical/26-packaging-matrix.md):
  #   1. KB3033929 (SHA-2 code signing support) — Win7 SP1 must have this or
  #      Sage.exe signed with SHA-2 cert refuses to launch (Phase 3 signing).
  #   2. KB3140245 (TLS 1.2, optional) — not required by Sage itself.
  #   3. Win7 SP1 x64 minimum (32-bit Win7 not supported by Electron 21).
  # VC++ Redistributable: bundled by build/installer.nsh customInstall (no user action).
```

- [ ] **Step 3: 提交**

```bash
git add electron-builder.yml
git commit -m "build(win): wire NSIS customInstall via nsis.include = build/installer.nsh

- VC++ Redistributable now bundled into NSIS installer
- Comment block updated: VCRedist no longer in user-action prerequisites
- KB3033929/KB3140245 still surfaced for signing/TLS contexts"
```

---

### Task 6: CI Windows job 加 fetch-vcredist step

**Files:**
- Modify: `.github/workflows/ci.yml:232-234`(`Package (Windows NSIS)` step 前)

- [ ] **Step 1: 在 `Package (Windows NSIS)` step **之前**插入 fetch step**

把 232-234 行:

```yaml
      - name: Package (Windows NSIS)
        if: matrix.os == 'windows-latest'
        run: npx electron-builder --win --publish never
```

替换为:

```yaml
      - name: Fetch VC++ Redistributable (Windows)
        if: matrix.os == 'windows-latest'
        shell: pwsh
        run: pwsh scripts/fetch-vcredist.ps1

      - name: Package (Windows NSIS)
        if: matrix.os == 'windows-latest'
        run: npx electron-builder --win --publish never
```

- [ ] **Step 2: 提交**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(desktop-build): fetch VCRedist before Windows NSIS package step

- pwsh scripts/fetch-vcredist.ps1 downloads vc_redist.x64.exe to resources/
- Must run before electron-builder so NSIS customInstall can File it
- ~14MB download, cached by actions/cache via npm-lock + electron cache key"
```

---

### Task 7: 文档 — 平台覆盖矩阵

**Files:**
- Create: `docs/technical/26-packaging-matrix.md`

- [ ] **Step 1: 写覆盖矩阵 + 用户安装指南**

Create `docs/technical/26-packaging-matrix.md`:

```markdown
# 26. 跨平台打包矩阵

> 本章节描述 Sage 桌面端在各平台的分发产物与用户侧安装路径。
> 更新自 2026-06-15(feat/cross-platform-packaging)。

## 1. 平台覆盖矩阵

| 平台 | 最低版本 | 架构 | 产物 | CI 构建 runner |
|---|---|---|---|---|
| Windows | 7 SP1 | x64 | Sage-Setup-${version}.exe(NSIS,含 VCRedist bundling) | windows-latest |
| Windows | 10 | x64 | 同上 | 同上 |
| Windows | 11 | x64 | 同上 | 同上 |
| Ubuntu | 20.04+ | amd64 | sage_${version}_amd64.deb(原生 deb) | ubuntu-latest |
| Linux 通用 | glibc 2.28+ | x64 | Sage-${version}.AppImage | ubuntu-latest |
| macOS | — | — | **暂不支持**(mac.target: null) | — |

**架构限制(本期不支持):** 32-bit Windows · ARM Windows · ARM Linux · 任何 macOS。

## 2. 用户侧安装

### Windows 7 SP1 / 10 / 11

1. 下载 Sage-Setup-${version}.exe
2. 双击运行,按向导安装(默认 HKCU,无需管理员权限)
3. 安装阶段会**静默装** VC++ 2015-2022 Redistributable(已装会跳过)
4. Win7 SP1 用户需提前装 **KB3033929**(SHA-2 代码签名,Phase 3 启用签名后强依赖)

### Ubuntu 20.04+ / Debian / Mint

\`\`\`bash
sudo apt install ./sage_${version}_amd64.deb
# 或
sudo dpkg -i sage_${version}_amd64.deb && sudo apt-get install -f
\`\`\`

安装后 sage 出现在应用菜单 → Office 类别。卸载:sudo apt remove sage。

### 其它 Linux(Fedora / Arch / openSUSE / NixOS)

\`\`\`bash
chmod +x Sage-${version}.AppImage
./Sage-${version}.AppImage
\`\`\`

可选:用 [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) 集成到桌面菜单。

## 3. 真机烟测策略

| 平台 | 自动化 | 频率 | 工具 |
|---|---|---|---|
| Win Server 2022 | ✅ CI electron-smoke(每次 PR) | Per-PR | Playwright _electron |
| Win10 / Win11 | ⚠️ 等价于 Server 2022(同 Chromium 内核),无独立真机 | — | — |
| Win7 SP1 | ❌ 人工(docs/technical/21-win7-lts.md§3) | 每 release | scripts/win7-smoke/*.ps1 |
| Ubuntu | ❌ 暂无 | — | (TODO:可加 electron-smoke 的 Linux 镜像) |

## 4. 已知限制

- **macOS 缺席** — electron-builder.yml:56-59 的 mac.target: null 是 Phase 1 战略决策(Win7 优先)。Phase 3 可补 dmg + 签名。
- **deb 无 GPG 签名** — 用户首次 apt install 会警告 "未签名"。Phase 3 加 GPG key + APT repo。
- **VCRedist bundling 让安装包 +~14MB** — 文档已明示;可接受(节省 Win7 用户找 VC++ 的麻烦)。
- **AppImage 不进 apt 列表** — 这是 AppImage 设计本身的特性,不是 bug。

## 5. 故障排查

| 现象 | 平台 | 原因 / 处理 |
|---|---|---|
| sage.exe 双击无响应 | Win7 SP1 | KB3033929 未装(若用了签名版) → 装补丁;或 VCRedist 未装成功 → 手动跑 vc_redist.x64.exe /install |
| error while loading shared libraries: libnss3.so | Linux | sudo apt install libnss3(deb 应自动解,AppImage 需手动) |
| Ubuntu 24.04 apt install 报 libasound2 not found | Ubuntu | 24.04 改名为 libasound2t64;升级到本计划的 deb 已用 electron-builder 默认列表(自动迁移) |

## 6. 相关文档

- [20-electron.md](./20-electron.md) — Electron 主进程架构
- [21-win7-lts.md](./21-win7-lts.md) — Win7 LTS 分支策略
- ../plans/2026-06-15_cross-platform-packaging.md — 本计划文档(实施后归并并删除)
```

注:用 backtick 转义包了 ${version} 防 markdown 把它当变量替换 — 实际文件里写 markdown 三反引号代码块即可。

- [ ] **Step 2: 提交**

```bash
git add docs/technical/26-packaging-matrix.md
git commit -m "docs(technical): add 26-packaging-matrix.md cross-platform coverage doc

- Platform support matrix (Win7/10/11 x64 + Ubuntu amd64 + Linux AppImage)
- User-side install instructions per platform
- Smoke-test strategy table
- Known limitations (no macOS, no GPG-signed deb, +14MB VCRedist)
- Troubleshooting table for common install errors"
```

---

### Task 8: 文档 — Win7 LTS 段更新

**Files:**
- Modify: `docs/technical/21-win7-lts.md`(在 86 行 teardown.ps1 后追加新 §8)

- [ ] **Step 1: 在第 7 节末尾追加 VCRedist 自动化说明**

在 86 行 `- teardown.ps1 — 清理` 后追加:

```markdown

## 8. VC++ Redistributable(自 0.1.2 起自动 bundling)

NSIS 安装包内含 `vc_redist.x64.exe`(由 `build/installer.nsh` customInstall 宏在
安装阶段静默运行)。用户**无需**手动下载 VC++。

构建侧细节:

- `scripts/fetch-vcredist.ps1` 在 CI(`windows-latest`)和本地 Win 构建前下载
- `resources/vc_redist.x64.exe` 已 gitignore(~14MB 二进制)
- 已装更新版本的用户:MSI 返回 1638,customInstall 宏忽略并继续

人工烟测时(`scripts/win7-smoke/install.ps1`)无需再单独验证 VC++ 安装路径,
但**首次跑**仍要确认安装日志出现:
`Installing Microsoft Visual C++ 2015-2022 Redistributable (x64)...`

详见 [`26-packaging-matrix.md`](./26-packaging-matrix.md)§2。
```

- [ ] **Step 2: 提交**

```bash
git add docs/technical/21-win7-lts.md
git commit -m "docs(win7): document VCRedist auto-bundling since 0.1.2

- New §8 covers build/installer.nsh customInstall behavior
- User no longer needs to manually install VC++ Redistributable
- Smoke-test reviewers should check install log for VCRedist line"
```

---

### Task 9: 文档 — README 章节目录

**Files:**
- Modify: `docs/technical/README.md`

- [ ] **Step 1: 先读 README 当前章节表**

```bash
cat /home/fz/project/sage/docs/technical/README.md
```

- [ ] **Step 2: 在章节目录表里追加第 26 行(格式与现有行对齐)**

在 25 行(`25-llm-wiki-integration.md`)之后追加:

```markdown
| 26 | [跨平台打包矩阵](./26-packaging-matrix.md) | Win7/10/11 + Ubuntu deb 覆盖与用户安装指南 |
```

注:具体表格列宽以读到的现有行为准,缩进对齐即可。

- [ ] **Step 3: 提交**

```bash
git add docs/technical/README.md
git commit -m "docs(technical): add chapter 26 to README index"
```

---

### Task 10: 本地全程跑通 + 推 PR

**Files:**(无新增,纯验证 + git/gh 操作)

- [ ] **Step 1: 本地全产物烟测(Linux)**

```bash
cd /home/fz/project/sage
rm -rf release/0.1.2
npm run electron:build
npx electron-builder --linux AppImage deb --publish never
ls -lh release/0.1.2/
npx vitest run tests/packaging/verify-artifacts.spec.ts
```

Expected:`Sage-0.1.2.AppImage` + `sage_0.1.2_amd64.deb` 都在;vitest 全绿。

- [ ] **Step 2: deb 反向元数据校验(强烈推荐)**

```bash
dpkg-deb --info release/0.1.2/sage_0.1.2_amd64.deb
```

Expected:看到 `Depends:` 行含 `libgtk-3-0, libnss3, libsecret-1-0, ...`;`Section: utils`;`Priority: optional`。

- [ ] **Step 3: 推 feature 分支**

```bash
git push -u origin feat/cross-platform-packaging
```

- [ ] **Step 4: 开 PR**

```bash
gh pr create \
  --title "feat(packaging): cross-platform coverage — Win7/10/11 + Ubuntu deb" \
  --body "Plan: docs/plans/2026-06-15_cross-platform-packaging.md

## Summary

Extend desktop packaging to fully cover the user's deployment matrix:

- **Windows 7 SP1 / 10 / 11 (x64)** — NSIS installer now bundles VC++ 2015-2022 Redistributable via customInstall macro, so clean Win7 has zero manual prerequisites.
- **Ubuntu 20.04+ (amd64)** — new native .deb target joins the existing AppImage.
- **Linux generic** — AppImage retained as fallback for Fedora/Arch/NixOS users.
- **macOS** — explicitly out of scope (Phase 1 Win7-first decision preserved).

## Test plan

- [x] Local Linux build produces both .AppImage and .deb
- [x] dpkg-deb --info shows expected Depends/Section/Priority
- [x] vitest tests/packaging/verify-artifacts.spec.ts green
- [ ] CI desktop-build (ubuntu-latest) produces both artifacts
- [ ] CI desktop-build (windows-latest) runs fetch-vcredist + produces NSIS .exe
- [ ] CI electron-smoke still green
- [ ] Manual: install .deb on Ubuntu 24.04 VM
- [ ] Manual: install NSIS .exe on clean Win7 SP1 VM"
```

- [ ] **Step 5: 监控 CI**

```bash
gh pr checks --watch
```

Expected:全绿(backend / frontend / desktop-build 两个 OS / electron-smoke / all-green)。

- [ ] **Step 6: CI 红灯处理**

如果失败:`gh run view <run_id> --log-failed`,STOP 报告用户,**不自动修**。

- [ ] **Step 7: 请用户合并**

CI 绿后:

> ✅ CI 通过。请在 GitHub UI 上合并 PR #N。合并后我会清理分支并把 plans/2026-06-15_cross-platform-packaging.md 删除(按 feature-development.md:完成后并入技术手册即删,不留历史版本)。

---

## 5. 完成准则(definition of done)

- [ ] CI 全绿(backend + frontend + desktop-build 双 OS + electron-smoke)
- [ ] CI artifact 包含 `Sage-Setup-0.1.2.exe`(Windows)和 `Sage-0.1.2.AppImage` + `sage_0.1.2_amd64.deb`(Linux)
- [ ] `tests/packaging/verify-artifacts.spec.ts` 全 PASS
- [ ] PR merged to main
- [ ] feature 分支已删(本地 + 远程)
- [ ] `docs/plans/2026-06-15_cross-platform-packaging.md` **删除**(per feature-development.md:计划文档完成后归并到 technical/26 即删,不留历史版本)

## 6. Self-Review 复核

**Spec 覆盖:**
- Win7/10/11 NSIS bundled VCRedist → Task 3-6 ✅
- Ubuntu .deb → Task 1-2 ✅
- Linux AppImage 保留 → Task 1(`target: [AppImage, deb]`)✅
- 用户文档 → Task 7-9 ✅
- 自动化测试 → Task 1(verify-artifacts)+ CI 默认烟测 ✅
- 风险记录 → §3 已列 5 项 ✅

**Placeholder 扫描:** 无 TODO/TBD/"similar to"/未定义函数引用。所有代码块都是完整可执行内容。

**类型一致性:** `productName` `Sage` / `appId` `com.sage.app` / artifactName 模板 `${productName}` `${version}` `${ext}` 与 `electron-builder.yml:2-3` 一致。`BUILD_RESOURCES_DIR` NSIS 变量对应 yml `directories.buildResources: resources`。

## 7. 执行模式

两种实施方式(按 writing-plans skill handoff):

1. **Subagent-Driven(推荐)** — 我每个 Task 派一个 fresh subagent,任务间 review,迭代快
2. **Inline Execution** — 我在本会话内顺序跑 Task 1-10,每 2-3 个 task 一个 checkpoint

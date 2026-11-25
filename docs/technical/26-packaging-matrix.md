# 26. 跨平台打包矩阵

> 本章节描述 Sage 桌面端在各平台的分发产物与用户侧安装路径。
> 更新自 2026-06-15(feat/cross-platform-packaging)。

## 1. 平台覆盖矩阵

| 平台 | 最低版本 | 架构 | 产物 | Release 入口 | CI 构建 runner |
|---|---|---|---|---|---|
| Windows (main) | 10 1809+ | x64 | `Sage-Setup-${version}-win10.exe` (NSIS, 含 VCRedist) | main release | `release.yml` (main branch) |
| Windows 11 | 10 | x64 | 同上 | main release | 同上 |
| **Windows 7 SP1 (LTS)** | 7 SP1 | x64 | `Sage-Setup-${version}-win7.exe` (NSIS, 含 VCRedist) | LTS release (`v*-lts` tag) | `release-win7.yml` (`release/win7` branch) |
| **Windows 7 SP1 (LTS) core 变体** | 7 SP1 | x64 | `Sage-Setup-${version}-win7-core.exe` (NSIS, 不含内置模型) | 同上 LTS release | `release-win7.yml` (同 Source job) |
| Ubuntu | 20.04+ | amd64 | `sage_${version}_amd64.deb` (原生 deb) | main release | `release.yml` (main branch) |
| Linux 通用 | glibc 2.28+ | x64 | `Sage-${version}.AppImage` | main release | `release.yml` (main branch) |
| macOS | — | — | **暂不支持** (`mac.target: null`) | — | — |

**架构限制(本期不支持):** 32-bit Windows · ARM Windows · ARM Linux · 任何 macOS。

## 2. 用户侧安装

### Windows 10 / 11 (main release)

1. 从 main release 页面下载 `Sage-Setup-${version}-win10.exe`
2. 双击运行, 按向导安装 (默认 HKCU, 无需管理员权限)
3. 安装阶段会**静默装** VC++ 2015-2022 Redistributable (已装会跳过)
4. 不支持 Windows 7 (main release 不再含 Win7 兼容代码路径)

### Windows 7 SP1 (LTS release)

1. 从 LTS release 页面 (tag 形如 `v*-lts`) 下载 `Sage-Setup-${version}-win7.exe`
2. **前置**: 装 **KB3033929** (SHA-2 代码签名, 2016 年发布) — Win7 SP1 必装
3. 双击 `Sage-Setup-${version}-win7.exe` 运行安装
4. 安装阶段静默装 VC++ 2015-2022 Redistributable
5. 启动 Sage 前确认桌面快捷方式 (`Sage.lnk`) 存在
6. **x64 only** — Electron 21 不支持 Win7 32-bit

同一 LTS release 还提供 **core 变体** `Sage-Setup-${version}-win7-core.exe`：安装流程与上表相同，但不含内置 AI 模型。首次启动以 `HashEmbedder` 兜底（不阻断），需在设置页「组件管理」或 SageDoctor 导入 `embedding-bge-small-zh-*.sagepkg`（OCR 可选装 `ocr-models-ppocr-*.sagepkg`）后才会启用语义检索 / OCR。详见下文 [§8](#8-win7-core-最小安装包变体)。

LTS release 由 `release/win7` 分支的 `release-win7.yml` workflow 产出, 详见 [`31-win7-lts.md` §9](./31-win7-lts.md)。

### Ubuntu 20.04+ / Debian / Mint

```bash
sudo apt install ./sage_${version}_amd64.deb
# 或
sudo dpkg -i sage_${version}_amd64.deb && sudo apt-get install -f
```

安装后 `sage` 出现在应用菜单 → Office 类别。卸载:`sudo apt remove sage`。

### 其它 Linux(Fedora / Arch / openSUSE / NixOS)

```bash
chmod +x Sage-${version}.AppImage
./Sage-${version}.AppImage
```

可选:用 [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) 集成到桌面菜单。

## 3. 真机烟测策略

| 平台 | 自动化 | 频率 | 工具 |
|---|---|---|---|
| Win Server 2022 | ✅ CI `electron-smoke`(每次 PR) | Per-PR | Playwright `_electron` |
| Win10 / Win11 | ⚠️ 等价于 Server 2022(同 Chromium 内核),无独立真机 | — | — |
| Win7 SP1 | ❌ 人工([`31-win7-lts.md`](./31-win7-lts.md)§3) | 每 release | `scripts/win7-smoke/*.ps1` |
| Ubuntu | ❌ 暂无 | — | (TODO:可加 `electron-smoke` 的 Linux 镜像) |

## 4. 已知限制

- **macOS 缺席** — `electron-builder.yml` 的 `mac.target: null` 是 Phase 1 战略决策(Win7 优先)。Phase 3 可补 `dmg` + 签名。
- **deb 无 GPG 签名** — 用户首次 `apt install` 会警告 "未签名"。Phase 3 加 GPG key + APT repo。
- **VCRedist bundling 让安装包 +~14MB** — 文档已明示;可接受(节省 Win7 用户找 VC++ 的麻烦)。
- **AppImage 不进 apt 列表** — 这是 AppImage 设计本身的特性,不是 bug。

## 5. 故障排查

| 现象 | 平台 | 原因 / 处理 |
|---|---|---|
| `sage.exe` 双击无响应 | Win7 SP1 | KB3033929 未装(若用了签名版) → 装补丁;或 VCRedist 未装成功 → 手动跑 `vc_redist.x64.exe /install` |
| `error while loading shared libraries: libnss3.so` | Linux | `sudo apt install libnss3`(deb 应自动解,AppImage 需手动) |
| Ubuntu 24.04 apt install 报 `libasound2` not found | Ubuntu | 24.04 改名为 `libasound2t64`;升级到本计划的 deb 已用 electron-builder 默认列表(自动迁移) |

## 6. 相关文档

- [`20-electron.md`](./20-electron.md) — Electron 主进程架构
- [`31-win7-lts.md`](./31-win7-lts.md) — Win7 LTS 分支策略
- [`30-release-tiers.md`](./30-release-tiers.md) — 4 档发布分级系统
- `../plans/2026-06-15_cross-platform-packaging.md` — 本计划文档(实施后归并并删除)

## 7. 预发布构建矩阵

> 自 v0.5.0 起，Sage 引入 4 档发布分级（alpha / beta / RC / stable）+ SemVer 预发布段。`ARTIFACT_SUFFIX` 与 cache key 必须按 tag 命名空间隔离，避免 stable 构建被预发布版本污染。完整分级系统说明见 [`30-release-tiers.md`](./30-release-tiers.md)。

### 7.1 Artifact 后缀映射

**自 v0.5.0 起，artifact 后缀在 `electron-builder.yml` 字面量硬编码，不再使用 env 占位符或脚本推断。** main 分支默认无后缀，win7 LTS 分支硬编码 `-win7` 后缀。

| Tag | 分支 | Artifact 后缀 | 产物名 |
|-----|------|--------------|--------|
| `v0.5.0-alpha.1` | main | (无) | `Sage-Setup-0.5.0-alpha.1.exe` |
| `v0.5.0-beta.1` | main | (无) | `Sage-Setup-0.5.0-beta.1.exe` |
| `v0.5.0-rc.1` | main | (无) | `Sage-Setup-0.5.0-rc.1.exe` |
| `v0.5.0` | main | (无) | `Sage-Setup-0.5.0.exe` |
| `v0.5.0-alpha.1-win7` | release/win7 | `-win7` | `Sage-Setup-0.5.0-alpha.1-win7.exe` |
| `v0.5.0-alpha.1-win7` | release/win7 | `-win7` (core) | `Sage-Setup-0.5.0-alpha.1-win7-core.exe`（不含内置模型） |
| `v0.5.0-beta.1-win7` | release/win7 | `-win7` | `Sage-Setup-0.5.0-beta.1-win7.exe` |
| `v0.5.0-rc.1-win7` | release/win7 | `-win7` | `Sage-Setup-0.5.0-rc.1-win7.exe` |
| `v0.5.0-win7` | release/win7 | `-win7` | `Sage-Setup-0.5.0-win7.exe` |

> **设计意图**：
> - **main** 是主要开发分支，默认平台（Win10+/Linux），artifact 不带平台后缀
> - **release/win7** 是附属特化分支（仅 Win7 SP1），artifact 强制 `-win7` 后缀标识平台
> - tier（alpha/beta/rc）后缀从 SemVer pre-release 段保留在 version 里，不需要额外 suffix
> - 老 `-lts` 后缀 + `scripts/release/determine_artifact_suffix.sh` 已在 v0.4.3-alpha.1-win7 配套 PR 中废弃

### 7.2 Cache key 命名空间隔离

预发布与 stable 必须使用不同 cache key，否则预发布版本的 node_modules / 打包产物可能污染 stable build：

```yaml
# release.yml — 旧：stable 与预发布共享 cache（已废弃）
key: ${{ runner.os }}-electron-${{ hashFiles('package-lock.json') }}

# release.yml — 新：预发布 tag 加 -prerelease 命名空间
key: ${{ runner.os }}-electron-${{ contains(github.ref_name, '-') && 'prerelease-' || '' }}${{ hashFiles('package-lock.json') }}
```

**效果**：

- `v0.5.0` → `windows-electron-a1b2c3d4` (stable)
- `v0.5.0-beta.1` → `windows-electron-prerelease-a1b2c3d4` (隔离)

LTS workflow (`release-win7.yml`) 同步加 `-prerelease` 隔离，cache key prefix 为 `*-electron-lts-*`。

### 7.3 `prerelease` 字段自动判断

`release.yml` 与 `release-win7.yml` 在上传产物时按 tag 决定是否标记为 prerelease：

```yaml
prerelease: ${{ contains(github.ref_name, '-alpha') || contains(github.ref_name, '-beta') || contains(github.ref_name, '-rc') }}
```

这确保 GitHub Releases 页面默认显示 stable 为 "Latest"，预发布版本归入 "Pre-release" 筛选器，避免用户误装。

### 7.4 Tauri 矩阵隔离

Tauri 矩阵**不参与**预发布段：alpha / beta / RC 阶段不发 Tauri 构建。仅当 main 进入 stable 时才同步触发 Tauri stable 构建（`release.yml` 加 `tauri-build` 步骤，条件为 tag 不含 `-alpha` / `-beta` / `-rc` / `-lts`）。Tauri 矩阵的常规 CI 维持现状（`ci.yml` 跑常规检查）。

## 8. Win7 core 最小安装包变体

面向「内网终端已部署模型」「仅用远端 LLM、无需本地 embedding/OCR」等轻量分发场景，`release/win7` 在每次 `-win7` tag 发布时，除全量 Source 包与实验性 Cython 包外，再产出一个不含内置 AI 模型的 **core** 安装包。

### 8.1 与全量包的区别

| 维度 | 全量 Source 包 | core 变体 |
|---|---|---|
| 产物 | `Sage-Setup-${version}-win7.exe` | `Sage-Setup-${version}-win7-core.exe` |
| 内置模型 | 含 `resources/models`（PP-OCRv6 OCR + bge-small-zh-v1.5 Embedding） | 不含 |
| 开箱能力 | 语义检索 / OCR 直接可用 | 首启降级 `HashEmbedder`、OCR 引擎不可用；导入 `.sagepkg` 后启用 |
| 体积 | 模型净体积 + Electron 21 + Python 3.8 运行时 | 仅少模型；运行时仍是主体，非量级缩减 |

### 8.2 依赖裁剪范围

core 仅移走内置模型目录 `resources/models`，其余 `extraResources` 与全量包完全一致：内嵌 Python 运行时（`python`）、后端代码（`backend` / `sage-core`）、网页回退前端 `dist-web`、MSYS2 bash（`tools`）、`win7-fix`、浏览器扩展，以及 `build-manifest.json` / `component-public-key.pem` / `CHANGELOG.md`。裁剪只触发「模型缺位」降级，不影响程序其他功能。

### 8.3 构建入口与产物命名

- **入口**：`.github/workflows/release-win7.yml` 的 `build-windows`（Source）job，在全量包上传之后追加三个步骤：
  1. 将 `resources/models` 临时移到 `RUNNER_TEMP`，并重建空目录，使 `electron-builder.yml` 的 `extraResources: from: resources/models` 指向空目录；
  2. 以覆盖 `artifactName` 的方式再打一次 NSIS：`npx electron-builder --win nsis --publish never --config.win.artifactName='${productName}-Setup-${version}-core.${ext}'`；
  3. `if: always()` 恢复 `resources/models`，避免污染后续步骤与缓存。
- **artifact 隔离**：Source 包上传 glob 显式排除 `*-core.exe`；core 包单独作为 `sage-setup-core` artifact（`release/*/Sage-Setup-*-core.exe`）上传。`upload-release` 下载 `artifacts/core` 并校验非空，与 Source / Cython / `.sagepkg` 发布到同一 LTS release，发布说明 Downloads 表列出三个 exe 版本（Source / core / Cython）。
- **命名**：`${version}` 由 git tag 同步进 `package.json`（含 `-win7` 段），故实际文件名为 `Sage-Setup-<tag 版本>-core.exe`，例如 `Sage-Setup-0.4.9-alpha.85-win7-core.exe`；后缀映射见 [§7.1](#71-artifact-后缀映射)。

### 8.4 与常规 win7 包的关系

- core 是 win7 LTS 的**第三个分发变体**（Source 推荐 / core 轻量 / Cython 实验），与全量包共用同一 Source job、同一份 `electron-builder.yml` 与同一签名流程，不是独立 job 或独立配置，避免配置漂移。
- **仅 release/win7**：main 分支不产出 core；Cython 模式也不产出 core（Cython 仍为实验性代码保护构建，core 只配合 Source）。
- 运行时模型查找为 `userData/models`（`.sagepkg` 导入位置）> 安装包内置 `SAGE_BUNDLED_MODELS_DIR`；`.sagepkg` 安装到 `userData` 后优先于内置，因此 core 与全量包可无缝互转。模型缺位不阻断启动：Embedding 降级 `HashEmbedder`，OCR 引擎不可用。
- core 依赖 `.sagepkg` 补装模型；若 CI 未配置 `SAGE_COMPONENT_SIGNING_KEY`，组件包构建当前仅打 warning 并跳过，此时 core 包无法完成模型补装。

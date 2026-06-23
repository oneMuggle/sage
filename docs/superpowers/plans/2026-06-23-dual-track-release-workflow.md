# 双轨 Release Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `release.yml` 拆为两条独立 workflow —— main 出 Win10+/Linux/macOS installer（产物带 `-win10` 后缀），`release/win7` LTS 分支出 Win7 专用 installer（产物带 `-win7` 后缀）。

**Architecture:** 用 `v*-lts` tag 后缀路由到 LTS workflow（用 `if: contains/ref_name, '-lts'` 守卫），electron-builder 的 `win.artifactName` 用 `${env.ARTIFACT_SUFFIX}` 占位，CI 通过环境变量在两条 workflow 间切产物后缀。零代码改动，只动 yml + docs + electron-builder 配置。

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-node@v4`, `actions/cache@v4`, `softprops/action-gh-release@v2`), electron-builder 24.13.3, Electron 21.4.4 锁定。

**Design Spec:** `docs/superpowers/specs/2026-06-23-win7-lts-release-workflow-design.md`

---

## Global Constraints

> 这些约束来自 spec，对所有任务隐式生效。

- **Electron 版本**: 锁定 21.4.4（不改 main 也不改 LTS；后续 Phase 7+ 再升）
- **LTS 触发条件**: tag 形如 `v*-lts`（如 `v0.2.0-lts`）；其他 `v*` tag 走 main workflow
- **main workflow `if` 守卫**: `if: "!contains(github.ref_name, '-lts')"`
- **LTS workflow `if` 守卫**: `if: "contains(github.ref_name, '-lts')"`
- **env.ARTIFACT_SUFFIX 必填**: workflow 必须显式设；空值会产出 `Sage-Setup-0.2.0-.exe`（破产物）
- **产物命名**: main Windows `Sage-Setup-${version}-win10.exe`；LTS Windows `Sage-Setup-${version}-win7.exe`；Linux/macOS 命名不变
- **LTS workflow 范围**: 只 build Windows NSIS；不构建 Linux / macOS（macOS `mac.target: null`）
- **LTS EOL**: 2027-12-13；届时删 `release/win7` 分支 + `release-win7.yml`
- **功能分支**: 所有改动在 `feat/dual-track-release-workflow` 分支（已建），不开 main 直接改
- **commit 格式**: conventional commits（`feat:` / `docs:` / `chore:` / `fix:`）

---

## File Structure

| 文件 | 改动类型 | 作用 |
|---|---|---|
| `electron-builder.yml` | Modify | win.artifactName 改为 `${env.ARTIFACT_SUFFIX}` |
| `.github/workflows/release.yml` | Modify | 加 if-guard + env 变量 + Windows 产物改 -win10 + upload glob |
| `.github/workflows/release-win7.yml` | Create | 全新 LTS workflow |
| `docs/technical/21-win7-lts.md` | Modify | 新增 §9 Release 工作流 |
| `docs/technical/26-packaging-matrix.md` | Modify | §1 拆 Win7/Win10 行；§2 拆 Win7/Win10 子节 |
| `docs/technical/20-electron.md` | Modify | §5 加一行 LTS 提示 |
| `README.md` | Modify | §"双轨发布" 表格补具体链接；Q4 重写 |
| `docs/user-manual/01-desktop.md` | Modify | §1.1/§1.2 拆 Win7/Win10 |
| `CHANGELOG.md` | Modify | [Unreleased] 加条目 |

---

## Task 1: CI 基础设施改动（yml）

**Files:**
- Modify: `electron-builder.yml` (1 处)
- Modify: `.github/workflows/release.yml` (3 处：头部注释 / build job 守卫 + env / Windows step env + upload glob)
- Create: `.github/workflows/release-win7.yml` (新文件 ~75 行)

**Interfaces:**
- Consumes: 现有 `release.yml` 的 windows job build 步骤（VCRedist fetcher + electron-builder 命令）
- Produces: 
  - `env.ARTIFACT_SUFFIX` 环境变量在两个 workflow 中被设置
  - main release 产物: `release/${version}/Sage-Setup-${version}-win10.exe`
  - LTS release 产物: `release/${version}/Sage-Setup-${version}-win7.exe`

### Step 1.1: 修改 `electron-builder.yml` 的 win.artifactName

打开 `electron-builder.yml`，找到第 38 行的：

```yaml
  artifactName: ${productName}-Setup-${version}.${ext}
```

替换为：

```yaml
  artifactName: ${productName}-Setup-${version}-${env.ARTIFACT_SUFFIX}.${ext}
```

**不要动** 第 75 行（`linux.artifactName: ${productName}-${version}.${ext}`）和第 90 行（`deb.artifactName: sage_${version}_amd64.${ext}`）。

### Step 1.2: 验证 yml 语法

```bash
cd /home/fz/project/sage && python3 -c "import yaml; yaml.safe_load(open('electron-builder.yml'))" && echo "OK"
```

Expected: `OK`（无错误输出表示 yml 语法正确）。

### Step 1.3: 修改 `release.yml` 头部注释

打开 `.github/workflows/release.yml`，**完整替换**第 1-24 行的注释块：

```yaml
# Release Workflow — 自动化构建 + 上传 Electron 应用到 GitHub Release
#
# 触发条件: push tag 形如 v* (如 v0.2.0, v1.0.0-beta.1)
#
# ⚠️ Win7 LTS 专用 installer 改由 release-win7.yml 在 release/win7 分支产出
#    tag 格式: v*-lts (如 v0.2.0-lts)
#    下载入口: https://github.com/onemuggle/sage/releases?q=tag%3Av0.2.0-lts
#
# 工作流:
#   1. checkout 代码
#   2. setup Node.js + cache npm + electron-builder downloads
#   3. 安装 Linux 构建依赖
#   4. 构建前端 + Electron (npm run electron:build)
#   5. electron-builder 跨平台构建 (linux AppImage/deb + windows NSIS)
#   6. 上传产物到 GitHub Release (由本次 push tag 自动创建)
#
# 产物格式 (来自 electron-builder.yml, env.ARTIFACT_SUFFIX 由 workflow 设置):
#   - Sage-${version}.AppImage              (Linux)
#   - sage_${version}_amd64.deb             (Linux Debian)
#   - Sage-Setup-${version}-win10.exe       (Windows NSIS, Win10+ only)
#
# Win7 用户请改用 release-win7.yml 的 LTS release。
#
# 失败处理: tag push 后 workflow 失败, 需人工:
#   1. git tag -d v<X.Y.Z> && git push origin :v<X.Y.Z>  # 删除坏 tag
#   2. 修 workflow, 重新打 tag
```

**注意**：链接里的 `onemuggle/sage` 替换为实际 repo `<owner>/<repo>`（如 `your-org/sage`）。若不知道当前 repo，跑 `git -C /home/fz/project/sage remote get-url origin` 查 `git@github.com:OWNER/REPO.git`。

### Step 1.4: 修改 `release.yml` build job 加 if-guard 和默认 env

打开 `.github/workflows/release.yml`，找到第 36-44 行的：

```yaml
jobs:
  build:
    name: Build (${{ matrix.os }})
    strategy:
      fail-fast: false
      matrix:
        # macOS DMG 暂未启用 (electron-builder.yml mac.target: null)
        # 待 Win7 验证后补回
        os: [ubuntu-latest, windows-latest]

    runs-on: ${{ matrix.os }}
```

替换为：

```yaml
jobs:
  build:
    name: Build (${{ matrix.os }})
    # Skip LTS-suffixed tags — those go to release-win7.yml
    if: "!contains(github.ref_name, '-lts')"
    strategy:
      fail-fast: false
      matrix:
        # macOS DMG 暂未启用 (electron-builder.yml mac.target: null)
        # 待 Win7 验证后补回
        os: [ubuntu-latest, windows-latest]

    runs-on: ${{ matrix.os }}

    # Default suffix — empty placeholder.
    # ⚠️ MUST be overridden by any step that uses ${env.ARTIFACT_SUFFIX}
    # in electron-builder.yml artifactName. Windows job overrides below.
    env:
      ARTIFACT_SUFFIX: ''
```

### Step 1.5: 修改 `release.yml` Windows build step 加 env 覆盖

打开 `.github/workflows/release.yml`，找到第 98-100 行：

```yaml
      - name: Build Windows (NSIS installer)
        if: matrix.os == 'windows-latest'
        run: npx electron-builder --win nsis --publish never
```

替换为：

```yaml
      - name: Build Windows (NSIS installer)
        if: matrix.os == 'windows-latest'
        env:
          # Override default; produces Sage-Setup-${version}-win10.exe
          ARTIFACT_SUFFIX: win10
        run: npx electron-builder --win nsis --publish never
```

### Step 1.6: 修改 `release.yml` upload glob 加 -win10

打开 `.github/workflows/release.yml`，找到第 102-118 行的 upload step：

```yaml
      - name: Upload artifacts to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          # tag_name 默认 = github.ref (即本次 push 的 tag),无需显式指定
          files: |
            release/*/Sage-*.AppImage
            release/*/sage_*_amd64.deb
            release/*/Sage-Setup-*.exe
          # draft: true (本次发布先 draft, 人工审核后再 publish)
          # 与 v0.1.2 流程一致: gh release create v0.1.2 --draft
          draft: true
          # 包含完整 commit history 和 changelog
          generate_release_notes: true
          # 失败时仍上传部分产物 (其他平台可能成功)
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

替换为：

```yaml
      - name: Upload artifacts to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          # tag_name 默认 = github.ref (即本次 push 的 tag),无需显式指定
          files: |
            release/*/Sage-*.AppImage
            release/*/sage_*_amd64.deb
            release/*/Sage-Setup-*-win10.exe
          # draft: true (本次发布先 draft, 人工审核后再 publish)
          # 与 v0.1.2 流程一致: gh release create v0.1.2 --draft
          draft: true
          # 包含完整 commit history 和 changelog
          generate_release_notes: true
          # 失败时仍上传部分产物 (其他平台可能成功)
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Step 1.7: 验证 `release.yml` 语法

```bash
cd /home/fz/project/sage && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo "OK"
```

Expected: `OK`。

### Step 1.8: 创建 `.github/workflows/release-win7.yml`

新建文件 `.github/workflows/release-win7.yml`，写入：

```yaml
# Release LTS Workflow — Windows 7 LTS 维护分支专用
#
# 触发: push tag v*-lts (如 v0.2.0-lts) 到 release/win7 分支
# 目标: Windows 7 SP1 x64 only (Electron 21.4.4 冻结)
#
# 与 release.yml 差异:
#   - 触发条件:  tag 含 '-lts' 后缀
#   - 产物:      仅 Windows NSIS, artifactName 用 -win7 后缀
#   - 不构建:    Linux / macOS (Win7 LTS 不覆盖)
#   - EOL:       2027-12-13 归档, 届时删除本 workflow + release/win7 分支
#
# 详见 docs/technical/21-win7-lts.md §2 LTS 策略 + §9 Release 工作流

name: Release (Win7 LTS)

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write  # 必需: gh release upload 需要 write 权限

jobs:
  build-windows:
    name: Build Windows (Win7 LTS)
    # Only act on LTS-suffixed tags; non-LTS tags skip this job entirely
    if: "contains(github.ref_name, '-lts')"

    runs-on: windows-latest

    env:
      # Force -win7 suffix via electron-builder.yml artifactName placeholder
      ARTIFACT_SUFFIX: win7

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'

      - name: Cache electron-builder downloads (LTS namespace)
        uses: actions/cache@v4
        with:
          path: |
            ~/.cache/electron
            ~/.cache/electron-builder
          # -lts suffix prevents cache collision with main release
          key: ${{ runner.os }}-electron-lts-${{ hashFiles('package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-electron-lts-

      - name: Install npm dependencies
        run: npm ci --force

      - name: Build frontend + Electron
        run: npm run electron:build

      - name: Fetch VC++ Redistributable (Windows)
        shell: pwsh
        run: pwsh scripts/fetch-vcredist.ps1

      - name: Build Windows NSIS (Win7 LTS, env.ARTIFACT_SUFFIX=win7)
        run: npx electron-builder --win nsis --publish never

      - name: Upload to LTS GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          # Use the original tag (e.g. v0.2.0-lts) as the release identifier,
          # so it becomes a separate release page from main's v0.2.0
          tag_name: ${{ github.ref_name }}
          files: |
            release/*/Sage-Setup-*-win7.exe
          body: |
            ## Sage ${{ github.ref_name }} (Win7 LTS) — Windows 7 SP1 x64 ONLY

            > ⚠️ **此版本专为 Windows 7 SP1 x64 设计**。
            > Win10+ 用户请改用 [main release](https://github.com/${{ github.repository }}/releases)。

            ### Downloads

            | File | Notes |
            | --- | --- |
            | `Sage-Setup-*.win7.exe` | NSIS, x64, VCRedist bundled |

            ### Win7 前置

            - **KB3033929** (SHA-2 代码签名支持, 2016 年发布) — Win7 SP1 必装, 否则 Sage.exe 启动被拒
            - x64 only (Electron 21 不支持 Win7 32-bit)

            ### 风险声明

            ⚠️ 本分支基于 EOL 技术栈 (Electron 21.4.4 + Python 3.8 + Chromium 106)。
            详见 [`docs/technical/21-win7-lts.md`](https://github.com/${{ github.repository }}/blob/release/win7/docs/technical/21-win7-lts.md) §6。
          # draft: true — 人工 review release notes 后再 publish
          draft: true
          generate_release_notes: true
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Step 1.9: 验证新文件语法

```bash
cd /home/fz/project/sage && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release-win7.yml'))" && echo "OK"
```

Expected: `OK`。

### Step 1.10: 提交 CI 改动

```bash
cd /home/fz/project/sage && git add electron-builder.yml .github/workflows/release.yml .github/workflows/release-win7.yml && git commit -m "feat(ci): 双轨 release workflow (main → Win10+, LTS → Win7)

- release.yml: 加 if-guard 排除 -lts tag; Windows job 设 ARTIFACT_SUFFIX=win10
- 新增 release-win7.yml: 监听 -lts tag, 出 Sage-Setup-*-win7.exe
- electron-builder.yml: win.artifactName 用 \${env.ARTIFACT_SUFFIX} 占位
- cache key 加 -lts namespace 避免和 main 冲突" 2>&1 | tail -5
```

Expected: commit 成功, hash 返回。

### Step 1.11: Task 1 完成检查

```bash
cd /home/fz/project/sage && git log --oneline -2 && echo "---" && git status --short
```

Expected: 
- 最新 commit 是 feat(ci): 双轨 release workflow
- 没有 uncommitted 改动（除 package-lock.json 等与本任务无关的）

---

## Task 2: 技术文档更新

**Files:**
- Modify: `docs/technical/21-win7-lts.md` (新增 §9)
- Modify: `docs/technical/26-packaging-matrix.md` (§1 表 + §2 子节)
- Modify: `docs/technical/20-electron.md` (§5 加一行)

**Interfaces:**
- Consumes: spec §3.4 文档改动清单 + spec §3.5 §9 模板
- Produces: 三份技术文档反映双 release workflow

### Step 2.1: 在 `21-win7-lts.md` 末尾追加 §9

打开 `docs/technical/21-win7-lts.md`，**在文件末尾**追加新章节：

```markdown

## 9. Release 工作流

`release/win7` 分支的 release 由 **`.github/workflows/release-win7.yml`** 触发，独立于 main。

| 项              | 值                                                                                |
| --------------- | --------------------------------------------------------------------------------- |
| 触发 tag        | `v*-lts`（如 `v0.2.0-lts`）                                                       |
| Runner          | `windows-latest` (cross-build, 同 main)                                           |
| 产物            | `Sage-Setup-${version}-win7.exe` (NSIS, x64)                                      |
| Release 入口    | https://github.com/\<owner>/sage/releases?q=tag%3Av*-lts                          |
| Release 状态    | draft（人工 review 后 publish）                                                   |
| 与 main 共用    | electron-builder.yml / build/installer.nsh / scripts/fetch-vcredist.ps1           |
| EOL 动作        | 2027-12-13 后 `git push origin --delete release/win7` + 删 `release-win7.yml`      |

### 9.1 触发步骤

1. 切到 `release/win7` 分支: `git switch release/win7`
2. 拉 main 的最新 commit: `git fetch origin main && git rebase origin/main`（如有冲突手动解决）
3. 决定版本号: 通常 cherry-pick N 个 commit 后 bump patch 号（如 `0.2.0` → `0.2.0-lts` 或 `0.2.1-lts`）
4. 打 tag: `git tag -a v0.2.1-lts -m "v0.2.1-lts — Win7 patch: ..."`
5. push tag: `git push origin v0.2.1-lts`
6. 监控 Actions: `gh run watch`
7. CI 通过后到 GitHub Releases 找到 draft，**人工 review release notes** 后 publish

### 9.2 失败处理

| 失败位置                          | 处理                                                                       |
| --------------------------------- | -------------------------------------------------------------------------- |
| Win7 烟测未通过                   | 不 publish；hotfix 修；重新打 tag (`v0.2.2-lts`)                          |
| NSIS 产物里没有 win7 后缀         | 检查 release-win7.yml 的 `env.ARTIFACT_SUFFIX` 是否正确设为 `win7`         |
| Release 误发到 main channel       | 删 release + 删 tag：`gh release delete v0.2.0-lts && git push origin :v0.2.0-lts` |

### 9.3 与 main release 的对比

| 维度         | main release                | LTS release                 |
| ------------ | --------------------------- | --------------------------- |
| 触发 branch  | `main`                      | `release/win7`              |
| 触发 tag     | `v*` (排除 `*-lts`)         | `v*-lts`                    |
| Workflow     | `release.yml`               | `release-win7.yml`          |
| 平台         | Linux / Windows NSIS / macOS (Phase 3+) | Windows NSIS only          |
| 产物后缀     | `-win10` (Windows)          | `-win7` (Windows)           |
| 频率         | 每次 main 发版              | 仅 Win7 特定 patch 时       |
| EOL          | 持续                        | 2027-12-13                  |
```

**注意**：把 `<owner>/sage` 替换为实际 repo owner。运行 `git -C /home/fz/project/sage remote get-url origin` 查。

### Step 2.2: 修改 `26-packaging-matrix.md` §1 表格

打开 `docs/technical/26-packaging-matrix.md`，**替换**第 8-15 行：

```markdown
| 平台 | 最低版本 | 架构 | 产物 | CI 构建 runner |
|---|---|---|---|---|
| Windows (main) | 10 1809+ | x64 | `Sage-Setup-${version}-win10.exe` (NSIS, 含 VCRedist) | `release.yml` (main) |
| Windows 11 | 10 | x64 | 同上 | 同上 |
| **Windows 7 SP1 (LTS)** | 7 SP1 | x64 | `Sage-Setup-${version}-win7.exe` (NSIS, 含 VCRedist) | `release-win7.yml` (`release/win7` branch) |
| Ubuntu | 20.04+ | amd64 | `sage_${version}_amd64.deb` (原生 deb) | `release.yml` (main) |
| Linux 通用 | glibc 2.28+ | x64 | `Sage-${version}.AppImage` | `release.yml` (main) |
| macOS | — | — | **暂不支持** (`mac.target: null`) | — |
```

为：

```markdown
| 平台 | 最低版本 | 架构 | 产物 | Release 入口 | CI 构建 runner |
|---|---|---|---|---|---|
| Windows (main) | 10 1809+ | x64 | `Sage-Setup-${version}-win10.exe` (NSIS, 含 VCRedist) | main release | `release.yml` (main branch) |
| Windows 11 | 10 | x64 | 同上 | main release | 同上 |
| **Windows 7 SP1 (LTS)** | 7 SP1 | x64 | `Sage-Setup-${version}-win7.exe` (NSIS, 含 VCRedist) | LTS release (`v*-lts` tag) | `release-win7.yml` (`release/win7` branch) |
| Ubuntu | 20.04+ | amd64 | `sage_${version}_amd64.deb` (原生 deb) | main release | `release.yml` (main branch) |
| Linux 通用 | glibc 2.28+ | x64 | `Sage-${version}.AppImage` | main release | `release.yml` (main branch) |
| macOS | — | — | **暂不支持** (`mac.target: null`) | — | — |
```

### Step 2.3: 修改 `26-packaging-matrix.md` §2 Win 安装说明

在 `docs/technical/26-packaging-matrix.md` 第 22-26 行的 `### Windows 7 SP1 / 10 / 11` 子节，**替换**为两个独立子节：

找到：

```markdown
### Windows 7 SP1 / 10 / 11

1. 下载 `Sage-Setup-${version}.exe`
2. 双击运行, 按向导安装 (默认 HKCU, 无需管理员权限)
3. 安装阶段会**静默装** VC++ 2015-2022 Redistributable (已装会跳过)
4. Win7 SP1 用户需提前装 **KB3033929** (SHA-2 代码签名, Phase 3 启用签名后强依赖)
```

替换为：

```markdown
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

LTS release 由 `release/win7` 分支的 `release-win7.yml` workflow 产出, 详见 [`21-win7-lts.md` §9](./21-win7-lts.md)。
```

### Step 2.4: 修改 `20-electron.md` §5 加一行 LTS 提示

打开 `docs/technical/20-electron.md`，找到第 87-97 行的 `## 5. CI 流水线` 表格。在表格**之后**追加一段：

```markdown

> **2026-06-23 更新**: Win7 LTS release 拆出独立 workflow `release-win7.yml` (在 `release/win7` 分支), 不再走本表中的 main release。详见 [`21-win7-lts.md` §9](./21-win7-lts.md)。
```

### Step 2.5: 验证三份技术文档可读

```bash
cd /home/fz/project/sage && wc -l docs/technical/21-win7-lts.md docs/technical/26-packaging-matrix.md docs/technical/20-electron.md
```

Expected: 三份文件行数 ≥ 修改前行数（21-win7-lts.md 应增加约 30 行）。

### Step 2.6: 提交技术文档改动

```bash
cd /home/fz/project/sage && git add docs/technical/21-win7-lts.md docs/technical/26-packaging-matrix.md docs/technical/20-electron.md && git commit -m "docs(technical): 双轨 release workflow 文档化

- 21-win7-lts.md: 加 §9 Release 工作流 (tag 格式 + 触发步骤 + 失败处理)
- 26-packaging-matrix.md: §1 拆 main/LTS 行; §2 拆 Win10/11 和 Win7 LTS 子节
- 20-electron.md: §5 加 LTS workflow 拆出提示" 2>&1 | tail -5
```

Expected: commit 成功。

---

## Task 3: 用户面向文档 + CHANGELOG 更新

**Files:**
- Modify: `README.md` (§"双轨发布" 表格 + Q4)
- Modify: `docs/user-manual/01-desktop.md` (§1.1 + §1.2)
- Modify: `CHANGELOG.md` ([Unreleased] 段)

**Interfaces:**
- Consumes: spec §3.4 文档改动清单
- Produces: 用户能直接看到 Win7 vs Win10+ 的下载引导

### Step 3.1: 修改 `README.md` §"双轨发布" 表格

打开 `README.md`，找到第 30-44 行的 §"双轨发布" 整段：

```markdown
## 🪟 双轨发布

Sage 维护**两条独立分支**，分别针对不同平台：

| 分支               | 目标平台                                  | Electron       | Python              | Chromium                  | 状态                   |
| ------------------ | ----------------------------------------- | -------------- | ------------------- | ------------------------- | ---------------------- |
| **`main`**         | Win10+ / macOS / Linux                    | 21.4.4         | 3.11+               | 106                       | ✅ 主线持续迭代        |
| **`release/win7`** | **Windows 7 SP1 x64**（**完全离线**部署） | 21.4.4（冻结） | 3.8（最后兼容版本） | 106（官方 fallback 机制） | ⚠️ 长期维护，仅 hotfix |

**如何选择？**

- 普通用户：使用 `main` 分支，享受最新功能。
- **Win7 用户**（内网/无网/老硬件）：使用 `release/win7` 分支。下载方式见各分支的 [GitHub Releases](https://github.com/your-repo/sage/releases) 页面。

**为什么需要两条分支？**
Electron 21.4.4 内嵌 Chromium 106，对 Windows 7 仍有官方支持（Electron ≥22 起官方停止 Win7 支持）。Electron 21.4.4 是最后支持 Win7 的稳定版本，因此 Win7 用户需要独立的维护分支。

详细同步策略和风险说明见 [`release/win7` 分支的 BRANCH_NOTES.md](https://github.com/your-repo/sage/blob/release/win7/BRANCH_NOTES.md)。
```

替换为：

```markdown
## 🪟 双轨发布

Sage 维护**两条独立的 GitHub Release 通道**，分别针对不同平台：

| 通道        | 触发分支       | 目标平台                                  | 产物                                                          | Electron       | Python  | 状态                   |
| ----------- | -------------- | ----------------------------------------- | ------------------------------------------------------------- | -------------- | ------- | ---------------------- |
| **main release**   | `main`         | Win10+ / Linux / macOS (Phase 3+)         | `Sage-Setup-${version}-win10.exe` / `sage_${version}_amd64.deb` / `Sage-${version}.AppImage` | 21.4.4         | 3.11+   | ✅ 主线持续迭代        |
| **LTS release**    | `release/win7` | **Windows 7 SP1 x64**（完全离线部署）     | `Sage-Setup-${version}-win7.exe`                               | 21.4.4 (冻结)  | 3.8     | ⚠️ 长期维护, 仅 hotfix, 2027-12-13 EOL |

**下载入口**:

- **普通用户 (Win10+/Linux/macOS)**:  https://github.com/\<owner>/sage/releases/latest
- **Win7 SP1 x64 用户**: https://github.com/\<owner>/sage/releases?q=tag%3Av*-lts (tag 形如 `v0.2.0-lts`)

**为什么需要两条通道？**

- main release 已经移除了 Win7 特定兼容代码路径（Chromium 启动开关等），产物不再支持 Win7
- LTS release 锁在 Electron 21.4.4 + Python 3.8，单独维护 Win7 SP1 x64
- 两条通道独立迭代：main 后续可升 Electron 28+/32+，LTS 维持冻结

详细同步策略和风险说明见 [`release/win7` 分支的 BRANCH_NOTES.md](https://github.com/\<owner>/sage/blob/release/win7/BRANCH_NOTES.md) 和 [`docs/technical/21-win7-lts.md`](./docs/technical/21-win7-lts.md)。
```

**注意**：把 `<owner>/sage` 替换为实际 owner。运行 `git -C /home/fz/project/sage remote get-url origin` 查。

### Step 3.2: 修改 `README.md` Q4 Win7 回答

打开 `README.md`，找到第 323-328 行的 Q4:

```markdown
### Q4: Windows 7 下无法运行

**A**: 当前 `main` 分支（Electron 21.4.4）支持 Win7。Win10+ 用户使用 `main`；纯 Win7 用户请使用 `release/win7` 分支。如遇到具体问题，确保已安装以下依赖：

- Visual C++ Redistributable (Electron 21 仍需要)
```

替换为：

```markdown
### Q4: Windows 7 下无法运行 / 哪里下载 Win7 版

**A**:

- **main release (`Sage-Setup-${version}-win10.exe`) 已不再支持 Win7**（自 2026-06-23 起）
- **Win7 SP1 x64 用户**请从 LTS release 下载 `Sage-Setup-${version}-win7.exe`：
  https://github.com/\<owner>/sage/releases?q=tag%3Av*-lts
- 前置条件: 装 **KB3033929** (SHA-2 代码签名, 2016 年发布)；x64 only
- 详细: [`docs/technical/21-win7-lts.md` §6](./docs/technical/21-win7-lts.md) 风险声明
```

### Step 3.3: 修改 `docs/user-manual/01-desktop.md` §1.1 系统要求表

打开 `docs/user-manual/01-desktop.md`，**替换**第 8-15 行的系统要求表：

```markdown
| 系统 | 最低 | 推荐 | 备注 |
|------|------|------|------|
| Windows 11 | ✅ | ✅ | 默认 WebView2 已装 |
| Windows 10 | ✅ | ✅ | 1809+ 含 WebView2 |
| **Windows 7** | ⚠️ 需 embedBootstrapper | ⚠️ x64 only | **x86 兼容性已知问题**（issue #11381） |
| macOS 12+ | ✅ | ✅ | Monterey 起 |
| Ubuntu 22.04+ | ✅ | ✅ | GTK + WebKitGTK 4.1 |
```

替换为：

```markdown
| 系统 | 最低 | 推荐 | 备注 | 下载来源 |
|------|------|------|------|---------|
| Windows 11 | ✅ | ✅ | 默认 WebView2 已装 | main release |
| Windows 10 | ✅ | ✅ | 1809+ 含 WebView2 | main release |
| **Windows 7 SP1 x64** | ⚠️ LTS only | ⚠️ x64 only | main release 不再支持; KB3033929 必需 | **LTS release** (`v*-lts` tag) |
| macOS 12+ | ⏳ Phase 3 | ⏳ Phase 3 | 暂未发布 | — |
| Ubuntu 22.04+ | ✅ | ✅ | GTK + WebKitGTK 4.1 | main release |
| Linux 通用 (glibc 2.28+) | ✅ | ✅ | AppImage 通用 | main release |
```

### Step 3.4: 修改 `docs/user-manual/01-desktop.md` §1.2 Win 安装拆为两子节

打开 `docs/user-manual/01-desktop.md`，**替换**第 16-37 行的 §1.2 安装 Windows 整段：

```markdown
### 1.2 安装 Windows

### 1.2.1 正常安装

1. 下载 `sage_0.1.0_x64-setup.exe`
2. 双击运行
3. 按提示完成安装
4. WebView2 自动检测（Win10 1809+ / Win11 预装）

### 1.2.2 Windows 7 安装

Win7 系统不预装 WebView2 runtime，需要 embedBootstrapper 模式：

1. 下载 `sage_0.1.0_x64-setup.exe`（构建时已含 WebView2 bootstrapper，约 +1.8MB）
2. 双击运行
3. 安装器自动检测并安装 WebView2
4. 安装完成后启动 Sage

**已知问题**（issue #11381）：

- Windows 7 **x86 (32-bit)** 上可能因 `tao` 库异常而崩溃
- 推荐 Win7 用户使用 **x64 (64-bit)** 版本
- x86 兼容性需要 rust 1.77.2 + 特定依赖降级（社区 workaround）
```

替换为：

```markdown
### 1.2 安装 Windows

### 1.2.1 Windows 10 / 11 安装 (main release)

1. 从 main release 页面下载 `Sage-Setup-${version}-win10.exe`
2. 双击运行, 按向导安装 (默认 HKCU, 无需管理员权限)
3. 安装阶段静默装 VC++ 2015-2022 Redistributable (已装会跳过)
4. 桌面出现 Sage 快捷方式, 双击启动

**入口**: https://github.com/\<owner>/sage/releases/latest

### 1.2.2 Windows 7 SP1 安装 (LTS release)

> ⚠️ **2026-06-23 起**: main release 不再支持 Win7。Win7 用户请下载 LTS release。

1. **前置**: 装 **KB3033929** (SHA-2 代码签名, 2016 年发布) — Win7 SP1 必装, 否则 Sage.exe 启动被拒
2. 从 LTS release 页面下载 `Sage-Setup-${version}-win7.exe`:
   https://github.com/\<owner>/sage/releases?q=tag%3Av*-lts
3. 双击 `.exe` 运行安装 (NSIS, HKCU, 无需管理员)
4. 安装阶段静默装 VC++ 2015-2022 Redistributable
5. 桌面出现 Sage 快捷方式, 双击启动
6. **x64 only** — Electron 21 不支持 Win7 32-bit

**已知限制**（基于 EOL 技术栈 Electron 21.4.4 + Chromium 106）:

- 不保证 Win7 GPU 驱动兼容, 启动时已禁用硬件加速 (`--disable-gpu`)
- 7 个 Chromium 启动开关在 `electron/main.ts` 行内注释完整记录
- 详见 [`../technical/21-win7-lts.md` §6 风险声明](../technical/21-win7-lts.md)
```

**注意**：把 `<owner>/sage` 替换为实际 owner。运行 `git -C /home/fz/project/sage remote get-url origin` 查。

### Step 3.5: 验证 `CHANGELOG.md` 现有 [Unreleased] 段

```bash
cd /home/fz/project/sage && head -30 CHANGELOG.md
```

查看是否已有 `[Unreleased]` 段。如果有, 在该段下加新条目；如果没有, 创建段。

### Step 3.6: 在 `CHANGELOG.md` [Unreleased] 段加新条目

在 `[Unreleased]` 段下（如果不存在则创建），加：

```markdown
## [Unreleased]

### Added
- **feat(ci)**: 双轨 release workflow (main → Win10+/Linux/macOS, LTS → Win7 SP1)
  - main release 产物: `Sage-Setup-${version}-win10.exe` (Windows), `sage_${version}_amd64.deb`, `Sage-${version}.AppImage`
  - LTS release 产物: `Sage-Setup-${version}-win7.exe` (Windows 7 SP1 x64 only, tag 形如 `v*-lts`)
  - 新 workflow: `.github/workflows/release-win7.yml` (在 `release/win7` 分支)
  - electron-builder.yml: `win.artifactName` 用 `${env.ARTIFACT_SUFFIX}` 占位
  - Win7 用户引导: 文档化的独立 release 入口

### Changed
- **docs(technical)**: `21-win7-lts.md` 加 §9 Release 工作流；`26-packaging-matrix.md` §1/§2 拆 Win7/Win10+；`20-electron.md` §5 加 LTS 提示
- **docs(README)**: §"双轨发布" 表格加具体下载入口；Q4 重写
- **docs(user-manual)**: `01-desktop.md` §1.1/§1.2 拆 Win7 LTS 子节
```

### Step 3.7: 验证 changelog 格式

```bash
cd /home/fz/project/sage && head -25 CHANGELOG.md
```

Expected: `[Unreleased]` 段存在，新条目（双轨 release workflow）在 `### Added` 子段下。

### Step 3.8: 提交用户面向文档 + CHANGELOG 改动

```bash
cd /home/fz/project/sage && git add README.md docs/user-manual/01-desktop.md CHANGELOG.md && git commit -m "docs: 双轨 release workflow 用户引导 (README + user-manual + CHANGELOG)

- README: §双轨发布 表格补具体下载入口; Q4 重写指向 LTS release
- user-manual/01-desktop: §1.1/§1.2 拆 Win10+ main 和 Win7 LTS 子节
- CHANGELOG: [Unreleased] 加 feat(ci) 双轨 release workflow 条目" 2>&1 | tail -5
```

Expected: commit 成功。

---

## Task 4: 验证、推送、创建 PR

**Files:**
- Read-only: `release.yml` / `release-win7.yml` / `electron-builder.yml` / 所有改过的文档
- Push: `feat/dual-track-release-workflow` 分支 → origin
- Create: PR via `gh pr create`

**Interfaces:**
- Consumes: Task 1-3 产出的所有 commits
- Produces: 一个 PR 等待 CI 绿 + 用户 merge

### Step 4.1: 检查功能分支状态

```bash
cd /home/fz/project/sage && git status --short && echo "---" && git log --oneline main..HEAD
```

Expected:
- 状态: 除 `M package-lock.json`（与本任务无关）外无未提交改动
- 3 个新 commit 在 `main` 之上（feat(ci) / docs(technical) / docs）

### Step 4.2: 跑本地 dry-run 验证 `ARTIFACT_SUFFIX=win10` 生效

> 这一步会触发完整 Windows NSIS build，**约需 2-3 分钟**。如果嫌慢可跳过（CI 会做同样的验证）。

```bash
cd /home/fz/project/sage && ARTIFACT_SUFFIX=win10 npx electron-builder --win nsis --publish never 2>&1 | tail -20
```

Expected: 看到 `Sage-Setup-<version>-win10.exe` 输出到 `release/<version>/` 路径。

### Step 4.3: 检查产物文件名

```bash
cd /home/fz/project/sage && ls -la release/*/Sage-Setup-*-win10.exe 2>&1
```

Expected: 至少一个 `Sage-Setup-<version>-win10.exe` 文件存在。

### Step 4.4: 跑 `ARTIFACT_SUFFIX=win7` dry-run

> 同样需要 2-3 分钟。**注意**：先备份 -win10 产物或重新放一个目录。

```bash
cd /home/fz/project/sage && rm -rf release/ && ARTIFACT_SUFFIX=win7 npx electron-builder --win nsis --publish never 2>&1 | tail -20
```

Expected: 看到 `Sage-Setup-<version>-win7.exe` 输出。

### Step 4.5: 验证 -win7 产物

```bash
cd /home/fz/project/sage && ls -la release/*/Sage-Setup-*-win7.exe 2>&1
```

Expected: 至少一个 `Sage-Setup-<version>-win7.exe` 文件存在。

### Step 4.6: 清理 dry-run 产物（不入 commit）

```bash
cd /home/fz/project/sage && rm -rf release/ && git status --short
```

Expected: 状态没有 `release/` 目录（应被 `.gitignore` 忽略）。

### Step 4.7: 推送到 origin

```bash
cd /home/fz/project/sage && git push -u origin feat/dual-track-release-workflow 2>&1 | tail -5
```

Expected: `* [new branch] feat/dual-track-release-workflow -> feat/dual-track-release-workflow`。

### Step 4.8: 创建 PR

```bash
cd /home/fz/project/sage && gh pr create \
  --base main \
  --head feat/dual-track-release-workflow \
  --title "feat(ci): 双轨 release workflow (main → Win10+, release/win7 → Win7 LTS)" \
  --body "## 目标

将 release 自动化对齐到 \`README.md\` §'双轨发布' 已对外宣传的双轨策略:

- **main release** (tag \`v*\` 不含 \`-lts\`) → Win10+ / Linux / macOS
- **LTS release** (tag \`v*-lts\` 在 \`release/win7\` 分支) → Windows 7 SP1 x64 only

## 主要改动

- \`electron-builder.yml\`: \`win.artifactName\` 用 \`\${env.ARTIFACT_SUFFIX}\` 占位
- \`.github/workflows/release.yml\`: 加 \`if-guard\` 排除 \`-lts\` tag; Windows job 设 \`ARTIFACT_SUFFIX=win10\`
- \`.github/workflows/release-win7.yml\` (新增): 监听 \`-lts\` tag, 出 \`-win7.exe\` 上传到 LTS release
- \`docs/technical/21-win7-lts.md\`: 加 §9 Release 工作流
- \`docs/technical/26-packaging-matrix.md\`: §1/§2 拆 Win7/Win10+ 行/子节
- \`docs/technical/20-electron.md\`: §5 加 LTS 提示
- \`README.md\`: §'双轨发布' 表格补具体下载入口; Q4 重写
- \`docs/user-manual/01-desktop.md\`: §1.1/§1.2 拆 Win7 LTS 子节
- \`CHANGELOG.md\`: [Unreleased] 加 feat(ci) 条目

## 验证

- [ ] CI 跑通 (desktop-build + electron-smoke 全绿)
- [ ] (可选) push \`v0.0.0-test\` 到 main → main release workflow 跑通
- [ ] (可选) push \`v0.0.0-test-lts\` 到 release/win7 → LTS release workflow 跑通

## 风险

详见 spec §4.1。最大风险: \`release/win7\` cherry-pick 时漏改 \`electron-builder.yml\` → 通过 commit message 强制同步。

## Spec

- 设计: \`docs/superpowers/specs/2026-06-23-win7-lts-release-workflow-design.md\`
- 计划: \`docs/superpowers/plans/2026-06-23-dual-track-release-workflow.md\`

Closes #无 (新功能, 无对应 issue)" 2>&1 | tail -10
```

Expected: PR URL 输出（如 `https://github.com/onemuggle/sage/pull/55`）。

### Step 4.9: 监控 PR CI

```bash
cd /home/fz/project/sage && gh pr checks $(gh pr list --head feat/dual-track-release-workflow --json number -q '.[] | "\(.number)"') --watch 2>&1 | tail -20
```

Expected: 所有 checks 显示 `pass`（desktop-build, electron-smoke, frontend, backend 等）。

如果有任何 check 失败:
1. 看 `gh pr checks <PR#>` 找失败 job
2. `gh run view <run-id> --log-failed` 看具体错误
3. 修代码 → commit → push → 监控

### Step 4.10: 任务完成报告

任务完成。在 PR 描述里 @ 用户 review。

**完工检查清单**:

- [ ] `release.yml` 头部注释更新
- [ ] `release.yml` build job 有 `if: "!contains(github.ref_name, '-lts')"`
- [ ] `release.yml` Windows step 有 `env: ARTIFACT_SUFFIX: win10`
- [ ] `release.yml` upload glob 含 `*-win10.exe`
- [ ] `release-win7.yml` 存在并有 `if: "contains(github.ref_name, '-lts')"`
- [ ] `release-win7.yml` 有 `env: ARTIFACT_SUFFIX: win7`
- [ ] `electron-builder.yml` 的 `win.artifactName` 用了 `${env.ARTIFACT_SUFFIX}` 占位
- [ ] `21-win7-lts.md` §9 存在
- [ ] `26-packaging-matrix.md` §1/§2 反映双 release
- [ ] `20-electron.md` §5 有 LTS 提示
- [ ] `README.md` §'双轨发布' 表格含具体链接
- [ ] `README.md` Q4 重写
- [ ] `01-desktop.md` §1.1/§1.2 拆 Win7/Win10+
- [ ] `CHANGELOG.md` [Unreleased] 加条目
- [ ] 4 个 commit 在 `feat/dual-track-release-workflow` 分支
- [ ] PR 创建, CI 全绿

---

## 验收准则

实施完成后必须满足（来自 spec §5）:

- [ ] `release.yml` 头部注释明确说明 Win7 在 LTS release
- [ ] `release.yml` 含 `if: "!contains(github.ref_name, '-lts')"` 守卫
- [ ] `release.yml` Windows job 产物命名为 `Sage-Setup-${version}-win10.exe`
- [ ] `release-win7.yml` 存在并含 `if: "contains(github.ref_name, '-lts')"` 守卫
- [ ] `release-win7.yml` Windows job 产物命名为 `Sage-Setup-${version}-win7.exe`
- [ ] `electron-builder.yml` 的 `win.artifactName` 使用 `${env.ARTIFACT_SUFFIX}` 占位
- [ ] `docs/technical/21-win7-lts.md` §9 存在并完整
- [ ] `docs/technical/26-packaging-matrix.md` §1/§2 反映双 release 入口
- [ ] `README.md` §"双轨发布" 表格含具体下载入口
- [ ] `docs/user-manual/01-desktop.md` §1.2 拆分 Win10+ 和 Win7 子节
- [ ] `CHANGELOG.md` [Unreleased] 段加入条目
- [ ] 本地 dry-run 验证: `ARTIFACT_SUFFIX=win10` 产出 `-win10.exe`; `ARTIFACT_SUFFIX=win7` 产出 `-win7.exe`
- [ ] Actions dry-run: push `v0.0.0-test` → main; push `v0.0.0-test-lts` → LTS

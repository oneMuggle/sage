# 双轨 release 工作流（main → Win10+ & release/win7 → Win7 LTS）

> **状态**: 草案 v1（待用户审阅）
> **日期**: 2026-06-23
> **作者**: Claude (brainstorming)
> **关联文档**:
> - `docs/technical/21-win7-lts.md` §2（双分支定位）
> - `docs/technical/26-packaging-matrix.md` §1（平台覆盖矩阵）
> - `README.md` §"双轨发布"（已对外宣传但 workflow 未对齐）
> - `release/win7:BRANCH_NOTES.md`（LTS 分支声明）

---

## 1. 背景与目标

### 1.1 当前状态（问题）

`README.md` §"双轨发布" 自 2026-06-13 起对外宣传：

> | 分支               | 目标平台                                  |
> | ------------------ | ----------------------------------------- |
> | **`main`**         | Win10+ / macOS / Linux                    |
> | **`release/win7`** | **Windows 7 SP1 x64**（完全离线部署）     |

但实际 release workflow（`.github/workflows/release.yml`）**只触发 main 分支的 tag push**，而 `release/win7` 分支**没有 release workflow**。两个后果：

1. Win7 用户从 `release/win7` 分支文档上被告知去 GitHub Releases 页面下载，但实际 main release 出来的 `Sage-Setup-X.Y.Z.exe` 才是唯一的产物
2. 文档承诺与 CI 现实不一致——main 仍锁 Electron 21.4.4 是为了"main 也要兼容 Win7"，但用户可能误以为 main release 也支持 Win7

### 1.2 目标

将 release 自动化**对齐**到文档承诺：

| Release 通道         | 触发分支          | 目标平台               | Tag 格式           |
| -------------------- | ----------------- | ---------------------- | ------------------ |
| **main release**     | `main`            | Win10+ / Linux / macOS | `v0.2.0`           |
| **Win7 LTS release** | `release/win7`    | Windows 7 SP1 x64 only | `v0.2.0-lts`       |

**具体收益**：

1. **UX 清晰** — Win10+ 用户从 main release 下载 `-win10.exe`，Win7 用户从 LTS release 下载 `-win7.exe`，文件名自带 OS 标识
2. **分支可独立升级** — main 未来可以升 Electron 到 28+（2027 年 Electron 32 LTS），不用再为 Win7 妥协；LTS 维持 Electron 21.4.4
3. **Win7 EOL 2027-12-13 时** — 直接 `git push origin --delete release/win7` + 删 `release-win7.yml`，main 无需任何改动
4. **CI 成本仅 +1 个 workflow 文件** — 不需要拆 IPC 启动开关、不需要翻倍 cache key

### 1.3 范围

**IN SCOPE**:
- `release.yml` 头部注释 + 产物命名（加 `-win10` 后缀）
- 新增 `release-win7.yml`
- `electron-builder.yml` artifactName 改用环境变量切后缀
- 文档：`26-packaging-matrix.md` §1/§2、`21-win7-lts.md` §9、`20-electron.md` §5 流程图、`README.md` §"双轨发布" + Q4、`docs/user-manual/01-desktop.md` §1.1/§1.2
- `CHANGELOG.md` 加 entry

**OUT OF SCOPE** (后续 Phase 7+):
- main 分支的 Electron 21.4.4 → 28+ 升级
- 真实 Win7 self-hosted runner（目前用 `windows-latest` cross-build 兜底）
- LTS 通道的 Linux/macOS（Win7 LTS 不覆盖 Linux/macOS，跟 main 一致）
- 真实 Win7 烟测结果触发 release 的"软门禁"（21-win7-lts.md §10 风险 #5）

---

## 2. 设计

### 2.1 Tag 命名约定

| Tag 模式        | 触发 workflow       | 渠道     | Release 页面标题                     |
| --------------- | ------------------- | -------- | ------------------------------------ |
| `vMAJOR.MINOR.PATCH`（如 `v0.2.0`） | `release.yml`       | main     | `Sage v0.2.0`                        |
| `vMAJOR.MINOR.PATCH-IDENTIFIER`（如 `v0.2.0-beta.1`） | `release.yml`       | main     | `Sage v0.2.0-beta.1`                 |
| `vMAJOR.MINOR.PATCH-lts`（如 `v0.2.0-lts`） | `release-win7.yml`  | LTS      | `Sage v0.2.0 (Win7 LTS)`             |

**冲突处理**：两个 workflow 都监听 `push tags: v*`，用 `if` 守卫分流：

```yaml
# release.yml (main)
on:
  push:
    tags: ['v*']
jobs:
  build:
    if: "!contains(github.ref_name, '-lts')"
```

```yaml
# release-win7.yml (LTS)
on:
  push:
    tags: ['v*']
jobs:
  build:
    if: "contains(github.ref_name, '-lts')"
```

LTS workflow 在非 LTS tag 上虽然 start 但所有 job 立即跳过，Actions 历史会有"无操作"记录。**接受这个 trade-off**：tag pattern 的 include/exclude 语法 GitHub 不支持，引入 tag 后缀（`-lts`）是最低成本的方案。

### 2.2 产物命名

| 渠道   | 平台       | 产物                                    | 路径                                              |
| ------ | ---------- | --------------------------------------- | ------------------------------------------------- |
| main   | Linux      | `sage_${version}_amd64.deb`            | `release/${version}/sage_${version}_amd64.deb`    |
| main   | Linux      | `Sage-${version}.AppImage`             | `release/${version}/Sage-${version}.AppImage`     |
| main   | Windows    | `Sage-Setup-${version}-win10.exe`      | `release/${version}/Sage-Setup-${version}-win10.exe` |
| main   | macOS      | (Phase 3+, 当前 null)                   | —                                                 |
| LTS    | Windows    | `Sage-Setup-${version}-win7.exe`       | `release/${version}/Sage-Setup-${version}-win7.exe`  |

**后缀规则**：

- **Windows NSIS** 加 OS 后缀（`-win10` / `-win7`）—— 用户一眼看出目标平台
- **Linux deb / AppImage** 不加后缀 —— deb 命名已含 `_amd64`，AppImage 不存在平台歧义

**实现机制**：`electron-builder.yml` 的 `win.artifactName` 用环境变量切后缀：

```yaml
win:
  artifactName: ${productName}-Setup-${version}-${env.ARTIFACT_SUFFIX}.${ext}

linux:
  artifactName: ${productName}-${version}.${ext}    # 不变

deb:
  artifactName: sage_${version}_amd64.${ext}        # 不变
```

**默认值约束**：`env.ARTIFACT_SUFFIX` **必须**被 workflow 设置，否则 electron-builder 解析为空字符串，产物会变成 `Sage-Setup-0.2.0-.exe`（注意两个连字符，破产物）。

```yaml
# release.yml 的 build job 顶层 (默认值)
env:
  ARTIFACT_SUFFIX: ''  # placeholder；windows job 必须覆盖

# Windows job step env 覆盖
env:
  ARTIFACT_SUFFIX: win10
```

```yaml
# release-win7.yml 的 build job 顶层
env:
  ARTIFACT_SUFFIX: win7
```

**为什么用环境变量而不是两份 electron-builder.yml** — `release/win7` 分支没有自己的 electron-builder.yml，cherry-pick 同步时只需关注代码/脚本差异，配置统一在主文件用 env 切。

### 2.3 Release page 内容差异化

**main release notes 模板**：

```markdown
## Sage v0.2.0 — Win10+ / Linux / macOS

### Downloads

| Platform       | File                                | Notes                         |
| -------------- | ----------------------------------- | ----------------------------- |
| Windows 10/11  | `Sage-Setup-0.2.0-win10.exe`        | x64, NSIS, VCRedist bundled   |
| Ubuntu 20.04+  | `sage_0.2.0_amd64.deb`              | Native deb                    |
| Linux generic  | `Sage-0.2.0-linux.AppImage`         | glibc 2.28+                   |
| macOS          | (not yet released)                  | Phase 3 plan                  |

### Win7 SP1 用户

请从 [`release/win7` 分支的 LTS Release](https://github.com/.../releases?q=tag%3Av0.2.0-lts) 下载 `Sage-Setup-0.2.0-win7.exe`。
```

**LTS release notes 模板**：

```markdown
## Sage v0.2.0 (Win7 LTS) — Windows 7 SP1 x64 ONLY

> ⚠️ **此版本专为 Windows 7 SP1 x64 设计**。Win10+ 用户请改用 [main release](https://github.com/.../releases/tag/v0.2.0)。
>
> ⚠️ **本分支基于 EOL 技术栈**（Electron 21.4.4 + Python 3.8 + Chromium 106）。详见 [`docs/technical/21-win7-lts.md`](https://github.com/.../blob/release/win7/docs/technical/21-win7-lts.md) §6 风险声明。

### Downloads

| File                                 | Notes                                          |
| ------------------------------------ | ---------------------------------------------- |
| `Sage-Setup-0.2.0-win7.exe`          | NSIS, x64, VCRedist bundled, KB3033929 必需    |

### Win7 前置

- **KB3033929**（SHA-2 代码签名支持，2016 年发布）— Win7 SP1 必须先装，否则 Sage.exe 启动被拒
- x64 only（Electron 21 不支持 Win7 32-bit）
```

**生成方式**：通过 `softprops/action-gh-release@v2` 的 `body: |` 字段内嵌。`generate_release_notes: true` 仍启用（自动附 commit 列表），手动 body 加在前面。

### 2.4 LTS release 的局限

LTS workflow **不构建** Linux 和 macOS 产物——LTS 分支只服务 Win7：

- macOS 跟 Win7 无关（macOS 12+ 不需要 LTS）
- Linux 跟 Win7 无关（glibc 2.28+ 都自带现代 Electron）
- Linux/macOS 用户继续从 main release 下载

**LTS workflow 的 windows job 跟 main release.yml 的 windows job 几乎相同**，差异只在：

- env.ARTIFACT_SUFFIX = win7（vs win10）
- 不需要 VCRedist fetcher？不，仍然需要（NSIS 安装器都 bundling VCRedist）

### 2.5 与现有 LTS 流程的对齐

| 现有约定                                | 本设计调整                                  |
| --------------------------------------- | ------------------------------------------- |
| `release/win7` 分支 18 个月 EOL 计划   | 保持（与 LTS release workflow 同步）        |
| `docs/technical/21-win7-lts.md` §3 人工烟测 | 保持（每个 LTS release 前人工执行）          |
| main + LTS 双分支 cherry-pick 同步      | 保持（commit message 走 conventional）       |
| `ci.yml` 用 `if: github.ref == 'refs/heads/release/win7'` 跑 backend-py38 | 保持（CI 已经分轨） |

---

## 3. 详细改动清单

### 3.1 新增 `.github/workflows/release-win7.yml`

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
#   - EOL:       2027-12-13 归档,届时删除本 workflow
#
# 详见 docs/technical/21-win7-lts.md §2 LTS 策略

name: Release (Win7 LTS)

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  build-windows:
    name: Build Windows (Win7 LTS)
    # Only act on LTS-suffixed tags
    if: "contains(github.ref_name, '-lts')"

    runs-on: windows-latest

    env:
      ARTIFACT_SUFFIX: win7

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'

      - name: Cache electron-builder downloads
        uses: actions/cache@v4
        with:
          path: |
            ~/.cache/electron
            ~/.cache/electron-builder
          key: ${{ runner.os }}-electron-lts-${{ hashFiles('package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-electron-lts-

      - name: Install npm dependencies
        run: npm ci --force

      - name: Build frontend + Electron
        run: npm run electron:build

      - name: Fetch VC++ Redistributable
        shell: pwsh
        run: pwsh scripts/fetch-vcredist.ps1

      - name: Build Windows NSIS (Win7 LTS)
        run: npx electron-builder --win nsis --publish never

      - name: Upload to LTS GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          # Strip -lts suffix from tag for the "real" version, but use the original
          # tag as the release identifier (so v0.2.0-lts becomes a separate release)
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

            ### 前置
            - **KB3033929** (SHA-2 代码签名) — Win7 SP1 必装
            - x64 only
          draft: true
          generate_release_notes: true
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 3.2 修改 `.github/workflows/release.yml`

**改动 1**: 头部注释加 Win7 提示

```yaml
# Release Workflow — 自动化构建 + 上传 Electron 应用到 GitHub Release
#
# 触发条件: push tag 形如 v* (如 v0.2.0, v1.0.0-beta.1)
#
# ⚠️ Win7 LTS 专用 installer 改由 release-win7.yml 在 release/win7 分支产出
#    tag 格式: v*-lts (如 v0.2.0-lts)
#    下载入口: https://github.com/.../releases?q=tag%3Av0.2.0-lts
#
# 工作流:
#   1. checkout 代码
#   2. setup Node.js + cache npm + electron-builder downloads
#   3. 安装 Linux 构建依赖
#   4. 构建前端 + Electron (npm run electron:build)
#   5. electron-builder 跨平台构建 (linux AppImage/deb + windows NSIS)
#   6. 上传产物到 GitHub Release (由本次 push tag 自动创建)
```

**改动 2**: 加 `if` 守卫 + `ARTIFACT_SUFFIX` 环境变量

```yaml
jobs:
  build:
    name: Build (${{ matrix.os }})
    # Skip LTS-suffixed tags — those go to release-win7.yml
    if: "!contains(github.ref_name, '-lts')"
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]

    runs-on: ${{ matrix.os }}

    env:
      # Default suffix; Windows job overrides to win10
      ARTIFACT_SUFFIX: linux
```

**改动 3**: Windows job 的 env 覆盖 + upload glob 改 `-win10.exe`

```yaml
      - name: Build Windows (NSIS installer)
        if: matrix.os == 'windows-latest'
        env:
          ARTIFACT_SUFFIX: win10
        run: npx electron-builder --win nsis --publish never

      - name: Upload artifacts to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            release/*/Sage-*.AppImage
            release/*/sage_*_amd64.deb
            release/*/Sage-Setup-*-win10.exe
          # ...其余不变
```

### 3.3 修改 `electron-builder.yml`

只改 `win.artifactName`（具体配置见 §2.2 模板）：

```yaml
win:
  target:
    - target: nsis
      arch:
        - x64
  icon: build/icon.ico
  artifactName: ${productName}-Setup-${version}-${env.ARTIFACT_SUFFIX}.${ext}
  # ... 其余不变

linux:
  artifactName: ${productName}-${version}.${ext}    # 不变

deb:
  artifactName: sage_${version}_amd64.${ext}        # 不变
```

**默认值约束**：见 §2.2，workflow 必须显式设 `ARTIFACT_SUFFIX`，否则产物命名破缺。

### 3.4 文档改动

| 文件                                              | 改动                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `docs/technical/26-packaging-matrix.md` §1        | Windows 行拆为两行（main release + LTS release）                                            |
| `docs/technical/26-packaging-matrix.md` §2        | §2 拆 "Windows 7 SP1 / 10 / 11" 为 "Win10/11" 和 "Win7 SP1 LTS" 独立子节                   |
| `docs/technical/21-win7-lts.md`                  | 加 §9 Release 工作流（说明 tag 格式 + 下载入口 + EOL 后归档动作）                           |
| `docs/technical/20-electron.md` §5                | 把 CI 矩阵描述加一行 "Win7 LTS release 由 release-win7.yml 单独产出"                        |
| `README.md` §"双轨发布"                            | 表格中"下载方式"列改为具体 GitHub Releases 链接模板                                         |
| `README.md` Q4                                    | 改为具体 "Win7 用户请下载 v*-lts 版本的 -win7.exe"                                          |
| `docs/user-manual/01-desktop.md` §1.1/§1.2        | 系统要求表 + 安装步骤拆分 Win10+ 和 Win7 LTS                                               |
| `CHANGELOG.md`                                    | 加 unreleased entry: "feat(release): 双轨 release workflow (main → Win10+, LTS → Win7)" |

### 3.5 文档章节示例

`docs/technical/21-win7-lts.md` §9（新增）：

```markdown
## 9. Release 工作流

`release/win7` 分支的 release 由 **`.github/workflows/release-win7.yml`** 触发，独立于 main。

| 项              | 值                                                                                |
| --------------- | --------------------------------------------------------------------------------- |
| 触发 tag        | `v*-lts`（如 `v0.2.0-lts`）                                                       |
| Runner          | `windows-latest` (cross-build, 同 main)                                           |
| 产物            | `Sage-Setup-${version}-win7.exe` (NSIS, x64)                                      |
| Release 入口    | https://github.com/.../releases?q=tag%3Av*-lts                                    |
| Release 状态    | draft（人工 review 后 publish）                                                   |
| 与 main 共用    | electron-builder.yml / build/installer.nsh / scripts/fetch-vcredist.ps1            |
| EOL 动作        | 2027-12-13 后 `git push origin --delete release/win7` + 删 `release-win7.yml`       |

### 9.1 触发步骤

1. 切到 `release/win7` 分支: `git switch release/win7`
2. 拉 main 的最新 commit: `git fetch origin main && git rebase origin/main`（如有冲突手动解决）
3. 决定版本号: 通常 cherry-pick N 个 commit 后 bump patch 号（如 `0.2.0` → `0.2.0-lts` 或 `0.2.1-lts`）
4. 打 tag: `git tag -a v0.2.1-lts -m "v0.2.1-lts — Win7 patch: ..."`
5. push tag: `git push origin v0.2.1-lts`
6. 监控 Actions: `gh run watch`
7. CI 通过后到 https://github.com/.../releases 找到 draft，**人工 review release notes** 后 publish

### 9.2 失败处理

| 失败位置                          | 处理                                                                       |
| --------------------------------- | -------------------------------------------------------------------------- |
| Win7 烟测未通过                   | 不 publish；hotfix 修；重新打 tag (`v0.2.2-lts`)                          |
| NSIS 产物里没有 win7 后缀         | 检查 release-win7.yml 的 `env.ARTIFACT_SUFFIX` 是否正确设为 `win7`         |
| Release 误发到 main channel       | 删 release + 删 tag：`gh release delete v0.2.0-lts && git push origin :v0.2.0-lts` |
```

---

## 4. 风险与回滚

### 4.1 风险登记

| 风险                                                   | 严重度 | 概率 | 缓解                                                                                |
| ------------------------------------------------------ | ------ | ---- | ----------------------------------------------------------------------------------- |
| electron-builder 的 `${env.ARTIFACT_SUFFIX}` 解析异常 | LOW    | 低   | 顶层 env 设默认空串，job-level 覆盖；本地用 `ARTIFACT_SUFFIX=win10 npm run electron:dist` 验证 |
| LTS tag 误触发 main workflow                           | MEDIUM | 低   | main release.yml 的 `if: "!contains(github.ref_name, '-lts')"` 显式过滤              |
| main tag 误触发 LTS workflow                           | MEDIUM | 低   | LTS release-win7.yml 的 `if: "contains(github.ref_name, '-lts')"` 显式过滤            |
| 现有用户从 main release 仍下载到 Win10 installer      | LOW    | 中   | README + release notes 显式引导 Win7 用户去 LTS release                              |
| LTS 分支 cherry-pick 时遗漏 electron-builder.yml 改动  | HIGH   | 低   | electron-builder.yml 改动走 main → win7 自动同步（cherry-pick `electron-builder.yml`） |
| LTS release 没跑 Win7 真机烟测就 publish              | MEDIUM | 中   | 21-win7-lts.md §3 流程要求人工烟测；release notes 模板加 "⚠️ 烟测未通过请勿下载" 提示  |
| cache key 冲突（main 和 LTS 共享 cache）               | LOW    | 中   | LTS 用 `key: ...-electron-lts-...` 区分（见 release-win7.yml）                        |

### 4.2 回滚计划

**触发条件**: LTS release workflow 在 1 周内有 ≥ 1 个 CRITICAL 问题（如产物损坏、tag 误发、release page 内容错乱）。

**回滚步骤**:

1. **删除新 workflow**: `git rm .github/workflows/release-win7.yml`
2. **revert main release.yml + electron-builder.yml 改动**: `git revert <commit>`
3. **删除 LTS release page**: `gh release delete v0.2.0-lts` (如有)
4. **删除 tag**: `git push origin :v0.2.0-lts`
5. **发布 hotfix**: `git commit -m "fix(ci): revert 双轨 release workflow" && push`
6. **公告**: 在 `release/win7` 分支的 BRANCH_NOTES.md 加 "release workflow 回滚中, 暂停 LTS release" 段落

**回滚时长**: < 30 分钟（main 改动是 additive, revert 干净）。

### 4.3 后续 Phase 7+（不属本 spec 范围）

1. **main 升 Electron 28+**: 不再锁 21.4.4; main release 出新版 installer
2. **Win7 self-hosted runner**: 拿到 Win7 物理机后改 `runs-on: [self-hosted, windows-7]`
3. **LTS release 软门禁**: 把 "最近 7 天有 Win7 烟测报告" 作为 release publish 的前置条件
4. **macOS DMG**: Phase 3 启用 `mac.target: dmg` + 代码签名
5. **deb GPG 签名**: Phase 3 加 GPG key + APT repo

---

## 5. 验收准则

实施完成后必须满足：

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
- [ ] 本地 dry-run 验证: `ARTIFACT_SUFFIX=win10 npm run electron:dist` 产出 `-win10.exe`; `ARTIFACT_SUFFIX=win7 npm run electron:dist` 产出 `-win7.exe`
- [ ] Actions dry-run: push `v0.0.0-test` 到 main → main workflow 跑通; push `v0.0.0-test-lts` 到 release/win7 → LTS workflow 跑通

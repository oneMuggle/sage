# Sage 版本生命周期分级（alpha → beta → preview → stable）

> **状态**: 草案 v1（待用户审阅）
> **日期**: 2026-07-06
> **作者**: Claude (brainstorming)
> **关联文档**:
> - `docs/technical/21-win7-lts.md` §9 Release 工作流
> - `docs/technical/26-packaging-matrix.md` §1/§2 平台矩阵
> - `README.md` §"双轨发布" 表格
> - `CHANGELOG.md` (Keep a Changelog)
> - `.github/workflows/release.yml` + `.github/workflows/release-win7.yml`

---

## 1. 背景与目标

### 1.1 当前状态（问题）

Sage 自 v0.1.0 起所有 tag 都是"稳定版"语义，没有区分 alpha/beta/preview 渠道：

- 2 个月内发布 12 个 tag（M1-M9 多个 milestone 快速迭代）
- 每次 merge 后直接打 `v0.X.Y` 或 `v0.X.Y-lts`，无内部 soak 缓冲
- 用户只能"装或不装"，无法按风险偏好选择
- 快速迭代期暴露给全量用户，blocker bug 修复成本高
- README 仅承诺"双轨发布"，但缺失"预发布渠道"维度

### 1.2 目标

引入 **4 档发布分级 + SemVer 预发布段 + 双分支 LTS 派生 + 约定式提交推断升档**，覆盖：

| 档位 | 目标用户 | 风险等级 | 通道 |
|------|----------|----------|------|
| **alpha** | Sage 贡献者 | 高 | GitHub Releases `prerelease=true` |
| **beta** | 公开少量早期用户 | 中高 | GitHub Releases `prerelease=true` |
| **preview / RC** | 准稳定广泛推荐 | 中 | GitHub Releases `prerelease=true` |
| **stable** | 全量用户 | 低 | GitHub Releases (latest) |

**具体收益**：
1. 快速迭代时给早期用户风险缓冲，避免每次 merge 即暴露全量
2. 严格遵循 SemVer 2.0 预发布段规范 (`alpha.N` / `beta.N` / `rc.N`)，npm/uv 等工具可识别
3. win7 LTS 维护分支同步具备分级能力（`v0.5.0-beta.1-lts`）
4. 升档基于约定式提交与 milestone 闭合状态，可脚本化（不强制）

### 1.3 不做的事（YAGNI）

- ❌ 不引入 release-please / semantic-release 等外部工具
- ❌ 不创建独立 alpha/beta/rc 物理分支（仅 tag 区分）
- ❌ 不在 CI 里自动打 tag（始终人工确认）
- ❌ 不为预发布段做 in-app update channel（GitHub Releases 足够）
- ❌ 不让 Tauri 矩阵参与预发布（仅 stable 同步）

---

## 2. 版本号规范

### 2.1 Tag 格式

| 档位 | main 分支 | win7 LTS 分支 |
|------|-----------|---------------|
| alpha | `v0.5.0-alpha.1` | `v0.5.0-alpha.1-lts` |
| beta | `v0.5.0-beta.2` | `v0.5.0-beta.2-lts` |
| preview / RC | `v0.5.0-rc.1` | `v0.5.0-rc.1-lts` |
| stable | `v0.5.0` | `v0.5.0-lts` |

注：`-lts` 后缀始终在 tier 之后，符合 SemVer 2.0 附录 B（多 pre-release identifier 用 `.` 分隔，`-` 仅作为第一个分隔符）。

### 2.2 段内数字递增规则

- 同一 `MAJOR.MINOR.PATCH` 内：`alpha.1 → alpha.2 → beta.1 → beta.2 → rc.1 → rc.2 → v0.5.0`
- 升档时数字重置从 1 开始（如 `beta.2` 后升 `rc`，下一个是 `rc.1`）
- 跨 MINOR：进入新的 `v0.6.0-*` 系列，计数清零
- PATCH 修复：仅 stable 后才有 `v0.5.1`（hotfix）；预发布段内不打 patch，bug 在当前段累积修复

### 2.3 升号触发（约定式提交推断）

| 触发条件 | 推断档位 |
|----------|----------|
| 首个 `feat:` merge 到 main，且未发过任何 `v0.X.Y-*` tag | **alpha.1** |
| 累计 ≥3 `feat:` 或首个完整 milestone (e.g. M1) 闭合 | **beta.1** |
| 累计 ≥6 `feat:` 或 ≥2 milestone 闭合 | **rc.1** |
| 所有 milestone 闭合 + 无 `release-blocker` issue | **stable** |
| `fix:` merge → 预发布段内数字 +1（`alpha.1` → `alpha.2`），不影响 stable | 段内 +1 |
| `BREAKING CHANGE:` body → MINOR 不够 → MAJOR+1，预发布段号不变 | MAJOR 升号 |
| `hotfix:` merge → 不走预发布段，直接 `v0.5.1` | PATCH 升号 |

### 2.4 LTS 派生规则

- win7 LTS 的预发布 tag **必须**从 main 的对应 tag cherry-pick 后打，不允许直接基于旧 LTS tag 升档
- 例：main 发 `v0.5.0-beta.2`，2 周 soak 后 win7 才打 `v0.5.0-beta.2-lts`
- 例外：纯 win7 修复可打 `v0.4.3-lts` patch（`v0.4.2-lts → v0.4.3-lts`），不走预发布段
- alpha 阶段 win7 LTS 不跟随（alpha 仅供贡献者，win7 用户无 alpha 需求）
- beta/rc/stable 跟随，间隔 1-2 周

### 2.5 Tauri 规则

- Tauri **不参与**预发布段，alpha/beta/rc 阶段不发 Tauri 构建
- 仅当 main 进入 stable 时才同步触发 Tauri stable 构建（`release.yml` 加 `tauri-build` 步骤，仅在 `!contains(github.ref_name, '-')` 时运行）
- Tauri 矩阵维持现状（`ci.yml` 跑常规 CI）

---

## 3. CI Workflow 改动

### 3.1 `release.yml` 改动（main 分支）

```yaml
# 改动点 1: prerelease 自动判断
- name: Upload artifacts to GitHub Release
  uses: softprops/action-gh-release@v2
  with:
    tag_name: ${{ github.ref_name }}
    files: |
      release/*/Sage-*.AppImage
      release/*/sage_*_amd64.deb
      release/*/Sage-Setup-*-win10.exe
    # NEW:
    prerelease: ${{ contains(github.ref_name, '-alpha') || contains(github.ref_name, '-beta') || contains(github.ref_name, '-rc') }}
    body: |
      ## 🧪 Sage ${{ github.ref_name }}

      > **This is a ${{ contains(github.ref_name, '-alpha') && 'ALPHA' || contains(github.ref_name, '-beta') && 'BETA' || contains(github.ref_name, '-rc') && 'RELEASE CANDIDATE' || 'STABLE' }} release.**
      > ${{ contains(github.ref_name, '-alpha') && '⚠️ 仅供 Sage 贡献者使用，可能含已知 bug。' || contains(github.ref_name, '-beta') && '⚠️ 公开测试版，欢迎反馈 issue。' || contains(github.ref_name, '-rc') && '✅ 准稳定版，推荐广泛测试。' || '✅ 稳定版，推荐所有用户升级。' }}

      ...
    draft: true
    generate_release_notes: true
    fail_on_unmatched_files: false
```

### 3.2 Cache key 命名空间隔离

```yaml
# 旧：stable 与预发布共享 cache
key: ${{ runner.os }}-electron-${{ hashFiles('package-lock.json') }}

# 新：预发布 tag 加 -prerelease 命名空间
key: ${{ runner.os }}-electron-${{ contains(github.ref_name, '-') && 'prerelease-' || '' }}${{ hashFiles('package-lock.json') }}
```

效果：
- `v0.5.0` → `windows-electron-a1b2c3d4` (stable)
- `v0.5.0-beta.1` → `windows-electron-prerelease-a1b2c3d4` (隔离)

### 3.3 `release-win7.yml` 改动

相同逻辑应用到 `prerelease` 字段：

```yaml
- name: Upload to LTS GitHub Release
  uses: softprops/action-gh-release@v2
  with:
    tag_name: ${{ github.ref_name }}
    files: |
      release/*/Sage-Setup-*-win7.exe
    prerelease: ${{ contains(github.ref_name, '-alpha') || contains(github.ref_name, '-beta') || contains(github.ref_name, '-rc') }}
    body: |
      ## Sage ${{ github.ref_name }} (Win7 LTS) — Windows 7 SP1 x64 ONLY

      > **Tier**: ${{ contains(github.ref_name, '-alpha') && 'ALPHA' || contains(github.ref_name, '-beta') && 'BETA' || contains(github.ref_name, '-rc') && 'RC' || 'STABLE' }}
      ... (现有 LTS 警告 + KB3033929 提示)
    draft: true
```

LTS cache key 同步加 `-prerelease` 隔离：

```yaml
key: ${{ runner.os }}-electron-lts-${{ contains(github.ref_name, '-alpha') && 'prerelease-' || contains(github.ref_name, '-beta') && 'prerelease-' || contains(github.ref_name, '-rc') && 'prerelease-' || '' }}${{ hashFiles('package-lock.json') }}
```

### 3.4 Artifact 命名（electron-builder.yml 配套）

| Tag | workflow env ARTIFACT_SUFFIX | Artifact |
|-----|----------------------------|----------|
| `v0.5.0-alpha.1` | `alpha` | `Sage-Setup-0.5.0-alpha.exe` |
| `v0.5.0-beta.1` | `beta` | `Sage-Setup-0.5.0-beta.exe` |
| `v0.5.0-rc.1` | `rc` | `Sage-Setup-0.5.0-rc.exe` |
| `v0.5.0` | `win10` | `Sage-Setup-0.5.0-win10.exe` |
| `v0.5.0-lts` | `win7` | `Sage-Setup-0.5.0-win7.exe` |
| `v0.5.0-beta.1-lts` | `beta-lts` | `Sage-Setup-0.5.0-beta-lts.exe` |

workflow env 注入逻辑（在 `Build Windows` 步骤前）：

```yaml
- name: Determine ARTIFACT_SUFFIX
  id: suffix
  run: |
    if [[ "${{ github.ref_name }}" == *-alpha* ]]; then
      if [[ "${{ github.ref_name }}" == *-lts ]]; then
        echo "value=alpha-lts" >> $GITHUB_OUTPUT
      else
        echo "value=alpha" >> $GITHUB_OUTPUT
      fi
    elif [[ "${{ github.ref_name }}" == *-beta* ]]; then
      if [[ "${{ github.ref_name }}" == *-lts ]]; then
        echo "value=beta-lts" >> $GITHUB_OUTPUT
      else
        echo "value=beta" >> $GITHUB_OUTPUT
      fi
    elif [[ "${{ github.ref_name }}" == *-rc* ]]; then
      if [[ "${{ github.ref_name }}" == *-lts ]]; then
        echo "value=rc-lts" >> $GITHUB_OUTPUT
      else
        echo "value=rc" >> $GITHUB_OUTPUT
      fi
    elif [[ "${{ github.ref_name }}" == *-lts ]]; then
      echo "value=win7" >> $GITHUB_OUTPUT
    else
      echo "value=win10" >> $GITHUB_OUTPUT
    fi
```

### 3.5 Tauri Stable 同步（仅 stable 触发）

```yaml
# release.yml 新增 job（仅 stable tag 触发）
build-tauri:
  name: Build Tauri (stable only)
  if: "!contains(github.ref_name, '-alpha') && !contains(github.ref_name, '-beta') && !contains(github.ref_name, '-rc') && !contains(github.ref_name, '-lts')"
  needs: build
  runs-on: ${{ matrix.os }}
  strategy:
    matrix:
      os: [ubuntu-latest, windows-latest]
  steps:
    - uses: actions/checkout@v4
    - name: Build Tauri
      run: npm run tauri build
    - name: Upload Tauri artifacts
      uses: softprops/action-gh-release@v2
      with:
        tag_name: ${{ github.ref_name }}
        files: |
          src-tauri/target/release/bundle/**/*
        fail_on_unmatched_files: false
```

### 3.6 `ci.yml`（普通 CI）

**不变**。`ci.yml` 在 push main + PR 上跑，不在 tag 上跑，与新分级无交集。

---

## 4. 升档判断脚本

### 4.1 脚本位置

`scripts/release/infer_tier.py`（新建，约 100-150 行）

### 4.2 CLI

```bash
python scripts/release/infer_tier.py \
  --since-tag v0.4.0-lts \
  --target-minor 0.5.0 \
  --milestone-closed "M1,M2" \
  --open-blockers 0
```

### 4.3 输出

```json
{
  "recommended_tier": "beta",
  "recommended_tag": "v0.5.0-beta.1",
  "confidence": "high",
  "reasons": [
    "main 上次 tag 为 v0.4.0-lts，距今 21 天",
    "累计 feat: 4 个 (>= 3 触发 beta)",
    "M1 milestone 已闭合",
    "当前 release-blocker issue: 0",
    "未检测到 BREAKING CHANGE，PATCH 保持 0"
  ],
  "next_action": "git tag v0.5.0-beta.1 -m '...' && git push origin v0.5.0-beta.1"
}
```

### 4.4 推断规则

| 检查项 | 数据源 | 阈值 |
|--------|--------|------|
| 自上次 tag 以来 `feat:` 数 | `git log <last_tag>..HEAD --grep='^feat'` | α→β: ≥3, β→rc: ≥6 |
| 自上次 tag 以来 `BREAKING CHANGE` body | `git log <last_tag>..HEAD --grep='BREAKING CHANGE'` | 任一存在 → MAJOR+1 |
| 自上次 tag 以来 `fix:` 数 | `git log <last_tag>..HEAD --grep='^fix'` | 仅在稳定后影响 PATCH |
| Milestone 闭合数 | `--milestone-closed` CLI 参数；判定标准：GitHub milestone `state=closed` 且 `due_on` 已过 | α→β: ≥1, β→rc: ≥2, rc→stable: ≥3 |
| Release blocker issue 数 | `--open-blockers` CLI 参数 | rc→stable: == 0 |
| 上次 tag 是否同 MINOR | `git tag --list 'v0.X.Y-*'` | 是 → 段内计数 +1；否 → 重置 |

### 4.5 段内计数重置

```python
def next_tag(current_minor: str, tier: str, current_tier_counters: dict) -> str:
    counter = current_tier_counters.get(tier, 0) + 1
    return f"v{current_minor}-{tier}.{counter}"
```

例：当前 main tags = `[v0.5.0-alpha.1, v0.5.0-alpha.2, v0.5.0-beta.1]`，
推断 `beta` → 下一个 = `v0.5.0-beta.2`。

### 4.6 不做的事

- ❌ 不在 CI 里自动打 tag（PR review + 人工确认更稳）
- ❌ 不修改 git tag 本身（脚本只推荐）
- ❌ 不写 semver 解析库依赖（用 Python `packaging.version.Version` 已自带）
- ❌ 不读 GitHub API（避免 secret 管理复杂化）

---

## 5. CHANGELOG 模板更新

### 5.1 顶部档位说明块

在 `CHANGELOG.md` 顶部加：

```markdown
## Release Tier Definitions

| Tier | Tag Format | Audience | Channel |
|------|-----------|----------|---------|
| **alpha** | `vX.Y.Z-alpha.N` | Sage contributors only | GitHub Releases (prerelease) |
| **beta** | `vX.Y.Z-beta.N` | Public beta testers | GitHub Releases (prerelease) |
| **rc / preview** | `vX.Y.Z-rc.N` | Broad testing, recommended for early adopters | GitHub Releases (prerelease) |
| **stable** | `vX.Y.Z` | All users | GitHub Releases (latest) |

Win7 LTS adds `-lts` suffix after tier (e.g. `vX.Y.Z-beta.N-lts`).
```

### 5.2 新增段落格式（同一 MINOR 内多档聚合）

按"最新档在上"排列，同一 MINOR 内的 alpha/beta/rc 段独立，stable 段在最后：

```markdown
## [Unreleased]

## [v0.5.0-beta.1] - 2026-07-08

### Added
- feat(permission): 路径守卫 + fail-closed + PermissionPreset (#102)

### Changed
- refactor(event): schema-versioned event envelope (#100)

### Fixed
- fix(limits): 工具中心超时/截断预算守卫 (#101)

### Known Issues
- feat-tool-policy config UI 暂未迁移，新配置需手动编辑 backend/config.yaml
- 🔗 Milestone: https://github.com/oneMuggle/sage/milestone/3

## [v0.5.0-alpha.2] - 2026-07-05

### Added
- feat(observability): event envelope schema v1 (#100)

### Fixed
- fix(electron): TDZ bug in logger import (post-merge smoke test only)

### Known Issues
- M2 工具中心预算守卫尚未合并

## [v0.5.0-alpha.1] - 2026-07-03

### Added
- feat(event): initial schema-versioned envelope RFC

## [v0.4.2-lts] - 2026-07-04
... (现有 stable 段，原样保留)
```

### 5.3 Known Issues 段规则

- 仅 alpha/beta/rc 段加 `### Known Issues`，stable 段不放
- 每条 issue 必须对应 GitHub issue（`#NNN` 引用）
- 脚注链接到 milestone 看板

### 5.4 模板生成器

`scripts/release/append_changelog.py`：

```bash
python scripts/release/append_changelog.py \
  --tier beta \
  --tag v0.5.0-beta.1 \
  --date 2026-07-08 \
  --milestone "M1,M2,M3" \
  --known-issues "issue/123,issue/456"
```

输入：`git log <last_tag>..HEAD --pretty='%s'` 解析 conventional commits，按 type 分到 `### Added/Changed/Fixed/Removed` 节。
输出：新段落插入到 `[Unreleased]` 之后、最新版本段之前。

### 5.5 `[Unreleased]` 段规则

- 永远保留空段
- 当下面准备写新档位时，先把 `[Unreleased]` 清空为标题
- stable release 完成后，下一个 MINOR 的首个 commit 重新填

### 5.6 LTS 段独立分组

win7 LTS 段单独写，不与 main 同 MINOR 合并：

```markdown
## [v0.5.0-beta.1] - 2026-07-08  (main 公测)
... (main 公测)

## [v0.5.0-beta.1-lts] - 2026-07-22  (Win7 LTS 公测)
... (从 main cherry-pick 后)
```

---

## 6. 文档同步

### 6.1 改动清单

| 文档 | 改动 |
|------|------|
| `docs/technical/21-win7-lts.md` | §9 后新增 §9.1 预发布段映射 + §9.2 升档脚本使用 |
| `docs/technical/26-packaging-matrix.md` | 新增 §3 预发布构建矩阵 |
| `docs/technical/30-release-tiers.md` | **新建**：专门描述 4 档分级系统 |
| `README.md` | §"双轨发布" 表格加 pre-release 行 |
| `docs/user-manual/01-desktop.md` | 新增 §1.3 预发布渠道与安装风险说明 |
| `CHANGELOG.md` | 顶部加档位说明块 + 段落格式更新 |

### 6.2 `21-win7-lts.md` §9.1 扩展示例

```markdown
### §9.1 Pre-release tier mapping (Win7 LTS)

Win7 LTS 跟随 main 进入预发布段，每个段位延迟 1-2 周让 main soak：

| main tag | win7 LTS tag | 间隔 |
|----------|--------------|------|
| `v0.5.0-alpha.1` | 不跟随 | - |
| `v0.5.0-beta.1` | `v0.5.0-beta.1-lts` (2 周后) | main soak 2 周 |
| `v0.5.0-rc.1` | `v0.5.0-rc.1-lts` (1 周后) | main soak 1 周 |
| `v0.5.0` | `v0.5.0-lts` (同日) | cherry-pick 完成后立即 |

**不允许** win7 单独定义预发布段。Win7 特有修复走 hotfix patch (`v0.5.1-lts`)。
```

### 6.3 `30-release-tiers.md` 新建文档结构

```markdown
# §30 Release Tiers

## 30.1 概述
Sage 采用 4 档发布分级 + SemVer 预发布段 + 双分支 LTS 派生。

## 30.2 档位定义
（链接到 §21 §9.1 + §26 §3）

## 30.3 升档流程
1. 在 main 分支确认 CI 全绿
2. 跑 `scripts/release/infer_tier.py` 看推荐档位
3. 跑 `scripts/release/append_changelog.py` 更新 CHANGELOG
4. 人工 review 后 `git tag` + `git push`
5. CI 自动构建 + 标记 prerelease

## 30.4 win7 LTS 派生
（链接到 §21 §9.1）
```

### 6.4 `01-desktop.md` §1.3 用户向章节

```markdown
### §1.3 选择合适的安装版本

Sage 提供 4 个发布档位，根据风险偏好选择：

| 档位 | 适合谁 | 风险 | 更新频率 |
|------|--------|------|----------|
| **Stable** (推荐) | 所有用户 | 低 | main milestone 闭合时 |
| **RC / Preview** | 早期采用者 | 中 | RC 阶段 |
| **Beta** | 测试贡献者 | 中高 | beta 阶段 |
| **Alpha** | Sage 贡献者 | 高 | merge 后即发 |

**怎么装预发布版？**

1. 访问 [Sage Releases](https://github.com/oneMuggle/sage/releases)
2. 点击 "Tags" 或筛选 "Pre-release"
3. 下载对应档位的 installer
4. ⚠️ 预发布版可能含已知 bug，重要数据请先备份

**怎么回滚到 Stable？**

下载最新 stable installer 覆盖安装即可。数据/配置保留在 `~/.config/sage/`。
```

---

## 7. 回滚与故障处理

### 7.1 错档位（误打高/低档）

**处理**：
```bash
git tag -d v0.5.0
git push origin :refs/tags/v0.5.0
gh release delete v0.5.0 --yes
git tag -a v0.5.0-beta.1 -m "..."
git push origin v0.5.0-beta.1
```

**预防**：`infer_tier.py` 加 `--dry-run` 模式，人工 review 输出后再实际打 tag。

### 7.2 漏档（跳过 beta 直接打 stable）

**禁止回填** beta tag。规范要求所有 stable 之前必须有 ≥1 个 beta 和 ≥1 个 rc tag。

**预防**：
- `infer_tier.py` 检测：若上一个同 MINOR tag 是 alpha 或 beta 且时间 < 7 天，建议继续该档位
- 在 release body 加警告 banner

### 7.3 Cache 冲突

已在 §3.2 通过 cache key 命名空间隔离解决。

### 7.4 LTS 段内 hotfix

```bash
# 在 release/win7 开 fix 分支
git switch -c fix/win7-critical-bug release/win7
git cherry-pick <commit-sha>
# 打 hotfix tag（不走预发布段）
git tag -a v0.4.3-lts -m "v0.4.3-lts — win7 critical bug fix"
git push origin v0.4.3-lts
# 同步回 main
git switch main
git cherry-pick <commit-sha>
```

### 7.5 Release Blocker 升级

```bash
# 在 main 开 hotfix 分支
git switch -c hotfix/v0.5.1 main
# 修复 + 打 stable tag
git tag -a v0.5.1 -m "v0.5.1 — fix release-blocker #NNN"
git push origin v0.5.1
# 在原 v0.5.0 release 贴警告 banner
gh release edit v0.5.0 --notes "$(cat warning-banner.md)"
```

### 7.6 脚本 ambiguous

脚本输出 `confidence: "low"` 时列出原因，人工裁决（看 milestone 看板 + release-blocker issue + 与上次发布者沟通）。

### 7.7 预发布误标为非 prerelease

**处理**：
```bash
gh release edit v0.5.0-beta.1 --prerelease
gh release edit v0.5.0-beta.1 --notes "$(cat warning-banner.md)"
```

**预防**：`prerelease` 字段由 workflow 自动判断（§3.1），非人工。CI 监控 cron job 每 6 小时扫描，发现异常自动校正。

### 7.8 CI 部分失败

现有逻辑已处理（`fail_on_unmatched_files: false` + `draft: true`）。人工 review draft release 决定 publish/重打。

### 7.9 失败处理决策表

| 失败类型 | 自动 | 人工 |
|----------|------|------|
| 错档位 | ❌ | ✅ 删 tag 重打 |
| 漏档 | ❌ | ✅ review |
| Cache 冲突 | ✅ key 隔离 | 仅排查 |
| LTS hotfix | ❌ | ✅ cherry-pick |
| Release blocker | ❌ | ✅ hotfix 分支 |
| 脚本 ambiguous | 输出 low confidence | ✅ 人工裁决 |
| 误标非 prerelease | ✅ cron 校正 | ✅ 发警告 banner |
| CI 部分失败 | ✅ draft + 部分上传 | ✅ 决定 publish/重打 |

---

## 8. 实施步骤

### Phase 1: 基础设施（独立 PR）

- [ ] 写 `scripts/release/infer_tier.py`（含 dry-run + 单元测试）
- [ ] 写 `scripts/release/append_changelog.py`（含已知段落合并测试）
- [ ] 写 `scripts/release/determine_artifact_suffix.sh`（workflow 调用的 bash 脚本）
- [ ] `release.yml` 加 prerelease 字段 + cache key 改写 + suffix 步骤
- [ ] `release-win7.yml` 同步加 prerelease 字段 + cache key 改写 + suffix 步骤
- [ ] CI 全绿验证（不打 tag，只验证 workflow YAML 语法）

### Phase 2: 文档同步（独立 PR）

- [ ] 新建 `docs/technical/30-release-tiers.md`
- [ ] 更新 `docs/technical/21-win7-lts.md` §9.1 + §9.2
- [ ] 更新 `docs/technical/26-packaging-matrix.md` §3
- [ ] 更新 `README.md` "双轨发布" 表格
- [ ] 更新 `docs/user-manual/01-desktop.md` §1.3
- [ ] 更新 `CHANGELOG.md` 顶部档位说明块
- [ ] 更新 `docs/technical/README.md` 总览章节目录（加 30 章节）

### Phase 3: 实战演练（独立 PR，dry-run）

- [ ] 在 main 上跑 `infer_tier.py --dry-run`，记录输出
- [ ] 人工 review 输出，确认推荐档位合理
- [ ] **不打 tag**，仅生成 changelog 草稿确认格式正确

### Phase 4: 首次实战（独立 PR）

- [ ] 在 main 上打首个 alpha tag（基于 §3 推断的 v0.5.0-alpha.1）
- [ ] CI 构建 + draft release
- [ ] 人工 review draft release body
- [ ] publish
- [ ] 验证 cache key + prerelease 标记 + artifact name 正确

### Phase 5: win7 LTS 派生（1-2 周后）

- [ ] 在 release/win7 cherry-pick main 的 alpha → beta 阶段 commits
- [ ] 打首个 win7 LTS beta tag (`v0.5.0-beta.1-lts`)
- [ ] CI 构建 + draft release
- [ ] publish

### Phase 6: 监控与反馈（持续）

- [ ] 监控预发布渠道 issue 反馈
- [ ] 调整档位阈值（如发现 alpha 阶段 bug 太多，可提高 β 阈值）
- [ ] 更新本文档附录（实战数据）

---

## 9. 风险与依赖

### 9.1 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 用户误装 alpha 当 stable | 高 | prerelease 标记 + release body 大字警告 + 文档 §1.3 |
| 升档脚本误判 | 中 | dry-run + 人工 review + ambiguous 输出 |
| Cache 冲突导致构建污染 | 中 | 已用命名空间隔离 |
| LTS 派生周期过长 → 用户等不及 | 低 | 文档明确 1-2 周间隔 + 提供 main 公测版作为临时替代 |
| win7 LTS 用户不愿装预发布 | 低 | LTS 默认只发 stable，预发布是可选 |

### 9.2 依赖

- Python 3.11（与 main 一致）
- `packaging` 库（项目已有 pyproject.toml 依赖）
- Bash 4+（CI 环境 ubuntu-latest 默认 5+）
- GitHub Actions 现有服务（无新依赖）

### 9.3 兼容性

- ✅ 所有现有 `v0.1.0 - v0.4.2-lts` tag 仍识别为 stable
- ✅ 无 breaking change 现有用户
- ✅ win7 LTS 分支不受 main 流程干扰
- ✅ CHANGELOG 顶部加块不破坏现有段落（向后兼容 append-only）

---

## 10. 验收标准

- [ ] Phase 1: 三个脚本在 CI 中 `python -m pytest` 全过；两个 workflow YAML `actionlint` 通过
- [ ] Phase 2: 文档 lint 无警告；`mkdocs build`（如有）通过
- [ ] Phase 3: dry-run 输出 JSON 格式正确，档位推断与人工判断一致
- [ ] Phase 4: 首个 alpha tag 在 24h 内成功 publish，预发布标记正确，artifact name 包含 `-alpha`
- [ ] Phase 5: win7 LTS 派生 tag 在 main 间隔 1-2 周后成功 publish
- [ ] Phase 6: 1 个月内收到 ≥3 条预发布反馈 issue，档位阈值根据反馈微调

---

## 附录 A：参考示例（首个实战预期输出）

### A.1 首个 alpha tag 的 release body

```markdown
## 🧪 Sage v0.5.0-alpha.1

> **This is an ALPHA release.**
> ⚠️ 仅供 Sage 贡献者使用，可能含已知 bug。不推荐普通用户安装。

### What's New

This is the first alpha for v0.5.0. Includes:

- feat(observability): schema-versioned event envelope (#100)
- feat(limits): ToolPolicy explicit limits (#101)
- feat(permission): path guard + fail-closed (#102)

### Known Issues

- #123 Tool policy config UI not migrated — edit backend/config.yaml manually
- #456 Electron logging TDZ bug on Windows startup (smoke test only)

🔗 Milestone: https://github.com/oneMuggle/sage/milestone/3

### Downloads

| File | Notes |
| --- | --- |
| `Sage-Setup-0.5.0-alpha.exe` | Windows NSIS, Win10+ |
| `sage_0.5.0_amd64.deb` | Debian / Ubuntu |
| `Sage-0.5.0-alpha.AppImage` | Linux portable |
```

### A.2 推断脚本示例输出

```bash
$ python scripts/release/infer_tier.py \
    --since-tag v0.4.0-lts \
    --target-minor 0.5.0 \
    --milestone-closed "M1,M2,M3" \
    --open-blockers 0

{
  "recommended_tier": "beta",
  "recommended_tag": "v0.5.0-beta.1",
  "confidence": "high",
  "reasons": [
    "上次 tag v0.4.0-lts 距今 28 天 (>= 7 天阈值)",
    "累计 feat: 4 个 (>= 3 触发 beta)",
    "M1/M2/M3 milestone 已闭合 (>= 1 触发 beta)",
    "release-blocker issue: 0",
    "未检测到 BREAKING CHANGE，PATCH 保持 0"
  ],
  "next_action": "git tag v0.5.0-beta.1 -m '...' && git push origin v0.5.0-beta.1"
}
```
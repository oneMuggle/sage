# 30. Release Tiers（发布档位分级）

> Sage 采用 **4 档发布分级 + SemVer 预发布段 + 双分支 LTS 派生** 系统，目标是给不同风险偏好的用户提供明确的升级路径。

**适用读者**：Sage 贡献者、Release 维护者、CI 维护者。

---

## 30.1 概述

Sage 自 v0.1.0 起所有 tag 都是"稳定版"语义，没有区分 alpha / beta / preview 渠道：

- 2 个月内发布 12 个 tag（M1-M9 多个 milestone 快速迭代）
- 每次 merge 后直接打 `v0.X.Y` 或 `v0.X.Y-lts`，无内部 soak 缓冲
- 用户只能"装或不装"，无法按风险偏好选择
- 快速迭代期暴露给全量用户，blocker bug 修复成本高
- README 仅承诺"双轨发布"，但缺失"预发布渠道"维度

引入 4 档分级后：

1. 快速迭代时给早期用户风险缓冲，避免每次 merge 即暴露全量
2. 严格遵循 SemVer 2.0 预发布段规范 (`alpha.N` / `beta.N` / `rc.N`)，npm/uv 等工具可识别
3. Win7 LTS 维护分支同步具备分级能力（`v0.5.0-beta.1-lts`）
4. 升档基于约定式提交与 milestone 闭合状态，可脚本化（不强制）

**4 档总览**：

| 档位 | 目标用户 | 风险等级 | 通道 |
|------|----------|----------|------|
| **alpha** | Sage 贡献者 | 高 | GitHub Releases `prerelease=true` |
| **beta** | 公开少量早期用户 | 中高 | GitHub Releases `prerelease=true` |
| **preview / RC** | 准稳定广泛推荐 | 中 | GitHub Releases `prerelease=true` |
| **stable** | 全量用户 | 低 | GitHub Releases (latest) |

---

## 30.2 档位定义

### Tag 格式

| 档位 | main 分支 | win7 LTS 分支 |
|------|-----------|---------------|
| alpha | `v0.5.0-alpha.1` | `v0.5.0-alpha.1-lts` |
| beta | `v0.5.0-beta.2` | `v0.5.0-beta.2-lts` |
| preview / RC | `v0.5.0-rc.1` | `v0.5.0-rc.1-lts` |
| stable | `v0.5.0` | `v0.5.0-lts` |

> `-lts` 后缀始终在 tier 之后，符合 SemVer 2.0 附录 B（多 pre-release identifier 用 `.` 分隔，`-` 仅作为第一个分隔符）。

### 段内数字递增规则

- 同一 `MAJOR.MINOR.PATCH` 内：`alpha.1 → alpha.2 → beta.1 → beta.2 → rc.1 → rc.2 → v0.5.0`
- 升档时数字重置从 1 开始（如 `beta.2` 后升 `rc`，下一个是 `rc.1`）
- 跨 MINOR：进入新的 `v0.6.0-*` 系列，计数清零
- PATCH 修复：仅 stable 后才有 `v0.5.1`（hotfix）；预发布段内不打 patch，bug 在当前段累积修复

### 升档触发（约定式提交推断）

| 触发条件 | 推断档位 |
|----------|----------|
| 首个 `feat:` merge 到 main，且未发过任何 `v0.X.Y-*` tag | **alpha.1** |
| 累计 ≥3 `feat:` 或首个完整 milestone (e.g. M1) 闭合 | **beta.1** |
| 累计 ≥6 `feat:` 或 ≥2 milestone 闭合 | **rc.1** |
| 所有 milestone 闭合 + 无 `release-blocker` issue | **stable** |
| `fix:` merge → 预发布段内数字 +1（`alpha.1` → `alpha.2`），不影响 stable | 段内 +1 |
| `BREAKING CHANGE:` body → MINOR 不够 → MAJOR+1，预发布段号不变 | MAJOR 升号 |
| `hotfix:` merge → 不走预发布段，直接 `v0.5.1` | PATCH 升号 |

### 跨章节参考

- Win7 LTS 预发布段映射：[`21-win7-lts.md` §9.1](./21-win7-lts.md)
- 预发布构建矩阵（artifact 后缀 / cache key 隔离）：[`26-packaging-matrix.md` §7](./26-packaging-matrix.md)

---

## 30.3 升档流程

### 标准流程

1. **CI 全绿**：在 main 分支确认 CI 全绿（`ci.yml` 的 4 个 job 全部 success）
2. **跑档位推断脚本**：
   ```bash
   python scripts/release/infer_tier.py \
     --since-tag v0.4.0-lts \
     --target-minor 0.5.0 \
     --milestone-closed "M1,M2" \
     --open-blockers 0
   ```
   脚本输出推荐档位、置信度、推断理由（参考 spec §4.3 的 JSON 输出格式）
3. **更新 CHANGELOG**：
   ```bash
   python scripts/release/append_changelog.py \
     --tier beta \
     --tag v0.5.0-beta.1 \
     --date 2026-07-08 \
     --milestone "M1,M2,M3" \
     --known-issues "issue/123,issue/456"
   ```
   脚本从 `git log <last_tag>..HEAD` 解析 conventional commits，按 type 分到 `### Added/Changed/Fixed/Removed` 节
4. **人工 review + 打 tag**：
   ```bash
   git tag -a v0.5.0-beta.1 -m "v0.5.0-beta.1 — M1/M2/M3 milestone close, 4 feat: accumulated"
   git push origin v0.5.0-beta.1
   ```
5. **CI 自动构建 + 标记 prerelease**：`release.yml` 检测 tag 含 `-beta`，自动设 `prerelease: true` + release body 警告 banner

### 升档判断速查

| 检查项 | 数据源 | 阈值 |
|--------|--------|------|
| 自上次 tag 以来 `feat:` 数 | `git log <last_tag>..HEAD --grep='^feat'` | α→β: ≥3, β→rc: ≥6 |
| 自上次 tag 以来 `BREAKING CHANGE` body | `git log <last_tag>..HEAD --grep='BREAKING CHANGE'` | 任一存在 → MAJOR+1 |
| 自上次 tag 以来 `fix:` 数 | `git log <last_tag>..HEAD --grep='^fix'` | 仅在稳定后影响 PATCH |
| Milestone 闭合数 | `--milestone-closed` CLI 参数；判定标准：GitHub milestone `state=closed` 且 `due_on` 已过 | α→β: ≥1, β→rc: ≥2, rc→stable: ≥3 |
| Release blocker issue 数 | `--open-blockers` CLI 参数 | rc→stable: == 0 |
| 上次 tag 是否同 MINOR | `git tag --list 'v0.X.Y-*'` | 是 → 段内计数 +1；否 → 重置 |

### 不做的事（YAGNI）

- ❌ 不引入 release-please / semantic-release 等外部工具
- ❌ 不创建独立 alpha/beta/rc 物理分支（仅 tag 区分）
- ❌ 不在 CI 里自动打 tag（始终人工确认）
- ❌ 不为预发布段做 in-app update channel（GitHub Releases 足够）
- ❌ 不让 Tauri 矩阵参与预发布（仅 stable 同步）

---

## 30.4 win7 LTS 派生

Win7 LTS 跟随 main 进入预发布段，每个段位延迟 1-2 周让 main soak：

| main tag | win7 LTS tag | 间隔 |
|----------|--------------|------|
| `v0.5.0-alpha.1` | 不跟随 | - |
| `v0.5.0-beta.1` | `v0.5.0-beta.1-lts`（2 周后） | main soak 2 周 |
| `v0.5.0-rc.1` | `v0.5.0-rc.1-lts`（1 周后） | main soak 1 周 |
| `v0.5.0` | `v0.5.0-lts`（同日） | cherry-pick 完成后立即 |

**核心约束**：

- **不允许** win7 单独定义预发布段。Win7 特有修复走 hotfix patch (`v0.5.1-lts`)。
- win7 LTS 的预发布 tag **必须**从 main 的对应 tag cherry-pick 后打，不允许直接基于旧 LTS tag 升档
- 例：main 发 `v0.5.0-beta.2`，2 周 soak 后 win7 才打 `v0.5.0-beta.2-lts`
- 例外：纯 win7 修复可打 `v0.4.3-lts` patch（`v0.4.2-lts → v0.4.3-lts`），不走预发布段
- alpha 阶段 win7 LTS 不跟随（alpha 仅供贡献者，win7 用户无 alpha 需求）
- beta/rc/stable 跟随，间隔 1-2 周

详细流程与失败处理：[`21-win7-lts.md` §9.1](./21-win7-lts.md)。

---

## 30.5 相关文档

- 设计规范：[`docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md`](../superpowers/specs/2026-07-06-sage-release-tiers-design.md)
- Win7 LTS 维护与 Release 工作流：[`21-win7-lts.md`](./21-win7-lts.md)
- 跨平台打包矩阵与预发布构建矩阵：[`26-packaging-matrix.md`](./26-packaging-matrix.md)
- Electron 21 桌面壳：[`20-electron.md`](./20-electron.md)
- CI 工作流：[`.github/workflows/release.yml`](../../.github/workflows/release.yml) + [`release-win7.yml`](../../.github/workflows/release-win7.yml)
- 升档脚本：`scripts/release/infer_tier.py`
- CHANGELOG 模板：`scripts/release/append_changelog.py`
- Artifact 后缀判定：`scripts/release/determine_artifact_suffix.sh`

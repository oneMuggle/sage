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
| alpha | `v0.5.0-alpha.1` | `v0.5.0-alpha.1-win7` |
| beta | `v0.5.0-beta.2` | `v0.5.0-beta.2-win7` |
| preview / RC | `v0.5.0-rc.1` | `v0.5.0-rc.1-win7` |
| stable | `v0.5.0` | `v0.5.0-win7` |

> `-win7` 后缀始终在 tier 之后（stable 段直接加在版本号后），标识该 tag 是 Win7 LTS 维护分支的 release 产物。
>
> **SemVer 影响**：pre-release identifier 按 ASCII 字典序比较（`1 < win7`），所以 `v0.5.0-alpha.1-win7` 优先级**低于** `v0.5.0-alpha.1`（实际上 main 和 win7 不会互相比较优先级，因为它们是分 branch 维护的独立发布线）。npm/uv 等依赖 SemVer 排序的工具不依赖跨 branch tag 比较，对实际发布流程无影响。
>
> **向后兼容**：之前发布的 `v0.2.0-lts` / `v0.2.1-lts` / `v0.3.0-lts` / `v0.4.0-lts` / `v0.4.1-lts` / `v0.4.2-lts` tag 仍保留（Git tag 不可改名）。新命名从 `v0.4.3-alpha.1-win7` 开始生效。CHANGELOG 段命名也同步：`## [v0.4.3-alpha.1-win7]` 而非 `## [v0.4.3-alpha.1]`。

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

- Win7 LTS 预发布段映射：[`31-win7-lts.md` §9.1](./31-win7-lts.md)
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

Win7 LTS 与 main 走**完全平行**的 4 档发布线，MAJOR.MINOR.PATCH 与 main 同步，tier 编号与 main 同步。win7 LTS 现在是独立的 4 档发布线（**不再**仅从 beta 阶段开始跟随 main）。

**Tag 同步矩阵**：

| main tag | win7 LTS tag | 间隔 | 备注 |
|----------|--------------|------|------|
| `v0.5.0-alpha.1` | `v0.5.0-alpha.1-win7` | **同日** | alpha 阶段 win7 LTS **也参与**（破除旧 §30.4 "alpha 不跟随" 条款） |
| `v0.5.0-beta.1` | `v0.5.0-beta.1-win7` | **1 周** | 缩短为 1 周（vs 旧 2 周）—— 留 soak 时间给平台特定 bug |
| `v0.5.0-rc.1` | `v0.5.0-rc.1-win7` | **同日** | rc 阶段已稳定，平台差异可快速 cherry-pick（vs 旧 1 周） |
| `v0.5.0` | `v0.5.0-win7` | **同日** | 不变 |

**核心约束**：

- win7 LTS 的 tag **必须**从 main 的对应 tag cherry-pick 后打（不能直接基于旧 win7 LTS tag 升档——避免版本号脱钩）
- **MAJOR.MINOR.PATCH 强同步**：win7 LTS 的 `X.Y.Z` 必须等于 main 的 `X.Y.Z`，tier 编号（alpha.1 / beta.2 / rc.1）也必须一致
- 例：main 发 `v0.5.0-beta.2` → 1 周后 win7 LTS 发 `v0.5.0-beta.2-win7`（cherry-pick beta.2 + win7 特定 commit）
- 例外：纯 win7 修复可打 hotfix patch（`v0.4.2-lts → v0.4.3-alpha.1-win7`，走 4 档而不是 hotfix，因为 win7 现在有完整 4 档）
- 4 档全 win7 参与，破除旧的 "alpha 阶段 win7 不跟随" 限制
- win7 LTS 与 main 同步策略简化为：alpha/rc/stable 同日，beta 1 周后

详细流程与失败处理：[`31-win7-lts.md` §9.1](./31-win7-lts.md)。

---

## 30.5 相关文档

- 设计规范：[`docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md`](../superpowers/specs/2026-07-06-sage-release-tiers-design.md)
- Win7 LTS 维护与 Release 工作流：[`31-win7-lts.md`](./31-win7-lts.md)
- 跨平台打包矩阵与预发布构建矩阵：[`26-packaging-matrix.md`](./26-packaging-matrix.md)
- Electron 21 桌面壳：[`20-electron.md`](./20-electron.md)
- CI 工作流：[`.github/workflows/release.yml`](../../.github/workflows/release.yml) + [`release-win7.yml`](../../.github/workflows/release-win7.yml)
- 升档脚本：`scripts/release/infer_tier.py`
- CHANGELOG 模板：`scripts/release/append_changelog.py`
- Artifact 后缀：**main 用 `electron-builder.yml` 字面量 `${version}`（无后缀），win7 LTS 用字面量 `${version}-win7`**（详见 PR #110）

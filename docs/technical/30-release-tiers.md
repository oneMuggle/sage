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
- Artifact 后缀：**main 用 `electron-builder.yml` 字面量 `${version}`（无后缀），win7 LTS 用字面量 `${version}-win7`**（详见 PR #110）

---

## 30.6 Release Branches

> 设计规范：[`docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md`](../superpowers/specs/2026-07-10-release-branch-strategy-design.md)

Sage 在 tag-only 4 档分级之上，新增 **3 个物理分支** 解决"稳定化期 main 继续加新功能不污染候选版本"的场景：

| 分支 | 角色 | 生命周期 | 谁能推 |
|------|------|---------|--------|
| `main` | 主开发线 | 永久 | 任何人通过 PR |
| `release/vX.Y.0` | 当前版本稳定化线 | **临时**，stable ship 后删除 | 仅通过 PR（label 限制） |
| `release/stable` | 下游消费镜像（main） | 永久 | 仅 release workflow（PAT） |
| `release/win7` | Win7 LTS 维护线 | 永久至 2027-12-13 | 仅 cherry-pick from main |
| `release/stable-win7` | Win7 LTS 下游消费镜像 | 永久 | 仅 release-win7 workflow（PAT） |

### 时间线：v0.5.0 完整 cycle

```text
T0   main ──────────────────────────────────────────────────────►
     │  feat: feat-A │ feat-B │ feat-C │ feat-D │ feat-E
     │
     ├─ v0.5.0-alpha.1 tag (T0+1d)        ← tag-only,不开分支
     ├─ v0.5.0-beta.1 tag (T0+5d)         ← tag-only,不开分支
     │
T1   ├─ v0.5.0-rc.1 tag (T0+10d)
     │   ├─ [自动化] git switch -c release/v0.5.0 v0.5.0-rc.1
     │   └─ 分支保护启用: 必须 fix:/hotfix: label
     │
T2   ├─ main 加 feat: → 后续 v0.6.0-alpha.1 (独立线,不污染)
     ├─ release/v0.5.0 加 fix: → v0.5.0-rc.2 (T1+3d)
     │
T3   ├─ release/v0.5.0 加 fix: → v0.5.0-rc.3 (T1+6d)
     │
T4   ├─ v0.5.0 tag 在 release/v0.5.0 上
     │   ├─ [自动化] git push <sha>:release/stable --force-with-lease
     │   ├─ [自动化] git checkout main && git merge --no-ff release/v0.5.0
     │   ├─ [自动化] git push origin main
     │   └─ [自动化] git push origin --delete release/v0.5.0
     │
T5   进入 v0.6.0 cycle: 再次从 v0.6.0-rc.1 开 release/v0.6.0
```

### 5 种 Commit 流转路径

| 路径 | 场景 | 操作 |
|------|------|------|
| **A** | main 加 feat: | PR → main (squash merge) |
| **B** | release/vX.Y.0 加 fix:（稳定化期主路径） | PR → release/vX.Y.0（label: fix:）+ cherry-pick 到 release/win7 + 段内升 tag |
| **C** | main 先合 fix:，需回 release/vX.Y.0 | `git cherry-pick <sha>` 到 release/vX.Y.0 后 push |
| **D** | release/vX.Y.0 先合 fix:，必须回 main | `git cherry-pick <sha>` 回 main（developer responsibility） |
| **E** | stable ship 收尾 | release.yml 触发 promote-stable + finalize |

详细命令：[`docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md` §4](../superpowers/specs/2026-07-10-release-branch-strategy-design.md#4-数据流5-种-commit-流转路径)

### 为什么 alpha/beta 不开分支

- **alpha**：仅给 Sage 贡献者用，不需要"在某版本上稳定化"的能力 → tag 够用
- **beta**：少量早期用户测试，但允许破坏性变更 → tag 够用
- **rc.1 起**：面向广泛用户的候选版，需"测试期 + 同时开发"的并行 → 开 release/vX.Y.0 物理分支承接

### YAGNI 边界

- ❌ 不开 `release/alpha`、`release/beta`、`release/rc` 镜像分支
- ❌ 不开 `release/vX.Y.0-win7`（release/win7 已充当 win7 自己的稳定化线）
- ❌ 不同时维护多个 `release/vX.Y.0`
- ❌ 不让用户自由 PR 到 `release/stable` / `release/stable-win7`

### 自动化脚本入口

- 分支创建 / 检测 rc.1：`scripts/release/release_branches.py create`
- stable 镜像同步：`scripts/release/release_branches.py promote-stable`
- 收尾清理（merge 回 main + 删分支）：`scripts/release/release_branches.py finalize`
- Cross-minor guard + 幂等保护 + 冲突检测均内置在脚本中
- 单元测试 18 个 + 集成测试 3 个位于 `scripts/release/tests/`

---

## 30.7 Branch Setup & Manual Smoke Test

### GitHub Settings 手动配置（首次部署）

> ⚠️ **必须在第一次合入 Task 4-5 PR 后立即配置**，否则 PR 检查无效。

**步骤 1：创建 SAGE_RELEASE_BOT_TOKEN secret**

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Generate new token：
   - Name: `SAGE_RELEASE_BOT_TOKEN`
   - Resource owner: `oneMuggle`
   - Repository access: Only select repositories → `sage`
   - Permissions: **Contents: Read and write**（仅此一项）
3. 复制 token，粘贴到 Sage repo → Settings → Secrets and variables → Actions → New repository secret
4. **不要**勾选 Allow access via workflows for fork PRs

**步骤 2：配置 `release/vX.Y.0` 分支保护**

1. Settings → Branches → Add branch protection rule
2. Branch name pattern: `release/v*`
3. 勾选：
   - ☑ Require a pull request before merging
   - ☑ Require approvals: 1
   - ☑ Dismiss stale pull request approvals when new commits are pushed
   - ☑ Require status checks to pass before merging
     - 搜并勾选: `Frontend TS` / `Electron build (ubuntu-latest)` / `Electron build (windows-latest)`
   - ☑ Require conversation resolution before merging
   - ☑ Do not allow force pushes
   - ☑ Do not allow deletions
4. **不**勾选：Require linear history (允许 merge commit)

**步骤 3：验证 label check 工作**

测试 PR：

```bash
git switch -c test/label-check main
echo "test" > /tmp/throwaway.txt  # 不要 commit, 此步仅演示
gh pr create --base main --title "test label check (will close)" --label "feat:" --body "this should NOT trigger label check (base is main)"
gh pr create --base release/v0.5.0 --title "test label check (will close)" --label "feat:" --body "this SHOULD trigger CI failure (base is release/v*, label is feat:)"
gh pr create --base release/v0.5.0 --title "test label check (will close)" --label "fix:" --body "this should PASS"
```

预期：

- 第 1 个 PR：pr-label-check job 不跑（base 是 main）✅
- 第 2 个 PR：pr-label-check job 红，提示加 `fix:` 或 `hotfix:` label
- 第 3 个 PR：pr-label-check job 绿

测试完关闭所有 test PR。

### 手动 Smoke Test（每次 release.yml 改动后必跑）

> 这是 release.yml 新 step 的验证流程，**首次合入 Task 4 PR 后必跑**。
> 触发的 step 由 `scripts/release/release_branches.py` 实现。

**前置**：

- fork 仓库（避免污染主仓库）
- fork 上配置 `SAGE_RELEASE_BOT_TOKEN`（指向 fork repo）
- 在 fork 上重跑 release.yml（push tag 触发）

**测试场景 1：rc.1 创建 release/vX.Y.0 分支**

```bash
# 1. 在 fork main 上做几个 commit, 打 v0.5.0-rc.1 tag
git tag v0.5.0-rc.1
git push origin v0.5.0-rc.1

# 2. 观察 Actions: release.yml run
#    - "Detect rc.1 and create stabilization branch" step 应绿
#    - exit code 应为 0
#    - 远端应出现 release/v0.5.0 分支, 指向 v0.5.0-rc.1 commit

# 3. 验证
git fetch origin
git ls-remote --heads origin release/v0.5.0  # 应有输出
git rev-parse release/v0.5.0  # 应等于 v0.5.0-rc.1 commit
```

**测试场景 2：fix 在 release/vX.Y.0 合入 + 升 rc.2**

```bash
# 1. 在 fork release/v0.5.0 上 PR fix:
git switch release/v0.5.0
echo "fix content" >> README.md
git commit -am "fix: smoke test bug"
git push origin release/v0.5.0

# 2. PR 应通过 label check (fix: label)
#    - 合并后 release/v0.5.0 HEAD 前进

# 3. 手动打 v0.5.0-rc.2 tag
git tag v0.5.0-rc.2
git push origin v0.5.0-rc.2

# 4. 验证 release.yml 不触发新 step (rc.1 only)
#    Actions 跑 build, 但 Detect rc.1 不应跑
```

**测试场景 3：stable ship 收尾**

```bash
# 1. 在 release/v0.5.0 上打 v0.5.0 tag
git tag v0.5.0
git push origin v0.5.0

# 2. 观察 Actions:
#    - "Promote release/stable mirror" 应绿 (调 scripts/release/release_branches.py promote-stable)
#    - "Finalize stabilization branch" 应绿 (调 scripts/release/release_branches.py finalize)
#    - exit code 0

# 3. 验证:
git fetch origin
git rev-parse origin/release/stable     # 应等于 v0.5.0 commit
git ls-remote --heads origin release/v0.5.0  # 应为空 (已删)
git log main --oneline -5              # main HEAD 应含 release/v0.5.0 的 fix commit
```

**测试场景 4：cross-minor guard**

```bash
# 1. 不走 finalize 流程, 直接在 main 上推进 + 打 v0.6.0-rc.1 + v0.6.0 tag
git switch main
echo "v0.6 features" >> README.md
git commit -am "feat: v0.6 features"
git push origin main
git tag v0.6.0
git push origin v0.6.0

# 2. 观察 Actions: finalize step 应红 (exit 2)
#    报错: "previous stabilization branch release/v0.5.0 still open"

# 3. 手动补救:
git switch release/v0.5.0
git tag v0.5.0
git push origin v0.5.0
# 等 release.yml 跑完 promote + finalize
# 再重试 v0.6.0 finalize
```

### 失败排查

| 现象 | 排查 |
|------|------|
| `Detect rc.1` step 报 "branch already exists" | 正常：幂等 skip，verify log 看到 "already exists, skipping" |
| `Promote stable` 报 exit 4 (diverged) | release/stable 被外部 push 覆盖，需人工 review + 决定保留哪侧 |
| `Finalize` 报 exit 2 (previous still open) | 上 cycle release/vX.Y.0 未 finalize，先打稳定 tag 走完流程 |
| `Finalize` 报 exit 3 (conflict) | merge 冲突，按 §5.4 应急路径人工解 |
| PR label check 红但 PR 有 `fix:` label | label 全名匹配：应是 `fix:` `fix(scope):` `hotfix:`，不是 `Fix` `bug` `Bug Fix` |

### 故障回滚

- **回滚脚本**：删除 `scripts/release/release_branches.py` 文件 + revert Task 1-2 commit → workflow step 调不到脚本会红（feature 分支）→ 简单
- **回滚 workflow**：删除 release.yml 新增的 3 个 step + release-win7.yml 新增的 1 个 step → 回到纯 tag-only 模式
- **回滚 label check**：删除 `.github/labeler.yml` + `pr-label-check.yml` → PR 不再被强制
- **回滚 GitHub Settings**：手动去分支保护配置页面改回

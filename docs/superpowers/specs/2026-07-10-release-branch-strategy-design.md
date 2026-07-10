# Sage Release Branch 策略（稳定化分支 + 下游消费镜像）

> **状态**: 草案 v1（待用户审阅）
> **日期**: 2026-07-10
> **作者**: Claude (brainstorming)
> **关联文档**:
> - [`docs/technical/30-release-tiers.md`](../technical/30-release-tiers.md) — 4 档 tag 分级（已有）
> - [`docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md`](2026-07-06-sage-release-tiers-design.md) — 上一份 spec（4 档 tag）
> - [`docs/technical/21-win7-lts.md`](../technical/21-win7-lts.md) §9 Win7 LTS 维护
> - [`docs/technical/26-packaging-matrix.md`](../technical/26-packaging-matrix.md) §7 artifact 矩阵
> - `.github/workflows/release.yml` + `.github/workflows/release-win7.yml`

---

## 1. 背景与目标

### 1.1 当前状态（问题）

Sage v0.1.0 起的发布模型是 **"2 分支（main + release/win7）+ tag-only 4 档"**：

- 任何 `vX.Y.Z-{alpha,beta,rc}.N` 都是 main 上的浮动 tag，没有专门的物理分支承接
- `docs/technical/30-release-tiers.md §30.3` YAGNI 条款明示："不创建独立 alpha/beta/rc 物理分支（仅 tag 区分）"

这个模型在"快速出 tag、用户自选升级时机"场景下工作良好，但**无法支撑以下关键场景**：

> **稳定化冲突**：当 `v0.5.0-rc.1` 进入测试期时，main 同时需要继续添加新功能（进入 `v0.6.0-alpha.1`）。
> - 若继续把 fix: 合到 main → main HEAD ≠ rc.1 commit → "在 rc.1 上测试修复"失去意义（用户装的 rc.1 不含后续 fix）
> - 若把 fix: 合到 release/win7（win7 LTS 当前稳定化线）→ main 的 win7 用户无法享用 fix
> - 把 fix: 合到 main 后再回打 tag → 污染 main、影响 v0.6.0-alpha.1 开发节奏

**核心缺陷**：tag 是只读的 ref，**不能在上面 commit**；tag-only 模型没有"承载某版本稳定化过程"的物理分支。

### 1.2 目标

在保留 tag-only 4 档模型（YAGNI）的前提下，**新增 3 个物理分支**：

1. **`release/vX.Y.0` 稳定化分支**：从首个 `vX.Y.0-rc.1` tag 开出，承载 vX.Y.0 版本的 fix: / hotfix: 工作，到 stable ship 后合并回 main 并删除。
2. **`release/stable` 下游消费镜像**（main 线）：始终指向 main 上的最新 stable tag commit，供 packaging、auto-update 等下游工具引用。
3. **`release/stable-win7` 下游消费镜像**（win7 LTS 线）：功能同 #2，但跟随 release/win7 的最新 stable tag（`vX.Y.Z-win7`）。

**预期收益**：

- ✅ **稳定化冲突解决**：main 加 feat:，fix: 走 release/vX.Y.0，两线并行不污染
- ✅ **下游工具跟 ref**：`git clone -b release/stable` 永远拿"已知可用"的代码
- ✅ **4 档分级完整闭环**：alpha/beta tag-only → rc.1 开稳定化分支 → stable ship 收尾
- ✅ **win7 LTS 不变**：release/win7 仍是 win7 的稳定化线，不引入新概念

### 1.3 不做的事（YAGNI）

- ❌ **不开** `release/alpha`、`release/beta`、`release/rc` 镜像分支（维持 §30.3 YAGNI）
- ❌ **不开** `release/vX.Y.0-win7`（release/win7 已充当 win7 自己的稳定化线）
- ❌ **不同时**维护多个 `release/vX.Y.0`（同一时间只能稳一个版本）
- ❌ **不让用户**自由 PR 到 `release/stable` / `release/stable-win7`（仅 release workflow 推）
- ❌ **不引入** release-please / semantic-release 等外部工具（沿用人工 review + tag 流程）
- ❌ **不自动化** cherry-pick 反向操作（fail-closed，冲突时人工解）
- ❌ **不监控** stale 分支（靠 finalize 跨 MINOR 守护兜底）

---

## 2. 分支模型

### 2.1 5 类分支（含生命周期）

| 分支 | 角色 | 生命周期 | 谁能推 | 谁能 PR |
|------|------|---------|--------|---------|
| `main` | 主开发线 | 永久 | 任何人通过 PR | ✅ |
| `release/vX.Y.0` | **当前版本稳定化线**（承载 vX.Y.0 的 fix: 工作） | **临时**，stable ship 后删除 | 仅通过 PR | ✅（label 限制） |
| `release/stable` | **下游消费镜像**（指向最新 stable tag） | 永久 | 仅 release workflow（PAT） | ❌ |
| `release/win7` | Win7 LTS 维护线 | 永久至 2027-12-13 | 仅 cherry-pick from main | ❌ |
| `release/stable-win7` | **Win7 LTS 下游消费镜像** | 永久 | 仅 release-win7 workflow（PAT） | ❌ |

### 2.2 时间线：v0.5.0 完整 cycle

```
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

### 2.3 与现有 4 档 tag 模型的关系

| 4 档阶段 | 物理分支状态 |
|----------|------------|
| alpha | tag-only（main 上浮动 tag），无 release/* 分支 |
| beta | tag-only，**仍不开** release/beta 分支 |
| rc.1 (首次进入 RC) | **首次创建** release/vX.Y.0 分支 |
| rc.2 / rc.3 / rc.N | 在 release/vX.Y.0 上迭代 tag，分支不删 |
| stable (ship 当下) | release/stable mirror 强制更新；release/vX.Y.0 合并回 main 后删除 |

**关键不变量**：

- main 的 HEAD 在 rc.1 之后 ≠ v0.5.0 的 commit（main 在前进新功能，release/vX.Y.0 在固定旧 commit 上加 fix）
- release/stable 永远指向"最新已发布 stable tag 的 commit"
- release/win7 与 main 完全脱钩，不参与本次设计的稳定化分支机制

---

## 3. 组件与 Workflow 改动

### 3.1 新文件：`scripts/release/release_branches.py`

负责 release 分支生命周期管理，被 release.yml / release-win7.yml 调用。

**子命令**：

```bash
# 创建 release/vX.Y.0 分支（从 tag 切出）
python scripts/release/release_branches.py create \
  --tier rc \
  --tag v0.5.0-rc.1 \
  --version 0.5.0

# stable tag 后: fast-forward release/stable mirror
python scripts/release/release_branches.py promote-stable \
  --tier stable \
  --tag v0.5.0

# stable ship 后: 合并 release/vX.Y.0 回 main 并删除
python scripts/release/release_branches.py finalize \
  --version 0.5.0 \
  --main-branch main

# win7 LTS 同 promote-stable
python scripts/release/release_branches.py promote-stable \
  --tier stable \
  --tag v0.5.0-win7 \
  --branch release/stable-win7
```

**幂等性矩阵**：

| 命令 | 重复调用 / 已达目标 | 行为 |
|------|---------------------|------|
| `create` | 分支已存在 | exit 0 + log "already exists at <sha>" |
| `promote-stable` | ref 已指向该 tag commit | exit 0 + log "already at target" |
| `finalize` | 分支已删除 | exit 0 + log "branch already gone" |

**错误码**：

| Exit code | 含义 |
|-----------|------|
| 0 | 成功 / 幂等 skip |
| 1 | 通用错误（git 命令失败等） |
| 2 | 跨 MINOR 守护：上一 cycle release/vX.Y.0 未 finalize |
| 3 | cherry-pick 冲突（finalize 合并回 main 时） |
| 4 | force-with-lease 检测到 remote ref diverged |
| 5 | finalize 时 main 已领先 vX.Y.0 之后的 commit |
| 6 | tag 格式非法 |

### 3.2 改动：`.github/workflows/release.yml`

**新增 3 个 step**（在已有 "Create GitHub release" step 之后）：

```yaml
- name: Detect rc.1 and create stabilization branch
  if: startsWith(github.ref, 'refs/tags/v') && endsWith(github.ref_name, '-rc.1') && !endsWith(github.ref_name, '-rc.1-win7')
  run: |
    VERSION=$(echo "${{ github.ref_name }}" | sed 's/-rc\.1$//' | sed 's/^v//')
    python scripts/release/release_branches.py create \
      --tier rc --tag ${{ github.ref_name }} --version $VERSION
  env:
    SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}

- name: Promote release/stable mirror on stable tag
  if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-') && !endsWith(github.ref_name, '-win7')
  run: |
    python scripts/release/release_branches.py promote-stable \
      --tier stable --tag ${{ github.ref_name }}
  env:
    SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}

- name: Finalize stabilization branch on stable ship
  if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-') && !endsWith(github.ref_name, '-win7')
  run: |
    VERSION=$(echo "${{ github.ref_name }}" | sed 's/^v//')
    python scripts/release/release_branches.py finalize \
      --version $VERSION --main-branch main
  env:
    SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}
```

**新增权限**：`permissions: contents: write`（已存在则不重复）。

**新增 Secret**：`SAGE_RELEASE_BOT_TOKEN`（专用 PAT，仅含 `repo` scope + 仅 push 到 `release/*` 分支的权限）。

### 3.3 改动：`.github/workflows/release-win7.yml`

**新增 1 个 step**：

```yaml
- name: Promote release/stable-win7 mirror
  if: startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-rc') && !contains(github.ref_name, '-beta') && !contains(github.ref_name, '-alpha') && endsWith(github.ref_name, '-win7')
  run: |
    python scripts/release/release_branches.py promote-stable \
      --tier stable --tag ${{ github.ref_name }} --branch release/stable-win7
  env:
    SAGE_RELEASE_BOT_TOKEN: ${{ secrets.SAGE_RELEASE_BOT_TOKEN }}
```

win7 LTS **不创建** `release/vX.Y.0-win7`，因为 release/win7 自己就是稳定化线。

### 3.4 新文件：`.github/labeler.yml`（PR label 强制）

```yaml
release-branch:
  - release/v*
  - release/stable
  - release/stable-win7

fix-or-hotfix-only:
  - release/v*
```

配套 PR check action：`.github/workflows/pr-label-check.yml` 在 PR 含 `release/v*` base 时，要求 label ∈ {`fix:`, `hotfix:`}，否则 CI 红。

### 3.5 分支保护规则（GitHub Settings，文档化）

| 分支 | 直推 | Squash merge | Merge commit | Required checks | Required labels |
|------|------|--------------|--------------|-----------------|-----------------|
| `main` | ❌ | ✅ | ✅ | Frontend TS / Electron build x2 / Electron smoke | — |
| `release/vX.Y.0` | ❌ | ❌ | ✅ | Frontend TS / Electron build x2 | `fix:` or `hotfix:` |
| `release/stable` | ❌（仅 PAT） | ❌ | ❌ | — | — |
| `release/win7` | ❌ | ❌ | ❌ | — | — |
| `release/stable-win7` | ❌（仅 PAT） | ❌ | ❌ | — | — |

---

## 4. 数据流：5 种 Commit 流转路径

### 路径 A：main 上加新功能（默认）

```
开发者 PR (feat: ...)
  → CI 通过 + branch protection 通过
  → merge squash 到 main
  → main HEAD 前进
  → 不影响 release/* 任一分支
  → 后续进入 v0.6.0 cycle
```

### 路径 B：release/vX.Y.0 上修 bug（稳定化期主路径）

```
开发者 PR (fix: ...) → release/vX.Y.0
  → CI 跑 label check: label ∈ {fix:, hotfix:} → pass
  → merge commit (no squash, 保留原 commit hash 便于反向 cherry-pick)
  → release/vX.Y.0 HEAD 前进
  → 用户手动跑 infer_tier.py → 推断段内 +1
  → 打 v0.5.0-rc.2 tag (仍在 release/vX.Y.0 上)
  → cherry-pick 该 fix commit 到 release/win7 → 打 v0.5.0-rc.2-win7 tag
```

### 路径 C：fix 在 main 先合，需要回 release/vX.Y.0

```
main 上 PR (fix: ...) merged (commit SHA = ABCDEF)
  → developer 跑:
      git fetch origin release/v0.5.0
      git switch release/v0.5.0
      git cherry-pick ABCDEF
      git push origin release/v0.5.0
  → 若冲突 → 走 §5.4 应急路径
  → tag 升档流程同路径 B
```

### 路径 D：fix 在 release/vX.Y.0 先合，必须回 main

```
PR (fix: ...) merged 到 release/v0.5.0 (commit SHA = 123456)
  → developer 立刻跑:
      git switch main
      git cherry-pick 123456
      git push origin main
  → 防止 release/vX.Y.0 finalize 时反向 merge 漏掉
  → 这是 developer responsibility,CI 不强制（fail-closed by design）
```

### 路径 E：stable ship 收尾

```
v0.5.0 tag push 到 origin
  → release.yml 触发 promote-stable step:
      python release_branches.py promote-stable --tag v0.5.0
        → git push origin <v0.5.0-commit>:release/stable --force-with-lease
  → release.yml 触发 finalize step:
      python release_branches.py finalize --version 0.5.0 --main-branch main
        → git fetch origin main
        → git switch main
        → git merge --no-ff release/v0.5.0 -m "Merge release/v0.5.0 (finalize)"
        → git push origin main
        → git push origin --delete release/v0.5.0
  → 收尾完成,进入下一 cycle
```

---

## 5. 错误处理与失败模式

### 5.1 Workflow 失败

| 失败位置 | 行为 |
|---------|------|
| `Detect rc.1` 中 `create` 失败 | workflow 红，不继续下游 step；用户看 log 修复 |
| `Promote stable mirror` 中 `promote-stable` 失败 | 同上 |
| `Finalize` 中 `merge --no-ff` 冲突 | exit 3 + 冲突文件清单到 stderr；workflow 红；**不自动解**，人工处理 |
| `Finalize` 中 `git push --delete release/vX.Y.0` 失败 | 主流程已完成（tag + merge + stable mirror），仅分支删除失败；warning log + 留待用户清理 |
| `force-with-lease` 检测到 release/stable 被第三方更新 | exit 4 + 报错 "remote ref diverged, manual review needed"；**不强制覆盖** |

### 5.2 脚本逻辑失败

| 场景 | 行为 |
|------|------|
| `create` 分支已存在 | exit 0 + log "already exists at <sha>"，幂等 |
| `promote-stable` ref 已指向目标 | exit 0 + log "already at target"，幂等 |
| `finalize` 分支已删除 | exit 0 + log "branch already gone"，幂等 |
| `finalize` 时 main 已有 vX.Y.0 之后的 commit（即未合并就跳版本号） | exit 5 + stderr "main is ahead of vX.Y.0, refusing finalize" |
| 跨 MINOR 时上 cycle `release/vX.Y.0` 未 finalize | exit 2 + 列出未关的 release/vX.Y.0 名称 |
| tag 不符合 `vX.Y.Z[-tier.N[-win7]]` 格式 | exit 6 + 提示合法格式 |

### 5.3 分支保护违规

| 场景 | 行为 |
|------|------|
| PR 到 release/vX.Y.0 缺 `fix:` / `hotfix:` label | CI 红（labeler.yml + pr-label-check.yml）+ 不可 merge |
| 直推 release/* 任一分支 | GitHub 拒绝 |
| PAT 泄露 | 通过 token rotation 流程处理（不属本次设计范围） |

### 5.4 Cherry-pick 冲突的应急路径

```bash
# 1. 看冲突
git status

# 2. 编辑冲突(语义冲突必须人工判断)
$EDITOR <conflicted-file>

# 3. 标记已解决
git add <resolved-files>

# 4. 继续 cherry-pick
git cherry-pick --continue

# 5. 推送
git push origin <target-branch>

# 6. 重跑 tier 推断 + tag
python scripts/release/infer_tier.py --since-tag v0.5.0-rc.1 --target-minor 0.5.0
git tag -a v0.5.0-rc.2 -m "..."
git push origin v0.5.0-rc.2
```

冲突解决**不**自动化：cherry-pick 冲突通常是语义冲突（同一行代码被两种意图改），自动解容易引入 bug。

### 5.5 win7 LTS 同步失败

```
场景: release.yml 在 main 打 v0.5.0 tag
      release-win7.yml 必须 cherry-pick + 打 v0.5.0-win7 tag

失败模式:
  - cherry-pick 到 release/win7 冲突
  - v0.5.0-win7 推送后 build 失败

行为:
  - release.yml 已在 main 推送 v0.5.0,无法回滚（用户已下载）
  - release-win7.yml fail → 标记 v0.5.0-win7 为 missing
  - 用户决定:
      a) 修冲突后单独补 v0.5.0-win7 (走 hotfix pattern)
      b) 跳过 win7 这一档 (win7 用户等下个 cycle)
  - 此逻辑已在 docs/technical/30-release-tiers.md §30.4 说明,本次不重复设计
```

---

## 6. 测试策略

### 6.1 单元测试：`tests/test_release_branches.py`（新增）

| 测试用例 | 验证点 |
|---------|--------|
| `test_create_creates_branch_at_tag` | `create --tier rc --tag v0.5.0-rc.1 --version 0.5.0` 后 release/v0.5.0 指向 v0.5.0-rc.1 commit |
| `test_create_is_idempotent_when_branch_exists` | 重复 create → exit 0，分支 ref 不变 |
| `test_create_rejects_malformed_tag` | tag 不是 `vX.Y.Z-tier.N` 格式 → exit 6 |
| `test_promote_stable_updates_ref` | `promote-stable --tag v0.5.0` 后 release/stable 指向 v0.5.0 commit |
| `test_promote_stable_is_idempotent` | 重复 promote 到同 tag → exit 0 |
| `test_promote_stable_force_lease_detection` | 模拟远端 ref 被改 → exit 4，不覆盖 |
| `test_finalize_merges_back_to_main_and_deletes_branch` | mock git 调用，验证顺序：merge --no-ff → push main → push --delete |
| `test_finalize_refuses_when_main_ahead` | main 有 v0.5.0 之后 commit → exit 5 |
| `test_finalize_is_idempotent_when_branch_gone` | 分支已删 → exit 0 |
| `test_cross_minor_guard_rejects_open_previous` | finalize v0.6.0 时 release/v0.5.0 仍存在 → exit 2 |
| `test_win7_promote_uses_release_stable_win7` | `--branch release/stable-win7` 时推到正确 ref |

**Mock 策略**：`subprocess.run` 用 `unittest.mock` mock 掉 git 调用，不依赖真实 git 仓库。**目标覆盖率 ≥ 90%**。

### 6.2 集成测试：`tests/integration/test_release_branch_lifecycle.py`（新增）

在 temp git 仓库跑真实 git 操作（`git init --bare` + `git clone`），跑完销毁。

```python
def test_full_lifecycle_alpha_to_stable():
    """完整 cycle: alpha → beta → rc.1 (建分支) → rc.2 (修 bug) → stable (收尾)"""
    # 1. temp git repo, 模拟 main
    # 2. 提交 feat-A, 打 v0.5.0-alpha.1 tag (不开分支)
    # 3. 提交 feat-B, 打 v0.5.0-beta.1 tag (不开分支)
    # 4. 提交 feat-C, 打 v0.5.0-rc.1 tag → create release/v0.5.0
    # 5. 开发者 A: main 加 feat-D (→ 后续 v0.6.0-alpha.1)
    # 6. 开发者 B: release/v0.5.0 加 fix-E, bump 到 v0.5.0-rc.2
    # 7. 断言: main HEAD ≠ release/v0.5.0 HEAD (两线独立)
    # 8. 开发者 C: release/v0.5.0 加 fix-F, bump 到 v0.5.0
    # 9. promote-stable + finalize:
    #    - release/stable 指向 v0.5.0
    #    - main 含 release/v0.5.0 全部 commit (含 fix-E, fix-F)
    #    - release/v0.5.0 已删除
    # 10. 全部断言通过

def test_cherry_pick_from_main_to_release_branch():
    """路径 C: fix 在 main 先合, cherry-pick 到 release/vX.Y.0"""
    # 1. 创建 release/v0.5.0
    # 2. main 上 commit fix: A
    # 3. 路径 C: cherry-pick A 到 release/v0.5.0
    # 4. 验证: release/v0.5.0 含 A 的修改

def test_cherry_pick_from_release_branch_to_main():
    """路径 D: fix 在 release/vX.Y.0 先合, 必须 cherry-pick 回 main"""
    # 1. 创建 release/v0.5.0
    # 2. release/v0.5.0 上 commit fix: B
    # 3. 路径 D: cherry-pick B 回 main
    # 4. 验证: main 含 B 的修改
```

**运行环境**：CI 时间预算 < 30s。

### 6.3 Workflow 测试：手动 + 文档化

`release.yml` / `release-win7.yml` 的新 step **不写自动化 workflow test**（GitHub Actions 自动化测试 ROI 低、flake 高）。

替代方案：

- **手动 smoke test 文档**：在 `docs/technical/30-release-tiers.md §30.7`（新增章节）写明"如何手动验证新 step 工作"，包括 dry-run checklist
- **PR-time 验证**：第一次合入时，作者在 PR description 附 manual test log
- **首个真 cycle 观察**：v0.5.0-rc.1 第一次在真实环境触发时，作者人工监督 workflow run，确认每 step OK

### 6.4 文档测试：链接 + 示例可执行性

`docs/technical/30-release-tiers.md` 新章节里所有 bash 示例必须可复制粘贴执行：

- 链接到真实脚本路径
- 不写伪命令（避免文档腐烂）
- CI 中加最小检查：`grep -c "scripts/release/release_branches.py" docs/technical/30-release-tiers.md` ≥ 1（防脱钩）

### 6.5 覆盖率目标

| 模块 | 目标 |
|------|------|
| `scripts/release/release_branches.py` | ≥ 90% |
| `scripts/release/infer_tier.py`（已有） | ≥ 80%（不变） |
| `scripts/release/append_changelog.py`（已有） | ≥ 80%（不变） |

---

## 7. 迁移与回滚

### 7.1 迁移步骤

1. **步骤 1**：合入 `scripts/release/release_branches.py` + 单元测试 + 集成测试（PR #1）
2. **步骤 2**：合入 `.github/workflows/release.yml` + `release-win7.yml` 改动 + `release.yml` PAT 配置（PR #2，依赖步骤 1）
3. **步骤 3**：合入 `.github/labeler.yml` + `.github/workflows/pr-label-check.yml`（PR #3，依赖步骤 2）
4. **步骤 4**：在 GitHub Settings 手动配置分支保护规则（文档化在 `docs/technical/30-release-tiers.md §30.7`）
5. **步骤 5**：更新 `docs/technical/30-release-tiers.md`，新增 §30.6（Release Branches）+ §30.7（Branch Setup & Manual Smoke Test）

**总 PR 数**：3 个 + 1 个 GitHub Settings 手动配置 + 1 个 docs 改动。

### 7.2 回滚

每个 PR 单独可回滚：

- 回滚 PR #1 → 脚本 + 测试移除，workflow 不引用 → 安全
- 回滚 PR #2 → workflow 移除新 step → release.yml 回到 v0.4.x 行为
- 回滚 PR #3 → PR label check 移除 → release/vX.Y.0 失去 label 强制（但分支保护仍可手动配置）

**唯一不可回滚的**：GitHub Settings 分支保护规则。误配置需手动去 Settings 改回。

### 7.3 兼容性

- **现存 tag 不影响**：`v0.2.0-lts` / `v0.4.0-lts` 等历史 tag 保留，release/stable mirror 首次运行时会指向"当前 main 上的最新 stable tag commit"
- **现存 release/win7 不影响**：本次设计不改 win7 LTS 工作流
- **PR 流程不变**：现有 feat: → main 的 PR 流程 100% 不变

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| `force-with-lease` 误覆盖 | release/stable 指向错误 commit | exit 4 立即 stop + 人工 review |
| PAT 泄露 | 攻击者可推 release/* 分支 | PAT 最小权限（仅 `repo`）+ 定期 rotate |
| cherry-pick 冲突频繁 | 稳定化期效率下降 | 不强制双向同步，main 上 commit 优先考虑稳定性 |
| 跨 MINOR 时上 cycle 忘 finalize | exit 2 阻塞下个 cycle | finalize 是 stable ship 的必须 step，不跳过 |
| GitHub branch protection 误配置 | 开发者卡死无法推 PR | 文档化配置步骤 + 手动 smoke test 验证 |
| `release/stable` 与 main HEAD 长期 diverged | 下游消费方装到旧代码 | release/stable 只指向 stable tag commit，不跟踪 main HEAD |

---

## 9. 开放问题与未来工作

**本次不解决，留待后续**：

1. **自动化反向 cherry-pick**：路径 D（fix 在 release/vX.Y.0 先合 → 必须回 main）当前是 developer responsibility。后续可加 workflow 自动检测 "release/vX.Y.0 has commits not in main" + 报警。
2. **多版本并行支持**：当前同一时间只稳一个版本（`release/vX.Y.0`）。如未来需要"v0.5.0 LTS + v0.6.0 同步开发"双稳定化线，需扩展支持。
3. **In-app update channel**：当前下游消费靠 `git clone -b release/stable`。未来可加 Tauri/Electron auto-update 检查 release/stable 的更新。
4. **可视化分支状态页**：当前分支拓扑靠 `git branch -a` 看。未来可加 GitHub Action 自动生成 mermaid 图嵌入 README。
5. **PR labeler 智能推断**：当前 developer 需手动加 `fix:` label。后续可加 bot 自动根据 commit message 推荐 label。

---

## 10. 验收清单

- [ ] `scripts/release/release_branches.py` 实现 create / promote-stable / finalize / win7 子命令
- [ ] 单元测试 `tests/test_release_branches.py` 覆盖 ≥ 90%
- [ ] 集成测试 `tests/integration/test_release_branch_lifecycle.py` 跑过 3 个核心场景
- [ ] `.github/workflows/release.yml` 新增 3 个 step 且通过 syntax check
- [ ] `.github/workflows/release-win7.yml` 新增 1 个 step 且通过 syntax check
- [ ] `.github/labeler.yml` + `.github/workflows/pr-label-check.yml` 配置完成
- [ ] GitHub Settings 配置 `release/vX.Y.0` 分支保护（含 required label）
- [ ] GitHub Secret `SAGE_RELEASE_BOT_TOKEN` 创建并配置最小权限
- [ ] `docs/technical/30-release-tiers.md` 新增 §30.6（Release Branches）+ §30.7（Branch Setup & Manual Smoke Test）
- [ ] 手动 smoke test：跑通一次 v0.5.0-rc.1 → v0.5.0 完整 cycle（可在 fork 仓库做）
- [ ] CI 全绿（main + release/win7 双侧）

---

## 11. 相关文档

- 设计规范（本文件）
- 上一份 spec：[`docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md`](2026-07-06-sage-release-tiers-design.md) — 4 档 tag 分级（已有）
- 技术手册：[`docs/technical/30-release-tiers.md`](../technical/30-release-tiers.md)（将新增 §30.6/§30.7）
- 技术手册：[`docs/technical/21-win7-lts.md`](../technical/21-win7-lts.md) §9 — Win7 LTS 维护（不变）
- 技术手册：[`docs/technical/26-packaging-matrix.md`](../technical/26-packaging-matrix.md) §7 — artifact 矩阵（不变）
- 脚本：`scripts/release/infer_tier.py`（已有）+ `append_changelog.py`（已有）+ `release_branches.py`（新增）
- Workflow：`.github/workflows/release.yml` + `.github/workflows/release-win7.yml`（改动）
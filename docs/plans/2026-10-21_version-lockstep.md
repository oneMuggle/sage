# 版本 lockstep 归位 + CI 闸门（P1）

- 日期：2026-10-21
- 分支：`chore/version-lockstep-20261021`（基于 `origin/main` @ `6c3c193d4`）
- 上游依据：`docs/technical/30-release-tiers.md` §30.3 / §30.4
- 关联：`docs/mcp-win7-main-alignment-plan.md` P1 阶段；PR #2232（P0 推送死锁）

## 1. 目标

把「main 与 release/win7 版本号强同步」这条**已经写在文档里、但没有被执行**的规则变成
可执行检查，并把当前已经发生的脱钩修回。

## 2. 现状（实测）

| 项 | main | release/win7 |
|---|---|---|
| `package.json` version | `0.4.9-alpha.63` | `0.4.9-alpha.64-win7` |
| CHANGELOG 顶端已发布段 | `v0.4.9-alpha.61`（缺 62 / 63） | `v0.4.9-alpha.62-win7`（缺 63 / 64） |
| 已发布 tag / Release | `v0.4.9-alpha.63` | `v0.4.9-alpha.64-win7` |

规则（§30.4）要求 win7 的 `X.Y.Z` 与 tier 编号必须与 main 一致。当前 **win7 领先一个 tier**：
`v0.4.9-alpha.64-win7` 已作为 GitHub Release 发布，而 main 从未有 `v0.4.9-alpha.64`。

成因是双轨手工 bump：两侧各自发 `chore(release): bump to vX` PR，某次 win7 侧多 bump 了一次
（win7 `#2176` bump 到 64-win7，main `#2177` 只到 63），之后没有任何检查发现。

## 3. 变更

### 3.1 版本归位（数据修复）

- `package.json`：`0.4.9-alpha.63` → **`0.4.9-alpha.64`**
- `CHANGELOG.md`：新增 `## [v0.4.9-alpha.64] - 2026-10-21` 段，如实说明「仅版本号对齐，无功能变更」

方向选择说明：**向 64 对齐，而不是把 win7 退回 63**。因为 `v0.4.9-alpha.64-win7` 已经作为
GitHub Release 发布，重新编号会与已发布的产物/tag 冲突（SemVer 与 tag 都不可回收）。

### 3.2 闸门（防再犯）

**`scripts/check_version_lockstep.py`**（仅标准库，py3.8 语法兼容，便于将来 cherry-pick 到 win7）

| 规则 | 级别 |
|---|---|
| win7 版本必须带 `-win7` 后缀；main 不得带 | 硬失败 |
| win7 去掉后缀后必须**逐字等于** main 版本 | 硬失败 |
| MAJOR.MINOR.PATCH 与 tier 编号一致（语义化拆分校验） | 硬失败 |
| 当前版本的 tag 配对（win7 已发而 main 未发，或反之） | 默认 warning，`--strict-tags` 可升为失败 |
| CHANGELOG 顶端两侧一致 / 与 package.json 一致 | 默认 warning，`--strict-changelog` 可升为失败 |

历史 tag **不做**强配对校验：仓库存在大量 `-lts` 旧命名与 win7 独有发布线，逐条告警只会变成噪音。
`--tags` 只报告「当前版本」的配对情况与 tag 总数。

用法：

```bash
python scripts/check_version_lockstep.py                       # HEAD vs origin/release/win7
python scripts/check_version_lockstep.py --main-ref worktree   # 提交前本地自检（读工作区）
python scripts/check_version_lockstep.py --tags --json          # 机器可读
```

退出码：`0` 一致 / `1` 漂移 / `2` 参数或环境错误。

**`.github/workflows/version-lockstep.yml`**

- 触发：改动 `package.json` / `CHANGELOG.md` / 脚本 / 本 workflow 的 PR；main push；手动
- `permissions: contents: read`（最小权限），无需写权限
- 按 §30.3 **只校验，不自动打 tag、不改版本**

## 4. 验证

| # | 检查 | 结果 |
|---|---|---|
| 1 | 改前跑脚本（HEAD 口径） | ❌ exit=1，精确指出 `alpha.63` vs `alpha.64` |
| 2 | 改后跑脚本（`--main-ref worktree`） | ✅ exit=0「版本 lockstep 校验通过」 |
| 3 | 反向验证：未提交时 HEAD 口径仍失败 | ✅ 证明检查不是空转 |
| 4 | workflow YAML 解析 | ✅（PyYAML） |
| 5 | 历史 tag 噪音 | ✅ 从 100+ 条 warning 收敛为 0 条 |

## 5. 已知遗留（不阻塞，需后续处理）

1. **main CHANGELOG 缺 `v0.4.9-alpha.62` / `v0.4.9-alpha.63` 两段**；win7 缺 `alpha.63-win7` /
   `alpha.64-win7`。这是发布说明撰写问题，需要按各自 Release Notes 补写，不应由我臆造。
   补齐后即可把 workflow 切到 `--strict-changelog`。
2. **win7 侧 CHANGELOG 顶端仍是 `alpha.62-win7`**，需要在 `release/win7` 上单独补 63/64 两段。
3. `v0.4.9-alpha.64` 的 tag 与 Release 仍需人工打（§30.3），本次不代劳。

## 6. 影响面与回滚

- 影响：`package.json`（一行版本号）、`CHANGELOG.md`（新增一段）、新增脚本与 workflow。
- 不改任何业务代码、不改依赖、不改 `release/win7`。
- 回滚：`git revert` 即可；即使保留检查脚本，也可通过 `--main-ref` 参数单独运行，无副作用。
- 风险：新增的 PR 检查会让「只 bump main 不 bump win7」的 PR 变红——这正是设计意图（§30.4 要求同批次完成）。

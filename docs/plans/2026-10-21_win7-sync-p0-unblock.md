# win7-sync P0：解开推送死锁 + parity 门禁分级

- 日期：2026-10-21
- 分支：`fix/win7-sync-p0-perms-20261021`（基于 `origin/main` @ `6c3c193d4`）
- 基线文档：`docs/win7-sync/parity.md`（2026-09-15 稳态 226 文件）、`docs/mcp-win7-main-alignment-plan.md`（对齐总方案）
- 变更文件：`.github/workflows/win7-sync.yml`（唯一）

## 1. 目标

让 `Win7 Sync` 流水线恢复「每晚真的能把 main 合进 release/win7 并开出 PR」，同时把长期钉红的门禁分成
「阻塞 / 非阻塞」两级，消除告警疲劳。

## 2. 根因（含一处更正）

### R1 推送死锁（真实原因）

定时运行日志（run `39508701927`，2026-10-20 03:30）：

```
! [remote rejected] HEAD -> sync/win7-main-20261020
  (refusing to allow a GitHub App to create or update workflow
   '.github/workflows/ci.yml' without 'workflows' permission)
error: failed to push some refs
```

`auto_sync.py` 的 merge、py38 回写、`check_py38_compat`、ruff 门禁**全部通过**，最后一步 push 被 GitHub 拒绝，
成果每晚被丢弃（近 8 次定时运行 8 次失败，`sync/*` 远端分支数为 0）。

> **更正**：此前建议「在 `permissions:` 里加 `workflows: write`」是**错误**的。
> `workflows` 不属于 GITHUB_TOKEN 的合法 permission 键（合法集合为 actions / attestations / checks /
> contents / deployments / discussions / id-token / issues / models / packages / pages / pull-requests /
> repository-projects / security-events / statuses）。写入非法键会让 GitHub 以
> `HTTP 422: failed to parse workflow ... Unexpected value 'workflows'` **拒绝解析整个文件**，
> 结果是定时任务与所有触发全部失效——比原来的 bug 更严重。
> 该权限只存在于 GitHub App / fine-grained PAT。因此唯一正解是**换推送凭据**。

### R2 门禁语义错位

`--fail-on main-only,real,win7-only` 让 parity job 在**每次 main push 上都必然失败**（漂移本来就存在），
而 sync job 只在 `schedule` / 手动时运行。红灯不代表新问题，也不驱动任何修复动作。

### R3 触发依赖单一时点

sync 只在 03:30 定时跑一次。一次失败就整整一天没有对齐动作，且没人看得到。

## 3. 变更清单

| # | 位置 | 变更 | 解决 |
|---|---|---|---|
| 1 | 头部注释 | 说明分级语义与推送凭据 | 文档一致性 |
| 2 | 头部注释 | 新增「推送凭据」段：解释为何不能靠 `permissions` 修 | 防止后人重踩 |
| 3 | `permissions:` | 加显式禁令注释（**不新增任何键**） | 防 422 |
| 4 | `concurrency` | `cancel-in-progress: false → true` | push 触发后旧运行自动折叠 |
| 5 | parity step | 移除 `--fail-on main-only,real,win7-only` | R2 |
| 6 | parity step | 改从 `parity-auto.json` 提取 `real` / `mainonly` / `win7only` / `unmerged` 四个 output | R2 |
| 7 | 两个 artifact 步骤 | 加 `if: always()` | 脚本异常时也留证据 |
| 8 | 门禁步骤 | 拆为 `Annotate non-blocking drift`（warning + job summary）与 `Fail on real drift`（硬失败） | R2 |
| 9 | sync `if:` | 增加 `github.event_name == 'push'` | R3 |
| 10 | sync checkout | `token: secrets.WIN7_SYNC_TOKEN != '' && ... \|\| github.token` | R1 |
| 11 | sync 新增步骤 | `Resolve push credential`：输出 `has_pat`，缺失时发 warning 说明后果 | R1（可观测） |
| 12 | sync 新增步骤 | `Keep workflow files untouched (no PAT)`：无 PAT 时把 `.github/workflows/**` 目录级回退到 `release/win7` | R1（降级路径） |
| 13 | rc=2 冲突分支 | 同样回退 `.github/workflows/**` 后再推 | R1（冲突路径同样会被拒） |

### 降级路径为什么必要

未配置 PAT 时，merge 出来的树会包含 main 上对 `.github/workflows/*` 的改动（例如 main 独有的
`audit-watch.yml`），push 必然被拒。降级动作是：把该目录整体还原为 `release/win7` 的版本再推送，
这样**代码合并照常落地**，只有 workflow 文件暂时不同步，并给出显式 warning。

实现上不能用 `git restore --source=<ref>`：它只还原源里存在的文件，**不会删除 main 新增的 workflow 文件**。
因此改为「先 `git rm -r --cached` 清空 index 条目，再 `git checkout <ref> -- 目录` 取回」，
确保新增文件也被排除在这次推送之外。

## 4. 需要人工完成的一步

在仓库 Secrets 中添加 `WIN7_SYNC_TOKEN`：

- 类型：fine-grained PAT（或 GitHub App installation token）
- 权限：**Contents: Read and write** + **Workflows: Read and write**
- 范围：仅 `oneMuggle/sage`
- 未配置时机器人不会死，但每次都会 warning 且 workflow 文件不同步。

> 注意：checkout 必须拿到这个 token（凭据写进 local git config，`git push` 用的是它），
> 只在 push 步骤里设 `GH_TOKEN` 是无效的。

## 5. 验收标准

| # | 检查 | 期望 |
|---|---|---|
| 1 | `python -c "import yaml; yaml.safe_load(open(...))"` | 解析成功 |
| 2 | `permissions` | 仍为 `contents: write` + `pull-requests: write`，**无 `workflows` 键** |
| 3 | `on` | `push` / `schedule` / `workflow_dispatch` |
| 4 | parity steps 顺序 | … → `Annotate non-blocking drift` → `Fail on real drift` |
| 5 | sync steps | 含 `Resolve push credential`、`Keep workflow files untouched (no PAT)` |
| 6 | 手动 `workflow_dispatch`（do_sync=true） | 能推出 `sync/win7-main-YYYYMMDD` 并开 PR/draft PR |
| 7 | 定时运行 | 不再出现 `refusing to allow a GitHub App ... without workflows permission` |
| 8 | 门禁 | `main-only` / `win7-only` 只出 warning；`real > 0` 才红 |

已验证 1–5（本 worktree 内，PyYAML 实测通过）；6–8 需合并到 main 后由真实运行确认。

## 6. 影响面与风险

- **影响**：仅 `.github/workflows/win7-sync.yml`；不触碰任何业务代码、`release/win7` 脚本、`parity-allow.txt`。
- **风险 A**：`real` 仍是硬失败。当前 `real = 483`，所以合并后 parity job **仍会红**。
  这是刻意保留的：它代表真实业务差异，需要按总方案 P3 逐域消化。区分点在于
  「红的原因现在只剩 real，不再是三类混在一起」。
- **风险 B**：push 触发后高频合并。`cancel-in-progress: true` 保证只保留最新一次；
  每次运行都从 `release/win7` 重建，结果幂等，取消安全。
- **风险 C**：无 PAT 时 workflow 文件长期不同步（已被 `parity-allow.txt` 的 real/intentional 覆盖）。
- **回滚**：`git revert` 本提交即可，或把 `concurrency` 改回 false、去掉 push 触发。
  单文件、无迁移、无需重跑数据。

## 7. 与总方案的关系

总方案 `docs/mcp-win7-main-alignment-plan.md` 的 P0 阶段。P0 只解「机器人能不能跑通」，
不改变漂移量（当前 parity：需动作 990 文件）。P1（版本 lockstep）、P2（按域批次 merge）、
P3（残差审计）在 P0 合并后再动，否则又是「人肉追平、机器人空转」的循环。
